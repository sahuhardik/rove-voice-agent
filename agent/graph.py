"""The `docs/06` §3.2 state machine, as a LangGraph `StateGraph` (§8.6, D-13).

`docs/06` §8.6 chose option B — LangGraph `StateGraph` — **as an implementation
of option A, the explicit hand-written state machine, not as a replacement for
it**. Everything in this module follows from that one sentence:

* **The graph is authored, never planned.** Every node is one of our own
  functions from `agent/core.py`, `agent/policy.py` and `agent/retrieval.py`.
  Every edge is a pure function of the typed state record. **No node is ever
  reached by model choice**, there is no planner, no tool-calling loop, no
  agent-framework prebuilt anywhere in this file, and the LLM is called only
  *inside* `core.step_triage` and `core.step_select_step` — as a function, at a
  bounded point, over a set the filter chain has already narrowed.
* **The edges are the §3.2 table, not a new one.** `_ALLOWED` below *is*
  `agent.state.LEGAL_TRANSITIONS`, imported rather than re-typed, and
  `_LEGAL_EDGES` asserts at import time that every edge this module wires is in
  it. A second copy of that table would be a second thing to drift.
* **Every transition goes through `DiagnosticState.transition`**, which raises
  `TransitionError` on an illegal move. The router may only *propose* a
  successor; the typed record is what accepts or refuses it. An illegal edge is
  therefore impossible to add silently, whether a human or a model writes it.
* **The checkpointer persists `DiagnosticState` per turn.** Phase 1 uses
  langgraph's in-memory `InMemorySaver`; the Postgres checkpointer of §8.5 /
  D-12 is Phase 2 and there is no Postgres yet. The channel that is checkpointed
  is the typed record of §3.3 — the per-turn working set (retrieval hits, filter
  verdicts, the option list) rides `core.TurnContext` in the run context and is
  deliberately **not** persisted, which keeps the per-turn checkpoint write of
  §2.2 line 4 proportional to the record rather than to the corpus.
* **Human-in-the-loop interrupts** are where §5.3's escalation and §6.4's
  destructive gate live: `ESCALATE` and `CLOSE` end the turn, `PROPOSE_STEP`
  ends it waiting at `AWAIT_OUTCOME`, and `DESTRUCTIVE_GATE` reads a consent
  record that only an external decision can fill in. Resuming is one more
  `invoke` on the same `thread_id`.

Running the per-turn overhead measurement that §8.6's flip condition needs:

    .venv/bin/python -m agent.graph --bench 30

prints the mean per-turn cost of the graph against `run_turn_direct` — the same
nodes and the same routers driven by a plain loop, which is option A exactly.
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass, is_dataclass
from enum import Enum
from inspect import isclass
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from agent import core
from agent.state import (
    LEGAL_TRANSITIONS,
    DiagnosticState,
    State,
    TransitionError,
)

# --------------------------------------------------------------------------
# The state the graph carries
# --------------------------------------------------------------------------


class DiagnosticGraphState(TypedDict, total=False):
    """The checkpointed channels: the typed record of §3.3, plus the scalars
    the routers read.

    Every field here is either `DiagnosticState` itself or something derived
    from it that an edge condition needs. The routers are pure functions over
    this dict — they never see the utterance, the retrieved chunks or anything
    the model produced, which is what makes "no node is reached by model
    choice" checkable by reading ten lines rather than the whole module.
    """

    session_id: str
    #: `State.value` — the FSM position the next turn resumes from.
    fsm_state: str
    turn: int
    #: Routing scalars, written by the nodes.
    model_signals: bool
    step_id: str | None
    step_destructive: bool
    gate_allows: bool
    escalate: bool
    outcome: str
    resolved: bool
    #: The durable record. This is what the checkpointer persists.
    diagnostic: DiagnosticState
    #: The last thing the agent said, kept so a resumed session can be replayed.
    response_text: str
    citations: list[str]
    taxonomy_id: str


#: The §3.2 transition table, imported, never re-typed.
_ALLOWED: dict[State, frozenset[State]] = LEGAL_TRANSITIONS

#: One node per state. `docs/06` §3.2 names thirteen states and this names
#: thirteen nodes: the states *are* the nodes.
NODE_FOR_STATE: dict[State, str] = {
    State.GREET: "greet",
    State.SYMPTOM_CAPTURE: "symptom_capture",
    State.TRIAGE: "triage",
    State.MODEL_ID: "model_id",
    State.HYPOTHESISE: "hypothesise",
    State.SELECT_STEP: "select_step",
    State.DESTRUCTIVE_GATE: "destructive_gate",
    State.PROPOSE_STEP: "propose_step",
    State.AWAIT_OUTCOME: "await_outcome",
    State.EVALUATE_OUTCOME: "evaluate_outcome",
    State.VERIFY_RESOLVED: "verify_resolved",
    State.ESCALATE: "escalate",
    State.CLOSE: "close",
}
STATE_FOR_NODE: dict[str, State] = {v: k for k, v in NODE_FOR_STATE.items()}

assert len(NODE_FOR_STATE) == len(State) == 13, "one node per §3.2 state"

#: The turn-step functions, by node. These are the functions the rest of the
#: package already uses; the graph adds sequencing and nothing else.
NODE_FUNCTIONS: dict[str, Callable[[DiagnosticState, core.TurnContext], None]] = {
    "greet": core.step_greet,
    "symptom_capture": core.step_symptom_capture,
    "triage": core.step_triage,
    "model_id": core.step_model_id,
    "hypothesise": core.step_hypothesise,
    "select_step": core.step_select_step,
    "destructive_gate": core.step_destructive_gate,
    "propose_step": core.step_propose_step,
    "await_outcome": core.step_await_outcome,
    "evaluate_outcome": core.step_evaluate_outcome,
    "verify_resolved": core.step_verify_resolved,
    "escalate": core.step_escalate,
    "close": core.step_close,
}


# --------------------------------------------------------------------------
# Edges — every one of them in the §3.2 table
# --------------------------------------------------------------------------

#: The edges this graph wires, as (from, to) node names. Checked against the
#: imported transition table at import time, below.
_LEGAL_EDGES: tuple[tuple[str, str], ...] = (
    ("greet", "symptom_capture"),
    ("greet", "escalate"),
    ("symptom_capture", "triage"),
    ("symptom_capture", "escalate"),
    ("triage", "model_id"),
    ("triage", "hypothesise"),
    ("triage", "escalate"),
    ("model_id", "hypothesise"),
    ("model_id", "escalate"),
    ("hypothesise", "select_step"),
    ("hypothesise", "escalate"),
    ("select_step", "destructive_gate"),
    ("select_step", "propose_step"),
    ("select_step", "escalate"),
    ("destructive_gate", "propose_step"),
    ("destructive_gate", "select_step"),
    ("destructive_gate", "escalate"),
    ("propose_step", "await_outcome"),
    ("await_outcome", "evaluate_outcome"),
    ("await_outcome", "escalate"),
    ("evaluate_outcome", "hypothesise"),
    ("evaluate_outcome", "verify_resolved"),
    ("evaluate_outcome", "escalate"),
    ("verify_resolved", "close"),
    ("verify_resolved", "hypothesise"),
    ("escalate", "close"),
)

for _from, _to in _LEGAL_EDGES:
    assert (
        STATE_FOR_NODE[_to] in _ALLOWED[STATE_FOR_NODE[_from]]
    ), f"{_from} -> {_to} is not in docs/06 §3.2's transition table"


def enter(state: DiagnosticState, target: State, reason: str = "") -> None:
    """Move the FSM into `target`, refusing an illegal move loudly.

    This is the single choke point: a node cannot run without passing through
    it, and it delegates to `DiagnosticState.transition`, which raises
    `TransitionError` against the §3.2 table. The graph's edges and the typed
    record cannot disagree about what is legal, because only one of them is
    allowed to decide.
    """
    if state.state is target:
        return
    state.transition(target, reason)


# --------------------------------------------------------------------------
# Routers. Pure functions over the graph state — no model, ever.
# --------------------------------------------------------------------------


def route_entry(gstate: DiagnosticGraphState) -> str:
    """Where this turn starts, given where the last one stopped.

    This is what makes a resumed session continue rather than restart: the
    checkpoint holds `fsm_state`, and a session that stopped at `PROPOSE_STEP`
    opens its next turn at `AWAIT_OUTCOME` — the §3.2 edge that follows a
    spoken step — not back at `GREET`.
    """
    fsm = State(gstate.get("fsm_state", State.GREET.value))
    if fsm is State.PROPOSE_STEP:
        return "await_outcome"
    if fsm is State.ESCALATE:
        return "close"
    if fsm is State.CLOSE:
        return END
    return NODE_FOR_STATE[fsm]


def route_greet(gstate: DiagnosticGraphState) -> str:
    return "symptom_capture"


def route_symptom_capture(gstate: DiagnosticGraphState) -> str:
    return "triage"


def route_triage(gstate: DiagnosticGraphState) -> str:
    """§3.2: `MODEL_ID` "may run in parallel or be deferred"."""
    return "model_id" if gstate.get("model_signals") else "hypothesise"


def route_model_id(gstate: DiagnosticGraphState) -> str:
    return "hypothesise"


def route_hypothesise(gstate: DiagnosticGraphState) -> str:
    return "select_step"


def route_select_step(gstate: DiagnosticGraphState) -> str:
    """§3.2: an escalation leaves the main path; a destructive step goes
    through the gate; everything else is spoken."""
    if gstate.get("escalate"):
        return "escalate"
    if gstate.get("step_destructive"):
        return "destructive_gate"
    return "propose_step"


def route_destructive_gate(gstate: DiagnosticGraphState) -> str:
    """Consent granted → speak it. Refused → back to `SELECT_STEP`, which will
    not offer that step again (§3.2: "refusal is final for that step")."""
    return "propose_step" if gstate.get("gate_allows") else "select_step"


def route_propose_step(gstate: DiagnosticGraphState) -> str:
    """The turn ends with the step spoken. The next one resumes at
    `AWAIT_OUTCOME` through `route_entry`."""
    return END


def route_await_outcome(gstate: DiagnosticGraphState) -> str:
    """No turn limit (§3.2): without a reported outcome the turn ends still
    waiting, and the checkpoint keeps the session exactly where it was."""
    return "evaluate_outcome" if gstate.get("outcome") else END


def route_evaluate_outcome(gstate: DiagnosticGraphState) -> str:
    """The ceilings are edge conditions, which is §8.6's phrase for exactly
    this: `01` §5's "silent escalation failure" is a transition, not a prompt."""
    diagnostic = gstate["diagnostic"]
    if diagnostic.ceiling_breaches():
        diagnostic.escalate(
            "ceiling", "; ".join(diagnostic.ceiling_breaches())
        )
        return "escalate"
    if gstate.get("resolved"):
        return "verify_resolved"
    return "hypothesise"


