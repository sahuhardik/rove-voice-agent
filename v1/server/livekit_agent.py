"""The LiveKit agent worker: the thing that joins the room.

`docs/07` D-02 picks LiveKit Agents 1.0 as the production target, and is
explicit that it is not picked for the pipeline:

> **Escalation is a hard requirement and the room model satisfies it
> directly.** [...] *We are not choosing a framework for the happy path; we are
> choosing it for the handoff, because the handoff is the part that is
> expensive to retrofit.*

So this module uses LiveKit for the part D-02 bought — **rooms, job dispatch,
and a participant that is us** — and keeps the voice pipeline itself in our own
hands. `docs/06` §8.1.1 names that as a requirement rather than a preference:

> The plugin layer is an abstraction that will occasionally need to be reached
> around; we must keep the §2.2 component timings visible through it, which is
> a requirement to verify, not assume.

Concretely: we do **not** use `AgentSession` with STT/LLM/TTS plugins. The
media comes off `rtc.AudioStream` at 16 kHz in 20 ms frames (§1.4.2), Silero
VAD v5 runs on it (D-03), our own `server/transcribe.py` stream transcribes it
(D-05), our own `server/endpointing.py` decides end-of-turn (§2.3), and
`server/core_bridge.py` dispatches the result into the same `agent.core`
function a typed turn goes through. Every §2.2 line this milestone owns is
therefore a number we take ourselves:

| §2.2 | Measured here as |
|---|---|
| line 2 — endpoint decision | `endpoint.fired` → `silence_ms`, `hangover_ms`, `turn_type` |
| line 3 — ASR final flush | `turn.voice` → `asr_flush_ms`, from `TranscribeStream.await_final` |
| lines 4–6 — gate, FSM, retrieval, LLM | `turn.reply` → `latency_ms`, already produced by `core_bridge` |
| line 7 — TTS time-to-first-audio | `tts.played` → `synthesis_ms` (first clause) |
| line 5 — retrieval not hidden by prefetch | `prefetch.hit` / `prefetch.discarded` |

**Barge-in (Milestone 6.2, `docs/06` §2.1).** The VAD runs continuously,
including while the agent is speaking, and start-of-speech during playout stops
the agent mid-utterance:

> On detected user speech the TTS stream is cancelled within one frame and the
> playback buffer is flushed — both server-side and in the browser, since audio
> already handed to the peer connection will otherwise keep playing for the
> length of the jitter buffer.

Both halves are here. Server-side is :meth:`RoomVoiceAgent._barge_in`, which
stops pushing frames and calls `AudioSource.clear_queue()` — the source holds
up to a second of queued audio, so dropping the remaining clauses without
clearing it would leave the caller talked over for exactly as long as the
buffer. Browser-side is one `agent.flush` message on the `rove` topic;
`client/src/livekit.js` re-attaches the remote track to the `<audio>` element,
which is what empties a jitter buffer you do not otherwise get a handle on.

And §2.1's other requirement — *"the agent **re-anchors** rather than
restarting"* — is `server/core_bridge.note_interruption`: the `step_id`, the
`sub_step_index` and the `spoken_prefix` go into `DiagnosticState.notes`, the
reply stays in the transcript, and the un-spoken remainder goes to the page.
Being interrupted is not a diagnostic event and advances nothing.

**The agent still does not listen to itself.** While it is speaking, the
recogniser is fed silence and the caller's frames go to a short hold buffer
instead; on barge-in the hold is drained into the recogniser so the caller's
first word is not the one that was eaten proving they were speaking. Browser
AEC (§2.1 "Echo and self-trigger") is what makes those held frames the
caller's rather than ours, and the hold is deliberately shorter than a word.

**Where the worker runs.** In the API process by default, with
`JobExecutorType.THREAD`, so the job can reach the server-side
`DiagnosticState` (§1.4.2: "`DiagnosticState` lives server-side") by object
reference rather than over a wire that does not exist yet. The job's event loop
is *not* the API process's event loop, so every crossing is explicit: trace and
UI messages go through :class:`AgentHost.publish`, and turns are dispatched
onto the API loop through :class:`AgentHost.dispatch_turn`, which is also what
makes a spoken turn and a typed turn contend for the same per-room lock. A
worker in its own process is a Phase 4 question and `server/README.md` says
what it would cost.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobExecutorType, WorkerOptions
from livekit.agents import vad as agent_vad

# `livekit-agents` registers a plugin at *import* time and refuses to do it off
# the main thread. The job runs on a worker thread (`JobExecutorType.THREAD`),
# so importing this inside `_start_vad` — where it reads most naturally — makes
# the whole voice path depend on which thread happened to get there first, and
# it dies with "Plugins must be registered on the main thread" whenever the API
# process is itself started from a thread (which is exactly what
# `server/verify_livekit.py` and `server/test_livekit.py` do). Importing it
# here, and importing this module from `server/app.py` at module scope, pins
# the registration to the import that starts the process. `docs/06` §8.1.1
# calls the plugin layer "an abstraction that will occasionally need to be
# reached around"; this is one of those occasions, and it is cheap.
from livekit.plugins import silero

from server import core_bridge, endpointing, latency, polly, prefetch, transcribe
from server import ladder as ladder_module
from server.config import Settings
from server.core_bridge import Session

#: 20 ms frames, as §1.4.2 requires and as the VAD, the endpointer and
#: Transcribe are all tuned against.
FRAME_MS = 20

#: How often the audio level goes to the page. Eight a second is enough for a
#: meter to look live and little enough to stay out of the way of media.
LEVEL_HZ = 8.0

MIN_DBFS = -90.0

#: The data-channel topic the page and the agent talk on. A topic rather than
#: an untyped broadcast so a future second participant (§5.3) can be addressed
#: without the caller's page having to filter.
TOPIC = "rove"

#: How long we wait past the endpoint for Transcribe to finalise. §2.2 line 3
#: budgets 80 ms at the median and 200 ms at p95; a second is the ceiling at
#: which we give up and use the partial, because a turn that never closes is
#: worse than a turn that closes on a partial.
FINAL_FLUSH_TIMEOUT_S = 1.0

#: How many clauses may be synthesised ahead of the one being played
#: (`server/polly.py`). One is enough to hide synthesis under playout, and it
#: bounds what a barge-in throws away: at most one unplayed clause of Polly.
TTS_LOOKAHEAD = 1

#: How much of the caller's audio is held back while the agent is speaking, so
#: that a barge-in does not lose the word that proved they were speaking. Silero
#: needs `vad_start_secs` (200 ms by default) of speech to declare onset, and
#: the hold has to cover that plus the inference window — but it must stay
#: shorter than a word, because every held frame was captured while our own
#: voice was in the room and only browser AEC makes it the caller's (§2.1).
ECHO_HOLD_MS = 400


# --------------------------------------------------------------------------
# What the agent needs from the process that owns the sessions
# --------------------------------------------------------------------------


class AgentHost(Protocol):
    """The API process, as the worker is allowed to see it.

    Three methods, and the narrowness is the point: the worker cannot reach
    into `agent/`, cannot touch a WebSocket, and cannot run a turn itself.
    `server/app.py` is the only implementation.
    """

    settings: Settings
    #: The handle `run_typed_turn` passes to `agent.core.diagnose`, wrapped in
    #: `server/prefetch.MemoLLM`. The worker reads it so that a speculative
    #: `classify` on a partial and the turn's own `classify` on the final share
    #: one memo — which is the whole of §2.1's "warms the LLM prompt prefix".
    llm: Any

    def session_for(self, room: str) -> Session | None:
        """The `Session` for a room, or `None` if we did not mint it."""

    def publish(self, room: str, message: dict[str, Any]) -> None:
        """Send one message to every open page for `room`. Thread-safe."""

    def dispatch_turn(
        self,
        session: Session,
        text: str,
        *,
        modality: str,
        confidence: float,
        shed: Any = None,
    ) -> Any:
        """Run one turn on the API loop. Returns a `concurrent.futures.Future`."""


#: Set by :class:`AgentWorker` while it is running. The entrypoint is a plain
#: function handed to LiveKit, so there is nowhere else to put this; it is a
#: module global rather than a parameter because the framework owns the call.
_HOST: AgentHost | None = None
_HOST_LOCK = threading.Lock()


def current_host() -> AgentHost | None:
    with _HOST_LOCK:
        return _HOST


# --------------------------------------------------------------------------
# Level metering
# --------------------------------------------------------------------------


def dbfs(pcm: bytes) -> float:
    """RMS of mono 16-bit PCM, in dBFS. Full scale is 0.

    Deliberately not imported from `server/pipeline.py`, which holds the same
    arithmetic for the Pipecat fallback: importing it would make the LiveKit
    path pull in Pipecat, and D-02 keeps the two transports independent so
    either can go without touching the other.
    """
    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size == 0:
        return MIN_DBFS
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 1.0:
        return MIN_DBFS
    return max(MIN_DBFS, round(20.0 * float(np.log10(rms / 32768.0)), 2))


# --------------------------------------------------------------------------
# One room's voice path
# --------------------------------------------------------------------------


@dataclass
class VoiceStats:
    """What the session did, in numbers the verification script reads."""

    frames_in: int = 0
    audio_seconds: float = 0.0
    speech_segments: int = 0
    endpoints_fired: int = 0
    voice_turns: int = 0
    spoken_turns: int = 0
    transcribing: bool = False
    asr_error: str = ""
    #: Utterances the caller talked over (§2.1).
    barge_ins: int = 0


@dataclass
class SpeechOutcome:
    """One utterance, and how much of it the caller actually heard.

    The fields §2.1 names — `step_id`, `sub_step_index`, `spoken_prefix` — are
    here rather than in `DiagnosticState` until the turn is over, because this
    is the media path's view and the state record is the core's.
    """

    text: str = ""
    kind: str = "reply"
    step_id: str | None = None
    #: What was audible before the caller cut in. Derived from the playout
    #: position, not from what was *queued* — `AudioSource` holds up to a
    #: second, and counting queued frames as spoken would put words in the
    #: caller's ears that the flush had just thrown away.
    spoken_prefix: str = ""
    remainder: str = ""
    #: Which clause was playing. §2.1's `sub_step_index`.
    sub_step_index: int = 0
    interrupted: bool = False
    at_ms: float = 0.0
    played_ms: int = 0
    chunks: int = 0
    #: §2.2 line 7 — the wait before the **first** sample was pushed.
    first_audio_ms: float = 0.0
    #: The same instant on the process clock, so M7 can be taken as one wall
    #: clock from end-of-speech rather than reconstructed by adding lines up.
    first_audio_at: float = 0.0
    #: What whole-utterance synthesis would have charged before that sample.
    synthesis_total_ms: float = 0.0
    failed: str = ""


def spoken_prefix(
    chunks: list[str], pushed: list[tuple[str, int]], played_ms: float
) -> tuple[str, str, int]:
    """Split a reply at the playout position: heard, un-heard, which clause.

    `pushed` is the clauses that reached the source and how many milliseconds
    of each; `played_ms` is how much of that was audible before the flush. The
    cut inside the clause that was playing is character-proportional and lands
    on a word boundary — Polly's PCM has no word timings in it, and inventing a
    precision the data does not carry would be worse than a rounded answer that
    says so. §2.1 wants the remainder on screen, and a remainder that starts
    mid-word is the one thing that would read as a bug rather than as a pause.
    """
    joined = " ".join(chunks).strip()
    spoken: list[str] = []
    budget = max(0.0, played_ms)
    index = 0
    for position, (text, duration_ms) in enumerate(pushed):
        index = position
        if duration_ms <= 0 or budget >= duration_ms:
            spoken.append(text)
            budget -= max(0, duration_ms)
            index = position + 1
            continue
        fraction = budget / duration_ms
        cut = int(len(text) * fraction)
        head = text[:cut]
        if " " in head:
            head = head.rsplit(" ", 1)[0]
        elif cut < len(text):
            head = ""
        if head:
            spoken.append(head)
        break
    heard = " ".join(spoken).strip()
    remainder = joined[len(heard) :].strip() if joined.startswith(heard) else joined
    return heard, remainder, index


class RoomVoiceAgent:
    """The agent, for the length of one room.

    Owns the inbound audio pump, the VAD, the recogniser, the endpointer and
    the outbound voice. Owns no diagnostic state at all: that is the
    `Session`'s, and it is reached only through :class:`AgentHost`.
    """

    def __init__(self, *, ctx: JobContext, session: Session, host: AgentHost) -> None:
        self.ctx = ctx
        self.session = session
        self.host = host
        self.settings = host.settings
        self.rate = self.settings.audio_sample_rate
        self.stats = VoiceStats()

        self._loop = asyncio.get_running_loop()
        self._source: rtc.AudioSource | None = None
        self._asr: transcribe.TranscribeStream | None = None
        self._vad_stream: agent_vad.VADStream | None = None
        self._endpointer = endpointing.Endpointer()
        self._tasks: set[asyncio.Task] = set()
        self._turn_gate = asyncio.Lock()
        #: Set the moment an endpoint fires and cleared when the turn is over.
        #: The lock alone is not enough: `_close_turn` is spawned as a task, so
        #: between the decision and the task's first line the loop can deliver
        #: another inference event and fire the same turn twice. A plain flag
        #: set synchronously inside `_on_inference` closes that window.
        self._turn_pending = False
        self._speaking = False
        self._cursor = 0
        self._last_level_at = 0.0
        self._peak_dbfs = MIN_DBFS
        self._closed = asyncio.Event()

        # -- barge-in (§2.1) ----------------------------------------------
        #: Set by `_barge_in`, cleared by the next `_speak`. A fresh event per
        #: utterance rather than a flag, so a late frame from the utterance
        #: that was interrupted cannot clear the next one's.
        self._interrupt = asyncio.Event()
        self._interrupt.set()
        #: What `AudioSource` still had queued the instant the caller cut in.
        #: Pushed-minus-queued is what was audible; see :class:`SpeechOutcome`.
        self._queued_at_interrupt_ms = 0.0
        #: The caller's frames, held back while we speak. See `ECHO_HOLD_MS`.
        self._echo_hold: deque[bytes] = deque(
            maxlen=max(1, ECHO_HOLD_MS // FRAME_MS)
        )
        #: Set by `_barge_in` to the hold's contents, drained by the pump into
        #: the recogniser on its next frame.
        self._hold_drain: list[bytes] = []

        # -- speculative prefetch (§2.1) -----------------------------------
        #: One thread, so speculation is serialised with itself and cannot
        #: fan out into a thread per partial. It is also where the blocking
        #: work lives: `docs/07` D-14's "no blocking calls on the media path".
        self._speculation = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="rove-prefetch"
        )
        self._prefetch = prefetch.SpeculativePrefetch(
            state=self.session.state,
            llm=getattr(host, "llm", None),
            chunks_path=self.settings.chunks_path,
            trace=self._trace,
            submit=self._speculate,
        )

    def _speculate(self, work: Any) -> None:
        """Run one speculation off the media loop. Never raises at the caller."""
        with contextlib.suppress(RuntimeError):  # pool shut down mid-session
            self._speculation.submit(work)

    # -- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        """Join, speak, listen, and stay until the caller leaves."""
        room = self.ctx.room
        self.session.voice = self
        self._trace(
            "agent.joined",
            identity=room.local_participant.identity,
            room=room.name,
            vad="silero-v5",
            vad_floor_ms=endpointing.VAD_FLOOR_MS,
        )

        await self._publish_voice_track()
        await self._start_recogniser()
        self._start_vad()

        room.on("track_subscribed", self._on_track_subscribed)
        room.on("data_received", self._on_data_received)
        room.on("participant_disconnected", self._on_participant_left)
        room.on("disconnected", self._on_disconnected)

        # A participant that published before we subscribed to the event.
        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._on_track_subscribed(publication.track, publication, participant)

        await self._greet()
        try:
            await self._closed.wait()
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        self._closed.set()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        if self._vad_stream is not None:
            with contextlib.suppress(Exception):
                await self._vad_stream.aclose()
            self._vad_stream = None
        if self._asr is not None:
            with contextlib.suppress(Exception):
                await self._asr.close()
            self._asr = None
        if self.session.voice is self:
            self.session.voice = None
        # `cancel_futures` rather than a wait: a speculation that has not
        # started is about a sentence from a session that has ended, and one
        # that has started holds nothing the caller is waiting for.
        with contextlib.suppress(Exception):
            self._speculation.shutdown(wait=False, cancel_futures=True)
        self._trace(
            "agent.left",
            frames_in=self.stats.frames_in,
            audio_seconds=round(self.stats.audio_seconds, 2),
            speech_segments=self.stats.speech_segments,
            endpoints_fired=self.stats.endpoints_fired,
            voice_turns=self.stats.voice_turns,
            barge_ins=self.stats.barge_ins,
            prefetch=self._prefetch.stats.as_dict(),
        )

    def _spawn(self, coro: Any, *, name: str) -> asyncio.Task:
        task = self._loop.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- the two ways out of this object ----------------------------------

    def _trace(self, name: str, **fields: Any) -> None:
        """One trace event. `Trace` is thread-safe and fans out to the page.

        The event's name is `name` and not `kind` because several of the events
        below carry a field *called* `kind` — `tts.played` says whether it was
        the greeting or a reply — and a parameter of the same name eats it.
        """
        self.session.trace.event(name, **fields)

    def _send(self, message: dict[str, Any]) -> None:
        """One message down the LiveKit data channel to the caller's page.

        Media-plane facts travel on the media plane, exactly as they did on the
        Pipecat data channel in Phase 2b. Losing them costs a meter, never a
        turn — so this is best-effort and never awaited by a caller that has
        something better to do.
        """
        room = self.ctx.room
        if room.connection_state != rtc.ConnectionState.CONN_CONNECTED:
            return
        payload = json.dumps(message).encode("utf-8")
        self._spawn(
            self._publish_data(payload, reliable=message.get("type") != "audio.level"),
            name="lk-data",
        )

    async def _publish_data(self, payload: bytes, *, reliable: bool) -> None:
        with contextlib.suppress(Exception):
            await self.ctx.room.local_participant.publish_data(
                payload, reliable=reliable, topic=TOPIC
            )

    # -- the outbound voice -----------------------------------------------

    async def _publish_voice_track(self) -> None:
        self._source = rtc.AudioSource(self.rate, 1)
        track = rtc.LocalAudioTrack.create_audio_track("rove-agent", self._source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        publication = await self.ctx.room.local_participant.publish_track(track, options)
        self._trace("agent.track_published", sid=publication.sid, sample_rate=self.rate)

    async def _greet(self) -> None:
        if not self.settings.greeting_text.strip():
            self._arm(spoken="", step_id=None)
            return
        outcome = await self._speak(self.settings.greeting_text, kind="greeting")
        self._finish_utterance(outcome, spoken=self.settings.greeting_text, step_id=None)

    async def _speak(
        self, text: str, *, kind: str = "reply", step_id: str | None = None
    ) -> SpeechOutcome:
        """Synthesise one utterance clause by clause and play it into the room.

        Two §9.1 Phase 3 items meet in this method.

        **Incremental synthesis (§2.2 line 7).** The reply is cut into clauses
        by `server/polly.py` and the first one is pushed into the room the
        moment Polly returns it, with the next synthesised behind it. So
        `synthesis_ms` — the number line 7 budgets at 120 ms median — is the
        wait for the *first clause* rather than for the whole reply, and it
        stops scaling with reply length. `synthesis_total_ms` is what the
        whole-utterance path charged for the same text, kept in the trace so
        the before/after is in every session rather than only in a benchmark.

        **Barge-in (§2.1).** Every frame push checks the interrupt, so playout
        stops within one 20 ms frame of the VAD declaring speech, and
        `_barge_in` has already emptied the source queue and told the browser
        to empty its own. The utterance returns a :class:`SpeechOutcome`
        saying how far it got; nothing here writes to `DiagnosticState` —
        `core_bridge.note_interruption` does, once, from the caller.
        """
        text = (text or "").strip()
        outcome = SpeechOutcome(text=text, kind=kind, step_id=step_id)
        if text == "" or self._source is None:
            return outcome

        chunks = polly.split_clauses(text)
        outcome.chunks = len(chunks)
        pushed: list[tuple[str, int]] = []
        pushed_ms = 0

        self._interrupt = asyncio.Event()
        self._queued_at_interrupt_ms = 0.0
        self._echo_hold.clear()
        self._speaking = True
        started = time.perf_counter()
        self._send(
            {"type": "agent.speech", "state": "start", "text": text, "chunks": len(chunks)}
        )

        stream = polly.synthesize_incremental(
            chunks,
            split=False,
            voice=self.settings.polly_voice,
            engine=self.settings.polly_engine,
            sample_rate=self.rate,
            cache_dir=self.settings.polly_cache_dir,
            lookahead=TTS_LOOKAHEAD,
        )
        try:
            try:
                async for clip in stream:
                    if self._interrupt.is_set():
                        break
                    if outcome.first_audio_ms == 0.0:
                        outcome.first_audio_at = time.perf_counter()
                        outcome.first_audio_ms = round(
                            (outcome.first_audio_at - started) * 1000, 1
                        )
                    outcome.synthesis_total_ms = round(
                        outcome.synthesis_total_ms + clip.synthesis_ms, 1
                    )
                    frames = await self._push(clip.pcm)
                    pushed.append((clip.text, frames * FRAME_MS))
                    pushed_ms += frames * FRAME_MS
                    if self._interrupt.is_set():
                        break
                if not self._interrupt.is_set():
                    # Returns early if `_barge_in` clears the queue under it,
                    # which is exactly the behaviour wanted here.
                    await self._source.wait_for_playout()
            finally:
                with contextlib.suppress(Exception):
                    await stream.aclose()
        except polly.PollyUnavailable as exc:
            self._speaking = False
            self._echo_hold.clear()
            outcome.failed = str(exc)
            self._trace("tts.failed", kind=kind, error=str(exc))
            self._send({"type": "agent.speech", "state": "failed", "text": text})
            return outcome
        finally:
            interrupted = self._interrupt.is_set()
            self._interrupt.set()
            self._speaking = False
            if not interrupted:
                # Everything the recogniser heard while we were talking is
                # ours, not the caller's: drop the hold and move the cursor
                # past it. On a barge-in the opposite is true — the hold *is*
                # the caller, and `_barge_in` has already queued it for the
                # recogniser — so neither happens there.
                self._echo_hold.clear()
                if self._asr is not None:
                    self._cursor = self._asr.cursor()

        outcome.interrupted = interrupted
        outcome.played_ms = int(
            max(0.0, pushed_ms - self._queued_at_interrupt_ms) if interrupted else pushed_ms
        )
        heard, remainder, index = spoken_prefix(chunks, pushed, outcome.played_ms)
        outcome.spoken_prefix = heard
        outcome.remainder = remainder if interrupted else ""
        outcome.sub_step_index = index
        outcome.at_ms = round((time.perf_counter() - started) * 1000, 1)

        self.stats.spoken_turns += 1
        self._trace(
            "tts.played",
            kind=kind,
            engine=self.settings.polly_engine,
            voice=self.settings.polly_voice,
            # §2.2 line 7 — the wait before the first sample, which with
            # incremental synthesis is the first clause's and not the reply's.
            synthesis_ms=outcome.first_audio_ms,
            # What the whole-utterance path would have charged for the same
            # text before a single sample was audible. The pair is the
            # measurement; `server/measure.py` runs it as a benchmark.
            synthesis_total_ms=outcome.synthesis_total_ms,
            incremental=True,
            chunks=len(chunks),
            first_chunk_characters=len(chunks[0]) if chunks else 0,
            duration_ms=outcome.played_ms,
            characters=len(text),
            interrupted=interrupted,
            sub_step_index=outcome.sub_step_index if interrupted else None,
        )
        self._send(
            {
                "type": "agent.speech",
                "state": "interrupted" if interrupted else "end",
                "text": text,
                "spoken_prefix": outcome.spoken_prefix,
                "remainder": outcome.remainder,
                "played_ms": outcome.played_ms,
            }
        )
        return outcome

    async def _push(self, pcm: bytes) -> int:
        """Frames into the room, one 20 ms frame at a time. Returns how many.

        The interrupt is checked per frame rather than per clause, which is
        §2.1's "cancelled within one frame" taken literally. `capture_frame`
        returns once the frame is *queued*, so what this counts is what was
        handed over — `_speak` subtracts the queue depth to get what was heard.
        """
        assert self._source is not None
        frame_bytes = self.rate * 2 * FRAME_MS // 1000
        samples = frame_bytes // 2
        sent = 0
        for offset in range(0, len(pcm), frame_bytes):
            if self._interrupt.is_set():
                break
            chunk = pcm[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            await self._source.capture_frame(
                rtc.AudioFrame(
                    data=chunk,
                    sample_rate=self.rate,
                    num_channels=1,
                    samples_per_channel=samples,
                )
            )
            sent += 1
        return sent

    # -- barge-in (docs/06 §2.1) -------------------------------------------

    def _barge_in(self, *, probability: float) -> bool:
        """The caller started talking while we were. Stop, now.

        Synchronous and called straight from the VAD loop, because every
        statement in it is on the critical path of §2.1's "within one frame":
        set the interrupt (the push loop checks it per frame), empty the
        source's own queue (up to a second of already-synthesised audio that
        would otherwise keep playing), and tell the browser to empty its
        jitter buffer. The trace event and the state record come later, from
        `_speak`'s caller, where the spoken prefix is actually known.
        """
        if not self._speaking or self._interrupt.is_set():
            return False
        source = self._source
        if source is not None:
            with contextlib.suppress(Exception):
                self._queued_at_interrupt_ms = 1000.0 * float(source.queued_duration)
            with contextlib.suppress(Exception):
                source.clear_queue()
        self._interrupt.set()
        self._speaking = False
        # The frames captured while we were talking are the caller's first
        # word. Hand them to the pump, which feeds them to the recogniser
        # before the live frame it is holding — so the turn starts where the
        # caller started it, not where the VAD finished noticing.
        self._hold_drain.extend(self._echo_hold)
        self._echo_hold.clear()
        self.stats.barge_ins += 1
        self._send(
            {
                "type": "agent.flush",
                "reason": "barge-in",
                "at": time.time(),
                "queued_ms": round(self._queued_at_interrupt_ms, 1),
            }
        )
        # The VAD saw speech while `_speaking` was true, so `_on_speech_start`
        # did not arm the endpointer for it. It is a real turn now.
        self._endpointer.note_speech()
        self._trace(
            "barge_in.detected",
            vad="silero-v5",
            probability=round(float(probability or 0.0), 3),
            flushed_ms=round(self._queued_at_interrupt_ms, 1),
            held_frames=len(self._hold_drain),
        )
        return True

    def _finish_utterance(
        self, outcome: SpeechOutcome, *, spoken: str, step_id: str | None
    ) -> None:
        """Record an interruption if there was one, then arm the next turn.

        Order matters. The record is written first so that a page rendering
        the §2.1 remainder sees it before the endpoint decision that follows,
        and `_arm` is given the **spoken prefix** rather than the whole reply
        when the caller cut in: §2.3 classifies the next turn from what the
        agent actually said, and a hangover chosen from a sentence nobody
        heard is a hangover chosen from fiction.
        """
        if outcome.interrupted:
            core_bridge.note_interruption(
                self.session,
                kind=outcome.kind,
                step_id=outcome.step_id or step_id,
                text=outcome.text,
                spoken_prefix=outcome.spoken_prefix,
                remainder=outcome.remainder,
                sub_step_index=outcome.sub_step_index,
                at_ms=outcome.at_ms,
                played_ms=outcome.played_ms,
            )
        self._arm(
            spoken=outcome.spoken_prefix if outcome.interrupted else spoken,
            step_id=step_id,
        )
        if outcome.interrupted:
            # `_arm` resets `speech_seen`, and the caller is mid-sentence. They
            # are not starting a turn, they are already in one.
            self._endpointer.note_speech()

    # -- the inbound audio -------------------------------------------------

    def _on_track_subscribed(
        self, track: rtc.Track, publication: Any, participant: rtc.RemoteParticipant
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        self._trace(
            "media.track_subscribed",
            participant=participant.identity,
            sid=getattr(publication, "sid", ""),
        )
        self._spawn(self._pump(track), name="lk-audio-pump")

    async def _pump(self, track: rtc.Track) -> None:
        """Caller's microphone → VAD, recogniser and level meter.

        One stream, asked for the rate and the frame size we want rather than
        resampled afterwards: §1.4.2 says the pipeline is fed "at real-time
        pace, in 20 ms frames", and asking the SDK for exactly that is how the
        VAD's hangover and the endpointer's silence arithmetic stay in the same
        units as §2.3's table.
        """
        stream = rtc.AudioStream(
            track,
            sample_rate=self.rate,
            num_channels=1,
            frame_size_ms=FRAME_MS,
        )
        silence = b"\x00" * (self.rate * 2 * FRAME_MS // 1000)
        try:
            async for event in stream:
                frame = event.frame
                pcm = bytes(frame.data)
                self.stats.frames_in += 1
                self.stats.audio_seconds += frame.samples_per_channel / max(frame.sample_rate, 1)

                if self._vad_stream is not None:
                    self._vad_stream.push_frame(frame)
                if self._asr is not None:
                    await self._feed_recogniser(pcm, silence)
                self._meter(pcm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the track ends with the call
            self._trace("media.pump_error", error=f"{type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    async def _feed_recogniser(self, pcm: bytes, silence: bytes) -> None:
        """One frame to Transcribe — or to the hold buffer, while we speak.

        Our own voice is not the caller's turn, so while the agent is speaking
        the recogniser is fed silence (which also keeps the stream alive across
        a long reply instead of letting Transcribe time it out) and the real
        frames go to a short hold. On barge-in `_barge_in` moves the hold to
        `_hold_drain` and clears `_speaking`, so the very next frame through
        here replays the caller's first syllables into the recogniser ahead of
        the live audio. See `ECHO_HOLD_MS` for why the hold is short.
        """
        assert self._asr is not None
        if self._speaking:
            self._echo_hold.append(pcm)
            await self._asr.send(silence)
            return
        if self._hold_drain:
            held, self._hold_drain = self._hold_drain, []
            for frame in held:
                await self._asr.send(frame)
        await self._asr.send(pcm)

    def _meter(self, pcm: bytes) -> None:
        level = dbfs(pcm)
        self._peak_dbfs = max(self._peak_dbfs, level)
        now = time.time()
        if now - self._last_level_at < 1.0 / LEVEL_HZ:
            return
        self._last_level_at = now
        self._send(
            {
                "type": "audio.level",
                "dbfs": level,
                "peak_dbfs": self._peak_dbfs,
                "frames": self.stats.frames_in,
                "sample_rate": self.rate,
                "speaking": self._endpointer.speech_seen and not self._speaking,
            }
        )
        self._peak_dbfs = MIN_DBFS

    # -- the recogniser ----------------------------------------------------

    async def _start_recogniser(self) -> None:
        if not self.settings.use_transcribe:
            self._trace("asr.disabled", reason="ROVE_USE_TRANSCRIBE is off")
            return
        stream = transcribe.TranscribeStream(
            sample_rate=self.rate,
            region=self.settings.transcribe_region or None,
            vocabulary_name=self.settings.transcribe_vocabulary,
            on_partial=self._on_partial,
        )
        try:
            await stream.start()
        except transcribe.TranscribeUnavailable as exc:
            # §2.4 tier 4: the session degrades to typed-only rather than
            # ending. The page is told, because a user who can see that the
            # microphone is not being heard will type instead of repeating
            # themselves.
            self.stats.asr_error = str(exc)
            self._trace("asr.unavailable", error=str(exc))
            self._send({"type": "asr.state", "available": False, "detail": str(exc)})
            return
        self._asr = stream
        self.stats.transcribing = True
        self._cursor = stream.cursor()
        self._trace(
            "asr.started",
            vendor="amazon-transcribe-streaming",
            vocabulary=self.settings.transcribe_vocabulary or None,
            sample_rate=self.rate,
        )
        self._send(
            {
                "type": "asr.state",
                "available": True,
                "vocabulary": self.settings.transcribe_vocabulary or None,
            }
        )

    def _on_partial(self, partial: transcribe.Partial) -> None:
        """Every hypothesis, straight to the §1.4 transcript panel.

        §1.4: "ASR partials may be shown greyed; finals replace them." The
        surface string is normalised first, because what the user reads has to
        be what a user who *typed* it would have typed — see
        `server/transcribe.py`.
        """
        if self._speaking:
            return
        text = transcribe.normalise(partial.text)
        self._send(
            {
                "type": "asr.partial",
                "text": text,
                "is_partial": partial.is_partial,
                "confidence": partial.confidence,
            }
        )
        # §2.1: the prefetch fires off the partial, before the endpointer has
        # decided anything. Nothing it does can reach `DiagnosticState` — see
        # `server/prefetch.py` — so firing early is a cache warm and never a
        # commitment.
        self._prefetch.consider(
            text, confidence=partial.confidence, is_partial=partial.is_partial
        )

    # -- the VAD and the endpointer ---------------------------------------

    def _start_vad(self) -> None:
        """Silero VAD v5, with **our** hangover as its floor (`docs/07` D-03).

        `min_silence_duration` is set to §2.3's shortest row and no longer:
        §2.2 line 2 is "the single largest controllable line in the budget",
        and a budget line delegated to a library is not controllable. The VAD
        reports end-of-speech at 180 ms; which of §2.3's four hangovers
        actually closes the turn is `server/endpointing.py`'s decision.
        """
        vad = silero.VAD.load(
            min_silence_duration=endpointing.VAD_FLOOR_MS / 1000.0,
            min_speech_duration=self.settings.vad_start_secs,
            activation_threshold=self.settings.vad_confidence,
            sample_rate=16000,
            force_cpu=True,
        )
        self._vad_stream = vad.stream()
        self._spawn(self._vad_loop(), name="lk-vad")

    def _arm(self, *, spoken: str, step_id: str | None) -> None:
        """Choose §2.3's row for the turn the caller is about to take."""
        # §2.4 Tier 1 — "drop the semantic endpoint classifier back to fixed
        # hangovers". Applied at arming rather than at evaluation so that one
        # turn is decided under one policy start to finish.
        self._endpointer.semantic_enabled = self.session.shed().semantic_endpointing
        hangover = self._endpointer.arm(
            state=self.session.state, step_id=step_id, spoken=spoken
        )
        self._cursor = self._asr.cursor() if self._asr is not None else 0
        # A new caller turn: any speculation left from the last one is about a
        # sentence that has already been answered (`server/prefetch.py`).
        self._prefetch.arm()
        self._trace(
            "endpoint.armed",
            turn_type=self._endpointer.turn_type.value,
            hangover_min_ms=hangover.min_ms,
            hangover_max_ms=hangover.max_ms,
            prompt_satisfied=self._endpointer.prompt_satisfied,
            step_id=step_id,
            fsm_state=self.session.state.state.value,
        )
        self._send(
            {
                "type": "endpoint.armed",
                "turn_type": self._endpointer.turn_type.value,
                "hangover_min_ms": hangover.min_ms,
                "hangover_max_ms": hangover.max_ms,
            }
        )

    async def _vad_loop(self) -> None:
        assert self._vad_stream is not None
        async for event in self._vad_stream:
            if event.type == agent_vad.VADEventType.START_OF_SPEECH:
                self._on_speech_start(event)
            elif event.type == agent_vad.VADEventType.END_OF_SPEECH:
                self._on_speech_end(event)
            elif event.type == agent_vad.VADEventType.INFERENCE_DONE:
                self._on_inference(event)

    def _on_speech_start(self, event: agent_vad.VADEvent) -> None:
        """§2.1's barge-in trigger, and the ordinary start of a turn.

        One handler for both, because they are the same event: the caller
        started talking. Whether that is a turn opening or a turn being
        interrupted is decided by whether we happened to be speaking, which is
        the agent's business and not the VAD's.
        """
        speaking = self._speaking
        barged = self._barge_in(probability=float(event.probability or 0.0)) if speaking else False
        if not speaking:
            self._endpointer.note_speech()
        self._trace(
            "vad.speech_start",
            vad="silero-v5",
            probability=round(float(event.probability or 0.0), 3),
            agent_speaking=speaking,
            barge_in=barged,
        )
        self._send(
            {
                "type": "speech.start",
                "at": time.time(),
                "vad": "silero-v5",
                "barge_in": barged,
            }
        )

    def _on_speech_end(self, event: agent_vad.VADEvent) -> None:
        duration_ms = int(1000 * float(event.speech_duration or 0.0))
        self.stats.speech_segments += 1
        self._trace(
            "vad.speech_end",
            vad="silero-v5",
            duration_ms=duration_ms,
            # The VAD's own floor, not the hangover that will close the turn:
            # §2.3's number is the endpointer's and appears on `endpoint.fired`.
            vad_floor_ms=endpointing.VAD_FLOOR_MS,
            segment=self.stats.speech_segments,
            agent_speaking=self._speaking,
        )
        self._send(
            {
                "type": "speech.end",
                "at": time.time(),
                "duration_ms": duration_ms,
                "segment": self.stats.speech_segments,
            }
        )

    def _on_inference(self, event: agent_vad.VADEvent) -> None:
        """§2.3's decision, once per inference window of silence.

        `silence_duration` is the publisher-level accumulator: zero while
        speaking, and counting up from the VAD's own 180 ms floor once speech
        has ended. That is exactly the quantity §2.3's table is written in.
        """
        if event.speaking or self._speaking:
            return
        if not self._endpointer.speech_seen or self._turn_pending or self._turn_gate.locked():
            return
        if self._asr is None:
            return
        partial = self._asr.text_since(self._cursor)
        decision = self._endpointer.evaluate(
            silence_ms=1000.0 * float(event.silence_duration or 0.0),
            partial=partial,
        )
        if decision.fired:
            self._turn_pending = True
            self._spawn(self._close_turn(decision), name="lk-turn")

    # -- the turn ----------------------------------------------------------

    async def _close_turn(self, decision: endpointing.EndpointDecision) -> None:
        try:
            await self._run_turn(decision)
        finally:
            self._turn_pending = False

    async def _run_turn(self, decision: endpointing.EndpointDecision) -> None:
        if self._turn_gate.locked():
            return
        async with self._turn_gate:
            # §2.2's clock starts at **end of speech**, which is `silence_ms`
            # of audio time before the endpointer decided anything. Everything
            # below is measured against this instant, so M7 is one wall clock
            # rather than a sum of lines that could quietly double-count.
            fired_at = time.perf_counter()
            end_of_speech_at = fired_at - (decision.silence_ms / 1000.0)
            self.stats.endpoints_fired += 1
            self._trace(
                "endpoint.fired",
                turn_type=decision.turn_type.value,
                # §2.2 line 2: the hangover actually used, and the silence that
                # satisfied it. The gap between them is the decision's cost.
                hangover_ms=decision.hangover_ms,
                silence_ms=decision.silence_ms,
                completeness=decision.completeness,
                reason=decision.reason,
            )
            self._send(
                {
                    "type": "endpoint.fired",
                    "turn_type": decision.turn_type.value,
                    "hangover_ms": decision.hangover_ms,
                    "silence_ms": decision.silence_ms,
                    "completeness": decision.completeness,
                    "reason": decision.reason,
                }
            )

            assert self._asr is not None
            # §2.2 line 3 — finalisation and punctuation, nothing else.
            flush_ms = await self._asr.await_final(
                self._cursor, timeout=FINAL_FLUSH_TIMEOUT_S
            )
            heard = self._asr.text_since(self._cursor)
            confidence = self._asr.confidence_since(self._cursor)
            self._cursor = self._asr.cursor()
            text = transcribe.normalise(heard)
            if not text:
                self._trace("turn.voice_empty", asr_flush_ms=flush_ms)
                self._prefetch.claim("")
                self._arm(spoken="", step_id=self._last_step_id())
                return

            # §2.1: settle the speculation against the final transcript. The
            # result is recorded and never acted on — the turn below runs the
            # real retrieval either way, and a hit means it finds the work
            # already done rather than that it skips it.
            claimed = self._prefetch.claim(text)

            # §3.4: the alias table yields *candidates*, never resolved values.
            # They go into the trace beside the turn so a mis-heard model is
            # visible as a candidate rather than as a branch.
            candidates = transcribe.alias_candidates(heard)
            self.stats.voice_turns += 1
            self._trace(
                "turn.voice",
                verbatim=heard,
                normalised=text,
                asr_flush_ms=flush_ms,
                confidence=confidence,
                turn_type=decision.turn_type.value,
                asr_candidates=[
                    {"token": c.token, "surface": c.surface, "confidence": c.confidence}
                    for c in candidates
                ],
                # §2.2 line 5: `0 ms on a prefetch hit`. What that means in
                # practice is on `prefetch.hit`; this says which turn it was.
                prefetch=claimed.kind,
            )

            # §2.4's ladder decides here, one step before the turn runs,
            # because Tier 0's cover has to be *spoken* before the work starts
            # and Tiers 1–4 have to ride into the core call with it.
            shed = self.session.shed_for_turn(self.session.state.turn + 1)
            first_audible = "reply"
            first_audio_at = 0.0
            if shed.filler:
                # §2.4 Tier 0: "Emit a short, honest filler through TTS
                # immediately." It is the first audible thing the caller
                # hears, so it is what M7 is measured to — and the record says
                # `filler`, so the median is not quietly flattered by it.
                cover = await self._speak(ladder_module.FILLER_TEXT, kind="filler")
                if cover.first_audio_at:
                    first_audible = "filler"
                    first_audio_at = cover.first_audio_at

            payload = await self._dispatch(text, confidence, shed=shed)
            if payload is None:
                self._arm(spoken="", step_id=self._last_step_id())
                return
            step_id = (payload.get("step") or {}).get("step_id")
            outcome = await self._speak(payload.get("text", ""), step_id=step_id)
            if not first_audio_at:
                first_audio_at = outcome.first_audio_at

            self._record_latency(
                decision=decision,
                end_of_speech_at=end_of_speech_at,
                flush_ms=flush_ms,
                tts=outcome,
                first_audible=first_audible,
                first_audio_at=first_audio_at,
                prefetch_kind=claimed.kind,
                shed=shed,
            )
            self._finish_utterance(outcome, spoken=payload.get("text", ""), step_id=step_id)

            event = self._advance_ladder()
            if event is not None and event.tier >= 5:
                # §2.4 Tier 5: "Tell the user plainly that the connection is
                # struggling." The §5.3 same-session join itself is Phase 4's
                # (`server/support.py`); what this tier owes the caller now is
                # the truth, and §5.3's rule is that we never announce a join
                # that has not happened.
                notice = await self._speak(ladder_module.TIER5_TEXT, kind="ladder")
                self._finish_utterance(
                    notice, spoken=ladder_module.TIER5_TEXT, step_id=step_id
                )

    # -- §2.2's nine lines, and §2.4's response to them --------------------

    def _record_latency(
        self,
        *,
        decision: endpointing.EndpointDecision,
        end_of_speech_at: float,
        flush_ms: float,
        tts: SpeechOutcome,
        first_audible: str,
        first_audio_at: float,
        prefetch_kind: str,
        shed: Any,
    ) -> None:
        """One `latency.turn` event: §2.2's nine lines for this turn (§7.5).

        Seven of the nine are filled. Lines 1 and 9 are not, and the record
        says :data:`~server.latency.UNMEASURED` rather than carrying the
        loopback numbers this process *could* produce — `server/README.md`
        has said since Phase 2b why a sub-millisecond RTT between two
        processes on one host is not evidence about a browser on broadband,
        and quoting it as line 1 would be the exact mistake that note exists
        to prevent.
        """
        record = latency.TurnLatency(
            turn=self.session.state.turn,
            modality="voice",
            # §2.2 line 2 — the silence the endpointer waited out. This *is*
            # the endpoint decision's cost: end of speech was `silence_ms` ago.
            line2_ms=round(float(decision.silence_ms), 2),
            line3_ms=round(float(flush_ms), 2),
            line7_ms=round(float(tts.first_audio_ms), 2) if tts.first_audio_ms else None,
            turn_type=decision.turn_type.value,
            hangover_ms=decision.hangover_ms,
            prefetch=prefetch_kind,
            first_audible=first_audible,
            ladder_tier=getattr(shed, "tier", 0),
        )
        breakdown = self.session.last_core_breakdown
        if breakdown is not None:
            record.apply_core(breakdown)
        if first_audio_at:
            record.m7_server_ms = round((first_audio_at - end_of_speech_at) * 1000.0, 2)
        elif tts.failed:
            record.notes = f"no audio: {tts.failed}"
        self.session.latency.record(record)
        self._trace("latency.turn", **record.as_event())

    def _advance_ladder(self) -> Any:
        """Re-read §2.4's triggers now this turn's numbers are in the book."""
        rung = self.session.ladder
        if rung is None:
            return None
        breakdown = self.session.last_core_breakdown
        if breakdown is not None:
            # §2.4 Tier 3's second trigger: "or primary LLM erroring". The
            # core catches the exception and answers from its rule-based
            # floor, so the only place in the process that sees one is the
            # wrapper that timed the call.
            rung.model_erroring = breakdown.llm_errors > 0
        return rung.evaluate()

    async def _dispatch(
        self, text: str, confidence: float, *, shed: Any = None
    ) -> dict[str, Any] | None:
        """Hand the turn to the API loop, where every turn is run.

        §1.4.1 item 2: a click, a typed string and a transcribed utterance are
        the same event type. Making the voice path use the *same* dispatcher —
        on the same loop, behind the same per-room lock — is what makes that
        true in code rather than in a comment, and it is what M10 measures.
        """
        future = self.host.dispatch_turn(
            self.session, text, modality="voice", confidence=confidence, shed=shed
        )
        try:
            return await asyncio.wrap_future(future)
        except Exception as exc:  # noqa: BLE001 — a failed turn is not a failed call
            self._trace("turn.failed", error=f"{type(exc).__name__}: {exc}", modality="voice")
            self.host.publish(
                self.session.room, {"type": "error", "detail": f"turn failed: {exc}"}
            )
            return None

    def _last_step_id(self) -> str | None:
        result = self.session.last_result
        return (result.get("step") or {}).get("step_id") if result else None

    # -- turns that arrived some other way ---------------------------------

    def on_external_turn(self, payload: dict[str, Any]) -> None:
        """A typed or clicked turn was answered: speak it and re-arm.

        Called from the API loop, so it must not block and must not await.
        §1.4.1 item 3 is the requirement: "a user who types the SSID in turn 4
        and then speaks turn 5 has one session". The agent speaking the reply
        to a typed turn is what makes that one session rather than two.
        """
        if self._closed.is_set():
            return
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(
                lambda: self._spawn(self._speak_external(payload), name="lk-external")
            )

    async def _speak_external(self, payload: dict[str, Any]) -> None:
        async with self._turn_gate:
            step_id = (payload.get("step") or {}).get("step_id")
            outcome = await self._speak(payload.get("text", ""), step_id=step_id)
            self._finish_utterance(outcome, spoken=payload.get("text", ""), step_id=step_id)

    def note_typing(self) -> None:
        """§2.3: someone part-way through typing an SSID has not finished."""
        self._endpointer.note_typing()

    # -- room events -------------------------------------------------------

    def _on_data_received(self, packet: rtc.DataPacket) -> None:
        try:
            message = json.loads(bytes(packet.data))
        except (ValueError, TypeError):
            return
        if not isinstance(message, dict):
            return
        if message.get("type") == "user.typing":
            self.note_typing()

    def _on_participant_left(self, participant: rtc.RemoteParticipant) -> None:
        self._trace("media.participant_left", participant=participant.identity)
        if not self.ctx.room.remote_participants:
            self._loop.call_soon_threadsafe(self._closed.set)

    def _on_disconnected(self, *_args: Any) -> None:
        self._loop.call_soon_threadsafe(self._closed.set)


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------


