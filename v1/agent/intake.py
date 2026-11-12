"""The intake agent (Milestone 6.7): collect what the diagnostic core needs.

Until this milestone a vague symptom -- "something is wrong with my dashcam" --
matched no taxonomy entry, triage returned `NO_MATCH`, and the policy escalated
on turn 1: an *under-specified* symptom was treated as a *cannot-help* one.
`docs/06` §5.1's trigger is "`NO_MATCH` from triage", and a caller who has said
nothing yet has not given triage anything to fail on.

This module is the front door that runs before the diagnostic core takes over.
It is a bounded routine inside the `TRIAGE` state of the `docs/06` §3.2 machine,
not a fourteenth state and not a second framework: `core.step_triage` consults
it, the policy decides *whether* it may ask (`policy.intake_can_ask`), and the
same LangGraph nodes carry the turn. The §3.2 transition table is untouched.

**Intent is the router's.** `agent/router.py` classifies the turn (symptom,
meta, out-of-scope, greeting, small talk, human request) and this module is only
consulted for a symptom. Nothing here re-decides scope or intent.

**Three slots, one question per turn, in the order the brief gives them:**

1. *device model* -- `router.has_model_context`: a named model or any ladder
   answer (`docs/06` §3.4's probes). Asked with the router's own question text.
2. *problem area* -- one of the `docs/02` categories, in plain words.
3. *specific symptom* -- one of the category's taxonomy entries, offered in the
   caller's own wording from `docs/02`'s "Symptom (caller)" quotes.

A slot the caller has already filled is never asked for. A reply that fills
nothing is a *miss*; two misses on one slot is the give-up rule (`MISS_LIMIT`).
The model slot gives up by moving on -- the diagnostic core already handles an
unknown model through its clearance filter (`docs/06` §3.4), so a caller who
cannot read the model off the camera can still be helped. The area and symptom
slots cannot be skipped, so giving up on them hands the caller to a person.

**Rules, not a model.** Every verdict is deterministic, for the reason
`agent/router.py` gives: a front door that depends on an LLM call succeeding is
not a front door. Nova Pro still reasons about the *diagnosis* once the filled
state is handed over; Nova Micro still classifies in triage.

State lives in `state.notes["intake"]` as plain JSON so the existing
checkpointer persists it without a new serialisable type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from agent import router
from agent.state import DiagnosticState, ModelSignal, narrowing_for
from eval import baseline, ontology

SLOT_MODEL = "model"
SLOT_AREA = "area"
SLOT_SYMPTOM = "symptom"

ASK = "ask"
HANDOFF = "handoff"
GIVE_UP = "give_up"

#: Two rounds with nothing learned on the same slot and intake stops asking.
MISS_LIMIT = 2

#: Why intake gave up, for the policy: an unanswered slot is "intake_unanswered";
#: the caller saying nothing on offer fits is an honest `no_match`.
REASON_UNANSWERED = "unanswered"
REASON_OTHER = "other"

NOTES_KEY = "intake"


# --------------------------------------------------------------------------
# What the tree offers, in the caller's words
# --------------------------------------------------------------------------

#: Plain words for each `docs/02` category, in the order they are read out.
AREA_LABELS: dict[str, str] = {
    "WIFI": "the Wi-Fi connection to your phone",
    "APP": "the app",
    "REC": "recording",
    "SD": "the SD card",
    "PWR": "power or overheating",
    "VID": "picture or sound quality",
    "FW": "a software update",
}

#: Words that put a caller's reply in a category. Whole-word, and a reply that
#: reaches two categories names none: "the wifi and the sd card" is a question
#: back, not a guess.
AREA_WORDS: dict[str, tuple[str, ...]] = {
    "WIFI": (r"wi-?fi", r"wireless", r"hotspot", r"network", r"connection"),
    "APP": (r"app", r"application", r"pair(?:ing)?"),
    "REC": (r"record(?:s|ing|ed)?", r"loop(?:ing)?"),
    "SD": (r"sd", r"card", r"storage", r"memory", r"format(?:ting)?"),
    "PWR": (
        r"power(?:s|ing)?",
        r"turn(?:s|ing)? on",
        r"battery",
        r"over-?heat(?:s|ing)?",
        r"shuts? (?:down|off)",
        r"ignition",
    ),
    "VID": (
        r"pictures?",
        r"images?",
        r"blurr?y",
        r"night",
        r"audio",
        r"sound",
        r"video quality",
        r"resolution",
    ),
    "FW": (r"updates?", r"firmware", r"upgrad(?:e|ing)"),
}
_AREA_RES: dict[str, re.Pattern[str]] = {
    area: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)
    for area, words in AREA_WORDS.items()
}

#: `docs/02`'s "Symptom (caller)" quotes, in first person and without a
#: question mark so they can sit inside one question. One per taxonomy entry:
#: a test asserts the table stays in step with `ontology.TAXONOMY_CANDIDATES`.
SYMPTOM_LABELS: dict[str, str] = {
    "WIFI-01": "it connects for a second and then my phone goes back to normal internet",
    "WIFI-02": "I don't even see it, there's nothing in my list that looks like the camera",
    "WIFI-03": "it keeps saying wrong password",
    "WIFI-04": "it stays connected for a couple of minutes and then I lose it",
    "WIFI-05": "it connects fine but the video just buffers forever",
    "FW-01": "the update got partway and just sat there",
    "FW-02": "since the update it just shows the logo and nothing happens",
    "FW-03": "it was fine until the update and now something has stopped working",
    "FW-04": "I downloaded the update file but I can't work out how to install it",
    "APP-01": "my phone says it's connected but the app can't find the camera",
    "APP-02": "it used to work and now the app won't open properly since I updated my phone",
    "APP-03": "the app keeps asking me for permissions and never gets past setup",
    "APP-04": "it works with my old phone but a new phone won't pair",
    "REC-01": "there's no footage of an incident I need",
    "REC-02": "it's on but it never starts recording",
    "REC-03": "it deleted my old videos by itself",
    "REC-04": "nothing was recorded while the car was parked",
    "SD-01": "it says card error or insert card even though the card is in",
    "SD-02": "it says memory full and stops instead of recording over old files",
    "SD-03": "I can see the files on the camera but half won't open on my computer",
    "SD-04": "every couple of weeks it stops working and I have to format the card again",
    "PWR-01": "nothing at all happens, no lights and no screen",
    "PWR-02": "it turns itself off on hot days",
    "PWR-03": "it stays on after I turn the car off and drains the battery",
    "PWR-04": "it asks me to set the date and time every time I start the car",
    "VID-01": "the video is okay but I can't read a number plate",
    "VID-02": "I can't see anything at night, or I see reflections of the dashboard",
    "VID-03": "there's no sound on the videos, or the date is wrong",
}

_ORDINALS: dict[str, int] = {
    "first": 1, "1st": 1, "1": 1, "one": 1,
    "second": 2, "2nd": 2, "2": 2, "two": 2,
    "third": 3, "3rd": 3, "3": 3, "three": 3,
    "fourth": 4, "4th": 4, "4": 4, "four": 4,
    "fifth": 5, "5th": 5, "5": 5, "five": 5,
}
_ORDINAL_RE = re.compile(
    r"^\W*(?:the |number |option )?(" + "|".join(_ORDINALS) + r")(?: one)?\W*$", re.I
)
_NONE_OF_THESE_RE = re.compile(
    r"\b(?:none of (?:those|these|them)|something else|neither|not any of|"
    r"nothing like (?:that|those))\b",
    re.I,
)
#: A caller describing a fault, as opposed to naming a topic. "It's the Wi-Fi"
#: names an area; "it won't record" reports a symptom.
_FAILURE_CUE_RE = re.compile(
    r"\b(?:won'?t|will not|cannot|can'?t|doesn'?t|does not|never|stopped|keeps|"
    r"not (?:working|recording|showing|connecting)|nothing)\b",
    re.I,
)
_LENS_WORDS_RE = re.compile(r"\b(?:lens(?:es)?|cameras?|channels?)\b", re.I)
_STOP_STEMS = frozenset(
    "that this with from they them then when what have were does only even just "
    "into over your been very much also some there their about".split()
)

# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeRecord:
    """Where the question tree stands. Frozen: a turn builds the next one."""

    #: A question is outstanding; the next symptom turn is its answer.
    active: bool = False
    #: The slot the last question asked for.
    asked: str | None = None
    area: str | None = None
    entry: str | None = None
    #: The model slot is no longer asked: answered elsewhere or given up on.
    model_deferred: bool = False
    gave_up: bool = False
    give_up_reason: str = ""
    misses: dict[str, int] = field(default_factory=dict)
    #: The entries the last symptom question listed, in order read out.
    offered: tuple[str, ...] = ()


def load(state: DiagnosticState) -> IntakeRecord:
    raw = state.notes.get(NOTES_KEY)
    if not isinstance(raw, dict):
        return IntakeRecord()
    return IntakeRecord(
        active=bool(raw.get("active")),
        asked=raw.get("asked"),
        area=raw.get("area"),
        entry=raw.get("entry"),
        model_deferred=bool(raw.get("model_deferred")),
        gave_up=bool(raw.get("gave_up")),
        give_up_reason=str(raw.get("give_up_reason", "")),
        misses=dict(raw.get("misses") or {}),
        offered=tuple(raw.get("offered") or ()),
    )


def save(state: DiagnosticState, record: IntakeRecord) -> None:
    state.notes[NOTES_KEY] = {
        "active": record.active,
        "asked": record.asked,
        "area": record.area,
        "entry": record.entry,
        "model_deferred": record.model_deferred,
        "gave_up": record.gave_up,
        "give_up_reason": record.give_up_reason,
        "misses": dict(record.misses),
        "offered": list(record.offered),
    }


def is_active(state: DiagnosticState) -> bool:
    return load(state).active


def note_asked(state: DiagnosticState, slot: str) -> None:
    """Record that something outside intake -- the router's context gate -- has
    already put a slot's question, so the caller's next reply is its answer."""
    save(state, replace(load(state), active=True, asked=slot))


@dataclass(frozen=True)
class IntakeDecision:
    action: str
    slot: str | None = None
    reply: str = ""
    entry: str | None = None
    reason: str = ""

    def as_trace(self) -> dict[str, Any]:
        return dict(action=self.action, slot=self.slot, entry=self.entry, reason=self.reason)


# --------------------------------------------------------------------------
# Reading the caller's reply
# --------------------------------------------------------------------------


def area_in(text: str) -> str | None:
    """The one category this reply names, or `None` if it names none or several."""
    hits = [area for area, pattern in _AREA_RES.items() if pattern.search(text or "")]
    return hits[0] if len(hits) == 1 else None


def _stems(text: str) -> set[str]:
    return {
        word[:5]
        for word in re.findall(r"[a-z]+", text.lower())
        if len(word) >= 4 and word not in _STOP_STEMS
    }


def _entries_in(area: str) -> list[str]:
    return sorted(e for e in SYMPTOM_LABELS if ontology.category_of(e) == area)


def _entry_from_overlap(area: str, text: str) -> str | None:
    """The area's one entry whose plain wording the reply shares most words with."""
    reply = _stems(text)
    scored = sorted(
        ((len(reply & _stems(SYMPTOM_LABELS[e])), e) for e in _entries_in(area)),
        reverse=True,
    )
    if not scored or scored[0][0] < 2:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def _entry_in(record: IntakeRecord, area: str, text: str) -> str | None:
    """Resolve a symptom inside a known area: a listed ordinal, the caller's
    own words against the plain wording, or -- for a reply that reports a fault
    -- the rule floor's entry when it agrees with the area."""
    ordinal = _ORDINAL_RE.match(text.strip())
    if ordinal and record.offered:
        index = _ORDINALS[ordinal.group(1).lower()] - 1
        if 0 <= index < len(record.offered):
            return record.offered[index]
    by_words = _entry_from_overlap(area, text)
    if by_words:
        return by_words
    if _FAILURE_CUE_RE.search(text):
        rule = baseline.match_taxonomy(text)
        if rule not in ("NO_MATCH", "OUT_OF_SCOPE") and ontology.category_of(rule) == area:
            return rule
    return None


