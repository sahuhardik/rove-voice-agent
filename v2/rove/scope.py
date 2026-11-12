"""Scope gate: the agent only talks about troubleshooting the customer's Rove dash cam.

This runs in code, before the model sees anything, so a small or jailbroken model can never be talked into small
talk, jokes, trivia, brand comparisons, or revealing its instructions. Off-topic messages get a fixed redirect and
never reach the model or the conversation history.

Decision order (see `check`):
  1. Prompt-injection / "who are you / what are you doing" style probes  -> blocked
  2. Explicitly off-topic subjects (jokes, weather, trivia, competitors, car repair, evading the law) -> blocked
  3. Dash-cam vocabulary present                                           -> allowed
  4. Mid-diagnosis short reply ("yes", "it's a SanDisk", "I don't know")   -> allowed
  5. A bare greeting                                                       -> allowed (the agent asks what is wrong)
  6. Anything else                                                         -> blocked
"""
from __future__ import annotations

import re
from dataclasses import dataclass

I = re.IGNORECASE


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), I)


INJECTION = _rx(
    r"\bignore (all |any |your |the |previous |prior |above )+(instructions|rules|prompt|guidelines)",
    r"\b(system|hidden|initial|original) (prompt|instructions?|message)\b",
    r"\b(your|the) (instructions|rules|guidelines|prompt|programming)\b",
    r"\b(reveal|show|print|repeat|tell me) (me )?(your|the) (prompt|instructions|rules)",
    r"\b(pretend|act|behave|roleplay|role-play) (like |as |that )?(you('| a)?re|you are|a |an |if)",
    r"\byou are now\b", r"\bdeveloper mode\b", r"\bjailbreak\b", r"\bdo anything now\b", r"\bDAN\b",
    r"\bforget (everything|all|your)\b", r"\bnew (instructions|rules|persona)\b",
)

#: Questions about the assistant itself, and chit-chat. Not diagnostic, so not answered.
ABOUT_THE_BOT = _rx(
    r"\bwho (are|r) you\b", r"\bwhat (are|r) you( doing| up to)?\b", r"\bwhat('s| is) your (name|job|purpose)\b",
    r"\bwhat do you do\b", r"\bwhat can you (do|help)\b", r"\bare you (an? )?(ai|bot|robot|human|real|person|chatgpt|gpt|claude)\b",
    r"\bwho (made|built|created|trained|programmed) you\b", r"\bwhich (model|llm|ai) are you\b", r"\bwhat model (are|r) you\b",
    r"\btell me about yourself\b", r"\bhow are you\b", r"\bhow('s| is) it going\b", r"\bwhat'?s up\b",
    r"\bwhat are you doing\b", r"\bwhat'?re you doing\b", r"\bdo you (like|love|hate|feel|think|dream|sleep|eat)\b",
    r"\bare you (there|alive|listening|ok|okay)\b",
)

#: Always blocked, even if a dash-cam word is also present.
OFF_TOPIC = _rx(
    r"\b(joke|jokes|riddle|poem|poetry|song|lyrics|story|haiku|rap)\b",
    r"\bcapital of\b", r"\bwho (won|is the (president|ceo|richest))\b", r"\btranslate\b", r"\bhomework\b",
    r"\bwhat('s| is) \d+\s*[\+\-\*x/]\s*\d+",
    r"\bbetter than\b", r"\bwhich (dash ?cam|camera|brand) (is|should)\b", r"\bbest dash ?cam\b", r"\brecommend (a|another|an)\b",
    r"\bcheck engine\b", r"\bengine (light|noise|problem)\b", r"\b(oil change|tyre|tire pressure|brake pads?|transmission|clutch|gearbox)\b",
    r"\bmy car (won'?t|doesn'?t) start\b",
    r"\b(speeding|speed) (ticket|camera)s?\b", r"\bget away with\b", r"\b(avoid|dodge|beat) (a |the )?(ticket|fine|police|cops)\b",
    r"\bcaught (speeding|driving)\b", r"\b(delete|destroy|hide|erase) (the )?evidence\b",
    r"\b(write|draft|compose|generate) (me )?(a |an |some )?(email|essay|letter|code|poem|story|script)\b",
    r"\b(girlfriend|boyfriend|dating|love me|marry)\b", r"\bsex\w*\b",
)

#: Subjects that are off-topic on their own, but may appear inside a real dash-cam complaint
#: ("it restarts in hot weather", "I switched from a Garmin").
SOFT_OFF_TOPIC = _rx(
    r"\b(weather|forecast|temperature outside|rain(ing)?|snow(ing)?)\b",
    r"\b(news|headline|election|president|prime minister|politic\w*|stock|stocks|bitcoin|crypto|cricket|football|soccer|nba|ipl|score)\b",
    r"\b(recipe|cook|restaurant|movie|netflix|music|game|games)\b",
    r"\b(garmin|nextbase|vantrue|viofo|thinkware|blackvue|70mai|xiaomi|gopro|cobra|rexing|kenwood)\b",
)

