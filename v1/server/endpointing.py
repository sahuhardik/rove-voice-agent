"""Context-dependent endpointing (`docs/06` §2.3, `docs/07` D-03).

§2.3 is blunt about why this module exists:

> A fixed silence threshold cannot serve this session type. The users in `01`
> §2 pause to look at a camera, to read a screen, to find a card, to answer a
> passenger. A 400 ms hangover cuts them off; a 1,200 ms hangover makes the
> agent feel dead.

So the hangover is **set by the FSM state, not globally**, and the table it is
set from is §2.3's, copied here without rounding:

| Dialogue context | Hangover |
|---|---|
| Yes/no confirmation | 180–250 ms |
| Model identification / read-back of a code or SSID | 700–900 ms |
| Open symptom description (turn 1) | 600–800 ms |
| User performing a physical action | 2,000 ms + an explicit "tell me when you've done that" |

Three layers decide end-of-turn, and they are deliberately separate things:

1. **Silero VAD v5** (`docs/07` D-03) decides, frame by frame, whether there is
   speech. That lives in `server/livekit_agent.py`; this module only consumes
   the accumulated-silence number it produces. The VAD's *own* hangover is set
   to :data:`VAD_FLOOR_MS` — the shortest we would ever wait — precisely so
   that the hangover that matters is ours and not the plugin's. §2.2 line 2 is
   "the single largest controllable line in the budget", and a budget line you
   have delegated to a library is not controllable.
2. **The context hangover**, from the table above, keyed off the FSM state and
   the step the user is answering. Between `min_ms` and `max_ms`.
3. **A lightweight semantic endpoint classifier** over the ASR partial —
   §2.3's "is this a complete thought?" — which closes a confident *"yeah it's
   on"* at the bottom of the window and holds *"it says… um…"* to the top of
   it. §2.3 is explicit that this is "a small, fast classifier, not an LLM
   call; putting an LLM in the endpoint path would blow line 6 twice per turn",
   so it is lexical and it runs in microseconds. :func:`completeness` is the
   whole of it.

And one suppressor, which is the signal §2.3 says the browser has and a phone
call does not: **the user is typing.** Keystrokes or focus in the text field
hold the turn open exactly the way continued speech does.

Nothing here touches `agent/`. The classifier reads a `DiagnosticState` and a
step id and returns a number of milliseconds; the core never learns that
endpointing happened.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent.state import State
from eval import ontology

# --------------------------------------------------------------------------
# The table (docs/06 §2.3)
# --------------------------------------------------------------------------


class TurnType(str, Enum):
    """What the user is doing while we wait. The rows of §2.3's table."""

    YES_NO = "yes_no"
    MODEL_ID_READBACK = "model_id_readback"
    OPEN_SYMPTOM = "open_symptom"
    PHYSICAL_ACTION = "physical_action"


@dataclass(frozen=True)
class Hangover:
    """One row: the window, and whether the row carries an obligation."""

    turn_type: TurnType
    min_ms: int
    max_ms: int
    #: §2.3's physical-action row is "2,000 ms **plus** explicit 'tell me when
    #: you've done that'". The prompt is part of the hangover, not a nicety:
    #: without it a two-second silence is indistinguishable from a user who has
    #: walked away, and the agent would be guessing.
    requires_explicit_prompt: bool = False

    def window_ms(self) -> tuple[int, int]:
        return self.min_ms, self.max_ms


#: §2.3's table, verbatim. These are the only four rows; a turn that matches
#: none of them is an open symptom description, which is the safe default
#: because it waits longer rather than less.
HANGOVERS: dict[TurnType, Hangover] = {
    TurnType.YES_NO: Hangover(TurnType.YES_NO, 180, 250),
    TurnType.MODEL_ID_READBACK: Hangover(TurnType.MODEL_ID_READBACK, 700, 900),
    TurnType.OPEN_SYMPTOM: Hangover(TurnType.OPEN_SYMPTOM, 600, 800),
    TurnType.PHYSICAL_ACTION: Hangover(
        TurnType.PHYSICAL_ACTION, 2000, 2000, requires_explicit_prompt=True
    ),
}

#: What Silero VAD v5 is configured with, in milliseconds: the floor of the
#: table above. The VAD must report end-of-speech no later than the shortest
#: hangover we might choose, or the 180 ms row is unreachable.
VAD_FLOOR_MS = 180

#: How long a keystroke suppresses the endpointer for. One keystroke is not a
#: sentence; somebody typing an SSID pauses between characters exactly the way
#: somebody reading one aloud does, which is why this is close to the
#: read-back row rather than to the yes/no row.
TYPING_GRACE_MS = 900

