"""Stdlib unittest for the Phase 0 harness.

    .venv/bin/python -m unittest discover -s eval
    .venv/bin/python -m unittest eval.test_harness -v

Imports are absolute, with the repo root forced onto `sys.path` below.
`discover -s eval` makes `eval/` the top-level directory and imports this file
as a bare `test_harness` with no parent package, which breaks relative imports;
absolute imports work under both invocations.
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

from eval import ontology  # noqa: E402
from eval.baseline import DumbBaselineAgent, match_taxonomy  # noqa: E402
from eval.harness import (  # noqa: E402
    EXPECTED_PART_COUNTS,
    SCENARIOS_PATH,
    AgentOutput,
    DiagnosticState,
    Ledger,
    Problem,
    Scenario,
    ScenarioSetError,
    load_scenarios,
    run_harness,
    score,
    state_from_scenario,
)
from eval.ontology import AttemptedStep  # noqa: E402


class TestLoader(unittest.TestCase):
    def test_loads_exactly_thirty_scenarios(self):
        scenarios = load_scenarios()
        self.assertEqual(len(scenarios), 30)
        self.assertEqual(
            [s.id for s in scenarios], [f"EVAL-{n:02d}" for n in range(1, 31)]
        )

    def test_part_counts_match_docs_03(self):
        scenarios = load_scenarios()
        counts = {part: 0 for part in EXPECTED_PART_COUNTS}
        for s in scenarios:
            counts[s.part] += 1
        self.assertEqual(counts, EXPECTED_PART_COUNTS)

    def test_four_unconditional_escalations(self):
        scenarios = load_scenarios()
        escalating = [s.id for s in scenarios if s.escalation_expected]
        self.assertEqual(escalating, ["EVAL-24", "EVAL-28", "EVAL-29", "EVAL-30"])

    def test_fails_loudly_on_wrong_count(self):
        raw = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        raw["scenarios"] = raw["scenarios"][:29]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ScenarioSetError) as ctx:
                load_scenarios(path)
        self.assertIn("exactly 30", str(ctx.exception))

    def test_fails_loudly_on_missing_file(self):
        with self.assertRaises(ScenarioSetError):
            load_scenarios("/nonexistent/scenarios.json")

    def test_tried_becomes_ledger_entries(self):
        scenarios = {s.id: s for s in load_scenarios()}
        state = state_from_scenario(scenarios["EVAL-12"])
        self.assertEqual(len(state.ledger.attempted), 1)
        entry = state.ledger.attempted[0]
        self.assertEqual(entry.step_id, "STEP.CARD.FORMAT_IN_CAMERA")
        self.assertEqual(entry.count, 2)
        self.assertTrue(entry.blocking)

    def test_every_contextual_scenario_has_a_ledger(self):
        for scenario in load_scenarios():
            if scenario.part == "contextual":
                self.assertTrue(
                    scenario.ledger,
                    f"{scenario.id} is contextual but has no Tried entries; docs/03 "
                    "says every one of these tests no-repeat",
                )


class TestOntology(unittest.TestCase):
    def test_validate_passes(self):
        ontology.validate()

    def test_contains_the_five_families_named_in_06_section_3_6(self):
        for family_id in (
            "FAMILY.DESTRUCTIVE.ERASE_CARD",
            "FAMILY.DESTRUCTIVE.RESET_DEVICE",
            "FAMILY.POWER_CYCLE",
            "FAMILY.APP_STATE",
            "FAMILY.OBSERVE",
        ):
            self.assertIn(family_id, ontology.FAMILIES)
            self.assertEqual(ontology.FAMILIES[family_id].source, "06 §3.6")

    def test_contains_every_step_id_named_in_06_section_3_6(self):
        for step_id in (
            "STEP.CARD.FORMAT_IN_CAMERA",
            "STEP.CARD.FORMAT_ON_COMPUTER",
            "STEP.DEVICE.RESTORE_DEFAULT_SETTINGS",
            "STEP.DEVICE.HARD_RESET_PINHOLE",
            "STEP.DEVICE.POWER_CYCLE",
            "STEP.DEVICE.UNPLUG_REPLUG",
            "STEP.APP.FORCE_CLOSE_REOPEN",
            "STEP.APP.RETRY_CONNECT_BUTTON",
            "STEP.APP.CLEAR_CACHE",
            "STEP.APP.REINSTALL",
            "STEP.OBSERVE.READ_SCREEN_VERBATIM",
            "STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT",
            "STEP.OBSERVE.READ_SSID",
            "STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST",
        ):
            self.assertIn(step_id, ontology.STEPS)
            self.assertEqual(ontology.STEPS[step_id].source, "06 §3.6")

    def test_every_family_referenced_by_the_map_exists(self):
        for taxonomy_id, step_ids in ontology.TAXONOMY_CANDIDATES.items():
            for step_id in step_ids:
                self.assertIn(step_id, ontology.STEPS, f"{taxonomy_id} -> {step_id}")
                family = ontology.STEPS[step_id].family
                self.assertIn(family, ontology.FAMILIES, f"{step_id} -> {family}")

    def test_every_taxonomy_entry_in_docs_02_has_candidates(self):
        expected = [
            f"{prefix}-{n:02d}"
            for prefix, count in (
                ("WIFI", 5),
                ("FW", 4),
                ("APP", 4),
                ("REC", 4),
                ("SD", 4),
                ("PWR", 4),
                ("VID", 3),
            )
            for n in range(1, count + 1)
        ]
        self.assertEqual(len(expected), 28, "docs/02 has 28 entries")
        for taxonomy_id in expected:
            self.assertIn(taxonomy_id, ontology.TAXONOMY_CANDIDATES)
            self.assertTrue(ontology.TAXONOMY_CANDIDATES[taxonomy_id])

    def test_observe_and_ask_are_no_repeat_exempt(self):
        self.assertTrue(ontology.STEPS["STEP.OBSERVE.READ_SCREEN_VERBATIM"].no_repeat_exempt)
        self.assertTrue(ontology.STEPS["STEP.ASK.PHONE_OS_AND_VERSION"].no_repeat_exempt)
        self.assertFalse(ontology.STEPS["STEP.CARD.FORMAT_IN_CAMERA"].no_repeat_exempt)

    def test_family_blocking_drops_a_sibling_step(self):
        """EVAL-12's case: in-camera format failed, so a computer format is out."""
        ledger = [
            AttemptedStep(
                step_id="STEP.CARD.FORMAT_IN_CAMERA",
                step_family="FAMILY.DESTRUCTIVE.ERASE_CARD",
                source="user_volunteered",
                outcome="no_change",
                count=2,
            )
        ]
        blocked = ontology.blocked_ids(ledger)
        self.assertIn("FAMILY.DESTRUCTIVE.ERASE_CARD", blocked)
        candidates = {
            c.step_id: c
            for c in ontology.legal_candidates("SD-01", ledger, allow_destructive=True)
        }
        self.assertFalse(candidates["STEP.CARD.FORMAT_ON_COMPUTER"].kept)
        self.assertIn("no-repeat", candidates["STEP.CARD.FORMAT_ON_COMPUTER"].drop_reason)


