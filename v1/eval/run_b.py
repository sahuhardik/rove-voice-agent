"""`python -m eval.run_b` — the Harness B loop (`docs/06` §7.3).

Runs the eight scripted scenarios — the three `docs/03` marks multi-turn
(EVAL-23, EVAL-26, EVAL-27) plus the five whose expected outcome branches
(EVAL-07, EVAL-16, EVAL-17, EVAL-20, EVAL-21) — once per branch, with a
scripted responder playing the user.

    python -m eval.run_b                        # the Phase 0 dumb baseline
    python -m eval.run_b --agent core           # the Phase 1 core (Bedrock)
    python -m eval.run_b --agent core --no-llm  # the core, model calls off
    python -m eval.run_b --agent core --transcripts
    python -m eval.run_b --scenario EVAL-23     # one scenario, both branches

`--no-llm` stubs every model call out as a failure, which exercises the state
machine, retrieval, the policy filter and the output guard across turns with no
AWS credentials.

**Exit code.** Non-zero only if the harness itself errors — a malformed
scenario set, a script that drifted from the ontology, an agent returning
something that is not a step. A failed branch check is a *result*: the dumb
baseline is supposed to fail every one of them, and a runner that exited
non-zero on a bad score would make the floor measurement unrunnable in CI.
This matches `eval.run`, deliberately.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from .harness import load_scenarios
from .harness_b import (
    DRIVER_NAMES,
    HARNESS_B_IDS,
    build_driver,
    format_report_b,
    run_harness_b,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.run_b", description=__doc__)
    parser.add_argument(
        "--scenarios",
        default=None,
        help="path to a scenario set (default: eval/scenarios.json)",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        choices=list(HARNESS_B_IDS),
        help="restrict the run to one scenario (the full set still has to load)",
    )
    parser.add_argument(
        "--agent",
        choices=DRIVER_NAMES,
        default="dumb",
        help="which agent to drive (default: dumb, the Phase 0 baseline)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="run the agent with its LLM stubbed out as unavailable",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="harness turn ceiling per conversation (default: 4)",
    )
    parser.add_argument(
        "--transcripts",
        action="store_true",
        help="print every turn of every conversation under the tables",
    )
    args = parser.parse_args(argv)

    try:
        scenarios = load_scenarios(args.scenarios)
        if args.scenario:
            scenarios = [s for s in scenarios if s.id == args.scenario]
        kwargs: dict[str, object] = {}
        if args.no_llm:
            if args.agent == "dumb":
                parser.error("--no-llm is meaningless for the dumb baseline: it has no LLM")
            from agent.llm import NullLLM

            kwargs["llm"] = NullLLM()
        driver = build_driver(args.agent, **kwargs)
        run_kwargs = {} if args.max_turns is None else {"max_turns": args.max_turns}
        scripts = None
        if args.scenario:
            from .harness_b import SCRIPTS

            scripts = {args.scenario: SCRIPTS[args.scenario]}
        report = run_harness_b(
            driver,
            scenarios,
            scripts,
            **run_kwargs,  # type: ignore[arg-type]
        )
    except Exception:  # noqa: BLE001 — the harness erroring is the only failure
        traceback.print_exc()
        print("\nHARNESS ERROR — the harness itself failed, not the agent.", file=sys.stderr)
        return 1

    print(format_report_b(report, transcripts=args.transcripts))
    print()
    print(
        "Exit 0. A failed branch check is the measurement, not a failure of the "
        "run (06 §9.1, 01 §8 Q9)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
