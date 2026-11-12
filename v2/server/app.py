"""Web server: the support page, the text/voice API, and saved sessions.

    python -m v2.server            # http://localhost:8000

Endpoints
  POST /api/sessions                     start a session -> {id, greeting, audio}
  POST /api/sessions/{id}/message        {"text": "..."} -> agent reply
  POST /api/sessions/{id}/voice          raw 16 kHz 16-bit mono PCM body -> transcript + agent reply
  GET  /api/sessions/{id}                transcript + case file (also used for the human handoff)
  GET  /healthz
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import json
import os
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from v2.rove import speech
from v2.rove.agent import Agent

log = logging.getLogger("rove.server")
HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE.parent / "data" / "sessions"
MAX_SESSIONS = 500


class Session:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.agent = Agent()
        self.transcript: list[dict] = []
        self.created = time.time()
        self.lock = asyncio.Lock()

    def snapshot(self) -> dict:
        return {"id": self.id, "created": self.created, "transcript": self.transcript,
                "case": self.agent.case.to_dict(), "closed": self.agent.closed,
                "handoff": self.agent.case.handoff_summary()}

    def save(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        (SESSIONS_DIR / f"{self.id}.json").write_text(json.dumps(self.snapshot(), indent=1), encoding="utf-8")


class Message(BaseModel):
    text: str
    speak: bool = True


def create_app() -> FastAPI:
    app = FastAPI(title="Rove support agent v2")
    sessions: dict[str, Session] = {}

    def get(sid: str) -> Session:
        if sid not in sessions:
            raise HTTPException(404, "No such session. Start a new one.")
        return sessions[sid]

    def audio_b64(text: str, speak: bool) -> str | None:
        if not speak:
            return None
        try:
            return base64.b64encode(speech.synthesize(text)).decode()
        except Exception:
            return None  # text still works if speech is unavailable

    async def turn(s: Session, text: str, speak: bool, via: str) -> dict:
        if s.agent.closed:
            raise HTTPException(409, "This session was handed to a person. Start a new session for a new problem.")
        async with s.lock:
            try:
                reply = await asyncio.to_thread(s.agent.respond, text)
            except Exception:
                # Every model refused or the AI service is down. Say so plainly and keep the
                # session: the customer can retry the same message, and nothing was recorded.
                log.exception("agent turn failed")
                raise HTTPException(503, "The support assistant is temporarily unavailable. "
                                         "Please try again in a minute, or contact Rove support directly.")
            s.transcript += [{"role": "customer", "text": text, "via": via},
                             {"role": "agent", "text": reply.say, "action": reply.action,
                              "latency_s": reply.latency_s, "safety_notes": reply.safety_notes}]
            s.save()
        return {"say": reply.say, "action": reply.action, "latency_s": reply.latency_s,
                "case": s.agent.case.to_dict(), "closed": s.agent.closed,
                "audio": await asyncio.to_thread(audio_b64, reply.say, speak)}

    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True, "sessions": len(sessions)}

    @app.post("/api/sessions")
    async def start(speak: bool = True) -> dict:
        if len(sessions) >= MAX_SESSIONS:  # drop the oldest; they are saved on disk
            sessions.pop(min(sessions, key=lambda k: sessions[k].created))
        s = Session()
        sessions[s.id] = s
        greeting = s.agent.greeting()
        s.transcript.append({"role": "agent", "text": greeting})
        return {"id": s.id, "greeting": greeting, "audio": await asyncio.to_thread(audio_b64, greeting, speak)}

    @app.post("/api/sessions/{sid}/message")
    async def message(sid: str, body: Message) -> dict:
        if not body.text.strip():
            raise HTTPException(400, "Say or type something first.")
        return await turn(get(sid), body.text.strip(), body.speak, "text")

    @app.post("/api/sessions/{sid}/voice")
    async def voice(sid: str, request: Request) -> dict:
        s = get(sid)
        pcm = await request.body()
        if len(pcm) < speech.SAMPLE_RATE // 5:  # under ~0.1 s
            raise HTTPException(400, "That recording was too short. Hold the button while you speak.")
        text = await speech.transcribe_pcm(pcm)
        if not text:
            return {"transcript": "", "say": "Sorry, I didn't catch that. Could you say it again?", "action": "continue",
                    "case": s.agent.case.to_dict(), "closed": False, "audio": await asyncio.to_thread(
                        audio_b64, "Sorry, I didn't catch that. Could you say it again?", True)}
        return {"transcript": text, **await turn(s, text, True, "voice")}

    @app.get("/api/sessions/{sid}")
    def session(sid: str) -> dict:
        return get(sid).snapshot()

    @app.get("/api/livekit/token")
    def livekit_token(name: str = "Customer") -> dict:
        """A short-lived token for the browser to join its own room, where the voice agent answers."""
        try:
            from livekit import api
        except ImportError:
            raise HTTPException(503, "Live voice is not installed on this server.")
        key = os.environ.get("LIVEKIT_API_KEY", "devkey")
        secret = os.environ.get("LIVEKIT_API_SECRET", "secret")
        room = f"rove-{uuid.uuid4().hex[:10]}"
        token = (api.AccessToken(key, secret).with_identity(f"customer-{uuid.uuid4().hex[:6]}")
                 .with_name(name[:40] or "Customer").with_ttl(datetime.timedelta(hours=1))
                 .with_grants(api.VideoGrants(room_join=True, room=room)).to_jwt())
        return {"url": os.environ.get("LIVEKIT_PUBLIC_URL", os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")),
                "token": token, "room": room}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(HERE / "static" / "live.html")

    @app.get("/classic")
    def classic() -> FileResponse:
        return FileResponse(HERE / "static" / "index.html")

    return app


app = create_app()