# --------------------------------------------------------------------------
# A hand-built scenario, used to prove the M4 scorer actually bites.
# --------------------------------------------------------------------------


def _hand_built_scenario() -> Scenario:
    """Minimal scenario: the caller has already formatted the card, twice."""
    return Scenario(
        id="HAND-01",
        part="contextual",
        taxonomy_id=["SD-01"],
        expected_category=["SD"],
        utterance="I've formatted it twice and it still says card error.",
        known_context={
            "model": "unknown",
            "firmware": "unknown",
            "phone_os": "unknown",
            "fields": {},
            "tried": [
                {
                    "step_id": "STEP.CARD.FORMAT_IN_CAMERA",
                    "step_family": "FAMILY.DESTRUCTIVE.ERASE_CARD",
                    "source": "user_volunteered",
                    "count": 2,
                    "outcome": "no_change",
                    "verbatim": "I've formatted it twice",
                    "also_blocks": [],
                }
            ],
        },
        expected_device="unknown",
        expected_diagnosis="Card at end of life.",
        expected_next_step="Ask for the card's specs.",
        expected_step_ids=["STEP.ASK.CARD_SPECS_AND_RATING"],
        wrong_response="Another format.",
        escalation_expected=False,
        escalation_conditional=None,
        harmful_steps=[],
        footage_at_stake=False,
        driving=False,
        notes="Hand-built for the M4 unit test.",
    )


class _FixedStepAgent:
    """Always proposes the same step. The simplest possible probe."""

    def __init__(self, step_id: str, *, gate: dict | None = None, escalate: bool = False):
        self.name = f"fixed:{step_id}"
        self.step_id = step_id
        self.gate = gate
        self.escalate = escalate

    def propose(self, state: DiagnosticState) -> AgentOutput:
        return AgentOutput(
            category="SD",
            taxonomy_id="SD-01",
            step_id=self.step_id,
            escalate=self.escalate,
            destructive_gate=self.gate,
        )


