"""The server: one FastAPI process, one port (`docs/06` §9.1).

Four surfaces, and the split between them is the design rather than an
accident:

| Surface | Carries | Why there |
|---|---|---|
| `POST /api/session`, `POST /api/session/{room}/token` | The room, the identity and a short-lived join token (§1.4.2), and its renewal while the page stays open | The browser has to get its credential from somewhere, and that somewhere is not its own storage |
| `POST /api/offer`, `POST /api/ice` | WebRTC signalling, **fallback transport only** | The Pipecat peer connection lives in this process (`docs/07` D-02's documented fallback) |
| The media data channel | Speech segments, audio levels, ASR partials, endpoint decisions | Media-plane facts, produced by the media path, reported on the media path |
| `WS /ws` | Typed turns, the diagnostic state, the step, the transcript, trace events, and the browser's RTT/jitter/loss | Control plane. It survives a media drop, which is what lets the page keep rendering while the media link re-establishes |

The token is checked on every one of them. A page that has a room id but no
token can do nothing with it.

**Milestone 7.1 adds a fifth surface and leaves the four above alone.**
`server/support.py` mounts `/api/support/*`, `WS /ws/support` and the console
at `/support`, all of them behind a *separate* observer scope
(`docs/06` §5.3). The four caller surfaces are unchanged and, because
`tokens.verify` defaults to the caller scope, they refuse an observer token
without a line of this file being edited for it. That default is doing the
security work here, which is why it is a default and not a parameter every
call site passes.

**Two transports, one shape (`docs/07` D-02).** In `livekit` mode — the Phase 3
default — the mint issues a **LiveKit access token**, the browser joins a room
on the media server with it, and the agent worker joins the same room as a
participant (`server/livekit_agent.py`). The `/api/offer` and `/api/ice`
surfaces are then not used at all; they stay wired, and the Pipecat path behind
them stays tested, because D-02 keeps Pipecat as the fallback rather than as
dead code. `ROVE_TRANSPORT=smallwebrtc` is the whole of the flip.

**Where the two meet.** Whichever transport is running, a turn is one call to
:func:`run_turn` on *this* loop, behind the session's own lock. The LiveKit
worker's job runs on a different loop in this process, so it reaches that
function through :meth:`AppState.dispatch_turn` — which is the only crossing
there is, and is what makes §1.4.1's "a click, a typed string and a transcribed
utterance are the same event type" true in code rather than in a comment.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import dataclasses
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pipecat.transports.smallwebrtc.connection import IceServer
from pipecat.transports.smallwebrtc.request_handler import (
    ConnectionMode,
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from server import consent as consent_module

# Imported at module scope rather than where it is used: `livekit-agents`
# registers its plugins on import and refuses to do so off the main thread, so
# the import has to happen while the process is still being built rather than
# when the first job is dispatched onto a worker thread. See the note at the
# top of `server/livekit_agent.py`.
from server import ladder, latency, prefetch
from server import livekit_agent, livekit_tokens
from server import sdp as sdp_module
from server import tokens as token_module
from server import transcribe
from server.config import Settings
from server.core_bridge import (
    Session,
    SessionRegistry,
    fanout,
    TranscriptLine,
    run_typed_turn_async,
    session_snapshot,
)
from server.livekit_relay import register_livekit_relay
from server.pipeline import attach_media
from server.support import register_support_routes


class AppState:
    """Everything the process holds between requests.

    Also the one implementation of `server/livekit_agent.AgentHost`: three
    methods the worker is allowed to call, and nothing else. The narrowness is
    deliberate — the worker cannot reach into `agent/`, cannot touch a
    WebSocket, and cannot run a turn itself.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions = SessionRegistry(trace_dir=settings.trace_dir)
        self.webrtc = SmallWebRTCRequestHandler(
            ice_servers=[IceServer(urls=url) for url in settings.ice_servers] or None,
            connection_mode=ConnectionMode.MULTIPLE,
        )
        self.llm: Any = None
        self.worker: Any = None
        self.started_at = time.time()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fanout: asyncio.Queue[tuple[str, dict]] | None = None
        self._fanout_task: asyncio.Task | None = None

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._fanout = asyncio.Queue()
        self._fanout_task = asyncio.create_task(self._drain_fanout())
        # §2.2 lines 5, 6 and 8 are timed by wrappers round three `agent/`
        # module attributes, installed once for the life of the process. They
        # are a single `is None` test outside a measured turn, so this costs
        # nothing on a path that is not being measured.
        latency.install()
        if self.settings.use_llm:
            # Nova Micro / Nova Pro (`docs/07` D-06, D-07) — still TO VERIFY
            # under C-2, which is why the core treats the model as an advisor
            # that may fail at any moment and falls back to its rule-based
            # floor. Building the handle here costs nothing if it never works.
            try:
                from agent import llm as llm_module

                # `server/prefetch.py` names this file as `MemoLLM`'s
                # "documented injection point", and Milestone 6.2 shipped the
                # wrapper without ever installing it — so the speculative
                # `classify` on a partial and the turn's own `classify` on the
                # final were two Bedrock calls, and §2.1's "warms the LLM
                # prompt prefix" bought nothing. One memo, on one pure call
                # (`server/prefetch.py` says why `decide` must never be
                # memoised), and `agent/` is unchanged.
                self.llm = prefetch.MemoLLM(llm_module.BedrockLLM())
            except Exception:  # noqa: BLE001
                self.llm = None
        await self._ensure_vocabulary()
        await self._start_worker()

    async def _ensure_vocabulary(self) -> None:
        """Create or refresh the §3.4 biasing vocabulary. Non-fatal, by design.

        `server/transcribe.py` layer 1 is a quality lever, not a guarantee: a
        process that cannot create a custom vocabulary still gets a working
        recogniser, just an unbiased one. What must not happen is the agent
        asking Transcribe for a vocabulary that is not `READY` — the service
        rejects the whole stream for that — so a failure here *clears* the
        setting rather than leaving it hopefully set.
        """
        settings = self.settings
        if not (settings.is_livekit and settings.use_transcribe):
            return
        if not (settings.transcribe_vocabulary and settings.transcribe_ensure_vocabulary):
            return
        name = await asyncio.to_thread(
            transcribe.ensure_vocabulary,
            settings.transcribe_vocabulary,
            region=settings.transcribe_region or None,
        )
        if name != settings.transcribe_vocabulary:
            self.settings = dataclasses.replace(settings, transcribe_vocabulary=name)

    async def _start_worker(self) -> None:
        """Bring up the LiveKit agent worker, if this process owns one."""
        settings = self.settings
        if not (settings.is_livekit and settings.livekit_worker_inprocess):
            return
        self.worker = livekit_agent.AgentWorker(host=self)
        await self.worker.start()

    async def stop(self) -> None:
        if self.worker is not None:
            with contextlib.suppress(Exception):
                await self.worker.stop()
            self.worker = None
        if self._fanout_task is not None:
            self._fanout_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._fanout_task
        for room in self.sessions.rooms():
            session = self.sessions.get(room)
            if session is not None and session.media is not None:
                with contextlib.suppress(Exception):
                    await session.media.stop()
        with contextlib.suppress(Exception):
            await self.webrtc.close()

    # -- pushing messages to open pages ----------------------------------

    def _subscriber(self, room: str):
        """A sync callback for `Trace`, safe to call from any thread."""

        def publish(record: dict) -> None:
            self.publish(room, {"type": "trace", "event": record})

        return publish

    def publish(self, room: str, message: dict[str, Any]) -> None:
        """Send one message to every open page for `room`. Thread-safe.

        `AgentHost.publish`. The worker's job runs on its own event loop, so
        this hops onto the API loop rather than touching a socket from the
        wrong thread; a message published before the loop exists is dropped,
        which costs a log line and never a turn.
        """
        loop, queue = self._loop, self._fanout
        if loop is None or queue is None:
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, (room, message))

    async def _drain_fanout(self) -> None:
        assert self._fanout is not None
        while True:
            room, message = await self._fanout.get()
            session = self.sessions.get(room)
            if session is not None:
                await broadcast(session, message)

    # -- what the LiveKit worker is allowed to ask for --------------------

    def session_for(self, room: str) -> Session | None:
        """`AgentHost.session_for`: the `Session` for a room we minted."""
        return self.sessions.get(room)

    def dispatch_turn(
        self,
        session: Session,
        text: str,
        *,
        modality: str,
        confidence: float,
        shed: Any = None,
    ) -> concurrent.futures.Future:
        """`AgentHost.dispatch_turn`: run one turn on the API loop.

        The agent speaks the reply itself — it is holding the turn and the
        audio source — so `speak=False` here. Everything else is identical to
        the typed path, deliberately: same function, same per-room lock, same
        trace events, which is what §7.2's M10 is computed from.
        """
        loop = self._loop
        if loop is None:
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_exception(RuntimeError("the API loop is not running"))
            return future
        return asyncio.run_coroutine_threadsafe(
            run_turn(
                self,
                session,
                text,
                modality=modality,
                confidence=confidence,
                speak=False,
                shed=shed,
            ),
            loop,
        )

    # -- sessions and credentials -----------------------------------------

    def new_session(self) -> Session:
        session = self.sessions.create()
        session.trace.subscriber = self._subscriber(session.room)
        # §2.4's ladder, over §2.2's book, logging every move. "Applied
        # automatically on measured breach, **logged every time**" — so the
        # trace callback is wired at construction rather than left to a caller
        # who might forget it.
        session.ladder = ladder.Ladder(
            session.latency,
            on_change=lambda event: session.trace.event("latency.ladder", **event.as_dict()),
        )
        session.trace.event(
            "session.created",
            transport=self.settings.transport,
            token_ttl_seconds=self.settings.token_ttl_seconds,
            public_ip_advertised=bool(self.settings.public_ip),
            llm="bedrock-nova" if self.llm is not None else "none (rule-based floor)",
            # A credential published in LiveKit's own documentation must never
            # be silently in production (`server/livekit_dev.py`), so it is in
            # every session's trace rather than only in the startup banner.
            livekit_keys="dev (published)" if self.settings.livekit_keys_are_dev else "configured",
        )
        return session

    def mint(
        self, session: Session, *, scheme: str = "http", host: str = ""
    ) -> token_module.MintedSession:
        """One join credential for one room, in whichever shape the media
        server will accept (`docs/06` §1.4.2, `docs/07` D-02).

        The envelope is the same either way — room, identity, token, expiry —
        because the browser's question is the same either way. Only the
        signature algorithm and the `livekit_url` differ, and the page branches
        on `transport` rather than being built for one of them.
        """
        settings = self.settings
        if settings.is_livekit:
            token = livekit_tokens.mint(
                room=session.room,
                identity=session.identity,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
                ttl_seconds=settings.token_ttl_seconds,
            )
            claims: Any = livekit_tokens.verify(
                token,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
                room=session.room,
                identity=session.identity,
            )
        else:
            token = token_module.mint(
                room=session.room,
                identity=session.identity,
                secret=settings.token_secret,
                ttl_seconds=settings.token_ttl_seconds,
            )
            claims = token_module.verify(
                token, secret=settings.token_secret, room=session.room
            )
        return token_module.MintedSession(
            room=session.room,
            identity=session.identity,
            token=token,
            expires_at=claims.expires_at,
            ttl_seconds=claims.ttl_seconds,
            ice_servers=settings.ice_server_payload(),
            transport=settings.transport,
            livekit_url=(
                settings.livekit_public_url(scheme, host) if settings.is_livekit else ""
            ),
        )

    def authorise(self, token: str, room: str) -> Session:
        """Verify a join token **for this room** and return its session.

        One function for both token shapes, and one set of outcomes: 401 for
        expired or absent, 403 for everything else. The two mints raise the
        same exception hierarchy precisely so that this does not have to know
        which one issued the credential it is rejecting.
        """
        if not token or not room:
            raise HTTPException(status_code=401, detail="token and room are required")
        session = self.sessions.get(room)
        if session is None:
            raise HTTPException(status_code=404, detail="no such room")
        settings = self.settings
        try:
            if settings.is_livekit:
                claims: Any = livekit_tokens.verify(
                    token,
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                    room=room,
                    identity=session.identity,
                )
            else:
                claims = token_module.verify(
                    token,
                    secret=settings.token_secret,
                    room=room,
                    identity=session.identity,
                )
        except token_module.TokenExpired as exc:
            session.trace.event("auth.rejected", reason="expired", room=room)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except token_module.TokenError as exc:
            peek = livekit_tokens.peek if settings.is_livekit else token_module.peek
            session.trace.event(
                "auth.rejected",
                reason=type(exc).__name__,
                room=room,
                token_room=peek(token).get("room"),
            )
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        session.state.notes["last_join_jti"] = claims.jti
        return session


