"""`python -m eval.build_grounding_pack` — assemble the two-grader grounding pack.

`docs/06` §7.4 item 1 asks for **two** human graders and a measured Cohen's κ
before an LLM judge ships. Every semantic grounding number this repo has
published so far (65 % pre-4.4, 70 % post-4.4) came from **one** grader, so
§7.4 item 1 is unmet and the Phase 1 exit on grounding is not clear. This
script builds the material a second grader needs; it **grades nothing**.

What it writes, under `eval/grounding_pack/`:

* `claims.json` — the 20 sampled claims, each with the full text of every
  chunk it cites, every scenario/turn it was spoken at, and the rubric.
* `rubric.md` — the rubric, carried over verbatim from
  `eval/grounding_semantic.json` so the two gradings are comparable.
* `sheet.csv` — one row per claim, with a column pair per grader.
* `instructions.md` — how to grade, and the independence rule.

Run it:

    .venv/bin/python -m eval.run_grounding --dump .runs/pack.json
    .venv/bin/python -m eval.build_grounding_pack \\
        --from-dump .runs/pack_a.json .runs/pack_b.json

**How the sample is drawn.** The same way Milestone 4.7 drew its sample, so
the two gradings are read against each other rather than against two different
populations:

1. The pool is every *distinct* cited line — `grounding.cited_lines` then
   `grounding.distinct_claims` — over both harnesses of the fresh run.
2. Each claim of the previous sample (`grounding_semantic.json`) that the
   current core **still produces verbatim**, with the same citation set
   (order-insensitive — 4.7 treated a reordered citation list as the same
   claim), is carried forward.
3. The rest of the 20 are replacements, taken in order from
   `grounding.sample_claims` over the fresh pool at the module's own seed,
   skipping claims already carried. If that seeded draw runs out before 20 are
   filled, the remainder comes from a seeded shuffle of what is left, at the
   same seed; whichever path was used is recorded in `claims.json`.

Carrying claims forward is not free and the pack says so: it keeps the
denominator comparable across milestones, and it means the sample is **not an
independent redraw** of the population. The provenance block in `claims.json`
records which claims are carried and which are new, and nothing in the pack
carries the previous grader's *verdicts* — a second grader who can see the
first grader's answer is not a second grader.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from . import grounding

PACK_DIR = Path(__file__).with_name("grounding_pack")

#: Column pair per grader in `sheet.csv`. The names are also what
#: `eval/score_grading.py` looks for, so the two files agree by construction.
GRADER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("grader_1", "grader_1_verdict", "grader_1_note"),
    ("grader_2", "grader_2_verdict", "grader_2_note"),
)

SHEET_FIELDS = [
    "claim_id",
    "harness",
    "scenario",
    "branch",
    "turn",
    "line_kind",
    "claim",
    "cited_chunk_ids",
    "instances",
]
for _name, _verdict, _note in GRADER_COLUMNS:
    SHEET_FIELDS += [_verdict, _note]


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — a missing git is not a build failure
        return "unknown"


@dataclass(frozen=True)
class Occurrence:
    harness: str
    scenario_id: str
    branch: str | None
    turn: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "harness": self.harness,
            "scenario_id": self.scenario_id,
            "branch": self.branch,
            "turn": self.turn,
        }

    def __str__(self) -> str:
        where = self.scenario_id if not self.branch else f"{self.scenario_id}/{self.branch}"
        return f"{self.harness}:{where} turn {self.turn}"


def _key(line_text: str, chunk_ids: Sequence[str]) -> tuple[str, frozenset[str]]:
    """Claim identity for the carry-forward test.

    Line text plus the citation *set*: 4.7 found one claim emitting the same
    three chunks in a different order and treated it as the same claim, which
    is right — the grader reads the same evidence either way.
    """
    return (line_text.strip(), frozenset(chunk_ids))


def load_pool(paths: Sequence[str], chunks_path: str | None) -> tuple[
    list[grounding.ClaimSpan], dict[tuple[str, frozenset[str]], list[Occurrence]]
]:
    """Every distinct cited claim of the run, and where each one was spoken."""
    known = grounding.known_chunk_ids(chunks_path)
    turns: list[grounding.CapturedTurn] = []
    for path in paths:
        turns.extend(
            grounding.load_turns(json.loads(Path(path).read_text(encoding="utf-8")))
        )
    spans = grounding.cited_lines(turns, known)
    occurrences: dict[tuple[str, frozenset[str]], list[Occurrence]] = {}
    for span in spans:
        occurrences.setdefault(_key(span.line_text, span.chunk_ids), []).append(
            Occurrence(
                harness=span.label.harness,
                scenario_id=span.label.scenario_id,
                branch=span.label.branch,
                turn=span.label.turn,
            )
        )
    return grounding.distinct_claims([s for s in spans if s.cited]), occurrences


def previous_claims(path: Path | None = None) -> list[tuple[str, frozenset[str]]]:
    """The previous sample's claims — text and citation set, never verdicts."""
    record = json.loads(
        (path or grounding.SEMANTIC_RECORD_PATH).read_text(encoding="utf-8")
    )
    return [_key(v["claim"], v["chunk_ids"]) for v in record["verdicts"]]


