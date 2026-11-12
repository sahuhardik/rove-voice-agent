"""Tests for the LangGraph orchestration of `docs/06` §3.2 (§8.6, D-13).

Four things are worth asserting about a graph whose whole claim is that it is
the hand-written state machine with the plumbing already written:

1. **It compiles**, with one node per §3.2 state and no edge that is not in
   §3.2's transition table.
2. **An illegal transition is refused** — and refused by the typed record, not
   by the graph, so that a router bug cannot talk its way past it.
3. **A checkpoint resumes**: the same `thread_id` continues the session rather
   than restarting it, which is §1.4.2's reconnect-and-resume and the reason
   §8.6 chose a library with checkpointing at all.
4. **The graph changes nothing about the answer.** The same nodes driven by a
   plain loop produce the same turn on all 30 scenarios — if they did not, the
   overhead measurement would be comparing two different agents.

    .venv/bin/python -m unittest agent.test_graph
"""

from __future__ import annotations

import inspect
import unittest

from langgraph.graph import END

from agent import core, graph
from agent.llm import NullLLM
from agent.state import (
    LEGAL_TRANSITIONS,
    DiagnosticState,
    State,
    TransitionError,
)
from eval import ontology
from eval.harness import load_scenarios


class FailingLLM:
    """Every call raises. The floor has to hold without a model."""

    def classify(self, utterance):  # noqa: ANN001, ANN201
        raise RuntimeError("no model")

    def decide(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("no model")


def fresh(session_id: str = "graph-test") -> DiagnosticState:
    return DiagnosticState(session_id=session_id)


# --------------------------------------------------------------------------
# 1. It compiles, and it is the §3.2 machine
# --------------------------------------------------------------------------


class TestTheGraphCompiles(unittest.TestCase):
    def test_it_compiles(self):
        app = graph.compiled_graph(fresh=True)
        self.assertIsNotNone(app)

    def test_one_node_per_state(self):
        self.assertEqual(len(graph.NODE_FUNCTIONS), 13)
        self.assertEqual(
            set(graph.NODE_FOR_STATE.values()), set(graph.NODE_FUNCTIONS)
        )
        self.assertEqual(set(graph.NODE_FOR_STATE), set(State))

    def test_the_compiled_graph_has_exactly_those_nodes(self):
        app = graph.compiled_graph(fresh=True)
        nodes = set(app.get_graph().nodes) - {"__start__", "__end__"}
        self.assertEqual(nodes, set(graph.NODE_FUNCTIONS))

    def test_every_wired_edge_is_in_the_transition_table(self):
        """The table is `agent/state.py`'s, imported. No edge is invented here."""
        for src, dst in graph._LEGAL_EDGES:
            with self.subTest(edge=f"{src}->{dst}"):
                self.assertIn(
                    graph.STATE_FOR_NODE[dst],
                    LEGAL_TRANSITIONS[graph.STATE_FOR_NODE[src]],
                )

    def test_the_routers_can_only_return_a_table_edge_or_end(self):
        for node, targets in graph.EDGE_MAP.items():
            for target in targets:
                if target is END:
                    continue
                with self.subTest(edge=f"{node}->{target}"):
                    self.assertIn(
                        graph.STATE_FOR_NODE[target],
                        LEGAL_TRANSITIONS[graph.STATE_FOR_NODE[node]],
                    )

    def test_every_router_is_a_pure_function_of_the_graph_state(self):
        """No router may see the model, the utterance or the retrieved chunks.

        `docs/06` §8.6's review rule is that the graph is authored, never
        planned. A router that took the run context could read the model's
        output; one that takes only the state dict cannot.
        """
        for name, router in graph.ROUTERS.items():
            with self.subTest(router=name):
                params = list(inspect.signature(router).parameters)
                self.assertEqual(params, ["gstate"])
        self.assertEqual(
            list(inspect.signature(graph.route_entry).parameters), ["gstate"]
        )

    def test_no_planner_or_agent_framework_pattern_is_imported(self):
        """`docs/06` §8.6 option C is the thing being deliberately removed."""
        source = inspect.getsource(graph)
        for banned in (
            "langgraph.prebuilt",
            "create_react_agent",
            "ToolNode",
            "tools_condition",
            "bind_tools",
            "AgentExecutor",
        ):
            with self.subTest(pattern=banned):
                self.assertNotIn(banned, source)


# --------------------------------------------------------------------------
# 2. An illegal transition is rejected
# --------------------------------------------------------------------------


class TestIllegalTransitionsAreRejected(unittest.TestCase):
    def test_enter_refuses_a_move_the_table_does_not_allow(self):
        state = fresh()
        self.assertIs(state.state, State.GREET)
        with self.assertRaises(TransitionError):
            graph.enter(state, State.CLOSE, "greet straight to close")

    def test_the_refusal_names_the_legal_set(self):
        state = fresh()
        with self.assertRaises(TransitionError) as caught:
            graph.enter(state, State.PROPOSE_STEP, "skipping the filter")
        self.assertIn("GREET -> PROPOSE_STEP", str(caught.exception))
        self.assertIn("SYMPTOM_CAPTURE", str(caught.exception))

    def test_a_router_that_proposes_an_illegal_node_is_refused_at_runtime(self):
        """The guarantee is in the typed record, not in the edge map.

        A graph that wired `TRIAGE -> PROPOSE_STEP` would skip the §3.5 filter
        chain entirely, so this
        builds exactly that — router and edge map both altered, as a bad change
        would alter them — and asserts the turn still refuses to make the move.
        """
        builder = graph.build_graph()
        compiled = builder.compile(checkpointer=graph.make_checkpointer())
        self.assertIsNotNone(compiled)

        original_router = graph.ROUTERS["triage"]
        original_edges = dict(graph.EDGE_MAP["triage"])
        try:
            graph.ROUTERS["triage"] = lambda gstate: "propose_step"
            graph.EDGE_MAP["triage"] = {"propose_step": "propose_step"}
            bad = graph.build_graph().compile(checkpointer=graph.make_checkpointer())
            with self.assertRaises(TransitionError):
                graph.run_turn(
                    "the wifi will not connect",
                    fresh("illegal-edge"),
                    llm=None,
                    graph=bad,
                )
        finally:
            graph.ROUTERS["triage"] = original_router
            graph.EDGE_MAP["triage"] = original_edges

    def test_the_plain_loop_refuses_the_same_move(self):
        original_router = graph.ROUTERS["triage"]
        try:
            graph.ROUTERS["triage"] = lambda gstate: "propose_step"
            with self.assertRaises(TransitionError):
                graph.run_turn_direct(
                    "the wifi will not connect", fresh("illegal-direct"), llm=None
                )
        finally:
            graph.ROUTERS["triage"] = original_router

    def test_the_whole_table_is_enforced_both_ways(self):
        """Every pair of states: legal in the table ⇔ accepted by the record."""
        for src in State:
            for dst in State:
                if src is dst:
                    continue
                state = fresh()
                state.state = src
                legal = dst in LEGAL_TRANSITIONS[src]
                with self.subTest(src=src.value, dst=dst.value, legal=legal):
                    if legal:
                        graph.enter(state, dst, "table says yes")
                        self.assertIs(state.state, dst)
                    else:
                        with self.assertRaises(TransitionError):
                            graph.enter(state, dst, "table says no")


# --------------------------------------------------------------------------
# 3. Checkpoint resume
# --------------------------------------------------------------------------


class TestCheckpointResume(unittest.TestCase):
    def setUp(self):
        self.app = graph.compiled_graph(fresh=True)
        self.llm = NullLLM()
        self.state = fresh("resume-session")
        self.first = graph.run_turn(
            "the app will not connect to the camera wifi",
            self.state,
            llm=self.llm,
            thread_id="thread-resume",
            graph=self.app,
        )

    def test_the_first_turn_stops_with_a_step_proposed(self):
        self.assertIsNotNone(self.first.step_id)
        self.assertIs(self.state.state, State.PROPOSE_STEP)
        self.assertEqual(self.state.turn, 1)

    def test_the_checkpoint_holds_the_typed_record(self):
        snapshot = self.app.get_state(
            {"configurable": {"thread_id": "thread-resume"}}
        )
        stored = snapshot.values["diagnostic"]
        self.assertIsInstance(stored, DiagnosticState)
        self.assertEqual(stored.session_id, "resume-session")
        self.assertEqual(snapshot.values["fsm_state"], State.PROPOSE_STEP.value)

    def test_resuming_continues_the_session_instead_of_restarting_it(self):
        second = graph.resume_turn(
            "I tried that, still the same",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        )
        resumed = second.state
        # Continued, not restarted: turn 2, and the record came back out of the
        # checkpointer rather than from the object the caller still holds.
        self.assertEqual(resumed.turn, 2)
        self.assertIsNot(resumed, self.state)
        self.assertEqual(resumed.session_id, "resume-session")
        self.assertEqual(
            resumed.problem.verbatim_symptom,
            "the app will not connect to the camera wifi",
        )

    def test_the_resumed_turn_walks_the_continuing_path_of_32(self):
        graph.resume_turn(
            "I tried that, still the same",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        )
        snapshot = self.app.get_state(
            {"configurable": {"thread_id": "thread-resume"}}
        )
        visited = [entry[0] for entry in snapshot.values["diagnostic"].history]
        self.assertEqual(
            visited[-5:],
            [
                State.AWAIT_OUTCOME,
                State.EVALUATE_OUTCOME,
                State.HYPOTHESISE,
                State.SELECT_STEP,
                State.PROPOSE_STEP,
            ],
        )

    def test_the_ledger_survives_the_resume_and_blocks_the_step(self):
        first_step = self.first.step_id
        second = graph.resume_turn(
            "I tried that, still the same",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        )
        attempted = [a.step_id for a in second.state.ledger.attempted]
        self.assertEqual(attempted, [first_step])
        self.assertNotEqual(second.step_id, first_step)
        self.assertNotIn(
            ontology.STEPS[first_step].family,
            [
                ontology.STEPS[s].family
                for s in [second.step_id]
                if s is not None
            ],
        )

    def test_a_success_closes_the_session(self):
        graph.resume_turn(
            "I tried that, still the same",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        )
        third = graph.resume_turn(
            "that fixed it, it is working now",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        )
        self.assertIs(third.state.state, State.CLOSE)
        self.assertEqual(third.state.turn, 3)

    def test_two_threads_do_not_see_each_other(self):
        other = fresh("other-session")
        graph.run_turn(
            "my memory card keeps giving an error",
            other,
            llm=self.llm,
            thread_id="thread-other",
            graph=self.app,
        )
        resumed = graph.resume_turn(
            "no change",
            thread_id="thread-resume",
            llm=self.llm,
            graph=self.app,
        ).state
        self.assertEqual(resumed.session_id, "resume-session")
        self.assertEqual(
            resumed.problem.verbatim_symptom,
            "the app will not connect to the camera wifi",
        )

    def test_resuming_an_unknown_thread_is_an_error_not_a_fresh_session(self):
        with self.assertRaises(KeyError):
            graph.resume_turn(
                "hello?", thread_id="never-seen", llm=self.llm, graph=self.app
            )


# --------------------------------------------------------------------------
# 4. The graph does not change the answer
# --------------------------------------------------------------------------


class TestTheGraphIsTheSameMachine(unittest.TestCase):
    """`run_turn_direct` is §8.6 option A built from the same nodes and the
    same routers. If the two disagreed on any scenario, the overhead number
    would be comparing two different agents."""

    def test_both_paths_agree_on_all_thirty_scenarios(self):
        llm = NullLLM()
        for scenario in load_scenarios():
            with self.subTest(scenario=scenario.id):
                a = fresh(f"{scenario.id}-graph")
                a.problem.verbatim_symptom = scenario.utterance
                b = fresh(f"{scenario.id}-direct")
                b.problem.verbatim_symptom = scenario.utterance
                via_graph = graph.run_turn(scenario.utterance, a, llm=llm)
                direct = graph.run_turn_direct(scenario.utterance, b, llm=llm)
                self.assertEqual(via_graph.step_id, direct.step_id)
                self.assertEqual(via_graph.escalate, direct.escalate)
                self.assertEqual(via_graph.taxonomy_id, direct.taxonomy_id)
                self.assertEqual(via_graph.response_text, direct.response_text)
                self.assertEqual(via_graph.citations, direct.citations)
                self.assertEqual(a.state, b.state)

    def test_the_hard_constraints_hold_through_the_graph_with_no_model(self):
        """M4 and M5 are code, not prompt, and the graph did not move them.

        Graded by Harness A itself, through `core.diagnose` — which now goes
        through the graph — so this is the same claim `agent/test_core.py`
        makes, re-asserted against the new orchestration.
        """
        from eval.harness import run_harness

        report = run_harness(core.CoreAgent(llm=FailingLLM()), load_scenarios())
        breaches = [
            (r.scenario_id, r.m4_breaches + r.m5_breaches)
            for r in report.results
            if not r.m4_no_repeat or not r.m5_harmful
        ]
        self.assertEqual(breaches, [])


# --------------------------------------------------------------------------
# The §8.6 flip-condition measurement
# --------------------------------------------------------------------------


class TestTheOverheadIsMeasurable(unittest.TestCase):
    def test_the_benchmark_reports_an_overhead(self):
        numbers = graph.benchmark(1)
        for key in (
            "direct_mean_ms",
            "graph_mean_ms",
            "overhead_mean_ms",
            "checkpoint_write_mean_ms",
        ):
            self.assertIn(key, numbers)
        self.assertEqual(numbers["turns"], 30.0)
        self.assertGreater(numbers["graph_mean_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
