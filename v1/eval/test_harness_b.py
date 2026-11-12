"""Stdlib unittest for Harness B — the scripted multi-turn harness.

    .venv/bin/python -m unittest eval.test_harness_b -v
    .venv/bin/python -m unittest discover -s eval

No LLM, no AWS, no network. Every agent in here is a hand-written stub that
returns a fixed sequence of steps, which is what makes the *harness* the thing
under test rather than whatever the core happened to say today.

Imports are absolute against a forced `sys.path` entry, for the same reason as
`test_harness.py`: `discover -s eval` imports this file with no parent package.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval import ontology  # noqa: E402
from eval.harness import AgentOutput, Scenario, load_scenarios  # noqa: E402
from eval.harness_b import (  # noqa: E402
    BRANCHING_IDS,
    HARNESS_B_IDS,
    MAX_TURNS,
    MULTI_TURN_IDS,
    OFF_SCRIPT_ACTION,
    OFF_SCRIPT_QUESTION,
    SCRIPTS,
    BaselineDriver,
    Branch,
    Observation,
    Script,
    ScriptedResponder,
    ScriptError,
    branch_matches,
    build_driver,
    format_report_b,
    harness_b_scenarios,
    run_harness_b,
    run_script,
    turn_scenario,
    validate_scripts,
)
from eval.ontology import AttemptedStep  # noqa: E402

_SCENARIOS = {s.id: s for s in load_scenarios()}


# --------------------------------------------------------------------------
# Stub agents. Each is a fixed sequence of (step_id, escalate).
# --------------------------------------------------------------------------


class _FixedSession:
    """Replays a fixed script of its own, holding the last entry if it runs out.

    It keeps **no ledger**: `record_attempt` is a no-op, exactly as the core's
    is. Anything M4 catches here was caught by the harness's own ledger.
    """

    def __init__(self, scenario, steps, *, category, taxonomy_id, resolved=None):
        self.scenario = scenario
        self.steps = list(steps)
        self.category = category
        self.taxonomy_id = taxonomy_id
        self.resolved = resolved
        self.utterances: list[str] = []
        self.recorded: list[AttemptedStep] = []

    def turn(self, utterance: str) -> Observation:
        index = min(len(self.utterances), len(self.steps) - 1)
        self.utterances.append(utterance)
        step_id, escalate = self.steps[index]
        return Observation(
            output=AgentOutput(
                category=self.category,
                taxonomy_id=self.taxonomy_id,
                step_id=step_id,
                escalate=escalate,
            ),
            resolved=self.resolved,
        )

    def record_attempt(self, entry: AttemptedStep) -> None:
        self.recorded.append(entry)


class _FixedDriver:
    def __init__(self, steps, *, category, taxonomy_id, resolved=None, name="fixed"):
        self.name = name
        self.steps = steps
        self.category = category
        self.taxonomy_id = taxonomy_id
        self.resolved = resolved
        self.sessions: list[_FixedSession] = []

    def open(self, scenario: Scenario, session_key: str) -> _FixedSession:
        session = _FixedSession(
            scenario,
            self.steps,
            category=self.category,
            taxonomy_id=self.taxonomy_id,
            resolved=self.resolved,
        )
        self.sessions.append(session)
        return session


def _run(scenario_id: str, branch_name: str, driver, **kwargs):
    script = SCRIPTS[scenario_id]
    return run_script(
        driver, _SCENARIOS[scenario_id], script, script.branch(branch_name), **kwargs
    )


# --------------------------------------------------------------------------
# The script itself
# --------------------------------------------------------------------------


class TestScriptCoverage(unittest.TestCase):
    def test_covers_the_eight_docs_06_section_7_3_names(self):
        self.assertEqual(MULTI_TURN_IDS, ("EVAL-23", "EVAL-26", "EVAL-27"))
        self.assertEqual(
            BRANCHING_IDS, ("EVAL-07", "EVAL-16", "EVAL-17", "EVAL-20", "EVAL-21")
        )
        self.assertEqual(
            HARNESS_B_IDS,
            (
                "EVAL-07",
                "EVAL-16",
                "EVAL-17",
                "EVAL-20",
                "EVAL-21",
                "EVAL-23",
                "EVAL-26",
                "EVAL-27",
            ),
        )
        self.assertEqual(tuple(sorted(SCRIPTS)), HARNESS_B_IDS)

    def test_the_three_multi_turn_ids_are_the_ones_docs_03_marks(self):
        text = (_REPO_ROOT / "docs" / "03-golden-eval-set.md").read_text(
            encoding="utf-8"
        )
        marked = [
            line.split("### ")[1].strip()
            for line in text.splitlines()
            if line.startswith("### EVAL-")
        ]
        multi = [
            eval_id
            for eval_id in marked
            if "*multi-turn*"
            in text.split(f"### {eval_id}\n", 1)[1].split("### ", 1)[0]
        ]
        self.assertEqual(tuple(multi), MULTI_TURN_IDS)

    def test_every_scripted_scenario_is_in_the_golden_set(self):
        selected = harness_b_scenarios()
        self.assertEqual([s.id for s in selected], list(HARNESS_B_IDS))

    def test_validate_passes_on_the_shipped_scripts(self):
        validate_scripts()

    def test_every_branch_cites_a_docs_03_line(self):
        for script in SCRIPTS.values():
            for branch in script.branches:
                self.assertIn(script.scenario_id, branch.source)
                self.assertTrue(branch.reply.strip())

    def test_the_branching_question_is_a_real_step(self):
        for script in SCRIPTS.values():
            for step_id in script.question_step_ids:
                self.assertIn(step_id, ontology.STEPS)

    def test_only_eval_27_has_branches_a_signature_cannot_tell_apart(self):
        """Where two branches share a signature, the branch check degrades to
        "did it re-ask the question it just got answered" and can say nothing
        about *which* reading the agent took.

        EVAL-27 is the one script where that is true, and it is not a defect in
        the script: `docs/03` gives EVAL-27 a single expected outcome ("No
        escalation. Likely card replacement...") for both readings of the card,
        so there is no escalation, category or resolution difference to observe.
        Inventing one would be grading an expectation `docs/03` does not state.
        Pinned here so that a *second* script drifting into the same state is a
        test failure rather than a silent loss of coverage.
        """
        shared = set()
        for script in SCRIPTS.values():
            signatures = {
                (b.escalate, b.categories, b.forbidden_step_ids, b.resolved)
                for b in script.branches
            }
            if len(signatures) != len(script.branches):
                shared.add(script.scenario_id)
        self.assertEqual(shared, {"EVAL-27"})


class TestScriptValidation(unittest.TestCase):
    """`validate_scripts` has to bite, or it is decoration."""

    def _one(self, **changes) -> dict[str, Script]:
        script = SCRIPTS["EVAL-07"]
        return {"EVAL-07": replace(script, **changes)} if changes else {"EVAL-07": script}

    def test_wrong_id_set_is_rejected(self):
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(self._one())
        self.assertIn("Harness B covers", str(ctx.exception))

    def test_unknown_branching_step_is_rejected(self):
        scripts = dict(SCRIPTS)
        scripts["EVAL-07"] = replace(
            SCRIPTS["EVAL-07"], question_step_ids=("STEP.ASK.NOT_A_REAL_STEP",)
        )
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(scripts)
        self.assertIn("is not a step", str(ctx.exception))

    def test_single_branch_is_rejected(self):
        scripts = dict(SCRIPTS)
        scripts["EVAL-07"] = replace(
            SCRIPTS["EVAL-07"], branches=SCRIPTS["EVAL-07"].branches[:1]
        )
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(scripts)
        self.assertIn("at least two outcomes", str(ctx.exception))

    def test_unknown_outcome_is_rejected(self):
        scripts = dict(SCRIPTS)
        branches = SCRIPTS["EVAL-07"].branches
        scripts["EVAL-07"] = replace(
            SCRIPTS["EVAL-07"],
            branches=(replace(branches[0], outcome="went_fine"), branches[1]),
        )
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(scripts)
        self.assertIn("went_fine", str(ctx.exception))

    def test_uncited_branch_is_rejected(self):
        scripts = dict(SCRIPTS)
        branches = SCRIPTS["EVAL-07"].branches
        scripts["EVAL-07"] = replace(
            SCRIPTS["EVAL-07"], branches=(replace(branches[0], source=" "), branches[1])
        )
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(scripts)
        self.assertIn("cites no docs/03 line", str(ctx.exception))

    def test_step_outside_the_ontology_is_rejected(self):
        scripts = dict(SCRIPTS)
        branches = SCRIPTS["EVAL-07"].branches
        scripts["EVAL-07"] = replace(
            SCRIPTS["EVAL-07"],
            branches=(
                replace(branches[0], forbidden_step_ids=("STEP.MADE.UP",)),
                branches[1],
            ),
        )
        with self.assertRaises(ScriptError) as ctx:
            validate_scripts(scripts)
        self.assertIn("not in the ontology", str(ctx.exception))

    def test_missing_scenario_is_reported(self):
        thinned = [s for s in load_scenarios() if s.id != "EVAL-23"]
        with self.assertRaises(ScriptError) as ctx:
            harness_b_scenarios(thinned)
        self.assertIn("EVAL-23", str(ctx.exception))


# --------------------------------------------------------------------------
# The responder
# --------------------------------------------------------------------------


class TestScriptedResponder(unittest.TestCase):
    def setUp(self):
        self.script = SCRIPTS["EVAL-16"]
        self.branch = self.script.branch("drops_mid_transfer")

    def test_plays_the_branch_reply_when_the_question_is_asked(self):
        responder = ScriptedResponder(self.script, self.branch)
        reply = responder.reply_to("STEP.ASK.DROP_IDLE_OR_ACTIVE", 1)
        self.assertTrue(reply.on_script)
        self.assertEqual(reply.text, self.branch.reply)
        self.assertEqual(reply.outcome, self.branch.outcome)
        self.assertEqual(reply.branch_name, "drops_mid_transfer")
        self.assertEqual(responder.answered_at_turn, 1)

    def test_plays_the_branch_reply_only_once(self):
        responder = ScriptedResponder(self.script, self.branch)
        responder.reply_to("STEP.ASK.DROP_IDLE_OR_ACTIVE", 1)
        again = responder.reply_to("STEP.ASK.DROP_IDLE_OR_ACTIVE", 2)
        self.assertFalse(again.on_script)
        self.assertEqual(again.text, OFF_SCRIPT_QUESTION[0])
        self.assertEqual(responder.answered_at_turn, 1)

    def test_off_script_question_and_action_replies_differ(self):
        responder = ScriptedResponder(self.script, self.branch)
        question = responder.reply_to("STEP.ASK.PHONE_OS_AND_VERSION", 1)
        action = responder.reply_to("STEP.PHONE.MOVE_CLOSER_TO_CAMERA", 2)
        self.assertEqual((question.text, question.outcome), OFF_SCRIPT_QUESTION)
        self.assertEqual((action.text, action.outcome), OFF_SCRIPT_ACTION)
        self.assertFalse(question.on_script)
        self.assertFalse(action.on_script)

    def test_no_step_gets_an_empty_reply(self):
        responder = ScriptedResponder(self.script, self.branch)
        reply = responder.reply_to(None, 1)
        self.assertEqual(reply.text, "")
        self.assertFalse(reply.on_script)

    def test_is_deterministic(self):
        sequence = [
            "STEP.ASK.PHONE_OS_AND_VERSION",
            "STEP.ASK.DROP_IDLE_OR_ACTIVE",
            "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
            "STEP.ASK.DROP_IDLE_OR_ACTIVE",
        ]
        runs = []
        for _ in range(2):
            responder = ScriptedResponder(self.script, self.branch)
            runs.append(
                [responder.reply_to(s, i).text for i, s in enumerate(sequence, 1)]
            )
        self.assertEqual(runs[0], runs[1])

    def test_either_branching_question_unlocks_a_two_question_script(self):
        script = SCRIPTS["EVAL-23"]
        branch = script.branch("camera_restarts_in_heat")
        for step_id in script.question_step_ids:
            responder = ScriptedResponder(script, branch)
            self.assertTrue(responder.reply_to(step_id, 1).on_script, step_id)


# --------------------------------------------------------------------------
# Branch classification
# --------------------------------------------------------------------------


def _obs(step_id, *, escalate=False, category="WIFI", resolved=None) -> Observation:
    return Observation(
        output=AgentOutput(
            category=category,
            taxonomy_id="WIFI-04",
            step_id=step_id,
            escalate=escalate,
        ),
        resolved=resolved,
    )


class TestBranchMatching(unittest.TestCase):
    def setUp(self):
        self.branch = SCRIPTS["EVAL-16"].branch("drops_mid_transfer")

    def test_matching_signature_matches(self):
        self.assertTrue(
            branch_matches(self.branch, _obs("STEP.ESCALATE.HANDOFF", escalate=True))
        )

    def test_wrong_escalation_does_not_match(self):
        self.assertFalse(branch_matches(self.branch, _obs("STEP.ESCALATE.HANDOFF")))

    def test_wrong_category_does_not_match(self):
        self.assertFalse(
            branch_matches(
                self.branch,
                _obs("STEP.ESCALATE.HANDOFF", escalate=True, category="PWR"),
            )
        )

    def test_a_forbidden_step_proves_the_answer_was_ignored(self):
        self.assertFalse(
            branch_matches(
                self.branch, _obs("STEP.ASK.DROP_IDLE_OR_ACTIVE", escalate=True)
            )
        )

    def test_m3_steps_never_classify_a_branch(self):
        """A different-but-legal next step is an M3 miss, not a branch failure."""
        branch = SCRIPTS["EVAL-26"].branch("permission_declined")
        self.assertIsNotNone(branch.step_ids)
        self.assertTrue(
            branch_matches(
                branch,
                _obs(
                    "STEP.ASK.APP_PERMISSIONS_GRANTED", category="APP", resolved=False
                ),
            )
        )

    def test_resolution_is_skipped_when_the_driver_cannot_observe_it(self):
        branch = SCRIPTS["EVAL-26"].branch("permission_granted")
        self.assertIs(branch.resolved, True)
        self.assertTrue(branch_matches(branch, _obs(None, category="APP")))
        self.assertFalse(
            branch_matches(branch, _obs(None, category="APP", resolved=False))
        )


# --------------------------------------------------------------------------
# Building the per-turn scenario
# --------------------------------------------------------------------------


class TestTurnScenario(unittest.TestCase):
    def test_replaces_the_ledger_and_the_expectation(self):
        scenario = _SCENARIOS["EVAL-17"]
        branch = SCRIPTS["EVAL-17"].branch("correctly_rated_card")
        entry = AttemptedStep(
            step_id="STEP.CARD.RESEAT",
            step_family="FAMILY.CARD_HANDLING",
            source="agent_proposed",
            outcome="no_change",
        )
        built = turn_scenario(
            scenario,
            [entry],
            categories=branch.categories,
            step_ids=branch.step_ids,
            escalate=branch.escalate,
        )
        self.assertEqual(
            [e.step_id for e in built.ledger], ["STEP.CARD.RESEAT"]
        )
        self.assertEqual(built.expected_category, ["SD"])
        self.assertEqual(built.expected_step_ids, [None, "STEP.ESCALATE.HANDOFF"])
        self.assertTrue(built.escalation_expected)

    def test_keeps_everything_the_scenario_says_about_safety(self):
        scenario = _SCENARIOS["EVAL-27"]
        built = turn_scenario(scenario, [])
        self.assertEqual(built.harmful_steps, scenario.harmful_steps)
        self.assertEqual(built.footage_at_stake, scenario.footage_at_stake)
        self.assertEqual(built.driving, scenario.driving)
        self.assertEqual(built.id, scenario.id)

    def test_does_not_mutate_the_scenario_it_was_given(self):
        scenario = _SCENARIOS["EVAL-20"]
        before = list(scenario.known_context.get("tried", []))
        turn_scenario(
            scenario,
            [
                AttemptedStep(
                    step_id="STEP.CARD.RESEAT",
                    step_family="FAMILY.CARD_HANDLING",
                    source="agent_proposed",
                    outcome="no_change",
                )
            ],
            categories=("SD",),
        )
        self.assertEqual(scenario.known_context.get("tried", []), before)
        self.assertEqual(scenario.expected_category, ["PWR"])


# --------------------------------------------------------------------------
# Driving a conversation
# --------------------------------------------------------------------------


class TestRunScript(unittest.TestCase):
    def test_an_agent_that_acts_on_the_answer_passes(self):
        driver = _FixedDriver(
            [("STEP.ASK.DROP_IDLE_OR_ACTIVE", False), ("STEP.ESCALATE.HANDOFF", True)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertEqual(run.question_asked_at, 1)
        self.assertEqual(run.branch_turn_index, 2)
        self.assertEqual(run.branch_implied, "drops_mid_transfer")
        self.assertEqual(run.branch_taken, "drops_mid_transfer")
        self.assertTrue(run.branch_pass)
        self.assertTrue(run.hard_constraints_held)
        self.assertTrue(run.passed)

    def test_an_agent_that_ignores_the_answer_fails_the_branch(self):
        driver = _FixedDriver(
            [("STEP.ASK.DROP_IDLE_OR_ACTIVE", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertEqual(run.question_asked_at, 1)
        self.assertEqual(run.branch_turn_index, 2)
        self.assertFalse(run.branch_pass)
        self.assertFalse(run.passed)
        self.assertIn("which the answer rules out", run.branch_detail)

    def test_taking_the_other_branch_is_named(self):
        driver = _FixedDriver(
            [("STEP.ASK.DROP_IDLE_OR_ACTIVE", False), (None, False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertFalse(run.branch_pass)
        self.assertEqual(run.branch_taken, "idle_only")
        self.assertIn("looks like branch idle_only", run.branch_detail)

    def test_never_asking_cannot_pass(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertIsNone(run.question_asked_at)
        self.assertIsNone(run.branch_turn_index)
        self.assertIsNone(run.branch_implied)
        self.assertFalse(run.branch_pass)
        self.assertIn("never asked the branching question", run.branch_detail)
        self.assertEqual(len(run.turns), MAX_TURNS)

    def test_a_late_question_still_gets_its_branch_turn(self):
        driver = _FixedDriver(
            [
                ("STEP.ASK.PHONE_OS_AND_VERSION", False),
                ("STEP.ASK.DROP_IDLE_OR_ACTIVE", False),
                ("STEP.ESCALATE.HANDOFF", True),
            ],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertEqual(run.question_asked_at, 2)
        self.assertEqual(run.branch_turn_index, 3)
        self.assertTrue(run.branch_pass)

    def test_turn_roles_are_opening_branch_follow_up(self):
        driver = _FixedDriver(
            [
                ("STEP.ASK.DROP_IDLE_OR_ACTIVE", False),
                ("STEP.ASK.PHONE_OS_AND_VERSION", False),
                ("STEP.ASK.PHONE_OS_AND_VERSION", False),
            ],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertEqual([t.role for t in run.turns][:3], ["opening", "branch", "follow-up"])

    def test_escalating_ends_the_conversation(self):
        driver = _FixedDriver(
            [("STEP.ESCALATE.HANDOFF", True)], category="WIFI", taxonomy_id="WIFI-04"
        )
        run = _run("EVAL-16", "idle_only", driver)
        self.assertEqual(len(run.turns), 1)

    def test_no_step_ends_the_conversation(self):
        driver = _FixedDriver([(None, False)], category="WIFI", taxonomy_id="WIFI-04")
        run = _run("EVAL-16", "idle_only", driver)
        self.assertEqual(len(run.turns), 1)

    def test_max_turns_is_honoured(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "idle_only", driver, max_turns=2)
        self.assertEqual(len(run.turns), 2)

    def test_the_scripted_reply_becomes_the_next_utterance(self):
        driver = _FixedDriver(
            [("STEP.ASK.DROP_IDLE_OR_ACTIVE", False), ("STEP.ESCALATE.HANDOFF", True)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "idle_only", driver)
        self.assertEqual(run.turns[0].utterance, _SCENARIOS["EVAL-16"].utterance)
        self.assertEqual(
            run.turns[1].utterance, SCRIPTS["EVAL-16"].branch("idle_only").reply
        )


class TestIndependentLedger(unittest.TestCase):
    """M4 is scored against the harness's ledger, never the agent's."""

    def test_a_repeat_across_turns_fails_m4_even_with_no_agent_ledger(self):
        driver = _FixedDriver(
            [("STEP.SETTINGS.CHECK_GSENSOR_SENSITIVITY", False)],
            category="REC",
            taxonomy_id="REC-03",
        )
        run = _run("EVAL-07", "clips_were_ordinary", driver)
        self.assertEqual(driver.sessions[0].recorded and True, True)
        self.assertTrue(run.turns[0].result.m4_no_repeat, "turn 1 is not a repeat")
        self.assertFalse(run.turns[1].result.m4_no_repeat, "turn 2 is")
        self.assertTrue(run.m4_breaches)
        self.assertFalse(run.hard_constraints_held)
        self.assertFalse(run.passed)

    def test_the_harness_ledger_grows_turn_by_turn(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "idle_only", driver)
        sizes = [len(t.ledger_before) for t in run.turns]
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(sizes[-1] - sizes[0], len(run.turns) - 1)

    def test_ask_steps_stay_exempt_across_turns(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "idle_only", driver)
        self.assertTrue(all(t.result.m4_no_repeat for t in run.turns))
        self.assertEqual(run.m4_breaches, [])


class TestGradedMetrics(unittest.TestCase):
    def test_a_follow_up_turn_is_graded_on_hard_constraints_only(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "idle_only", driver)
        follow_ups = [t for t in run.turns if t.role == "follow-up"]
        self.assertTrue(follow_ups)
        for turn in follow_ups:
            self.assertEqual(turn.graded, ("m1_device", "m4_no_repeat", "m5_harmful"))
            self.assertFalse(turn.graded_m6)

    def test_the_opening_turn_is_graded_on_everything(self):
        driver = _FixedDriver(
            [("STEP.ASK.DROP_IDLE_OR_ACTIVE", False), ("STEP.ESCALATE.HANDOFF", True)],
            category="WIFI",
            taxonomy_id="WIFI-04",
        )
        run = _run("EVAL-16", "drops_mid_transfer", driver)
        self.assertEqual(
            run.turns[0].graded,
            (
                "m1_device",
                "m2_category",
                "m3_next_step",
                "m4_no_repeat",
                "m5_harmful",
            ),
        )
        self.assertTrue(run.turns[0].graded_m6)

    def test_a_branch_docs_03_names_no_step_for_is_not_graded_on_m3(self):
        branch = SCRIPTS["EVAL-17"].branch("ordinary_consumer_card")
        self.assertIsNone(branch.step_ids)
        driver = _FixedDriver(
            [("STEP.ASK.CARD_SPECS_AND_RATING", False), ("STEP.CARD.RESEAT", False)],
            category="SD",
            taxonomy_id="SD-04",
        )
        run = _run("EVAL-17", "ordinary_consumer_card", driver)
        branch_turn = run.turns[run.branch_turn_index - 1]
        self.assertNotIn("m3_next_step", branch_turn.graded)
        self.assertIn("m2_category", branch_turn.graded)


class TestContractGuards(unittest.TestCase):
    def test_free_text_is_not_a_step(self):
        driver = _FixedDriver(
            [("please reseat the card", False)], category="WIFI", taxonomy_id="WIFI-04"
        )
        with self.assertRaises(ValueError) as ctx:
            _run("EVAL-16", "idle_only", driver)
        self.assertIn("free text is not a step", str(ctx.exception))

    def test_unknown_category_is_rejected(self):
        driver = _FixedDriver(
            [("STEP.ASK.PHONE_OS_AND_VERSION", False)],
            category="WIFIX",
            taxonomy_id="WIFI-04",
        )
        with self.assertRaises(ValueError):
            _run("EVAL-16", "idle_only", driver)


# --------------------------------------------------------------------------
# The set, the drivers and the report
# --------------------------------------------------------------------------


class TestRunHarnessB(unittest.TestCase):
    def setUp(self):
        self.report = run_harness_b(BaselineDriver())

    def test_runs_every_branch_of_every_scenario(self):
        self.assertEqual(len(self.report.runs), 16)
        self.assertEqual(
            len({r.scenario_id for r in self.report.runs}), len(HARNESS_B_IDS)
        )
        for scenario_id in HARNESS_B_IDS:
            branches = [r.branch_name for r in self.report.runs if r.scenario_id == scenario_id]
            self.assertEqual(
                sorted(branches), sorted(b.name for b in SCRIPTS[scenario_id].branches)
            )

    def test_the_baseline_breaches_no_hard_constraint(self):
        self.assertEqual(self.report.m4_breaches, [])
        self.assertEqual(
            self.report.m5_breaches,
            [],
            "M4/M5 are enforced by the policy filter; a breach here means the "
            "filter is broken, not that the agent is weak",
        )

    def test_a_scenario_passes_only_if_every_branch_does(self):
        verdicts = self.report.scenario_verdicts()
        self.assertEqual(sorted(verdicts), sorted(HARNESS_B_IDS))
        for scenario_id, ok in verdicts.items():
            runs = [r for r in self.report.runs if r.scenario_id == scenario_id]
            self.assertEqual(ok, all(r.passed for r in runs), scenario_id)

    def test_the_floor_cannot_follow_a_branch(self):
        """The reason Harness B exists: a keyword router has no memory of its
        own question, so it should not be able to clear the branch check."""
        self.assertLess(self.report.branch_passes, len(self.report.runs))

    def test_is_deterministic(self):
        again = run_harness_b(BaselineDriver())
        self.assertEqual(
            [(r.scenario_id, r.branch_name, r.branch_pass) for r in self.report.runs],
            [(r.scenario_id, r.branch_name, r.branch_pass) for r in again.runs],
        )

    def test_a_single_scenario_can_be_run_alone(self):
        report = run_harness_b(BaselineDriver(), scripts={"EVAL-23": SCRIPTS["EVAL-23"]})
        self.assertEqual(len(report.runs), 2)
        self.assertEqual({r.scenario_id for r in report.runs}, {"EVAL-23"})

    def test_report_names_every_section(self):
        text = format_report_b(self.report, transcripts=True)
        for heading in (
            "Branch check",
            "M1–M5 across the multi-turn runs",
            "M6 escalation correctness",
            "Hard-constraint breaches",
            "Per-scenario verdict",
            "Phase 1 exit",
            "Transcripts:",
        ):
            self.assertIn(heading, text)
        self.assertNotIn("\nALL 16", text, "06 §7.3: no aggregate M1–M5 row")

    def test_report_has_no_aggregate_m1_to_m5_row(self):
        text = format_report_b(self.report)
        table = text.split("M1–M5 across")[1].split("No aggregate row")[0]
        for part in self.report.parts:
            self.assertIn(part, table)
        self.assertNotIn("ALL", table)


class TestDriverFactory(unittest.TestCase):
    def test_dumb_is_the_default(self):
        self.assertEqual(build_driver().name, "dumb-rule-based-baseline")

    def test_dumb_takes_no_options(self):
        with self.assertRaises(TypeError):
            build_driver("dumb", llm=object())

    def test_unknown_driver_is_rejected(self):
        with self.assertRaises(ValueError):
            build_driver("clairvoyant")

    def test_core_is_constructible_without_touching_aws(self):
        from agent.llm import NullLLM

        driver = build_driver("core", llm=NullLLM())
        self.assertEqual(driver.name, "core-text-diagnostic")

    def test_the_baseline_session_is_given_the_whole_transcript(self):
        driver = BaselineDriver()
        session = driver.open(_SCENARIOS["EVAL-16"], "key")
        session.turn("first")
        session.turn("second")
        self.assertEqual(session.state.problem.verbatim_symptom, "first second")

    def test_the_baseline_session_takes_the_harness_ledger(self):
        driver = BaselineDriver()
        session = driver.open(_SCENARIOS["EVAL-16"], "key")
        before = len(session.ledger)
        session.record_attempt(
            AttemptedStep(
                step_id="STEP.CARD.RESEAT",
                step_family="FAMILY.CARD_HANDLING",
                source="agent_proposed",
                outcome="no_change",
            )
        )
        self.assertEqual(len(session.ledger), before + 1)


class TestNoScoringDrift(unittest.TestCase):
    def test_harness_b_scores_through_harness_a(self):
        """One implementation of M1–M6 in the repository, not two."""
        import eval.harness as harness_a
        import eval.harness_b as harness_b

        self.assertIs(harness_b.score, harness_a.score)

    def test_a_branch_declares_only_what_docs_03_says(self):
        """`step_ids=None` and `escalate=None` mean *not graded*, not *False*."""
        branch = Branch(
            name="x",
            reply="y",
            outcome="unclear",
            source="03 EVAL-00 expected outcome: 'z'",
        )
        self.assertIsNone(branch.escalate)
        self.assertIsNone(branch.categories)
        self.assertIsNone(branch.step_ids)
        self.assertIsNone(branch.resolved)
        self.assertEqual(branch.forbidden_step_ids, ())


if __name__ == "__main__":
    unittest.main()
