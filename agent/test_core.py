"""Stdlib unittest for the Phase 1 diagnostic core.

    .venv/bin/python -m unittest agent.test_core
    .venv/bin/python -m unittest agent.test_core -v

**No network and no AWS.** Every test here stubs the LLM. `agent/core.py`
treats a model as an advisor that can fail at any moment, so the interesting
behaviour — the policy filter, the output guard, the fallback — is exactly the
behaviour that does not need Bedrock to exercise. A test suite that needed
credentials to assert that the destructive gate holds would be a test suite
nobody runs.

Six properties, one class each:

1. **no-repeat holds on EVAL-12** — the canonical family-blocking case. The
   caller has formatted the card twice; neither that step nor its sibling in
   the same destructive family may come back.
2. **the destructive gate blocks without consent** — cause and consequence are
   not enough, and in text mode there is no consent surface at all.
3. **the output guard drops an uncited device claim** — a device specific with
   no Tier-1 chunk behind it does not get spoken.
4. **the LLM fallback returns the baseline step** — with the model stubbed to
   raise, the core agent's step is the dumb baseline's step, on all 30.
5. **model identification narrows or stays UNKNOWN** (Milestone 3.1) — every
   probe answer carries the `docs/06` §3.4 candidate set it implies, and
   `unknown` at `PROBABLE` is unreachable.
6. **a classification is not an escalation trigger** (Milestone 3.1) — a
   `NO_MATCH` or `OUT_OF_SCOPE` vote with no §5.1 trigger behind it routes back
   to a question; `FW-02` still escalates immediately.
7. **an unmatched symptom combination escalates** (Milestone 3.3) — an entry
   that explains a minority of what the caller reported, with its own
   discriminating condition absent, is `docs/06` §4.7's "nearest category,
   forced" and does not defeat `NO_MATCH`. Both directions are asserted: an
   EVAL-28-shaped turn escalates, and (6)'s single-symptom routes still do not.
8. **the attempt ceiling counts attempts** (Milestone 4.8) — `docs/02`'s
   cross-cutting trigger 1 counts "two steps *attempted* with no change", and a
   question that was put and answered is not one of them. Both directions:
   two failed actions still breach it, and the answered question is still
   blocked by no-repeat.

Plus one invariant test for the spoken forms, which is what keeps (3) from
quietly deleting the agent's only action.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import core, policy, retrieval, symptoms  # noqa: E402
from agent.llm import Classification, LLMError, TurnDecision  # noqa: E402
from agent.state import (  # noqa: E402
    PROBABLE,
    UNKNOWN,
    DeviceIdentification,
    DiagnosticState,
    Ledger,
    ModelSignal,
    Problem,
    Safety,
)
from eval import ontology  # noqa: E402
from ingest.metadata import (  # noqa: E402
    ALL_MODELS,
    R2_4K_DUAL_PRO,
    R2_4K_EITHER_REVISION,
    R2_4K_MINI_USB,
    R3,
)
from eval.baseline import DumbBaselineAgent  # noqa: E402
from eval.harness import load_scenarios, state_from_scenario  # noqa: E402

#: EVAL-12's blocked family: the caller formatted the card in the camera twice.
#: `STEP.CARD.FORMAT_ON_COMPUTER` is a *different step* in that family, and the
#: whole point of family-level blocking is that it is equally blocked.
ERASE_CARD_FAMILY = "FAMILY.DESTRUCTIVE.ERASE_CARD"
FORMAT_IN_CAMERA = "STEP.CARD.FORMAT_IN_CAMERA"
FORMAT_ON_COMPUTER = "STEP.CARD.FORMAT_ON_COMPUTER"


# --------------------------------------------------------------------------
# Stub models
# --------------------------------------------------------------------------


class FailingLLM:
    """A model that is always down. Every call raises, as Bedrock would."""

    name = "failing-stub"

    def __init__(self) -> None:
        self.classify_calls = 0
        self.decide_calls = 0

    def classify(self, utterance: str) -> Classification:
        self.classify_calls += 1
        raise LLMError("stub: Bedrock unreachable")

    def decide(self, **kwargs: object) -> TurnDecision:
        self.decide_calls += 1
        raise LLMError("stub: Bedrock unreachable")


class ScriptedLLM:
    """A model that returns exactly what it is told to return.

    Used to drive the core down a path a healthy model would take, without
    making the assertion depend on what a real model happens to say today.
    """

    name = "scripted-stub"

    def __init__(self, classification: Classification, decision: TurnDecision) -> None:
        self._classification = classification
        self._decision = decision

    def classify(self, utterance: str) -> Classification:
        return self._classification

    def decide(self, **kwargs: object) -> TurnDecision:
        return self._decision


def _state_for(scenario_id: str) -> DiagnosticState:
    """The agent-side state for one golden scenario, via the harness loader."""
    scenario = next(s for s in load_scenarios() if s.id == scenario_id)
    return core.state_from_harness(state_from_scenario(scenario))


# --------------------------------------------------------------------------
# 1. No-repeat, on the scenario the rule was written for
# --------------------------------------------------------------------------


class TestNoRepeatOnEval12(unittest.TestCase):
    """`docs/06` §3.5 / §3.6, EVAL-12: family-level blocking, not step-level."""

    def setUp(self) -> None:
        self.state = _state_for("EVAL-12")

    def test_ledger_blocks_the_step_and_its_family(self):
        blocked = self.state.ledger.blocked
        self.assertIn(FORMAT_IN_CAMERA, blocked)
        self.assertIn(ERASE_CARD_FAMILY, blocked)

    def test_filter_drops_the_tried_step_with_a_no_repeat_reason(self):
        decisions = policy.candidate_steps(self.state, taxonomy_id="SD-01")
        by_id = {d.step_id: d for d in decisions}
        self.assertIn(
            FORMAT_IN_CAMERA,
            by_id,
            "SD-01 must still offer the step as a candidate — the filter is what "
            "removes it, and a candidate that never appears cannot be audited",
        )
        decision = by_id[FORMAT_IN_CAMERA]
        self.assertFalse(decision.kept)
        self.assertIn("no-repeat", decision.drop_reason or "")

    def test_a_sibling_in_the_same_family_is_equally_blocked(self):
        decisions = policy.candidate_steps(
            self.state,
            taxonomy_id="SD-01",
            # Force the sibling into the candidate set even if the taxonomy map
            # for SD-01 does not list it: the claim under test is about the
            # family rule, not about which steps SD-01 happens to enumerate.
            retrieved_step_ids=[FORMAT_ON_COMPUTER],
        )
        by_id = {d.step_id: d for d in decisions}
        self.assertIn(FORMAT_ON_COMPUTER, by_id)
        decision = by_id[FORMAT_ON_COMPUTER]
        self.assertFalse(
            decision.kept,
            "a different step in a tried-and-failed family is still blocked "
            "(06 §3.6, EVAL-12)",
        )
        self.assertIn("no-repeat", decision.drop_reason or "")

    def test_no_legal_candidate_is_in_the_blocked_family(self):
        decisions = policy.candidate_steps(self.state, taxonomy_id="SD-01")
        for step_id in policy.legal_step_ids(decisions):
            self.assertNotEqual(
                ontology.STEPS[step_id].family,
                ERASE_CARD_FAMILY,
                f"{step_id} survived the filter but is in the blocked family",
            )

    def test_the_whole_turn_never_proposes_a_blocked_step(self):
        """End to end, with the model stubbed to a plausible wrong answer.

        The model is told to pick `STEP.CARD.FORMAT_IN_CAMERA` — the one thing
        EVAL-12 says must not come back. The filter runs *before* the model
        sees its options, so the step is not on the menu and cannot be chosen.
        """
        scripted = ScriptedLLM(
            Classification(category="SD", taxonomy_ids=["SD-01"]),
            TurnDecision(
                category="SD",
                taxonomy_id="SD-01",
                next_step=FORMAT_IN_CAMERA,
                hypothesis="The card is corrupt.",
                escalate=False,
                reason="a format usually clears it",
            ),
        )
        state = _state_for("EVAL-12")
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=scripted
        )
        self.assertNotEqual(result.step_id, FORMAT_IN_CAMERA)
        if result.step_id is not None:
            self.assertNotEqual(
                ontology.STEPS[result.step_id].family, ERASE_CARD_FAMILY
            )
        offered = result.trace.get("options", [])
        self.assertNotIn(
            FORMAT_IN_CAMERA,
            offered,
            "a blocked step must never reach the model's option list",
        )


# --------------------------------------------------------------------------
# 2. The destructive gate
# --------------------------------------------------------------------------


class TestDestructiveGate(unittest.TestCase):
    """`docs/06` §6.4: cause + consequence + *explicit* consent, or no step."""

    def _state(self) -> DiagnosticState:
        # Deliberately not EVAL-12: an empty ledger means no-repeat cannot be
        # the thing doing the blocking, and `footage_at_stake="none"` keeps the
        # §6.4 preservation rule (which removes destructive steps outright,
        # with no consent path) from pre-empting the gate.
        return DiagnosticState(
            session_id="gate-test",
            safety=Safety(driving="no", footage_at_stake="none"),
            problem=Problem(verbatim_symptom="the card keeps throwing an error"),
            ledger=Ledger(),
        )

    def _decision_for(self, state: DiagnosticState):
        decisions = policy.candidate_steps(
            state, taxonomy_id="SD-01", retrieved_step_ids=[FORMAT_IN_CAMERA]
        )
        return next(d for d in decisions if d.step_id == FORMAT_IN_CAMERA)

    def test_the_step_is_actually_destructive(self):
        """Guard against the test passing because the ontology changed."""
        self.assertTrue(ontology.STEPS[FORMAT_IN_CAMERA].destructive)

    def test_blocked_without_consent(self):
        state = self._state()
        decision = self._decision_for(state)
        self.assertFalse(decision.kept)
        self.assertIn("destructive gate", decision.drop_reason or "")
        self.assertNotIn(FORMAT_IN_CAMERA, policy.legal_step_ids(
            policy.candidate_steps(
                state, taxonomy_id="SD-01", retrieved_step_ids=[FORMAT_IN_CAMERA]
            )
        ))

    def test_the_refusal_is_recorded_as_structured_fields(self):
        """A gate that refuses silently looks the same as a filter that forgot."""
        state = self._state()
        decision = self._decision_for(state)
        self.assertIsNotNone(decision.gate)
        gate = decision.gate
        self.assertEqual(gate.consent_state, "not_requested")
        self.assertEqual(gate.decision, "blocked")
        self.assertTrue(gate.cause, "a blocked gate still records its cause")
        self.assertTrue(gate.consequence, "and the consequence it would speak")
        self.assertFalse(gate.satisfied)
        self.assertIn(gate, state.gates)

    def test_cause_and_consequence_alone_do_not_open_it(self):
        """The failure mode worth testing: two of three parts present."""
        state = self._state()
        gate = self._decision_for(state).gate
        self.assertTrue(gate.cause and gate.consequence)
        self.assertEqual(gate.decision, "blocked")

    def test_explicit_consent_opens_it(self):
        """The positive control. Without it, a gate welded shut would pass."""
        state = self._state()
        state.consent[FORMAT_IN_CAMERA] = True
        decision = self._decision_for(state)
        self.assertTrue(decision.kept, decision.drop_reason)
        self.assertEqual(decision.gate.consent_state, "granted")
        self.assertEqual(decision.gate.decision, "allowed")
        self.assertTrue(decision.gate.satisfied)

    def test_footage_at_stake_removes_it_with_no_consent_path(self):
        """§6.4: preservation overrides the gate, consent or not."""
        state = self._state()
        state.safety.footage_at_stake = "wanted"
        state.consent[FORMAT_IN_CAMERA] = True
        decision = self._decision_for(state)
        self.assertFalse(decision.kept)
        self.assertIn("preservation", decision.drop_reason or "")


# --------------------------------------------------------------------------
# 3. The output guard
# --------------------------------------------------------------------------


class TestOutputGuard(unittest.TestCase):
    """`docs/06` §4.5 / §4.6: no device specific without a Tier-1 chunk."""

    UNCITED = "The R2-4K needs a class 10 card of at least 32 GB."

    def test_detects_the_device_specific_spans(self):
        spans = core.device_specific_spans(self.UNCITED)
        self.assertTrue(spans, "the claim detector has to fire at all")

    def test_drops_an_uncited_device_claim(self):
        line = core.Line(self.UNCITED, chunk_ids=[], kind="prose")
        report = core.output_guard([line])
        self.assertEqual(report.kept, [])
        self.assertEqual(len(report.dropped), 1)
        dropped, reason = report.dropped[0]
        self.assertIs(dropped, line)
        self.assertIn("device-specific claim", reason)
        self.assertNotIn("R2-4K", report.text)
        self.assertEqual(report.text, "")

    def test_keeps_the_same_claim_once_it_is_cited(self):
        """The control: it is the missing citation that drops it, not the words."""
        line = core.Line(self.UNCITED, chunk_ids=["chunk-0001"], kind="prose")
        report = core.output_guard([line])
        self.assertEqual(report.dropped, [])
        self.assertIn("R2-4K", report.text)
        self.assertEqual(report.citations, ["chunk-0001"])

    def test_an_uncited_step_line_is_rewritten_rather_than_dropped(self):
        """Dropping a step line leaves a `step_id` the agent never asked for."""
        line = core.Line(
            "Could you press the reset button?",
            chunk_ids=[],
            kind="step",
            fallback="Could you look for a small recessed hole on the body?",
        )
        report = core.output_guard([line])
        self.assertEqual(report.dropped, [])
        self.assertEqual(len(report.rewritten), 1)
        self.assertIn("recessed hole", report.text)
        self.assertNotIn("reset button", report.text)

    def test_a_firmware_version_is_dropped_from_every_kind_of_line(self):
        """§4.6: no path may emit a version — including a safety line."""
        for kind in ("prose", "step", "safety"):
            with self.subTest(kind=kind):
                line = core.Line(
                    "Unplug it; firmware 2.1.4 is mid-write.",
                    chunk_ids=["chunk-0001"],
                    kind=kind,
                )
                report = core.output_guard([line])
                self.assertEqual(report.kept, [])
                self.assertIn("firmware-version-shaped", report.dropped[0][1])

    def test_the_guard_runs_inside_a_real_turn(self):
        """The guard is wired into `diagnose`, not merely importable."""
        state = _state_for("EVAL-02")
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=FailingLLM()
        )
        self.assertFalse(core.firmware_version_spans(result.response_text))
        self.assertTrue(
            state.clearance.spoken_claims,
            "EVAL-02 retrieves Tier-1 evidence, so the audit trail is not empty",
        )
        for claim in state.clearance.spoken_claims:
            self.assertTrue(
                claim.chunk_ids, "a recorded spoken claim always carries its chunks"
            )


class TestSpokenFormsCannotLoseTheStep(unittest.TestCase):
    """Every step has a sayable form the guard will not delete outright.

    This is what stops the §4.5 rule from turning into "the agent silently
    stops proposing steps": a generated spoken form that trips the device-claim
    detector must be covered by an explicit `SPOKEN_FORM` rewrite, or by a
    de-specified `SPOKEN_FALLBACK` the guard can substitute.
    """

    def test_every_tripping_step_has_a_rewrite_or_a_fallback(self):
        for step_id in ontology.STEPS:
            spoken = core.spoken_form(step_id)
            if not core.device_specific_spans(spoken):
                continue
            with self.subTest(step=step_id):
                self.assertIn(
                    step_id,
                    core.SPOKEN_FALLBACK,
                    f"{core.spoken_form(step_id)!r} trips the device-claim "
                    "detector and has no fallback, so the guard would drop the "
                    "agent's only action",
                )
                self.assertFalse(
                    core.device_specific_spans(core.SPOKEN_FALLBACK[step_id]),
                    "the fallback itself must be de-specified",
                )

    def test_no_spoken_form_contains_a_version(self):
        for step_id in ontology.STEPS:
            with self.subTest(step=step_id):
                self.assertFalse(core.firmware_version_spans(core.spoken_form(step_id)))

    def test_no_spoken_form_leaks_internal_vocabulary(self):
        """Milestone 6.5. The guard's leak rule has no fallback -- a line
        carrying an eval id or a docs reference is dropped outright -- so a
        step whose description carries one has to have a spoken form, or the
        turn proposes a step it never asked for. `STEP.CARD.FORMAT_ON_COMPUTER`
        is the one that did: its description ends "(EVAL-12)"."""
        for step_id in ontology.STEPS:
            with self.subTest(step=step_id):
                self.assertFalse(
                    core.internal_marker_spans(core.spoken_form(step_id)),
                    f"{core.spoken_form(step_id)!r} would be dropped by the "
                    "guard's leak rule, which would delete the agent's only "
                    "action",
                )
                fallback = core.SPOKEN_FALLBACK.get(step_id)
                if fallback is not None:
                    self.assertFalse(core.internal_marker_spans(fallback))


# --------------------------------------------------------------------------
# 4. The LLM fallback
# --------------------------------------------------------------------------


class TestLLMFallback(unittest.TestCase):
    """With Bedrock down, the core degrades to the Phase 0 floor, not to nothing."""

    def test_one_turn_falls_back_to_the_baseline_step(self):
        scenario = next(s for s in load_scenarios() if s.id == "EVAL-02")
        harness_state = state_from_scenario(scenario)
        expected = DumbBaselineAgent().propose(harness_state)

        llm = FailingLLM()
        state = core.state_from_harness(harness_state)
        result = core.diagnose(state.problem.verbatim_symptom, state, llm=llm)

        self.assertEqual(result.step_id, expected.step_id)
        self.assertEqual(result.taxonomy_id, expected.taxonomy_id)
        self.assertEqual(llm.classify_calls, 1, "it must have tried the model first")
        self.assertGreaterEqual(llm.decide_calls, 1)
        self.assertIn("rule-based fallback", result.rationale)

    def test_both_failures_are_recorded_in_the_trace(self):
        """A silent fallback is indistinguishable from a model that agreed."""
        state = _state_for("EVAL-02")
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=FailingLLM()
        )
        fallbacks = result.trace["fallbacks"]
        self.assertTrue(any(f.startswith("classify:") for f in fallbacks), fallbacks)
        self.assertTrue(any(f.startswith("decide:") for f in fallbacks), fallbacks)
        self.assertTrue(all("LLMError" in f for f in fallbacks), fallbacks)

    def test_the_agent_still_returns_a_scorable_output(self):
        """Degraded is not broken: the harness contract still holds."""
        scenario = next(s for s in load_scenarios() if s.id == "EVAL-22")
        output = core.CoreAgent(llm=FailingLLM()).propose(state_from_scenario(scenario))
        self.assertIsNotNone(output.step_id)
        self.assertIn(output.step_id, ontology.STEPS)

    def test_the_floor_holds_across_the_whole_eval_set(self):
        """Every scenario, not just a convenient one.

        This is the claim `agent/core.py` makes in so many words — "the whole
        point of having a dumb agent is that it is still there when the clever
        one is not" — so it is worth asserting on all 30 rather than on one.

        **First documented exception, from Milestone 3.3: EVAL-28.** The floor
        is the baseline's *step list*, not its triage. `eval/baseline.py`'s
        keyword router matches "time" inside "sometimes" and forces EVAL-28
        onto `PWR-04`; `core.step_triage` takes the `docs/06` §3.2 `NO_MATCH`
        exit instead, because the caller reported three symptoms, two of them
        outside `docs/02` entirely. Diverging *upwards* there is the fix, and
        it holds with the model down — which is the point worth asserting.

        **Second documented exception, from Milestone 4.4: EVAL-26.** Same
        shape, same direction. The caller volunteers the answer to
        `STEP.ASK.APP_PERMISSIONS_GRANTED` in their opening words — "it did ask
        me something about local network and I think I said no" — and `docs/02`
        APP-02 says what that answer does: "the branch moves to `APP-03`". The
        baseline's keyword router cannot read an answer, so it stays on APP-02
        and proposes a force-close; the core recategorises and proposes the
        step `docs/03` EVAL-26 names as the expected one. Recategorising on a
        volunteered answer is deterministic policy, not a model judgement, so
        it holds with the model down — again the point worth asserting. The
        assertion is therefore *stronger* than the floor here, not weaker: the
        core must land on the golden step, not merely on some step.
        """
        scenarios = load_scenarios()
        agent = core.CoreAgent(llm=FailingLLM())
        baseline = DumbBaselineAgent()
        for scenario in scenarios:
            with self.subTest(scenario=scenario.id):
                expected = baseline.propose(state_from_scenario(scenario))
                actual = agent.propose(state_from_scenario(scenario))
                if scenario.id == "EVAL-28":
                    self.assertEqual(actual.taxonomy_id, "NO_MATCH")
                    self.assertTrue(actual.escalate)
                    self.assertIn(actual.step_id, scenario.expected_step_ids)
                    continue
                if scenario.id == "EVAL-26":
                    self.assertEqual(actual.taxonomy_id, "APP-03")
                    self.assertIn(actual.step_id, scenario.expected_step_ids)
                    self.assertNotEqual(
                        actual.step_id,
                        expected.step_id,
                        "if the baseline has caught up, drop this exception",
                    )
                    continue
                self.assertEqual(
                    actual.step_id,
                    expected.step_id,
                    "with the model down, the core's step is the baseline's step",
                )

    def test_the_hard_constraints_still_hold_with_no_model(self):
        """M4 and M5 are code, not behaviour the model is trusted to produce."""
        from eval.harness import run_harness

        report = run_harness(core.CoreAgent(llm=FailingLLM()), load_scenarios())
        breaches = [
            (r.scenario_id, r.m4_breaches + r.m5_breaches)
            for r in report.results
            if not r.m4_no_repeat or not r.m5_harmful
        ]
        self.assertEqual(breaches, [])


# --------------------------------------------------------------------------
# 5. Model identification: narrowing, and the UNKNOWN floor (Milestone 3.1)
# --------------------------------------------------------------------------


class TestModelNarrowing(unittest.TestCase):
    """`docs/06` §3.4: a probe answer narrows the candidate set, or says nothing.

    The defect this fixes: every `ModelSignal` was built without `narrows_to`,
    so `candidates` never shrank, `model` was never assigned, and confidence
    still climbed to `PROBABLE` on any feature signal — leaving the agent
    reporting model `unknown` at confidence `PROBABLE`.
    """

    def test_ssid_narrows_to_the_r2_4k_family(self):
        """Probe 1, the strongest rung of the ladder (05 SSID table)."""
        device = DeviceIdentification()
        device.add_signal(ModelSignal.from_probe("ssid", "ROVE_R2-4K_8F2A1C", 1))
        self.assertEqual(device.candidates, list(R2_4K_EITHER_REVISION))
        self.assertNotEqual(device.confidence, UNKNOWN)
        self.assertNotEqual(device.reported_model, "unknown")

    def test_the_longer_ssid_prefixes_are_not_eaten_by_the_shorter_one(self):
        """`ROVE_R2-4K-DUAL_PRO` must not match as a bare `ROVE_R2-4K_`."""
        device = DeviceIdentification()
        device.add_signal(ModelSignal.from_probe("ssid", "ROVE_R2-4K-DUAL_PRO", 1))
        self.assertEqual(device.candidates, [R2_4K_DUAL_PRO])
        self.assertEqual(device.model, R2_4K_DUAL_PRO)

    def test_touch_screen_resolves_the_r2_vs_r3_question(self):
        """Probe 3 — and it never asks the caller to say "R2" or "R3" (§3.4)."""
        device = DeviceIdentification()
        device.add_signal(
            ModelSignal.from_probe("touch_or_buttons", "I tap the screen", 1)
        )
        self.assertEqual(device.candidates, [R3])
        self.assertEqual(device.reported_model, R3)

    def test_the_reversible_plug_probe_sets_the_revision(self):
        """Probe 4 is the R2-4K revision split (05 `M1` vs `M2`/`M3`)."""
        device = DeviceIdentification()
        device.add_signal(ModelSignal.from_probe("lens_count", "just the one", 1))
        device.add_signal(
            ModelSignal.from_probe("connector", "it only goes in one way", 2)
        )
        self.assertEqual(device.candidates, [R2_4K_MINI_USB])
        self.assertEqual(device.hw_revision, "mini_usb")

    def test_a_signal_that_narrows_nothing_does_not_raise_confidence(self):
        """The defect, stated as a test: no narrowing, no promotion."""
        device = DeviceIdentification()
        device.add_signal(ModelSignal.from_probe("lens_count", "not sure really", 1))
        self.assertEqual(device.candidates, list(ALL_MODELS))
        self.assertEqual(device.confidence, UNKNOWN)
        self.assertEqual(device.reported_model, "unknown")
        self.assertTrue(device.evidence, "it is still recorded as evidence")

    def test_a_spoken_model_name_never_narrows_and_never_promotes(self):
        """§3.4: "one weak signal, never identification" — however often."""
        device = DeviceIdentification()
        for turn in range(1, 5):
            device.add_signal(ModelSignal.from_probe("name", "R2", turn))
        self.assertEqual(device.candidates, list(ALL_MODELS))
        self.assertEqual(device.confidence, UNKNOWN)
        self.assertEqual(device.reported_model, "unknown")

    def test_a_contradicting_signal_is_recorded_not_obeyed(self):
        """ASR biasing (§3.4): a mis-heard answer is evidence, not a 7th model."""
        device = DeviceIdentification()
        device.add_signal(ModelSignal.from_probe("touch_or_buttons", "touch", 1))
        device.add_signal(ModelSignal.from_probe("lens_count", "two", 2))
        self.assertEqual(device.candidates, [R3])
        self.assertEqual(
            [s.applied for s in device.evidence],
            [True, False],
            "the contradicting signal is kept but not applied, so it cannot "
            "count toward the two-signals-in-agreement rule",
        )
        self.assertEqual(device.confidence, PROBABLE)

    def test_reported_model_is_never_unknown_above_unknown_confidence(self):
        """The invariant, over every rung of the ladder and every answer."""
        answers = [
            ("ssid", "ROVE_R2-4K_8F2A1C"),
            ("ssid", "ROVE_R2-4K-DUAL_5B11"),
            ("ssid", "ROVE_R2-4K-DUAL_PRO"),
            ("ssid", "Rove_R3_9A77"),
            ("ssid", "BTHub-7742"),
            ("lens_count", "just the one"),
            ("lens_count", "there's a second one"),
            ("lens_count", "three"),
            ("lens_count", "I haven't counted"),
            ("touch_or_buttons", "I tap the screen"),
            ("touch_or_buttons", "buttons on the side"),
            ("touch_or_buttons", "no idea"),
            ("connector", "it goes in either way up"),
            ("connector", "only one way"),
            ("serial", "R2041577301"),
            ("serial", "can't read it"),
            ("band", "it's 2.4 GHz, there's nothing to switch"),
            ("band", "5GHz"),
            ("in_box", "there was a CPL filter"),
            ("in_box", "a second camera for the back window"),
            ("name", "R3"),
            ("name", "the 4K one"),
        ]
        for first in answers:
            for second in answers:
                device = DeviceIdentification()
                device.add_signal(ModelSignal.from_probe(*first, 1))
                device.add_signal(ModelSignal.from_probe(*second, 2))
                with self.subTest(first=first, second=second):
                    if device.confidence == UNKNOWN:
                        self.assertEqual(device.reported_model, "unknown")
                    else:
                        self.assertNotEqual(
                            device.reported_model,
                            "unknown",
                            "confidence above UNKNOWN with no model to report is "
                            "the M1 defect Milestone 3.1 fixes",
                        )
                        self.assertTrue(
                            device.narrowed,
                            "confidence may only rise once a signal has narrowed",
                        )

    def test_eval_02_and_eval_06_no_longer_report_unknown_at_probable(self):
        """The two scenarios Run A lost M1 on, driven through a whole turn.

        Both are graded `expected_device: unknown`, and neither utterance names
        a model. The classifier is scripted to emit the kind of unanchored
        feature signal Nova Micro produced on them; the turn must come back
        `unknown` **at UNKNOWN**, not `unknown` at `PROBABLE`.
        """
        for scenario_id, signal in (
            ("EVAL-02", {"signal": "lens_count", "value": "I'm not sure"}),
            ("EVAL-06", {"signal": "ssid", "value": "the one on the screen"}),
        ):
            with self.subTest(scenario=scenario_id):
                state = _state_for(scenario_id)
                entry = "SD-01" if scenario_id == "EVAL-02" else "WIFI-03"
                scripted = ScriptedLLM(
                    Classification(
                        category=entry.split("-")[0],
                        taxonomy_ids=[entry],
                        model_signals=[signal],
                    ),
                    TurnDecision(
                        category=entry.split("-")[0],
                        taxonomy_id=entry,
                        next_step=None,
                        hypothesis="",
                        escalate=False,
                        reason="",
                    ),
                )
                core.diagnose(
                    state.problem.verbatim_symptom, state, llm=scripted
                )
                self.assertEqual(state.device.confidence, UNKNOWN)
                self.assertEqual(state.device.reported_model, "unknown")

    def test_a_real_ssid_read_back_resolves_a_model_instead_of_unknown(self):
        """The positive control: a ladder that never fires is also broken."""
        state = _state_for("EVAL-06")
        scripted = ScriptedLLM(
            Classification(
                category="WIFI",
                taxonomy_ids=["WIFI-03"],
                model_signals=[{"signal": "ssid", "value": "ROVE_R2-4K-DUAL_PRO"}],
            ),
            TurnDecision(
                category="WIFI",
                taxonomy_id="WIFI-03",
                next_step=None,
                hypothesis="",
                escalate=False,
                reason="",
            ),
        )
        core.diagnose(state.problem.verbatim_symptom, state, llm=scripted)
        self.assertNotEqual(state.device.confidence, UNKNOWN)
        self.assertEqual(state.device.reported_model, R2_4K_DUAL_PRO)


# --------------------------------------------------------------------------
# 6. Escalation: a classification is not a trigger (Milestone 3.1)
# --------------------------------------------------------------------------


class TestEscalationNeedsATrigger(unittest.TestCase):
    """`docs/06` §5.1: escalation fires from a trigger, not from uncertainty."""

    def _state(self) -> DiagnosticState:
        return DiagnosticState(
            session_id="escalation-test",
            safety=Safety(driving="no", footage_at_stake="none"),
            problem=Problem(verbatim_symptom="it does something odd now and then"),
            ledger=Ledger(),
        )

    def test_a_no_match_vote_with_a_routable_alternative_does_not_escalate(self):
        decision = policy.escalation(
            self._state(),
            taxonomy_id="NO_MATCH",
            legal_steps=["STEP.ASK.PHYSICAL_TRAUMA_HISTORY"],
            flags=[],
            routable_alternatives=["SD-01"],
        )
        self.assertFalse(decision.escalate)
        self.assertTrue(decision.declined, "the declined vote is kept for the trace")

    def test_an_out_of_scope_vote_with_a_routable_alternative_does_not_escalate(self):
        decision = policy.escalation(
            self._state(),
            taxonomy_id="OUT_OF_SCOPE",
            legal_steps=["STEP.ESCALATE.OUT_OF_SCOPE_TRANSFER"],
            flags=[],
            routable_alternatives=["SD-04"],
        )
        self.assertFalse(decision.escalate)

    def test_no_match_from_triage_with_nothing_else_still_escalates(self):
        """§5.1 structural trigger. Removing it would be the EVAL-28 failure."""
        decision = policy.escalation(
            self._state(),
            taxonomy_id="NO_MATCH",
            legal_steps=["STEP.ASK.PHYSICAL_TRAUMA_HISTORY"],
            flags=[],
            routable_alternatives=[],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "no_match")

    def test_the_keyword_detector_still_escalates_an_out_of_scope_request(self):
        """EVAL-29: a refund is §5.1 item 1, whatever the classifier thinks."""
        decision = policy.escalation(
            self._state(),
            taxonomy_id="SD-04",
            legal_steps=["STEP.CARD.REPLACE_CARD"],
            flags=["out_of_scope"],
            routable_alternatives=[],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "out_of_scope")

    def test_fw_02_still_escalates_immediately(self):
        """`docs/02` FW-02: "immediately, in parallel with any step"."""
        decision = policy.escalation(
            self._state(),
            taxonomy_id="FW-02",
            legal_steps=["STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR"],
            flags=[],
            routable_alternatives=["PWR-04"],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "suspected_brick")

    def test_a_hazard_still_escalates(self):
        state = self._state()
        state.safety.hazard_flags.append("burning_smell")
        decision = policy.escalation(
            state,
            taxonomy_id="PWR-02",
            legal_steps=["STEP.ASK.RECOVERS_WHEN_COOL"],
            flags=["hazard"],
            routable_alternatives=[],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "hazard")

    def test_an_empty_legal_set_still_escalates(self):
        decision = policy.escalation(
            self._state(),
            taxonomy_id="SD-01",
            legal_steps=[],
            flags=[],
            routable_alternatives=[],
        )
        self.assertTrue(decision.escalate)
        self.assertEqual(decision.reason_code, "no_legal_step")

    def test_an_unverified_entry_is_flagged_and_still_not_escalated(self):
        """Unchanged by Milestone 3.1, and `docs/03` requires it to be.

        EVAL-14, EVAL-19, EVAL-21 and EVAL-23 all sit on `UNVERIFIED` entries
        and all expect a diagnostic question with no escalation.
        """
        state = self._state()
        state.problem.taxonomy_id = "APP-02"
        self.assertFalse(state.speakable_as_fix)
        decisions = policy.candidate_steps(state, taxonomy_id="APP-02")
        kept = [d for d in decisions if d.kept]
        self.assertTrue(kept)
        self.assertIn("unverified-entry", kept[0].flags)
        decision = policy.escalation(
            state,
            taxonomy_id="APP-02",
            legal_steps=policy.legal_step_ids(decisions),
            flags=[],
            routable_alternatives=[],
        )
        self.assertFalse(decision.escalate)

    def test_a_whole_turn_ignores_the_classifiers_escalation_flags(self):
        """End to end: the classifier reaches, the policy declines.

        Nova Micro flagged `out_of_scope` and `requests_human` on scenarios
        about a failing card and a wrong timestamp, and voted `NO_MATCH` on a
        dead camera. Each one was an escalation false positive. None of the
        three is in the caller's own words, so none of them may escalate.
        """
        state = _state_for("EVAL-08")
        scripted = ScriptedLLM(
            Classification(
                category="NO_MATCH",
                taxonomy_ids=["NO_MATCH", "VID-03"],
                flags=["out_of_scope", "requests_human", "hazard"],
            ),
            TurnDecision(
                category="VID",
                taxonomy_id="VID-03",
                next_step="STEP.ASK.SPLIT_SYMPTOMS_AUDIO_FIRST",
                hypothesis="Audio and timestamp are two separate things.",
                escalate=True,
                reason="split the symptoms",
            ),
        )
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=scripted
        )
        self.assertFalse(
            result.escalate,
            f"escalated on classifier flags alone: {result.trace.get('escalation')}",
        )
        self.assertNotIn("NO_MATCH", result.trace["shortlist"])
        self.assertEqual(result.taxonomy_id, "VID-03")
        self.assertIsNotNone(result.step_id)

    def test_a_turn_that_does_not_escalate_never_proposes_a_handoff(self):
        """The pairing that would leak a declined trigger back out."""
        scenarios = load_scenarios()
        agent = core.CoreAgent(llm=FailingLLM())
        for scenario in scenarios:
            output = agent.propose(state_from_scenario(scenario))
            with self.subTest(scenario=scenario.id):
                if output.step_id is not None and not output.escalate:
                    self.assertNotEqual(
                        ontology.STEPS[output.step_id].family,
                        "FAMILY.ESCALATE",
                        "a handoff step without an escalation is a contradiction",
                    )


# --------------------------------------------------------------------------
# 7. The unmatched-symptom exit from triage (Milestone 3.3)
# --------------------------------------------------------------------------


class TestUnmatchedSymptomCombination(unittest.TestCase):
    """`docs/06` §3.2: `TRIAGE` exits with a taxonomy ID **or** `NO_MATCH`.

    Milestone 3.1 read "`NO_MATCH` from triage" as "no other shortlisted entry
    has a legal step", which let `PWR-02` — one of EVAL-28's three symptoms, no
    mention of heat anywhere — defeat `NO_MATCH`. §4.7 has a name for that:
    "force it into the nearest category... the EVAL-28 failure and the most
    damaging thing the agent can do".
    """

    def test_only_eval_28_reports_a_symptom_outside_the_taxonomy(self):
        """The guard that keeps this from touching the other 29 scenarios.

        `assess` will not conclude `NO_MATCH` unless some reported facet is
        explained by no `docs/02` entry at all. If that were true of a routable
        scenario it would be a new false positive, so it is asserted directly
        rather than inferred from a run.
        """
        for scenario in load_scenarios():
            with self.subTest(scenario=scenario.id):
                facets = symptoms.reported_facets(scenario.utterance)
                unmapped = symptoms.unmapped_facets(facets)
                if scenario.id == "EVAL-28":
                    self.assertEqual(
                        sorted(unmapped), ["audible_noise", "display_artefact"]
                    )
                else:
                    self.assertEqual(sorted(unmapped), [])

    def test_no_taxonomy_entry_at_all_can_route_eval_28(self):
        """Not "the classifier happened to offer PWR-02" — all 28 of them.

        This is what makes the fix independent of what Nova Micro says on the
        day: whatever entry triage shortlists, it explains at most one of the
        three reported symptoms and its discriminating condition is absent.
        """
        utterance = next(
            s.utterance for s in load_scenarios() if s.id == "EVAL-28"
        )
        facets = symptoms.reported_facets(utterance)
        self.assertEqual(len(facets), 3)
        for entry in ontology.TAXONOMY_CANDIDATES:
            if entry in ("NO_MATCH", "OUT_OF_SCOPE"):
                continue
            with self.subTest(entry=entry):
                self.assertTrue(
                    symptoms.is_nearest_category_force(entry, utterance, facets),
                    f"{entry} would defeat NO_MATCH on EVAL-28",
                )

    def test_an_eval_28_shaped_turn_escalates_with_the_model_up(self):
        """The regression itself: classifier offers NO_MATCH *and* PWR-02."""
        state = _state_for("EVAL-28")
        scripted = ScriptedLLM(
            Classification(
                category="PWR",
                taxonomy_ids=["NO_MATCH", "PWR-02"],
            ),
            TurnDecision(
                category="PWR",
                taxonomy_id="PWR-02",
                next_step="STEP.ASK.RECOVERS_WHEN_COOL",
                hypothesis="Sounds like it is overheating.",
                escalate=False,
                reason="nearest category",
            ),
        )
        result = core.diagnose(state.problem.verbatim_symptom, state, llm=scripted)
        self.assertEqual(result.taxonomy_id, "NO_MATCH")
        self.assertTrue(
            result.escalate,
            f"EVAL-28 must escalate: {result.trace.get('escalation')}",
        )
        self.assertIn(
            result.step_id,
            ("STEP.ESCALATE.HANDOFF", "STEP.ASK.PHYSICAL_TRAUMA_HISTORY"),
        )
        self.assertNotEqual(result.step_id, "STEP.ASK.RECOVERS_WHEN_COOL")
        self.assertIn("triage_no_match", result.trace)

    def test_an_eval_28_shaped_turn_escalates_with_the_model_down(self):
        """Same answer with no Bedrock: the mechanism is in the code, not the
        prompt. The keyword router alone offers `PWR-04` here, on the "time"
        inside "sometimes"."""
        state = _state_for("EVAL-28")
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=FailingLLM()
        )
        self.assertEqual(result.taxonomy_id, "NO_MATCH")
        self.assertTrue(result.escalate)

    def test_a_no_match_vote_with_a_genuine_single_symptom_route_still_routes(self):
        """Milestone 3.1's fix, unweakened. One symptom, one entry that
        explains it — a `NO_MATCH` vote alongside is a vote, not a trigger."""
        state = _state_for("EVAL-02")  # "card error", and nothing else
        scripted = ScriptedLLM(
            Classification(
                category="SD",
                taxonomy_ids=["NO_MATCH", "SD-01"],
                flags=["out_of_scope"],
            ),
            TurnDecision(
                category="SD",
                taxonomy_id="SD-01",
                next_step="STEP.ASK.CARD_BRAND_AND_SPEED",
                hypothesis="Could be the card's speed rating.",
                escalate=True,
                reason="unsure",
            ),
        )
        result = core.diagnose(state.problem.verbatim_symptom, state, llm=scripted)
        self.assertEqual(result.taxonomy_id, "SD-01")
        self.assertFalse(
            result.escalate,
            f"a single-symptom route must not escalate: "
            f"{result.trace.get('escalation')}",
        )
        self.assertNotIn("NO_MATCH", result.trace["shortlist"])
        self.assertNotIn("triage_no_match", result.trace)

    def test_a_candidate_explaining_half_the_symptoms_is_still_a_route(self):
        """EVAL-25: two symptoms, `SD-03` explains one. Strictly a minority is
        the test, not "fewer than all" — `docs/03` grades EVAL-25 as no
        escalation, and EVAL-24's `REC-04` sits in the same shape."""
        for scenario_id, entry in (("EVAL-25", "SD-03"), ("EVAL-24", "REC-04")):
            utterance = next(
                s.utterance for s in load_scenarios() if s.id == scenario_id
            )
            facets = symptoms.reported_facets(utterance)
            with self.subTest(scenario=scenario_id):
                self.assertEqual(len(facets), 2)
                self.assertFalse(
                    symptoms.is_nearest_category_force(entry, utterance, facets)
                )
                self.assertFalse(symptoms.assess(utterance, [entry]).unmatched)

    def test_a_volunteered_discriminating_condition_keeps_the_entry_routable(self):
        """EVAL-23 hands over "it's been really hot today" — `PWR-02`'s own
        condition, verbatim. That is a re-rank, not a forced category."""
        utterance = next(
            s.utterance for s in load_scenarios() if s.id == "EVAL-23"
        )
        self.assertTrue(symptoms.discriminator_present("PWR-02", utterance))
        self.assertFalse(
            symptoms.is_nearest_category_force(
                "PWR-02", utterance, symptoms.reported_facets(utterance)
            )
        )

    def test_sometimes_does_not_read_as_time(self):
        """The substring bug the keyword router has and this must not: EVAL-28
        contains no date or clock complaint, so `PWR-04`'s discriminator is
        absent."""
        utterance = next(
            s.utterance for s in load_scenarios() if s.id == "EVAL-28"
        )
        self.assertIn("sometimes", utterance.lower())
        self.assertFalse(symptoms.discriminator_present("PWR-04", utterance))
        self.assertNotIn("clock_loss", symptoms.reported_facets(utterance))

    def test_every_entry_in_the_signature_tables_is_a_real_taxonomy_entry(self):
        """Two tables transcribed from `docs/02` are two things that can drift
        from it. This catches a typo'd id, which would silently make an entry
        un-creditable and therefore always a force."""
        known = {
            e
            for e in ontology.TAXONOMY_CANDIDATES
            if e not in ("NO_MATCH", "OUT_OF_SCOPE")
        }
        self.assertEqual(set(symptoms.ENTRY_EXPLAINS), known)
        self.assertEqual(set(symptoms.ENTRY_DISCRIMINATORS), known)
        for entry, facets in symptoms.ENTRY_EXPLAINS.items():
            with self.subTest(entry=entry):
                self.assertTrue(facets, f"{entry} explains nothing")
                self.assertTrue(facets <= set(symptoms.FACET_PATTERNS))