#: §2.3's physical-action prompt, matched rather than generated: the agent's
#: own words have to contain this obligation before a 2 s hangover is honest.
EXPLICIT_PROMPT_PATTERNS = (
    re.compile(r"\btell me when\b", re.I),
    re.compile(r"\blet me know when\b", re.I),
    re.compile(r"\bsay when\b", re.I),
    re.compile(r"\bonce you(?:'ve| have)\b", re.I),
)


# --------------------------------------------------------------------------
# Which row (docs/06 §2.3 ← §3.2 state, §3.6 step ontology)
# --------------------------------------------------------------------------

#: Reading characters off a screen. §2.3's second row names "a code or SSID";
#: §3.4 probe 1 and probe 5 are the steps that ask for one.
READBACK_STEPS = frozenset(
    {
        "STEP.OBSERVE.READ_SSID",
        "STEP.OBSERVE.READ_SCREEN_VERBATIM",
        "STEP.OBSERVE.READ_PASSWORD_CHARACTERWISE",
    }
)

#: Families whose steps send the user away from the screen to do something.
#: §2.3's fourth row: "They are walking to the car, away from the screen.
#: Silence is not end-of-turn."
PHYSICAL_FAMILIES = frozenset(
    {
        "FAMILY.POWER_CYCLE",
        "FAMILY.CARD_HANDLING",
        "FAMILY.PHYSICAL",
        "FAMILY.POWER_HARDWARE",
        "FAMILY.DEVICE_CONTROL",
        "FAMILY.SETTINGS_CHANGE",
        "FAMILY.DATE_TIME",
        "FAMILY.APP_STATE",
        "FAMILY.PHONE_NETWORK",
        "FAMILY.SAFETY",
        "FAMILY.DESTRUCTIVE.ERASE_CARD",
        "FAMILY.DESTRUCTIVE.RESET_DEVICE",
        "FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE",
    }
)

#: Every family in `eval.ontology` is either classified above, asked
#: (`FAMILY.ASK`), observed (`FAMILY.OBSERVE`) or an escalation — which is not
#: a user turn at all. Asserted in `server/test_livekit.py`, because a family
#: added to the ontology later would otherwise silently fall through to the
#: open-symptom default and quietly lengthen a yes/no hangover.
NON_PHYSICAL_FAMILIES = frozenset({"FAMILY.ASK", "FAMILY.OBSERVE", "FAMILY.ESCALATE"})

#: Observe steps are "look, listen, read out" (§3.6). The read-backs are their
#: own row; the rest — a shutter test, a card-removed test — are actions.
OBSERVE_FAMILY = "FAMILY.OBSERVE"
ASK_FAMILY = "FAMILY.ASK"

#: A closed question opens with one of these and expects one word back.
_CLOSED_OPENERS = re.compile(
    r"^\s*(?:and\s+|so\s+|ok(?:ay)?,?\s+|right,?\s+)?"
    r"(do|does|did|is|are|was|were|has|have|had|can|could|will|would|should|am)\b",
    re.I,
)
#: "…, or steady?" — a forced choice is closed too (§1.4 renders it as buttons).
_OR_CHOICE = re.compile(r",\s*or\b[^?]*\?", re.I)


def closed_question(text: str) -> bool:
    """Whether a prompt expects a one-word answer (§2.3 row 1).

    §1.4.1 requires the spoken phrasing to stand alone, so the spoken text is
    a fair thing to classify: "is the red light blinking, or steady?" is closed
    whether it is answered by voice or by one of the two buttons beside it.
    """
    text = (text or "").strip()
    if not text:
        return False
    # Classify the last sentence: the turn's question is at the end of it.
    tail = re.split(r"(?<=[.!?])\s+", text)[-1]
    if "?" not in tail and "?" not in text:
        return False
    question = tail if "?" in tail else text
    return bool(_CLOSED_OPENERS.match(question) or _OR_CHOICE.search(question))


def classify_turn(
    state: Any,
    *,
    step_id: str | None = None,
    spoken: str = "",
) -> TurnType:
    """Which row of §2.3's table the *next* user turn falls on.

    Args:
        state: The `DiagnosticState` as it stands after the agent's turn —
            the state the user is answering *into*.
        step_id: The step the agent just proposed, if any (`docs/06` §3.6).
        spoken: What the agent actually said, which is what decides whether a
            question is closed. §1.4.1 forbids branching on modality, and this
            does not: the same text produces the same row whether the answer
            arrives typed, clicked or spoken.

    Returns:
        The turn type. Defaults to `OPEN_SYMPTOM`, which waits longer than
        every row but the physical one — the safe direction to be wrong in,
        because `01` §2's failure is a three-part question getting one answer.
    """
    fsm = getattr(state, "state", None)

    # §3.4's whole sub-dialogue is a read-back, whatever step carries it.
    if fsm is State.MODEL_ID:
        return TurnType.MODEL_ID_READBACK
    if step_id and step_id in READBACK_STEPS:
        return TurnType.MODEL_ID_READBACK

    if step_id:
        step = ontology.STEPS.get(step_id)
        family = step.family if step else ""
        if family in PHYSICAL_FAMILIES:
            return TurnType.PHYSICAL_ACTION
        if family == OBSERVE_FAMILY:
            # Look / listen / test — the user leaves the screen for it.
            return TurnType.PHYSICAL_ACTION
        if family == ASK_FAMILY:
            return TurnType.YES_NO if closed_question(spoken) else TurnType.OPEN_SYMPTOM

    if fsm in (State.GREET, State.SYMPTOM_CAPTURE, None):
        return TurnType.OPEN_SYMPTOM
    if closed_question(spoken):
        return TurnType.YES_NO
    return TurnType.OPEN_SYMPTOM