async def entrypoint(ctx: JobContext) -> None:
    """One job: one room, one caller, one agent.

    LiveKit dispatches this when a room we minted a token for comes into
    existence. A room we did **not** mint for gets connected to and immediately
    left: the agent has no `DiagnosticState` for it, and joining a session we
    cannot reason about would put a silent participant in somebody's room.
    """
    host = current_host()
    room_name = ctx.room.name or (ctx.job.room.name if ctx.job and ctx.job.room else "")
    if host is None:
        return
    session = host.session_for(room_name)
    if session is None:
        return
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    agent = RoomVoiceAgent(ctx=ctx, session=session, host=host)
    try:
        await agent.run()
    finally:
        await agent.aclose()


@dataclass
class AgentWorker:
    """The `livekit-agents` worker, started and stopped with the API process.

    One worker serves every room: LiveKit dispatches a job per room and the
    worker runs them concurrently, which is the same shape a separate worker
    deployment would have. What in-process buys is the object reference to
    `Session`; what it costs is that the API process and the media work share
    an interpreter. `docs/06` §2.2 says the two transport lines total 55 ms and
    `docs/07` D-02's flip to Ten Framework is gated on measuring them *after*
    lines 2, 6 and 7 — so this is the right side of that ordering to start on.
    """

    host: AgentHost
    server: Any = None
    task: asyncio.Task | None = None
    error: str = ""
    _started: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self) -> None:
        settings = self.host.settings
        options = WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            # The job runs in this process, on its own loop, so it can reach
            # the `Session` the API process is holding. See the module
            # docstring for what a separate process would need instead.
            job_executor_type=JobExecutorType.THREAD,
            num_idle_processes=0,
        )
        global _HOST
        with _HOST_LOCK:
            _HOST = self.host
        self.server = AgentServer.from_server_options(options)
        self.task = asyncio.create_task(self._run(), name="livekit-worker")

    async def _run(self) -> None:
        assert self.server is not None
        try:
            await self.server.run(devmode=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — no media server, bad keys
            self.error = f"{type(exc).__name__}: {exc}"

    async def wait_registered(self, timeout: float = 30.0) -> bool:
        """Block until the worker has registered with the media server."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.error:
                return False
            worker_id = getattr(self.server, "id", "") if self.server else ""
            if worker_id:
                return True
            await asyncio.sleep(0.1)
        return False

    async def stop(self) -> None:
        global _HOST
        with _HOST_LOCK:
            if _HOST is self.host:
                _HOST = None
        if self.server is not None:
            with contextlib.suppress(Exception):
                await self.server.aclose()
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        self.task = None
        self.server = None