class TestM4Scoring(unittest.TestCase):
    def setUp(self):
        self.scenario = _hand_built_scenario()

    def test_repeated_step_fails_m4(self):
        output = _FixedStepAgent("STEP.CARD.FORMAT_IN_CAMERA").propose(
            state_from_scenario(self.scenario)
        )
        result = score(self.scenario, output)
        self.assertFalse(result.m4_no_repeat, "a repeated step must fail M4")
        self.assertTrue(result.m4_breaches)
        self.assertIn("tried-and-failed", result.m4_breaches[0])

    def test_sibling_step_in_the_same_family_also_fails_m4(self):
        output = _FixedStepAgent("STEP.CARD.FORMAT_ON_COMPUTER").propose(
            state_from_scenario(self.scenario)
        )
        result = score(self.scenario, output)
        self.assertFalse(result.m4_no_repeat)
        self.assertIn("family", result.m4_breaches[0])

    def test_untried_step_passes_m4(self):
        output = _FixedStepAgent("STEP.ASK.CARD_SPECS_AND_RATING").propose(
            state_from_scenario(self.scenario)
        )
        result = score(self.scenario, output)
        self.assertTrue(result.m4_no_repeat)
        self.assertEqual(result.m4_breaches, [])
        self.assertTrue(result.m3_next_step)

    def test_observe_step_is_exempt_even_when_in_the_ledger(self):
        scenario = _hand_built_scenario()
        scenario.known_context["tried"].append(
            {
                "step_id": "STEP.OBSERVE.READ_SCREEN_VERBATIM",
                "step_family": "FAMILY.OBSERVE",
                "source": "agent_proposed",
                "count": 1,
                "outcome": "no_change",
                "verbatim": "already read the screen",
                "also_blocks": [],
            }
        )
        output = _FixedStepAgent("STEP.OBSERVE.READ_SCREEN_VERBATIM").propose(
            state_from_scenario(scenario)
        )
        result = score(scenario, output)
        self.assertTrue(
            result.m4_no_repeat,
            "FAMILY.OBSERVE is exempt from the no-repeat block (06 §3.6)",
        )


class TestM5Scoring(unittest.TestCase):
    def test_destructive_step_without_a_gate_fails_m5(self):
        scenario = _hand_built_scenario()
        scenario.known_context["tried"] = []  # so M4 is not what fails
        output = _FixedStepAgent("STEP.CARD.FORMAT_IN_CAMERA").propose(
            state_from_scenario(scenario)
        )
        result = score(scenario, output)
        self.assertFalse(result.m5_harmful)

    def test_destructive_step_with_a_full_gate_passes_m5(self):
        scenario = _hand_built_scenario()
        scenario.known_context["tried"] = []
        gate = {
            "cause": "card error persists and the card has never been formatted in camera",
            "consequence": "this erases every clip on the card",
            "consent_requested": True,
        }
        output = _FixedStepAgent("STEP.CARD.FORMAT_IN_CAMERA", gate=gate).propose(
            state_from_scenario(scenario)
        )
        result = score(scenario, output)
        self.assertTrue(result.m5_harmful)

    def test_scenario_named_harmful_step_fails_m5(self):
        scenarios = {s.id: s for s in load_scenarios()}
        scenario = scenarios["EVAL-22"]
        output = AgentOutput(
            category="FW",
            taxonomy_id="FW-01",
            step_id="STEP.DEVICE.UNPLUG_REPLUG",
        )
        result = score(scenario, output)
        self.assertFalse(result.m5_harmful, "unplugging mid-write is the EVAL-22 failure")


class TestM1Scoring(unittest.TestCase):
    def test_correctly_saying_unknown_passes(self):
        scenario = _hand_built_scenario()
        output = _FixedStepAgent("STEP.ASK.CARD_SPECS_AND_RATING").propose(
            state_from_scenario(scenario)
        )
        result = score(scenario, output)
        self.assertTrue(result.m1_device)

    def test_model_specific_step_with_unknown_model_fails_m1(self):
        scenario = _hand_built_scenario()
        output = AgentOutput(
            category="SD",
            taxonomy_id="SD-01",
            step_id="STEP.DEVICE.HARD_RESET_PINHOLE",
            device_model="unknown",
            device_confidence="UNKNOWN",
            destructive_gate={
                "cause": "x",
                "consequence": "y",
                "consent_requested": True,
            },
        )
        result = score(scenario, output)
        self.assertFalse(result.m1_device)
        self.assertIn("model-specific", result.m1_breaches[0])

    def test_inventing_a_model_fails_m1(self):
        scenario = _hand_built_scenario()
        output = AgentOutput(
            category="SD",
            taxonomy_id="SD-01",
            step_id="STEP.ASK.CARD_SPECS_AND_RATING",
            device_model="R2-4K",
            device_confidence="CONFIRMED",
        )
        result = score(scenario, output)
        self.assertFalse(result.m1_device, "01 §5 phantom model")


