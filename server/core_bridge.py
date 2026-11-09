"""The click-or-type path, wired to the existing diagnostic core (`docs/06` §1.4).

§1.4 puts a text field on the page "for strings the voice channel mangles —
SSIDs, serial numbers, card markings, error text", and §1.4.1 states the rule
that makes it safe:

> A click, a typed string and a transcribed utterance enter the turn dispatcher
> as the **same** event type, carrying `{value, modality, confidence}`. The FSM
> and the policy layer read `value`; they may not branch on `modality`.

So this module is a dispatcher and nothing else. A typed turn is one call to
`agent.core.diagnose` — the same function `eval/`'s harnesses call, with the
same `DiagnosticState` — and the modality rides into the **trace**, never into
the core. That is not tidiness: §7.2's **M10** measures that the branch taken
is identical whichever modality the answer arrived by, and a dispatcher that
passed modality down would make M10 unmeasurable by making it untrue.

`DiagnosticState` lives here, server-side, for the same reason §1.4.2 gives:
"a dropped connection costs the in-flight turn and nothing else". The browser
holds a projection (:func:`project_state`); a reload or a re-join replays it.

Two things this module does **not** do. It does not reimplement any part of the
core — there is no second copy of the policy filter, the guard or the ladder
here, and `agent/` is not modified. And it does not feed the voice channel into
the core: Phase 2b has a VAD and no ASR, so there is no transcript to dispatch.
That wiring is Phase 3 (`docs/06` §9.1), and it enters at exactly this
function with `modality="voice"`.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import core as agent_core
from agent.state import DiagnosticState
from eval import ontology
from server import ladder as ladder_module
from server import latency, prefetch
from server import tokens as token_module
from server.consent import ConsentState
from server.trace import Trace

#: §1.4.1: typed input is higher-confidence than ASR for the fields §3.4 calls
#: confusable. Phase 2b has no ASR, so every turn that reaches the core is
#: typed and carries this.
TYPED_CONFIDENCE = 1.0

#: The agent is driving: it proposes the next diagnostic step each turn.
AGENT_MODE_PROPOSING = "proposing"

#: A human is in the room (`docs/06` §5.3). The agent "stops proposing steps
#: and drops to transcribing and recording the ledger" — so a caller turn in
#: this mode is still a transcript line, still a trace event and still part of
#: the handoff panel, and is **not** dispatched into `agent.core.diagnose` at
#: all. The gate is here, at the dispatcher, rather than inside the core:
#: `agent/` decides what the *next step* is, and "there should not be a next
#: step" is not a diagnostic judgement, it is a fact about who is in the room.
#: Phrasing it as a filter inside the core would also make §7.2's M10
#: unmeasurable, because the branch taken would start depending on something
#: other than the caller's answer.
AGENT_MODE_TRANSCRIBING = "transcribing"

AGENT_MODES = (AGENT_MODE_PROPOSING, AGENT_MODE_TRANSCRIBING)


@dataclass
class TranscriptLine:
    """One line of the §1.4 transcript panel, as the server remembers it."""

    role: str  # caller | agent
    text: str
    modality: str = "typed"  # typed | click | voice
    confidence: float = TYPED_CONFIDENCE
    turn: int = 0
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "modality": self.modality,
            "confidence": self.confidence,
            "turn": self.turn,
            "at": self.at,
        }


@dataclass
class Participant:
    """A second party admitted to the room (`docs/06` §5.3, `docs/07` D-17).

    "Escalation admits a second participant to the room the user is already
    in." A row per admission, kept after they leave, because the handoff panel
    and the trace both want to say *who was in the room when* rather than
    *who is in it now*.
    """

    identity: str
    display_name: str = ""
    role: str = "support"
    joined_at: float = field(default_factory=time.time)
    left_at: float | None = None

    @property
    def present(self) -> bool:
        return self.left_at is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "display_name": self.display_name,
            "role": self.role,
            "joined_at": self.joined_at,
            "left_at": self.left_at,
            "present": self.present,
        }


@dataclass
class Session:
    """One room, one caller, one `DiagnosticState`, one trace."""

    room: str
    identity: str
    session_id: str
    state: DiagnosticState
    trace: Trace
    created_at: float = field(default_factory=time.time)
    transcript: list[TranscriptLine] = field(default_factory=list)
    last_result: dict[str, Any] | None = None
    #: Open control sockets for this room. The media path is separate.
    listeners: set[Any] = field(default_factory=set)
    #: Open **support console** sockets (`docs/06` §5.3). A separate set from
    #: `listeners` on purpose: both receive the session feed, only one of them
    #: may send a caller turn, and keeping them apart means that difference is
    #: a property of which set a socket is in rather than of a flag somebody
    #: has to remember to check.
    observers: set[Any] = field(default_factory=set)
    #: Observer identities this room has issued a token for. An observer token
    #: is only accepted for the room *and* the identity it was minted with.
    observer_identities: set[str] = field(default_factory=set)
    #: Humans admitted to the room, in order of admission (§5.3).
    participants: list[Participant] = field(default_factory=list)
    #: §5.3: `proposing` until a human joins, `transcribing` afterwards.
    agent_mode: str = AGENT_MODE_PROPOSING
    #: §6.3. Two decisions, and nothing is stored until the storage one exists.
    consent: ConsentState = field(default_factory=ConsentState)
    #: The live Pipecat worker and its connection, when a peer is attached.
    #: Only the `smallwebrtc` fallback sets this (`docs/07` D-02).
    media: Any = None
    #: The `RoomVoiceAgent` for this room, while the LiveKit worker has a job
    #: in it. Set by the agent on join and cleared on leave, so the API process
    #: can hand it a typed turn to speak (§1.4.1 item 3: one session, whichever
    #: modality the turn arrived by) without knowing how it joined.
    voice: Any = None
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: §2.2's nine lines, per turn, for this session (`server/latency.py`).
    #: Lives on the `Session` rather than on the voice agent because a typed
    #: turn is measured too — §2.2 lines 4, 5, 6 and 8 are the same lines
    #: whichever modality asked the question, and §7.2's M7 is the one that is
    #: voice-only.
    latency: latency.LatencyBook = field(default_factory=latency.LatencyBook)
    #: §2.4's graded ladder over that book. Attached by `server/app.py`, which
    #: owns the trace callback it logs through.
    ladder: Any = None
    #: The last turn's §2.2 lines 4/5/6/8, for the voice path to build the
    #: nine-line record round. Overwritten per turn and never read across one.
    last_core_breakdown: Any = None

    def shed(self) -> Any:
        """What §2.4's current tier sheds. Pure; never `None`."""
        if self.ladder is None:
            return ladder_module.Shed()
        return self.ladder.shed()

    def shed_for_turn(self, turn: int) -> Any:
        """The same, plus §2.4's Tier-0 decision. Once per turn — see
        `server/ladder.Ladder.shed_for_turn`."""
        if self.ladder is None:
            return ladder_module.Shed()
        return self.ladder.shed_for_turn(turn)

    def add_line(self, line: TranscriptLine) -> TranscriptLine:
        self.transcript.append(line)
        return line

    # -- §5.3 same-session join -------------------------------------------

    @property
    def humans_present(self) -> list[Participant]:
        return [p for p in self.participants if p.present]

    def participant(self, identity: str) -> Participant | None:
        for entry in self.participants:
            if entry.identity == identity:
                return entry
        return None

    def set_agent_mode(self, mode: str, *, reason: str) -> str:
        """Flip the agent between proposing and transcribing (§5.3).

        Mirrored into `DiagnosticState.notes` — a free-form dict the core
        already owns and never branches on — so that the mode travels with the
        state into the handoff panel and anything that snapshots the session,
        without `agent/` growing a field about who is in the room.
        """
        if mode not in AGENT_MODES:
            raise ValueError(f"agent mode must be one of {AGENT_MODES}, got {mode!r}")
        previous, self.agent_mode = self.agent_mode, mode
        self.state.notes["agent_mode"] = mode
        if previous != mode:
            self.trace.event(
                "agent.mode",
                mode=mode,
                previous=previous,
                reason=reason,
                turn=self.state.turn,
                humans_present=[p.identity for p in self.humans_present],
            )
        return previous


