"""The 25-probe accuracy battery, as code (Milestone 6.7).

    .venv/bin/python -m eval.probe_battery

The battery was quoted in `eval/README.md` for Milestones 6.5 and 6.6 but never
checked in: it was a one-off script. This is a reconstruction of it from the
probe groups those sections report -- out-of-scope 10, negative/non-symptom 9,
context-first 3, meta-questions 3 -- using the utterances `eval/test_turn_router.py`
already carries. It is **not** the original script, so its score is comparable
with the 6.6 figure in spirit and not byte for byte.

Each probe runs through `eval.harness.build_agent("core").propose` with the LLM
stubbed out (`NullLLM`), so what is scored is the deterministic floor. The reply
text is read from `agent.turns[-1]`, because `AgentOutput` does not carry it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.llm import NullLLM  # noqa: E402
from eval.harness import (  # noqa: E402
    DiagnosticState,
    Problem,
    Safety,
    build_agent,
)

OUT_OF_SCOPE = "out_of_scope"
NEGATIVE = "negative"
CONTEXT = "context"
META = "meta"

#: What the probe must do. `escalate` and `diagnose` are the two outcomes a
#: harness `AgentOutput` can show; `reply_has` is read from the spoken reply.
@dataclass(frozen=True)
class Probe:
    group: str
    utterance: str
    escalate: bool
    diagnose: bool
    reply_has: str = ""


PROBES: tuple[Probe, ...] = (
    # ---- out of scope: another device, or not a dash cam (10) --------------
    *(
        Probe(OUT_OF_SCOPE, u, escalate=True, diagnose=False)
        for u in (
            "My Garmin dash cam will not turn on.",
            "My Nextbase 522 keeps dropping the wifi.",
            "My GoPro Hero will not connect to the app.",
            "My fridge is making a clicking noise.",
            "My Samsung TV won't turn on.",
            "My phone won't connect to Wi-Fi.",
            "My car's reverse camera screen is frozen.",
            "My GoPro won't turn on.",
            "My laptop screen is flickering.",
            "My washing machine is leaking.",
        )
    ),
    # ---- negative: no symptom to diagnose (9) ------------------------------
    *(
        Probe(NEGATIVE, u, escalate=False, diagnose=False)
        for u in (
            "hello",
            "thank you",
            "bye",
            "I don't know",
            "never mind",
            "I hate this camera",
            "This is stupid",
            "You're useless",
        )
    ),
    Probe(NEGATIVE, "I want to talk to a human", escalate=True, diagnose=False),
    # ---- context first: ask which camera before diagnosing (3) -------------
    Probe(CONTEXT, "It won't turn on.", False, False, reply_has="Rove camera"),
    Probe(CONTEXT, "My dashcam won't connect to Wi-Fi.", False, False, reply_has="phone"),
    Probe(CONTEXT, "My R2-4K won't turn on.", False, True),
    # ---- meta questions (3) -------------------------------------------------
    Probe(META, "What are the camera models you support?", False, False, reply_has="R2-4K"),
    Probe(META, "What can you help me with?", False, False, reply_has="Wi-Fi"),
    Probe(META, "What dashcams do you support?", False, False, reply_has="R2-4K"),
)

assert len(PROBES) == 25, "the battery is 25 probes"


def run_probe(probe: Probe) -> tuple[bool, str]:
    """Run one probe; return (passed, why-not-if-failed)."""
    agent = build_agent("core", llm=NullLLM())
    state = DiagnosticState(
        session_id="probe",
        problem=Problem(verbatim_symptom=probe.utterance),
        safety=Safety(),
    )
    out = agent.propose(state)
    reply = agent.turns[-1].response_text
    diagnosed = bool(out.step_id) and not out.escalate and out.category not in (
        "",
        "NO_MATCH",
        "OUT_OF_SCOPE",
    )
    problems = []
    if bool(out.escalate) != probe.escalate:
        problems.append(f"escalate={out.escalate}, wanted {probe.escalate}")
    if diagnosed != probe.diagnose:
        problems.append(f"diagnosed={diagnosed}, wanted {probe.diagnose}")
    if probe.reply_has and probe.reply_has.lower() not in reply.lower():
        problems.append(f"reply lacks {probe.reply_has!r}: {reply[:90]!r}")
    return not problems, "; ".join(problems)


def run_all() -> list[tuple[Probe, bool, str]]:
    return [(p, *run_probe(p)) for p in PROBES]


def main() -> int:
    results = run_all()
    by_group: dict[str, list[bool]] = {}
    for probe, passed, why in results:
        by_group.setdefault(probe.group, []).append(passed)
        if not passed:
            print(f"FAIL [{probe.group}] {probe.utterance!r}: {why}")
    total = sum(passed for _, passed, _ in results)
    for group, flags in by_group.items():
        print(f"{group}: {sum(flags)}/{len(flags)}")
    print(f"25-probe battery: {total}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
