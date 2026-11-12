"""Stdlib unittest for the two-grader scorer.

    .venv/bin/python -m unittest eval.test_score_grading -v
    .venv/bin/python -m unittest discover -s eval

No LLM, no AWS, no network. Every sheet in here is written to a temp file, so
the thing under test is the *scorer*, not whatever two humans happened to write
today — the same rule `test_grounding.py` follows.

What is pinned, stated as tests rather than as prose:

* κ is the textbook unweighted Cohen's κ, including the two cases that bite —
  perfect agreement on a single category (undefined, not 1.0, and not 0.0) and
  agreement no better than chance (0.0);
* a sheet that is blank, double-filled, half-graded, note-less or
  vocabulary-drifted is **rejected**, because each of those would quietly
  change a published rate;
* the Phase 1 verdict is met only when *both* graders score every claim
  `supported`.

Imports are absolute against a forced `sys.path` entry, for the same reason as
`test_grounding.py`: `discover -s eval` imports this file with no parent
package.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval import score_grading  # noqa: E402
from eval.grounding import PARTIAL, SUPPORTED, UNSUPPORTED  # noqa: E402
from eval.score_grading import SheetError, cohens_kappa, load_sheet, report  # noqa: E402


def write_sheet(
    directory: Path,
    name: str,
    grades: list[tuple[str, str, str]],
    column: int = 1,
) -> Path:
    """A sheet with `column`'s pair filled and the other pair blank."""
    path = directory / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=score_grading_fields())
        writer.writeheader()
        for claim_id, verdict, note in grades:
            row = {f: "" for f in score_grading_fields()}
            row["claim_id"] = claim_id
            row["claim"] = f"claim text for {claim_id}"
            row[f"grader_{column}_verdict"] = verdict
            row[f"grader_{column}_note"] = note
            writer.writerow(row)
    return path


def score_grading_fields() -> list[str]:
    return [
        "claim_id",
        "harness",
        "scenario",
        "branch",
        "turn",
        "line_kind",
        "claim",
        "cited_chunk_ids",
        "instances",
        "grader_1_verdict",
        "grader_1_note",
        "grader_2_verdict",
        "grader_2_note",
    ]


class KappaTests(unittest.TestCase):
    def test_perfect_agreement_across_two_categories(self) -> None:
        a = [SUPPORTED, SUPPORTED, PARTIAL, PARTIAL]
        kappa, po, _pe, why = cohens_kappa(a, list(a))
        self.assertEqual(why, "")
        self.assertAlmostEqual(kappa, 1.0)
        self.assertAlmostEqual(po, 1.0)

    def test_perfect_agreement_on_one_category_is_undefined(self) -> None:
        """κ = (po - pe) / (1 - pe) with pe = 1 is 0/0, not 1 and not 0.

        Reporting 1.0 would claim measured agreement a sample of one category
        cannot support; reporting 0.0 would read as disagreement when the two
        graders agreed on every claim.
        """
        a = [SUPPORTED] * 5
        kappa, po, pe, why = cohens_kappa(a, list(a))
        self.assertIsNone(kappa)
        self.assertAlmostEqual(po, 1.0)
        self.assertAlmostEqual(pe, 1.0)
        self.assertIn("undefined", why)

    def test_chance_level_agreement_is_zero(self) -> None:
        a = [SUPPORTED, SUPPORTED, PARTIAL, PARTIAL]
        b = [SUPPORTED, PARTIAL, SUPPORTED, PARTIAL]
        kappa, po, pe, _why = cohens_kappa(a, b)
        self.assertAlmostEqual(po, 0.5)
        self.assertAlmostEqual(pe, 0.5)
        self.assertAlmostEqual(kappa, 0.0)

    def test_known_value(self) -> None:
        # 10 claims: 6 agreed supported, 2 agreed partial, 1 each way.
        a = [SUPPORTED] * 7 + [PARTIAL] * 3
        b = [SUPPORTED] * 6 + [PARTIAL] * 3 + [SUPPORTED]
        kappa, po, pe, _why = cohens_kappa(a, b)
        self.assertAlmostEqual(po, 0.8)
        self.assertAlmostEqual(pe, 0.7 * 0.7 + 0.3 * 0.3)
        self.assertAlmostEqual(kappa, (0.8 - 0.58) / (1 - 0.58))

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(SheetError):
            cohens_kappa([SUPPORTED], [SUPPORTED, PARTIAL])


class SheetLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_detects_the_filled_column(self) -> None:
        path = write_sheet(self.dir, "b.csv", [("C01", SUPPORTED, "the chunk says so")], column=2)
        sheet = load_sheet(path)
        self.assertEqual(sheet.column, "grader_2_verdict")
        self.assertEqual(sheet.grades["C01"].verdict, SUPPORTED)
        self.assertEqual(sheet.rate, 1.0)

    def test_blank_sheet_is_rejected(self) -> None:
        path = self.dir / "blank.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=score_grading_fields())
            writer.writeheader()
            writer.writerow({f: "" for f in score_grading_fields()} | {"claim_id": "C01"})
        with self.assertRaises(SheetError) as caught:
            load_sheet(path)
        self.assertIn("no grader column", str(caught.exception))

    def test_both_columns_filled_is_rejected(self) -> None:
        path = self.dir / "both.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=score_grading_fields())
            writer.writeheader()
            row = {f: "" for f in score_grading_fields()}
            row |= {
                "claim_id": "C01",
                "grader_1_verdict": SUPPORTED,
                "grader_1_note": "n",
                "grader_2_verdict": PARTIAL,
                "grader_2_note": "n",
            }
            writer.writerow(row)
        with self.assertRaises(SheetError) as caught:
            load_sheet(path)
        self.assertIn("grader columns are filled", str(caught.exception))

    def test_ungraded_row_is_rejected(self) -> None:
        path = write_sheet(
            self.dir,
            "half.csv",
            [("C01", SUPPORTED, "carried by step 1"), ("C02", "", "")],
        )
        with self.assertRaises(SheetError) as caught:
            load_sheet(path)
        self.assertIn("ungraded", str(caught.exception))

    def test_empty_note_is_rejected(self) -> None:
        path = write_sheet(self.dir, "nonote.csv", [("C01", SUPPORTED, "")])
        with self.assertRaises(SheetError) as caught:
            load_sheet(path)
        self.assertIn("empty note", str(caught.exception))

    def test_unknown_verdict_is_rejected(self) -> None:
        path = write_sheet(self.dir, "drift.csv", [("C01", "mostly", "hmm")])
        with self.assertRaises(SheetError) as caught:
            load_sheet(path)
        self.assertIn("not", str(caught.exception))

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(SheetError):
            load_sheet(self.dir / "nope.csv")


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.claims = {
            "measured_commit": "deadbee",
            "claims": [
                {
                    "claim_id": "C01",
                    "claim": "the card may be too slow",
                    "spoken_at": [{"harness": "A", "scenario_id": "EVAL-02",
                                   "branch": None, "turn": 1}],
                },
                {
                    "claim_id": "C02",
                    "claim": "hand to a human engineer",
                    "spoken_at": [{"harness": "B", "scenario_id": "EVAL-27",
                                   "branch": "x", "turn": 2}],
                },
            ],
        }

    def test_not_met_lists_the_failures(self) -> None:
        a = write_sheet(self.dir, "a.csv",
                        [("C01", SUPPORTED, "step 2"), ("C02", PARTIAL, "no payload")],
                        column=1)
        b = write_sheet(self.dir, "b.csv",
                        [("C01", SUPPORTED, "step 2"), ("C02", UNSUPPORTED, "nothing")],
                        column=2)
        text = report(load_sheet(a), load_sheet(b), self.claims)
        self.assertIn("NOT MET", text)
        self.assertIn("[C02]", text)
        self.assertIn("Harness A", text)
        self.assertIn("Harness B", text)
        self.assertIn("50.0%", text)

    def test_met_only_when_both_graders_say_supported(self) -> None:
        a = write_sheet(self.dir, "a.csv",
                        [("C01", SUPPORTED, "x"), ("C02", SUPPORTED, "y")], column=1)
        b = write_sheet(self.dir, "b.csv",
                        [("C01", SUPPORTED, "x"), ("C02", SUPPORTED, "y")], column=2)
        text = report(load_sheet(a), load_sheet(b), self.claims)
        self.assertIn("MET on this sample", text)
        self.assertNotIn("NOT MET", text)

    def test_partial_overlap_is_flagged_not_silently_blended(self) -> None:
        a = write_sheet(self.dir, "a.csv",
                        [("C01", SUPPORTED, "x"), ("C02", PARTIAL, "y")], column=1)
        b = write_sheet(self.dir, "b.csv", [("C01", SUPPORTED, "x")], column=2)
        text = report(load_sheet(a), load_sheet(b), self.claims)
        self.assertIn("only A: 1", text)
        self.assertIn("have not been compared", text)

    def test_kappa_threshold_is_reported_not_enforced(self) -> None:
        a = write_sheet(self.dir, "a.csv",
                        [("C01", SUPPORTED, "x"), ("C02", PARTIAL, "y")], column=1)
        b = write_sheet(self.dir, "b.csv",
                        [("C01", PARTIAL, "x"), ("C02", SUPPORTED, "y")], column=2)
        text = report(load_sheet(a), load_sheet(b), self.claims)
        self.assertIn("names no numeric", text)
        self.assertIn("reported, not passed or failed", text)


class PackShapeTests(unittest.TestCase):
    """The built pack and the scorer have to agree about the sheet's columns."""

    def test_sheet_columns_match_the_scorer(self) -> None:
        from eval import build_grounding_pack as build

        for verdict, note in score_grading.GRADER_COLUMNS:
            self.assertIn(verdict, build.SHEET_FIELDS)
            self.assertIn(note, build.SHEET_FIELDS)

    def test_pack_carries_no_previous_verdicts(self) -> None:
        """A grader who can see the first grader's answer is not a grader."""
        path = Path(__file__).with_name("grounding_pack") / "claims.json"
        if not path.exists():  # pragma: no cover — pack not built in this tree
            self.skipTest("no built pack in this tree")
        pack = json.loads(path.read_text(encoding="utf-8"))
        for claim in pack["claims"]:
            self.assertNotIn("verdict", claim)
            self.assertNotIn("previous_verdict", claim)
            self.assertNotIn("note", claim)

    def test_pack_claims_carry_chunk_text(self) -> None:
        path = Path(__file__).with_name("grounding_pack") / "claims.json"
        if not path.exists():  # pragma: no cover — pack not built in this tree
            self.skipTest("no built pack in this tree")
        pack = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(pack["claims"]), pack["sample_size"])
        for claim in pack["claims"]:
            self.assertTrue(claim["claim"].strip())
            self.assertTrue(claim["chunk_ids"])
            self.assertTrue(claim["cited_chunks"], claim["claim_id"])
            for chunk in claim["cited_chunks"]:
                self.assertTrue(chunk["text"].strip())
            self.assertIsNotNone(claim["first_spoken_at"])


if __name__ == "__main__":
    unittest.main()