def route_verify_resolved(gstate: DiagnosticGraphState) -> str:
    return "close" if gstate.get("resolved") else "hypothesise"


def route_escalate(gstate: DiagnosticGraphState) -> str:
    """The handoff has been delivered; the session closes on the next turn."""
    return END


def route_close(gstate: DiagnosticGraphState) -> str:
    return END


ROUTERS: dict[str, Callable[[DiagnosticGraphState], str]] = {
    "greet": route_greet,
    "symptom_capture": route_symptom_capture,
    "triage": route_triage,
    "model_id": route_model_id,
    "hypothesise": route_hypothesise,
    "select_step": route_select_step,
    "destructive_gate": route_destructive_gate,
    "propose_step": route_propose_step,
    "await_outcome": route_await_outcome,
    "evaluate_outcome": route_evaluate_outcome,
    "verify_resolved": route_verify_resolved,
    "escalate": route_escalate,
    "close": route_close,
}

#: What each router is allowed to return — the §3.2 successors of that state,
#: plus `END` where a turn stops. Built from `_LEGAL_EDGES`, so a router that
#: returned anything else would fail at the graph level as well as at the
#: `DiagnosticState.transition` level.
EDGE_MAP: dict[str, dict[str, str]] = {node: {} for node in NODE_FUNCTIONS}
for _from, _to in _LEGAL_EDGES:
    EDGE_MAP[_from][_to] = _to