def explicit_prompt_present(spoken: str) -> bool:
    """Whether the agent said §2.3's "tell me when you've done that"."""
    return any(pattern.search(spoken or "") for pattern in EXPLICIT_PROMPT_PATTERNS)


# --------------------------------------------------------------------------
# The semantic endpoint classifier (docs/06 §2.3, layered on top)
# --------------------------------------------------------------------------

#: Trailing tokens that mean the user has not finished. §2.3's own example is
#: *"it says… um…"*, which must hold even though the silence after it looks
#: exactly like the silence after *"yeah it's on"*.
_HOLD_TAIL = re.compile(
    r"(?:\b(?:um|uh|er|erm|hmm|ah|like|and|or|but|so|then|it'?s|its|the|a|an|my|"
    r"to|of|for|with|that|which|because|cos|cause|when|if|is|was|i|we|there'?s|"
    r"says?|saying|shows?|showing)\b|[,\-–—])\s*$",
    re.I,
)

#: Reading a code out loud: a run of spelled characters or digits that has not
#: obviously ended. §3.4 says cutting a user mid-string is "the `R2`/`R3`
#: failure in a new costume", so a partial that looks like a read-back holds.
_SPELLING_TAIL = re.compile(r"(?:\b[A-Za-z0-9]\b[\s\-]*){2,}$")

#: Short, complete answers. The point of the 180 ms row.
_COMPLETE_SHORT = frozenset(
    {
        "yes", "yeah", "yep", "yup", "no", "nope", "nah", "correct", "right",
        "wrong", "ok", "okay", "done", "sure", "maybe", "dunno", "both",
        "neither", "one", "two", "three", "none", "steady", "blinking",
        "nothing", "stopped", "it is", "it isn't", "it does", "it doesn't",
        "i did", "i didn't", "i have", "i haven't",
    }
)


def completeness(partial: str) -> float:
    """§2.3's "is this a complete thought?", as a number in [0, 1].

    Lexical, allocation-free enough to run on every partial, and deliberately
    not a model. Above :data:`COMPLETE_THRESHOLD` the endpointer is allowed to
    close at the bottom of the hangover window; below it, the turn holds to the
    top of the window and no further — a classifier that could *extend* a
    hangover would be a classifier that can hang the session.

    Returns:
        0.0 for an empty partial (nothing has been heard, so nothing is
        complete), rising to 1.0 for a short closed answer.
    """
    text = (partial or "").strip()
    if not text:
        return 0.0
    lowered = re.sub(r"[.!?]+$", "", text.lower()).strip()
    if lowered in _COMPLETE_SHORT:
        return 1.0
    if _HOLD_TAIL.search(lowered):
        return 0.0
    if _SPELLING_TAIL.search(text):
        return 0.1
    words = lowered.split()
    if not words:
        return 0.0
    if words[0] in _COMPLETE_SHORT and len(words) <= 4:
        return 0.9
    if text.rstrip().endswith((".", "?", "!")):
        return 0.85
    # A clause with a verb in it is usually a thought; a noun phrase is not.
    if len(words) >= 4:
        return 0.7
    return 0.4


#: The line above which a partial counts as a complete thought.
COMPLETE_THRESHOLD = 0.6


# --------------------------------------------------------------------------
# The endpointer
# --------------------------------------------------------------------------


@dataclass
class EndpointDecision:
    """Why a turn closed, in a shape the trace can take whole."""

    fired: bool
    turn_type: TurnType
    hangover_ms: int
    silence_ms: float
    completeness: float
    reason: str
    suppressed_by: str = ""


