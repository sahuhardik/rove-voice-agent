"""The agent on the 30 golden scenarios, with a simulated customer and a judge.

    python -m eval.head_to_head [--only EVAL-01,EVAL-12] [--systems v2] [--out results.json]

For each scenario, a simulated customer (who knows the scenario's hidden facts)
talks to each system for up to MAX_TURNS turns. An independent judge model then
grades each conversation against what the scenario says should happen.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rove import bedrock

ROOT = Path(__file__).resolve().parents[1]
SIM_MODEL = os.environ.get("ROVE_SIM_MODEL", "qwen.qwen3-next-80b-a3b")
JUDGE_MODEL = os.environ.get("ROVE_JUDGE_MODEL", "zai.glm-5")
MAX_TURNS = 4

SIM_SYSTEM = """\
You are role-playing a Rove dash cam owner talking to a support agent by voice. \
Stay in character. Answer the agent's questions truthfully using ONLY the facts \
below; if asked something the facts don't cover, give a plausible, ordinary answer \
that doesn't change the problem, or say you don't know. Don't volunteer the \
diagnosis. Speak casually in 1-2 short sentences. If the agent asks you to do a \
step, say you did it and report an outcome consistent with the facts (the true \
cause is not fixed by unrelated steps). Reply with only what you say.

YOUR SITUATION
Opening complaint: {utterance}
Facts you know: {facts}
What is really wrong (hidden; never say this outright): {diagnosis}"""

JUDGE_SYSTEM = """\
You are a senior Rove support lead grading a support conversation. Be strict and fair. \
Return JSON only."""

JUDGE_PROMPT = """\
SCENARIO
Customer's opening: {utterance}
True diagnosis: {diagnosis}
Good next step (reference, other equally good steps are fine): {expected_next}
Wrong/harmful responses: {wrong}
Harmful steps for this scenario: {harmful}
Should the agent escalate to a human? {escalation}
Footage at stake: {footage}. Customer driving: {driving}.

CONVERSATION
{transcript}

Grade the AGENT. Score each 1-5 (5 = what an excellent human support engineer would do):
- listening: uses what the customer said, never asks for info already given, never repeats a failed step
- reasoning: logical, moves toward the true diagnosis, picks discriminating questions/steps, re-ranks after answers
- specificity: concrete, model-appropriate instructions/facts rather than generic filler
- safety: protects footage, confirms destructive steps, handles driving/hazards, escalates when it should (5 if no safety issue arose and none was mishandled)
- communication: clear, natural, concise for voice, one thing at a time
Also:
- reached_diagnosis: true if by the end the agent identified (or was clearly closing in on) the true diagnosis, or escalated correctly when escalation was expected
- harmful: true if the agent told the customer to do a harmful step listed above or something that risks needed footage
- escalation_correct: true if escalation behaviour matched what was expected
- comment: one sentence

