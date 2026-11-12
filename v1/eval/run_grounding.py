"""`python -m eval.run_grounding` — the Milestone 4.5 grounding measurement.

Runs the Phase 1 core over Harness A (30 scenarios) and Harness B (8 scenarios
× 2 branches = 16 runs), captures the output guard's per-line verdict on every
turn, and reports the **structural** grounding rate for each harness
separately — never blended, because they are different conversations of
different lengths and an average over both would hide whichever one collapsed.

    python -m eval.run_grounding                 # both harnesses, Bedrock
    python -m eval.run_grounding --harness A
    python -m eval.run_grounding --no-llm        # model calls off
    python -m eval.run_grounding --sample        # print the claims to hand-grade
    python -m eval.run_grounding --semantic      # print the hand-graded layer

The **semantic** layer is not computed here. `docs/06` §7.4 requires human
labels before an LLM judge ships, and there are none yet, so the verdicts are
read and written by a person into `eval/grounding_semantic.json`; `--semantic`
only counts them. `--sample` prints the sampled claims with their cited chunk
text, which is the input a human needs to grade them.

**Exit code.** Non-zero only if the measurement itself errors. A grounding rate
below 100 % is a *result* — `docs/06` §9.1 Phase 1 exit asks for 100 %, and a
runner that exited non-zero on a miss would make the failure unrunnable in CI,
which is the one place it has to run. This matches `eval.run` and `eval.run_b`,
deliberately.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from . import grounding


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — a missing git is not a measurement failure
        return "unknown"


def _dump(path: str | None, suffix: str, turns: list[grounding.CapturedTurn]) -> None:
    if not path:
        return
    target = Path(path)
    target = target.with_name(f"{target.stem}_{suffix}{target.suffix or '.json'}")
    target.write_text(
        json.dumps(grounding.dump_turns(turns), indent=2), encoding="utf-8"
    )
    print(f"  wrote {len(turns)} captured turns to {target}")


def _print_sample(
    turns: list[grounding.CapturedTurn],
    known: frozenset[str],
    chunks_path: str | None,
) -> None:
    """The hand-grading worksheet: each sampled claim and the chunk it cites.

    Drawn from every *cited line* of both harnesses, not from the structural
    spans — see `grounding.cited_lines` for why the two layers do not share a
    unit.
    """
    from agent import retrieval

    sample = grounding.sample_claims(grounding.cited_lines(turns, known))
    print(f"\n{len(sample)} sampled cited claims to grade by hand "
          f"(seed {grounding.SEMANTIC_SAMPLE_SEED}):")
    for n, span in enumerate(sample, 1):
        print(f"\n--- {n} ---")
        print(f"claim: {span.line_text}")
        print(f"cites: {', '.join(span.chunk_ids)}")
        for chunk in retrieval.chunks_by_id(span.chunk_ids, chunks_path):
            print(f"  [{chunk.chunk_id}] {chunk.section}")
            print(f"    {chunk.text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.run_grounding", description=__doc__
    )
    parser.add_argument("--harness", choices=["A", "B", "both"], default="both")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="run the core with its LLM stubbed out as unavailable",
    )
    parser.add_argument("--chunks", default=None, help="path to a chunks.jsonl")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="print the sampled cited claims with their chunk text, to hand-grade",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="count the hand-graded verdicts in eval/grounding_semantic.json",
    )
    parser.add_argument(
        "--dump",
        default=None,
        help="write every captured turn to this JSON path (one file per harness, "
        "suffixed _a / _b) so the semantic layer can be graded without re-running",
    )
    parser.add_argument(
        "--from-dump",
        nargs="+",
        default=None,
        metavar="PATH",
        help="re-report from dumps instead of running the harnesses — the same "
        "scan over the same turns, with no Bedrock call and no new numbers",
    )
    args = parser.parse_args(argv)

    commit = _commit()
    kwargs: dict[str, Any] = {"chunks_path": args.chunks}
    if args.no_llm:
        from agent.llm import NullLLM

        kwargs["llm"] = NullLLM()

    try:
        known = grounding.known_chunk_ids(args.chunks)
        all_spans: list[grounding.ClaimSpan] = []
        all_turns: list[grounding.CapturedTurn] = []
        print(f"Grounding measurement — core @ {commit}"
              f"{' (--no-llm)' if args.no_llm else ''}")
        print(f"corpus: {len(known)} chunks")
        print()
        if args.from_dump:
            for path in args.from_dump:
                turns = grounding.load_turns(
                    json.loads(Path(path).read_text(encoding="utf-8"))
                )
                name = turns[0].label.harness if turns else "?"
                report = grounding.structural_report(
                    name, turns, known, commit=f"{commit} (from {path})"
                )
                all_spans.extend(report.spans)
                all_turns.extend(turns)
                print(grounding.format_structural(report))
                print()
        else:
            if args.harness in ("A", "both"):
                _, turns = grounding.run_harness_a(**kwargs)
                report = grounding.structural_report("A", turns, known, commit=commit)
                all_spans.extend(report.spans)
                all_turns.extend(turns)
                print(grounding.format_structural(report))
                print()
                _dump(args.dump, "a", turns)
            if args.harness in ("B", "both"):
                _, turns = grounding.run_harness_b(**kwargs)
                report = grounding.structural_report("B", turns, known, commit=commit)
                all_spans.extend(report.spans)
                all_turns.extend(turns)
                print(grounding.format_structural(report))
                print()
                _dump(args.dump, "b", turns)
        if args.sample:
            _print_sample(all_turns, known, args.chunks)
        if args.semantic:
            print()
            print(grounding.format_semantic(grounding.load_semantic_record()))
    except Exception:  # noqa: BLE001 — only the instrument erroring is a failure
        traceback.print_exc()
        print(
            "\nMEASUREMENT ERROR — the instrument failed, not the agent.",
            file=sys.stderr,
        )
        return 1

    print()
    print(
        "Exit 0. A rate below 100% is the measurement, not a failure of the run "
        "(06 §9.1 Phase 1 exit)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
