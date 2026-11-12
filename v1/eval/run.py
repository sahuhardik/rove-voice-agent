"""`python -m eval.run` — the Harness A loop.

Runs all 30 golden scenarios through Harness A and prints the per-part table.

    python -m eval.run                  # the Phase 0 dumb baseline (default)
    python -m eval.run --agent core     # the Phase 1 diagnostic core (Bedrock)
    python -m eval.run --agent core --no-llm   # the core agent, model calls off

`--no-llm` runs the core agent with its LLM stubbed out as unavailable, which
exercises the policy filter, retrieval and the output guard while every model
call falls back to the rule-based step. It is the cheapest way to see what the
machinery contributes on its own, and it needs no AWS credentials.

**Exit code.** Non-zero only if the harness itself errors — a malformed
scenario set, an ontology inconsistency, an agent returning something that is
not a step. A low score is a *result*, not a failure: the baseline is supposed
to score badly, and a runner that failed on a bad score would make the floor
measurement unrunnable in CI.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from .harness import AGENT_NAMES, build_agent, format_report, load_scenarios, run_harness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__)
    parser.add_argument(
        "--scenarios",
        default=None,
        help="path to a scenario set (default: eval/scenarios.json)",
    )
    parser.add_argument(
        "--part",
        choices=["simple", "contextual", "complex", "escalation"],
        default=None,
        help="restrict the run to one part (the full set still has to load)",
    )
    parser.add_argument(
        "--agent",
        choices=AGENT_NAMES,
        default="dumb",
        help="which agent to grade (default: dumb, the Phase 0 baseline)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="run the agent with its LLM stubbed out as unavailable",
    )
    args = parser.parse_args(argv)

    try:
        scenarios = load_scenarios(args.scenarios)
        if args.part:
            scenarios = [s for s in scenarios if s.part == args.part]
        kwargs: dict[str, object] = {}
        if args.no_llm:
            if args.agent == "dumb":
                parser.error("--no-llm is meaningless for the dumb baseline: it has no LLM")
            from agent.llm import NullLLM

            kwargs["llm"] = NullLLM()
        agent = build_agent(args.agent, **kwargs)
        report = run_harness(agent, scenarios)
    except Exception:  # noqa: BLE001 — the harness erroring is the only failure
        traceback.print_exc()
        print("\nHARNESS ERROR — the harness itself failed, not the agent.", file=sys.stderr)
        return 1

    print(format_report(report))
    print()
    print(
        "Exit 0. A low baseline score is the measurement, not a failure "
        "(06 §9.1, 01 §8 Q9)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