#: Words that show the customer is talking about this product.
CORE = _rx(r"\bdash ?-?cams?\b", r"\bcamera\b", r"\brove\b", r"\br\s?3\b", r"\br\s?2\b", r"\bcards?\b", r"\brecord\w*\b", r"\bfootage\b")

CAMERA = _rx(
    r"\bdash ?-?cams?\b", r"\bcamera\b", r"\bcam\b", r"\brove\b", r"\br\s?3\b", r"\br\s?2\b", r"\b4k\b", r"\bdual\b", r"\bpro\b", r"\busb[- ]?c\b",
    r"\b(sd|micro ?sd|memory|storage|flash)\b", r"\bcards?\b", r"\b(record\w*|footage|video|clips?|files?|loop|overwrit\w*)\b",
    r"\b(screen|display|lcd|touch\w*|button|menu|settings?|brightness|volume|sound|audio|mic\w*|speaker|voice prompts?)\b",
    r"\b(power\w*|batter\w*|charg\w*|usb|cable|cord|plug\w*|socket|hard ?wir\w*|fuse|supercap\w*|ignition|parking( mode)?)\b",
    r"\b(wi-?fi|wireless|hotspot|bluetooth|app|phone|iphone|android|ios|pair\w*|connect\w*|password|network)\b",
    r"\b(firmware|update\w*|upgrade|version|reset|restart\w*|reboot\w*|freez\w*|frozen|crash\w*|hang\w*|stuck|boot\w*|logo)\b",
    r"\b(beep\w*|error|warning|alert|notification|light|led|flash\w*|blink\w*|ir|night|dark|blur\w*|fuzzy|lens|focus|glare|film|stripes?)\b",
    r"\b(mount\w*|suction|adhesive|windshield|windscreen|dashboard|rear|front|interior|cabin|channel|angle|view)\b",
    r"\b(date|time ?zone|timestamp|gps|speed stamp|g-?sensor|motion|collision|lock\w*|format\w*|class ?10|u1|u3|gb|gigabytes?)\b",
    r"\b(support|contact|email|warranty|refund|manual)\b",
    r"\b(won'?t|doesn'?t|isn'?t|not|stopped|keeps?|can'?t|cannot|no) (work\w*|turn\w*|record\w*|start\w*|connect\w*|show\w*|power\w*|save\w*|read\w*|detect\w*|charg\w*)\b",
)

GREETING = re.compile(r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|namaste|yo)\b[\s,.!?]*(there|support|rove)?[\s,.!?]*$", I)
#: A short message that opens a new question or request is not an answer to the agent's question,
#: unless it is a request to clarify what the agent just said.
NEW_REQUEST = re.compile(r"^\s*(how|what|who|why|when|where|which|can you|could you|would you|tell me|write|give me|explain|do you know)\b", I)
CLARIFY = _rx(r"what do you mean", r"what does that mean", r"repeat", r"say that again", r"pardon", r"sorry",
              r"how (do|can) i (do|find|get to|open|check|turn|press|tell) (that|it|this)", r"where is (that|it|this)",
              r"what (is|are) (that|it|those|the (menu|button|app))", r"which (one|button|menu)")
#: Answers to the agent's own questions are fine even without dash-cam words.
SHORT_REPLY_WORDS = 16


@dataclass
class Verdict:
    ok: bool
    reason: str = ""  # "", "injection", "about_the_bot", "off_topic", "no_camera_topic"


def check(text: str, *, mid_diagnosis: bool) -> Verdict:
    t = text.strip()
    if not t:
        return Verdict(False, "empty")
    if INJECTION.search(t):
        return Verdict(False, "injection")
    if ABOUT_THE_BOT.search(t):
        return Verdict(False, "about_the_bot")
    if OFF_TOPIC.search(t):
        return Verdict(False, "off_topic")
    if SOFT_OFF_TOPIC.search(t) and not CORE.search(t):
        return Verdict(False, "off_topic")
    if CAMERA.search(t):
        return Verdict(True)
    if GREETING.match(t):
        return Verdict(True)
    if mid_diagnosis and len(t.split()) <= SHORT_REPLY_WORDS:
        if NEW_REQUEST.match(t) and not CLARIFY.search(t):
            return Verdict(False, "off_topic")
        return Verdict(True)
    return Verdict(False, "no_camera_topic")


SUPPORT = "help@rovedashcam.com"


def redirect(reason: str, strikes: int, model_known: bool) -> str:
    """A fixed spoken reply. Never answers the question that was asked."""
    if reason == "injection":
        return "I can't help with that. I can only help you troubleshoot your Rove dash cam. What is it doing?"
    ask = "What is your dash cam doing?" if model_known else "Which model do you have, and what is it doing?"
    if strikes <= 1:
        return f"I can only help with troubleshooting your Rove dash cam. {ask}"
    if strikes == 2:
        return f"I'm only able to help with your dash cam. {ask}"
    return (f"I can only help with dash cam troubleshooting here. For anything else, please contact Rove support at "
            f"{SUPPORT}. {ask}")
