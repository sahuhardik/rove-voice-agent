"""The text-only diagnostic turn (`docs/06` §9.1 Phase 1).

One function matters here:

    diagnose(utterance, state) -> TurnResult(response_text, state, citations)

and it wires the five stages the architecture names, in this order:

    interrupts → TRIAGE → MODEL_ID → retrieval → policy → LLM → output guard

Each stage can only narrow what the next one may do. The LLM sits second from
last and is handed a list it did not write; the output guard sits last and can
veto words the LLM chose. Nothing downstream of the policy filter can widen the
set of legal actions, which is the whole argument of `docs/06` §3.1 — the hard
constraints are code, not instructions.

**The output guard** (`docs/06` §4.5 item 4, §4.6, §3.5) enforces three rules
on the words before they are returned:

1. **Every device-specific claim cites a chunk id.** A line that asserts a
   model, a capacity, a named control, a documented on-screen string or a
   number-with-unit, and carries no citation, is dropped. A step whose own
   description carries device specifics has a spoken form that asks instead of
   asserting — see `SPOKEN_FORM`.
2. **Firmware-version-shaped tokens are blocked by regex.** There is exactly
   one version string in the entire corpus and it is the 2017 build of a
   discontinued revision (`docs/05`). No retrieval path, prompt or template may
   emit one; the agent may only ask the user to read theirs out.
3. **An `UNVERIFIED` entry is never spoken as a fix.** The four unevidenced
   entries (`FW-03`, `APP-02`, `APP-04`, `PWR-02`) and the rejected premise of
   `SD-02` may still be *investigated* — see `policy.py` on why — but the turn
   says plainly that it cannot be confirmed against Rove's documentation.

Voice is not here and neither is Postgres. This is text in, text out, in one
process, which is the point of doing Phase 1 before Phase 3: every hard
constraint in `docs/01` §5 is testable in text, and debugging a no-repeat
failure through an audio pipeline is miserable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from agent import answers
from agent import llm as llm_module
from agent import intake, policy, retrieval, router, symptoms
from agent.state import (
    DiagnosticState,
    Hypothesis,
    ModelSignal,
    State,
)
from eval import baseline, ontology

#: Escalation reasons that *replace* the diagnostic step with a handoff. The
#: others — a suspected brick, an implicated third-party installation, a
#: ceiling — escalate **in parallel with** the step, which is exactly what
#: `docs/02` FW-02 ("immediately, in parallel with any step") and `docs/03`
#: EVAL-24 ("escalate once the installation is implicated... characterise, not
#: fix") each ask for.
HARD_STOP_CODES = frozenset(
    {
        "hazard",
        "no_match",
        "intake_unanswered",
        "out_of_scope",
        "no_legal_step",
        "undocumented_model",
        "user_requests_human",
    }
)


# --------------------------------------------------------------------------
# Interrupt detection (docs/06 §6.1, §6.2, §6.4)
# --------------------------------------------------------------------------

#: `docs/02` cross-cutting trigger 3. Detection runs on **every** user turn and
#: on typed input, not only at triage: PWR-02 reaches it mid-session when a
#: caller mentions swelling after four turns about heat (`docs/06` §6.1).
HAZARD_PATTERNS: list[tuple[str, str]] = [
    (r"\bsmoke|smoking\b", "smoke"),
    (r"\bburn(ing|t)?\b.{0,20}\bsmell|smell.{0,20}\bburn", "burning_smell"),
    (r"\bswell(ing|ed|n)?|bulg(e|ing)|puff(ed|y)\b", "swelling"),
    (r"\bmelt(ed|ing)?|scorch|charred|heat damage\b", "heat_damage"),
    (r"\bexposed wir|bare wir|spark(s|ing)\b", "exposed_wiring"),
]

DRIVING_PATTERNS = (
    r"\bi'?m driving\b",
    r"\bwhile i'?m driving\b",
    r"\bon the (motorway|freeway|highway)\b",
    r"\bat the wheel\b",
    r"\bbehind the wheel\b",
)

FOOTAGE_PATTERNS = (
    r"\binsurance\b",
    r"\bpolice\b",
    r"\bclaim\b",
    r"\blawyer|solicitor|court\b",
    r"\bhit my car\b",
    r"\bneed (that|the) (video|footage|clip)\b",
)

OUT_OF_SCOPE_PATTERNS = (
    r"\brefund|money back\b",
    r"\bsend it back|return it\b",
    r"\bwarrant(y|ies)\b",
    r"\brma\b",
    r"\bbilling|invoice|charged\b",
)

REQUESTS_HUMAN_PATTERNS = (
    r"\b(speak|talk) to (a|an|someone|a real) ?(person|human|agent|engineer)?\b",
    r"\bput me through\b",
    r"\breal person\b",
)

FIRMWARE_IN_PROGRESS_PATTERNS = (
    r"\b(doing|running|installing|in the middle of) (the |a )?(firmware )?update\b",
    r"\bupdate (is )?(stuck|stalled|sat|sitting|frozen)\b",
    r"\bit'?s updating\b",
    r"\bhalf ?way\b.{0,30}\bupdate\b",
    r"\bupdate\b.{0,30}\b(per ?cent|%)\b",
)

#: `docs/01` §4 puts vehicle electrical work out of scope. A third-party
#: hardwire installation plus a drained battery is the EVAL-24 signature:
#: characterise it, then hand it to a human — do not give wiring instructions.
VEHICLE_ELECTRICAL_PATTERNS = (
    r"\bhard ?wir(e|ed|ing)\b",
    r"\bfuse box|fuse tap|ignition wire\b",
    r"\binstalled (it )?(by|for me)\b",
    r"\bauto ?electrician|installer\b",
)

BATTERY_DRAIN_PATTERNS = (
    r"\b(car )?battery (went |was |is )?(flat|dead|drained)\b",
    r"\bdrain(ed|ing)? (my|the) (car )?battery\b",
)


@dataclass
class UtteranceSignals:
    hazards: list[str] = field(default_factory=list)
    driving: bool = False
    footage_at_stake: bool = False
    flags: list[str] = field(default_factory=list)


def scan_utterance(utterance: str) -> UtteranceSignals:
    """Keyword detection for the interrupts, run before anything else.

    Rule-based on purpose. These are the paths that must still work when the
    model is unavailable, mis-configured, or wrong: a hazard stop that depends
    on an LLM call succeeding is not a hazard stop.
    """
    text = utterance.lower()
    signals = UtteranceSignals()
    for pattern, flag in HAZARD_PATTERNS:
        if re.search(pattern, text):
            signals.hazards.append(flag)
    if any(re.search(p, text) for p in DRIVING_PATTERNS):
        signals.driving = True
        signals.flags.append("driving")
    if any(re.search(p, text) for p in FOOTAGE_PATTERNS):
        signals.footage_at_stake = True
        signals.flags.append("footage_at_stake")
    if any(re.search(p, text) for p in OUT_OF_SCOPE_PATTERNS):
        signals.flags.append("out_of_scope")
    if any(re.search(p, text) for p in REQUESTS_HUMAN_PATTERNS):
        signals.flags.append("requests_human")
    if any(re.search(p, text) for p in FIRMWARE_IN_PROGRESS_PATTERNS):
        signals.flags.append("firmware_update_in_progress")
    if any(re.search(p, text) for p in VEHICLE_ELECTRICAL_PATTERNS) and any(
        re.search(p, text) for p in BATTERY_DRAIN_PATTERNS
    ):
        signals.flags.append("vehicle_electrical")
    if signals.hazards:
        signals.flags.append("hazard")
    return signals


# --------------------------------------------------------------------------
# The output guard
# --------------------------------------------------------------------------

#: A firmware-version-shaped token (`docs/06` §4.6). Two patterns: a dotted
#: version near firmware vocabulary, and Rove's own build-string shape.
FIRMWARE_VOCAB = r"(?:firmware|version|build|fw)"
FIRMWARE_VERSION_PATTERNS = (
    re.compile(rf"{FIRMWARE_VOCAB}\D{{0,20}}\b\d+\.\d+(?:\.\d+)?\b", re.I),
    re.compile(rf"\b\d+\.\d+(?:\.\d+)?\b\D{{0,20}}{FIRMWARE_VOCAB}", re.I),
    re.compile(r"\bROVE-R\d-4K-\d{8}\b", re.I),
)

#: What counts as a device-specific claim. Anything matching has to be backed
#: by a cleared Tier-1 chunk or it does not get spoken.
DEVICE_CLAIM_PATTERNS = (
    re.compile(r"\bR2[-\s]?4K\b", re.I),
    re.compile(r"\bR3\b"),
    re.compile(r"\bDUAL(\s+PRO)?\b"),
    re.compile(r"\bROVE[_\s-]?R\d\b", re.I),
    re.compile(
        r"\b\d+(?:\.\d+)?\s?(?:GB|TB|MB/s|GHz|mAh|V|volts?|°C|°F|m|ft|metres|feet|"
        r"second|seconds|sec|s|minute|minutes|min|%|per\s?cent)\b"
    ),
    re.compile(r"\bclass\s?10\b|\bU3\b|\bV30\b", re.I),
    re.compile(r"\b12345678\b"),
    re.compile(
        r"\b(?:emergency lock|reset button|up button|ok button|power button|"
        r"system settings|video mode|loop recording|wifi mode|time zone|"
        r"firmware update|retry connect|usb flash drive|hardwire kit|"
        r"supercapacitor|cpl filter|vlc)\b",
        re.I,
    ),
    re.compile(
        r"\"?(?:memory card error|card full|please insert microsd card)\"?", re.I
    ),
)


#: Internal vocabulary, and the fourth rule of the output guard (Milestone
#: 6.5, brief item (e)). None of this is for the caller: an eval id, a docs
#: section, a taxonomy id, a step id, or the name of a mechanism they have no
#: way to act on. The observed failure was an escalation that read "triage
#: found no taxonomy entry for the symptom ... is the EVAL-28 failure" —
#: `policy.escalation`'s own internal reason, delivered verbatim to a customer
#: whose camera was clicking. Escalation lines now take their words from
#: `ESCALATION_PHRASE` below, and this is the net under that.
INTERNAL_MARKER_PATTERNS = (
    re.compile(r"\bEVAL-\d+\b"),
    re.compile(r"\u00a7"),
    re.compile(r"\((?:0\d|extension)[^)]*\)"),
    re.compile(r"\b(?:STEP|FAMILY)\.[A-Z]"),
    re.compile(r"\b(?:NO_MATCH|OUT_OF_SCOPE|KNOWN-GAP)\b"),
    re.compile(r"\b(?:WIFI|FW|APP|REC|SD|PWR|VID)-\d{2}\b"),
    re.compile(
        r"\b(?:taxonomy|shortlist|triage|output guard|policy filter|"
        r"no-repeat ledger|candidate set)\b",
        re.I,
    ),
)

#: Causes, and the fifth rule of the guard (Milestone 6.5, brief item (f)).
#: The observed failure was a reply that told a caller their camera "may have
#: been damaged due to physical trauma" when they had said nothing of the kind
#: and no chunk said it either — there is no such string anywhere in this
#: repository, so the words came from the model and nothing stopped them.
#:
#: A line may name a cause when the caller named it or a retrieved chunk
#: supports it. Otherwise it is an invention, and an invented cause is worse
#: than an unhelpful turn: it sends someone to look for damage that is not
#: there, and `docs/01` §5 counts a confident wrong answer as the expensive
#: failure. The patterns are stems so that "damage", "damaged" and "damaging"
#: are one rule, and they are matched against the same support text on both
#: sides, so a cause the caller *did* mention is always speakable.
CAUSE_CLAIM_PATTERNS = (
    re.compile(r"damag\w*", re.I),
    re.compile(r"\btrauma\w*", re.I),
    re.compile(r"\bdropp?(?:ed|ing)?\b", re.I),
    re.compile(r"\b(?:water|moistur\w*|liquid|damp|wet)\b", re.I),
    re.compile(r"\bimpact\w*|\bknocked\b|\bcrack\w*", re.I),
    re.compile(r"\bfaulty\b|\bdefect\w*", re.I),
    re.compile(r"\bbroken\b|\bbroke\b", re.I),
    re.compile(r"\bburn\w*|\bscorch\w*|\bmelt\w*", re.I),
    re.compile(r"\bworn out\b|\bwear and tear\b", re.I),
    re.compile(r"\bcounterfeit\b|\bfake\b", re.I),
    re.compile(r"\boverheat\w*", re.I),
    re.compile(r"\bpower surge\b|\bshort circuit\w*", re.I),
    re.compile(r"\bcorrupt\w*", re.I),
    re.compile(r"\bstolen\b|\btheft\b|\btamper\w*", re.I),
    re.compile(r"\bmanufactur\w*\s+(?:defect|fault)\w*", re.I),
    re.compile(r"\bhardware failure\b|\bdead battery\b", re.I),
)


@dataclass
class Line:
    """One spoken line, the chunk ids that back it, and what to say instead.

    `fallback` is the de-specified form of the same line. A step line whose
    only problem is an uncited device specific is better rewritten than
    dropped: dropping it leaves the turn with a `step_id` the agent never
    actually asked for, which is a quieter failure than saying something
    vaguer. A line with no fallback is dropped outright.
    """

    text: str
    chunk_ids: list[str] = field(default_factory=list)
    #: prose | step | caveat | safety | escalation | system.
    #: `system` is the one kind the agent composes about *itself* rather than
    #: about a camera — the model list, the category list, the model-ID
    #: question of `agent/router.py`. Its device specifics come from
    #: `ingest.metadata.ALL_MODELS`, the registry the corpus is indexed by,
    #: rather than from a retrieved chunk, so the citation rule has nothing to
    #: check and exempts it. Every other rule still applies to it.
    kind: str = "prose"
    fallback: str | None = None


@dataclass
class GuardReport:
    kept: list[Line] = field(default_factory=list)
    dropped: list[tuple[Line, str]] = field(default_factory=list)
    rewritten: list[tuple[Line, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.kept).strip()

    @property
    def citations(self) -> list[str]:
        out: list[str] = []
        for line in self.kept:
            for chunk_id in line.chunk_ids:
                if chunk_id not in out:
                    out.append(chunk_id)
        return out


def device_specific_spans(text: str) -> list[str]:
    spans: list[str] = []
    for pattern in DEVICE_CLAIM_PATTERNS:
        spans.extend(match.group(0) for match in pattern.finditer(text))
    return spans


def internal_marker_spans(text: str) -> list[str]:
    """Internal vocabulary found in a line that is about to be spoken."""
    spans: list[str] = []
    for pattern in INTERNAL_MARKER_PATTERNS:
        spans.extend(match.group(0) for match in pattern.finditer(text))
    return spans


def unsupported_cause_spans(text: str, support: str) -> list[str]:
    """Causes this line names that neither the caller nor a chunk supports."""
    spans: list[str] = []
    for pattern in CAUSE_CLAIM_PATTERNS:
        match = pattern.search(text)
        if match is not None and pattern.search(support) is None:
            spans.append(match.group(0))
    return spans


def firmware_version_spans(text: str) -> list[str]:
    spans: list[str] = []
    for pattern in FIRMWARE_VERSION_PATTERNS:
        spans.extend(match.group(0) for match in pattern.finditer(text))
    return spans


def output_guard(lines: Sequence[Line], *, support_text: str = "") -> GuardReport:
    """Drop any line that breaks a grounding, version, leak or cause rule.

    A safety line is never dropped for being device-specific — "unplug it and
    stop" is not a claim about the product — but it is still version-checked,
    because a version rendered inside a safety instruction is the same false
    claim as one rendered anywhere else.

    `support_text` is everything this turn is allowed to ground a cause in:
    the caller's own words across the session, and the text of the chunks
    retrieved for the entry in play. Milestone 6.5 adds the two rules that
    read it and `INTERNAL_MARKER_PATTERNS`, and both apply to **every** line
    kind including escalations — the two failures they exist to stop were both
    in escalation replies.
    """
    report = GuardReport()
    for line in lines:
        versions = firmware_version_spans(line.text)
        if versions:
            report.dropped.append(
                (
                    line,
                    "firmware-version-shaped token "
                    + ", ".join(repr(v) for v in versions)
                    + " — no path may emit a version (06 §4.6)",
                )
            )
            continue
        markers = internal_marker_spans(line.text)
        if markers:
            report.dropped.append(
                (
                    line,
                    "internal vocabulary "
                    + ", ".join(repr(m) for m in markers)
                    + " — reason strings, eval ids and docs references are "
                    "never spoken",
                )
            )
            continue
        # A `system` line is a statement about what this agent covers, not
        # about the caller's camera — "Power / overheating" is the name of a
        # `docs/02` category, not a claim that anything overheated. The cause
        # rule is about claims on the device, so it does not reach there. The
        # exemption is safe because a `system` line is never model-authored:
        # it is one of the fixed answers in `agent/router.py`, composed from
        # `ingest.metadata.ALL_MODELS` and `eval.ontology.CATEGORIES`.
        causes = (
            unsupported_cause_spans(line.text, support_text)
            if line.kind != "system"
            else []
        )
        if causes:
            report.dropped.append(
                (
                    line,
                    "cause "
                    + ", ".join(repr(c) for c in causes)
                    + " that the caller never mentioned and no chunk supports",
                )
            )
            continue
        if line.kind not in ("safety", "system"):
            spans = device_specific_spans(line.text)
            if spans and not line.chunk_ids:
                reason = (
                    "device-specific claim "
                    + ", ".join(repr(s) for s in spans)
                    + " with no Tier-1 citation (06 §4.5)"
                )
                if line.fallback and not device_specific_spans(line.fallback):
                    report.rewritten.append((line, reason))
                    report.kept.append(
                        Line(text=line.fallback, kind=line.kind, chunk_ids=[])
                    )
                else:
                    report.dropped.append((line, reason))
                continue
        report.kept.append(line)
    return report


# --------------------------------------------------------------------------
# Spoken forms
# --------------------------------------------------------------------------

#: Steps whose ontology description carries device specifics — a named control,
#: a documented string, a number with a unit. The description is the right
#: thing for a trace and the wrong thing to say out loud without a citation, so
#: these are the forms the agent actually speaks: they **ask** rather than
#: assert, which is also the better diagnostic move.
#:
#: `agent/test_core.py` asserts that every step whose generated spoken form
#: trips the device-claim detector is covered either here or by a
#: `SPOKEN_FALLBACK` the guard can substitute — so a new step in the ontology
#: can neither introduce an uncited claim nor get its line silently deleted.
SPOKEN_FORM: dict[str, str] = {
    "STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT": (
        "Without touching anything, can you tell me whether the camera is saying "
        "anything out loud, and what it says?"
    ),
    "STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST": (
        "Could you switch the camera into photo mode and take one picture, and "
        "tell me whether you hear a shutter sound?"
    ),
    "STEP.DEVICE.ENABLE_WIFI_ON_CAMERA": (
        "Could you turn the camera's Wi-Fi on from its own controls, and tell me "
        "what the screen shows when you do?"
    ),
    "STEP.DEVICE.HARD_RESET_PINHOLE": (
        "Could you press the recessed reset button on the camera body?"
    ),
    "STEP.SETTINGS.SWITCH_WIFI_BAND_2_4": (
        "Could you open the camera's settings and tell me what the Wi-Fi band is "
        "set to?"
    ),
    "STEP.SETTINGS.CHECK_LOOP_RECORDING": (
        "Could you open the camera's video settings and read out what loop "
        "recording is set to?"
    ),
    "STEP.SETTINGS.SET_DATE_TIME_AND_RETEST": (
        "Could you set the date and time, then leave the camera on power for "
        "about an hour, restart it and tell me whether the date held?"
    ),
    "STEP.OBSERVE.CHECK_UPDATE_INDICATOR": (
        "Please don't unplug anything. Could you watch the camera for a full "
        "minute and tell me whether any light or indicator is still changing?"
    ),
    "STEP.SAFETY.HOLD_DO_NOT_UNPLUG": (
        "Before anything else — please don't unplug it or switch it off. Cutting "
        "the power while it is writing is what turns this into a dead camera."
    ),
    "STEP.ASK.CARD_SPECS_AND_RATING": (
        "Could you read me what is printed on the card itself — the brand, the "
        "size, and any markings — and tell me roughly how long it has been in use?"
    ),
    "STEP.ASK.HARDWIRE_KIT_AND_CUTOFF": (
        "Is the camera wired into the car rather than plugged into a socket, and "
        "if so, was any cut-off setting mentioned when it was fitted?"
    ),
    "STEP.PHONE.MOVE_CLOSER_TO_CAMERA": (
        "Could you stand right next to the camera, in sight of it, and try again?"
    ),
    "STEP.PHONE.DOWNLOAD_SHORT_CLIP": (
        "Could you download one short clip to the phone rather than playing it, "
        "and tell me whether it finishes and roughly how long it takes?"
    ),
    "STEP.APP.CHECK_FIRMWARE_MENU": (
        "Could you open the app's menu and tell me whether there is an entry for "
        "updating the camera?"
    ),
    "STEP.APP.RETRY_CONNECT_BUTTON": (
        "On the app's live video screen, could you tap the option to retry the "
        "connection to the camera?"
    ),
    "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION": (
        "The app talks to the camera directly over the camera's own Wi-Fi rather "
        "than over the internet, which is why the phone asks for that permission. "
        "Knowing that, would you be willing to allow it?"
    ),
    #: The two `FAMILY.ESCALATE` steps. Their ontology descriptions are
    #: instructions to *us* — "say plainly ... and transfer", "hand to a human
    #: engineer with the handoff payload" — and `spoken_form` would otherwise
    #: read them out to the caller, which is the same class of leak as
    #: speaking an escalation reason string (Milestone 6.5, brief item (e)).
    "STEP.ESCALATE.OUT_OF_SCOPE_TRANSFER": (
        "That part is handled by a person on the team rather than by me, so "
        "I'll put you straight through — you don't have to work through "
        "anything with me first."
    ),
    "STEP.ESCALATE.HANDOFF": (
        "I'm going to hand this to one of our engineers, and I'll pass on "
        "everything you've told me so you don't have to say it twice."
    ),
    "STEP.ASK.PHYSICAL_TRAUMA_HISTORY": (
        "Has the camera ever been dropped, soaked, or left somewhere very hot?"
    ),
    #: Its description ends "Different step, SAME family (EVAL-12)", which is
    #: a note to whoever reads the ontology and not a sentence to say out
    #: loud. Without a spoken form here the guard's leak rule would drop the
    #: line and the turn would propose a step it never actually asked for.
    "STEP.CARD.FORMAT_ON_COMPUTER": (
        "Could you put the card into a computer and format it there?"
    ),

}

#: The de-specified form of a step line, used when the specific it names has no
#: Tier-1 citation this turn. Covers every step whose spoken form trips the
#: device-claim detector — an invariant `agent/test_core.py` asserts, so a new
#: step cannot arrive without one.
SPOKEN_FALLBACK: dict[str, str] = {
    "STEP.DEVICE.HARD_RESET_PINHOLE": (
        "Could you look on the camera body for a small recessed hole with a "
        "button inside it, and tell me whether you can find one?"
    ),
    "STEP.ASK.PARKED_POWER_SOURCE": (
        "Can I ask: how is the camera getting its power when the ignition is off?"
    ),
    "STEP.SETTINGS.CHECK_LOOP_RECORDING": (
        "Could you open the camera's video settings and read out what you see "
        "there?"
    ),
}

#: Strips the source citation the ontology descriptions carry — "(02 WIFI-02)",
#: "(06 §3.6)", "(03 EVAL-28)". Useful in a trace, not something to say.
_SOURCE_REF_RE = re.compile(r"\s*\((?:0\d|extension)[^)]*\)")
_TRAILING_META_RE = re.compile(r"\s*--\s*(?:the|a|an)\s+[^.]*$")


def spoken_form(step_id: str) -> str:
    """What the agent actually says to ask for this step."""
    if step_id in SPOKEN_FORM:
        return SPOKEN_FORM[step_id]
    step = ontology.STEPS[step_id]
    text = _SOURCE_REF_RE.sub("", step.description).strip()
    text = _TRAILING_META_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text).rstrip(" .") + "."
    if text.startswith("Ask "):
        rest = text[4:]
        return "Can I ask: " + rest[0].lower() + rest[1:]
    if step.family == "FAMILY.ESCALATE":
        return text
    first, _, rest = text.partition(" ")
    return f"Could you {first.lower()} {rest}".strip()


# --------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------


@dataclass
class TurnResult:
    """What one text-only diagnostic turn produces."""

    response_text: str
    state: DiagnosticState
    citations: list[str]
    taxonomy_id: str
    category: str
    step_id: str | None
    escalate: bool
    rationale: str
    #: The `agent/router.py` intent this turn was classified as, before triage.
    intent: str = router.SYMPTOM
    candidates: list[policy.CandidateDecision] = field(default_factory=list)
    dropped_claims: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def destructive_gate(self) -> dict[str, Any] | None:
        for candidate in self.candidates:
            if candidate.step_id == self.step_id and candidate.gate is not None:
                return candidate.gate.as_harness_gate()
        return None


@dataclass
class TurnContext:
    """Everything one turn needs that is **not** durable state.

    `docs/06` §3.3 keeps two stores apart, and §8.6 asks the checkpointer to
    persist the diagnostic record per turn. The working set of a single turn —
    the retrieval hits, the filter verdicts, the option list handed to the
    model, the composed lines — is derivable from the utterance and the record,
    so it is deliberately **not** checkpointed: it rides the graph's run
    context instead. That keeps the per-turn checkpoint write (§2.2 line 4)
    proportional to the state record rather than to the corpus.

    It also holds the two things that must never be serialised at all: the LLM
    handle and the path to the chunk file.
    """

    llm: Any | None = None
    chunks_path: str | None = None
    utterance: str = ""
    reported_outcome: str = ""
    trace: dict[str, Any] = field(default_factory=lambda: {"fallbacks": []})
    signals: UtteranceSignals = field(default_factory=UtteranceSignals)
    rule_flags: list[str] = field(default_factory=list)
    #: The pre-triage verdict of `agent/router.py` (06 §3.2's "evaluated before
    #: every transition"). Read by the nodes; written only in `begin_turn`.
    routing: router.Routing | None = None
    #: Set when the router can answer the turn itself -- a meta question, a
    #: greeting, or the context gate holding for a model ID. The diagnostic
    #: path does not run, and this is the whole of what gets said.
    router_reply: str | None = None
    #: The text `TRIAGE` classifies, when it is not simply this turn's
    #: utterance -- a turn resumed after the context gate triages the symptom
    #: and the answer together.
    triage_text: str = ""
    classification: Any | None = None
    shortlist: list[str] = field(default_factory=list)
    per_entry: dict[str, dict[str, Any]] = field(default_factory=dict)
    options: list[dict[str, Any]] = field(default_factory=list)
    taxonomy_id: str = ""
    chosen_step_id: str | None = None
    hypothesis_text: str = ""
    rationale: str = ""
    escalation: policy.EscalationDecision | None = None
    decisions: list[policy.CandidateDecision] = field(default_factory=list)
    hits: retrieval.RetrievalResult | None = None
    result: TurnResult | None = None


def begin_turn(state: DiagnosticState, ctx: TurnContext) -> None:
    """Open a turn: the turn counter, a fresh trace, and the interrupts.

    `docs/06` §3.2 puts the interrupts above the state diagram — "evaluated
    before every transition" — so they run here, once per turn, ahead of any
    node and whichever node this turn happens to start at. A hazard mentioned
    at turn four, on a turn that never passes through `TRIAGE`, is exactly the
    PWR-02 case §6.1 describes, and it has to be caught by the same code that
    catches it at turn one.

    Called by the graph runner rather than by a node, because every entry point
    into the graph shares it.
    """
    state.turn += 1
    ctx.trace["turn"] = state.turn
    ctx.trace.setdefault("fallbacks", [])

    signals = scan_utterance(ctx.utterance)
    ctx.signals = signals
    for hazard in signals.hazards:
        if hazard not in state.safety.hazard_flags:
            state.safety.hazard_flags.append(hazard)
    if signals.driving:
        state.safety.driving = "yes"
    if signals.footage_at_stake and state.safety.footage_at_stake == "none":
        state.safety.footage_at_stake = "wanted"
    #: Rule-derived flags only — `scan_utterance` on the caller's own words.
    #: These are the ones the escalation policy is allowed to act on (§5.1).
    ctx.rule_flags = list(signals.flags)

    # Milestone 6.5: the turn router (`agent/router.py`), which runs here for
    # the same reason the interrupts do — §3.2 evaluates both "before every
    # transition", and a scope gate that only runs on the turns that happen to
    # pass through `TRIAGE` is not a gate. It classifies; the nodes act.
    routing = router.route(ctx.utterance, state, flags=ctx.rule_flags)
    ctx.routing = routing
    ctx.trace["router"] = routing.as_trace()
    if routing.named_model is not None:
        _record_named_model(state, routing.named_model)
    scope_flagged = "out_of_scope_device" in ctx.rule_flags
    if routing.foreign_subject is not None and not scope_flagged:
        # §3.4: a device outside the documented line "routes to OUT_OF_SCOPE →
        # human". The flag is what carries that to `policy.escalation`, which
        # is where every escalation decision is made and where this one stays.
        ctx.rule_flags.append("out_of_scope_device")


def _record_named_model(state: DiagnosticState, named_model: str) -> None:
    """File a model the caller named as one weak signal, and no more.

    `docs/06` §3.4 is explicit: "a user saying 'R2' is treated as **one weak
    signal**, never as identification". `ModelSignal.from_probe` enforces that
    on its own — a `name` signal narrows nothing, so it cannot raise
    confidence above `UNKNOWN` and `reported_model` keeps saying `unknown`,
    which is what M1 grades. What the name *does* do is open the context gate:
    the caller has told us which camera is in front of them, so the turn has a
    subject and diagnosis can start.
    """
    if any(
        signal.signal == "name" and signal.value == named_model
        for signal in state.device.evidence
    ):
        return
    state.device.add_signal(
        ModelSignal.from_probe(signal="name", value=named_model, turn=state.turn)
    )


# ---- the nodes of docs/06 §3.2, one function per state -------------------
#
# Each one is a plain function of (state, ctx). None of them chooses what runs
# next: that is the routers' job in `agent/graph.py`, and the routers read the
# state record, never the model. `agent/graph.py` is the only place these are
# sequenced; `diagnose` below is the public turn and goes through the graph.


def step_greet(state: DiagnosticState, ctx: TurnContext) -> None:
    """`GREET`. The consent disclosure of §6.3 is Phase 2b — there is no audio
    channel to disclose on yet — so in text mode this records that the session
    opened and nothing else."""
    ctx.trace["greeted"] = True


def step_symptom_capture(state: DiagnosticState, ctx: TurnContext) -> None:
    """`SYMPTOM_CAPTURE`. The caller's own words, kept unparaphrased (§3.3).

    §3.2 puts three things in this state — "verbatim symptom + change event +
    prior attempts" — and Milestone 4.4 adds the fourth thing a caller
    volunteers unprompted: **an answer to a question nobody has asked yet**.
    `docs/06` §3.6 already makes mapping volunteered information onto canonical
    ids a per-turn job; `docs/03` EVAL-26 is the case where it matters, with
    "Permission: local network denied (caller-stated)" in the known context and
    "asking them to grant it without explaining why, when they have already
    said they refused it" named as the wrong response. An answer we were
    *given* is as real as one we asked for.
    """
    if ctx.utterance:
        state.problem.verbatim_symptom = (
            state.problem.verbatim_symptom or ctx.utterance
        )
    volunteered: list[dict[str, str]] = []
    for step_id, reading in answers.volunteered_answers(ctx.utterance):
        if step_id in state.answers:
            continue
        state.record_answer(
            step_id,
            reading,
            verbatim=ctx.utterance,
            source="user_volunteered",
        )
        volunteered.append({"step_id": step_id, "reading": reading})
    if volunteered:
        ctx.trace["volunteered_answers"] = volunteered


def step_triage(state: DiagnosticState, ctx: TurnContext) -> None:
    """`TRIAGE`: interrupts, the classifier, and the shortlist it is allowed to
    produce. Exits with a taxonomy id, `KNOWN-GAP` or `NO_MATCH` (§3.2)."""
    utterance = ctx.triage_text or ctx.utterance
    trace = ctx.trace
    llm = ctx.llm
    signals = ctx.signals
    rule_flags = ctx.rule_flags

    # Milestone 6.5. Two of the router's verdicts settle triage outright, and
    # both of them are about what the turn *is* rather than what is wrong with
    # the camera, which is why they are decided before the classifier runs
    # rather than argued with afterwards.
    routing = ctx.routing
    if routing is not None and routing.reply:
        # A meta question, a greeting, or the context gate holding for a model
        # ID. There is nothing to triage: the turn already has its answer, and
        # `step_hypothesise` / `step_select_step` stand down.
        ctx.router_reply = routing.reply
        ctx.shortlist = []
        trace["router_short_circuit"] = routing.intent
        if routing.needs_model_id:
            # The context gate has put the model question; intake owns what
            # happens to the answer.
            intake.note_asked(state, intake.SLOT_MODEL)
        return
    if routing is not None and routing.foreign_subject is not None:
        # §3.4: an out-of-line device "routes to OUT_OF_SCOPE → human". The
        # entry is forced here rather than left to the classifier because the
        # classifier is the thing that routed a Garmin to PWR-01.
        ctx.shortlist = ["OUT_OF_SCOPE"]
        trace["shortlist"] = ["OUT_OF_SCOPE"]
        trace["rule_flags"] = list(rule_flags)
        trace["device_scope"] = routing.foreign_subject
        return

    # Milestone 6.7. A question tree that is already open owns this turn: the
    # caller's words are the answer to the intake agent's last question, and
    # reading them through the keyword floor first would let "it's the Wi-Fi"
    # skip straight to a guess at which Wi-Fi fault. Only a turn that is a
    # symptom, with no hazard and no request for a person, is an answer.
    pinned_entry: str | None = None
    intake_gave_up = False
    if (
        intake.is_active(state)
        and routing is not None
        and routing.intent == router.SYMPTOM
        and policy.intake_can_ask(
            state,
            rule_flags=rule_flags,
            has_dashcam_context=(
                router.has_dashcam_mention(ctx.utterance)
                or router.has_model_context(state)
                or router.has_subject(state)
            ),
            is_clear_out_of_scope=router.is_clear_out_of_scope(ctx.utterance),
        )
    ):
        answer = intake.consult(state, ctx.utterance)
        trace["intake"] = answer.as_trace()
        if answer.action == intake.ASK:
            ctx.router_reply = answer.reply
            ctx.shortlist = []
            trace["router_short_circuit"] = "intake"
            return
        pinned_entry = answer.entry if answer.action == intake.HANDOFF else None
        intake_gave_up = answer.action == intake.GIVE_UP

    # ---- TRIAGE: Nova Micro, with the rule-based router as the floor ----
    classification = None
    if llm is not None:
        try:
            classification = llm.classify(utterance)
        except Exception as exc:  # noqa: BLE001 — any failure falls back
            trace["fallbacks"].append(f"classify: {type(exc).__name__}: {exc}")
    shortlist: list[str] = []
    model_flags: list[str] = []
    if classification is not None:
        trace["classification"] = {
            "category": classification.category,
            "taxonomy_ids": classification.taxonomy_ids,
            "flags": classification.flags,
        }
        shortlist.extend(classification.taxonomy_ids)
        model_flags = [f for f in classification.flags if f not in rule_flags]
    # The union, used only where a flag can make the turn *more* cautious:
    # believing a firmware write is in progress blocks the power-cycle family,
    # and believing footage is at stake removes every footage-erasing step with
    # no consent path. Being wrong there costs a candidate; being wrong about
    # escalation costs a caller their session, so that direction stays
    # rule-derived (see `policy.escalation`).
    flags = rule_flags + model_flags
    if "firmware_update_in_progress" in flags:
        state.firmware_update_in_progress = True
    if "footage_at_stake" in flags and state.safety.footage_at_stake == "none":
        state.safety.footage_at_stake = "wanted"

    rule_entry = baseline.match_taxonomy(utterance)
    if rule_entry not in shortlist:
        shortlist.append(rule_entry)
    # `OUT_OF_SCOPE` is put at the head of the shortlist by the *keyword*
    # detector, never by the classifier's flag: measured over three runs, Nova
    # Micro flagged `out_of_scope` on scenarios about a failing card and a
    # wrong timestamp, and each one became an escalation false positive.
    if "out_of_scope" in rule_flags and "OUT_OF_SCOPE" not in shortlist:
        shortlist.insert(0, "OUT_OF_SCOPE")
    # Same for `hazard`: the rule-based hazard detector is the authority (§6.1),
    # and it is the one that has already written `state.safety.hazard_flags`.
    if signals.hazards:
        shortlist = ["NO_MATCH"] + [s for s in shortlist if s != "NO_MATCH"]
    # §3.2: `TRIAGE` exits with "Taxonomy ID **or** `KNOWN-GAP` **or**
    # `NO_MATCH`" — alternatives, not a ranking. `_triage_exit` decides which
    # of the two it is; `_demote_residual_entries` is the taxonomy-ID branch.
    coverage = symptoms.assess(ctx.utterance, shortlist)
    trace["symptom_coverage"] = {
        "facets": coverage.facets,
        "unmapped": coverage.unmapped,
        "per_entry": coverage.per_entry,
    }
    if coverage.unmatched:
        shortlist = ["NO_MATCH"]
        trace["triage_no_match"] = coverage.reason
    else:
        shortlist = _demote_residual_entries(
            shortlist, rule_flags, signals, ctx.utterance
        )
        shortlist = _add_cross_checks(shortlist, ctx.utterance, trace)
    shortlist = shortlist[:4]
    if pinned_entry is not None:
        # The caller told the intake agent which fault this is; that is the
        # entry, whatever the keyword floor made of the words.
        shortlist = [pinned_entry]
        trace["intake_pinned_entry"] = pinned_entry
    elif intake_gave_up:
        shortlist = ["NO_MATCH"]
    trace["shortlist"] = list(shortlist)
    trace["rule_flags"] = list(rule_flags)
    trace["model_flags_ignored_for_escalation"] = list(model_flags)

    ctx.classification = classification
    ctx.shortlist = shortlist


def has_model_signals(ctx: TurnContext) -> bool:
    """Whether `MODEL_ID` has anything to do this turn (§3.2: it "may run in
    parallel or be deferred")."""
    return bool(
        ctx.classification is not None and getattr(ctx.classification, "model_signals", None)
    )


def step_model_id(state: DiagnosticState, ctx: TurnContext) -> None:
    """`MODEL_ID` (§3.4). Every signal is resolved through the discriminator
    ladder, so a signal that narrows nothing cannot raise confidence."""
    classification = ctx.classification
    if classification is None:
        return
    for raw in classification.model_signals:
        # `ModelSignal.from_probe` resolves the `docs/06` §3.4 ladder —
        # which models this answer leaves in contention — rather than
        # recording a bare value. Building the signal without that
        # narrowing is the Milestone 3 defect: confidence rose on evidence
        # that had never excluded a single model.
        state.device.add_signal(
            ModelSignal.from_probe(
                signal=raw.get("signal", "name"),
                value=raw.get("value", ""),
                turn=state.turn,
            )
        )


def step_hypothesise(state: DiagnosticState, ctx: TurnContext) -> None:
    """`HYPOTHESISE`: the evidence behind each shortlisted cause, retrieved
    per entry under the model filter (§4.6).

    §3.2 draws this node with "re-rank on change event (cross-cutting)" written
    inside it, and Milestone 4.4 gives it the other thing that re-ranks
    everything: **an answer that names where the conversation goes next**. See
    `_implied_entry`.
    """
    trace = ctx.trace
    trace["device_confidence"] = state.device.confidence
    trace["device_candidates"] = list(state.device.candidates)

    if ctx.router_reply:
        return

    query = ctx.utterance
    if not ctx.shortlist and not state.problem.taxonomy_id:
        # The context gate held the opening turn, so `TRIAGE` never reached an
        # entry and the record has none to continue from. The caller has now
        # answered, so the symptom and the answer are triaged together — the
        # §3.2 `TRIAGE` exit this session still owes, taken on the first turn
        # that has enough to take it with.
        ctx.triage_text = f"{state.problem.verbatim_symptom} {ctx.utterance}".strip()
        trace["triage_deferred_to_turn"] = state.turn
        step_triage(state, ctx)
        query = ctx.triage_text
    if not ctx.shortlist:
        # A continuing turn: §3.2's `EVALUATE_OUTCOME` → `HYPOTHESISE` edge
        # re-ranks causes for a symptom triage already classified, so the entry
        # comes from the record and the query leads with the symptom as the
        # caller first stated it rather than with "I tried that, no change".
        ctx.shortlist = [state.problem.taxonomy_id or "NO_MATCH"]
        trace["shortlist_from_record"] = list(ctx.shortlist)
        query = f"{state.problem.verbatim_symptom} {ctx.utterance}".strip()

    # The answer decides the route, and it decides it on every turn — triage
    # does not run again on a continuing turn, so doing this only in `TRIAGE`
    # would act on EVAL-26's volunteered answer and miss EVAL-23's, which
    # arrives on the branch turn. One place, both cases.
    implied = _implied_entry(state)
    if implied is not None and ctx.shortlist[:1] != [implied[0]]:
        trace["recategorised"] = {
            "to": implied[0],
            "by": implied[1],
            "from": list(ctx.shortlist),
        }
        ctx.shortlist = [implied[0]]

    per_entry: dict[str, dict[str, Any]] = {}
    for entry in ctx.shortlist:
        hits = retrieval.retrieve(
            query,
            confidence=state.device.confidence,
            model=state.device.model,
            hw_revision=state.device.hw_revision,
            candidates=state.device.candidates,
            category=ontology.category_of(entry)
            if entry not in ("NO_MATCH", "OUT_OF_SCOPE")
            else None,
            taxonomy_id=entry if entry not in ("NO_MATCH", "OUT_OF_SCOPE") else None,
            path=ctx.chunks_path,
        )
        per_entry[entry] = {"hits": hits, "decisions": []}
    ctx.per_entry = per_entry


def step_select_step(state: DiagnosticState, ctx: TurnContext) -> None:
    """`SELECT_STEP` (§3.5): the filter chain, then one action.

    The model is handed the kept candidates and asked to choose among them;
    its pick is checked for membership anyway, and the escalation decision
    below is never its call.
    """
    if ctx.router_reply:
        # The router answered this turn. No step, no escalation, no entry: a
        # question about the system is not a diagnosis that happened to have
        # none, and recording it as one would put `NO_MATCH` in the record and
        # escalate the next turn out of it.
        ctx.taxonomy_id = ""
        ctx.chosen_step_id = None
        ctx.escalation = policy.EscalationDecision(escalate=False)
        ctx.decisions = []
        ctx.hits = None
        ctx.options = []
        ctx.rationale = (
            "answered by the turn router before triage: "
            + (ctx.routing.reason if ctx.routing is not None else "short circuit")
        )
        return

    utterance = ctx.utterance
    trace = ctx.trace
    llm = ctx.llm
    shortlist = ctx.shortlist
    per_entry = ctx.per_entry

    # ---- the §3.5 filter chain, per shortlisted entry -------------------
    for entry in shortlist:
        hits = per_entry[entry]["hits"]
        per_entry[entry]["decisions"] = policy.candidate_steps(
            state, taxonomy_id=entry, retrieved_step_ids=hits.step_ids
        )

    #: A step whose destructive gate was refused is final for that step
    #: (§3.2), so it never returns to the option list in this session.
    refused = set(state.notes.get("gate_refused", []))

    options: list[dict[str, Any]] = []
    #: One line per step, not per (step, entry). Two shortlisted entries that
    #: share a candidate used to render it twice, which tells the model nothing
    #: and spends the same attention twice — EVAL-23's option list carried
    #: three duplicate pairs. The first entry offering it keeps it, which is
    #: shortlist order, which is triage's own ranking.
    for entry, bundle in per_entry.items():
        for decision in bundle["decisions"]:
            if not decision.kept or decision.step_id in refused:
                continue
            if any(o["step_id"] == decision.step_id for o in options):
                continue
            options.append(
                {
                    "step_id": decision.step_id,
                    "taxonomy_id": entry,
                    "description": ontology.STEPS[decision.step_id].description,
                    #: §3.5's ranking input, from `docs/02`'s own readings: what
                    #: this step's answer is documented to tell the session
                    #: apart. Empty for a step whose outcome is a change rather
                    #: than information.
                    "discriminates": _discriminations(decision.step_id),
                }
            )
    trace["options"] = [o["step_id"] for o in options]

    # ---- LLM turn reasoning, over the legal set only --------------------
    decision_obj = None
    primary = shortlist[0]
    if llm is not None and options:
        chunk_payload = _chunk_payload(per_entry, shortlist)
        try:
            decision_obj = llm.decide(
                utterance=utterance,
                state_summary=summarise_state(state),
                options=options,
                chunks=chunk_payload,
            )
        except Exception as exc:  # noqa: BLE001
            trace["fallbacks"].append(f"decide: {type(exc).__name__}: {exc}")

    # The model is prompted with the legal set and asked to choose from it, but
    # being asked is not being constrained: a model can name a step the filter
    # removed, or one that was never on the menu at all. `options` *is* the
    # legal set — it is built from kept decisions only — so membership in it is
    # the whole check, and failing it drops the turn to the floor rather than
    # letting a preference outrank a filter (06 §3.5). Without this, M4 and M5
    # would be properties of the prompt instead of properties of the code.
    model_step = decision_obj.next_step if decision_obj is not None else None
    model_step_legal = bool(model_step) and model_step in {
        option["step_id"] for option in options
    }
    if model_step and not model_step_legal:
        trace["fallbacks"].append(
            f"decide: rejected {model_step} — not in the legal option set"
        )

    # ---- §3.5 rank: the one candidate class the model may not outrank ----
    #
    # A question whose documented readings land on two of the entries triage
    # currently holds settles *which live cause the session is in*; every
    # other candidate probes inside a cause that may be the wrong one. §3.5
    # ranks by "expected information gain across the live causes", and that
    # phrase has exactly one unambiguous reading. See
    # `policy.cross_entry_discriminators` for why this half is policy and the
    # rest of the ranking stays the model's.
    splitters = policy.cross_entry_discriminators(
        state,
        {entry: bundle["decisions"] for entry, bundle in per_entry.items()},
        list(shortlist),
    )
    if splitters:
        trace["cross_entry_discriminators"] = [s for s, _ in splitters]

    if splitters and (not model_step_legal or model_step != splitters[0][0]):
        split_step, split_entry = splitters[0]
        taxonomy_id = split_entry
        selected = policy.select(
            per_entry[split_entry]["decisions"], preferred=split_step
        )
        chosen_step_id: str | None = selected.step_id if selected else None
        hypothesis_text = decision_obj.hypothesis if decision_obj is not None else ""
        rationale = (
            f"{split_step} splits the live causes "
            f"({', '.join(e for e in shortlist if e not in policy.RESIDUAL_ENTRIES)}): "
            "its answer decides which one this is, so 06 §3.5 ranks it above a "
            "probe inside either"
        )
        if decision_obj is not None:
            trace["llm_escalate_vote"] = decision_obj.escalate
            if model_step_legal:
                trace["fallbacks"].append(
                    f"rank: {model_step} outranked by {split_step} — "
                    "a step that splits the live causes (06 §3.5)"
                )
    elif decision_obj is not None and model_step_legal:
        taxonomy_id = _entry_for_step(
            model_step, options, decision_obj.taxonomy_id, primary
        )
        selected = policy.select(
            per_entry[taxonomy_id]["decisions"], preferred=model_step
        )
        chosen_step_id = selected.step_id if selected else None
        hypothesis_text = decision_obj.hypothesis
        rationale = decision_obj.reason
        trace["llm_escalate_vote"] = decision_obj.escalate
    else:
        # The baseline floor: first legal candidate of the first shortlisted
        # entry (`eval/baseline.py`). The whole point of having a dumb agent is
        # that it is still there when the clever one is not.
        taxonomy_id = primary
        selected = policy.select(per_entry[primary]["decisions"])
        chosen_step_id = selected.step_id if selected else None
        hypothesis_text = ""
        rationale = (
            "LLM unavailable, invalid, or outvoted by the filter; rule-based "
            f"fallback — keyword route to {taxonomy_id}, first legal candidate"
        )

    # ---- §5.1: an escalation-first entry is triage's to hold, not the
    #      reasoner's to route around ------------------------------------
    #
    # Milestone 6.4, from `noise:EVAL-30`. `docs/02` makes `FW-02`
    # escalation-first *unconditionally* — "in parallel with any step" — and
    # `policy.escalation` says in as many words that escalation is a policy
    # decision and not a model one. It was only half true. The trigger is keyed
    # on `taxonomy_id`, and `taxonomy_id` is whichever entry the reasoner
    # routed its chosen step to, so the model could turn an unconditional
    # trigger off by preferring a sibling — without ever being asked about
    # escalation.
    #
    # Measured on EVAL-30 ("did the update yesterday ... sits on the logo
    # screen ... unplugged it ten times"), which `docs/03` grades
    # `escalation_expected: true` with `FW-02` and
    # `STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR`: triage put `FW-02` first on every
    # run, and Nova Pro then re-routed to `PWR-04` on **three of six** live
    # turns, taking category `FW`→`PWR`, the step to
    # `STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY` and `escalate` `True`→`False`. The
    # same utterance, the same session kind, the same shortlist: the handoff a
    # suspected brick is owed was a coin flip. That is also the whole of its
    # M10 divergence — the voice leg drew one face and the typed leg the other,
    # and no part of it was modality.
    #
    # So the escalation-bound entry is pinned when *triage* put it first, which
    # is the same structural reading §5.1 already uses for "`NO_MATCH` **from
    # triage**" rather than "`NO_MATCH` was on the shortlist". It is
    # deliberately `primary` and not "anywhere in the shortlist": a suspected
    # brick ranked third behind two live causes is a guess, and `docs/03` runs
    # 26 negative controls against exactly that kind of eagerness.
    #
    # The step is re-selected from the pinned entry's own legal set, and
    # `_clarifying_step` is what picks it rather than `policy.select`, because
    # `suspected_brick` is not in `HARD_STOP_CODES`: FW-02 escalates *in
    # parallel with* a step, so spending the turn on `STEP.ESCALATE.HANDOFF` —
    # `policy.select`'s first legal candidate here — would announce the handoff
    # that is already happening and ask nothing. `docs/03` EVAL-30 asks for the
    # other thing in so many words: "escalate, and while doing so ask the
    # single question worth asking".
    if (
        primary in policy.ESCALATION_BOUND_ENTRIES
        and taxonomy_id != primary
        and policy.legal_step_ids(per_entry[primary]["decisions"])
    ):
        trace["fallbacks"].append(
            f"rank: {taxonomy_id} outranked by {primary} — triage's primary entry "
            "is escalation-first, and §5.1 is not the model's to decline (02)"
        )
        outranked = taxonomy_id
        taxonomy_id = primary
        pinned = per_entry[primary]["decisions"]
        fallback = policy.select(pinned)
        chosen_step_id = _clarifying_step(pinned) or (
            fallback.step_id if fallback else None
        )
        # The model's sentence explained the entry that just lost. Carrying it
        # over would file a hypothesis about `outranked` under `primary`.
        hypothesis_text = ""
        rationale = (
            f"{primary} is escalation-first and triage ranked it first, so the turn "
            f"is {primary}'s and not {outranked}'s: a suspected brick is a human's "
            "outcome (02, 06 §5.1)"
        )

    decisions = per_entry[taxonomy_id]["decisions"]
    hits = per_entry[taxonomy_id]["hits"]

    # Milestone 6.7: a vague symptom is the intake agent's to ask about, and a
    # turn that is about to be asked about must not leave `NO_MATCH` in the
    # record -- the next turn would read it as a finished diagnosis and escalate
    # out of the question tree. So the record write waits for the policy.
    intake_may_ask = taxonomy_id == "NO_MATCH" and policy.intake_can_ask(
        state,
        rule_flags=ctx.rule_flags,
        genuine_no_match=bool(trace.get("triage_no_match")),
        has_dashcam_context=(
            router.has_dashcam_mention(utterance)
            or router.has_model_context(state)
            or router.has_subject(state)
        ),
        is_clear_out_of_scope=router.is_clear_out_of_scope(utterance),
    )

    def record_entry() -> None:
        state.problem.taxonomy_id = taxonomy_id
        state.problem.category = ontology.category_of(taxonomy_id)
        if hypothesis_text:
            state.problem.push_hypothesis(
                Hypothesis(
                    cause_id=_cause_id(taxonomy_id, hypothesis_text),
                    text=hypothesis_text,
                    chunk_ids=hits.chunk_ids,
                )
            )

    if not intake_may_ask:
        record_entry()

    # ---- escalation (policy, never the model) ---------------------------
    # `routable_alternatives` is what makes "NO_MATCH from triage" different
    # from "the classifier said NO_MATCH": the other shortlisted entries that
    # still have a legal step to offer. With one in hand, a residual entry is
    # a vote, not a trigger (`policy.escalation`).
    #
    # Milestone 3.3: having a legal step is necessary and not sufficient. An
    # entry that explains a minority of the reported symptoms with its own
    # discriminating condition absent has a legal step and is still the
    # nearest category forced (§4.7), so it does not defeat `NO_MATCH` here
    # either — the same test `_demote_residual_entries` applies upstream.
    facets = symptoms.reported_facets(utterance)
    routable_alternatives = [
        entry
        for entry in shortlist
        if entry != taxonomy_id
        and entry not in policy.RESIDUAL_ENTRIES
        and not symptoms.is_nearest_category_force(entry, utterance, facets)
        and policy.legal_step_ids(per_entry[entry]["decisions"])
    ]
    escalation = policy.escalation(
        state,
        taxonomy_id=taxonomy_id,
        legal_steps=policy.legal_step_ids(decisions),
        flags=ctx.rule_flags,
        routable_alternatives=routable_alternatives,
        intake_can_ask=intake_may_ask,
    )
    if escalation.route_to_intake:
        answer = intake.consult(state, utterance)
        trace["intake"] = answer.as_trace()
        trace["escalation_declined"] = escalation.declined
        if answer.action == intake.ASK:
            ctx.router_reply = answer.reply
            trace["router_short_circuit"] = "intake"
            ctx.taxonomy_id = ""
            ctx.chosen_step_id = None
            ctx.escalation = policy.EscalationDecision(escalate=False)
            ctx.decisions = []
            ctx.hits = None
            ctx.options = []
            ctx.rationale = "the symptom is too vague to triage; the intake agent asked"
            return
    if intake_may_ask:
        record_entry()
    if escalation.escalate:
        state.escalate(escalation.reason_code, escalation.reason)
        if escalation.reason_code in HARD_STOP_CODES:
            chosen_step_id = policy.escalation_step(decisions, taxonomy_id)
    elif chosen_step_id is not None and (
        ontology.STEPS[chosen_step_id].family == "FAMILY.ESCALATE"
    ):
        # Not escalating, so do not propose a handoff: that pairing is how a
        # declined trigger would leak out as an escalation anyway. Take the
        # clarifying question the entry offers instead — for `NO_MATCH` that is
        # EVAL-28's trauma-history question, "the one question that makes an
        # unmatched-symptom handoff useful".
        chosen_step_id = _clarifying_step(decisions) or chosen_step_id
    trace["escalation"] = escalation.triggers
    trace["escalation_declined"] = escalation.declined

    ctx.taxonomy_id = taxonomy_id
    ctx.chosen_step_id = chosen_step_id
    ctx.hypothesis_text = hypothesis_text
    ctx.rationale = rationale
    ctx.escalation = escalation
    ctx.decisions = decisions
    ctx.hits = hits
    ctx.options = options


def selected_step_is_destructive(ctx: TurnContext) -> bool:
    """Whether `SELECT_STEP` must route through `DESTRUCTIVE_GATE` (§3.2)."""
    step_id = ctx.chosen_step_id
    return bool(step_id) and ontology.STEPS[step_id].destructive


def step_destructive_gate(state: DiagnosticState, ctx: TurnContext) -> None:
    """`DESTRUCTIVE_GATE` (§6.4). Reads the gate record the filter already
    wrote for this step — cause, consequence, consent, all structured fields —
    and never re-derives consent from the transcript.

    A refusal is final for that step (§3.2), so the step id is written to the
    durable record and `SELECT_STEP` will not offer it again.
    """
    step_id = ctx.chosen_step_id
    gate = None
    for recorded in reversed(state.gates):
        if recorded.step_id == step_id:
            gate = recorded
            break
    ctx.trace["destructive_gate"] = (
        {"step_id": step_id, "decision": gate.decision, "consent": gate.consent_state}
        if gate is not None
        else {"step_id": step_id, "decision": "blocked", "consent": "no record"}
    )
    if gate is not None and gate.decision == "allowed":
        return
    refused = state.notes.setdefault("gate_refused", [])
    if step_id not in refused:
        refused.append(step_id)
    ctx.chosen_step_id = None


def gate_allows_step(ctx: TurnContext) -> bool:
    return ctx.chosen_step_id is not None


def step_propose_step(state: DiagnosticState, ctx: TurnContext) -> None:
    """`PROPOSE_STEP`: exactly one action, composed and then guarded."""
    _compose_turn(state, ctx)


def step_escalate(state: DiagnosticState, ctx: TurnContext) -> None:
    """`ESCALATE`: the handoff, delivered in parallel with any step that is
    still legal (`docs/02` FW-02, `docs/03` EVAL-24)."""
    if ctx.escalation is None:  # reached from a ceiling, not from SELECT_STEP
        ctx.escalation = policy.EscalationDecision(
            escalate=True,
            reason_code=state.escalation.reason_code or "ceiling",
            reason=state.escalation.reason,
            triggers=[state.escalation.reason] if state.escalation.reason else [],
        )
    _compose_turn(state, ctx)


def step_await_outcome(state: DiagnosticState, ctx: TurnContext) -> None:
    """`AWAIT_OUTCOME`: the step has been spoken and the turn is waiting for
    the caller to report what happened. No turn limit (§3.2)."""
    ctx.reported_outcome = ctx.reported_outcome or parse_outcome(ctx.utterance)
    ctx.trace["reported_outcome"] = ctx.reported_outcome
    if not ctx.reported_outcome:
        _compose_turn(state, ctx)


def outcome_reported(ctx: TurnContext) -> bool:
    return bool(ctx.reported_outcome)


def step_evaluate_outcome(state: DiagnosticState, ctx: TurnContext) -> None:
    """`EVALUATE_OUTCOME`: the two records that make M4 and the branches work.

    The step the agent proposed last turn is written into the ledger with the
    outcome the caller reported, which is what blocks it — and its whole
    family — from ever being proposed again (§3.5).

    **Milestone 4.4: a question also gets its answer recorded.** An outcome is
    the wrong shape for a question — "did it help?" is not what "were the clips
    locked?" returns — so the ledger entry alone threw the information away and
    the policy layer, which may not read the transcript (§3.3), had nothing to
    act on. Both records are written here, both from the same reply, and
    neither replaces the other: the ledger still gets its entry, so nothing
    about no-repeat changes.
    """
    step_id = state.notes.get("proposed_step_id")
    if step_id and step_id in ontology.STEPS:
        state.record_attempt(
            step_id,
            ctx.reported_outcome,
            source="agent_proposed",
            verbatim=ctx.utterance,
        )
        ctx.trace["ledger_entry"] = {
            "step_id": step_id,
            "outcome": ctx.reported_outcome,
        }
        if _is_question(step_id):
            reading = answers.read_answer(step_id, ctx.utterance)
            state.record_answer(step_id, reading, verbatim=ctx.utterance)
            ctx.trace["answer"] = {"step_id": step_id, "reading": reading}
    ctx.trace["ceiling_breaches"] = state.ceiling_breaches()


def _is_question(step_id: str) -> bool:
    """Whether this step's product is information rather than a change.

    The two no-repeat-exempt families of `docs/06` §3.6 — `FAMILY.ASK` and
    `FAMILY.OBSERVE` — plus any step `agent/answers.py` holds a reading for.
    `STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION` is the case for that last
    clause: `docs/02` APP-03 makes it a question ("then ask whether they are
    willing to grant it") and the ontology files it under `FAMILY.APP_STATE`
    because it also changes app state.
    """
    return (
        ontology.STEPS[step_id].no_repeat_exempt
        or step_id in answers.ANSWER_RULES
    )


def outcome_resolved(ctx: TurnContext) -> bool:
    return ctx.reported_outcome == "success"


def step_verify_resolved(state: DiagnosticState, ctx: TurnContext) -> None:
    """`VERIFY_RESOLVED`: `docs/01` M8 counts a resolution only when the user
    states the symptom is gone, so this state exists to record that they did."""
    state.notes["resolution_confirmed_at_turn"] = state.turn
    ctx.trace["resolution_confirmed"] = True


def step_close(state: DiagnosticState, ctx: TurnContext) -> None:
    """`CLOSE`: resolved, honest non-fault, or explicit non-closure (§3.2)."""
    ctx.chosen_step_id = None
    _compose_turn(state, ctx, closing=True)


#: Rule-based outcome parsing. Deterministic on purpose: which step goes into
#: the ledger, and therefore what M4 blocks, is not a thing a model may decide.
#: An unrecognised answer is `unclear`, which `eval.ontology` already treats as
#: blocking — re-proposing a step the caller may already have done is the exact
#: behaviour `docs/01` M4 forbids.
OUTCOME_PATTERNS: tuple[tuple[str, str], ...] = (
    ("worse", r"\bworse\b|\bgot worse\b|\bnow it (?:won'?t|doesn'?t)\b"),
    (
        "success",
        r"\b(?:that )?(?:worked|fixed|sorted)\b|\bit'?s (?:working|back|fine) now\b|"
        r"\bno more\b|\ball good\b",
    ),
    (
        "not_attempted",
        r"\bhaven'?t\b|\bnot yet\b|\bcan'?t (?:do|try) that\b|\bdidn'?t try\b",
    ),
    (
        "no_change",
        r"\b(?:still|same)\b|\bno (?:change|difference|luck)\b|\bdidn'?t (?:work|help)\b|"
        r"\bnothing (?:changed|happened)\b|\btried that\b",
    ),
)


def parse_outcome(utterance: str) -> str:
    """Map a reply to one of `eval.ontology.VALID_OUTCOMES`, or `""`."""
    text = utterance.lower().strip()
    if not text:
        return ""
    for outcome, pattern in OUTCOME_PATTERNS:
        if re.search(pattern, text):
            return outcome
    return "unclear"


def _compose_turn(
    state: DiagnosticState, ctx: TurnContext, *, closing: bool = False
) -> None:
    """Compose the spoken lines, run the output guard, build the `TurnResult`.

    One composition path for every terminal node of a turn: a guard that some
    nodes skip is a guard nobody has tested.
    """
    escalation = ctx.escalation or policy.EscalationDecision(escalate=False)
    hits = ctx.hits if ctx.hits is not None else retrieval.RetrievalResult()
    if ctx.router_reply:
        # Milestone 6.5. The router answered the turn, so this is the whole of
        # it: one line, about this system rather than about the camera, and
        # still guarded — `system` is exempt from the citation rule and from
        # nothing else.
        lines = [Line(ctx.router_reply, kind="system")]
    else:
        lines = _compose(
            state=state,
            step_id=ctx.chosen_step_id,
            hypothesis=ctx.hypothesis_text,
            hits=hits,
            escalation=escalation,
        )
    if closing:
        lines.append(
            Line(
                "I'll close this off here — if the symptom comes back, start a new "
                "session and tell them what we already tried.",
                kind="prose",
            )
        )
    report = output_guard(lines, support_text=_support_text(state, ctx, hits))
    for line, reason in report.dropped:
        state.notes.setdefault("dropped_claims", []).append(
            {"text": line.text, "reason": reason}
        )
    for line, reason in report.rewritten:
        state.notes.setdefault("rewritten_claims", []).append(
            {"text": line.text, "reason": reason, "spoken_instead": line.fallback}
        )
    for line in report.kept:
        if line.chunk_ids:
            state.record_claim(
                line.text, line.chunk_ids, retrieval_date=_retrieval_date(hits)
            )

    #: A router-answered turn has no taxonomy entry and is not pretending to:
    #: `NO_MATCH` here would be a diagnosis that failed, which is a different
    #: thing from a turn that was never a diagnosis.
    taxonomy_id = (
        ""
        if ctx.router_reply
        else (ctx.taxonomy_id or state.problem.taxonomy_id or "NO_MATCH")
    )
    #: What `EVALUATE_OUTCOME` will write into the ledger next turn.
    if ctx.chosen_step_id is not None:
        state.notes["proposed_step_id"] = ctx.chosen_step_id
    ctx.result = TurnResult(
        response_text=report.text,
        state=state,
        citations=report.citations,
        taxonomy_id=taxonomy_id,
        category=(
            ""
            if not taxonomy_id
            else state.problem.category or ontology.category_of(taxonomy_id)
        ),
        intent=ctx.routing.intent if ctx.routing is not None else router.SYMPTOM,
        step_id=ctx.chosen_step_id,
        escalate=escalation.escalate,
        rationale=ctx.rationale,
        candidates=ctx.decisions,
        dropped_claims=[reason for _, reason in report.dropped],
        trace=ctx.trace | {"retrieval_funnel": hits.funnel, "cited": hits.chunk_ids},
    )


def _support_text(
    state: DiagnosticState, ctx: TurnContext, hits: retrieval.RetrievalResult
) -> str:
    """Everything this turn is allowed to ground a cause in (brief item (f)).

    Two sources and no third: **what the caller said** — this utterance, the
    verbatim symptom, and the verbatims attached to every answer and ledger
    entry the record holds — and **what was retrieved** for the entry in play.
    A cause that appears in neither was invented between the prompt and the
    reply, which is the one thing `docs/06` §4.5's grounding rule is for.
    """
    parts: list[str] = [state.problem.verbatim_symptom, ctx.utterance]
    parts.extend(answer.verbatim for answer in state.answers.values())
    parts.extend(attempt.verbatim or "" for attempt in state.ledger.attempted)
    parts.extend(hit.chunk.text for hit in hits.hits)
    return " ".join(part for part in parts if part)


def diagnose(
    utterance: str,
    state: DiagnosticState,
    *,
    llm: Any | None = None,
    chunks_path: str | None = None,
    thread_id: str | None = None,
) -> TurnResult:
    """One text-only diagnostic turn: utterance + state → words, state, citations.

    Milestone 3.2: the sequencing lives in `agent/graph.py` as a LangGraph
    `StateGraph` (`docs/06` §8.6, D-13) — the nodes are the step functions
    above, the edges are the §3.2 transition table, and the checkpointer holds
    `DiagnosticState` per turn. The signature and the return value are
    unchanged, because the graph is an implementation of the state machine
    rather than a replacement for it.
    """
    from agent import graph  # deferred: the graph imports these step functions

    return graph.run_turn(
        utterance,
        state,
        llm=llm,
        chunks_path=chunks_path,
        thread_id=thread_id,
    )


def _clarifying_step(decisions: list[policy.CandidateDecision]) -> str | None:
    """The first legal step that is not a handoff — a question, by preference."""
    legal = policy.legal_step_ids(decisions)
    asking = [
        step_id
        for step_id in legal
        if ontology.STEPS[step_id].family in ("FAMILY.ASK", "FAMILY.OBSERVE")
    ]
    if asking:
        return asking[0]
    for step_id in legal:
        if ontology.STEPS[step_id].family != "FAMILY.ESCALATE":
            return step_id
    return None


def _demote_residual_entries(
    shortlist: list[str],
    rule_flags: list[str],
    signals: UtteranceSignals,
    utterance: str = "",
) -> list[str]:
    """Drop `NO_MATCH` / `OUT_OF_SCOPE` while triage still has somewhere to go.

    `docs/06` §5.1 makes "`NO_MATCH` from triage" a *structural* trigger, and
    §3.2 reads the same way: the `TRIAGE` state exits with "taxonomy ID **or**
    `KNOWN-GAP` **or** `NO_MATCH`". Those are alternatives, not a ranking — a
    shortlist holding both `NO_MATCH` and `SD-01` has not finished triaging.

    So the two non-taxonomy outcomes survive only when nothing else is left, or
    when the deterministic detector corroborates them: a hazard keeps
    `NO_MATCH` (§6.1 stops diagnosis outright), and a refund/RMA/warranty
    keyword keeps `OUT_OF_SCOPE` (§5.1 item 1). A classifier that merely
    reached for one is outvoted by the entry it also offered.

    **Milestone 3.3: "the entry it also offered" has to be a real offer.** The
    caller is the one who said what is wrong, so an entry that explains a
    strict minority of what they reported and whose own discriminating
    condition is absent from their words is not somewhere triage can go — it is
    §4.7's "force it into the nearest category". Such an entry does not outvote
    a residual one. On EVAL-28 that is `PWR-02`, which explains one of three
    reported symptoms with no mention of heat anywhere in the utterance. The
    stronger case — *every* candidate is such a force, and some reported
    symptom is outside `docs/02` entirely — is caught upstream in
    `step_triage`, which exits at `NO_MATCH` outright.
    """
    facets = symptoms.reported_facets(utterance)
    routable = [
        e
        for e in shortlist
        if e not in policy.RESIDUAL_ENTRIES
        and not symptoms.is_nearest_category_force(e, utterance, facets)
    ]
    if not routable:
        return shortlist
    corroborated: set[str] = set()
    if signals.hazards:
        corroborated.add("NO_MATCH")
    if "out_of_scope" in rule_flags:
        corroborated.add("OUT_OF_SCOPE")
    return [
        entry
        for entry in shortlist
        if entry not in policy.RESIDUAL_ENTRIES or entry in corroborated
    ]


def _add_cross_checks(
    shortlist: list[str], utterance: str, trace: dict[str, Any]
) -> list[str]:
    """Put a `docs/02` cross-checked entry on the shortlist when the caller's
    own words carry its discriminating condition.

    Milestone 4.4, and it is the second half of "the agent never asks the
    branching question". `docs/02`'s ranked cause lists contain four explicit
    `cross-check` cross-references, and `WIFI-04` cause 5 is one of them:
    "Camera overheating and cycling (cross-check `PWR-02`)". EVAL-23's caller
    volunteers "it's been really hot today", which is `PWR-02`'s discriminating
    condition verbatim — and `docs/03` says "the heat detail is the whole
    scenario and ignoring it is the failure being tested". Without the link the
    heat question is not merely unranked, it is **not in the candidate set at
    all**, because it belongs to `PWR-02` and triage never shortlisted
    `PWR-02`.

    Two guards keep this from widening triage generally:

    * only the four cross-references `docs/02` actually writes down
      (`answers.CROSS_CHECKS`), and
    * only when `agent/symptoms.ENTRY_DISCRIMINATORS` finds the cross-checked
      entry's own **Must ask** condition in the caller's words. A cross-check
      nobody corroborated is a guess, which is `docs/06` §4.7's "force it into
      the nearest category" pointing the other way.

    The entry is inserted behind the primary rather than appended, so the
    `[:4]` cap cannot drop a corroborated cross-check in favour of a
    classifier's fourth guess. It does not displace the primary: triage's own
    route still leads.
    """
    if not shortlist:
        return shortlist
    added: list[str] = []
    for entry in list(shortlist):
        for other in answers.cross_checks_for(entry):
            if other in shortlist or other in added:
                continue
            if symptoms.discriminator_present(other, utterance):
                added.append(other)
    if not added:
        return shortlist
    trace["cross_checks_added"] = list(added)
    return [shortlist[0], *added, *shortlist[1:]]


def _implied_entry(state: DiagnosticState) -> tuple[str, str] | None:
    """The taxonomy entry the caller's latest answer re-categorises to (§3.2).

    `docs/06` §3.2 gives `HYPOTHESISE` the job of re-ranking on new
    information, and `docs/03` EVAL-23 states the strongest form of it
    outright: "Re-categorise to `PWR-02` if the camera is restarting; back to
    `WIFI-04` if not." That is a branch the document dictates, so it is taken
    deterministically rather than offered to the model as a preference — the
    whole point of Milestone 4.4 is that an answer must *decide* something.

    The most recent answer carrying a re-categorisation wins; answers that
    carry none leave the route alone.
    """
    best: tuple[int, str, str] | None = None
    for answer in policy.answers_held(state):
        entry = answers.recategorisation_for(answer.step_id, answer.reading)
        if entry is None:
            continue
        if best is None or answer.turn >= best[0]:
            best = (answer.turn, entry, answer.step_id)
    return (best[1], best[2]) if best is not None else None


def _discriminations(step_id: str) -> list[str]:
    """What `docs/02` says this step's answer tells apart, one line per reading.

    Milestone 4.6. `docs/06` §3.5 ranks candidates by "expected information
    gain across the live causes", and §3.5 itself says Phase 1 delegates that
    ranking to the LLM "which sees the live causes and the retrieved chunks".
    It did not: the option list gave the model a step id, an entry tag and the
    step's own description, and nothing at all about what the step's answer
    would *tell apart*. A ranker cannot rank by information gain without being
    told what the information is.

    `agent/answers.ANSWER_RULES` already holds that, transcribed from each
    entry's `docs/02` *"What would confirm / disconfirm it"* line, because
    Milestone 4.4 needed it to read the answers. The same table, read forwards,
    is the ranking input — so this invents nothing and adds no second source of
    truth. A step with no rule returns an empty list, which is itself honest:
    its outcome is a change, not information.
    """
    rule = answers.ANSWER_RULES.get(step_id)
    if rule is None:
        return []
    return [f"{reading.name}: {reading.meaning}" for reading in rule.readings]


def _cause_id(taxonomy_id: str, hypothesis_text: str) -> str:
    """The identity of one live cause: its entry **and what it claims**.

    Milestone 4.6. The id was `f"{taxonomy_id}:top"`, which made the entry the
    whole identity — every hypothesis the model offered while triage held the
    same entry was treated by `Problem.push_hypothesis` as a re-assertion of
    the one before it, however differently it read. That is the wrong unit for
    the thing the id feeds. `docs/02` cross-cutting trigger 2 escalates when
    "the agent's top hypothesis repeats for a third turn **with no new
    information**" (`docs/06` §3.2 says it the same way), and `turns_held` is
    the only counter behind it. Keyed on the entry alone, the counter did not
    measure repetition at all: it measured how long triage stayed put, so a
    session that reasoned its way through three genuinely different causes
    inside one entry breached a ceiling meant for one that was going in
    circles — and both EVAL-23 and EVAL-27 are four-turn scenarios whose
    `docs/03` outcome line is *no escalation*.

    So the hypothesis text joins the key. `push_hypothesis` still ages a cause
    that is put again — the mechanism is untouched, and a model that keeps
    asserting the same thing still trips trigger 2 on the third turn — but a
    cause that has actually changed is now a different cause, which is what
    the trigger's own words say it is.

    Wording is normalised before it counts: case, punctuation and run-on
    whitespace are not new information. The readable prefix is for the breach
    message (`DiagnosticState.ceiling_breaches` prints the id) and the digest
    carries the identity, so two hypotheses opening with the same five words
    are still two causes. `""` keeps the old `:top` form — `step_select_step`
    does not push an empty hypothesis, so that is a default, not a case.
    """
    words = re.findall(r"[a-z0-9]+", hypothesis_text.lower())
    if not words:
        return f"{taxonomy_id}:top"
    digest = hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()[:8]
    return f"{taxonomy_id}:{'-'.join(words[:5])}:{digest}"


def _entry_for_step(
    step_id: str, options: list[dict[str, Any]], claimed: str, default: str
) -> str:
    """Which shortlisted entry the chosen step belongs to.

    The model's claimed `taxonomy_id` is honoured only when the option list
    agrees that the step sits under it; otherwise the option list wins. The
    return value indexes `per_entry`, so an entry the model invented — a
    plausible-looking id that was never shortlisted — has to resolve to
    `default` rather than a `KeyError`.
    """
    for option in options:
        if option["step_id"] == step_id and option["taxonomy_id"] == claimed:
            return claimed
    for option in options:
        if option["step_id"] == step_id:
            return str(option["taxonomy_id"])
    return default


def _chunk_payload(
    per_entry: dict[str, dict[str, Any]], shortlist: Sequence[str]
) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in shortlist:
        for hit in per_entry[entry]["hits"].hits:
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            payload.append(
                {
                    "chunk_id": hit.chunk_id,
                    "text": hit.chunk.text[:900],
                }
            )
    return payload[:6]


def _retrieval_date(hits: retrieval.RetrievalResult) -> str:
    return hits.hits[0].chunk.retrieval_date if hits.hits else ""


#: What an escalation sounds like to the person it happens to (Milestone 6.5,
#: brief item (e)). Keyed by `policy.EscalationDecision.reason_code`, because
#: the code is the policy decision and the reason is the audit trail for it —
#: and the audit trail is written for whoever reads the handoff payload, not
#: for the caller. Two rules hold every phrase here: it says what happens next,
#: and it states no cause (item (f)). The fallback is deliberately the vaguest
#: of them: a reason code nobody wrote a phrase for must not be able to put the
#: raw reason string back into a reply.
ESCALATION_PHRASE: dict[str, str] = dict(
    (
        (
            "hazard",
            "this needs a person to look at it rather than any more testing "
            "from here",
        ),
        (
            "no_match",
            "what you are describing does not match anything I can work "
            "through with you, and guessing at it would waste your time",
        ),
        (
            "intake_unanswered",
            "I have not been able to narrow down what is wrong from here, so "
            "someone on the team can take it from what we have so far",
        ),
        (
            "out_of_scope",
            "this one is handled by a person on the team rather than by me",
        ),
        (
            "out_of_scope_vehicle_electrical",
            "anything involving the car's own wiring is handled by a person "
            "rather than by me",
        ),
        (
            "no_legal_step",
            "there is nothing further I can safely ask you to try",
        ),
        (
            "undocumented_model",
            "I do not hold the documentation for that camera, so I would only "
            "be guessing",
        ),
        (
            "user_requests_human",
            "you asked for a person, so that is what happens next",
        ),
        (
            "suspected_brick",
            "this one needs someone who can take it further than I can",
        ),
        ("ceiling", "we have gone as far as this is going to go from here"),
    )
)

#: The phrase for a reason code with no entry of its own.
ESCALATION_PHRASE_DEFAULT = "someone else can take this further than I can"


#: One code outranks the code the policy layer led with, for the words only.
#: When the caller asked for a person, that is what the reply should say —
#: `policy.escalation` may well have had a structural trigger first (triage
#: reaching `NO_MATCH` on "can I speak to a real person" is routine), and
#: telling someone who asked for a human that their symptom did not match
#: anything is an answer to a question they did not ask. Nothing about the
#: escalation decision changes here; only which sentence describes it.
PHRASE_PRECEDENCE: tuple[str, ...] = ("user_requests_human",)


def escalation_phrase(decision: policy.EscalationDecision) -> str:
    """The words for one escalation. Never the internal reason string."""
    for code in PHRASE_PRECEDENCE:
        if code in decision.codes:
            return ESCALATION_PHRASE[code]
    return ESCALATION_PHRASE.get(decision.reason_code, ESCALATION_PHRASE_DEFAULT)


def _compose(
    *,
    state: DiagnosticState,
    step_id: str | None,
    hypothesis: str,
    hits: retrieval.RetrievalResult,
    escalation: policy.EscalationDecision,
) -> list[Line]:
    """Build the spoken lines. One action, and never more than one."""
    lines: list[Line] = []

    if state.safety.hazard_stop:
        lines.append(
            Line(
                "Stop there, please — disconnect the camera from power now and "
                "don't use it again until someone has looked at it.",
                kind="safety",
            )
        )
    elif state.safety.driving == "yes":
        lines.append(
            Line(
                "Before anything else — if you're driving, we'll leave anything "
                "hands-on until you've stopped.",
                kind="safety",
            )
        )

    if hypothesis and not state.safety.hazard_stop:
        lines.append(Line(hypothesis, chunk_ids=_grounding(hits, state), kind="prose"))

    if step_id is not None and not state.safety.hazard_stop:
        lines.append(
            Line(
                spoken_form(step_id),
                chunk_ids=_step_grounding(hits, step_id, state.problem.taxonomy_id),
                kind="step",
                fallback=SPOKEN_FALLBACK.get(step_id),
            )
        )

    # The caveat is about a *fix* we cannot confirm. A handoff is not a fix,
    # and saying "treat it as something we're checking rather than a fix I know
    # works" about transferring someone to a human is noise at best.
    escalating_step = (
        step_id is not None and ontology.STEPS[step_id].family == "FAMILY.ESCALATE"
    )
    if not state.speakable_as_fix and step_id is not None and not escalating_step:
        lines.append(
            Line(
                "I should be straight with you: I can't confirm this one against "
                "Rove's own documentation, so treat it as something we're checking "
                "rather than a fix I know works.",
                kind="caveat",
            )
        )

    if escalation.escalate:
        lines.append(
            Line(
                "I'm also going to put you through to someone who can take this "
                "further — " + escalation_phrase(escalation) + ".",
                kind="escalation",
            )
        )
    return lines


def _grounding(hits: retrieval.RetrievalResult, state: DiagnosticState) -> list[str]:
    """Chunk ids that back a hypothesis about this taxonomy entry."""
    entry = state.problem.taxonomy_id
    return [
        h.chunk_id
        for h in hits.hits
        if entry and entry in h.chunk.taxonomy_ids
    ]


def _step_grounding(
    hits: retrieval.RetrievalResult, step_id: str, entry: str | None
) -> list[str]:
    """Chunk ids that back *this step*, not merely this topic.

    A citation attached to a claim it does not support is worse than no
    citation: it turns the audit trail in `clearance.spoken_claims` into
    decoration. So a chunk counts only if it names the step, or is evidence for
    the taxonomy entry the step belongs to.
    """
    return [
        h.chunk_id
        for h in hits.hits
        if step_id in h.chunk.step_ids or (entry and entry in h.chunk.taxonomy_ids)
    ]


def summarise_state(state: DiagnosticState) -> str:
    """The state, rendered for the prompt. Only what the model is allowed to use."""
    lines = [
        f"- device: {state.device.reported_model} "
        f"(confidence {state.device.confidence})",
        f"- driving: {state.safety.driving}",
        f"- footage at stake: {state.safety.footage_at_stake}",
        f"- firmware update believed in progress: {state.firmware_update_in_progress}",
        f"- change event: {state.problem.change_event or 'none stated'}",
    ]
    if state.ledger.attempted:
        lines.append("- already attempted (NEVER propose these again):")
        for attempt in state.ledger.attempted:
            count = f" x{attempt.count}" if attempt.count else ""
            lines.append(
                f"    {attempt.step_id}{count} -> {attempt.outcome} "
                f"({attempt.source}){': ' + attempt.verbatim if attempt.verbatim else ''}"
            )
    else:
        lines.append("- already attempted: nothing stated")
    if state.answers:
        lines.append("- already answered (NEVER ask these again):")
        for answer in policy.answers_held(state):
            lines.append(
                f"    {answer.step_id} -> {answer.reading}"
                f"{': ' + answer.verbatim if answer.verbatim else ''}"
            )
    if state.problem.ruled_out:
        lines.append("- ruled out: " + ", ".join(r.cause_id for r in state.problem.ruled_out))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Harness A adapter (docs/06 §7.3)
# --------------------------------------------------------------------------


def state_from_harness(harness_state: Any) -> DiagnosticState:
    """Build the full `DiagnosticState` from the harness's Phase 0 subset.

    Harness A pre-populates its own smaller record from a scenario's known
    context (`eval/harness.py`). The ledger entries carry across unchanged —
    they are the same `eval.ontology.AttemptedStep` type on both sides, which
    is the reason M4 means the same thing in both places.
    """
    from agent.state import Ledger, Problem, Safety

    state = DiagnosticState(
        session_id=harness_state.session_id,
        safety=Safety(
            driving=harness_state.safety.driving,
            hazard_flags=list(harness_state.safety.hazard_flags),
            footage_at_stake=harness_state.safety.footage_at_stake,
        ),
        problem=Problem(
            verbatim_symptom=harness_state.problem.verbatim_symptom,
            change_event=harness_state.problem.change_event,
        ),
        ledger=Ledger(attempted=list(harness_state.ledger.attempted)),
    )
    state.device.firmware_version = harness_state.device.firmware_version
    return state


class CoreAgent:
    """The Phase 1 agent, behind the Harness A `Agent` protocol.

    `propose` is one `diagnose` call. The harness grades the step, not the
    words, but the words are produced anyway and pass the same output guard —
    a guard that only runs in production is a guard nobody has tested.
    """

    name = "core-text-diagnostic"

    def __init__(self, llm: Any | None = None, *, chunks_path: str | None = None) -> None:
        self.llm = llm if llm is not None else llm_module.BedrockLLM()
        self.chunks_path = chunks_path
        self.turns: list[TurnResult] = []

    def propose(self, harness_state: Any) -> Any:
        from eval.harness import AgentOutput

        state = state_from_harness(harness_state)
        result = diagnose(
            state.problem.verbatim_symptom,
            state,
            llm=self.llm,
            chunks_path=self.chunks_path,
        )
        self.turns.append(result)
        return AgentOutput(
            category=result.category,
            taxonomy_id=result.taxonomy_id,
            step_id=result.step_id,
            escalate=result.escalate,
            # The caller's own words win over `unknown` (model pickup, 6.6);
            # `device_confidence` stays honest about how weak that is.
            device_model=state.device.spoken_model or state.device.reported_model,
            device_confidence=state.device.confidence,
            destructive_gate=result.destructive_gate,
            rationale=result.rationale,
            candidates=[c.as_ontology_candidate() for c in result.candidates],
        )
