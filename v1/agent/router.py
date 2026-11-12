"""The end-to-end turn router (Milestone 6.5): what kind of turn is this?

`docs/06` 3.2 puts the interrupts above the state diagram -- "evaluated before
every transition" -- and `agent/core.begin_turn` is where they run. This module
is the second thing that runs there, and it answers a question the pipeline
never used to ask out loud:

    before triage: is this a symptom at all, is it about a device we make, and
    do we know enough about the device to diagnose it?

Until Milestone 6.5 the answer was assumed to be yes on every turn, and three
failures followed from that one assumption:

1. **A non-Rove device was diagnosed.** "My Garmin dash cam will not turn on"
   keyword-routed to `PWR-01` and the agent proposed a Rove power step for a
   camera Rove did not build. `docs/06` 3.4 already says where an out-of-line
   device goes -- "routes to `OUT_OF_SCOPE` to a human, with a plain
   explanation" -- but nothing was checking the brand.
2. **A bare symptom was diagnosed before the device was known.** "It won't turn
   on" routed to `PWR-01` on the strength of three words. `docs/06` 3.4's
   discriminator ladder exists precisely so the agent does not do this; it was
   only ever consulted when the classifier volunteered a model signal.
3. **A question about the system was escalated.** "What camera models do you
   support" has an answer sitting in `ingest.metadata.ALL_MODELS`, and the turn
   handed it to a human instead.

**Every rule here is deterministic.** Same reasoning as `core.scan_utterance`:
these are the paths that must still work when the model is unavailable or
wrong, and a scope gate that depends on an LLM call succeeding is not a gate.
The router classifies; it never diagnoses, never escalates and never chooses a
step. What it produces is a `Routing` that the nodes of `docs/06` 3.2 read --
`core.step_triage` honours the device-scope verdict and the short circuit,
`core.step_select_step` refuses to propose a step through one -- so a routing
decision the turn then ignores is impossible by construction rather than by
convention.

**What it deliberately does not touch.** The existing out-of-scope keyword
detector (refunds, RMA, warranty, billing) and the requests-a-human detector
are `core.scan_utterance`'s, they already escalate correctly, and the router
reads their flags rather than re-deciding them: it reports the intent and
leaves the machinery alone. `docs/03` grades those scenarios, and the cheapest
way to break a passing escalation is to re-implement it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from agent import symptoms
from agent.state import UNKNOWN, DiagnosticState
from eval import ontology
from ingest import metadata
from ingest.metadata import ALL_MODELS

# --------------------------------------------------------------------------
# Intents (brief item (a))
# --------------------------------------------------------------------------

#: The caller is describing something their camera is doing.
SYMPTOM = "symptom"
#: A question about this system -- what it covers, what it can do.
META = "meta"
#: Not ours to answer: another manufacturer's device, something that is not a
#: dash cam at all, or one of the commercial requests `01` 4 puts out of scope.
OUT_OF_SCOPE = "out_of_scope"
#: Hello, and nothing else yet.
GREETING = "greeting"
#: Thanks, goodbye, "I don't know", a complaint: a turn with no symptom in it
#: that is not a request for anything out of scope either (Milestone 6.6).
SMALL_TALK = "small_talk"

INTENTS: tuple[str, ...] = (SYMPTOM, META, OUT_OF_SCOPE, GREETING, SMALL_TALK)

#: How each documented model is written when the agent says it out loud, in
#: `ingest.metadata.ALL_MODELS` order. Asserted complete below: a seventh model
#: cannot arrive in the corpus and go unlisted in an answer.
MODEL_DISPLAY_NAMES: dict[str, str] = dict(
    zip(
        ALL_MODELS,
        (
            "R2-4K (mini-USB)",
            "R2-4K (USB-C)",
            "R2-4K PRO",
            "R2-4K DUAL",
            "R2-4K DUAL PRO",
            "R3",
        ),
    )
)

assert len(MODEL_DISPLAY_NAMES) == len(ALL_MODELS) == 6, (
    "every documented model needs a spoken name, or the answer to "
    "which models do you support is quietly incomplete"
)

#: The two residual outcomes of `eval.ontology.CATEGORIES`. Neither is a
#: category the agent can offer to help with.
_RESIDUAL_CATEGORIES: tuple[str, ...] = ("NO_MATCH", "OUT_OF_SCOPE")


def model_display_names() -> list[str]:
    """The six documented models, in corpus order, as the agent says them."""
    return [MODEL_DISPLAY_NAMES[model] for model in ALL_MODELS]


def supported_category_labels() -> list[str]:
    """The `docs/02` categories the agent can actually work on."""
    return [
        label
        for code, label in ontology.CATEGORIES.items()
        if code not in _RESIDUAL_CATEGORIES
    ]


# --------------------------------------------------------------------------
# (b) The device-scope gate
# --------------------------------------------------------------------------

#: Dash cam and action camera brands that are not Rove. `docs/06` 3.4 puts an
#: out-of-line device at `OUT_OF_SCOPE` and a human; this is the list that
#: recognises one. Brands are matched bare -- nobody says "Nextbase" about a
#: Rove -- while the appliance nouns below need a possessive, because "camera"
#: and "phone" are words a Rove caller uses constantly.
FOREIGN_BRANDS: tuple[str, ...] = (
    "garmin",
    "nextbase",
    "blackvue",
    "vantrue",
    "thinkware",
    "viofo",
    "70mai",
    "kenwood",
    "cobra",
    "rexing",
    "roav",
    "apeman",
    "aukey",
    "miofive",
    "redtiger",
    "z-edge",
    "street guardian",
    "gopro",
    "go pro",
    "ring",
    "nest cam",
    "arlo",
    "wyze",
    "blink",
    "tesla",
    # Cameras that are not dash cams. "rear camera" is deliberately absent: the
    # DUAL models have one.
    "reverse camera",
    "reversing camera",
    "backup camera",
    "back-up camera",
    "parking camera",
    "security camera",
    "cctv",
    "webcam",
    "ip camera",
)

#: Subjects that are not a dash cam at all. Matched only behind a possessive or
#: an article, so "the fridge" counts and a passing mention does not.
NON_DASHCAM_SUBJECTS: tuple[str, ...] = (
    "fridge",
    "freezer",
    "washing machine",
    "dishwasher",
    "oven",
    "microwave",
    "kettle",
    "toaster",
    "vacuum",
    "hoover",
    "lawnmower",
    "boiler",
    "thermostat",
    "printer",
    "laptop",
    "desktop",
    "tablet",
    "television",
    "tv",
    "doorbell",
    "baby monitor",
    "drone",
    "treadmill",
    "games console",
)

#: Devices a Rove caller legitimately mentions in a Rove session -- the phone
#: running the app, the computer the footage is opened on -- so they only count
#: as the *subject* (my X won't / is / keeps ...) and only on an opening turn
#: with no camera context. Mid-diagnosis, "my phone won't connect" is an answer.
OPENING_ONLY_SUBJECTS: tuple[str, ...] = (
    "phone",
    "smartphone",
    "mobile",
    "iphone",
    "android",
    "ipad",
    "pc",
    "computer",
    "macbook",
    "router",
    "modem",
    "speaker",
    "headphones",
    "earbuds",
    "smart ?watch",
    "watch",
)
_SUBJECT_VERB = (
    r"(?:won'?t|will not|wo n't|can'?t|cannot|is(?:n'?t| not)?|are(?:n'?t| not)?|"
    r"keeps?|doesn'?t|does not|has|have|stopped|screen|'s)"
)
_OPENING_SUBJECT_RE = re.compile(
    r"\b(?:my|our)\s+(?:[\w'-]+\s+){0,2}?("
    + "|".join(OPENING_ONLY_SUBJECTS)
    + r")\s+"
    + _SUBJECT_VERB
    + r"\b",
    re.I,
)

_FOREIGN_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in FOREIGN_BRANDS) + r")\b", re.I
)
_NON_DASHCAM_RE = re.compile(
    r"\b(?:my|our|the|this|that)\s+(?:[\w'-]+\s+){0,2}?("
    + "|".join(re.escape(s) for s in NON_DASHCAM_SUBJECTS)
    + r")\b",
    re.I,
)
#: A Rove mention anywhere vetoes the brand check. "I swapped my Garmin for a
#: Rove" is a Rove session, and a scope gate that cannot hear that is a gate
#: that hangs up on customers.
_ROVE_RE = re.compile(r"\brove\b", re.I)


def foreign_subject_in(utterance: str, *, opening: bool = False) -> str | None:
    """The non-Rove brand or non-dash-cam subject this utterance is about.

    Returns the matched words, which is what the trace records -- a scope
    refusal has to be explicable in one look, and "out of scope" on its own is
    not an explanation.

    `opening` is True on a first turn with no camera context; only then does a
    phone or computer count as the subject (see `OPENING_ONLY_SUBJECTS`).
    """
    if _ROVE_RE.search(utterance) or named_model_in(utterance) is not None:
        return None
    brand = _FOREIGN_BRAND_RE.search(utterance)
    if brand is not None:
        return brand.group(1).lower()
    # An utterance that also names the camera is a camera session, and the
    # appliance in it is incidental rather than the subject. `docs/03` EVAL-25
    # is the case: "about half my videos won'"'"'t open on the laptop ... and the
    # camera keeps losing the time". The laptop is where the videos were
    # opened, not the thing that is broken, and routing that to a human
    # instead of to SD-03 would be a worse failure than the one this gate
    # exists to prevent.
    if _DEVICE_NOUN_RE.search(utterance):
        return None
    subject = _NON_DASHCAM_RE.search(utterance)
    if subject is not None:
        return subject.group(1).lower()
    if opening:
        subject = _OPENING_SUBJECT_RE.search(utterance)
        if subject is not None:
            return subject.group(1).lower()
    return None


def named_model_in(utterance: str) -> str | None:
    """The Rove model the caller named, as the agent would say it, or `None`.

    `ingest.metadata` is the one place model names are matched against text --
    it is what tags every chunk in the corpus -- so the router asks it rather
    than writing a seventh model regex. `models_spoken_in` is the
    longest-name-wins form: "R2-4K Pro" is the PRO, not the PRO plus both
    R2-4K revisions.

    Both R2-4K revisions answer to the bare name, and `docs/05` is explicit
    that stopping at "an R2-4K" has not finished identifying the device. The
    name is still enough to open the context gate: the caller has told us which
    camera they are holding, and `docs/06` 3.4 keeps the revision question for
    the probe that can actually settle it.
    """
    models = metadata.models_spoken_in(utterance)
    if not models:
        return None
    if tuple(models) == tuple(metadata.R2_4K_EITHER_REVISION):
        return "R2-4K"
    return ", ".join(MODEL_DISPLAY_NAMES[model] for model in models)


# --------------------------------------------------------------------------
# (c) The context gate
# --------------------------------------------------------------------------

#: A statement that something has failed, carrying no further information.
#: These are the whole of a bare symptom: strip them out and an utterance that
#: told us nothing has nothing left.
_GENERIC_FAILURE_PATTERNS: tuple[str, ...] = (
    # "won't connect to Wi-Fi" names the thing that failed to connect and
    # nothing more: which Wi-Fi step is right depends on the camera and the
    # phone, neither of which we know yet (Milestone 6.6).
    r"(?:won'?t|will not|can'?t|cannot|doesn'?t|does not) (?:connect|pair|join)"
    r"(?: to)?(?: (?:the|my|its|any|a))? ?(?:wi-?fi|wifi|wi fi|wireless|network|"
    r"hotspot|phone|app)(?: network)?",
    r"wo n'?t turn on",
    r"won'?t turn on",
    r"will not turn on",
    r"not turning on",
    r"won'?t (?:work|connect|start|pair|record|come on|power on|do anything)",
    r"will not (?:work|connect|start|pair|record|power on|do anything)",
    r"doesn'?t (?:work|do anything)",
    r"does not (?:work|do anything)",
    r"isn'?t working",
    r"is not working",
    r"not working",
    r"stopped working",
    r"(?:is|'s) (?:dead|broken|faulty|playing up|on the blink)",
    r"no power",
    r"needs? (?:some )?help",
    r"having (?:an? )?(?:issue|problem|trouble)s?",
    r"(?:is|'s) (?:not|n'?t) right",
)
_GENERIC_FAILURE_RES = tuple(
    re.compile(p, re.I) for p in _GENERIC_FAILURE_PATTERNS
)

#: Words for the thing itself. Naming the device is not describing a symptom.
_DEVICE_NOUN_RE = re.compile(
    r"\b(?:dash ?cams?|dash ?cameras?|dashcams?|cameras?|cams?|device|unit|"
    r"thing|rove)\b",
    re.I,
)

#: Words that carry no diagnostic content. Deliberately conservative: anything
#: left over after these are removed counts as something the caller told us,
#: and the regression battery asserts that no golden-set utterance survives
#: this filter empty (`eval/test_turn_router.py`).
_FILLER_WORDS: frozenset[str] = frozenset(
    (
        "a", "about", "actually", "again", "all", "also", "am", "an", "and",
        "any", "anymore", "are", "as", "at", "basically", "be", "been", "but",
        "can", "cheers", "could", "did", "do", "does", "else", "even", "ever",
        "for", "from", "get", "got", "had", "has", "have", "he", "hello",
        "help", "her", "here", "hey", "hi", "him", "his", "i", "if", "im",
        "in", "is", "it", "its", "ive", "just", "like", "literally", "me",
        "mine", "more", "my", "n", "no", "not", "now", "of", "off", "ok",
        "okay", "on", "only", "or", "our", "out", "please", "quite", "really",
        "right", "s", "she", "so", "some", "sorry", "still", "suddenly", "t",
        "than", "thanks", "that", "thats", "the", "their", "them", "then",
        "there", "theres", "these", "they", "this", "to", "today", "too",
        "uh", "um", "up", "us", "very", "was", "we", "well", "were", "what",
        "when", "which", "will", "with", "would", "yeah", "yep", "yes", "yet",
        "you", "your",
    )
)


def is_bare_symptom(utterance: str) -> bool:
    """Whether this utterance says only that something is wrong.

    The test is subtractive rather than a keyword list, and that is the whole
    point: remove the failure statement, remove the words for the device
    itself, remove the filler, and ask whether the caller told us anything
    else. "It won't turn on" has nothing left. `docs/03` EVAL-13 -- "It won't
    turn on. I've tried a different cable, borrowed my mate's, same thing" --
    has a cable, a swap and a result, which is three facts triage can use and
    the reason that scenario is diagnosed rather than gated.

    A positive here is not on its own a reason to hold the turn: `route` also
    requires that no model is known and no subject has been established yet.
    """
    if not any(pattern.search(utterance) for pattern in _GENERIC_FAILURE_RES):
        return False
    residue = utterance
    for pattern in _GENERIC_FAILURE_RES:
        residue = pattern.sub(" ", residue)
    residue = _DEVICE_NOUN_RE.sub(" ", residue)
    words = [
        word
        for word in re.findall(r"[a-z0-9']+", residue.lower())
        if word.strip("'") and word.strip("'") not in _FILLER_WORDS
    ]
    return not words



def has_dashcam_mention(utterance: str) -> bool:
    """Whether this utterance mentions a dashcam at all.

    Milestone 6.7 finish fix. The intake agent asks for the model only when
    the caller is talking about a dashcam; without this gate it asks "which
    Rove camera is this?" for a weather question, a joke, or the capital of
    France, because the router's SYMPTOM intent is a catch-all and those reach
    intake as NO_MATCH. A mention is a model name, a device noun (camera /
    dashcam / Rove), or a bare failure statement ("it is broken"). A specific
    symptom with a device noun ("my dashcam won't connect to Wi-Fi") counts,
    because the model slot is what the intake agent still has to fill for it.
    """
    text = utterance or ""
    if named_model_in(text) is not None:
        return True
    if _DEVICE_NOUN_RE.search(text) is not None:
        return True
    return is_bare_symptom(text)

#: A well-formed question or imperative. A question word followed by an
#: auxiliary ("what is", "what do", "can you"), a yes/no question ("is it",
#: "can you"), or an imperative ("tell me", "give me"). A fragment such as
#: "what you needed" has no auxiliary after the question word, so it does
#: not match -- it is unclear, not a question about something else.
_CLEAR_QUESTION_RE = re.compile(
    r"^\s*(?:(?:what|when|where|why|how|who|which|whose|whom)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|will|would|should|have|has|had)\b"
    r"|(?:is|are|was|were|do|does|did|can|could|will|would|should)\b"
    r"|(?:tell|give|show|find|book|get|set|open|play|send|make|write|sing|say|search|look)\b)",
    re.I,
)


def is_clear_out_of_scope(utterance: str) -> bool:
    """Whether this utterance is clearly about something other than a dashcam.

    Milestone 6.7 finish fix. The intake agent asks a clarifying question for
    an *unclear* turn ("what you needed" -- a fragment, no auxiliary after
    the question word) but must not ask "which camera?" for a *clear* question
    about something else ("what is the weather today like?", "tell me a
    joke.", "what is the capital of France?"). A turn is clear out-of-scope
    when it is a well-formed question or imperative, or it names a foreign
    subject (a Samsung TV, a GoPro, a phone). A turn that mentions a dashcam
    is never clear out-of-scope, however it is phrased.
    """
    text = utterance or ""
    if has_dashcam_mention(text):
        return False
    if foreign_subject_in(text, opening=True) is not None:
        return True
    return _CLEAR_QUESTION_RE.search(text) is not None


def has_model_context(state: DiagnosticState) -> bool:
    """Whether the session already knows which camera it is talking about."""
    return (
        state.device.confidence != UNKNOWN
        or state.device.model != "unknown"
        or bool(state.device.evidence)
    )


def has_subject(state: DiagnosticState) -> bool:
    """Whether this session has a subject yet -- anything to continue from.

    A continuing turn always has one: triage has run, or the caller has
    answered something, or a step is in the ledger. The gate is an opening
    move, and asking for the model on turn four of a live diagnosis would be
    the `docs/06` 3.4 deferral failure pointing the other way.
    """
    return bool(
        state.turn > 1
        or state.problem.taxonomy_id
        or state.ledger.attempted
        or state.answers
    )


# --------------------------------------------------------------------------
# (d) Meta questions and greetings, and the words that answer them
# --------------------------------------------------------------------------

_META_MODEL_SUBJECT_RE = re.compile(
    r"\b(?:what|which|how many)\b[^?.!]{0,60}\b(?:models?|cameras?|devices?|"
    r"dash ?cams?|dash ?cameras?|products?)\b",
    re.I,
)
_META_MODEL_VERB_RE = re.compile(
    r"\b(?:support|supported|cover|covered|handle|compatible|work with|"
    r"know about|do you have)\b",
    re.I,
)
_META_CAPABILITY_RES = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bwhat can you (?:help|do)\b",
        r"\bwhat do you do\b",
        r"\bwhat (?:are )?you able to\b",
        r"\bhow can you help\b",
        r"\bwhat (?:sort|kind|type)s? of (?:thing|problem|issue|fault)s?\b",
        r"\bwhat else can you\b",
        r"\bwhat are you for\b",
    )
)
_GREETING_RE = re.compile(
    r"^\s*(?:hi|hiya|hello|hey|yo|good (?:morning|afternoon|evening|day))"
    r"(?:\s+(?:there|all|team|folks|guys|everyone))?"
    r"[\s,!.]*"
    r"(?:how are you(?: doing)?|how'?s it going|are you there)?"
    r"[\s,!.?]*$",
    re.I,
)

#: Turns with no symptom in them that are not a request for anything: thanks,
#: goodbye, "I don't know", "never mind", and a caller venting. Short only --
#: a long sentence that happens to contain "stupid" is a person describing a
#: fault, and the symptom reader gets first look at it (`route`).
_SMALL_TALK_MAX_WORDS = 8
_THANKS_RE = re.compile(
    r"^\W*(?:ok(?:ay)?\W+)?(?:thanks|thank you|thankyou|cheers|ta)"
    r"(?:\s+(?:so much|very much|a lot|again|mate))?\W*$",
    re.I,
)
_GOODBYE_RE = re.compile(
    r"^\W*(?:ok(?:ay)?\W+)?(?:bye|goodbye|good ?bye|bye ?bye|see you|see ya|"
    r"cya|talk (?:to you )?later)\b",
    re.I,
)
_UNSURE_RE = re.compile(
    r"\b(?:i (?:do not|don'?t|dont) know|dunno|no idea|not sure|i'?m not sure)\b",
    re.I,
)
_NEVER_MIND_RE = re.compile(
    r"\b(?:never ?mind|forget it|forget about it|it doesn'?t matter|"
    r"doesn'?t matter)\b",
    re.I,
)
_COMPLAINT_RE = re.compile(
    r"\b(?:hate|stupid|useless|rubbish|garbage|terrible|awful|annoying|worst|"
    r"sucks?|dumb|pathetic|ridiculous|waste of|pointless|hopeless|crap|"
    r"fed up|sick of)\b",
    re.I,
)

SMALL_TALK_REPLIES: dict[str, str] = {
    "thanks": (
        "You're welcome. If the camera plays up again, just tell me what it is "
        "doing and we will work through it."
    ),
    "goodbye": (
        "Goodbye. If the camera gives you any more trouble, come back and tell "
        "me what it is doing."
    ),
    "unsure": (
        "That's fine. Tell me what you can see the camera doing -- a light, a "
        "message on the screen, or nothing at all -- and we will take it from "
        "there."
    ),
    "never_mind": (
        "No problem. If you want to pick it up again, just tell me what the "
        "camera is doing."
    ),
    "complaint": (
        "I'm sorry this has been frustrating. Tell me what the camera is doing "
        "and I will do my best to sort it out -- or say you would like to talk "
        "to a person and I will hand you over."
    ),
}


def small_talk_kind(utterance: str) -> str | None:
    """Which kind of non-symptom turn this is, or `None` if it is none of them."""
    if len(re.findall(r"[\w']+", utterance)) > _SMALL_TALK_MAX_WORDS:
        return None
    for kind, pattern in (
        ("thanks", _THANKS_RE),
        ("goodbye", _GOODBYE_RE),
        ("never_mind", _NEVER_MIND_RE),
        ("unsure", _UNSURE_RE),
        ("complaint", _COMPLAINT_RE),
    ):
        if pattern.search(utterance):
            return kind
    return None


#: `docs/06` 3.4's ladder, as the opening question. Probe 1 is the SSID the
#: camera shows for its own network -- the strongest discriminator there is --
#: and probes 2 and 3 are the fallback for a camera that cannot show it: the
#: lens count splits the single-lens bodies from the DUALs from the R3, and
#: touch-versus-buttons is the R2/R3 answer that never asks the caller to say
#: "R2" or "R3" out loud, which is the token ASR mangles (`docs/01` 2).
MODEL_ID_QUESTION = (
    "Before I send you after the wrong thing, can I check which Rove camera "
    "this is? If it can show you the name of its own Wi-Fi network, read that "
    "out to me -- and if it cannot, how many lenses does it have, and does it "
    "have a touchscreen or buttons?"
)

#: The same opening question when the symptom is a Wi-Fi connection failure: the
#: right first step splits on the phone as well as on the camera.
MODEL_ID_WIFI_QUESTION = (
    "Before I send you after the wrong thing, can I check two things? Which "
    "Rove camera is this -- if it can show you the name of its own Wi-Fi "
    "network, read that out to me, otherwise tell me how many lenses it has "
    "and whether it has a touchscreen or buttons. And is your phone an iPhone "
    "or an Android?"
)
_WIFI_WORDS_RE = re.compile(r"\b(?:wi-?fi|wifi|wi fi|wireless|hotspot)\b", re.I)
_PHONE_FAILURE_RE = re.compile(r"\bconnect(?:ing)? to (?:the |my )?(?:phone|app)\b", re.I)


def model_id_question(utterance: str) -> str:
    """The opening model question for this symptom: the Wi-Fi variant when the
    caller is describing a connection failure, the plain ladder otherwise.

    One place decides it, so the router's context gate and the intake agent
    (`agent/intake.py`) cannot ask two different questions for one symptom.
    """
    if _WIFI_WORDS_RE.search(utterance) or _PHONE_FAILURE_RE.search(utterance):
        return MODEL_ID_WIFI_QUESTION
    return MODEL_ID_QUESTION


def supported_models_answer() -> str:
    """The answer to "which models do you support", from the corpus registry."""
    names = model_display_names()
    return (
        "I cover "
        + str(len(names))
        + " Rove dash cams: "
        + ", ".join(names[:-1])
        + " and "
        + names[-1]
        + ". Tell me which one you have and I can be specific about it."
    )


def capabilities_answer() -> str:
    """The answer to "what can you help me with", from the `docs/02` map."""
    labels = supported_category_labels()
    return (
        "I help with faults on a Rove dash cam -- "
        + ", ".join(labels[:-1])
        + " and "
        + labels[-1]
        + ". Tell me what the camera is doing and we will work through it."
    )


def greeting_answer() -> str:
    """Hello back, and an invitation to say what is wrong."""
    return (
        "Hello -- you have reached Rove dash cam support. Tell me what the "
        "camera is doing and we will work through it together."
    )


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Routing:
    """What kind of turn this is, decided before triage and never after.

    Frozen on purpose. A node may read this; no node may edit it. The one
    field a node is allowed to act on without reading the rest is `reply`:
    when it is set, the turn has its answer already and the diagnostic path
    does not run.
    """

    intent: str = SYMPTOM
    #: The Rove model the caller named in this utterance, if any.
    named_model: str | None = None
    #: The non-Rove brand or non-dash-cam subject that put this out of scope.
    foreign_subject: str | None = None
    #: Which kind of out-of-scope this is, for the trace.
    out_of_scope_kind: str | None = None
    #: True when the context gate is holding the turn for a model ID.
    needs_model_id: bool = False
    #: The words to say, when the router can answer without diagnosing.
    reply: str | None = None
    #: Why, in the router's own words. Internal: never spoken (brief item (e)).
    reason: str = ""

    def as_trace(self) -> dict[str, Any]:
        """The trace row. `reply` is deliberately not in it -- the response
        text is already recorded, and a second copy is a second thing to
        diverge."""
        return dict(
            intent=self.intent,
            named_model=self.named_model,
            foreign_subject=self.foreign_subject,
            out_of_scope_kind=self.out_of_scope_kind,
            needs_model_id=self.needs_model_id,
            reason=self.reason,
        )


def route(
    utterance: str,
    state: DiagnosticState,
    *,
    flags: Sequence[str] = (),
) -> Routing:
    """Classify one turn: intent, device scope, context, answerable question.

    `flags` are `core.scan_utterance`'s rule-derived flags for this utterance.
    They are read, never re-derived: a hazard outranks every gate here (`06`
    6.1 stops diagnosis outright and this must not get in the way of it), and
    the commercial out-of-scope and requests-a-human detectors already escalate
    correctly through `policy.escalation`, so the router reports their intent
    and changes nothing about their handling.

    Order matters and follows the brief: scope first, because diagnosing
    another manufacturer's camera is the worst outcome available; then the
    questions the system can answer itself; then the context gate, which is the
    only verdict that depends on the session record rather than the words.
    """
    text = utterance or ""
    rule_flags = tuple(flags)
    named_model = named_model_in(text)

    if "hazard" in rule_flags:
        return Routing(
            intent=SYMPTOM,
            named_model=named_model,
            reason="hazard reported; the 06 6.1 stop outranks every gate",
        )

    opening = not has_subject(state) and not has_model_context(state)
    foreign = foreign_subject_in(text, opening=opening)
    if foreign is not None:
        kind = (
            "non_rove_device"
            if _FOREIGN_BRAND_RE.search(text)
            else "not_a_dashcam"
        )
        return Routing(
            intent=OUT_OF_SCOPE,
            foreign_subject=foreign,
            out_of_scope_kind=kind,
            reason=f"the utterance is about {foreign}, which is not a Rove dash cam",
        )

    if "out_of_scope" in rule_flags:
        return Routing(
            intent=OUT_OF_SCOPE,
            named_model=named_model,
            out_of_scope_kind="commercial_request",
            reason=(
                "billing, RMA, warranty or returns; the existing 5.1 trigger"
                " handles it"
            ),
        )
    if "requests_human" in rule_flags:
        return Routing(
            intent=OUT_OF_SCOPE,
            named_model=named_model,
            out_of_scope_kind="requests_human",
            reason="the caller asked for a person; handled by the existing 5.1 trigger",
        )

    if not symptoms.reported_facets(text):
        if _META_MODEL_SUBJECT_RE.search(text) and _META_MODEL_VERB_RE.search(text):
            return Routing(
                intent=META,
                named_model=named_model,
                reply=supported_models_answer(),
                reason=(
                    "a question about which models are covered; the"
                    " registry answers it"
                ),
            )
        if any(pattern.search(text) for pattern in _META_CAPABILITY_RES):
            return Routing(
                intent=META,
                named_model=named_model,
                reply=capabilities_answer(),
                reason=(
                    "a question about what this system covers; the"
                    " category map answers it"
                ),
            )
        if _GREETING_RE.match(text):
            return Routing(
                intent=GREETING,
                reply=greeting_answer(),
                reason="a greeting and nothing else yet",
            )
        kind = None if has_subject(state) else small_talk_kind(text)
        if kind is not None:
            return Routing(
                intent=SMALL_TALK,
                reply=SMALL_TALK_REPLIES[kind],
                reason=f"{kind} and no symptom; a person, not a fault",
            )

    if (
        named_model is None
        and not has_model_context(state)
        and not has_subject(state)
        and is_bare_symptom(text)
    ):
        return Routing(
            intent=SYMPTOM,
            needs_model_id=True,
            reply=model_id_question(text),
            reason="a bare symptom with no model and no subject; 3.4 ladder first",
        )

    return Routing(
        intent=SYMPTOM,
        named_model=named_model,
        reason="a symptom on a Rove camera, with enough to triage",
    )


__all__ = [
    "GREETING",
    "INTENTS",
    "META",
    "MODEL_DISPLAY_NAMES",
    "MODEL_ID_QUESTION",
    "OUT_OF_SCOPE",
    "Routing",
    "SMALL_TALK",
    "SYMPTOM",
    "capabilities_answer",
    "foreign_subject_in",
    "greeting_answer",
    "has_model_context",
    "has_dashcam_mention",
    "is_clear_out_of_scope",
    "has_subject",
    "is_bare_symptom",
    "model_display_names",
    "model_id_question",
    "named_model_in",
    "route",
    "small_talk_kind",
    "supported_category_labels",
    "supported_models_answer",
]