for _node in ("propose_step", "await_outcome", "escalate", "close"):
    EDGE_MAP[_node][END] = END


# --------------------------------------------------------------------------
# The graph
# --------------------------------------------------------------------------


@dataclass
class _Node:
    """One node: enter the state, run the step function, publish the scalars
    the routers read."""

    name: str

    def __call__(
        self, gstate: DiagnosticGraphState, runtime: Runtime[core.TurnContext]
    ) -> dict[str, Any]:
        diagnostic: DiagnosticState = gstate["diagnostic"]
        ctx = runtime.context
        enter(diagnostic, STATE_FOR_NODE[self.name], f"{self.name} (graph)")
        NODE_FUNCTIONS[self.name](diagnostic, ctx)
        return publish(diagnostic, ctx)


def publish(
    diagnostic: DiagnosticState, ctx: core.TurnContext
) -> dict[str, Any]:
    """The node → channel update. Everything a router reads is written here.

    Returning `diagnostic` explicitly is what makes the checkpointer re-serialise
    the record after a node mutated it in place.
    """
    update: dict[str, Any] = {
        "diagnostic": diagnostic,
        "fsm_state": diagnostic.state.value,
        "turn": diagnostic.turn,
        "model_signals": core.has_model_signals(ctx),
        "step_id": ctx.chosen_step_id,
        "step_destructive": core.selected_step_is_destructive(ctx),
        "gate_allows": core.gate_allows_step(ctx),
        "escalate": bool(ctx.escalation.escalate) if ctx.escalation else False,
        "outcome": ctx.reported_outcome,
        "resolved": core.outcome_resolved(ctx),
        "taxonomy_id": ctx.taxonomy_id,
    }
    if ctx.result is not None:
        update["response_text"] = ctx.result.response_text
        update["citations"] = list(ctx.result.citations)
    return update


