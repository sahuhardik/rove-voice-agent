"""Run the scenario suite through the real agent and save every turn.

    ROVE_AGENT_MODEL=ollama:llama3.2 ROVE_AGENT_FALLBACK_MODEL=ollama:llama3.2 python -m eval.run_suite OUT.json [ID ...]
"""
import json
import sys
import time

from eval.scenarios import SCENARIOS
from rove import config
from rove.agent import Agent

out_path, only = sys.argv[1], set(sys.argv[2:])
results = []
for sid, cat, turns, expect in SCENARIOS:
    if only and sid not in only:
        continue
    a = Agent(use_backstop=False)
    rows = []
    for t in turns:
        t0 = time.time()
        try:
            r = a.respond(t)
            row = {"customer": t, "agent": r.say, "action": r.action, "sec": round(time.time() - t0, 1),
                   "safety_notes": r.safety_notes, "case": a.case.to_dict()}
        except Exception as e:
            row = {"customer": t, "agent": None, "error": str(e)[:300], "sec": round(time.time() - t0, 1)}
        rows.append(row)
        print(f"[{sid}] {row['sec']}s  C: {t}\n      A: {row.get('agent') or row.get('error')}", flush=True)
    results.append({"id": sid, "category": cat, "expect": expect, "model": config.AGENT_MODEL, "turns": rows})
    json.dump(results, open(out_path, "w"), indent=1)
print("DONE", len(results))
