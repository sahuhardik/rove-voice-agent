"""The deterministic safety layer around the diagnostic agent.

Two halves:

* `screen(text)` runs on every user message BEFORE the model. Rules only, so it
  works even if the model is down. Its flags become standing instructions for
  the model and drive the hard overrides (hazard stop, human request).
* `review(reply, case)` runs on every agent reply BEFORE it is spoken. It finds
  things that must never be said; the agent is asked to rewrite, and if it
  still fails a fixed safe reply is used.

Patterns started from the old system's agent/core.py; the footage patterns
were widened because "I had an accident and can't find the video" slipped
through there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HAZARD = [
    (r"\bsmok(e|ing)\b", "smoke"),
    (r"\bburn(ing|t)?\b.{0,20}\bsmell|smell.{0,20}\bburn|\bsmells? (like )?(plastic|burning|electrical)", "burning_smell"),
    (r"\bswell(ing|ed|n)?\b|\bswollen\b|\bbulg(e|ed|ing)\b|\bpuff(ed|y)\b", "swelling"),
    (r"\bmelt(ed|ing)?\b|\bscorch|\bcharred\b|\bheat damage\b|\bcaught fire\b|\bon fire\b|\bflames?\b", "heat_damage"),
    (r"\bexposed wir|\bbare wir|\bspark(s|ing|ed)?\b|\belectric shock\b|\bshocked me\b", "exposed_wiring"),
    (r"\btoo hot to (touch|hold)\b|\bburnt? my (hand|finger)", "too_hot_to_touch"),
]
DRIVING = [
    r"\bi'?m (currently |still )?driving\b", r"\bwhile (i'?m )?driving\b", r"\bon the (motorway|freeway|highway|road) (now|right now)\b",
    r"\bat the wheel\b", r"\bbehind the wheel\b", r"\bdriving (right )?now\b",
]
FOOTAGE = [
    r"\binsurance\b", r"\bpolice\b", r"\bclaim\b", r"\blawyer|\bsolicitor|\bcourt\b", r"\bevidence\b",
    r"\baccident\b", r"\bcrash(ed)?\b", r"\bcollision\b", r"\bincident\b", r"\bhit (my|me|the car|us)\b",
    r"\b(rear|side)[- ]?ended\b", r"\bhit and run\b", r"\bfender bender\b", r"\bvandali[sz]",
    r"\bneed (that|the|this) (video|footage|clip|recording)\b", r"\b(can'?t|cannot|couldn'?t) find (the|my|that) (video|footage|clip|recording)\b",
]
WANTS_HUMAN = [
    r"\b(speak|talk|chat) (to|with) (a |an |some)?(real |actual |live )?(one|person|human|agent|engineer|representative|rep|someone)\b",
    r"\bput me through\b", r"\breal person\b", r"\bhuman (agent|being|please)\b", r"\b(get|transfer) me (to )?(a )?(human|person|someone)\b",
    r"\bcustomer (service|support) (agent|person|rep)\b",
]
OUT_OF_SCOPE = [r"\brefund\b", r"\bmoney back\b", r"\bsend it back\b", r"\breturn (it|the camera)\b", r"\bwarrant(y|ies)\b", r"\brma\b", r"\bbilling\b", r"\binvoice\b", r"\bcharged (me|twice)\b"]
FIRMWARE_IN_PROGRESS = [
    r"\b(doing|running|installing|in the middle of) (the |a )?(firmware )?update\b", r"\bupdate (is )?(stuck|stalled|frozen|hanging)\b",
    r"\bit'?s (still )?updating\b", r"\bhalf ?way\b.{0,30}\bupdate\b", r"\bupdate\b.{0,30}\b(per ?cent|%)",
]
#: Won't boot after an update: possibly bricked; recovery is for a Rove engineer, not a voice agent.
BRICKED = [
    r"\b(stuck|sits|sitting|frozen|hangs|hanging|stays) (on|at) (the )?(rove )?(logo|boot|start ?up|splash)",
    r"\b(won'?t|doesn'?t|does not|will not) (boot|start up|turn on)\b.{0,40}\bupdat",
    r"\bupdat.{0,60}\b(won'?t|doesn'?t|does not|will not) (boot|start|turn on)\b",
    r"\bbricked\b",
]
VEHICLE_ELECTRICAL = [r"\bhard ?wir(e|ed|ing)\b", r"\bfuse (box|tap)\b", r"\bignition wire\b", r"\bauto ?electrician\b", r"\binstaller\b"]
BATTERY_DRAIN = [r"\b(car )?battery (went |was |is |keeps going )?(flat|dead|drained)\b", r"\bdrain(ed|ing|s)? (my|the) (car )?battery\b"]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


@dataclass
class Screen:
    hazards: list[str] = field(default_factory=list)
    driving: bool = False
    footage_at_risk: bool = False
    wants_human: bool = False
    out_of_scope: bool = False
    firmware_in_progress: bool = False
    vehicle_electrical: bool = False
    bricked_after_update: bool = False

    NAMES = ("driving", "footage_at_risk", "wants_human", "out_of_scope", "firmware_in_progress",
             "vehicle_electrical", "bricked_after_update")

    @property
    def flags(self) -> list[str]:
        return (["hazard"] if self.hazards else []) + [n for n in self.NAMES if getattr(self, n)]


#: Situations a voice agent must hand to a person. The agent may ask one useful
#: question for the handoff in the same reply, but the session escalates.
REQUIRED_ESCALATION = {
    "out_of_scope": "refunds, returns, warranty and billing are handled by Rove's support team",
    "vehicle_electrical": "the car's wiring and power need a person to look at",
    "bricked_after_update": "a camera that won't start after an update needs a Rove engineer",
}
ESCALATION_LINE = "I'm going to pass this to a person at Rove who can take it from here, along with everything you've told me."


def screen(text: str) -> Screen:
    t = text.lower()
    return Screen(
        hazards=[name for pat, name in HAZARD if re.search(pat, t)],
        driving=_any(DRIVING, t),
        footage_at_risk=_any(FOOTAGE, t),
        wants_human=_any(WANTS_HUMAN, t),
        out_of_scope=_any(OUT_OF_SCOPE, t),
        firmware_in_progress=_any(FIRMWARE_IN_PROGRESS, t),
        vehicle_electrical=_any(VEHICLE_ELECTRICAL, t) and (_any(BATTERY_DRAIN, t) or "battery" in t),
        bricked_after_update=_any(BRICKED, t) and ("updat" in t or "firmware" in t or "bricked" in t),
    )


HAZARD_REPLY = (
    "Please stop using the camera now. Unplug it from power and don't plug it back in, "
    "and if anything is still hot or smoking, keep away from it. That needs a person from "
    "Rove to look at, so I'm passing you to the support team now."
)
HUMAN_REPLY = "Of course. I'm passing you to a person from Rove's support team now, along with everything we've covered so far."

# --------------------------------------------------------------------------
# Reviewing replies
# --------------------------------------------------------------------------

FIRMWARE_VERSION = re.compile(
    r"(?:firmware|version|build|\bfw\b)[^.\n]{0,25}?\bv?\d+\.\d+(?:\.\d+)?\b|\bv\d+\.\d+(?:\.\d+)?\b|ROVE-R\d[\w-]*\d{6,}", re.I)
#: Instructions (not mentions) that erase footage or settings: an imperative at the
#: start of a sentence, a suggestion ("you should / try / let's ..."), or a menu
#: path that ends on the action ("go to Settings, then Format").
#: Deleting or reinstalling the phone app does not touch the card, so "delete the app" is not an erase.
_NOT_APP = r"(?!\s+(?:and reinstall\s+)?(?:the\s+)?(?:rove\s+)?app\b)"
_ERASE = rf"(?:re-?format|format|wipe|erase|delete{_NOT_APP}|factory[- ]reset|reset|restore (?:the )?defaults?)"
DESTRUCTIVE = re.compile(
    rf"(?:^|[,;:]\s*|\b(?:and|then|now|next|first|please)\s+){_ERASE}\b"
    rf"|\b(?:you (?:can|should|could|need to|will need to|'ll need to|must|might want to)|try|let'?s|go ahead and|we(?:'ll| will| should| need to))\s+(?:\w+\s+){{0,2}}?{_ERASE}"
    rf"|\b(?:select|choose|tap|press|go to|open|pick)\b[^.?!]{{0,50}}\b(?:format|reset|restore default|delete|factory)",
    re.I)
#: Things that write to the card or make the camera record over old files.
WRITES_TO_CARD = re.compile(
    r"\b(take (a |one )?(photo|picture|snapshot)|start (a )?recording|record (a )?(short |test )?(clip|video)|"
    r"drive (it |around )?(for|again)|turn (it|the camera) back on and drive|keep (it )?recording)\b", re.I)
#: Hands-on instructions that must wait while the user is driving.
HANDS_ON = re.compile(r"\b(press|tap|hold (down )?the|open the (menu|app|settings)|remove the|unplug|plug|go (in)?to (the )?(menu|settings)|scroll|select)\b", re.I)
NEGATED = re.compile(r"\b(don'?t|do not|never|avoid|stop|without|before you|instead of|not to)\b", re.I)


#: Brands a reply might recommend or blame. Naming one is a product claim, so it
#: must come from the knowledge packs or the customer.
BRANDS = ["sandisk", "samsung", "lexar", "kingston", "pny", "transcend", "toshiba", "sony", "verbatim",
          "kioxia", "netac", "gigastone", "silicon power", "teamgroup", "adata", "western digital", "nextbase",
          "garmin", "vantrue", "viofo", "blackvue", "thinkware"]
#: A number with a unit is a spec claim.
SPEC = re.compile(r"\b\d+(?:\.\d+)?\s?(?:gb|tb|mb/s|mbps|ghz|mah|v|volts?|amps?|a|°[cf]|fps|p|k|ft|feet|meters?|m|inch(?:es)?|"
                  r"seconds?|minutes?|hours?|days?|%|(?:mega|giga)bytes?(?: per second)?|degrees?(?: fahrenheit| celsius)?)\b"
                  r"|\b[uv]\d{1,2}\b|\bclass ?\d{1,2}\b", re.I)
#: Spoken replies longer than this are hard to follow by ear.
MAX_WORDS = 85


_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}


def words_to_digits(text: str) -> str:
    """"forty-five minutes" -> "45 minutes", so spelled-out specs are checked too."""
    def repl(m: re.Match) -> str:
        tens, ones = m.group(1), m.group(2)
        value = _TENS.get(tens.lower(), 0) if tens else 0
        value += _ONES.get(ones.lower(), 0) if ones else 0
        return str(value)
    tens = "|".join(_TENS)
    ones = "|".join(sorted(_ONES, key=len, reverse=True))
    text = re.sub(rf"\b(?:({tens})(?:[- ]({ones}))?|()({ones}))\b(?=\s+(?:minutes?|seconds?|hours?|days?|percent|feet|meters?|degrees?))",
                  lambda m: repl(m) if m.group(1) else str(_ONES[m.group(4).lower()]), text, flags=re.I)
    return text


def ungrounded(reply: str, grounding: str) -> list[str]:
    """Brands and specs in a reply that appear nowhere in the knowledge or the conversation."""
    from v2.knowledge.factcheck import norm  # same unit normalisation as the offline check

    g = norm(words_to_digits(grounding))
    reply = words_to_digits(reply)
    missing = [b for b in BRANDS if re.search(rf"\b{b}\b", reply, re.I) and b not in g]
    for m in SPEC.finditer(reply):
        tok = norm(m.group(0))
        if not re.search(rf"(?<![\d.]){re.escape(tok)}(?![a-z0-9])", g):
            missing.append(m.group(0))
    return sorted(set(missing))


_RECOMMEND = re.compile(r"\b(recommend|use|get|buy|go with|try|pick|choose|replace (it )?with|switch to)\b", re.I)


def contradicted_brands(reply: str, model_pack: str) -> list[str]:
    """Brands the reply recommends that this model's documentation says NOT to use.

    The original R2-4K manual recommends Samsung; the R2-4K Pro / Dual Pro manuals say
    "NOT SanDisk or Samsung". Mentioning a brand is grounded either way, so the
    direction has to be checked against the pack of the customer's own model.
    """
    bad = []
    for s in _sentences(reply):
        if not _RECOMMEND.search(s) or NEGATED.search(s):
            continue
        for b in BRANDS:
            if re.search(rf"\b{b}\b", s, re.I) and re.search(
                    rf"\b(not|never|avoid|against|don'?t use)\b[^.\n]{{0,60}}\b{b}\b", model_pack, re.I):
                bad.append(b)
    return sorted(set(bad))


@dataclass
class Review:
    problems: list[str] = field(default_factory=list)
    kinds: set[str] = field(default_factory=set)
    ungrounded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, kind: str, problem: str) -> None:
        self.kinds.add(kind)
        self.problems.append(problem)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _instructed(pattern: re.Pattern, text: str) -> list[str]:
    """Sentences that tell the user to do the thing (not 'don't do the thing')."""
    hits = []
    for s in _sentences(text):
        m = pattern.search(s)
        if m and not NEGATED.search(s[: m.start()]) and not s.strip().endswith("?"):
            hits.append(s.strip())
    return hits


def review(reply: str, *, confirmed_destructive: bool, footage_at_risk: bool, driving: bool,
           grounding: str | None = None, model_pack: str = "") -> Review:
    rev = Review()
    if FIRMWARE_VERSION.search(reply):
        rev.add("firmware", "states a firmware version number; refer to 'the latest firmware on Rove's firmware page' instead")
    destructive = _instructed(DESTRUCTIVE, reply)
    if destructive and footage_at_risk:
        rev.add("destructive", "tells the user to erase or reset while footage they need may be on the card; protect the footage first")
    elif destructive and not confirmed_destructive:
        rev.add("destructive", "gives a step that erases footage or settings without the user's confirmation; say what will be lost and ask first")
    if footage_at_risk and _instructed(WRITES_TO_CARD, reply):
        rev.add("footage", "asks the user to record, photograph or drive while the footage they need is on the card; that can overwrite it")
    if driving and _instructed(HANDS_ON, reply):
        rev.add("driving", "gives a hands-on step while the user is driving; ask them to wait until they are parked")
    if len(reply.split()) > MAX_WORDS:
        rev.add("length", f"is {len(reply.split())} words long; say it in under 60 words with one question or step")
    if grounding is not None:
        rev.ungrounded = ungrounded(reply, grounding)
        if rev.ungrounded:
            rev.add("grounding", f"states things the Rove documentation does not support ({', '.join(rev.ungrounded)}); "
                                 "only use brands and specs from the knowledge packs")
    if model_pack:
        against = contradicted_brands(reply, model_pack)
        if against:
            rev.ungrounded += against
            rev.add("grounding", f"recommends {', '.join(against)}, which this camera's manual says not to use")
    return rev


#: Phrased so that "yes" means go ahead: the code treats a plain yes as the confirmation.
#: (An earlier "is there any video you need to keep?" made "no" mean go, and looped.)
SAFE_FALLBACK = (
    "The next step would erase the videos on the card, or reset the camera's settings. "
    "If there's nothing on it you need, is it OK to go ahead?"
)
DRIVING_FALLBACK = "Let's wait until you're parked somewhere safe for that step. Tell me when you've stopped and we'll carry on."


def fallback(reply: str, rev: Review) -> tuple[str, str]:
    """A safe reply when a rewrite still fails. Returns (text, action)."""
    if rev.kinds & {"destructive", "footage"}:
        return SAFE_FALLBACK, "ask_destructive_confirmation"
    if "driving" in rev.kinds:
        return DRIVING_FALLBACK, "continue"
    # Grounding / firmware: drop the offending sentences, keep the rest.
    keep = [s for s in _sentences(reply)
            if not FIRMWARE_VERSION.search(s) and not any(tok.lower() in s.lower() for tok in rev.ungrounded)]
    if "length" in rev.kinds and len(" ".join(keep).split()) > MAX_WORDS:
        # Keep the opening and the closing question: that is the step and what we need back.
        keep = keep[:2] + ([keep[-1]] if len(keep) > 2 and keep[-1].endswith("?") else [])
    text = " ".join(keep).strip()
    return (text or "Let me check that properly rather than guess. Can you tell me a bit more about what you're seeing?"), "continue"