# --------------------------------------------------------------------------
# The attempt ceiling counts attempts (Milestone 4.8)
# --------------------------------------------------------------------------


class TestTheAttemptCeilingCountsAttempts(unittest.TestCase):
    """`docs/02` cross-cutting trigger 1: *two steps **attempted** with no change*.

    Milestone 4.8, and the EVAL-27 over-escalation. A question is not an
    attempt — `docs/06` §3.6 says so when it exempts `FAMILY.ASK` and
    `FAMILY.OBSERVE` from no-repeat, because their product is information
    rather than a change to the device. An answered question is still recorded
    with a blocking outcome (`unclear` is the fail-safe §3.6 mapping), so the
    two readings of that one ledger entry have to stay apart: it blocks itself,
    and it does not count toward the ceiling.
    """

    def _state(self) -> DiagnosticState:
        return DiagnosticState(
            session_id="ceiling-test",
            safety=Safety(driving="no", footage_at_stake="none"),
            problem=Problem(verbatim_symptom="nothing new on the card"),
            ledger=Ledger(),
        )

    def test_two_answered_questions_do_not_breach_the_ceiling(self):
        state = self._state()
        state.record_attempt("STEP.ASK.CARD_SPECS_AND_RATING", "unclear")
        state.record_attempt("STEP.ASK.CARD_FROZEN_IN_TIME", "unclear")
        self.assertEqual(state.ledger.agent_proposed_failures(), 0)
        self.assertEqual(state.ceiling_breaches(), [])

    def test_two_failed_actions_still_breach_it(self):
        state = self._state()
        state.record_attempt("STEP.CARD.RESEAT", "no_change")
        state.record_attempt("STEP.DEVICE.POWER_CYCLE", "no_change")
        self.assertEqual(state.ledger.agent_proposed_failures(), 2)
        self.assertTrue(
            any("attempted" in b for b in state.ceiling_breaches()),
            "trigger 1 has to survive the fix — this is the EVAL-12 direction",
        )

    def test_an_answered_question_does_not_top_up_a_single_failed_action(self):
        """The exact EVAL-27 shape: one failed action, then two questions."""
        state = self._state()
        state.record_attempt("STEP.CARD.RESEAT", "no_change")
        state.record_attempt("STEP.ASK.CARD_SPECS_AND_RATING", "not_attempted")
        state.record_attempt("STEP.ASK.CARD_FROZEN_IN_TIME", "unclear")
        self.assertEqual(state.ledger.agent_proposed_failures(), 1)
        self.assertEqual(state.ceiling_breaches(), [])
        decision = policy.escalation(
            state,
            taxonomy_id="SD-01",
            legal_steps=["STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST"],
            flags=[],
            routable_alternatives=[],
        )
        self.assertFalse(
            decision.escalate,
            f"EVAL-27 escalated on {decision.triggers}; docs/03 says no escalation",
        )

    def test_the_answered_question_is_still_blocked_by_no_repeat(self):
        """The fix may not buy itself room by weakening the ledger."""
        state = self._state()
        state.record_attempt("STEP.ASK.CARD_FROZEN_IN_TIME", "unclear")
        self.assertIn("STEP.ASK.CARD_FROZEN_IN_TIME", state.ledger.blocked)

    def test_information_only_is_a_property_of_the_family_not_the_outcome(self):
        for family_id, family in ontology.FAMILIES.items():
            entry = ontology.AttemptedStep(
                step_id="STEP.CARD.RESEAT",  # id is not read; the family is
                step_family=family_id,
                source="agent_proposed",
                outcome="no_change",
            )
            self.assertEqual(entry.information_only, family.no_repeat_exempt)


# --------------------------------------------------------------------------
# Retrieval, enough to know the citations are real
# --------------------------------------------------------------------------


class TestRetrievalGrounding(unittest.TestCase):
    def test_only_tier_1_speakable_chunks_are_retrievable(self):
        for chunk in retrieval.speakable_chunks():
            self.assertEqual(chunk.tier, 1)

    def test_every_cited_chunk_id_resolves(self):
        state = _state_for("EVAL-02")
        result = core.diagnose(
            state.problem.verbatim_symptom, state, llm=FailingLLM()
        )
        self.assertTrue(result.citations, "EVAL-02 should retrieve something")
        resolved = retrieval.chunks_by_id(result.citations)
        self.assertEqual(len(resolved), len(result.citations))


if __name__ == "__main__":
    unittest.main()