def _fill(record: IntakeRecord, text: str) -> IntakeRecord:
    """Read the area and symptom slots out of some words, keeping what is held.

    A reply that reports a fault outright can name the area and the symptom in
    one go; a bare topic ("it's the Wi-Fi") only names the area.
    """
    area = record.area or area_in(text)
    entry = record.entry
    if entry is None and area:
        entry = _entry_in(record, area, text)
    if entry is not None:
        area = ontology.category_of(entry)
    return replace(record, area=area, entry=entry)


def _record_ladder_answers(state: DiagnosticState, text: str) -> None:
    """File what a reply to the model question tells the §3.4 ladder.

    `narrowing_for` is the ladder: an answer it cannot act on narrows nothing and
    is not filed, so it cannot raise confidence. The guards stop its substring
    matching reading "phone" as one lens.
    """
    probes: list[tuple[str, bool]] = [
        ("ssid", True),
        ("lens_count", bool(_LENS_WORDS_RE.search(text))),
        ("touch_or_buttons", True),
    ]
    for signal, plausible in probes:
        if not plausible or not narrowing_for(signal, text):
            continue
        if any(s.signal == signal and s.value == text for s in state.device.evidence):
            continue
        state.device.add_signal(
            ModelSignal.from_probe(signal=signal, value=text, turn=state.turn)
        )


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------