def previous_rubric(path: Path | None = None) -> list[str]:
    record = json.loads(
        (path or grounding.SEMANTIC_RECORD_PATH).read_text(encoding="utf-8")
    )
    return list(record["rubric"])


def draw_sample(
    pool: Sequence[grounding.ClaimSpan],
    carried_keys: Sequence[tuple[str, frozenset[str]]],
    size: int = grounding.SEMANTIC_SAMPLE_SIZE,
    seed: int = grounding.SEMANTIC_SAMPLE_SEED,
) -> tuple[list[grounding.ClaimSpan], list[grounding.ClaimSpan], str]:
    """(carried, replacements, how the replacements were drawn).

    `pool` is the fresh run's distinct cited claims. `carried_keys` are the
    previous sample's claims, in the previous sample's order; the ones the
    current core still produces are carried forward and the rest of the 20 are
    drawn fresh.
    """
    by_key = {_key(s.line_text, s.chunk_ids): s for s in pool}
    carried = [by_key[k] for k in carried_keys if k in by_key][:size]
    taken = {_key(s.line_text, s.chunk_ids) for s in carried}

    need = size - len(carried)
    replacements: list[grounding.ClaimSpan] = []
    if need <= 0:
        return carried, [], "none needed — the previous sample survives in full"

    for span in grounding.sample_claims(pool, size=size, seed=seed):
        if len(replacements) >= need:
            break
        key = _key(span.line_text, span.chunk_ids)
        if key in taken:
            continue
        taken.add(key)
        replacements.append(span)
    how = (
        f"in order from eval.grounding.sample_claims(pool, size={size}, "
        f"seed={seed}), skipping claims already carried"
    )

    if len(replacements) < need:
        rest = [
            s for s in pool if _key(s.line_text, s.chunk_ids) not in taken
        ]
        rest = sorted(rest, key=lambda s: (s.line_text, s.chunk_ids))
        random.Random(seed).shuffle(rest)
        for span in rest:
            if len(replacements) >= need:
                break
            taken.add(_key(span.line_text, span.chunk_ids))
            replacements.append(span)
        how += (
            f"; the seeded {size}-draw did not contain enough unheld claims, so "
            f"the remainder came from a seed-{seed} shuffle of the rest of the pool"
        )
    return carried, replacements, how


def build(
    paths: Sequence[str],
    chunks_path: str | None,
    out_dir: Path,
    *,
    commit: str,
) -> dict[str, Any]:
    from agent import retrieval

    pool, occurrences = load_pool(paths, chunks_path)
    carried_keys = previous_claims()
    carried, replacements, how = draw_sample(pool, carried_keys)
    carried_set = {_key(s.line_text, s.chunk_ids) for s in carried}

    sample = sorted(carried + replacements, key=lambda s: (s.line_text, s.chunk_ids))
    rubric = previous_rubric()

    claims: list[dict[str, Any]] = []
    for n, span in enumerate(sample, 1):
        key = _key(span.line_text, span.chunk_ids)
        where = occurrences.get(key, [])
        chunks = retrieval.chunks_by_id(span.chunk_ids, chunks_path)
        found = {c.chunk_id for c in chunks}
        claims.append(
            {
                "claim_id": f"C{n:02d}",
                "claim": span.line_text,
                "line_kind": span.kind,
                "chunk_ids": list(span.chunk_ids),
                "cited_chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "section": c.section,
                        "doc_code": c.doc_code,
                        "tier": c.tier,
                        "text": c.text,
                    }
                    for c in chunks
                ],
                "chunk_ids_not_in_corpus": [
                    cid for cid in span.chunk_ids if cid not in found
                ],
                "first_spoken_at": where[0].as_dict() if where else None,
                "spoken_at": [o.as_dict() for o in where],
                "instances": len(where),
                "carried_from_previous_sample": key in carried_set,
            }
        )

    pack = {
        "what_this_is": (
            "The two-grader grounding pack for docs/06 §7.4 item 1. Twenty spoken, "
            "cited claims from a fresh run of Harness A and Harness B, each with "
            "the full text of every chunk it cites, ready for two independent "
            "human graders. Nothing here is graded: §7.4 requires human labels "
            "before an LLM judge ships, and the published semantic rate (70% "
            "post-4.4) has one grader and no κ, which is why this pack exists. "
            "The previous grader's verdicts are deliberately NOT in this pack."
        ),
        "measured_commit": commit,
        "built_from": list(paths),
        "sample_size": len(claims),
        "pool": {
            "distinct_cited_claims": len(pool),
            "cited_line_instances": sum(len(v) for v in occurrences.values()),
            "distinct_chunks_cited_by_pool": len(
                {cid for s in pool for cid in s.chunk_ids}
            ),
            "distinct_chunks_cited_by_sample": len(
                {cid for c in claims for cid in c["chunk_ids"]}
            ),
            "per_harness_instances": dict(
                Counter(
                    o.harness for v in occurrences.values() for o in v
                )
            ),
        },
        "how_the_sample_was_drawn": {
            "carried_from_previous_sample": len(carried),
            "replacements": len(replacements),
            "replacement_rule": how,
            "seed": grounding.SEMANTIC_SAMPLE_SEED,
            "caveat": (
                "Claims carried forward keep the denominator comparable with the "
                "pre-4.4 and post-4.4 gradings. They also mean this is not an "
                "independent redraw of the population — read the rate as a "
                "property of these claims, not of the agent."
            ),
        },
        "rubric": rubric,
        "grading_is_a_human_step": (
            "Two independent human graders fill sheet.csv (one copy each), then "
            "eval/score_grading.py prints Cohen's κ and the rates. No model "
            "grades these claims."
        ),
        "claims": claims,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "claims.json").write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_rubric(out_dir / "rubric.md", rubric, commit)
    _write_sheet(out_dir / "sheet.csv", claims)
    return pack