def build_graph() -> StateGraph:
    """Wire the §3.2 state machine. Nodes are ours; edges are the table."""
    builder = StateGraph(DiagnosticGraphState, context_schema=core.TurnContext)
    for name in NODE_FUNCTIONS:
        builder.add_node(name, _Node(name))
    builder.add_conditional_edges(
        START,
        route_entry,
        {node: node for node in NODE_FUNCTIONS} | {END: END},
    )
    for name, router in ROUTERS.items():
        builder.add_conditional_edges(name, router, EDGE_MAP[name])
    return builder


def checkpointed_types() -> list[type]:
    """Exactly the classes the typed record of §3.3 is made of.

    langgraph will not rebuild a type it was not told about — it hands back the
    raw payload instead — so the allowlist is what makes a resumed session a
    `DiagnosticState` rather than a dict shaped like one. Derived from the
    module rather than typed out, because a hand-maintained list of thirteen
    dataclasses is a list that goes stale the first time one is added.
    """
    from eval import ontology

    from agent import state as state_module

    allowed = [
        obj
        for obj in vars(state_module).values()
        if isclass(obj)
        and obj.__module__ == state_module.__name__
        and (is_dataclass(obj) or issubclass(obj, Enum))
    ]
    allowed.append(ontology.AttemptedStep)
    return allowed


def make_checkpointer() -> InMemorySaver:
    """`docs/06` §8.6's checkpointer, Phase 1 edition.

    In-memory, because Phase 1 is one process and there is no Postgres yet
    (§8.5, D-12 — that is Phase 2). The serializer is told about our own types
    so a checkpoint round-trips the typed record rather than a dict that merely
    looks like one.
    """
    return InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=checkpointed_types())
    )


_COMPILED: Any | None = None
_CHECKPOINTER: InMemorySaver | None = None


def compiled_graph(*, fresh: bool = False) -> Any:
    """The compiled graph, with the Phase 1 checkpointer attached.

    Compiled once per process: compilation is the expensive part and the graph
    is a constant. `fresh=True` builds a new one with a new checkpointer, which
    is what a test that wants an empty session store asks for.
    """
    global _COMPILED, _CHECKPOINTER
    if fresh:
        return build_graph().compile(checkpointer=make_checkpointer())
    if _COMPILED is None:
        _CHECKPOINTER = make_checkpointer()
        _COMPILED = build_graph().compile(checkpointer=_CHECKPOINTER)
    return _COMPILED


# --------------------------------------------------------------------------
# Running a turn
# --------------------------------------------------------------------------


def initial_graph_state(
    state: DiagnosticState, *, utterance: str
) -> DiagnosticGraphState:
    return {
        "session_id": state.session_id,
        "fsm_state": state.state.value,
        "turn": state.turn,
        "diagnostic": state,
        "model_signals": False,
        "step_id": state.notes.get("proposed_step_id"),
        "step_destructive": False,
        "gate_allows": False,
        "escalate": False,
        "outcome": "",
        "resolved": False,
        "response_text": "",
        "citations": [],
        "taxonomy_id": state.problem.taxonomy_id or "",
    }