_RETRY_MODEL = (
    "No worries. Which Rove camera is it? If you can't read the model, just tell "
    "me how many lenses it has and whether it has a touchscreen or buttons."
)


def _area_question(retry: bool) -> str:
    labels = list(AREA_LABELS.values())
    body = (
        "what is it doing wrong -- is it about "
        + ", ".join(labels[:-1])
        + ", or "
        + labels[-1]
        + "?"
    )
    return ("No problem. Let me ask it another way: " if retry else "Thanks. So ") + body


def _symptom_question(area: str, retry: bool) -> tuple[str, tuple[str, ...]]:
    entries = tuple(_entries_in(area))
    ordinals = ("first", "second", "third", "fourth", "fifth")
    parts = [f"{ordinals[i]}, {SYMPTOM_LABELS[e]}" for i, e in enumerate(entries[:5])]
    lead = "No problem. " if retry else "Thanks. "
    body = "; ".join(parts) + "; or is it something else?"
    return lead + f"Which of these is closest to {AREA_LABELS[area]} -- " + body, entries[:5]


def _next_slot(record: IntakeRecord, model_known: bool) -> str | None:
    if not model_known and not record.model_deferred:
        return SLOT_MODEL
    if record.entry is None:
        return SLOT_AREA if record.area is None else SLOT_SYMPTOM
    return None


