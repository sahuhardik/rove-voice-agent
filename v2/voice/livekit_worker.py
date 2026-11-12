"""Production voice path: a LiveKit Agents worker that puts the diagnostic agent in a room.

    python -m v2.voice.livekit_worker dev      # needs LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

LiveKit supplies the parts that are hard to get right by hand: turn detection
(Silero VAD + endpointing), barge-in, echo handling in the browser, and rooms a
human support agent can join. The pipeline is standard; only the "LLM" step is
ours: `llm_node` hands the customer's words to `v2.rove.agent.Agent.respond` and
returns the cleared reply, so voice gets exactly the same reasoning and safety
layer as text.
"""
from __future__ import annotations

import asyncio
import logging

from livekit.agents import Agent as VoiceAgent
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli, llm
from livekit.plugins import aws, silero

from v2.rove import config, speech
from v2.rove.agent import Agent

log = logging.getLogger("rove.voice")


class DiagnosticLLM(llm.LLM):
    """Marks the session as having an LLM so LiveKit runs the reply pipeline.

    LiveKit only calls `Agent.llm_node` when the session has an LLM. The real
    reasoning happens in `RoveVoiceAgent.llm_node`, which never calls `chat`.
    """

    @property
    def model(self) -> str:
        return "rove-diagnostic-agent"

    def chat(self, **kwargs):  # pragma: no cover - llm_node replaces this path
        raise NotImplementedError("RoveVoiceAgent.llm_node handles every turn")


def last_user_text(chat_ctx) -> str:
    for item in reversed(chat_ctx.items):
        if getattr(item, "type", None) == "message" and item.role == "user":
            return item.text_content or ""
    return ""


def publish(room, topic: str, payload: dict) -> None:
    """Fire-and-forget message to every browser in the room (live captions, call state, case file)."""
    if room is None:
        return
    import json
    task = asyncio.ensure_future(room.local_participant.publish_data(json.dumps(payload), reliable=True, topic=topic))
    task.add_done_callback(lambda t: t.exception() and log.warning("publish %s failed: %s", topic, t.exception()))


def wire_ui_events(session: AgentSession, room) -> None:
    """Tell the browser what the call is doing, so the page can show live captions and state."""
    @session.on("user_input_transcribed")
    def _heard(ev) -> None:
        publish(room, "rove.transcript", {"type": "user", "text": ev.transcript, "final": bool(ev.is_final)})

    @session.on("agent_state_changed")
    def _state(ev) -> None:
        publish(room, "rove.state", {"type": "agent", "state": ev.new_state})

    @session.on("user_state_changed")
    def _user_state(ev) -> None:
        publish(room, "rove.state", {"type": "user", "state": ev.new_state})


class RoveVoiceAgent(VoiceAgent):
    def __init__(self) -> None:
        super().__init__(instructions="Rove dash cam support (reasoning lives in v2.rove.agent).")
        self.brain = Agent()

    async def on_enter(self) -> None:
        greeting = self.brain.greeting()
        room = self.session.room_io.room if getattr(self.session, "room_io", None) else None
        publish(room, "rove.transcript", {"type": "agent", "text": greeting, "final": True})
        self.session.say(greeting)

    async def llm_node(self, chat_ctx, tools, model_settings):
        text = speech.normalize_transcript(last_user_text(chat_ctx))
        if not text.strip():
            return None
        if self.brain.closed:
            return "A person from Rove's support team is taking over. They can see everything we've covered."
        reply = await asyncio.to_thread(self.brain.respond, text)
        log.info("turn model=%s action=%s latency=%.1fs flags=%s", self.brain.case.model, reply.action,
                 reply.latency_s, self.brain.case.flags)
        # The case file travels to the browser and the support console over the data channel.
        room = self.session.room_io.room if getattr(self.session, "room_io", None) else None
        if room is not None:
            import json
            payload = json.dumps({"type": "case", "case": self.brain.case.to_dict(), "action": reply.action})
            await room.local_participant.publish_data(payload, reliable=True, topic="rove.case")
        publish(room, "rove.transcript", {"type": "agent", "text": reply.say, "final": True,
                                          "latency_s": reply.latency_s, "action": reply.action})
        return reply.say


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=aws.STT(region=config.REGION, sample_rate=16000, language="en-US"),
        llm=DiagnosticLLM(),
        tts=aws.TTS(voice=config.POLLY_VOICE, speech_engine=config.POLLY_ENGINE, region=config.REGION),
        min_endpointing_delay=0.6,
        allow_interruptions=True,
    )
    wire_ui_events(session, ctx.room)
    await session.start(agent=RoveVoiceAgent(), room=ctx.room)


if __name__ == "__main__":
    logging.getLogger("rove.voice").setLevel(logging.INFO)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
