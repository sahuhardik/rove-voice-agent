"""Quick screen of candidate agent models on one hard scripted conversation.

    python -m eval.model_screen model1 model2 ...

Per model: did every turn follow the output format, how many safety rewrites /
fallbacks were needed, latency per turn, and the replies (for a human read).
"""
from __future__ import annotations

import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

from rove import agent as agent_mod
from rove import bedrock

SCRIPT = [
    "hi, my rove R2-4K keeps stopping recording after about ten minutes",
    "I already formatted the card in the camera, didn't help",
    "it's a 256 gig sandisk card, it says U1 on it",
    "I had a small accident yesterday too, I need that video",
]


def screen(model: str) -> dict:
    a = agent_mod.Agent(model=model)
    raw_ok, lat, notes, says = 0, [], 0, []

    def llm(system, messages):
        resp, used = bedrock.converse_with_fallback([model], messages, system=system, max_tokens=1200, temperature=0.3)
        return bedrock.text_of(resp)
    a._llm = llm
    try:
        for line in SCRIPT:
            r = a.respond(line)
            raw_ok += int("<say>" in r.raw) if r.raw else 1
            lat.append(r.latency_s)
            notes += len(r.safety_notes)
            says.append(r.say)
    except Exception as e:
        return {"model": model, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    return {"model": model, "format_ok": f"{raw_ok}/{len(SCRIPT)}", "safety_interventions": notes,
            "median_latency_s": round(statistics.median(lat), 1), "footage_flag": a.case.footage_at_risk,
            "case_model": a.case.model, "hypotheses": a.case.hypotheses[:2], "replies": says}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    with ThreadPoolExecutor(8) as pool:
        for res in pool.map(screen, sys.argv[1:]):
            print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