def run_turn(
    utterance: str,
    state: DiagnosticState,
    *,
    llm: Any | None = None,
    chunks_path: str | None = None,
    thread_id: str | None = None,
    outcome: str = "",
    graph: Any | None = None,
) -> core.TurnResult:
    """One turn, through the graph. The public entry point is `core.diagnose`.

    `thread_id` is the checkpoint key: re-invoking with the same one resumes
    the session where the last turn left it (§1.4.2's reconnect-and-resume,
    which is the reason §8.6 chose a library with checkpointing at all). With
    no `thread_id`, the session id is used, which is what Harness A's one-turn
    scenarios want.
    """
    app = graph if graph is not None else compiled_graph()
    ctx = core.TurnContext(
        llm=llm,
        chunks_path=chunks_path,
        utterance=utterance,
        reported_outcome=outcome,
    )
    core.begin_turn(state, ctx)
    app.invoke(
        initial_graph_state(state, utterance=utterance),
        config={"configurable": {"thread_id": thread_id or state.session_id}},
        context=ctx,
    )
    return _result_or_empty(state, ctx)


def resume_turn(
    utterance: str,
    *,
    thread_id: str,
    llm: Any | None = None,
    chunks_path: str | None = None,
    outcome: str = "",
    graph: Any | None = None,
) -> core.TurnResult:
    """Continue a session from its checkpoint alone (§1.4.2, §8.6).

    `run_turn` treats the `DiagnosticState` it is handed as authoritative,
    which is what a one-turn harness scenario wants. This is the other case —
    the browser dropped its peer connection and all that survived is the thread
    id — so the record comes back out of the checkpointer and the turn carries
    on from the state it stopped in. Nothing is re-run and nothing restarts.
    """
    app = graph if graph is not None else compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = app.get_state(config)
    values = snapshot.values or {}
    state = values.get("diagnostic")
    if not isinstance(state, DiagnosticState):
        raise KeyError(
            f"no checkpointed session for thread_id {thread_id!r} — there is "
            "nothing to resume"
        )
    return run_turn(
        utterance,
        state,
        llm=llm,
        chunks_path=chunks_path,
        thread_id=thread_id,
        outcome=outcome,
        graph=app,
    )


def run_turn_direct(
    utterance: str,
    state: DiagnosticState,
    *,
    llm: Any | None = None,
    chunks_path: str | None = None,
    outcome: str = "",
) -> core.TurnResult:
    """The same nodes and the same routers, driven by a plain loop.

    This is `docs/06` §8.6 option A — the hand-written state machine — built
    from exactly the pieces the graph uses, so the difference between this and
    `run_turn` is LangGraph's per-turn cost and nothing else. It exists to
    measure §8.6's flip condition honestly; it is not a second implementation
    of the policy, and nothing in the package calls it except the benchmark.
    """
    ctx = core.TurnContext(
        llm=llm,
        chunks_path=chunks_path,
        utterance=utterance,
        reported_outcome=outcome,
    )
    core.begin_turn(state, ctx)
    gstate = initial_graph_state(state, utterance=utterance)
    node = route_entry(gstate)
    while node is not END:
        enter(state, STATE_FOR_NODE[node], f"{node} (direct)")
        NODE_FUNCTIONS[node](state, ctx)
        gstate.update(publish(state, ctx))
        nxt = ROUTERS[node](gstate)
        if nxt is not END and nxt not in EDGE_MAP[node]:
            raise TransitionError(f"{node} -> {nxt} is not a §3.2 edge")
        node = nxt
    return _result_or_empty(state, ctx)


def _result_or_empty(
    state: DiagnosticState, ctx: core.TurnContext
) -> core.TurnResult:
    """Every path through the graph composes a turn except one: a session
    already at `CLOSE` has nothing left to say."""
    if ctx.result is not None:
        return ctx.result
    return core.TurnResult(
        response_text="",
        state=state,
        citations=[],
        taxonomy_id=state.problem.taxonomy_id or "",
        category=state.problem.category or "",
        step_id=None,
        escalate=state.escalation.triggered,
        rationale="session is closed; no further turn",
        trace=ctx.trace,
    )