def _write_rubric(path: Path, rubric: Sequence[str], commit: str) -> None:
    lines = [
        "# Semantic grounding rubric",
        "",
        "One question, asked of every claim in `claims.json`:",
        "",
        "> **Does the chunk the line cites support that line _as stated_?**",
        "",
        "Nothing else. Not whether the line is good advice, not whether it is a",
        "sensible next step, not whether the agent should have said it — only",
        "whether the cited evidence carries it.",
        "",
        "## The three verdicts",
        "",
    ]
    # The record keeps the verdict definitions and the edge rules in one list.
    # Split them for the reader — an edge rule printed as a fourth verdict is a
    # grader's first confusion — without editing either one.
    verdicts = [i for i in rubric if i.split(" ", 1)[0] in grounding.VERDICTS]
    rules = [i for i in rubric if i not in verdicts]
    for item in verdicts:
        lines.append(f"- **`{item.split(' ', 1)[0]}`** — {item.split('— ', 1)[-1]}")
    if rules:
        lines += ["", "## Edge rules", ""]
        for item in rules:
            lines.append(f"- {item}")
    lines += [
        "",
        "## Scoring",
        "",
        "| verdict | score |",
        "| --- | --- |",
        "| `supported` | 1 |",
        "| `partial` | 0 |",
        "| `unsupported` | 0 |",
        "",
        "`partial` scoring 0 is the point of the measurement, not a harsh reading:",
        "a citation attached to a claim it only half-carries scores full marks on",
        "the structural layer, and that is the failure the two-layer split exists",
        "to catch (`eval/grounding.py` module docstring).",
        "",
        "## Where this rubric comes from",
        "",
        "Carried over verbatim from `eval/grounding_semantic.json`, which is the",
        "rubric the pre-4.4 (65 %) and post-4.4 (70 %) single-grader gradings used.",
        "It is reused unchanged so this grading can be read against those, rather",
        "than against a rubric that moved underneath them.",
        "",
        f"Pack built at commit `{commit}`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_sheet(path: Path, claims: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for claim in claims:
            first = claim["first_spoken_at"] or {}
            row = {
                "claim_id": claim["claim_id"],
                "harness": first.get("harness", ""),
                "scenario": first.get("scenario_id", ""),
                "branch": first.get("branch") or "",
                "turn": first.get("turn", ""),
                "line_kind": claim["line_kind"],
                "claim": claim["claim"],
                "cited_chunk_ids": " | ".join(claim["chunk_ids"]),
                "instances": claim["instances"],
            }
            for _name, verdict, note in GRADER_COLUMNS:
                row[verdict] = ""
                row[note] = ""
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.build_grounding_pack", description=__doc__
    )
    parser.add_argument(
        "--from-dump",
        nargs="+",
        required=True,
        metavar="PATH",
        help="captured-turn dumps from `eval.run_grounding --dump` (both harnesses)",
    )
    parser.add_argument("--chunks", default=None, help="path to a chunks.jsonl")
    parser.add_argument("--out", default=str(PACK_DIR), help="pack directory")
    args = parser.parse_args(argv)

    commit = _commit()
    pack = build(args.from_dump, args.chunks, Path(args.out), commit=commit)
    print(f"Grounding pack built at {args.out} — core @ {commit}")
    print(
        f"  pool: {pack['pool']['distinct_cited_claims']} distinct cited claims "
        f"from {pack['pool']['cited_line_instances']} cited line instances"
    )
    print(
        f"  sample: {pack['sample_size']} claims "
        f"({pack['how_the_sample_was_drawn']['carried_from_previous_sample']} carried, "
        f"{pack['how_the_sample_was_drawn']['replacements']} replacement) citing "
        f"{pack['pool']['distinct_chunks_cited_by_sample']} distinct chunks"
    )
    print("  wrote claims.json, rubric.md, sheet.csv")
    print("  NOTHING WAS GRADED — two humans fill sheet.csv (see instructions.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
