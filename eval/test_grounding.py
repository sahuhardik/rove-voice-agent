"""Stdlib unittest for the Milestone 4.5 grounding measurement.

    .venv/bin/python -m unittest eval.test_grounding -v
    .venv/bin/python -m unittest discover -s eval

No LLM, no AWS, no network, no Postgres. Every turn in here is hand-built from
`agent.core.Line`, which is what makes the *instrument* the thing under test
rather than whatever the core happened to say today — the same rule
`test_harness_b.py` follows.

The two cases the milestone pins, stated as tests rather than as prose:

* a turn with an uncited device-specific claim **scores 0**;
* a cited-and-supported claim **scores 1** — on both layers, structural and
  semantic, because they are different claims about the same sentence.

Imports are absolute against a forced `sys.path` entry, for the same reason as
`test_harness.py`: `discover -s eval` imports this file with no parent package.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import core  # noqa: E402
from eval import grounding  # noqa: E402
from eval.grounding import (  # noqa: E402
    PARTIAL,
    SUPPORTED,
    UNSUPPORTED,
    CapturedLine,
    CapturedTurn,
    GuardRecorder,
    SemanticRecordError,
    SemanticVerdict,
    TurnLabel,
    capture_guard,
    distinct_claims,
    format_semantic,
    format_structural,
    load_semantic_record,
    sample_claims,
    scan_turn,
    semantic_rate,
    structural_report,
    turn_score,
    version_leaks,
)

#: A real chunk id shape, and a corpus that contains it.
CHUNK = "M3#LOOP_RECORDING#p46"
KNOWN = frozenset({CHUNK, "O2#WIFI_TABLE#R3"})


def _turn(*lines: CapturedLine, label: TurnLabel | None = None) -> CapturedTurn:
    return CapturedTurn(
        label=label or TurnLabel("A", "EVAL-01"), kept=list(lines)
    )


# --------------------------------------------------------------------------
# Capturing the guard — the instrument may not change what it measures
# --------------------------------------------------------------------------


class CaptureGuardTests(unittest.TestCase):
    def test_wraps_the_real_guard_and_returns_its_report(self):
        line = core.Line("Loop recording is on.", chunk_ids=[CHUNK], kind="prose")
        with capture_guard() as recorder:
            report = core.output_guard([line])
        self.assertEqual([l.text for l in report.kept], ["Loop recording is on."])
        self.assertEqual(len(recorder.turns), 1)
        self.assertEqual(recorder.turns[0].kept[0].chunk_ids, (CHUNK,))

    def test_restores_the_guard_afterwards_even_on_an_exception(self):
        real = core.output_guard
        with self.assertRaises(ValueError):
            with capture_guard():
                self.assertIsNot(core.output_guard, real)
                raise ValueError("boom")
        self.assertIs(core.output_guard, real)

    def test_records_the_guards_drops_and_rewrites_not_its_own_opinion(self):
        uncited = core.Line("The R3 has no reset button.", kind="prose")
        rewritten = core.Line(
            "Could you press the recessed reset button?",
            kind="step",
            fallback="Could you look for a small recessed hole on the body?",
        )
        with capture_guard() as recorder:
            core.output_guard([uncited, rewritten])
        turn = recorder.turns[0]
        self.assertEqual(len(turn.dropped), 1)
        self.assertEqual(len(turn.rewritten), 1)
        self.assertIn("no Tier-1 citation", turn.dropped[0][1])

    def test_labels_attach_to_the_turn_that_was_open(self):
        recorder = GuardRecorder()
        label = TurnLabel("B", "EVAL-07", branch="some_locked", turn=3)
        with capture_guard(recorder):
            with recorder.labelled(label):
                core.output_guard([core.Line("Right.", kind="prose")])
            core.output_guard([core.Line("Also right.", kind="prose")])
        self.assertEqual(recorder.turns[0].label, label)
        self.assertEqual(str(recorder.turns[0].label), "B:EVAL-07/some_locked turn 3")
        #: An unlabelled call is recorded, not swallowed.
        self.assertEqual(recorder.turns[1].label.harness, "?")


# --------------------------------------------------------------------------
# Layer 1 — structural
# --------------------------------------------------------------------------


class StructuralScanTests(unittest.TestCase):
    def test_uncited_device_specific_claim_scores_zero(self):
        turn = _turn(
            CapturedLine("The card ceiling is 512 GB.", "safety", ()),
        )
        spans = scan_turn(turn, KNOWN)
        self.assertEqual([s.span for s in spans], ["512 GB"])
        self.assertFalse(spans[0].cited)
        self.assertEqual(spans[0].reason, "no chunk id on the line")
        self.assertEqual(turn_score(spans), 0)

    def test_cited_device_specific_claim_scores_one(self):
        turn = _turn(
            CapturedLine("The card ceiling is 512 GB.", "prose", (CHUNK,)),
        )
        spans = scan_turn(turn, KNOWN)
        self.assertTrue(spans[0].cited)
        self.assertEqual(turn_score(spans), 1)

    def test_one_uncited_claim_fails_the_whole_turn(self):
        turn = _turn(
            CapturedLine("Loop recording is on.", "prose", (CHUNK,)),
            CapturedLine("The R3 has no reset button.", "safety", ()),
        )
        spans = scan_turn(turn, KNOWN)
        #: 'loop recording' on the cited line; 'R3' and 'reset button' on the
        #: uncited one — the detector counts every match, not one per line.
        self.assertEqual(
            [s.span for s in spans], ["Loop recording", "R3", "reset button"]
        )
        self.assertEqual(sum(1 for s in spans if not s.cited), 2)
        self.assertEqual(turn_score(spans), 0)

    def test_a_turn_with_no_device_specifics_is_not_counted_either_way(self):
        turn = _turn(CapturedLine("Can you tell me what you see?", "prose", ()))
        self.assertEqual(scan_turn(turn, KNOWN), [])
        #: Vacuously 1 — but it contributes no span and no turn to the rate.
        self.assertEqual(turn_score([]), 1)

    def test_a_citation_to_a_chunk_outside_the_corpus_is_not_a_citation(self):
        turn = _turn(CapturedLine("Up to 1 TB.", "prose", ("M9#NOT_A_CHUNK#p1",)))
        spans = scan_turn(turn, KNOWN)
        self.assertFalse(spans[0].cited)
        self.assertIn("not a chunk in the corpus", spans[0].reason)
        self.assertEqual(turn_score(spans), 0)

    def test_one_live_citation_beside_a_dangling_one_still_counts(self):
        turn = _turn(
            CapturedLine("Up to 1 TB.", "prose", (CHUNK, "M9#NOT_A_CHUNK#p1"))
        )
        self.assertTrue(scan_turn(turn, KNOWN)[0].cited)

    def test_safety_lines_are_exempt_in_the_guard_but_not_in_the_measurement(self):
        """The guard lets an uncited safety line through (`agent/core.py`); the
        measurement still counts it, because the user still hears it."""
        line = core.Line("The R3 has no reset button.", kind="safety")
        report = core.output_guard([line])
        self.assertEqual(len(report.kept), 1)  # the guard kept it
        turn = _turn(CapturedLine(line.text, "safety", ()))
        self.assertEqual(turn_score(scan_turn(turn, KNOWN)), 0)  # we do not

    def test_span_detection_is_the_guards_own_detector(self):
        text = "The R2-4K Dual takes up to 1 TB."
        turn = _turn(CapturedLine(text, "prose", ()))
        self.assertEqual(
            [s.span for s in scan_turn(turn, KNOWN)],
            core.device_specific_spans(text),
        )

    def test_version_leaks_are_reported_separately(self):
        turn = _turn(CapturedLine("Firmware 2.1.4 is current.", "prose", (CHUNK,)))
        self.assertEqual(version_leaks(turn), [(0, "Firmware 2.1.4")])
        self.assertEqual(version_leaks(_turn(CapturedLine("ok", "prose", ()))), [])


class StructuralReportTests(unittest.TestCase):
    def _report(self):
        turns = [
            _turn(
                CapturedLine("Loop recording is on.", "prose", (CHUNK,)),
                label=TurnLabel("A", "EVAL-01"),
            ),
            _turn(
                CapturedLine("The card ceiling is 512 GB.", "safety", ()),
                CapturedLine("Up to 1 TB.", "prose", (CHUNK,)),
                label=TurnLabel("A", "EVAL-02"),
            ),
            _turn(
                CapturedLine("Nothing specific here.", "prose", ()),
                label=TurnLabel("A", "EVAL-03"),
            ),
        ]
        return structural_report("A", turns, KNOWN, commit="deadbee")

    def test_rates_count_spans_and_turns_separately(self):
        report = self._report()
        self.assertEqual(len(report.spans), 3)
        self.assertEqual(len(report.failing), 1)
        self.assertAlmostEqual(report.span_rate, 2 / 3)
        #: Two turns carried a claim; one of them is clean.
        self.assertAlmostEqual(report.turn_rate, 1 / 2)

    def test_a_run_that_made_no_claims_reports_none_not_one(self):
        report = structural_report(
            "A", [_turn(CapturedLine("Hello.", "prose", ()))], KNOWN
        )
        self.assertIsNone(report.span_rate)
        self.assertIsNone(report.turn_rate)

    def test_every_failing_span_is_listed_with_scenario_turn_and_text(self):
        text = format_structural(self._report())
        self.assertIn("A:EVAL-02 turn 1", text)
        self.assertIn("'512 GB'", text)
        self.assertIn("The card ceiling is 512 GB.", text)
        self.assertIn("66.7%", text)

    def test_the_clean_case_says_so_plainly(self):
        turns = [_turn(CapturedLine("Loop recording is on.", "prose", (CHUNK,)))]
        text = format_structural(structural_report("A", turns, KNOWN))
        self.assertIn("100.0%", text)
        self.assertIn("No failing spans", text)


# --------------------------------------------------------------------------
# Sampling for the semantic layer
# --------------------------------------------------------------------------


class SampleTests(unittest.TestCase):
    def _spans(self, n: int):
        turns = [
            _turn(
                CapturedLine(f"Claim {i} about 512 GB.", "prose", (CHUNK,)),
                label=TurnLabel("A", f"EVAL-{i:02d}"),
            )
            for i in range(n)
        ]
        return structural_report("A", turns, KNOWN).spans

    def test_distinct_claims_collapse_repeats_of_the_same_line(self):
        turns = [
            _turn(
                CapturedLine("Up to 1 TB.", "prose", (CHUNK,)),
                label=TurnLabel("A", f"EVAL-{i:02d}"),
            )
            for i in range(5)
        ]
        spans = structural_report("A", turns, KNOWN).spans
        self.assertEqual(len(spans), 5)
        self.assertEqual(len(distinct_claims(spans)), 1)

    def test_sampling_is_reproducible_and_takes_only_cited_claims(self):
        spans = self._spans(40)
        first = [s.line_text for s in sample_claims(spans)]
        second = [s.line_text for s in sample_claims(spans)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), grounding.SEMANTIC_SAMPLE_SIZE)
        self.assertTrue(all(s.cited for s in sample_claims(spans)))

    def test_a_small_pool_is_taken_whole_rather_than_padded(self):
        self.assertEqual(len(sample_claims(self._spans(4))), 4)

    def test_uncited_claims_are_never_sampled_they_are_all_graded(self):
        turn = _turn(CapturedLine("Uncited 512 GB.", "safety", ()))
        spans = structural_report("A", [turn], KNOWN).spans
        self.assertEqual(sample_claims(spans), [])


# --------------------------------------------------------------------------
# Layer 2 — semantic, hand-graded
# --------------------------------------------------------------------------


def _verdict(verdict: str, origin: str = "sampled-cited") -> SemanticVerdict:
    return SemanticVerdict(
        claim="The card ceiling is 512 GB.",
        chunk_ids=(CHUNK,),
        verdict=verdict,
        note="checked by hand",
        origin=origin,
    )


class SemanticTests(unittest.TestCase):
    def test_a_supported_claim_scores_one(self):
        self.assertEqual(_verdict(SUPPORTED).score, 1)

    def test_unsupported_and_partial_both_score_zero(self):
        self.assertEqual(_verdict(UNSUPPORTED).score, 0)
        #: `partial` is a 0 on purpose: the measurement is whether the chunk
        #: supports the claim **as stated**, not something near it.
        self.assertEqual(_verdict(PARTIAL).score, 0)

    def test_rate_is_supported_over_graded_within_one_origin(self):
        verdicts = [
            _verdict(SUPPORTED),
            _verdict(SUPPORTED),
            _verdict(UNSUPPORTED),
            _verdict(UNSUPPORTED, origin="structural-failure"),
        ]
        self.assertAlmostEqual(semantic_rate(verdicts, "sampled-cited"), 2 / 3)
        self.assertEqual(semantic_rate(verdicts, "structural-failure"), 0.0)
        self.assertIsNone(semantic_rate([], "sampled-cited"))

    def test_failures_are_quoted_in_the_report(self):
        text = format_semantic([_verdict(SUPPORTED), _verdict(UNSUPPORTED)])
        self.assertIn("50.0%", text)
        self.assertIn("Not supported as stated", text)
        self.assertIn(CHUNK, text)


class SemanticRecordTests(unittest.TestCase):
    """The hand-graded file is a measurement artefact, so it is validated hard:
    a verdict vocabulary that drifted or a grade with no reasoning would quietly
    move a published rate."""

    def _write(self, payload) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, handle)
        handle.close()
        return handle.name

    def _entry(self, **over):
        entry = {
            "claim": "The card ceiling is 512 GB.",
            "chunk_ids": [CHUNK],
            "verdict": SUPPORTED,
            "note": "the chunk states the ceiling",
            "origin": "sampled-cited",
        }
        entry.update(over)
        return entry

    def test_loads_a_well_formed_record(self):
        path = self._write({"verdicts": [self._entry()]})
        verdicts = load_semantic_record(path)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].score, 1)

    def test_rejects_an_unknown_verdict_word(self):
        path = self._write({"verdicts": [self._entry(verdict="probably fine")]})
        with self.assertRaises(SemanticRecordError):
            load_semantic_record(path)

    def test_rejects_a_grade_with_no_note(self):
        path = self._write({"verdicts": [self._entry(note="  ")]})
        with self.assertRaises(SemanticRecordError):
            load_semantic_record(path)

    def test_rejects_an_unknown_origin(self):
        path = self._write({"verdicts": [self._entry(origin="llm-judge")]})
        with self.assertRaises(SemanticRecordError):
            load_semantic_record(path)

    def test_rejects_a_missing_field_an_empty_record_and_bad_json(self):
        entry = self._entry()
        del entry["chunk_ids"]
        for payload in ({"verdicts": [entry]}, {"verdicts": []}, {"nope": []}):
            with self.assertRaises(SemanticRecordError):
                load_semantic_record(self._write(payload))
        with self.assertRaises(SemanticRecordError):
            load_semantic_record("/nonexistent/grounding_semantic.json")

    def test_the_shipped_record_loads_and_grades_only_real_claims(self):
        verdicts = load_semantic_record()
        sampled = [v for v in verdicts if v.origin == "sampled-cited"]
        self.assertGreaterEqual(len(sampled), 1)
        #: The sample may not quietly grow past the size it is published at.
        self.assertLessEqual(len(sampled), grounding.SEMANTIC_SAMPLE_SIZE)
        for v in verdicts:
            self.assertTrue(v.claim.strip())
            #: A sampled claim is by definition a line that carried a citation.
            #: Grading an uncited line as "supported" would inflate the rate
            #: with something the structural layer already counts as a miss.
            if v.origin == "sampled-cited":
                self.assertTrue(v.chunk_ids, v.claim)
        self.assertIsNotNone(semantic_rate(verdicts, "sampled-cited"))

    def test_the_shipped_record_agrees_with_the_published_rate(self):
        """The README quotes 14/20 (Milestone 4.7, post-4.4; it was 13/20
        pre-4.4). If a verdict is edited, this fails rather than letting the
        document and the record drift apart."""
        verdicts = load_semantic_record()
        sampled = [v for v in verdicts if v.origin == "sampled-cited"]
        self.assertEqual(len(sampled), 20)
        self.assertEqual(sum(v.score for v in sampled), 14)
        self.assertAlmostEqual(semantic_rate(verdicts, "sampled-cited"), 0.70)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
