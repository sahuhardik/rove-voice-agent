"""Scripted conversations that exposed the old system, run through v2.

    python -m v2.eval.conversations [--out file.json]

The customer lines are fixed (the same ones the old system was given), so the
two systems can be compared line by line.
"""
from __future__ import annotations

import argparse
import json
import sys

from v2.rove.agent import Agent

CONVOS = {
    "A. Stops recording, already reformatted": [
        "hi, my rove R2-4K keeps stopping recording after about ten minutes",
        "I already formatted the card in the camera, didn't help",
        "it's a 256 gig sandisk card, I bought it last week",
        "it says U1 on it I think",
        "no, still the same",
    ],
    "B. Vague start, user doesn't know model": [
        "my dash cam isn't working properly",
        "I don't know which model, it's the rove one my wife bought",
        "it has a screen and I think a second camera for the back",
        "the app won't find the camera",
        "yes the phone is connected to the camera wifi",
    ],
    "C. Mixed symptoms after update": [
        "since I updated the firmware the camera gets really hot and restarts on its own",
        "it's an R3",
        "it happens mostly when it's sunny, parked on the dashboard",
        "yes it comes back on after it cools down",
    ],
    "D. Wi-Fi drops repeatedly": [
        "the wifi keeps disconnecting from my phone every couple of minutes",
        "R2-4K Dual Pro, iPhone 15 with iOS 18",
        "it drops even while I'm watching videos in the app",
        "I'm sitting right next to the car",
    ],
    "E. Needs footage of accident": [
        "I had an accident yesterday and I can't find the video on the card",
        "R2-4K, the newer one with USB-C",
        "I haven't driven since, the card is still in the camera",
    ],
    "F. Simple how-to question": [
        "how do I turn on parking mode on my R2-4K Pro?",
    ],
}


def run(convos: dict[str, list[str]] = CONVOS) -> dict:
    results = {}
    for name, turns in convos.items():
        agent, log = Agent(), []
        print("=" * 78, f"\n{name}\n" + "=" * 78, flush=True)
        for text in turns:
            r = agent.respond(text)
            c = agent.case
            log.append({"user": text, "agent": r.say, "action": r.action, "latency_s": r.latency_s,
                        "model": c.model, "hypotheses": c.hypotheses, "flags": c.flags, "safety_notes": r.safety_notes})
            print(f"USER : {text}\nAGENT: {r.say}\n       [{r.action} | model={c.model} | {r.latency_s}s"
                  f"{' | ' + '; '.join(r.safety_notes) if r.safety_notes else ''}]\n       hypotheses: {c.hypotheses}\n", flush=True)
            if agent.closed:
                break
        results[name] = {"turns": log, "case": agent.case.to_dict()}
    return results


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    res = run()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
