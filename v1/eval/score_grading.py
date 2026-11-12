"""`python -m eval.score_grading` — score two completed grading sheets.

The counterpart to `eval/build_grounding_pack.py`. It takes the two sheets the
two human graders filled in and prints:

* **Cohen's κ** between them, over the three-verdict vocabulary, with the
  confusion matrix and every claim they disagreed on.
* **The semantic grounding rate per grader**, and — because `eval/grounding.py`
  refuses to blend harnesses and so does this — the same rate per harness, plus
  the consensus rate over the claims both graders called `supported`.
* **The verdict against the `docs/06` §9.1 Phase 1 bar of 100 %.**

    .venv/bin/python -m eval.score_grading \\
        eval/grounding_pack/sheet_hardik.csv eval/grounding_pack/sheet_second.csv

**This script does not grade.** It counts what two humans wrote. `docs/06` §7.4
item 1 asks for two human graders and a measured κ before an LLM judge ships;
until both sheets exist there is nothing here to run, and that absence is the
finding, not a gap to paper over with a model.

**On the κ threshold.** §7.4 says an LLM judge ships "only above an agreed κ
against humans" and names **no number**. This script therefore *reports* κ and
the usual Landis–Koch descriptive bands and does **not** pass or fail on it —
inventing a threshold here would quietly become the project's standard. It
fails on one thing only: the 100 % bar §9.1 does state.

**Exit code.** Non-zero only if the sheets cannot be read or do not line up. A
rate below 100 % or a low κ is a *result*, and a scorer that exited non-zero on
a result would make the result unrunnable in CI — same rule as
`eval.run_grounding`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .grounding import GROUNDING_TARGET, SUPPORTED, VERDICTS

PACK_DIR = Path(__file__).with_name("grounding_pack")

#: The column pairs `build_grounding_pack` writes into `sheet.csv`. A grader
#: fills exactly one pair; which one is detected per file.
GRADER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("grader_1_verdict", "grader_1_note"),
    ("grader_2_verdict", "grader_2_note"),
)

#: Landis & Koch (1977), descriptive only. Printed next to κ so the number is
#: readable; it is **not** a pass mark — §7.4 leaves the threshold to be agreed.
_BANDS = (
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.01, "slight"),
    (float("-inf"), "poor — at or below chance"),
)


class SheetError(ValueError):
    """A grading sheet this script cannot score."""


@dataclass(frozen=True)
class Grade:
    claim_id: str
    verdict: str
    note: str

    @property
    def score(self) -> int:
        return 1 if self.verdict == SUPPORTED else 0


@dataclass
class Sheet:
    path: Path
    grader: str
    column: str
    grades: dict[str, Grade]

    @property
    def rate(self) -> float | None:
        if not self.grades:
            return None
        return sum(g.score for g in self.grades.values()) / len(self.grades)

    def counts(self) -> Counter[str]:
        return Counter(g.verdict for g in self.grades.values())

    def rate_over(self, claim_ids: Sequence[str]) -> float | None:
        scope = [self.grades[c] for c in claim_ids if c in self.grades]
        if not scope:
            return None
        return sum(g.score for g in scope) / len(scope)


def _filled(rows: Sequence[dict[str, str]], column: str) -> list[dict[str, str]]:
    return [r for r in rows if (r.get(column) or "").strip()]


def load_sheet(path: str | Path, column: str | None = None, grader: str | None = None) -> Sheet:
    """One completed sheet, validated hard.

    A malformed sheet has to fail loudly for the same reason
    `grounding.load_semantic_record` does: a verdict vocabulary that drifted, or
    a grade with no note behind it, would quietly change a published rate.
    """
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise SheetError(f"no grading sheet at {path}") from exc
    if not rows:
        raise SheetError(f"{path} has no rows")
    if "claim_id" not in rows[0]:
        raise SheetError(f"{path} has no 'claim_id' column — is it a grading sheet?")

    pairs = [(v, n) for v, n in GRADER_COLUMNS if v in rows[0]]
    if column is not None:
        note_col = dict(GRADER_COLUMNS).get(column)
        if note_col is None or column not in rows[0]:
            raise SheetError(f"{path} has no column {column!r}")
        chosen: list[tuple[str, str]] = [(column, note_col)]
    else:
        chosen = [p for p in pairs if _filled(rows, p[0])]
    if not chosen:
        raise SheetError(
            f"{path}: no grader column is filled in — expected one of "
            f"{[v for v, _ in GRADER_COLUMNS]}. An empty sheet is not a grading."
        )
    if len(chosen) > 1:
        raise SheetError(
            f"{path}: {len(chosen)} grader columns are filled in "
            f"({[v for v, _ in chosen]}). One grader fills one column pair in "
            f"their own copy — pass --column-a / --column-b if that is wrong."
        )
    verdict_col, note_col = chosen[0]

    grades: dict[str, Grade] = {}
    blank: list[str] = []
    for row in rows:
        claim_id = (row.get("claim_id") or "").strip()
        if not claim_id:
            continue
        verdict = (row.get(verdict_col) or "").strip().lower()
        note = (row.get(note_col) or "").strip()
        if not verdict:
            blank.append(claim_id)
            continue
        if verdict not in VERDICTS:
            raise SheetError(
                f"{path}: claim {claim_id} has verdict {verdict!r}, which is not "
                f"one of {list(VERDICTS)}"
            )
        if not note:
            raise SheetError(
                f"{path}: claim {claim_id} is graded {verdict!r} with an empty "
                f"note — an ungrounded grade is not a grade"
            )
        if claim_id in grades:
            raise SheetError(f"{path}: claim {claim_id} appears twice")
        grades[claim_id] = Grade(claim_id=claim_id, verdict=verdict, note=note)
    if blank:
        raise SheetError(
            f"{path}: {len(blank)} claim(s) are ungraded ({', '.join(blank[:5])}"
            f"{'…' if len(blank) > 5 else ''}). Grade every claim, or the "
            f"denominator is not 20 and the rate is not comparable."
        )
    return Sheet(
        path=path,
        grader=grader or verdict_col.replace("_verdict", ""),
        column=verdict_col,
        grades=grades,
    )


def cohens_kappa(
    a: Sequence[str], b: Sequence[str], categories: Sequence[str] = VERDICTS
) -> tuple[float | None, float, float, str]:
    """(κ, observed agreement, expected agreement, why κ is None if it is).

    Unweighted κ over the three-verdict vocabulary. κ is **undefined** when
    expected agreement is 1 — both graders used a single category for every
    claim — and this returns `None` there rather than a 0 that reads like
    disagreement. Perfect agreement on one category is not chance-level
    agreement; it is a sample that cannot measure agreement at all.
    """
    if len(a) != len(b):
        raise SheetError("the two gradings cover a different number of claims")
    n = len(a)
    if not n:
        raise SheetError("there is nothing to compare")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    if abs(1.0 - pe) < 1e-12:
        return (
            None,
            po,
            pe,
            "undefined: expected agreement is 1.0 — both graders used a single "
            "verdict for every claim, so there is no chance-corrected agreement "
            "to measure",
        )
    return (po - pe) / (1.0 - pe), po, pe, ""


def _band(kappa: float) -> str:
    for floor, name in _BANDS:
        if kappa >= floor:
            return name
    return "poor"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:.1f}%"


def load_claims(path: str | Path | None) -> dict[str, Any] | None:
    path = Path(path) if path is not None else PACK_DIR / "claims.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _by_harness(claims: dict[str, Any] | None) -> dict[str, list[str]]:
    """claim_ids spoken in each harness.

    A claim spoken in both harnesses counts in both — this is membership, not a
    partition, and the report says so. Harnesses are never blended into one
    rate here for the same reason `eval/grounding.py` refuses to: they are
    different conversations of different lengths, and an average over both
    hides whichever one collapsed.
    """
    out: dict[str, list[str]] = {}
    if not claims:
        return out
    for claim in claims.get("claims", []):
        for where in claim.get("spoken_at", []):
            out.setdefault(where["harness"], []).append(claim["claim_id"])
    return {k: sorted(set(v)) for k, v in sorted(out.items())}


def report(
    sheet_a: Sheet, sheet_b: Sheet, claims: dict[str, Any] | None = None
) -> str:
    shared = sorted(set(sheet_a.grades) & set(sheet_b.grades))
    only_a = sorted(set(sheet_a.grades) - set(sheet_b.grades))
    only_b = sorted(set(sheet_b.grades) - set(sheet_a.grades))

    lines: list[str] = []
    lines.append("Two-grader semantic grounding — docs/06 §7.4 item 1")
    if claims:
        lines.append(f"  pack built at: {claims.get('measured_commit', '?')}")
    lines.append(f"  grader A: {sheet_a.grader}  ({sheet_a.path})")
    lines.append(f"  grader B: {sheet_b.grader}  ({sheet_b.path})")
    lines.append(
        f"  claims graded by both: {len(shared)}"
        + (f"   only A: {len(only_a)}   only B: {len(only_b)}" if only_a or only_b else "")
    )
    if only_a or only_b:
        lines.append(
            "  NOTE: κ and the consensus rate are over the shared claims only. "
            "Two graders who graded different claims have not been compared."
        )
    lines.append("")

    # --- agreement -------------------------------------------------------
    va = [sheet_a.grades[c].verdict for c in shared]
    vb = [sheet_b.grades[c].verdict for c in shared]
    kappa, po, pe, why = cohens_kappa(va, vb)
    lines.append("Inter-rater agreement")
    lines.append(f"  observed agreement: {_pct(po)}   expected by chance: {_pct(pe)}")
    if kappa is None:
        lines.append(f"  COHEN'S KAPPA: {why}")
    else:
        lines.append(f"  COHEN'S KAPPA: {kappa:.3f}  ({_band(kappa)}, Landis-Koch)")
    lines.append(
        "  §7.4 names no numeric κ — it says a judge ships 'only above an agreed "
        "κ'. This number is reported, not passed or failed."
    )
    lines.append("")
    lines.append("  Confusion matrix (rows: grader A, cols: grader B)")
    header = "    " + "".join(f"{v[:11]:>13}" for v in VERDICTS)
    lines.append(f"{'':>14}{header[4:]}")
    for ra in VERDICTS:
        row = f"  {ra:>12}"
        for rb in VERDICTS:
            row += f"{sum(1 for x, y in zip(va, vb) if x == ra and y == rb):>13}"
        lines.append(row)
    lines.append("")

    disagreed = [c for c in shared if sheet_a.grades[c].verdict != sheet_b.grades[c].verdict]
    if disagreed:
        lines.append(f"  Disagreements ({len(disagreed)}):")
        for claim_id in disagreed:
            ga, gb = sheet_a.grades[claim_id], sheet_b.grades[claim_id]
            text = _claim_text(claims, claim_id)
            lines.append(f"    [{claim_id}] A={ga.verdict}  B={gb.verdict}")
            if text:
                lines.append(f"      {text}")
            lines.append(f"      A: {ga.note}")
            lines.append(f"      B: {gb.note}")
    else:
        lines.append("  No disagreements: the two graders returned identical verdicts.")
    lines.append("")

    # --- rates -----------------------------------------------------------
    lines.append("Semantic grounding rate — supported / graded, per grader")
    lines.append(
        f"  grader A ({sheet_a.grader}): {_pct(sheet_a.rate)}   "
        + "  ".join(f"{v}={sheet_a.counts().get(v, 0)}" for v in VERDICTS)
    )
    lines.append(
        f"  grader B ({sheet_b.grader}): {_pct(sheet_b.rate)}   "
        + "  ".join(f"{v}={sheet_b.counts().get(v, 0)}" for v in VERDICTS)
    )
    both = [c for c in shared
            if sheet_a.grades[c].verdict == SUPPORTED
            and sheet_b.grades[c].verdict == SUPPORTED]
    consensus = len(both) / len(shared) if shared else None
    lines.append(
        f"  consensus (both graders say supported): {_pct(consensus)}  "
        f"({len(both)}/{len(shared)})"
    )
    lines.append("")

    harnesses = _by_harness(claims)
    if harnesses:
        lines.append("  Per harness — never blended (eval/grounding.py's rule).")
        lines.append(
            "  A claim spoken in both harnesses counts in both; these are "
            "membership sets, not a partition."
        )
        for name, ids in harnesses.items():
            shared_ids = [c for c in ids if c in shared]
            both_ids = [c for c in shared_ids if c in both]
            lines.append(
                f"    Harness {name}: {len(ids)} claim(s)   "
                f"A {_pct(sheet_a.rate_over(ids))}   B {_pct(sheet_b.rate_over(ids))}   "
                f"consensus {_pct(len(both_ids) / len(shared_ids) if shared_ids else None)}"
            )
    else:
        lines.append(
            "  Per-harness breakdown unavailable: claims.json was not found, so "
            "which harness each claim came from is unknown."
        )
    lines.append("")

    # --- the bar ---------------------------------------------------------
    target = f"{100.0 * GROUNDING_TARGET:.0f}%"
    rates = [r for r in (sheet_a.rate, sheet_b.rate) if r is not None]
    met = bool(rates) and all(r >= GROUNDING_TARGET for r in rates)
    lines.append(f"Phase 1 exit on semantic grounding (docs/06 §9.1 asks {target})")
    if met:
        lines.append(
            f"  MET on this sample: both graders scored every graded claim "
            f"`supported`. Read it as a property of {len(shared)} claims, not of "
            f"the agent — see claims.json 'how_the_sample_was_drawn'."
        )
    else:
        worst = min(rates) if rates else None
        lines.append(
            f"  NOT MET: the lower of the two grader rates is {_pct(worst)}, "
            f"against a bar of {target}."
        )
        failed = sorted(
            c for c in shared
            if sheet_a.grades[c].verdict != SUPPORTED
            or sheet_b.grades[c].verdict != SUPPORTED
        )
        lines.append(
            f"  {len(failed)} of {len(shared)} shared claims were called "
            f"something other than `supported` by at least one grader:"
        )
        for claim_id in failed:
            ga, gb = sheet_a.grades[claim_id], sheet_b.grades[claim_id]
            text = _claim_text(claims, claim_id)
            lines.append(f"    [{claim_id}] A={ga.verdict}  B={gb.verdict}"
                         + (f"  — {text}" if text else ""))
    lines.append("")
    lines.append(
        "§7.4 item 1 (two human graders, measured agreement): MET by this run — "
        "two sheets, κ above. Item 2 (an LLM judge validated against these "
        "labels at an agreed κ) is not addressed here and no judge ships on "
        "this alone."
    )
    return "\n".join(lines)


def _claim_text(claims: dict[str, Any] | None, claim_id: str, width: int = 96) -> str:
    if not claims:
        return ""
    for claim in claims.get("claims", []):
        if claim["claim_id"] == claim_id:
            text = claim["claim"]
            return text if len(text) <= width else text[: width - 1] + "…"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.score_grading", description=__doc__
    )
    parser.add_argument("sheet_a", help="the first grader's completed sheet.csv")
    parser.add_argument("sheet_b", help="the second grader's completed sheet.csv")
    parser.add_argument(
        "--claims",
        default=None,
        help="claims.json from the pack (default: eval/grounding_pack/claims.json) "
        "— used for the per-harness split and to print claim text",
    )
    parser.add_argument("--column-a", default=None, help="force grader A's column")
    parser.add_argument("--column-b", default=None, help="force grader B's column")
    parser.add_argument("--name-a", default=None, help="grader A's name, for the report")
    parser.add_argument("--name-b", default=None, help="grader B's name, for the report")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args(argv)

    try:
        if Path(args.sheet_a).resolve() == Path(args.sheet_b).resolve():
            raise SheetError(
                "both arguments are the same file. Two independent gradings are "
                "two files; one file scored against itself gives κ = 1 and means "
                "nothing."
            )
        sheet_a = load_sheet(args.sheet_a, args.column_a, args.name_a)
        sheet_b = load_sheet(args.sheet_b, args.column_b, args.name_b)
        claims = load_claims(args.claims)
    except SheetError as exc:
        print(f"CANNOT SCORE: {exc}", file=sys.stderr)
        return 1

    if args.json:
        shared = sorted(set(sheet_a.grades) & set(sheet_b.grades))
        kappa, po, pe, why = cohens_kappa(
            [sheet_a.grades[c].verdict for c in shared],
            [sheet_b.grades[c].verdict for c in shared],
        )
        print(json.dumps(
            {
                "graders": [sheet_a.grader, sheet_b.grader],
                "shared_claims": len(shared),
                "cohens_kappa": kappa,
                "kappa_undefined_because": why or None,
                "observed_agreement": po,
                "expected_agreement": pe,
                "rate_grader_a": sheet_a.rate,
                "rate_grader_b": sheet_b.rate,
                "counts_grader_a": dict(sheet_a.counts()),
                "counts_grader_b": dict(sheet_b.counts()),
                "phase_1_bar": GROUNDING_TARGET,
                "phase_1_met": all(
                    r is not None and r >= GROUNDING_TARGET
                    for r in (sheet_a.rate, sheet_b.rate)
                ),
            },
            indent=2,
        ))
    else:
        print(report(sheet_a, sheet_b, claims))
    return 0


if __name__ == "__main__":
    sys.exit(main())