async def broadcast(session: Session, message: dict[str, Any]) -> None:
    """Send to every open socket for this room — caller pages and consoles.

    One call reaches both sets because the session feed is the same session:
    `docs/07` D-17's whole point is that nothing about it changed except who
    else is in it. `core_bridge.fanout` is where a message that belongs to only
    one side says so.
    """
    await fanout(session, message)


async def run_turn(
    state: AppState,
    session: Session,
    text: str,
    *,
    modality: str,
    confidence: float = 1.0,
    speak: bool = True,
    shed: Any = None,
) -> dict[str, Any]:
    """**One** turn, however it arrived (`docs/06` §1.4.1 item 2).

    A click, a typed string and a transcribed utterance all land here, carrying
    `{value, modality, confidence}`; `core_bridge.run_typed_turn` puts the
    modality in the trace and hands the core nothing but the value. There is no
    second path and no second copy of this function, which is the only way
    §7.2's M10 — *the branch taken is identical whichever modality answered* —
    is a measurement rather than a hope.

    `speak` is about who owns the audio source, not about the turn. A voice
    turn is spoken by the agent that heard it, inside the turn gate it already
    holds; a typed turn has nobody holding that gate, so the reply is pushed to
    the agent to speak — §1.4.1 item 3, "a user who types the SSID in turn 4
    and then speaks turn 5 has one session".
    """
    await broadcast(
        session,
        {
            "type": "transcript",
            "line": TranscriptLine(
                role="caller",
                text=text,
                modality=modality,
                confidence=confidence,
                turn=session.state.turn + 1,
            ).as_dict(),
        },
    )
    payload = await run_typed_turn_async(
        session,
        text,
        modality=modality,
        confidence=confidence,
        llm=state.llm,
        chunks_path=state.settings.chunks_path,
        # §2.4's ladder decides per turn what the pipeline may stop doing.
        # Asked for every modality, because a shed that only applied to spoken
        # turns would make a typed turn and a spoken turn run different
        # pipelines — which is exactly what §7.2's M10 forbids. The voice path
        # chooses its own shed one step earlier, because Tier 0's filler has
        # to be *spoken* before the turn runs, and passes it down here.
        shed=shed if shed is not None else session.shed_for_turn(session.state.turn + 1),
    )
    if not payload.get("suppressed"):
        await broadcast(
            session,
            {
                "type": "transcript",
                "line": TranscriptLine(
                    role="agent",
                    text=payload["text"],
                    modality="text",
                    turn=session.state.turn,
                ).as_dict(),
            },
        )
    if modality != "voice" and session.last_core_breakdown is not None:
        # §2.2 lines 4, 5, 6 and 8 are the same lines whichever modality asked
        # the question, so a typed turn goes in the book too. It carries no
        # M7: there was no end of speech and no audio, and §7.2 is explicit
        # that turns answered by click or typing are reported separately
        # rather than blended into the latency median. The voice path records
        # its own turns, because only it can see lines 2, 3 and 7.
        session.latency.record(
            latency.TurnLatency(
                turn=session.state.turn, modality=modality
            ).apply_core(session.last_core_breakdown)
        )
    # The reply goes out either way: when it is suppressed it carries
    # `suppressed: true` and the mode that suppressed it, which is how
    # both the caller's page and the console learn that the agent heard
    # the turn and deliberately proposed nothing (§5.3).
    await broadcast(session, {"type": "turn.reply", "reply": payload})
    if speak and session.voice is not None:
        session.voice.on_external_turn(payload)
    return payload


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. One process holds the mint, the media and the core."""
    settings = settings or Settings.from_env()
    state = AppState(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):  # pragma: no cover - lifecycle
        await state.start()
        try:
            yield
        finally:
            await state.stop()

    app = FastAPI(title="Rove Phase 2b web client", version="0.1.0", lifespan=lifespan)
    app.state.rove = state

    # -- health ----------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        worker = state.worker
        return {
            "ok": True,
            "uptime_s": round(time.time() - state.started_at, 1),
            "rooms": len(state.sessions.rooms()),
            "llm": state.llm is not None,
            "public_ip_advertised": settings.public_ip or None,
            "audio_sample_rate": settings.audio_sample_rate,
            "console": settings.console_dist.is_dir(),
            "transport": state.settings.transport,
            "livekit_url": state.settings.livekit_url if state.settings.is_livekit else None,
            # Never inferred and never omitted: a process running on the
            # published `--dev` key pair says so on its health endpoint.
            "livekit_keys_are_dev": state.settings.livekit_keys_are_dev,
            "livekit_worker": (
                None if worker is None else {"running": worker.running, "error": worker.error}
            ),
            "transcribe": (
                {
                    "enabled": state.settings.use_transcribe,
                    "vocabulary": state.settings.transcribe_vocabulary or None,
                }
                if state.settings.is_livekit
                else None
            ),
        }

    # -- the token mint (§1.4.2) -----------------------------------------

    @app.post("/api/session")
    async def create_session(request: Request) -> dict[str, Any]:
        """Open a room and mint one short-lived token for it.

        The response is the **only** credential the browser ever holds, it
        names one room and one identity, and it expires in minutes. There is
        no AWS credential anywhere in it — Polly and Bedrock are called from
        this process, with this process's role.
        """
        session = state.new_session()
        minted = state.mint(
            session, scheme=request.url.scheme, host=request.headers.get("host", "")
        )
        session.trace.event(
            "session.minted",
            transport=minted.transport,
            expires_at=minted.expires_at,
            ttl_seconds=minted.ttl_seconds,
        )
        return {
            **minted.as_dict(),
            "session_id": session.session_id,
            "audio_sample_rate": settings.audio_sample_rate,
            # §6.3: the notice the page must show, handed over with the
            # credential so there is no version of the page that has a session
            # and does not have the words. Showing it is what makes a decision
            # recordable; `consent.disclosed` reports that it was.
            "consent": {
                "state": session.consent.as_dict(),
                "disclosure": consent_module.DEFAULT_DISCLOSURE,
            },
        }

    @app.post("/api/session/{room}/token")
    async def renew_token(room: str, request: Request) -> dict[str, Any]:
        """Re-mint for a room the caller is **already** in.

        §1.4.2 wants two things that pull against each other: a credential that
        expires in minutes, and sessions that outlive it — "reconnection is
        expected, not exceptional". A ten-minute call and a five-minute token
        meet here. The page renews while it is open, so the credential on the
        wire is never valid for more than one TTL, and a re-join after a media
        drop still names the room it already has a `DiagnosticState` in.

        Renewal needs an **unexpired** token: there is no grace window, no
        separate refresh credential, and nothing a leaked token buys after its
        few minutes are up. Leave the page shut past the TTL and the room is
        genuinely gone, which is the correct outcome and not a bug.
        """
        body = await request.json()
        session = state.authorise(body.get("token", ""), room)
        minted = state.mint(
            session, scheme=request.url.scheme, host=request.headers.get("host", "")
        )
        session.trace.event(
            "session.renewed", transport=minted.transport, expires_at=minted.expires_at
        )
        return {
            **minted.as_dict(),
            "session_id": session.session_id,
            "audio_sample_rate": settings.audio_sample_rate,
        }

    # -- WebRTC signalling (the `smallwebrtc` fallback only) ---------------
    #
    # D-02 keeps Pipecat as the fallback rather than deleting it, so these two
    # surfaces stay mounted and stay tested. In `livekit` mode they refuse
    # with 409 — *after* the token check, so a bad credential is still a 401 or
    # a 403 and the mint's scope is enforced identically on both transports.

    def _require_smallwebrtc() -> None:
        if state.settings.is_livekit:
            raise HTTPException(
                status_code=409,
                detail=(
                    "this process is running the livekit transport; the browser joins "
                    "the room directly. Set ROVE_TRANSPORT=smallwebrtc for this path."
                ),
            )

    @app.post("/api/offer")
    async def offer(request: Request) -> dict[str, Any]:
        """Take the browser's SDP offer, answer it, and start the pipeline."""
        body = await request.json()
        room = body.get("room", "")
        session = state.authorise(body.get("token", ""), room)
        _require_smallwebrtc()
        session.trace.event(
            "webrtc.offer",
            pc_id=body.get("pc_id"),
            restart_pc=bool(body.get("restart_pc")),
            renegotiation=bool(body.get("pc_id")),
        )

        async def on_connection(connection: Any) -> None:
            await attach_media(session=session, connection=connection, settings=settings)

        try:
            answer = await state.webrtc.handle_web_request(
                SmallWebRTCRequest(
                    sdp=body.get("sdp", ""),
                    type=body.get("type", "offer"),
                    pc_id=body.get("pc_id"),
                    restart_pc=body.get("restart_pc"),
                ),
                on_connection,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            session.trace.event("webrtc.offer_failed", error=f"{type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if answer is None:
            raise HTTPException(status_code=500, detail="no SDP answer produced")

        answer = dict(answer)
        if settings.public_ip:
            answer["sdp"] = sdp_module.rewrite_host_candidates(
                answer["sdp"], settings.public_ip
            )
        session.trace.event(
            "webrtc.answer",
            pc_id=answer.get("pc_id"),
            candidate_addresses=sdp_module.candidate_addresses(answer["sdp"]),
        )
        return answer

    @app.post("/api/ice")
    async def ice(request: Request) -> dict[str, Any]:
        """Trickled ICE candidates from the browser."""
        body = await request.json()
        session = state.authorise(body.get("token", ""), body.get("room", ""))
        _require_smallwebrtc()
        candidates = [
            IceCandidate(
                candidate=item.get("candidate", ""),
                sdp_mid=item.get("sdpMid") or item.get("sdp_mid") or "0",
                sdp_mline_index=int(
                    item.get("sdpMLineIndex") or item.get("sdp_mline_index") or 0
                ),
            )
            for item in body.get("candidates", [])
        ]
        await state.webrtc.handle_patch_request(
            SmallWebRTCPatchRequest(pc_id=body.get("pc_id", ""), candidates=candidates)
        )
        session.trace.event("webrtc.ice_patch", count=len(candidates))
        return {"ok": True, "count": len(candidates)}

    # -- the trace --------------------------------------------------------

    @app.get("/api/trace/{room}")
    async def trace(
        room: str,
        token: str = Query(""),
        since_seq: int = Query(0),
    ) -> dict[str, Any]:
        session = state.authorise(token, room)
        return {
            "summary": session.trace.summary(),
            "events": session.trace.events(since_seq=since_seq),
        }

    # -- the control plane -------------------------------------------------

    @app.websocket("/ws")
    async def control(socket: WebSocket, token: str = Query(""), room: str = Query("")) -> None:
        """Typed turns in, diagnostic state out (§1.4, §1.4.1).

        A socket per open page. The session outlives it: `DiagnosticState` is
        server-side (§3.3), so a reload or a re-join replays the snapshot and
        loses nothing.
        """
        try:
            session = state.authorise(token, room)
        except HTTPException as exc:
            await socket.accept()
            await socket.send_json({"type": "error", "detail": exc.detail})
            await socket.close(code=4401)
            return
        await socket.accept()
        session.listeners.add(socket)
        session.trace.event("control.connected", listeners=len(session.listeners))
        try:
            await socket.send_json({"type": "hello", "snapshot": session_snapshot(session)})
            while True:
                message = await socket.receive_json()
                await _handle_control_message(state, session, socket, message)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            session.trace.event("control.error", error=f"{type(exc).__name__}: {exc}")
        finally:
            session.listeners.discard(socket)
            session.trace.event("control.disconnected", listeners=len(session.listeners))

    # -- the support console (§5.3, D-17, §9.3 item 14) ---------------------

    register_support_routes(app, state)

    console: Path = settings.console_dist
    if console.is_dir():
        app.mount(
            "/support/assets",
            StaticFiles(directory=console / "assets"),
            name="console-assets",
        )

        @app.get("/support")
        @app.get("/support/")
        async def console_index() -> Any:
            """The console, from the same process as everything else.

            Served under a path rather than a second port because the console
            talks to this process's rooms: one origin means no CORS to arrange
            and no second thing to operate, which is the same argument
            `docs/06` §8.1.1 makes for the spike.
            """
            return FileResponse(console / "index.html")

    else:

        @app.get("/support")
        @app.get("/support/")
        async def console_missing() -> Any:
            return JSONResponse(
                {
                    "error": "support console not built",
                    "fix": "node support/build.mjs",
                    "expected": str(console),
                },
                status_code=503,
            )

    # -- same-origin signalling relay (wss for an https page) ---------------

    if settings.is_livekit:
        register_livekit_relay(app, settings)

    # -- the page ----------------------------------------------------------

    dist: Path = settings.client_dist
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        async def index() -> Any:
            return FileResponse(dist / "index.html")

    else:

        @app.get("/")
        async def index_missing() -> Any:
            return JSONResponse(
                {
                    "error": "client not built",
                    "fix": "cd client && npm install && npm run build",
                    "expected": str(dist),
                },
                status_code=503,
            )

    return app


async def _handle_control_message(
    state: AppState, session: Session, socket: WebSocket, message: dict[str, Any]
) -> None:
    """One message from an open page."""
    kind = message.get("type")
    if kind == "ping":
        await socket.send_json({"type": "pong", "t": time.time()})
        return

    if kind == "user.text":
        text = (message.get("text") or "").strip()
        # §1.4.1 item 2: a click and a typed string are the same event type.
        # Both arrive here, both carry their modality, and neither changes what
        # the core is asked.
        modality = message.get("modality") or "typed"
        if not text:
            await socket.send_json({"type": "error", "detail": "empty message"})
            return
        try:
            await run_turn(state, session, text, modality=modality, speak=True)
        except Exception as exc:  # noqa: BLE001
            session.trace.event("turn.failed", error=f"{type(exc).__name__}: {exc}", modality=modality)
            await socket.send_json({"type": "error", "detail": f"turn failed: {exc}"})
            return
        return

    if kind == "user.typing":
        # §2.3's one signal a phone call does not have. It has to reach the
        # endpointer, which lives on the agent's loop — `note_typing` only
        # stamps a float, so it is safe to call across the two.
        if session.voice is not None:
            with contextlib.suppress(Exception):
                session.voice.note_typing()
        return

    if kind == "consent.decision":
        # §6.3. One decision per message — `display` or `storage`, never both —
        # because they are separate decisions and a message shape that could
        # carry both is a control that could accidentally bundle them.
        try:
            session.consent.decide(
                str(message.get("kind", "")),
                str(message.get("decision", "")),
                modality=str(message.get("modality") or "click"),
            )
        except consent_module.ConsentError as exc:
            await socket.send_json({"type": "error", "detail": str(exc)})
            return
        session.trace.event(
            "consent.decision",
            kind=message.get("kind"),
            decision=message.get("decision"),
            modality=message.get("modality") or "click",
            may_display=session.consent.may_display(),
            may_store=session.consent.may_store(),
        )
        await broadcast(session, {"type": "consent", "consent": session.consent.as_dict()})
        return

    if kind == "consent.disclosed":
        # The page reporting that it rendered the §6.3 notice. Spoken and shown
        # are recorded separately: "a consent notice that only exists in audio
        # the user may have missed is weak evidence of consent", and a record
        # that cannot tell the two apart cannot be judged on that.
        try:
            session.consent.disclose(
                text=str(message.get("text") or consent_module.DEFAULT_DISCLOSURE),
                spoken=bool(message.get("spoken")),
                shown=bool(message.get("shown", True)),
            )
        except consent_module.ConsentError as exc:
            await socket.send_json({"type": "error", "detail": str(exc)})
            return
        session.trace.event(
            "consent.disclosed",
            spoken=bool(message.get("spoken")),
            shown=bool(message.get("shown", True)),
        )
        await broadcast(session, {"type": "consent", "consent": session.consent.as_dict()})
        return

    if kind == "net.stats":
        # The browser's own `RTCPeerConnection.getStats()` view of the link
        # (§9.1 Phase 2b exit). Kept apart from the server's `aiortc` view: two
        # measurements of one link, and a disagreement is information.
        session.trace.event(
            "net.client_stats",
            source="browser",
            rtt_ms=message.get("rtt_ms"),
            jitter_ms=message.get("jitter_ms"),
            packets_lost=message.get("packets_lost"),
            packets_received=message.get("packets_received"),
            playout_delay_ms=message.get("playout_delay_ms"),
            audio_level=message.get("audio_level"),
            connection_state=message.get("connection_state"),
        )
        return

    if kind == "client.event":
        session.trace.event(
            "client." + str(message.get("name", "event")),
            **{k: v for k, v in message.items() if k not in ("type", "name")},
        )
        return

    await socket.send_json({"type": "error", "detail": f"unknown message type {kind!r}"})
