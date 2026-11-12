"""The diagnostic agent: one model call per turn, wrapped in the safety layer.

    agent = Agent()
    reply = agent.respond("my camera keeps stopping recording")
    reply.say, reply.action, agent.case

Flow of a turn:
  1. safety.screen(user text)  -> hard stops (hazard, wants a human) answer at once
  2. backstop classifier        -> a fast model double-checks the rules, in parallel
  3. the diagnostic model       -> case update + spoken reply + action
  4. safety.review(reply)       -> one rewrite if it breaks a rule, else a safe fallback
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from . import bedrock, config, knowledge, safety
from .case import Case
from .prompt import METHOD, TURN_NOTE

AFFIRMATIVE = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|go ahead|do it|fine|that'?s fine|please do|alright|right|correct)\b", re.I)
PARKED = re.compile(r"\b(i'?m |i have |i've )?(parked|pulled over|stopped (the car|driving)|not driving)\b", re.I)

BACKSTOP_PROMPT = """\
Classify this message from a dash cam owner. Reply with JSON only:
{"hazard": bool, "footage_at_risk": bool, "wants_human": bool, "driving_now": bool}
hazard = smoke, fire, burning smell, melting, swelling, sparks, too hot to touch.
footage_at_risk = they need a recording of an accident/incident/crime/insurance event.
wants_human = they ask for a person/agent/someone else.
driving_now = they are driving at this moment.
Message: """


@dataclass
class Reply:
    say: str
    action: str = "continue"
    case_update: dict[str, Any] = field(default_factory=dict)
    safety_notes: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    raw: str = ""


def parse(raw: str) -> tuple[dict[str, Any], str, str]:
    def tag(name: str) -> str:
        m = re.search(rf"<{name}>(.*?)</{name}>", raw, re.S)
        return m.group(1).strip() if m else ""

    case_txt, say, action = tag("case"), tag("say"), tag("action").lower()
    try:
        update = bedrock.parse_json(case_txt) if case_txt else {}
        update = update if isinstance(update, dict) else {}
    except ValueError:
        update = {}
    if not say:  # model ignored the format: speak its text minus any tags
        say = re.sub(r"<[^>]+>.*?</[^>]+>", "", raw, flags=re.S).strip()
    say = re.sub(r"\s*(?:>|→|->)\s*", ", then ", say)  # menu paths read aloud: "Settings, then WiFi"
    say = re.sub(r"[*_#`\[\]]", "", say)  # nothing unspeakable
    say = re.sub(r"\s+", " ", say).strip()
    if action not in ("continue", "ask_destructive_confirmation", "escalate", "resolved"):
        action = "continue"
    return update, say, action


class Agent:
    def __init__(self, *, model: str | None = None, backstop_model: str | None = None,
                 llm: Callable[..., str] | None = None, use_backstop: bool = True):
        self.model = model or config.AGENT_MODEL
        self.model_used = ""  # which model actually answered the last turn (after any fallback)
        self.backstop_model = backstop_model or config.FAST_MODEL
        self.case = Case()
        self.history: list[dict[str, Any]] = []
        self._llm = llm or self._bedrock_llm
        self.use_backstop = use_backstop and llm is None
        self.closed = False

    # ---- model calls --------------------------------------------------------
    def _bedrock_llm(self, system: str, messages: list[dict[str, Any]]) -> str:
        resp, used = bedrock.converse_with_fallback([self.model, config.AGENT_FALLBACK_MODEL], messages,
                                                    system=system, max_tokens=1200, temperature=0.3)
        self.model_used = used
        return bedrock.text_of(resp)

    def _backstop(self, text: str) -> safety.Screen:
        try:
            resp, _ = bedrock.converse_with_fallback(
                [self.backstop_model, config.FAST_FALLBACK_MODEL],
                [{"role": "user", "content": [{"text": BACKSTOP_PROMPT + json.dumps(text)}]}], max_tokens=200)
            out = bedrock.text_of(resp)
            d = bedrock.parse_json(out)
            return safety.Screen(hazards=["model_flagged"] if d.get("hazard") else [], driving=bool(d.get("driving_now")),
                                 footage_at_risk=bool(d.get("footage_at_risk")), wants_human=bool(d.get("wants_human")))
        except Exception:
            return safety.Screen()  # the rules still stand if the backstop fails

    # ---- the turn -------------------------------------------------------------
    def respond(self, text: str) -> Reply:
        t0 = time.time()
        text = text.strip()
        case = self.case
        case.turns += 1

        # A plain "yes" after we asked about a destructive step is the confirmation.
        if case.awaiting_destructive_confirmation and AFFIRMATIVE.search(text):
            case.confirmed_destructive = True
        case.awaiting_destructive_confirmation = False
        if case.driving and PARKED.search(text):
            case.driving = False
            case.flags = [f for f in case.flags if f != "driving"]

        rules = safety.screen(text)
        with ThreadPoolExecutor(max_workers=2) as pool:
            backstop = pool.submit(self._backstop, text) if self.use_backstop else None
            flags_before = set(case.flags)
            hard = self._apply_screen(rules)
            if hard:
                return self._finish(hard, t0, text)
            reply = self._diagnose(text)
            if backstop is not None:
                extra = backstop.result()
                missed = [f for f in extra.flags if f not in rules.flags and f not in flags_before]
                if missed:
                    # The rules missed something. The backstop is a small model and can be
                    # wrong ("gets hot" is a symptom, "the app won't find it" is not a request
                    # for a person), so it never triggers a hard stop. Protective flags
                    # (footage, driving) are applied; the rest is advice to the agent.
                    self.history = self.history[:-2]
                    self._apply_screen(safety.Screen(footage_at_risk=extra.footage_at_risk, driving=extra.driving))
                    note = f"[A safety check also flagged: {', '.join(missed)}."
                    if "hazard" in missed:
                        note += " If there is any sign of physical damage (smoke, melting, swelling, burning smell), stop and escalate; ask if unsure."
                    if "wants_human" in missed:
                        note += " If the customer is asking for a person, escalate; otherwise carry on."
                    reply = self._diagnose(text, extra_note=note + "]")
                    reply.safety_notes.append(f"backstop flagged {missed}")
        return self._finish(reply, t0)

    def _apply_screen(self, s: safety.Screen) -> Reply | None:
        case = self.case
        case.flags = sorted(set(case.flags) | set(s.flags))
        case.footage_at_risk |= s.footage_at_risk
        case.driving |= s.driving
        if s.hazards:
            case.status = "escalated"
            return Reply(safety.HAZARD_REPLY, action="escalate", safety_notes=[f"hazard: {s.hazards}"])
        if s.wants_human:
            case.status = "escalated"
            return Reply(safety.HUMAN_REPLY, action="escalate", safety_notes=["customer asked for a person"])
        return None

    def _diagnose(self, text: str, extra_note: str = "") -> Reply:
        case = self.case
        # A model named in this message is loaded now, before the model reasons about it.
        named = knowledge.model_from_text(text)
        if named and case.model == "unknown":
            case.model, case.model_confidence = named, "confirmed"
        context = knowledge.context_for(case.model)  # the full packs: what replies are checked against
        said = " ".join(m["content"][0]["text"] for m in self.history if m["role"] == "user") + " " + text
        shown = knowledge.compact_context(case.model, said) if config.COMPACT_CONTEXT else context
        system = METHOD.replace("{catalogue}", knowledge.catalogue()).replace("{knowledge}", shown)
        # What a reply may draw facts from: the packs read this turn plus everything the customer said.
        grounding = context + "\n" + said
        snapshot = {k: v for k, v in case.to_dict().items()
                    if k not in ("awaiting_destructive_confirmation", "turns") and v not in ("", [], False)}
        note = TURN_NOTE.format(case=json.dumps(snapshot), flags=", ".join(case.flags) or "none",
                                extra=extra_note + ("\n[The customer has confirmed the destructive step.]" if case.confirmed_destructive else ""))
        user_msg = {"role": "user", "content": [{"text": f"{text}\n\n{note}"}]}
        messages = self.history + [user_msg]

        raw = self._llm(system, messages)
        update, say, action = parse(raw)
        notes: list[str] = []

        def check(s: str) -> safety.Review:
            pack = knowledge.pack(case.model) if case.model in knowledge.model_ids() else ""
            return safety.review(s, confirmed_destructive=case.confirmed_destructive,
                                 footage_at_risk=case.footage_at_risk, driving=case.driving, grounding=grounding,
                                 model_pack=pack)

        review = check(say)
        if not review.ok:
            notes.append(f"rewrite: {review.problems}")
            fix = {"role": "user", "content": [{"text": (
                f"{text}\n\n{note}\n[Your previous draft was blocked because it {'; and it '.join(review.problems)}. "
                f"Write a new reply that follows the rules.]")}]}
            raw = self._llm(system, self.history + [fix])
            update2, say2, action2 = parse(raw)
            review2 = check(say2)
            if review2.ok:
                update, say, action = update2, say2, action2
            else:
                notes.append(f"fallback: {review2.problems}")
                say, action = safety.fallback(say2, review2)
                update = update2 or update

        case.apply(update, knowledge.model_ids())
        required = [f for f in case.flags if f in safety.REQUIRED_ESCALATION]
        if required and action != "escalate":
            # Code, not the model, decides these hand-offs. The model's reply is kept
            # (it usually asks the one question that makes the handoff useful).
            notes.append(f"escalation enforced: {required}")
            if "pass" not in say.lower() and "person" not in say.lower():
                say = f"{say} {safety.ESCALATION_LINE}".strip()
            action = "escalate"
        if action == "ask_destructive_confirmation":
            case.awaiting_destructive_confirmation = True
        elif case.confirmed_destructive and action != "ask_destructive_confirmation":
            case.confirmed_destructive = False  # one confirmation covers one step
        if action == "escalate":
            case.status = "escalated"
        elif action == "resolved":
            case.status = "resolved"

        # History keeps the plain conversation; the case file travels in each turn's note.
        self.history += [{"role": "user", "content": [{"text": text}]},
                         {"role": "assistant", "content": [{"text": say}]}]
        return Reply(say=say, action=action, case_update=update, safety_notes=notes, raw=raw)

    def _finish(self, reply: Reply, t0: float, text: str = "") -> Reply:
        reply.latency_s = round(time.time() - t0, 2)
        if reply.action == "escalate":
            self.closed = True
        if not reply.raw and text:
            # A hard-stop reply never reached the model; record the exchange anyway.
            self.history += [{"role": "user", "content": [{"text": text}]},
                             {"role": "assistant", "content": [{"text": reply.say}]}]
        return reply

    def greeting(self) -> str:
        return "Hi, this is Rove support. Tell me what's going on with your dash cam, and which model it is if you know."