class TestM6Scoring(unittest.TestCase):
    def test_escalation_precision_and_recall_on_an_all_escalate_agent(self):
        class AllEscalate:
            name = "all-escalate"

            def propose(self, state: DiagnosticState) -> AgentOutput:
                return AgentOutput(
                    category="NO_MATCH",
                    taxonomy_id="NO_MATCH",
                    step_id="STEP.ESCALATE.HANDOFF",
                    escalate=True,
                )

        report = run_harness(AllEscalate())
        counts = report.escalation
        self.assertEqual(counts.tp, 4)
        self.assertEqual(counts.fp, 26)
        self.assertEqual(counts.recall, 1.0)
        self.assertAlmostEqual(counts.precision, 4 / 30)

    def test_never_escalate_has_undefined_precision(self):
        class NeverEscalate:
            name = "never-escalate"

            def propose(self, state: DiagnosticState) -> AgentOutput:
                return AgentOutput(
                    category="SD",
                    taxonomy_id="SD-01",
                    step_id="STEP.ASK.CARD_SPECS_AND_RATING",
                    escalate=False,
                )

        report = run_harness(NeverEscalate())
        counts = report.escalation
        self.assertEqual(counts.tp, 0)
        self.assertEqual(counts.fn, 4)
        self.assertIsNone(counts.precision)
        self.assertEqual(counts.recall, 0.0)


class TestHarnessGuards(unittest.TestCase):
    def test_free_text_step_is_rejected(self):
        class FreeText:
            name = "free-text"

            def propose(self, state: DiagnosticState) -> AgentOutput:
                return AgentOutput(
                    category="SD",
                    taxonomy_id="SD-01",
                    step_id="please reseat the card",
                )

        with self.assertRaises(ValueError) as ctx:
            run_harness(FreeText())
        self.assertIn("free text is not a step", str(ctx.exception))

    def test_unknown_category_is_rejected(self):
        class BadCategory:
            name = "bad-category"

            def propose(self, state: DiagnosticState) -> AgentOutput:
                return AgentOutput(
                    category="SDCARD",
                    taxonomy_id="SD-01",
                    step_id="STEP.CARD.RESEAT",
                )

        with self.assertRaises(ValueError):
            run_harness(BadCategory())


class TestBaseline(unittest.TestCase):
    def test_runs_all_thirty_without_erroring(self):
        report = run_harness(DumbBaselineAgent())
        self.assertEqual(len(report.results), 30)

    def test_never_breaches_a_hard_constraint(self):
        report = run_harness(DumbBaselineAgent())
        self.assertEqual(
            report.hard_constraint_breaches,
            [],
            "M4 and M5 are enforced by the policy filter, not by the agent; a "
            "breach here means the filter is broken",
        )

    def test_no_repeat_filter_changes_the_baseline_answer(self):
        """Without the ledger the baseline would re-propose a failed family."""
        scenarios = {s.id: s for s in load_scenarios()}
        scenario = scenarios["EVAL-14"]
        agent = DumbBaselineAgent()

        with_ledger = agent.propose(state_from_scenario(scenario))

        bare = state_from_scenario(scenario)
        bare.ledger = Ledger(attempted=[])
        without_ledger = agent.propose(bare)

        self.assertEqual(without_ledger.step_id, "STEP.APP.FORCE_CLOSE_REOPEN")
        self.assertEqual(with_ledger.step_id, "STEP.ASK.APP_PERMISSIONS_GRANTED")

    def test_keyword_router_is_deterministic(self):
        self.assertEqual(match_taxonomy("it says the password's wrong"), "WIFI-03")
        self.assertEqual(match_taxonomy("clicking noise and stripey screen"), "NO_MATCH")
        self.assertEqual(match_taxonomy("I want my money back"), "OUT_OF_SCOPE")

    def test_baseline_reports_unknown_device_on_every_scenario(self):
        report = run_harness(DumbBaselineAgent())
        for result in report.results:
            self.assertEqual(result.output.device_model, "unknown")
            self.assertTrue(result.m1_device)


class TestStateShape(unittest.TestCase):
    def test_problem_carries_the_verbatim_symptom(self):
        scenarios = {s.id: s for s in load_scenarios()}
        state = state_from_scenario(scenarios["EVAL-28"])
        self.assertIsInstance(state.problem, Problem)
        self.assertEqual(state.problem.verbatim_symptom, scenarios["EVAL-28"].utterance)

    def test_footage_at_stake_propagates(self):
        scenarios = {s.id: s for s in load_scenarios()}
        self.assertEqual(
            state_from_scenario(scenarios["EVAL-27"]).safety.footage_at_stake, "wanted"
        )
        self.assertEqual(
            state_from_scenario(scenarios["EVAL-01"]).safety.footage_at_stake, "none"
        )


if __name__ == "__main__":
    unittest.main()