# --------------------------------------------------------------------------
# The §8.6 flip-condition measurement
# --------------------------------------------------------------------------


def benchmark(repeats: int = 30, *, chunks_path: str | None = None) -> dict[str, float]:
    """Per-turn cost of the graph against the same turn without it.

    Both paths run the same nodes over the same scenarios with the LLM stubbed
    out (`agent.llm.NullLLM`), so what is left is LangGraph's own per-turn
    overhead: the channel writes, the super-step bookkeeping and the checkpoint
    serialisation. That number is what `docs/06` §8.6 says must be measured
    rather than assumed, against §2.2 line 4.
    """
    from agent.llm import NullLLM
    from eval.harness import load_scenarios

    utterances = [s.utterance for s in load_scenarios()]
    llm = NullLLM()
    checkpointed = compiled_graph(fresh=True)
    #: The same graph with no checkpointer, to split LangGraph's own per-turn
    #: cost from the cost of persisting the record. Phase 2 swaps the saver for
    #: Postgres (§8.5), and that swap only moves the second number.
    uncheckpointed = build_graph().compile()

    def one(fn: Callable[..., core.TurnResult], utterance: str, i: int) -> float:
        state = DiagnosticState(session_id=f"bench-{i}")
        state.problem.verbatim_symptom = utterance
        started = time.perf_counter()
        fn(utterance, state, llm=llm, chunks_path=chunks_path)
        return (time.perf_counter() - started) * 1000.0

    def direct_turn(utterance: str, state: DiagnosticState, **kw: Any) -> core.TurnResult:
        return run_turn_direct(utterance, state, **kw)

    def graph_turn(utterance: str, state: DiagnosticState, **kw: Any) -> core.TurnResult:
        return run_turn(utterance, state, graph=checkpointed, **kw)

    def bare_turn(utterance: str, state: DiagnosticState, **kw: Any) -> core.TurnResult:
        return run_turn(utterance, state, graph=uncheckpointed, **kw)

    # A warm pass each: the corpus is cached after the first retrieval and the
    # graph compiles on first use. Neither is a per-turn cost.
    for warm in (direct_turn, graph_turn, bare_turn):
        one(warm, utterances[0], -1)

    direct: list[float] = []
    graphed: list[float] = []
    bare: list[float] = []
    for r in range(repeats):
        for i, utterance in enumerate(utterances):
            direct.append(one(direct_turn, utterance, r * 1000 + i))
            graphed.append(one(graph_turn, utterance, r * 1000 + i))
            bare.append(one(bare_turn, utterance, r * 1000 + i))

    return {
        "turns": float(len(direct)),
        "direct_mean_ms": statistics.mean(direct),
        "direct_median_ms": statistics.median(direct),
        "graph_no_checkpoint_mean_ms": statistics.mean(bare),
        "graph_mean_ms": statistics.mean(graphed),
        "graph_median_ms": statistics.median(graphed),
        "overhead_mean_ms": statistics.mean(graphed) - statistics.mean(direct),
        "overhead_median_ms": statistics.median(graphed) - statistics.median(direct),
        "checkpoint_write_mean_ms": statistics.mean(graphed) - statistics.mean(bare),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.graph", description=__doc__)
    parser.add_argument(
        "--bench",
        type=int,
        default=0,
        metavar="N",
        help="measure the per-turn graph overhead over N passes of the 30 scenarios",
    )
    args = parser.parse_args(argv)
    if args.bench:
        numbers = benchmark(args.bench)
        width = max(len(k) for k in numbers)
        for key, value in numbers.items():
            print(f"{key:<{width}}  {value:10.3f}")
        print()
        print(
            "docs/06 §2.2 line 4 budgets 20 ms median / 50 ms p95 for the safety "
            "gate, FSM and policy filters together."
        )
        return 0
    app = compiled_graph(fresh=True)
    print(f"compiled: {len(NODE_FUNCTIONS)} nodes, {len(_LEGAL_EDGES)} §3.2 edges")
    try:
        print(app.get_graph().draw_ascii())
    except ImportError:
        # `draw_ascii` needs grandalf, which is an optional langchain extra and
        # not a dependency of anything this package does at runtime. The edge
        # list below is the same information without it.
        for source, target in sorted(_LEGAL_EDGES):
            print(f"  {source} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
