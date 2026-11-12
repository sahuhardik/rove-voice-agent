"""The intake agent's regression battery (Milestone 6.7).

    .venv/bin/python -m unittest eval.test_intake -v

A vague symptom used to be treated as "cannot help": triage found no taxonomy
entry, returned `NO_MATCH`, and the policy escalated on turn 1. The intake agent
(`agent/intake.py`) asks instead. Every test here drives a real turn through
`core.diagnose` -- router, LangGraph, policy, guard -- with `NullLLM`, so it
asserts the deterministic floor and needs no network or AWS.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import core, intake, policy, router  # noqa: E402
from agent.llm import NullLLM  # noqa: E402
from agent.state import DiagnosticState  # noqa: E402
from eval import ontology  # noqa: E402
from eval import probe_battery  # noqa: E402
from eval.harness import load_scenarios  # noqa: E402

_FORBIDDEN_IN_REPLY = (
    "EVAL-", "§", "taxonomy", "NO_MATCH", "OUT_OF_SCOPE", "STEP.",
    "FAMILY.", "triage", "shortlist", "slot",
)

VAGUE_UTTERANCES = (
    "I don't know for some reason my camera is not working.",
    "My camera is not working.",
    "Something is wrong with my dashcam.",
    "It is broken.",
    "Help, my camera.",
)


class Session:
    """One caller, one state, several turns."""

    def __init__(self, name: str) -> None:
        self.state = DiagnosticState(session_id=name)
        self.name = name
        self.results: list[core.TurnResult] = []

    def say(self, utterance: str) -> core.TurnResult:
        result = core.diagnose(
            utterance, self.state, llm=NullLLM(), thread_id=self.name
        )
        self.results.append(result)
        return result


def _assert_clean(case: unittest.TestCase, result: core.TurnResult) -> None:
    for marker in _FORBIDDEN_IN_REPLY:
        case.assertNotIn(marker, result.response_text)


class VagueSymptomsAskInsteadOfEscalating(unittest.TestCase):
    def test_a_vague_symptom_is_asked_about_and_not_escalated_on_turn_1(self) -> None:
        for utterance in VAGUE_UTTERANCES:
            with self.subTest(utterance=utterance):
                result = Session(f"v-{utterance[:12]}").say(utterance)
                self.assertFalse(result.escalate, result.rationale)
                self.assertNotEqual(result.step_id, "STEP.ESCALATE.HANDOFF")
                self.assertTrue(
                    result.response_text.rstrip().endswith("?"),
                    f"no question: {result.response_text!r}",
                )
                _assert_clean(self, result)

    def test_the_first_question_asks_which_camera(self) -> None:
        for utterance in VAGUE_UTTERANCES:
            with self.subTest(utterance=utterance):
                result = Session(f"w-{utterance[:12]}").say(utterance)
                self.assertIn("Rove camera", result.response_text)

    def test_the_vague_turn_leaves_no_taxonomy_entry_in_the_record(self) -> None:
        """Recording NO_MATCH would escalate the next turn out of the tree."""
        session = Session("rec")
        session.say("Something is wrong with my dashcam.")
        self.assertFalse(session.state.problem.taxonomy_id)
        self.assertFalse(session.state.escalation.triggered)



class NoDashcamMentionIsNotAskedAbout(unittest.TestCase):
    """Finish fix (Milestone 6.7): the intake agent must not ask "which Rove
    camera is this?" for a turn that is not about a dashcam. The router's
    SYMPTOM intent is a catch-all, so a weather question, a joke, or the
    capital of France reaches intake as NO_MATCH; those must escalate, not
    open a question tree."""

    def test_out_of_scope_questions_escalate_and_never_ask_which_camera(self) -> None:
        for utterance in (
            "What is the weather today like?",
            "Tell me a joke.",
            "What is the capital of France?",
        ):
            with self.subTest(utterance=utterance):
                result = Session(f"oos-{utterance[:12]}").say(utterance)
                self.assertTrue(result.escalate, result.rationale)
                self.assertEqual(result.step_id, "STEP.ESCALATE.HANDOFF")
                self.assertNotIn("Rove camera", result.response_text)


    def test_an_unclear_fragment_is_asked_what_they_need_not_escalated(self) -> None:
        """Finish fix (Milestone 6.7, revised): a fragment such as "what you
        needed" has no dashcam mention and is not a well-formed question about
        something else, so it is unclear, not out-of-scope. It must be asked
        what they need help with, not handed to a human."""
        result = Session("unclear").say("what you needed")
        self.assertFalse(result.escalate, result.rationale)
        self.assertIn("what you need help with", result.response_text)
        self.assertNotIn("Rove camera", result.response_text)

    def test_a_clear_question_about_something_else_still_escalates(self) -> None:
        """The same gate must not swallow a well-formed question about
        something else: those still escalate, and never ask which camera."""
        for utterance in (
            "What is the weather today like?",
            "Tell me a joke.",
            "What is the capital of France?",
        ):
            with self.subTest(utterance=utterance):
                result = Session(f"clr-{utterance[:12]}").say(utterance)
                self.assertTrue(result.escalate, result.rationale)
                self.assertEqual(result.step_id, "STEP.ESCALATE.HANDOFF")
                self.assertNotIn("Rove camera", result.response_text)

    def test_the_clarifying_question_leads_into_the_tree(self) -> None:
        """After the generic clarifying question, the next turn -- a real
        symptom -- starts the normal tree (asks which camera)."""
        session = Session("clarify-tree")
        first = session.say("what you needed")
        self.assertIn("what you need help with", first.response_text)
        second = session.say("my camera is not working")
        self.assertFalse(second.escalate, second.rationale)
        self.assertIn("Rove camera", second.response_text)


    def test_the_gate_is_in_the_policy_not_just_the_tree(self) -> None:
        """intake_can_ask must refuse a turn with no dashcam context *that is
        clearly out-of-scope*, so the escalation is never deferred to a tree
        that will decline to ask. An unclear turn (no dashcam context, not
        clearly out-of-scope) is allowed through, so the intake agent can ask
        what they need."""
        state = DiagnosticState(session_id="gate")
        self.assertFalse(
            policy.intake_can_ask(
                state,
                has_dashcam_context=False,
                is_clear_out_of_scope=True,
            )
        )
        self.assertTrue(
            policy.intake_can_ask(
                state,
                has_dashcam_context=False,
                is_clear_out_of_scope=False,
            )
        )
        self.assertTrue(
            policy.intake_can_ask(state, has_dashcam_context=True)
        )


class TheQuestionTreeBranchesOnTheAnswers(unittest.TestCase):
    def test_model_then_area_then_symptom_then_diagnosis(self) -> None:
        session = Session("tree")
        first = session.say("Something is wrong with my dashcam.")
        self.assertIn("Rove camera", first.response_text)

        second = session.say("It's an R2-4K.")
        self.assertFalse(second.escalate)
        self.assertNotIn("Rove camera", second.response_text)
        self.assertIn("Wi-Fi", second.response_text)
        self.assertIn("SD card", second.response_text)

        third = session.say("It's the Wi-Fi.")
        self.assertFalse(third.escalate)
        self.assertIn("goes back to normal internet", third.response_text)
        self.assertIn("nothing in my list", third.response_text)
        self.assertNotIn("Rove camera", third.response_text)

        fourth = session.say("My phone connects for a second then goes back to normal internet.")
        self.assertFalse(fourth.escalate)
        self.assertEqual(fourth.taxonomy_id, "WIFI-01")
        self.assertTrue(fourth.step_id)
        self.assertNotEqual(fourth.step_id, "STEP.ESCALATE.HANDOFF")
        _assert_clean(self, fourth)

    def test_the_area_and_symptom_turns_each_ask_exactly_one_question(self) -> None:
        """The model turn is excluded: its text is the router's existing ladder
        question, which is one question put in two parts."""
        session = Session("one")
        session.say("Something is wrong with my dashcam.")
        replies = [session.say("It's an R2-4K."), session.say("It's the Wi-Fi.")]
        for result in replies:
            self.assertEqual(result.response_text.count("?"), 1, result.response_text)

    def test_the_ladder_answer_fills_the_model_slot(self) -> None:
        session = Session("ladder")
        session.say("Something is wrong with my dashcam.")
        second = session.say("It has two lenses and buttons.")
        self.assertNotIn("Rove camera", second.response_text)
        self.assertIn("SD card", second.response_text)
        self.assertTrue(session.state.device.evidence)

    def test_an_ordinal_answer_picks_the_listed_symptom(self) -> None:
        session = Session("ordinal")
        session.say("Something is wrong with my dashcam.")
        session.say("It's an R2-4K.")
        session.say("It's the Wi-Fi.")
        result = session.say("The second one.")
        self.assertEqual(result.taxonomy_id, "WIFI-02")
        self.assertFalse(result.escalate)

    def test_the_area_can_be_given_with_the_model_in_one_answer(self) -> None:
        session = Session("both")
        session.say("Something is wrong with my dashcam.")
        result = session.say("It's an R2-4K and it won't record.")
        self.assertEqual(result.taxonomy_id, "REC-02")
        self.assertFalse(result.escalate)

    def test_a_specific_answer_hands_off_without_asking_the_model_again(self) -> None:
        session = Session("skip")
        session.say("Something is wrong with my dashcam.")
        result = session.say("It won't record anything.")
        self.assertEqual(result.taxonomy_id, "REC-02")
        self.assertNotIn("Rove camera", result.response_text)


class FilledSlotsAreNotAskedAgain(unittest.TestCase):
    def test_a_named_model_and_symptom_go_straight_to_diagnosis(self) -> None:
        result = Session("p1").say("My R2-4K won't turn on.")
        self.assertEqual(result.taxonomy_id, "PWR-01")
        self.assertNotIn("Rove camera", result.response_text)
        self.assertFalse(result.escalate)

    def test_a_named_model_with_a_vague_symptom_asks_only_for_the_area(self) -> None:
        result = Session("p2").say("My R2-4K is not working.")
        self.assertFalse(result.escalate)
        self.assertNotIn("Rove camera", result.response_text)
        self.assertIn("SD card", result.response_text)

    def test_a_missing_model_is_asked_for_when_the_symptom_is_given(self) -> None:
        utterance = "My dashcam won't connect to Wi-Fi."
        result = Session("p3").say(utterance)
        self.assertFalse(result.escalate)
        self.assertIn("Rove camera", result.response_text)
        # The symptom is given, so it is not asked for.
        self.assertNotIn("SD card", result.response_text)
        self.assertNotIn("goes back to normal internet", result.response_text)


class TheOpeningWordsArePreFilled(unittest.TestCase):
    def test_a_symptom_in_the_first_words_survives_the_model_question(self) -> None:
        """"It won't turn on" -> "which camera?" -> "R2-4K" must diagnose the
        power fault, not ask what is wrong a second time."""
        session = Session("pre1")
        first = session.say("It won't turn on.")
        self.assertIn("Rove camera", first.response_text)
        second = session.say("It's an R2-4K.")
        self.assertEqual(second.taxonomy_id, "PWR-01")
        self.assertFalse(second.escalate)

    def test_a_caller_who_cannot_name_the_model_is_still_helped(self) -> None:
        session = Session("pre2")
        session.say("It won't turn on.")
        session.say("I don't know")
        result = session.say("no idea")
        self.assertEqual(result.taxonomy_id, "PWR-01")
        self.assertFalse(result.escalate)


class GivingUp(unittest.TestCase):
    def test_two_unanswered_model_questions_move_on_to_the_area(self) -> None:
        session = Session("g1")
        session.say("Something is wrong with my dashcam.")
        again = session.say("I don't know")
        self.assertFalse(again.escalate)
        self.assertIn("Rove camera", again.response_text)  # asked a second time
        moved_on = session.say("I don't know")
        self.assertFalse(moved_on.escalate)
        self.assertNotIn("Rove camera", moved_on.response_text)
        self.assertIn("SD card", moved_on.response_text)

    def test_two_unanswered_area_questions_hand_over_to_a_person(self) -> None:
        session = Session("g2")
        session.say("My R2-4K is not working.")
        first_miss = session.say("I don't know")
        self.assertFalse(first_miss.escalate)
        self.assertIn("SD card", first_miss.response_text)
        second_miss = session.say("no idea")
        self.assertTrue(second_miss.escalate)
        self.assertEqual(second_miss.step_id, "STEP.ESCALATE.HANDOFF")
        self.assertTrue(session.state.escalation.triggered)

    def test_none_of_those_is_an_honest_dead_end_not_a_loop(self) -> None:
        session = Session("g3")
        session.say("My R2-4K is not working.")
        result = session.say("None of those, it's something else.")
        self.assertTrue(result.escalate)

    def test_an_answer_resets_the_count(self) -> None:
        session = Session("g4")
        session.say("My R2-4K is not working.")
        session.say("I don't know")
        result = session.say("It's the Wi-Fi.")
        self.assertFalse(result.escalate)
        self.assertIn("goes back to normal internet", result.response_text)


class EscalationPathsAreUntouched(unittest.TestCase):
    def test_a_person_is_still_a_person(self) -> None:
        self.assertTrue(Session("h1").say("I want to talk to a human").escalate)

    def test_a_person_mid_intake_still_escalates(self) -> None:
        session = Session("h2")
        session.say("Something is wrong with my dashcam.")
        self.assertTrue(session.say("Can I speak to a real person please?").escalate)

    def test_out_of_scope_still_routes_out(self) -> None:
        for utterance in (
            "I want a refund for this camera.",
            "My Garmin dash cam will not turn on.",
            "My fridge is making a clicking noise.",
        ):
            with self.subTest(utterance=utterance):
                self.assertTrue(Session(f"o-{utterance[:8]}").say(utterance).escalate)

    def test_small_talk_meta_and_hello_still_work(self) -> None:
        self.assertEqual(Session("s1").say("hello").intent, router.GREETING)
        self.assertEqual(Session("s2").say("thank you").intent, router.SMALL_TALK)
        meta = Session("s3").say("What dashcams do you support?")
        self.assertEqual(meta.intent, router.META)
        self.assertFalse(meta.escalate)

    def test_a_hazard_mid_intake_still_stops_everything(self) -> None:
        session = Session("hz")
        session.say("Something is wrong with my dashcam.")
        result = session.say("It's smoking and smells of burning plastic.")
        self.assertTrue(result.escalate)

    def test_a_genuinely_unmatched_golden_scenario_still_escalates(self) -> None:
        """EVAL-28 is specific and outside docs/02: that is a hand-off, not a
        question. Only an under-specified symptom is asked about."""
        scenario = next(s for s in load_scenarios() if s.id == "EVAL-28")
        result = Session("e28").say(scenario.utterance)
        self.assertTrue(result.escalate)


class PolicyRoutesVagueSymptomsToIntake(unittest.TestCase):
    def _state(self) -> DiagnosticState:
        return DiagnosticState(session_id="pol")

    def test_no_match_does_not_escalate_while_intake_can_ask(self) -> None:
        decision = policy.escalation(
            self._state(), taxonomy_id="NO_MATCH", legal_steps=["STEP.ESCALATE.HANDOFF"],
            intake_can_ask=True,
        )
        self.assertFalse(decision.escalate)
        self.assertTrue(any("intake" in d for d in decision.declined))

    def test_no_match_still_escalates_when_intake_cannot_ask(self) -> None:
        decision = policy.escalation(
            self._state(), taxonomy_id="NO_MATCH", legal_steps=["STEP.ESCALATE.HANDOFF"],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "no_match")

    def test_intake_cannot_ask_on_a_hazard_a_person_or_a_scope_flag(self) -> None:
        hazard = self._state()
        hazard.safety.hazard_flags.append("burning smell")
        self.assertFalse(policy.intake_can_ask(hazard, rule_flags=[], genuine_no_match=False))
        for flag in ("requests_human", "out_of_scope", "out_of_scope_device"):
            self.assertFalse(
                policy.intake_can_ask(self._state(), rule_flags=[flag], genuine_no_match=False)
            )

    def test_intake_cannot_ask_when_triage_found_a_real_no_match(self) -> None:
        self.assertFalse(
            policy.intake_can_ask(self._state(), rule_flags=[], genuine_no_match=True)
        )

    def test_intake_cannot_ask_after_it_has_given_up(self) -> None:
        state = self._state()
        intake.save(state, intake.IntakeRecord(gave_up=True))
        self.assertFalse(
            policy.intake_can_ask(state, rule_flags=[], genuine_no_match=False)
        )
        self.assertTrue(
            policy.intake_can_ask(self._state(), rule_flags=[], genuine_no_match=False)
        )


class IntakeUnits(unittest.TestCase):
    def test_every_taxonomy_entry_has_a_plain_language_symptom(self) -> None:
        entries = {e for e in ontology.TAXONOMY_CANDIDATES if e not in policy.RESIDUAL_ENTRIES}
        self.assertEqual(entries, set(intake.SYMPTOM_LABELS))

    def test_every_category_has_an_area_label_and_words(self) -> None:
        categories = {c for c in ontology.CATEGORIES if c not in ("NO_MATCH", "OUT_OF_SCOPE")}
        self.assertEqual(categories, set(intake.AREA_LABELS))
        self.assertEqual(categories, set(intake.AREA_WORDS))

    def test_area_words_resolve_a_unique_category_only(self) -> None:
        self.assertEqual(intake.area_in("it's the wifi"), "WIFI")
        self.assertEqual(intake.area_in("the sd card"), "SD")
        self.assertEqual(intake.area_in("something about the update"), "FW")
        self.assertIsNone(intake.area_in("the wifi and the sd card"))
        self.assertIsNone(intake.area_in("I really have no idea"))

    def test_the_record_round_trips_through_the_state_notes(self) -> None:
        state = DiagnosticState(session_id="rt")
        record = intake.IntakeRecord(active=True, asked=intake.SLOT_AREA, area="WIFI")
        intake.save(state, record)
        self.assertEqual(intake.load(state), record)
        self.assertIsInstance(state.notes["intake"], dict)

    def test_the_record_is_immutable(self) -> None:
        record = intake.IntakeRecord()
        with self.assertRaises(Exception):
            record.area = "WIFI"  # type: ignore[misc]

    def test_the_record_survives_the_graph_checkpointer(self) -> None:
        from agent import graph

        session = Session("ckpt")
        session.say("Something is wrong with my dashcam.")
        snapshot = graph.compiled_graph().get_state(
            {"configurable": {"thread_id": "ckpt"}}
        )
        restored = snapshot.values["diagnostic"]
        self.assertTrue(intake.load(restored).active)


class VagueBatteryThroughTheHarnessAgent(unittest.TestCase):
    """`eval.harness.build_agent("core").propose`, as the brief specifies."""

    def test_no_vague_utterance_escalates_through_propose(self) -> None:
        from eval.harness import DiagnosticState as HState
        from eval.harness import Problem, build_agent

        for utterance in VAGUE_UTTERANCES:
            with self.subTest(utterance=utterance):
                agent = build_agent("core", llm=NullLLM())
                out = agent.propose(HState(session_id="h", problem=Problem(verbatim_symptom=utterance)))
                self.assertFalse(out.escalate)
                self.assertNotEqual(out.step_id, "STEP.ESCALATE.HANDOFF")
                self.assertIn("?", agent.turns[-1].response_text)


class ProbeBatteryDoesNotRegress(unittest.TestCase):
    def test_the_25_probe_battery_scores_at_least_24(self) -> None:
        results = probe_battery.run_all()
        failures = [f"{p.utterance!r}: {why}" for p, ok, why in results if not ok]
        self.assertGreaterEqual(len(results) - len(failures), 24, failures)


class GoldenSetIsNotGated(unittest.TestCase):
    def test_no_golden_scenario_is_held_for_intake(self) -> None:
        """Harness A and B are graded on these. A question where they expect a
        step is a regression whatever the intake agent thinks of the symptom."""
        for scenario in load_scenarios():
            if scenario.id == "EVAL-28":
                continue
            with self.subTest(scenario=scenario.id):
                result = Session(f"gold-{scenario.id}").say(scenario.utterance)
                self.assertFalse(
                    intake.load(result.state).active,
                    f"{scenario.id} opened an intake session",
                )


if __name__ == "__main__":
    unittest.main()