class SessionRegistry:
    """Rooms, by id. One room per session (§1.4.2)."""

    def __init__(self, *, trace_dir: Path | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._trace_dir = trace_dir

    def create(self, *, room: str | None = None, identity: str | None = None) -> Session:
        room = room or token_module.new_room_id()
        identity = identity or token_module.new_identity()
        session_id = f"{room}-{uuid.uuid4().hex[:8]}"
        session = Session(
            room=room,
            identity=identity,
            session_id=session_id,
            state=DiagnosticState(session_id=session_id),
            trace=Trace(
                session_id=session_id,
                room=room,
                identity=identity,
                directory=self._trace_dir,
            ),
        )
        with self._lock:
            self._sessions[room] = session
        return session

    def get(self, room: str) -> Session | None:
        with self._lock:
            return self._sessions.get(room)

    def rooms(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def drop(self, room: str) -> Session | None:
        with self._lock:
            return self._sessions.pop(room, None)


# --------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------


def run_typed_turn(
    session: Session,
    text: str,
    *,
    modality: str = "typed",
    confidence: float = TYPED_CONFIDENCE,
    llm: Any | None = None,
    chunks_path: str | None = None,
    shed: Any = None,
) -> dict[str, Any]:
    """Dispatch one caller answer into the core and project the result.

    Synchronous, because `agent.core.diagnose` is: the caller runs it off the
    event loop (see :func:`run_typed_turn_async`), which is also what `docs/07`
    D-14 means by "no blocking calls on the media path".

    `shed` is §2.4's `server/ladder.Shed` for this turn, or `None` for the
    un-shed pipeline. It is read in exactly two places — the retrieval
    wrappers `server/latency.py` installs, and the model handle — and it
    cannot reach the policy filter, the destructive gate or the output guard,
    because §2.4 forbids buying latency with any of them.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty turn")

    # One number for the trace event, the transcript line and — when the core
    # is not being called — the counter itself. `agent.core.begin_turn` owns
    # `state.turn` and bumps it on entry, so this is what it is about to be.
    turn_number = session.state.turn + 1

    session.trace.event(
        "turn.user",
        value=text,
        modality=modality,
        confidence=confidence,
        turn=turn_number,
        agent_mode=session.agent_mode,
    )
    session.add_line(
        TranscriptLine(
            role="caller",
            text=text,
            modality=modality,
            confidence=confidence,
            turn=turn_number,
        )
    )

    if session.agent_mode == AGENT_MODE_TRANSCRIBING:
        # §5.3: "The agent announces the join, stops proposing steps, and
        # drops to transcribing and recording the ledger." The caller's words
        # are kept — transcript line above, trace event above, handoff panel
        # live — and the core is simply not asked for a next step. It is not
        # asked and then ignored: a step the policy layer computed and nobody
        # spoke would still enter the ledger's no-repeat accounting (§3.5) and
        # would make a later M4 reading wrong about what was actually tried.
        # `agent.core.begin_turn` advances `state.turn`, and it is not being
        # called, so the counter is advanced here instead. §5.3 drops the agent
        # to "transcribing and recording the ledger" — a record in which three
        # answers after the join all read "turn 4" is not a record of what
        # happened, and the handoff panel, the transcript line above and the
        # trace event above all stamp themselves from this number.
        session.state.turn = turn_number
        session.trace.event(
            "turn.not_proposed",
            turn=turn_number,
            reason="a human is in the room (§5.3)",
            humans_present=[p.identity for p in session.humans_present],
        )
        payload = {
            "text": "",
            "suppressed": True,
            "agent_mode": session.agent_mode,
            "step": None,
            "taxonomy_id": session.state.problem.taxonomy_id,
            "category": session.state.problem.category,
            "escalate": session.state.escalation.triggered,
            "citations": [],
            "rationale": "agent is transcribing — a human is in the room (§5.3)",
            "dropped_claims": [],
            "state": project_state(session.state),
            "latency_ms": 0.0,
            "modality": modality,
        }
        session.last_result = payload
        return payload

    started = time.perf_counter()
    # §2.2 lines 4, 5, 6 and 8, taken apart from outside `agent/`. The block
    # also carries the shed: `server/latency.py`'s wrappers read it off the
    # same thread-local, so a tier can never outlive the turn that chose it.
    with latency.measure_core(shed) as breakdown:
        # `server/prefetch.py` item 3: `agent/store.py` keeps one connection
        # and says why — *"the agent is single-threaded per turn and a pool
        # would be ceremony"*. The speculative retrieval runs on another
        # thread, so the real turn takes the lock **blocking** and speculation
        # takes it non-blocking. Taking it here rather than inside `agent/` is
        # deliberate: the constraint is "one caller of the store at a time in
        # this process", which is a fact about this process rather than about
        # the core.
        with prefetch.CORE_LOCK:
            result = agent_core.diagnose(
                text,
                session.state,
                llm=latency.timed_llm(llm, breakdown, shed),
                chunks_path=chunks_path,
                thread_id=session.session_id,
            )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    payload = project_turn(result, session.state)
    payload["latency_ms"] = elapsed_ms
    payload["latency_breakdown"] = breakdown.as_dict()
    # The object itself, for the voice path, which assembles the other five
    # lines round it. Kept on the `Session` rather than in the payload because
    # the payload is JSON on a WebSocket a moment later, and it is safe to
    # keep there because the per-room turn lock means one turn at a time.
    session.last_core_breakdown = breakdown
    payload["modality"] = modality
    payload["suppressed"] = False
    payload["agent_mode"] = session.agent_mode
    session.add_line(
        TranscriptLine(
            role="agent",
            text=result.response_text,
            modality="text",
            turn=session.state.turn,
        )
    )
    session.last_result = payload
    session.trace.event(
        "turn.reply",
        turn=session.state.turn,
        text=result.response_text,
        step_id=result.step_id,
        taxonomy_id=result.taxonomy_id,
        category=result.category,
        escalate=result.escalate,
        citations=result.citations,
        dropped_claims=result.dropped_claims,
        fsm_state=str(session.state.state.value),
        latency_ms=elapsed_ms,
        # §2.2 lines 4, 5, 6 and 8 for this turn. §7.5 wants the nine-line
        # decomposition in the per-turn record; the voice path writes the whole
        # nine as `latency.turn`, and this is the part a typed turn also has.
        latency_breakdown=breakdown.as_dict(),
        ladder_tier=getattr(shed, "tier", 0),
        # §1.4.1 item 2: the branch is recorded with the modality that produced
        # it, which is what makes M10 computable from a trace.
        modality=modality,
    )
    return payload


async def run_typed_turn_async(session: Session, text: str, **kwargs: Any) -> dict[str, Any]:
    """`run_typed_turn` on a worker thread, one turn at a time per room."""
    async with session.turn_lock:
        return await asyncio.to_thread(run_typed_turn, session, text, **kwargs)


# --------------------------------------------------------------------------
# Barge-in: the turn the caller talked over (docs/06 §2.1)
# --------------------------------------------------------------------------

#: How many interruptions a session keeps in full. The last one is what the
#: §1.4 panel renders; the rest are the record, and a session that is being
#: interrupted hundreds of times has a different problem than a short list.
MAX_INTERRUPTIONS_HELD = 50


def note_interruption(
    session: Session,
    *,
    kind: str,
    step_id: str | None,
    text: str,
    spoken_prefix: str,
    remainder: str,
    sub_step_index: int,
    at_ms: float,
    played_ms: int,
) -> dict[str, Any]:
    """Record that the caller talked over the agent, without losing the turn.

    `docs/06` §2.1 is specific about what barge-in must *not* do:

    > the agent **re-anchors rather than restarting**: the diagnostic state
    > records exactly how far through the proposed step it got (`step_id`,
    > `sub_step_index`, `spoken_prefix`), so the resume phrasing can be
    > "sorry — you were saying?" followed, when appropriate, by continuing from
    > the un-spoken remainder, not from the top. The un-spoken remainder is
    > still on screen (§1.4).

    So three things happen here and none of them is "discard the turn":

    1. The reply stays in the transcript exactly as it was composed. It was
       appended by :func:`run_typed_turn` before a sample was synthesised, and
       nothing below removes or rewrites it — the agent *said* that, the caller
       heard part of it, and a transcript that quietly dropped it would make
       the ledger and the §5.2 handoff panel disagree with the session.
    2. The three fields §2.1 names go into `DiagnosticState.notes`, which is
       the free-form dict the core already owns and **never branches on** (it
       is where `agent_mode` lives, for the same reason). The record travels
       with the state into the handoff payload and every snapshot, and `agent/`
       does not grow a field about who stopped talking.
    3. `project_state` publishes it, so §2.1's "the un-spoken remainder is
       still on screen" is a rendered fact rather than an intention.

    Nothing here advances the FSM or the ledger. Being interrupted is not a
    diagnostic event: the step was proposed, and whether the caller acts on it
    is still decided by what they say next.
    """
    record = {
        "turn": session.state.turn,
        "step_id": step_id,
        "kind": kind,
        "text": text,
        "spoken_prefix": spoken_prefix,
        "remainder": remainder,
        "sub_step_index": sub_step_index,
        "at_ms": round(at_ms, 1),
        "played_ms": played_ms,
        "at": time.time(),
    }
    notes = session.state.notes
    history = notes.get("interruptions")
    if not isinstance(history, list):
        history = []
    history.append(record)
    del history[:-MAX_INTERRUPTIONS_HELD]
    notes["interruptions"] = history
    notes["interruption"] = record
    session.trace.event("turn.interrupted", **record)
    return record


# --------------------------------------------------------------------------
# Fan-out
# --------------------------------------------------------------------------


async def fanout(
    session: Session,
    message: dict[str, Any],
    *,
    caller: bool = True,
    observers: bool = True,
) -> None:
    """Send one message to the open sockets for this room.

    Two sets, addressed separately. The caller's page and the support console
    see the same session, but not every message belongs to both: a console note
    is not the caller's business, and the caller's own control replies are not
    the console's. Which set a message goes to is stated at every call site.
    """
    targets: list[tuple[set[Any], Any]] = []
    if caller:
        targets.append((session.listeners, None))
    if observers:
        targets.append((session.observers, None))
    for sockets, _ in targets:
        dead = []
        for socket in list(sockets):
            try:
                await socket.send_json(message)
            except Exception:  # noqa: BLE001 — a dead page is not a dead session
                dead.append(socket)
        for socket in dead:
            sockets.discard(socket)


# --------------------------------------------------------------------------
# Projections for the UI (docs/06 §1.4, §3.3)
# --------------------------------------------------------------------------


def _step_view(step_id: str | None) -> dict[str, Any] | None:
    """The §1.4 "current diagnostic step" panel: the one action, in text.

    Spoken form, not the ontology description — §1.4 says the step is shown
    "exactly as spoken", and `agent.core.spoken_form` is what produces that.
    """
    if not step_id:
        return None
    step = ontology.STEPS.get(step_id)
    return {
        "step_id": step_id,
        "spoken": agent_core.spoken_form(step_id),
        "description": step.description if step else "",
        "family": step.family if step else "",
        "destructive": bool(step.destructive) if step else False,
    }


def project_state(state: DiagnosticState) -> dict[str, Any]:
    """`DiagnosticState` as the browser renders it (§1.4, §3.3).

    A projection, not the record: the browser owns none of this, which is why
    a reload costs nothing. Every field here is one the UI table in §1.4 asks
    for — model and confidence, the category, the attempted-step ledger as a
    visible list, and the escalation state.
    """
    return {
        "fsm_state": state.state.value,
        "turn": state.turn,
        "device": {
            "model": state.device.reported_model,
            "confidence": state.device.confidence,
            "hw_revision": state.device.hw_revision,
            "candidates": list(state.device.candidates),
            "firmware_version": state.device.firmware_version,
        },
        "problem": {
            "category": state.problem.category,
            "taxonomy_id": state.problem.taxonomy_id,
            "verbatim_symptom": state.problem.verbatim_symptom,
            "hypothesis": (
                state.problem.top_hypothesis.text if state.problem.top_hypothesis else ""
            ),
        },
        "ledger": [
            {
                "step_id": attempt.step_id,
                "outcome": attempt.outcome,
                "source": attempt.source,
                "count": attempt.count,
            }
            for attempt in state.ledger.attempted
        ],
        "answers": [
            {
                "step_id": answer.step_id,
                "reading": answer.reading,
                "modality": answer.modality,
                "verbatim": answer.verbatim,
            }
            for answer in state.answers.values()
        ],
        "safety": {
            "driving": state.safety.driving,
            "hazard_flags": list(state.safety.hazard_flags),
            "footage_at_stake": state.safety.footage_at_stake,
        },
        "escalation": {
            "triggered": state.escalation.triggered,
            "reason_code": state.escalation.reason_code,
            "reason": state.escalation.reason,
        },
        # §2.1: barge-in "re-anchors rather than restarting", and "the un-spoken
        # remainder is still on screen (§1.4), which is the one case where the
        # browser leg is strictly better than a phone call". `None` until the
        # caller first talks over the agent. See `note_interruption`.
        "interruption": state.notes.get("interruption"),
        "interruptions": len(state.notes.get("interruptions") or []),
    }


def project_turn(result: Any, state: DiagnosticState) -> dict[str, Any]:
    """One turn's reply, its step and the state it left behind."""
    # 6.4: the reply's escalate flag is the SESSION's, not just this turn's.
    # The FW-02 pin can escalate the session on the voice turn; a typed turn
    # after that closes the session off with no step of its own, and its reply
    # then carried neither a step nor an escalation -- verify_livekit check 51.
    # `state.escalation.triggered` is already the flag the other reply builder
    # (below, line ~352) reports; this one now agrees with it.
    return {
        "text": result.response_text,
        "step": _step_view(result.step_id),
        "taxonomy_id": result.taxonomy_id,
        "category": result.category,
        "escalate": result.escalate or state.escalation.triggered,
        "citations": list(result.citations),
        "rationale": result.rationale,
        "dropped_claims": list(result.dropped_claims),
        "state": project_state(state),
    }


def session_snapshot(session: Session) -> dict[str, Any]:
    """Everything the page needs to render itself from scratch.

    §6.3 governs *storage*, not display, so the transcript is in here
    regardless — "the live transcript is rendered in the browser whether or not
    it is retained". The one case it is withheld is an explicit decline of the
    display decision, which is a separate decision and the caller's to make.
    """
    return {
        "session_id": session.session_id,
        "room": session.room,
        "identity": session.identity,
        "created_at": session.created_at,
        "transcript": (
            [line.as_dict() for line in session.transcript]
            if session.consent.may_display()
            else []
        ),
        "transcript_displayed": session.consent.may_display(),
        "state": project_state(session.state),
        "step": session.last_result["step"] if session.last_result else None,
        "trace": session.trace.summary(),
        "agent_mode": session.agent_mode,
        "participants": [p.as_dict() for p in session.participants],
        "consent": session.consent.as_dict(),
    }