# --------------------------------------------------------------------------
# The turn
# --------------------------------------------------------------------------


def consult(state: DiagnosticState, utterance: str) -> IntakeDecision:
    """Read this turn's words into the slots, then ask, hand off or give up.

    The caller has already checked, with `policy.intake_can_ask`, that intake is
    allowed to speak. This function only does the slot work.
    """
    text = utterance or ""
    # Finish fix (Milestone 6.7, revised): a turn with no dashcam mention at
    # all -- no model, no device noun, no failure statement -- and no dashcam
    # context in the session is not describing a camera problem; it said
    # something unclear ("what you needed"). Ask what they need help with,
    # instead of asking which camera (wrong: no camera was mentioned) or
    # escalating (wrong: the turn is unclear, not out-of-scope). The record
    # stays active with no slot asked, so the next turn is read as a fresh
    # symptom and the normal tree starts from there. A turn that is *clearly*
    # out-of-scope never reaches here: policy.intake_can_ask refuses it.
    if (
        not is_active(state)
        and not router.has_dashcam_mention(text)
        and not router.has_model_context(state)
        and not router.has_subject(state)
    ):
        save(state, replace(load(state), active=True, asked=None))
        return IntakeDecision(
            ASK,
            slot=None,
            reply=(
                "I help with Rove dashcams. Can you tell me a bit more about "
                "what you need help with -- which camera it is, and what it "
                "is doing (or not doing)?"
            ),
            reason="no dashcam mention; asking what they need",
        )
    # Pre-fill from what the caller has already said. The opening words may
    # have named the area or the symptom ("it won't turn on") and the reply may
    # be only the model, so the slots are read from the original symptom first
    # and *progress* is measured against that, never against an empty tree.
    record = _fill(load(state), state.problem.verbatim_symptom)
    model_known_before = router.has_model_context(state)
    area_before, entry_before = record.area, record.entry

    if record.asked == SLOT_MODEL:
        _record_ladder_answers(state, text)
    record = _fill(record, text)

    model_known = router.has_model_context(state)
    progressed = (
        model_known != model_known_before
        or record.area != area_before
        or record.entry != entry_before
    )
    misses = dict(record.misses)
    pending = record.asked

    if pending:
        if progressed:
            misses[pending] = 0
            if pending == SLOT_MODEL and not model_known:
                record = replace(record, model_deferred=True)
        else:
            misses[pending] = misses.get(pending, 0) + 1
            if pending != SLOT_MODEL and _NONE_OF_THESE_RE.search(text):
                return _give_up(state, record, misses, REASON_OTHER)
            if misses[pending] >= MISS_LIMIT:
                if pending == SLOT_MODEL:
                    record = replace(record, model_deferred=True)
                else:
                    return _give_up(state, record, misses, REASON_UNANSWERED)
    record = replace(record, misses=misses)

    slot = _next_slot(record, model_known)
    if slot is None:
        save(state, replace(record, active=False, asked=None))
        return IntakeDecision(HANDOFF, entry=record.entry, reason="all required slots filled")

    retry = misses.get(slot, 0) > 0
    offered: tuple[str, ...] = ()
    if slot == SLOT_MODEL:
        reply = _RETRY_MODEL if retry else router.model_id_question(text)
    elif slot == SLOT_AREA:
        reply = _area_question(retry)
    else:
        reply, offered = _symptom_question(record.area or "", retry)
    save(state, replace(record, active=True, asked=slot, offered=offered))
    return IntakeDecision(ASK, slot=slot, reply=reply, reason=f"{slot} slot is empty")


def _give_up(
    state: DiagnosticState, record: IntakeRecord, misses: dict[str, int], reason: str
) -> IntakeDecision:
    save(
        state,
        replace(
            record,
            active=False,
            asked=None,
            gave_up=True,
            give_up_reason=reason,
            misses=misses,
        ),
    )
    return IntakeDecision(GIVE_UP, reason=reason)


__all__ = [
    "AREA_LABELS",
    "AREA_WORDS",
    "ASK",
    "GIVE_UP",
    "HANDOFF",
    "IntakeDecision",
    "IntakeRecord",
    "MISS_LIMIT",
    "SLOT_AREA",
    "SLOT_MODEL",
    "SLOT_SYMPTOM",
    "SYMPTOM_LABELS",
    "area_in",
    "consult",
    "is_active",
    "load",
    "note_asked",
    "save",
]
