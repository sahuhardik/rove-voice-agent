"""The end-to-end turn-router regression battery (Milestone 6.5).

    .venv/bin/python -m unittest eval.test_turn_router
    .venv/bin/python -m unittest eval.test_turn_router -v

Every test here runs a real utterance through the real turn -- `core.diagnose`,
the LangGraph state machine, retrieval, the policy filter chain and the output
guard -- and asserts **where it was routed**, not what a helper function
returned in isolation. A router that classifies correctly and is then ignored
by the turn is the failure this battery exists to catch, and a unit test on the
classifier alone cannot see it.

**No network and no AWS.** The LLM is `agent.llm.NullLLM`, which fails every
call, so what is asserted is the deterministic floor: the rule-based router,
the keyword route, the filter chain and the guard. That is deliberate -- the
owner's direction is that the system must *solve* end to end, and a routing
guarantee that evaporates when Bedrock is slow is not a guarantee.

The battery is the thirteen probes of the end-to-end brief plus the three
meta/greeting probes:

| # | Probe group | Expected routing |
| --- | --- | --- |
| 1-6 | out-of-scope requests (refund, returns, warranty, RMA, billing, a person) | escalate -- unchanged |
| 7-10 | a non-Rove device, or no dash cam at all | `OUT_OF_SCOPE` + escalate |
| 11 | a bare symptom, no model, no subject | a model-ID question, **no diagnosis step** |
| 12 | a dash cam named with no model | a model-ID question, **no diagnosis step** |
| 13 | `My R2-4K will not turn on` | device identified as R2-4K, diagnoses `PWR-01` |
| 14 | which camera models do you support | the six models, no escalation, no diagnosis |
| 15 | what can you help me with | the supported categories, no escalation |
| 16 | a plain greeting | a greeting, no diagnosis, no escalation |

Plus the containment checks that keep the gates from eating the golden set: no
`eval/scenarios.json` utterance may trip the context gate, the device-scope
gate, or the meta/greeting answer path. Harness A and Harness B are graded on
those utterances, so a gate that fires on one of them is a regression whatever
the probes say.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import core, router  # noqa: E402
from agent.llm import NullLLM  # noqa: E402
from agent.state import DiagnosticState  # noqa: E402
from eval.harness import load_scenarios  # noqa: E402
from ingest.metadata import ALL_MODELS  # noqa: E402

#: Internal vocabulary that must never reach a caller (reply rule (e)).
_FORBIDDEN_IN_REPLY = (
    "EVAL-",
    "\u00a7",
    "taxonomy",
    "NO_MATCH",
    "OUT_OF_SCOPE",
    "STEP.",
    "FAMILY.",
    "triage",
    "shortlist",
)

#: The diagnostic categories. A probe that lands on one of these was diagnosed.
_DIAGNOSTIC_CATEGORIES = ("WIFI", "FW", "APP", "REC", "SD", "PWR", "VID")


def _turn(utterance: str, *, session: str = "probe") -> core.TurnResult:
    """One real turn, LLM stubbed out as unavailable."""
    state = DiagnosticState(session_id=session)
    return core.diagnose(
        utterance, state, llm=NullLLM(), thread_id=f"{session}-{utterance[:24]}"
    )


class ReplyHygiene(unittest.TestCase):
    """Reply rule (e): no internal string ever reaches the caller."""

    def assert_clean(self, result: core.TurnResult, utterance: str) -> None:
        for marker in _FORBIDDEN_IN_REPLY:
            self.assertNotIn(
                marker,
                result.response_text,
                f"{utterance!r} leaked {marker!r} into the reply: "
                f"{result.response_text!r}",
            )


class OutOfScopeRequestsStayEscalated(ReplyHygiene):
    """Probes 1-6. These already escalated; the router must not break them."""

    UTTERANCES = (
        "I want a refund for this camera.",
        "How do I send it back? I want my money back.",
        "Is this still under warranty?",
        "I need an RMA number to return it.",
        "I was charged twice on my invoice for this.",
        "Can I speak to a real person please?",
    )

    def test_each_out_of_scope_request_still_escalates(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertTrue(
                    result.escalate,
                    f"{utterance!r} stopped escalating: {result.rationale}",
                )
                self.assert_clean(result, utterance)

    def test_the_handoff_is_spoken_to_the_caller_not_to_the_engineer(self) -> None:
        """The step description is a note to ourselves. Saying it out loud is
        the same class of leak as saying the escalation reason."""
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertNotIn("Say plainly", result.response_text)
                self.assertNotIn("handoff payload", result.response_text)

    def test_asking_for_a_person_is_answered_as_that(self) -> None:
        """What the caller asked for outranks whatever else triage thought."""
        result = _turn("Can I speak to a real person please?")
        self.assertIn("asked for a person", result.response_text)


class ForeignDeviceRoutesOutOfScope(ReplyHygiene):
    """Probes 7-10. The device-scope gate, ahead of triage."""

    UTTERANCES = (
        "My Garmin dash cam will not turn on.",
        "My Nextbase 522 keeps dropping the wifi.",
        "My GoPro Hero will not connect to the app.",
        "My fridge is making a clicking noise.",
    )

    def test_a_non_rove_device_is_out_of_scope_and_escalates(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertEqual(result.taxonomy_id, "OUT_OF_SCOPE")
                self.assertTrue(result.escalate)
                self.assert_clean(result, utterance)

    def test_a_non_rove_device_is_not_diagnosed(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertNotIn(result.category, _DIAGNOSTIC_CATEGORIES)


class ContextGateAsksForTheModelFirst(ReplyHygiene):
    """Probes 11-12. No model, no subject, a bare symptom: ask, do not guess."""

    UTTERANCES = (
        "It won't turn on.",
        "My dashcam isn't working.",
    )

    def test_a_bare_symptom_produces_a_clarifying_model_question(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertEqual(result.intent, router.SYMPTOM)
                self.assertIsNone(
                    result.step_id,
                    f"{utterance!r} proposed a diagnosis step {result.step_id!r} "
                    "before knowing which camera it is",
                )
                self.assertFalse(result.escalate)
                self.assertTrue(
                    result.response_text.rstrip().endswith("?"),
                    f"{utterance!r} did not get a question: "
                    f"{result.response_text!r}",
                )
                self.assert_clean(result, utterance)

    def test_a_bare_symptom_is_not_diagnosed(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertNotIn(result.category, _DIAGNOSTIC_CATEGORIES)

    def test_answering_the_model_question_then_diagnoses_the_symptom(self) -> None:
        """The gate asks in order to get on with it, not instead of it.

        This is the end-to-end property the gate exists to serve: holding the
        turn is only defensible if the session then continues from the answer.
        A gate that asks and then loses the symptom has replaced one failure
        with a worse one.
        """
        state = DiagnosticState(session_id="resume")
        first = core.diagnose(
            "It won't turn on.", state, llm=NullLLM(), thread_id="resume"
        )
        self.assertIsNone(first.step_id)

        second = core.diagnose(
            "It's an R2-4K.", state, llm=NullLLM(), thread_id="resume"
        )
        self.assertEqual(second.taxonomy_id, "PWR-01")
        self.assertIsNotNone(second.step_id)
        self.assertFalse(second.escalate)
        self.assert_clean(second, "It's an R2-4K.")


class NamedModelOpensTheGate(ReplyHygiene):
    """Probe 13. The gate reads the utterance, not only the record."""

    UTTERANCE = "My R2-4K will not turn on."

    def test_the_named_model_is_identified(self) -> None:
        result = _turn(self.UTTERANCE)
        self.assertEqual(result.trace["router"]["named_model"], "R2-4K")

    def test_a_named_model_is_diagnosed_rather_than_asked_about(self) -> None:
        result = _turn(self.UTTERANCE)
        self.assertEqual(result.taxonomy_id, "PWR-01")
        self.assertIsNotNone(result.step_id)
        self.assertFalse(result.escalate)
        self.assert_clean(result, self.UTTERANCE)


class MetaQuestionsAreAnswered(ReplyHygiene):
    """Probes 14-16. Answer from the knowledge the system already holds."""

    MODEL_QUESTION = "What are the camera models you support?"

    def test_the_model_question_is_answered_with_the_six_models(self) -> None:
        result = _turn(self.MODEL_QUESTION)
        self.assertEqual(result.intent, router.META)
        self.assertEqual(len(ALL_MODELS), 6)
        for name in router.model_display_names():
            self.assertIn(name, result.response_text)

    def test_the_model_question_neither_escalates_nor_diagnoses(self) -> None:
        result = _turn(self.MODEL_QUESTION)
        self.assertFalse(result.escalate)
        self.assertIsNone(result.step_id)
        self.assertNotIn(result.category, _DIAGNOSTIC_CATEGORIES)
        self.assert_clean(result, self.MODEL_QUESTION)

    def test_the_capability_question_is_answered_with_the_categories(self) -> None:
        result = _turn("What can you help me with?")
        self.assertEqual(result.intent, router.META)
        self.assertFalse(result.escalate)
        self.assertIsNone(result.step_id)
        for label in router.supported_category_labels():
            self.assertIn(label, result.response_text)

    def test_a_greeting_gets_a_greeting(self) -> None:
        result = _turn("Hello there!")
        self.assertEqual(result.intent, router.GREETING)
        self.assertFalse(result.escalate)
        self.assertIsNone(result.step_id)
        self.assertNotIn(result.category, _DIAGNOSTIC_CATEGORIES)
        self.assert_clean(result, "Hello there!")


class SubjectVerificationRoutesNonRoveDevicesOut(ReplyHygiene):
    """Milestone 6.6, fix 1. The subject must be a Rove dash cam, not a keyword."""

    OUT_OF_SCOPE = (
        "My Samsung TV won't turn on.",
        "My phone won't connect to Wi-Fi.",
        "My car's reverse camera screen is frozen.",
        "My GoPro won't turn on.",
        "My laptop screen is flickering.",
        "My washing machine is leaking.",
    )
    STILL_ROVE = (
        "My phone won't connect to the dashcam Wi-Fi.",
        "The app on my phone says the camera is offline.",
        "My rear camera image is upside down.",
        "My Samsung microSD card keeps getting corrupted on my dashcam.",
    )

    def test_a_non_rove_subject_is_out_of_scope_and_escalates(self) -> None:
        for utterance in self.OUT_OF_SCOPE:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertEqual(result.taxonomy_id, "OUT_OF_SCOPE")
                self.assertTrue(result.escalate)
                self.assert_clean(result, utterance)

    def test_a_rove_session_that_mentions_a_phone_or_card_is_not_gated(self) -> None:
        for utterance in self.STILL_ROVE:
            with self.subTest(utterance=utterance):
                routing = router.route(utterance, DiagnosticState(session_id="s"))
                self.assertIsNone(routing.foreign_subject)

    def test_the_phone_gate_does_not_fire_mid_diagnosis(self) -> None:
        """"My phone won't connect" is a normal WIFI answer once we are in one."""
        state = DiagnosticState(session_id="mid")
        state.turn = 3
        routing = router.route("My phone won't connect to Wi-Fi.", state)
        self.assertIsNone(routing.foreign_subject)


class ContextGateWidening(ReplyHygiene):
    """Milestone 6.6, fix 2."""

    def test_a_dashcam_that_will_not_connect_asks_for_model_and_phone(self) -> None:
        utterance = "My dashcam won't connect to Wi-Fi."
        routing = router.route(utterance, DiagnosticState(session_id="w"))
        self.assertTrue(routing.needs_model_id)
        self.assertIn("phone", routing.reply.lower())
        result = _turn(utterance)
        self.assertIsNone(result.step_id)
        self.assertFalse(result.escalate)

    def test_a_connect_failure_with_detail_is_still_diagnosed(self) -> None:
        routing = router.route(
            "My dashcam won't connect to Wi-Fi, it says wrong password.",
            DiagnosticState(session_id="w"),
        )
        self.assertFalse(routing.needs_model_id)

    def test_the_bare_symptom_still_asks_which_rove_camera(self) -> None:
        """Regression guard, called on the router: AgentOutput hides the reply."""
        routing = router.route("It won't turn on.", DiagnosticState(session_id="g"))
        self.assertTrue(routing.needs_model_id)
        self.assertIn("which Rove camera", routing.reply)

    def test_a_named_model_is_picked_up_on_the_first_turn(self) -> None:
        state = DiagnosticState(session_id="n")
        routing = router.route("My R2-4K won't turn on.", state)
        self.assertEqual(routing.named_model, "R2-4K")
        self.assertFalse(routing.needs_model_id)
        core.diagnose(
            "My R2-4K won't turn on.", state, llm=NullLLM(), thread_id="n"
        )
        self.assertTrue(state.device.evidence)
        self.assertEqual(state.device.evidence[0].value, "R2-4K")


class NonSymptomTurnsGetAConversationalReply(ReplyHygiene):
    """Milestone 6.6, fix 3. Chit-chat is not an engineering escalation."""

    UTTERANCES = (
        "thank you",
        "bye",
        "I don't know",
        "never mind",
        "I hate this camera",
        "This is stupid",
        "You're useless",
    )

    def test_each_is_answered_without_escalating_or_diagnosing(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertFalse(result.escalate, result.response_text)
                self.assertIsNone(result.step_id)
                self.assertNotIn(result.category, _DIAGNOSTIC_CATEGORIES)
                self.assertTrue(result.response_text.strip())
                self.assert_clean(result, utterance)

    def test_asking_for_a_human_still_escalates(self) -> None:
        self.assertTrue(_turn("I want to talk to a human").escalate)

    def test_hello_still_greets(self) -> None:
        self.assertEqual(_turn("hello").intent, router.GREETING)

    def test_i_dont_know_mid_diagnosis_is_an_answer_not_chit_chat(self) -> None:
        state = DiagnosticState(session_id="mid2")
        state.turn = 3
        routing = router.route("I don't know", state)
        self.assertIsNone(routing.reply)


class MetaPhrasingVariants(ReplyHygiene):
    """Milestone 6.6, fix 4."""

    UTTERANCES = (
        "What dashcams do you support?",
        "Which dash cams do you cover?",
        "What dash cameras do you support?",
        "What are the camera models you support?",
    )

    def test_each_is_answered_from_the_registry(self) -> None:
        for utterance in self.UTTERANCES:
            with self.subTest(utterance=utterance):
                result = _turn(utterance)
                self.assertEqual(result.intent, router.META)
                self.assertFalse(result.escalate)
                for name in router.model_display_names():
                    self.assertIn(name, result.response_text)


class GatesDoNotEatTheGoldenSet(unittest.TestCase):
    """Harness A and B are graded on these utterances. No gate may fire."""

    def setUp(self) -> None:
        self.scenarios = load_scenarios()

    def test_no_golden_utterance_trips_the_context_gate(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.id):
                self.assertFalse(
                    router.is_bare_symptom(scenario.utterance),
                    f"{scenario.id} would be held at the context gate",
                )

    def test_no_golden_utterance_trips_the_device_scope_gate(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.id):
                routing = router.route(
                    scenario.utterance, DiagnosticState(session_id="golden")
                )
                self.assertIsNone(
                    routing.foreign_subject,
                    f"{scenario.id} was read as a non-Rove device",
                )

    def test_no_golden_utterance_is_read_as_meta_or_greeting(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.id):
                routing = router.route(
                    scenario.utterance, DiagnosticState(session_id="golden")
                )
                self.assertNotIn(routing.intent, (router.META, router.GREETING))


class ModelNamePickup(unittest.TestCase):
    """Milestone 6.6 follow-up: a model named in the sentence is identified on
    turn 1, and only a model the registry knows is ever identified."""

    NAMED = (
        ("My R2-4K won't turn on.", "R2-4K"),
        ("My R3 won't record.", "R3"),
        ("My R2-4K Pro keeps rebooting.", "R2-4K PRO"),
        ("My R2-4K Dual won't turn on.", "R2-4K DUAL"),
        ("My R2-4K Dual Pro won't turn on.", "R2-4K DUAL PRO"),
        ("my r2 4k pro keeps rebooting", "R2-4K PRO"),
    )
    NOT_ROVE = (
        "My Samsung TV won't turn on.",
        "My phone won't connect to Wi-Fi.",
        "My GoPro won't turn on.",
    )

    @staticmethod
    def _propose(utterance: str):
        from eval import harness

        state = harness.DiagnosticState(session_id="pickup")
        state.problem.verbatim_symptom = utterance
        return harness.build_agent("core").propose(state)

    def test_named_model_resolves_to_exactly_that_model(self) -> None:
        for utterance, expected in self.NAMED:
            with self.subTest(utterance=utterance):
                routing = router.route(utterance, DiagnosticState(session_id="p"))
                self.assertEqual(routing.named_model, expected)

    def test_named_model_reaches_the_reported_device(self) -> None:
        for utterance, expected in self.NAMED:
            with self.subTest(utterance=utterance):
                self.assertEqual(self._propose(utterance).device_model, expected)

    def test_bare_r2_4k_is_not_given_a_revision(self) -> None:
        state = DiagnosticState(session_id="rev")
        core.diagnose(
            "My R2-4K won't turn on.", state, llm=NullLLM(), thread_id="rev-1"
        )
        self.assertEqual(state.device.hw_revision, "unknown")
        self.assertEqual(state.device.spoken_model, "R2-4K")
        # The 3.4 invariant holds: a spoken name is one weak signal.
        self.assertEqual(state.device.reported_model, "unknown")
        self.assertEqual(state.device.confidence, "UNKNOWN")

    def test_explicit_revision_is_kept(self) -> None:
        routing = router.route(
            "My R2-4K mini USB won't turn on.", DiagnosticState(session_id="p")
        )
        self.assertEqual(routing.named_model, "R2-4K (mini-USB)")

    def test_non_rove_subjects_identify_no_model(self) -> None:
        for utterance in self.NOT_ROVE:
            with self.subTest(utterance=utterance):
                routing = router.route(utterance, DiagnosticState(session_id="p"))
                self.assertEqual(routing.intent, router.OUT_OF_SCOPE)
                self.assertIsNone(routing.named_model)
                output = self._propose(utterance)
                self.assertEqual(output.device_model, "unknown")
                self.assertTrue(output.escalate)

    def test_state_spoken_names_match_router_display_names(self) -> None:
        from agent.state import SPOKEN_NAMES

        self.assertEqual(SPOKEN_NAMES, router.MODEL_DISPLAY_NAMES)

    def test_unregistered_name_is_not_reported_as_a_model(self) -> None:
        output = self._propose("My R9 won't turn on.")
        self.assertEqual(output.device_model, "unknown")


if __name__ == "__main__":
    unittest.main()
