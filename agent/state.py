"""The typed `DiagnosticState` (`docs/06` §3.3), and the 13-state FSM (§3.2).

Two stores, kept apart on purpose. **Conversation state** — the turn log, ASR
confidence, modality, barge-in events — is append-only and exists for the
LLM's understanding. **Diagnostic state**, which is everything in this module,
is typed, validated, and is the only thing the policy layer reads.

> The policy layer never reads the transcript. If a fact is not in
> `DiagnosticState`, it does not exist for decision-making. (`docs/06` §3.3)

That separation is what makes M4 enforceable: the user said "I already
formatted it" in turn 2, and the agent must not propose a format in turn 9
because the sentence fell out of a context window. Here it cannot, because the
sentence is not what the filter reads — `ledger.attempted` is.

**Milestone 4.4 adds the second half of that argument.** The ledger holds what
was *tried*; `answers` holds what the caller *told us* when we asked. A
question's product is information, and `AttemptedStep.outcome` has nowhere to
put it, so until the typed record grew an `Answer` the answer lived only in the
transcript — which the policy layer is forbidden to read. The two visible
consequences were an agent that re-asked a question it had just had answered,
and an agent that never acted on the answer when it did get one. See
`agent/answers.py` for the `docs/02` readings and the per-entry triggers.

**What this module deliberately does not do.** It does not decide anything.
Transitions are validated, ceilings are reported, consent is recorded — but the
choice of next step lives in `policy.py` and the words live in `core.py`.

Reuses rather than restates:

* `eval.ontology.AttemptedStep` — the ledger entry type, and `blocked_ids`,
  the family-level no-repeat computation (`docs/06` §3.5, EVAL-12).
* `ingest.metadata.TAXONOMY_STATUS` — the per-entry `docs/05` verification
  status that decides whether an entry may be spoken as a fix (§4.5).
* `ingest.metadata.ALL_MODELS` — the six documented models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from eval import ontology
from eval.ontology import AttemptedStep
from ingest.metadata import (
    ALL_MODELS,
    R2_4K_DUAL,
    R2_4K_DUAL_PRO,
    R2_4K_EITHER_REVISION,
    R2_4K_MINI_USB,
    R2_4K_PRO,
    R2_4K_USB_C,
    R3,
    SPEAKABLE_STATUSES,
    TAXONOMY_STATUS,
    UNVERIFIED,
    models_spoken_in,
)

# --------------------------------------------------------------------------
# The 13 states (docs/06 §3.2)
# --------------------------------------------------------------------------


class State(str, Enum):
    """The thirteen states of the diagnostic FSM, verbatim from `docs/06` §3.2.

    `VERIFY_RESOLVED` is a state in its own right and not a flag on `CLOSE`,
    because `docs/01` M8 counts a resolution only when *the user states the
    symptom is gone*. An unconfirmed instruction is not a resolution, and the
    distinction is only auditable if it is a transition.
    """

    GREET = "GREET"
    SYMPTOM_CAPTURE = "SYMPTOM_CAPTURE"
    TRIAGE = "TRIAGE"
    MODEL_ID = "MODEL_ID"
    HYPOTHESISE = "HYPOTHESISE"
    SELECT_STEP = "SELECT_STEP"
    DESTRUCTIVE_GATE = "DESTRUCTIVE_GATE"
    PROPOSE_STEP = "PROPOSE_STEP"
    AWAIT_OUTCOME = "AWAIT_OUTCOME"
    EVALUATE_OUTCOME = "EVALUATE_OUTCOME"
    VERIFY_RESOLVED = "VERIFY_RESOLVED"
    ESCALATE = "ESCALATE"
    CLOSE = "CLOSE"


assert len(State) == 13, "docs/06 §3.2 names thirteen states"

#: Terminal states. Nothing transitions out of these within a session.
TERMINAL_STATES = frozenset({State.ESCALATE, State.CLOSE})

#: The legal transition graph of `docs/06` §3.2. An interrupt (below) may enter
#: `ESCALATE` from anywhere, which is why every row carries it.
LEGAL_TRANSITIONS: dict[State, frozenset[State]] = {
    State.GREET: frozenset({State.SYMPTOM_CAPTURE, State.ESCALATE}),
    State.SYMPTOM_CAPTURE: frozenset(
        {State.SYMPTOM_CAPTURE, State.TRIAGE, State.ESCALATE}
    ),
    State.TRIAGE: frozenset(
        {State.MODEL_ID, State.HYPOTHESISE, State.ESCALATE, State.CLOSE}
    ),
    State.MODEL_ID: frozenset({State.MODEL_ID, State.HYPOTHESISE, State.ESCALATE}),
    State.HYPOTHESISE: frozenset({State.SELECT_STEP, State.ESCALATE}),
    State.SELECT_STEP: frozenset(
        {State.DESTRUCTIVE_GATE, State.PROPOSE_STEP, State.MODEL_ID, State.ESCALATE}
    ),
    State.DESTRUCTIVE_GATE: frozenset(
        {State.PROPOSE_STEP, State.SELECT_STEP, State.ESCALATE}
    ),
    State.PROPOSE_STEP: frozenset({State.AWAIT_OUTCOME, State.ESCALATE}),
    State.AWAIT_OUTCOME: frozenset({State.EVALUATE_OUTCOME, State.ESCALATE}),
    State.EVALUATE_OUTCOME: frozenset(
        {State.HYPOTHESISE, State.SELECT_STEP, State.VERIFY_RESOLVED, State.ESCALATE}
    ),
    State.VERIFY_RESOLVED: frozenset({State.CLOSE, State.HYPOTHESISE, State.ESCALATE}),
    State.ESCALATE: frozenset({State.CLOSE}),
    State.CLOSE: frozenset(),
}


class Interrupt(str, Enum):
    """Evaluated before every transition (`docs/06` §3.2, §6).

    These leave the main path. `HAZARD_STOP` pre-empts everything including an
    in-progress TTS turn (§6.1).
    """

    HAZARD_STOP = "HAZARD_STOP"
    DRIVING_GATE = "DRIVING_GATE"
    PRESERVE_FOOTAGE = "PRESERVE_FOOTAGE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    USER_REQUESTS_HUMAN = "USER_REQUESTS_HUMAN"


#: Per-state turn ceilings (`docs/06` §3.2 state table).
STATE_TURN_CEILINGS: dict[State, int] = {
    State.GREET: 1,
    State.SYMPTOM_CAPTURE: 3,
    State.TRIAGE: 1,
    State.MODEL_ID: 4,
}

#: Ledger outcomes that mean the situation actually moved. `docs/06` §3.6
#: licenses re-asking a question only "after something has changed", and these
#: are the two outcomes in which something did: the step worked, or it made
#: things worse. `no_change`, `not_attempted` and `unclear` are the ledger
#: saying nothing moved, or that it cannot tell — see
#: `DiagnosticState.answered_questions`.
CHANGED_OUTCOMES = frozenset({"success", "worse"})

#: Global ceilings, any of which forces `ESCALATE` (`docs/06` §3.2).
MAX_DIAGNOSTIC_TURNS = 12
MAX_AGENT_PROPOSED_ATTEMPTS = 2  # 02 cross-cutting trigger 1
MAX_HYPOTHESIS_TURNS_HELD = 3  # 02 cross-cutting trigger 2


class TransitionError(AssertionError):
    """An illegal FSM transition. A bug, not a user outcome."""


# --------------------------------------------------------------------------
# Model identification (docs/06 §3.4)
# --------------------------------------------------------------------------

CONFIRMED = "CONFIRMED"
PROBABLE = "PROBABLE"
UNKNOWN = "UNKNOWN"

#: `docs/06` §3.4: `RS2` and `RS4` are borescopes, not dash cams. Landing here
#: routes to OUT_OF_SCOPE and a human. `R`+digit pattern matching is forbidden.
NON_DASHCAM_MODELS = frozenset({"RS2", "RS4"})

#: `R1` (legacy) and `R4` (pre-launch) have no manual in the corpus. Identifying
#: as either sets clearance to none and escalates (`docs/06` §3.4).
UNDOCUMENTED_MODELS = frozenset({"R1", "R4"})

#: Signal kinds, weakest first. A spoken model name is the *least* reliable
#: signal available — it is exactly the token ASR mangles (`docs/01` §2) — so it
#: never promotes confidence on its own, however many times it is repeated.
SIGNAL_SPOKEN_NAME = "spoken_name"
SIGNAL_FEATURE = "feature"  # lens count, touch-vs-buttons, connector, band
SIGNAL_TYPED = "typed"  # SSID or serial typed into the web client (§1.4)


# --------------------------------------------------------------------------
# The discriminator ladder (docs/06 §3.4), as data
# --------------------------------------------------------------------------
#
# `docs/06` §3.4 gives seven probes and what each one *splits*. Until Milestone
# 3.1 that table lived only in prose, so every signal reached
# `DeviceIdentification` with an empty `narrows_to`, the candidate set never
# shrank, `device.model` was never assigned — and `confidence` still rose to
# `PROBABLE` on any feature signal. That is how the agent reported model
# `unknown` at confidence `PROBABLE`, two values that cannot both be true.
#
# Every entry below is traceable to `docs/05`, which is the only place the
# facts are verified. Where `docs/05` does not know something — the R2-4K PRO's
# SSID prefix is not in the SSID table, because its manual was never
# downloaded — the ladder says nothing rather than guessing.

#: Probe 1, the strongest: the SSID read off the camera's own screen
#: (`docs/05` "Wi-Fi SSID patterns"). Keys are normalised by `_squash`, and are
#: matched longest-first so that `ROVE_R2-4K-DUAL_PRO` is not eaten by
#: `ROVE_R2-4K-DUAL_`, which is not eaten by `ROVE_R2-4K_`.
#:
#: `ROVE_R2-4K_` narrows to the two R2-4K hardware revisions and no further:
#: they share one SSID prefix and are split by probe 4, not by this one.
SSID_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ROVE_R2-4K-DUAL_PRO", (R2_4K_DUAL_PRO,)),
    ("ROVE_R2-4K-DUAL_", (R2_4K_DUAL,)),
    ("ROVE_R2-4K_", R2_4K_EITHER_REVISION),
    ("ROVE R2-4K-", R2_4K_EITHER_REVISION),  # the mini-USB manual's printing
    ("ROVE_R3_", (R3,)),
)

#: Probe 2: total lens count. 1 → R2-4K / PRO · 2 → DUAL / DUAL PRO ·
#: 3 → R3 (front / cabin / rear).
LENS_COUNT_SPLITS: dict[int, tuple[str, ...]] = {
    1: (R2_4K_MINI_USB, R2_4K_USB_C, R2_4K_PRO),
    2: (R2_4K_DUAL, R2_4K_DUAL_PRO),
    3: (R3,),
}

#: Probe 3, the R2-vs-R3 answer that never asks the caller to say "R2" or "R3":
#: a touch screen is the R3 and nothing else (`docs/05` "Rove R3 … it is
#: 3-channel with a touchscreen").
TOUCH_ONLY = (R3,)
BUTTONS_ONLY = (R2_4K_MINI_USB, R2_4K_USB_C, R2_4K_PRO, R2_4K_DUAL, R2_4K_DUAL_PRO)

#: Probe 4, the R2-4K revision split (`docs/05` `M1` vs `M2`/`M3`): a plug that
#: only goes in one way is the original mini-USB body with the 250 mAh cell; a
#: reversible plug is USB-C, which is every other documented body.
MINI_USB_ONLY = (R2_4K_MINI_USB,)
USB_C_BODIES = (R2_4K_USB_C, R2_4K_PRO, R2_4K_DUAL, R2_4K_DUAL_PRO, R3)

#: Probe 5: the underside serial label. `R2XXXXXXXXX` is the documented format
#: (`docs/05` `FW-02`), and the R3 is the model `docs/05` singles out as having
#: no reset button beside such a label. An `R2`-prefixed serial therefore
#: excludes the R3 — it does not, on its own, say which R2 body it is.
SERIAL_R2_PREFIX = (R2_4K_MINI_USB, R2_4K_USB_C, R2_4K_PRO, R2_4K_DUAL, R2_4K_DUAL_PRO)

#: Probe 6: band behaviour. `docs/05` is explicit that "2.4 GHz only, nothing to
#: switch" is true for exactly one model — the R2-4K — and false for the DUAL,
#: the DUAL PRO and the R3, which are dual-band, with the PRO listed as 5 GHz.
BAND_2_4_ONLY = R2_4K_EITHER_REVISION
BAND_DUAL_OR_5 = (R2_4K_PRO, R2_4K_DUAL, R2_4K_DUAL_PRO, R3)

#: Probe 7, corroborative: a CPL filter ships **in the box** on the DUAL and
#: the DUAL PRO and is sold separately for the R2-4K and PRO (`docs/05`
#: `VID-02`). A second camera for the back window means a rear channel exists,
#: which the DUAL, the DUAL PRO and the 3-channel R3 all have.
IN_BOX_CPL = (R2_4K_DUAL, R2_4K_DUAL_PRO)
IN_BOX_REAR_CAMERA = (R2_4K_DUAL, R2_4K_DUAL_PRO, R3)


def _squash(text: str) -> str:
    """Lower-case and drop the separators ASR and typing disagree about."""
    return re.sub(r"[\s_\-]+", "", text).lower()


def _lens_count(value: str) -> int | None:
    text = value.lower()
    for word, count in (
        ("three", 3),
        ("third", 3),
        ("two", 2),
        ("second", 2),
        ("one", 1),
        ("single", 1),
        ("just the", 1),
    ):
        if word in text:
            return count
    digits = re.search(r"\b([123])\b", text)
    return int(digits.group(1)) if digits else None


def narrowing_for(signal: str, value: str) -> tuple[str, ...]:
    """The candidate set one probe answer narrows to (`docs/06` §3.4).

    Returns `()` when the answer says nothing the ladder can act on — an
    unparseable lens count, a "not sure", a signal kind we have no documented
    discriminator for. That empty return is load-bearing, not a default: a
    signal that narrows nothing is recorded as evidence and **does not raise
    confidence**, which is what makes `unknown` at `PROBABLE` unreachable.

    A spoken model name narrows nothing by design. `docs/06` §3.4: "A user
    saying 'R2' is treated as **one weak signal**, never as identification",
    and letting it cut the candidate set would hand the `R2`/`R3` ASR confusion
    the power to veto probe 3, which is the probe that actually resolves it.
    """
    text = value.strip()
    if not text:
        return ()
    squashed = _squash(text)

    if signal == "ssid":
        for prefix, models in SSID_PREFIXES:
            if squashed.startswith(_squash(prefix)):
                return models
        return ()

    if signal == "lens_count":
        count = _lens_count(text)
        return LENS_COUNT_SPLITS.get(count, ()) if count else ()

    if signal == "touch_or_buttons":
        if "touch" in squashed or "tap" in squashed:
            return TOUCH_ONLY
        if "button" in squashed or "press" in squashed:
            return BUTTONS_ONLY
        return ()

    if signal == "connector":
        if any(
            token in squashed
            for token in ("miniusb", "onlyoneway", "oneway", "onewayup", "onlyoneway")
        ):
            return MINI_USB_ONLY
        if any(
            token in squashed
            for token in ("usbc", "typec", "reversible", "eitherway", "bothways")
        ):
            return USB_C_BODIES
        return ()

    if signal == "serial":
        return SERIAL_R2_PREFIX if squashed.startswith("r2") else ()

    if signal == "band":
        if "2.4" in text or "24ghz" in squashed or "nothingtoswitch" in squashed:
            return BAND_2_4_ONLY
        if "5ghz" in squashed or "dualband" in squashed or "5g" in squashed:
            return BAND_DUAL_OR_5
        return ()

    if signal == "in_box":
        if "cpl" in squashed or "filter" in squashed or "polaris" in squashed:
            return IN_BOX_CPL
        if "rear" in squashed or "secondcamera" in squashed or "backwindow" in squashed:
            return IN_BOX_REAR_CAMERA
        return ()

    return ()


def revision_for(value: str) -> str:
    """The `hw_revision` a probe-4 answer implies, or `unknown`."""
    narrows = narrowing_for("connector", value)
    if narrows == MINI_USB_ONLY:
        return "mini_usb"
    if narrows == USB_C_BODIES:
        return "usb_c"
    return "unknown"


#: Labels for a candidate set that has narrowed without reaching one model.
#: `docs/06` §3.4 says `PROBABLE` "unlocks **family-level** steps only", so a
#: narrowed-but-unresolved device is a real, reportable state — it is just not
#: `unknown`, and saying `unknown` while holding a narrowed set is the defect
#: Milestone 3.1 fixes.
FAMILY_LABELS: dict[frozenset[str], str] = {
    frozenset(R2_4K_EITHER_REVISION): "R2-4K (revision not yet established)",
    frozenset(LENS_COUNT_SPLITS[1]): "R2-4K or R2-4K PRO",
    frozenset(IN_BOX_CPL): "R2-4K DUAL or DUAL PRO",
    frozenset(BUTTONS_ONLY): "a button-operated model (not the R3)",
    frozenset(USB_C_BODIES): "a USB-C model (not the original mini-USB R2-4K)",
}


@dataclass
class ModelSignal:
    """One row of `device.evidence` (`docs/06` §3.3).

    `narrows_to` is the §3.4 ladder's verdict on this answer, and `applied`
    records whether the live candidate set actually agreed with it. The pair is
    what the confidence rules read: an answer nobody could act on, and an
    answer that contradicts everything already held, both leave `applied`
    `False` and neither promotes the device above `UNKNOWN`.
    """

    signal: str  # ssid | lens_count | touch_or_buttons | connector | serial |
    # band | in_box | name
    value: str
    turn: int
    modality: str = "voice"  # voice | typed | click (§1.4.1)
    kind: str = SIGNAL_SPOKEN_NAME
    narrows_to: tuple[str, ...] = ()
    #: Set by `DeviceIdentification.add_signal` when this signal agreed with
    #: the live candidate set. Never set by the caller.
    applied: bool = False

    @classmethod
    def from_probe(
        cls,
        signal: str,
        value: str,
        turn: int,
        *,
        modality: str = "voice",
    ) -> ModelSignal:
        """Build a signal with its `docs/06` §3.4 narrowing already resolved.

        This is the only constructor callers should use. Building a
        `ModelSignal` by hand and forgetting `narrows_to` is precisely the
        Milestone 3 defect, so the ladder lookup lives here rather than at the
        call site.
        """
        if signal in ("name", ""):
            kind = SIGNAL_SPOKEN_NAME
        elif modality == "typed" and signal in ("ssid", "serial"):
            kind = SIGNAL_TYPED
        else:
            kind = SIGNAL_FEATURE
        return cls(
            signal=signal or "name",
            value=value,
            turn=turn,
            modality=modality,
            kind=kind,
            narrows_to=narrowing_for(signal, value),
        )


#: How a single registered model is said out loud. Mirrors
#: `router.MODEL_DISPLAY_NAMES`, which cannot be imported here (the router
#: imports this module).
SPOKEN_NAMES: dict[str, str] = {
    R2_4K_MINI_USB: "R2-4K (mini-USB)",
    R2_4K_USB_C: "R2-4K (USB-C)",
    R2_4K_PRO: "R2-4K PRO",
    R2_4K_DUAL: "R2-4K DUAL",
    R2_4K_DUAL_PRO: "R2-4K DUAL PRO",
    R3: "R3",
}


@dataclass
class DeviceIdentification:
    """`DiagnosticState.device` — model, revision, and how sure we are.

    The confidence rules are `docs/06` §3.4, implemented rather than described:

    * `CONFIRMED` — two independent signals in agreement, at least one of which
      is **not** a spoken model name; or a single *typed* SSID, since the
      transcription error the two-signal rule exists to defeat cannot occur.
    * `PROBABLE` — one non-name signal. Unlocks family-level steps only.
    * `UNKNOWN` — everything else, including "the user said R2 four times".
      This is `docs/01` §5's phantom-model failure made structural.

    Every one of those rules is read through `narrowed`: **confidence cannot
    rise above `UNKNOWN` until some signal has actually cut the candidate
    set.** Before Milestone 3.1 it could, and the result was the agent
    reporting model `unknown` at confidence `PROBABLE` — a pair of values that
    cannot both be true, and an M1 failure that no prompt change could reach.
    """

    model: str = "unknown"
    hw_revision: str = "unknown"  # mini_usb | usb_c | n/a | unknown
    evidence: list[ModelSignal] = field(default_factory=list)
    #: Models still in contention. Starts as all six documented models.
    candidates: list[str] = field(default_factory=lambda: list(ALL_MODELS))
    #: NEVER agent-generated (`docs/06` §4.6). Only ever a user-reported string.
    firmware_version: str = "unknown"
    card: dict[str, Any] = field(default_factory=dict)
    power: dict[str, Any] = field(default_factory=dict)

    @property
    def narrowed(self) -> bool:
        """True once some signal has actually cut the candidate set.

        This is the gate on the whole confidence ladder. A signal the `docs/06`
        §3.4 table has no discriminator for — a lens count of "not sure", a
        spoken model name, a probe answer the classifier invented — leaves the
        six documented models in contention, and six candidates is not
        identification however many rows `evidence` has.
        """
        return len(self.candidates) < len(ALL_MODELS)

    @property
    def agreeing_signals(self) -> list[ModelSignal]:
        """Signals the live candidate set actually agreed with (§3.4)."""
        return [s for s in self.evidence if s.applied]

    @property
    def strong_signals(self) -> list[ModelSignal]:
        """Agreeing signals that are not a spoken model name."""
        return [s for s in self.agreeing_signals if s.kind != SIGNAL_SPOKEN_NAME]

    @property
    def confidence(self) -> str:
        if not self.narrowed:
            return UNKNOWN
        typed_identifier = any(
            s.kind == SIGNAL_TYPED and s.signal in ("ssid", "serial")
            for s in self.agreeing_signals
        )
        distinct_strong = {s.signal for s in self.strong_signals}
        if typed_identifier or len(distinct_strong) >= 2:
            return CONFIRMED
        if distinct_strong:
            return PROBABLE
        return UNKNOWN

    @property
    def candidate_label(self) -> str:
        """What a narrowed-but-unresolved candidate set is called out loud.

        `PROBABLE` is a real state with a real answer — "it is an R2-4K, I do
        not yet know which revision" — and that answer is not `unknown`.
        """
        if len(self.candidates) == 1:
            return self.candidates[0]
        label = FAMILY_LABELS.get(frozenset(self.candidates))
        if label:
            return label
        return "one of " + ", ".join(self.candidates)

    @property
    def spoken_model(self) -> str | None:
        """The one registered model the caller named, or `None`.

        Deliberately NOT folded into `reported_model`: that property keeps the
        `docs/06` 3.4 invariant (`UNKNOWN` confidence reports `unknown`). This
        is what the caller said, surfaced separately for the turn output. It is
        still only a weak signal -- it narrows nothing and never lifts
        `confidence` or unlocks a model-specific step -- but a caller who says "my R2-4K" has told us which
        camera it is, and reporting `unknown` for that is wrong in the other
        direction. Only a name `ingest.metadata` resolves counts, so an
        unregistered "R9" or a mis-transcribed word identifies nothing, and a
        bare "R2-4K" is reported as such with `hw_revision` left `unknown` for
        the ladder to settle.
        """
        for signal in reversed(self.evidence):
            if signal.kind != SIGNAL_SPOKEN_NAME:
                continue
            models = models_spoken_in(signal.value)
            if not models:
                continue
            if tuple(models) == tuple(R2_4K_EITHER_REVISION):
                return "R2-4K"
            if len(models) == 1:
                return SPOKEN_NAMES[models[0]]
        return None

    @property
    def reported_model(self) -> str:
        """What the agent is allowed to *say* the model is.

        `UNKNOWN` reports `unknown` whatever the user claimed. Saying UNKNOWN
        passes M1 (`docs/06` §7.2); guessing does not.

        Above `UNKNOWN` it never reports `unknown`, and since Milestone 3.1 it
        cannot: confidence only leaves `UNKNOWN` once the candidate set has
        narrowed, and a narrowed set always has a name — the model, or the
        family still in contention.
        """
        if self.confidence == UNKNOWN:
            return "unknown"
        if self.model != "unknown":
            return self.model
        return self.candidate_label

    def add_signal(self, signal: ModelSignal) -> DeviceIdentification:
        """Record a signal and narrow the live candidate set."""
        self.evidence.append(signal)
        if signal.narrows_to:
            narrowed = [m for m in self.candidates if m in signal.narrows_to]
            # A signal that contradicts everything we hold is recorded, not
            # obeyed: it is evidence of a mis-heard answer, not of a seventh
            # model (`docs/06` §3.4, ASR biasing). `applied` stays False, so it
            # does not count toward the two-signals-in-agreement rule either.
            if narrowed:
                signal.applied = True
                self.candidates = narrowed
        if signal.signal == "connector":
            revision = revision_for(signal.value)
            if revision != "unknown":
                self.hw_revision = revision
        if self.confidence != UNKNOWN and len(self.candidates) == 1:
            self.model = self.candidates[0]
        return self


# --------------------------------------------------------------------------
# Hypotheses (docs/06 §3.3 problem.hypothesis_stack)
# --------------------------------------------------------------------------


@dataclass
class Hypothesis:
    """One live cause, ranked. `turns_held` drives `02` cross-cutting trigger 2."""

    cause_id: str
    text: str
    rank: int = 1
    confidence: str = "medium"  # high | medium | low
    turns_held: int = 1
    chunk_ids: list[str] = field(default_factory=list)


@dataclass
class RuledOut:
    """A cause taken off the stack, and the observation that killed it.

    Kept rather than deleted: the handoff payload (`docs/06` §5.2) is worth far
    more to a human when it says what has already been excluded and why.
    """

    cause_id: str
    text: str
    reason: str
    turn: int


# --------------------------------------------------------------------------
# The rest of the record
# --------------------------------------------------------------------------


@dataclass
class Safety:
    driving: str = "unknown"  # unknown | yes | no | deferred_at_turn_n
    hazard_flags: list[str] = field(default_factory=list)
    footage_at_stake: str = "none"  # none | wanted | insurance_or_police

    @property
    def hazard_stop(self) -> bool:
        return bool(self.hazard_flags)


@dataclass
class Problem:
    verbatim_symptom: str = ""  # for the handoff, never paraphrased away
    category: str | None = None
    taxonomy_id: str | None = None
    change_event: str | None = None
    known_gap: str | None = None  # GAP-REAR / GAP-GPS / GAP-MOUNTING / GAP-TIMELAPSE
    hypothesis_stack: list[Hypothesis] = field(default_factory=list)
    ruled_out: list[RuledOut] = field(default_factory=list)

    @property
    def top_hypothesis(self) -> Hypothesis | None:
        return self.hypothesis_stack[0] if self.hypothesis_stack else None

    def push_hypothesis(self, hypothesis: Hypothesis) -> None:
        """Add or refresh a hypothesis, keeping the stack ranked.

        Re-asserting the same cause does not duplicate it; it ages it. That
        ageing is the whole mechanism behind `02` cross-cutting trigger 2 — the
        same top hypothesis surviving three turns with no new information is an
        escalation trigger, not a sign of conviction.
        """
        for existing in self.hypothesis_stack:
            if existing.cause_id == hypothesis.cause_id:
                existing.turns_held += 1
                existing.confidence = hypothesis.confidence
                existing.chunk_ids = hypothesis.chunk_ids or existing.chunk_ids
                return
        self.hypothesis_stack.append(hypothesis)
        self.hypothesis_stack.sort(key=lambda h: h.rank)

    def rule_out(self, cause_id: str, reason: str, turn: int) -> None:
        for i, existing in enumerate(self.hypothesis_stack):
            if existing.cause_id == cause_id:
                self.hypothesis_stack.pop(i)
                self.ruled_out.append(
                    RuledOut(cause_id, existing.text, reason, turn)
                )
                return
        self.ruled_out.append(RuledOut(cause_id, "", reason, turn))


@dataclass
class Ledger:
    """THE no-repeat structure (`docs/06` §3.3). Rendered in the UI (§1.4)."""

    attempted: list[AttemptedStep] = field(default_factory=list)

    @property
    def blocked(self) -> set[str]:
        """Every step id and family id blocked by this ledger (§3.5)."""
        return ontology.blocked_ids(self.attempted)

    def agent_proposed_failures(self) -> int:
        """Agent-proposed *attempts* that were made and did not help.

        Milestone 4.8. `docs/02`'s cross-cutting trigger 1 is "Two next-steps
        attempted, symptom unchanged" — `docs/06` §5.1 transcribes it as "two
        steps attempted with no change" — and the word doing the work is
        *attempted*. A question is not an attempt: §3.6 says so outright when it
        exempts `FAMILY.ASK` and `FAMILY.OBSERVE` from no-repeat, and §3.5
        ranks candidates by information gain precisely because a question's
        product is information rather than a change to the device. Counting an
        answered question here made the agent escalate *for having asked* —
        Harness B EVAL-27, where the branching question is asked on turn 3,
        answered on turn 4, and recorded with outcome `unclear` (the fail-safe
        §3.6 mapping that keeps it blocked), which tipped the count to two and
        fired the ceiling on the turn the branch says to carry on diagnosing.

        `information_only` is a property of the family, not of the outcome, so
        this cannot be reached by an action step however its outcome reads, and
        nothing about no-repeat changes: the same entry still blocks its own
        step and family.
        """
        return sum(
            1
            for a in self.attempted
            if a.source == "agent_proposed" and a.blocking and not a.information_only
        )


@dataclass
class Answer:
    """One question put to the caller, and how their reply read (`docs/06` §3.3).

    The second typed record, alongside the ledger, and it exists for the same
    reason: *"if a fact is not in `DiagnosticState`, it does not exist for
    decision-making."* The ledger answers "what has been tried"; this answers
    "what have we been told". Before Milestone 4.4 the second question had no
    answer anywhere the policy layer could read, because a question's product is
    information and `AttemptedStep.outcome` has nowhere to put it.

    `reading` is one of the `docs/02` readings in `agent/answers.py`, or
    `unknown` when the reply matched none of them. **`unknown` is still an
    answer.** `docs/06` §3.6 treats an ambiguous mapping as attempted — fail
    safe — and §3.4 is explicit that "asking the same question louder is not a
    strategy": a caller who said "I don't know, I haven't checked" has answered,
    and putting it to them again costs a turn and gains nothing.

    `verbatim` is kept for the handoff payload (§5.2), which is worth far more
    to a human in the caller's own words than in ours.
    """

    step_id: str  # the canonical question id, never free text (§3.6)
    reading: str  # a docs/02 reading, or `answers.UNKNOWN_READING`
    verbatim: str = ""
    turn: int = 0
    source: str = "agent_asked"  # agent_asked | user_volunteered
    modality: str = "voice"  # voice | typed | click (§1.4.1)
    #: The ledger length when this answer landed. An action attempted *after*
    #: it is what `docs/06` §3.6 means by "after something has changed", and it
    #: is what makes the question askable again — see
    #: `DiagnosticState.answered_questions`.
    ledger_depth: int = 0


@dataclass
class SpokenClaim:
    """One row of `clearance.spoken_claims` — the audit trail (`docs/06` §4.4)."""

    claim: str
    chunk_ids: list[str]
    tier: int = 1
    retrieval_date: str = ""
    turn: int = 0


@dataclass
class Clearance:
    spoken_claims: list[SpokenClaim] = field(default_factory=list)


@dataclass
class GateDecision:
    """One destructive-gate decision, recorded as structured fields.

    `docs/06` §6.4: cause, consequence and consent are *logged as structured
    fields, not inferred from the transcript*. In text mode there is no consent
    surface, so a destructive step reaches this record as
    `consent_state="not_requested"` and `decision="blocked"` — which is the
    honest outcome, and is what keeps M5 at zero on the eval set.
    """

    step_id: str
    step_family: str
    cause: str = ""  # a specific hypothesis, naming the taxonomy entry
    consequence: str = ""  # spoken first, in plain words
    consent_state: str = "not_requested"  # not_requested | granted | refused
    modality: str = "voice"
    decision: str = "blocked"  # blocked | allowed
    turn: int = 0

    @property
    def satisfied(self) -> bool:
        return bool(self.cause) and bool(self.consequence) and (
            self.consent_state == "granted"
        )

    def as_harness_gate(self) -> dict[str, Any]:
        """The shape `eval.harness._gate_satisfied` reads."""
        return {
            "cause": self.cause,
            "consequence": self.consequence,
            "consent_requested": self.consent_state != "not_requested",
            "consent_state": self.consent_state,
            "step_id": self.step_id,
        }


@dataclass
class Escalation:
    triggered: bool = False
    reason_code: str = ""
    reason: str = ""
    at_turn: int = 0


@dataclass
class DiagnosticState:
    """The typed store the policy layer reads (`docs/06` §3.3).

    Separate from the transcript by construction: there is no field here that
    holds the conversation, only `problem.verbatim_symptom`, which is kept
    unparaphrased because the handoff payload needs the user's own words.
    """

    session_id: str
    turn: int = 0
    state: State = State.GREET
    safety: Safety = field(default_factory=Safety)
    device: DeviceIdentification = field(default_factory=DeviceIdentification)
    problem: Problem = field(default_factory=Problem)
    ledger: Ledger = field(default_factory=Ledger)
    #: Questions already put to the caller, by canonical step id (§3.3). The
    #: no-repeat ledger's sibling: the ledger holds what was *tried*, this
    #: holds what we were *told*. Milestone 4.4.
    answers: dict[str, Answer] = field(default_factory=dict)
    clearance: Clearance = field(default_factory=Clearance)
    gates: list[GateDecision] = field(default_factory=list)
    escalation: Escalation = field(default_factory=Escalation)
    #: The FW-01 interlock input (`docs/06` §6.4): while a firmware update is
    #: *believed* in progress, the power-cycle family is hard-blocked. Belief,
    #: not certainty, is the right trigger — EVAL-22's user will unplug it
    #: during the pause either way.
    firmware_update_in_progress: bool = False
    #: Consent granted per step id, by an explicit affirmative answer or a click
    #: on an affirmative control (`docs/06` §6.4). Text mode leaves this empty.
    consent: dict[str, bool] = field(default_factory=dict)
    history: list[tuple[State, str]] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    # ---- FSM ----------------------------------------------------------
    def transition(self, new_state: State, reason: str = "") -> DiagnosticState:
        """Move the FSM, refusing illegal moves loudly.

        An interrupt may enter `ESCALATE` from anywhere (§3.2), which the
        transition table already allows from every state.
        """
        allowed = LEGAL_TRANSITIONS[self.state]
        if new_state not in allowed and new_state is not self.state:
            raise TransitionError(
                f"illegal transition {self.state.value} -> {new_state.value}; "
                f"legal: {sorted(s.value for s in allowed)}"
            )
        self.history.append((new_state, reason))
        self.state = new_state
        return self

    # ---- Ledger -------------------------------------------------------
    def record_attempt(
        self,
        step_id: str,
        outcome: str,
        *,
        source: str = "agent_proposed",
        verbatim: str = "",
        count: int | None = None,
        also_blocks: list[str] | None = None,
    ) -> AttemptedStep:
        """Append to the ledger, deriving the family from the ontology.

        The family is never taken on trust from the caller. `step_family` is
        what the no-repeat filter blocks on (EVAL-12), so it has to come from
        the one place that defines it.
        """
        if step_id not in ontology.STEPS:
            raise KeyError(
                f"{step_id!r} is not in the step ontology — free text is not a "
                "step (06 §3.6)"
            )
        if outcome not in ontology.VALID_OUTCOMES:
            raise ValueError(
                f"outcome {outcome!r} is not one of {sorted(ontology.VALID_OUTCOMES)}"
            )
        entry = AttemptedStep(
            step_id=step_id,
            step_family=ontology.STEPS[step_id].family,
            source=source,
            outcome=outcome,
            count=count,
            turn=self.turn,
            verbatim=verbatim,
            also_blocks=list(also_blocks or []),
        )
        self.ledger.attempted.append(entry)
        return entry

    # ---- Answers ------------------------------------------------------
    def record_answer(
        self,
        step_id: str,
        reading: str,
        *,
        verbatim: str = "",
        source: str = "agent_asked",
        modality: str = "voice",
    ) -> Answer:
        """Record how the caller answered a question (`docs/06` §3.3).

        The step id is checked against the ontology for the same reason
        `record_attempt` checks it: free text is not a step, and an answer
        filed against a sentence rather than against a canonical id is an
        answer the policy layer cannot act on (§3.6).

        Re-answering replaces rather than appends. There is one current answer
        to a question; the history of how the caller phrased it belongs in the
        transcript, which is the other store.
        """
        if step_id not in ontology.STEPS:
            raise KeyError(
                f"{step_id!r} is not in the step ontology — an answer is filed "
                "against a canonical question id, not free text (06 §3.6)"
            )
        answer = Answer(
            step_id=step_id,
            reading=reading,
            verbatim=verbatim,
            turn=self.turn,
            source=source,
            modality=modality,
            ledger_depth=len(self.ledger.attempted),
        )
        self.answers[step_id] = answer
        return answer

    @property
    def answered_questions(self) -> set[str]:
        """Question ids whose answer still stands (`docs/06` §3.6, §3.5).

        `docs/06` §3.6 exempts `FAMILY.OBSERVE` from no-repeat with a reason
        attached, and the reason is a condition rather than a blanket licence:

            asking someone to read the screen again, **after something has
            changed**, is not repetition.

        So the answer stands until something changes, and "something changed"
        is read off the typed record exactly as §3.5's re-proposal `delta` is:
        an action step attempted after the answer landed. A question answered
        before the caller did anything is still answered; a question answered
        before they power-cycled the camera is worth putting again.

        **Milestone 4.6: attempted is not changed.** The first cut read any
        later action as a change, and an action is only a change if it *did*
        something. Harness B caught it on EVAL-23: turn 2 proposed a step, the
        caller said "I tried that and there is no change at all", and turn 4
        put the turn-1 question again — the thing §3.4 calls "asking the same
        question louder". A `no_change` or `not_attempted` outcome is the
        ledger stating in as many words that nothing changed, so it cannot be
        what §3.6's "after something has changed" licence turns on, and the
        answer goes on standing. `unclear` is treated the same way, and for the
        same fail-safe reason §3.6 gives for treating it as attempted: when the
        record cannot say whether anything moved, re-asking is the move that
        costs a turn for nothing.

        Questions only — the ledger, not this, governs everything else.
        """
        current: set[str] = set()
        for step_id, answer in self.answers.items():
            later = self.ledger.attempted[answer.ledger_depth :]
            changed = any(
                not ontology.STEPS[entry.step_id].no_repeat_exempt
                and entry.outcome in CHANGED_OUTCOMES
                for entry in later
                if entry.step_id in ontology.STEPS
            )
            if not changed:
                current.add(step_id)
        return current

    # ---- Clearance ----------------------------------------------------
    def record_claim(self, claim: str, chunk_ids: list[str], retrieval_date: str = "") -> None:
        self.clearance.spoken_claims.append(
            SpokenClaim(
                claim=claim,
                chunk_ids=list(chunk_ids),
                retrieval_date=retrieval_date,
                turn=self.turn,
            )
        )

    # ---- Clearance of the taxonomy entry itself -----------------------
    @property
    def entry_status(self) -> str:
        """The `docs/05` verification status of the current taxonomy entry."""
        if not self.problem.taxonomy_id:
            return UNVERIFIED
        return TAXONOMY_STATUS.get(self.problem.taxonomy_id, UNVERIFIED)

    @property
    def speakable_as_fix(self) -> bool:
        """`docs/06` §4.5 item 3: only VERIFIED and CORRECTED may be spoken as a fix."""
        return self.entry_status in SPEAKABLE_STATUSES

    # ---- Ceilings -----------------------------------------------------
    def ceiling_breaches(self) -> list[str]:
        """Every global ceiling currently breached (`docs/06` §3.2).

        Note what is counted and what is not: only steps **the agent itself
        proposed** and that failed count toward trigger 1. A caller who arrives
        having already tried three things of their own has not exhausted the
        agent's two attempts — EVAL-16 arrives with two failed attempts in the
        ledger and expects diagnosis to continue, not an escalation.
        """
        breaches: list[str] = []
        if self.ledger.agent_proposed_failures() >= MAX_AGENT_PROPOSED_ATTEMPTS:
            breaches.append(
                f"{MAX_AGENT_PROPOSED_ATTEMPTS} agent-proposed steps attempted, "
                "symptom unchanged (02 cross-cutting trigger 1)"
            )
        top = self.problem.top_hypothesis
        if top is not None and top.turns_held >= MAX_HYPOTHESIS_TURNS_HELD:
            breaches.append(
                f"top hypothesis {top.cause_id!r} has survived {top.turns_held} "
                "turns with no new information (trigger 2)"
            )
        if self.turn > MAX_DIAGNOSTIC_TURNS:
            breaches.append(f"{MAX_DIAGNOSTIC_TURNS} diagnostic turns exhausted")
        return breaches

    def escalate(self, reason_code: str, reason: str) -> None:
        self.escalation = Escalation(
            triggered=True, reason_code=reason_code, reason=reason, at_turn=self.turn
        )