@dataclass
class Endpointer:
    """One turn's worth of end-of-turn decision.

    Call :meth:`arm` when the agent finishes speaking, feed it silence as the
    VAD reports it, and it says when the turn is over. It holds no audio and
    no transcript of its own: the caller owns both, because the caller is the
    one that has to hand the final transcript to the core.
    """

    turn_type: TurnType = TurnType.OPEN_SYMPTOM
    hangover: Hangover = field(default_factory=lambda: HANGOVERS[TurnType.OPEN_SYMPTOM])
    prompt_satisfied: bool = True
    armed_at: float = 0.0
    speech_seen: bool = False
    last_typing_at: float = 0.0
    typing_grace_ms: int = TYPING_GRACE_MS
    fired_at: float | None = None
    last_decision: EndpointDecision | None = None
    #: §2.4 tier 1 — "drop the semantic endpoint classifier back to fixed
    #: hangovers". Off, :func:`completeness` is still computed and still goes
    #: into the trace (it costs microseconds and it is what makes the shed
    #: legible afterwards), but it no longer lets a turn close at the bottom of
    #: the window: every turn waits out `max_ms`. That is precisely what "fixed
    #: hangovers" means, and it is a latency *cost* on short answers bought
    #: back in CPU — §2.4's tier 1 is a bundle, and this is the member of it
    #: that trades the other way. `server/ladder.py` says why the bundle is
    #: applied whole rather than cherry-picked.
    semantic_enabled: bool = True

    # -- arming -----------------------------------------------------------

    def arm(
        self,
        *,
        state: Any = None,
        step_id: str | None = None,
        spoken: str = "",
        turn_type: TurnType | None = None,
        now: float | None = None,
    ) -> Hangover:
        """Set the hangover for the turn the user is about to take.

        `turn_type` overrides the classifier, which is what the unit tests and
        the verification harness use to drive one row at a time.
        """
        self.turn_type = turn_type or classify_turn(state, step_id=step_id, spoken=spoken)
        self.hangover = HANGOVERS[self.turn_type]
        self.prompt_satisfied = (
            explicit_prompt_present(spoken)
            if self.hangover.requires_explicit_prompt
            else True
        )
        self.armed_at = time.time() if now is None else now
        self.speech_seen = False
        self.fired_at = None
        self.last_decision = None
        return self.hangover

    def note_typing(self, now: float | None = None) -> None:
        """§2.3: someone part-way through typing an SSID has not finished."""
        self.last_typing_at = time.time() if now is None else now

    def note_speech(self) -> None:
        self.speech_seen = True

    # -- deciding ---------------------------------------------------------

    @property
    def effective_hangover_ms(self) -> int:
        """The hangover actually in force, prompt obligation included.

        §2.3's physical-action row is "2,000 ms **plus** an explicit prompt".
        If the prompt was not spoken, the silence is not evidence of anything,
        so the agent waits for words rather than for a timer: the hangover
        becomes unreachable rather than merely long, and `AWAIT_OUTCOME`'s own
        90-second nudge (§3.2) is what breaks the deadlock.
        """
        if self.hangover.requires_explicit_prompt and not self.prompt_satisfied:
            return -1
        return self.hangover.max_ms

    def evaluate(
        self,
        *,
        silence_ms: float,
        partial: str = "",
        now: float | None = None,
    ) -> EndpointDecision:
        """Should the turn close, given this much silence after this partial?"""
        now = time.time() if now is None else now
        score = completeness(partial)
        low, high = self.hangover.window_ms()

        def decision(fired: bool, reason: str, hangover_ms: int, suppressed: str = "") -> EndpointDecision:
            result = EndpointDecision(
                fired=fired,
                turn_type=self.turn_type,
                hangover_ms=hangover_ms,
                silence_ms=round(silence_ms, 1),
                completeness=round(score, 2),
                reason=reason,
                suppressed_by=suppressed,
            )
            self.last_decision = result
            if fired:
                self.fired_at = now
            return result

        if self.hangover.requires_explicit_prompt and not self.prompt_satisfied:
            return decision(False, "physical action without an explicit prompt", -1, "no_prompt")

        typing_age_ms = (now - self.last_typing_at) * 1000.0
        if self.last_typing_at and typing_age_ms < self.typing_grace_ms:
            return decision(False, "the user is typing", high, "typing")

        if not partial.strip():
            # Nothing heard. There is no turn to end, however long the silence.
            return decision(False, "no transcript yet", high, "no_transcript")

        if silence_ms >= high:
            return decision(True, "hangover ceiling", high)
        if not self.semantic_enabled:
            # §2.4 tier 1: fixed hangovers. The classifier's score is still in
            # the decision record; it is simply not allowed to close the turn.
            return decision(
                False, "within the fixed hangover (§2.4 tier 1)", high, "semantic_shed"
            )
        if silence_ms >= low and score >= COMPLETE_THRESHOLD:
            return decision(True, "complete thought at the hangover floor", low)
        return decision(False, "within the hangover window", high)