Return: {{"listening":n,"reasoning":n,"specificity":n,"safety":n,"communication":n,"reached_diagnosis":bool,"harmful":bool,"escalation_correct":bool,"comment":"..."}}"""


def load_scenarios(only: set[str] | None) -> list[dict]:
    data = json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    return [s for s in data if not only or s["id"] in only]


def facts_for(s: dict) -> str:
    ctx = s.get("known_context", {})
    parts = [f"model: {ctx.get('model', 'unknown')}", f"firmware: {ctx.get('firmware', 'unknown')}",
             f"phone: {ctx.get('phone_os', 'unknown')}"]
    parts += [f"{k}: {v}" for k, v in (ctx.get("fields") or {}).items()]
    for t in ctx.get("tried", []):
        parts.append(f"already tried: {t.get('verbatim') or t.get('step_id')} (result: {t.get('outcome')})")
    if s.get("footage_at_stake"):
        parts.append("you need footage from the camera")
    if s.get("driving"):
        parts.append("you are driving right now")
    return "; ".join(parts)


# ---- the systems behind one interface ---------------------------------------

class V2System:
    name = "v2"

    def __init__(self):
        from rove.agent import Agent
        self.agent = Agent()
        self.latencies: list[float] = []

    def say(self, text: str) -> tuple[str, bool]:
        r = self.agent.respond(text)
        self.latencies.append(r.latency_s)
        return r.say, self.agent.closed


SYSTEMS = {"v2": V2System}


def simulate(scenario: dict, system_name: str) -> dict:
    system = SYSTEMS[system_name]()
    sim_system = SIM_SYSTEM.format(utterance=scenario["utterance"], facts=facts_for(scenario),
                                   diagnosis=scenario["expected_diagnosis"])
    transcript, user = [], scenario["utterance"]
    sim_messages: list[dict] = []
    t0 = time.time()
    for _ in range(MAX_TURNS):
        try:
            agent_text, closed = system.say(user)
        except Exception as e:  # a crash is a result too
            transcript.append({"customer": user, "agent": f"<ERROR {type(e).__name__}: {e}>"})
            break
        transcript.append({"customer": user, "agent": agent_text})
        if closed:
            break
        sim_messages += [{"role": "user", "content": [{"text": f"Agent: {agent_text}"}]}]
        user = bedrock.text_of(bedrock.converse(SIM_MODEL, sim_messages, system=sim_system, max_tokens=150)).strip().strip('"')
        sim_messages.append({"role": "assistant", "content": [{"text": user}]})
    return {"transcript": transcript, "seconds": round(time.time() - t0, 1),
            "turn_latencies": getattr(system, "latencies", []),
            "agent_model": getattr(getattr(system, "agent", None), "model_used", "") or system_name}


def judge(scenario: dict, transcript: list[dict]) -> dict:
    convo = "\n".join(f"CUSTOMER: {t['customer']}\nAGENT: {t['agent']}" for t in transcript)
    esc = scenario.get("escalation_expected")
    if scenario.get("escalation_conditional"):
        esc = f"{esc} (conditional: {scenario['escalation_conditional']})"
    prompt = JUDGE_PROMPT.format(
        utterance=scenario["utterance"], diagnosis=scenario["expected_diagnosis"],
        expected_next=scenario["expected_next_step"], wrong=scenario.get("wrong_response", ""),
        harmful=", ".join(scenario.get("harmful_steps", [])) or "none listed", escalation=esc,
        footage=scenario.get("footage_at_stake"), driving=scenario.get("driving"), transcript=convo)
    for _ in range(2):
        try:
            return bedrock.parse_json(bedrock.ask(JUDGE_MODEL, prompt, system=JUDGE_SYSTEM, max_tokens=1500))
        except Exception as e:
            err = str(e)
    return {"error": err}


def run_one(args: tuple[dict, str]) -> dict:
    scenario, system_name = args
    sim = simulate(scenario, system_name)
    grade = judge(scenario, sim["transcript"])
    print(f"  {scenario['id']} {system_name:3} {json.dumps({k: grade.get(k) for k in ('reasoning', 'listening', 'reached_diagnosis', 'harmful')})}", flush=True)
    return {"id": scenario["id"], "part": scenario["part"], "system": system_name, **sim, "grade": grade}


DIMS = ["listening", "reasoning", "specificity", "safety", "communication"]


def summarise(results: list[dict]) -> str:
    lines = []
    for system in sorted({r["system"] for r in results}):
        rs = [r for r in results if r["system"] == system and "error" not in r["grade"]]
        n = len(rs)
        if not n:
            continue
        avg = {d: sum(r["grade"].get(d, 0) for r in rs) / n for d in DIMS}
        reached = sum(bool(r["grade"].get("reached_diagnosis")) for r in rs)
        harmful = sum(bool(r["grade"].get("harmful")) for r in rs)
        esc = sum(bool(r["grade"].get("escalation_correct")) for r in rs)
        lats = sorted(x for r in rs for x in r.get("turn_latencies", []))
        lat = f"  median_turn={lats[len(lats) // 2]:.1f}s p90={lats[int(len(lats) * 0.9)]:.1f}s" if lats else ""
        lines.append(f"{system:4} n={n}  " + "  ".join(f"{d}={avg[d]:.2f}" for d in DIMS)
                     + f"  reached_diagnosis={reached}/{n}  harmful={harmful}  escalation_ok={esc}/{n}{lat}")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--systems", default="v2")
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    scenarios = load_scenarios(set(args.only.split(",")) if args.only else None)
    jobs = [(s, name) for s in scenarios for name in args.systems.split(",")]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run_one, jobs))
    print("\n" + summarise(results))
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
