"""The §2.2 latency budget, measured (`docs/06` §2.2, §7.2 M7, §7.5).

`docs/06` §2.2 is a table of **nine** components and three columns of budget,
and it says what it is:

> All three columns below are **budgets, not measurements** — no pipeline
> exists and nothing has been built. They exist to make the trade-offs
> arguable and to give the instrumentation something to compare against.

This module is that instrumentation. §7.5 asks for "the 9-component latency
decomposition" on *every* turn's trace record, and §7.2 asks for "median, p95,
and the component breakdown — a single number hides which of lines 2/6/7
moved". So the unit of work here is one :class:`TurnLatency` per voice turn,
written whole into the trace as `latency.turn`, plus :func:`summarise` over a
session's worth of them.

Where each line comes from
--------------------------

| # | §2.2 component | how it is obtained here |
|---|---|---|
| 1 | browser capture → WebRTC uplink + jitter buffer | **UNMEASURED** — needs a browser |
| 2 | endpoint decision | the silence the endpointer waited out, from `endpoint.fired` |
| 3 | ASR final flush | `TranscribeStream.await_final`, wall clock |
| 4 | safety gate + FSM + policy | **derived**: core total − (5 + 6 + 8) |
| 5 | RAG retrieval not hidden by prefetch | every `agent.retrieval.retrieve` inside the turn |
| 6 | LLM time-to-first-token | every `classify`/`decide` inside the turn (see the caveat) |
| 7 | TTS time-to-first-audio | the wait before the first PCM frame was pushed |
| 8 | output guard | every `agent.core.output_guard` inside the turn |
| 9 | WebRTC downlink + browser playout | **UNMEASURED** — needs a browser |

**Lines 1 and 9 are UNMEASURED and say so in every record.** They are
properties of a browser leg, and the only peer that has ever been on this link
is `server/livekit_peer.py`, which is two processes on one host. `server/
README.md` has said since Phase 2b why a sub-millisecond loopback RTT is not
evidence about a laptop on domestic broadband, and the rule this module
enforces is the consequence: a loopback number is never written into line 1 or
line 9. Harness C measures the loopback leg it *can* see and reports it under
its own name (`loopback_ms`), never as a browser number.

**The line 6 caveat, stated once and carried in every record.** §2.2 line 6 is
*time to first token*. `agent/llm.py` calls Bedrock `Converse`, which is not
streaming, so what is measurable here is the **whole call**. That is an upper
bound on time-to-first-token, not the same quantity, and `measured="whole_call"`
rides on the line so a reader cannot mistake one for the other.

**Line 4 is derived, not measured.** The gate, the FSM and the policy filters
are interleaved with retrieval and the model inside one `agent.core.diagnose`
call, and §2.2 budgets them at 20 ms — small enough that instrumenting them
individually would mean editing `agent/`, which this milestone does not do.
Subtracting what *is* measured from the core's own wall clock is the honest
remainder, and `status="derived"` says so.

How the decomposition is taken without touching `agent/`
--------------------------------------------------------

The same way `eval/grounding.py` already captures the guard's per-line verdict:
by wrapping module globals for the duration of a run. `agent/core.py` looks
`output_guard` and `retrieval.retrieve` up as module attributes on every call,
so :func:`install` can swap them for timing wrappers once, at import of the
server, and nothing in `agent/` changes. The wrappers consult a
:class:`threading.local`, so a turn running on one worker thread cannot see
another turn's clock — and `server/prefetch.py`'s speculative retrieval, which
runs on its own thread with nothing installed, is correctly *not* counted
against line 5. That is the point: line 5 is "retrieval **not hidden by
prefetch**".
"""

from __future__ import annotations

import contextlib
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence

from agent import core as agent_core
from agent import retrieval as agent_retrieval

# --------------------------------------------------------------------------
# The table (docs/06 §2.2)
# --------------------------------------------------------------------------

#: A line whose value is not obtainable from this process. Written into the
#: trace as the value, so that a reader parsing a record cannot silently treat
#: an absent number as a zero.
UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class BudgetLine:
    """One row of §2.2's table, copied without rounding."""

    number: int
    name: str
    best_ms: float
    median_ms: float
    p95_ms: float
    #: `measured` — a clock in this process times it.
    #: `derived` — it is what is left of a measured total.
    #: `unmeasurable_here` — §2.2 lines 1 and 9: it needs a browser.
    status: str
    note: str = ""

    @property
    def key(self) -> str:
        return f"line{self.number}"


#: §2.2's nine components, verbatim, with the budget columns as written.
BUDGET: tuple[BudgetLine, ...] = (
    BudgetLine(
        1,
        "browser capture → WebRTC uplink + jitter buffer",
        15.0,
        25.0,
        70.0,
        "unmeasurable_here",
        "needs a real browser leg; a loopback peer is a different link",
    ),
    BudgetLine(
        2,
        "endpoint decision (Silero VAD v5 hangover + semantic classifier)",
        150.0,
        250.0,
        650.0,
        "measured",
        "the silence waited out before the turn closed (server/endpointing.py)",
    ),
    BudgetLine(
        3,
        "ASR final flush after endpoint",
        40.0,
        80.0,
        200.0,
        "measured",
        "TranscribeStream.await_final",
    ),
    BudgetLine(
        4,
        "safety gate + FSM + policy filters",
        5.0,
        20.0,
        50.0,
        "derived",
        "core wall clock minus lines 5, 6 and 8",
    ),
    BudgetLine(
        5,
        "RAG retrieval not hidden by prefetch",
        0.0,
        30.0,
        240.0,
        "measured",
        "agent.retrieval.retrieve inside the turn; speculative retrieval is not counted",
    ),
    BudgetLine(
        6,
        "LLM time-to-first-token",
        180.0,
        300.0,
        850.0,
        "measured",
        "whole Converse call, which is an upper bound on time-to-first-token",
    ),
    BudgetLine(
        7,
        "TTS time-to-first-audio",
        70.0,
        120.0,
        320.0,
        "measured",
        "wait before the first PCM frame of the first clause was pushed",
    ),
    BudgetLine(
        8,
        "output guard",
        1.0,
        5.0,
        10.0,
        "measured",
        "agent.core.output_guard inside the turn",
    ),
    BudgetLine(
        9,
        "WebRTC downlink + browser playout",
        15.0,
        30.0,
        80.0,
        "unmeasurable_here",
        "needs a real browser leg; includes the playout buffer barge-in flushes",
    ),
)

BUDGET_BY_NUMBER: dict[int, BudgetLine] = {line.number: line for line in BUDGET}

#: §2.2's own total row, for the median column.
TARGET_MEDIAN_TOTAL_MS = 860.0

#: `01` M7 — "the line that must not be crossed at the median" (§2.2).
M7_CEILING_MS = 1200.0

#: The lines this process can put a clock on. 1 and 9 are not among them and
#: never will be from here.
MEASURABLE_LINES: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8)

#: What lines 2–8 add up to in §2.2's median column. The comparison the
#: instrumentation can actually make, since 1 and 9 are unmeasured.
MEASURABLE_TARGET_MEDIAN_MS = sum(
    BUDGET_BY_NUMBER[n].median_ms for n in MEASURABLE_LINES
)


# --------------------------------------------------------------------------
# The per-turn record
# --------------------------------------------------------------------------


@dataclass
class CoreBreakdown:
    """Lines 4, 5, 6 and 8, taken apart from outside `agent/`.

    Filled by the wrappers :func:`install` puts on `agent.retrieval.retrieve`,
    `agent.retrieval.rerank` and `agent.core.output_guard`, plus the wrapper
    :func:`timed_llm` puts round the model handle. `total_ms` is set by the
    caller from its own clock round `agent.core.diagnose`.
    """

    total_ms: float = 0.0
    retrieval_ms: float = 0.0
    llm_ms: float = 0.0
    guard_ms: float = 0.0
    retrieval_calls: int = 0
    llm_calls: int = 0
    guard_calls: int = 0
    #: Model calls that raised. `agent/core.py` catches them and drops to its
    #: rule-based floor, so the turn still answers — but §2.4 Tier 3's second
    #: trigger is "or primary LLM erroring", and this is the only place in the
    #: process that sees one without reading the core's internals.
    llm_errors: int = 0
    #: Which model ids the turn actually reached, so a Tier-3 reroute is a
    #: fact in the record rather than an inference from the tier number.
    llm_models: list[str] = field(default_factory=list)

    @property
    def gate_fsm_policy_ms(self) -> float:
        """§2.2 line 4, as the remainder. Never negative.

        A clamp rather than a signed residual: the three measured parts are
        sampled with `perf_counter` inside the same call the total is timed
        round, so the remainder is non-negative up to clock granularity, and a
        -0.1 ms line 4 in a trace would read as a defect rather than as noise.
        """
        rest = self.total_ms - self.retrieval_ms - self.llm_ms - self.guard_ms
        return round(max(0.0, rest), 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_ms": round(self.total_ms, 2),
            "line4_gate_fsm_policy_ms": self.gate_fsm_policy_ms,
            "line5_retrieval_ms": round(self.retrieval_ms, 2),
            "line6_llm_ms": round(self.llm_ms, 2),
            "line8_guard_ms": round(self.guard_ms, 2),
            "retrieval_calls": self.retrieval_calls,
            "llm_calls": self.llm_calls,
            "llm_errors": self.llm_errors,
            "guard_calls": self.guard_calls,
            "llm_models": list(self.llm_models),
        }


@dataclass
class TurnLatency:
    """§2.2's nine lines for one turn, and what they add up to.

    Every field that §2.2 numbers is here, including the two that cannot be
    filled: :attr:`line1_ms` and :attr:`line9_ms` stay `None` and serialise as
    the string :data:`UNMEASURED`.
    """

    turn: int = 0
    modality: str = "voice"

    line1_ms: float | None = None  # browser uplink — UNMEASURED
    line2_ms: float | None = None  # endpoint decision
    line3_ms: float | None = None  # ASR final flush
    line5_ms: float | None = None  # retrieval
    line6_ms: float | None = None  # LLM
    line7_ms: float | None = None  # TTS time-to-first-audio
    line8_ms: float | None = None  # output guard
    line9_ms: float | None = None  # browser downlink — UNMEASURED

    #: Line 4 is the remainder of the core's own wall clock.
    core_total_ms: float = 0.0
    line4_ms: float | None = None

    #: End of speech → first sample pushed into the room, taken as one wall
    #: clock rather than as the sum of the lines. §7.2's M7, minus lines 1 and
    #: 9, which is as much of M7 as this process can see.
    m7_server_ms: float | None = None
    #: `reply` or `filler` — §2.4 Tier 0 allows a filler to be the first
    #: audible thing, and an M7 median that blends the two is not an M7 median.
    first_audible: str = "reply"

    turn_type: str = ""
    hangover_ms: int = 0
    prefetch: str = "none"
    ladder_tier: int = 0
    llm_models: list[str] = field(default_factory=list)
    notes: str = ""

    # -- the lines, as a list ---------------------------------------------

    def value(self, number: int) -> float | None:
        return getattr(self, f"line{number}_ms")

    def lines(self) -> list[dict[str, Any]]:
        """All nine, in §2.2's order, each carrying its own budget and status."""
        out: list[dict[str, Any]] = []
        for budget in BUDGET:
            value = self.value(budget.number)
            if budget.status == "unmeasurable_here":
                status, rendered = UNMEASURED, UNMEASURED
            elif value is None:
                status, rendered = "absent", None
            else:
                status, rendered = budget.status, round(value, 2)
            out.append(
                {
                    "line": budget.number,
                    "name": budget.name,
                    "ms": rendered,
                    "status": status,
                    "budget_median_ms": budget.median_ms,
                    "budget_p95_ms": budget.p95_ms,
                    "over_median_budget": (
                        bool(value > budget.median_ms) if isinstance(value, float) else None
                    ),
                    "note": budget.note,
                }
            )
        return out

    @property
    def measured_total_ms(self) -> float:
        """Lines 2–8. The only total this process is entitled to produce."""
        return round(
            sum(v for n in MEASURABLE_LINES if (v := self.value(n)) is not None), 2
        )

    def as_event(self) -> dict[str, Any]:
        """The record §7.5 asks for, in one trace event."""
        return {
            "turn": self.turn,
            "modality": self.modality,
            "lines": self.lines(),
            "measured_total_ms": self.measured_total_ms,
            "measurable_target_median_ms": round(MEASURABLE_TARGET_MEDIAN_MS, 1),
            "budget_total_median_ms": TARGET_MEDIAN_TOTAL_MS,
            "m7_server_ms": (
                round(self.m7_server_ms, 2) if self.m7_server_ms is not None else None
            ),
            "m7_ceiling_ms": M7_CEILING_MS,
            "first_audible": self.first_audible,
            "browser_lines": {
                "line1": UNMEASURED,
                "line9": UNMEASURED,
                "why": (
                    "lines 1 and 9 are properties of a browser leg; no browser has "
                    "been on this link, and a loopback peer is a different link "
                    "(server/README.md)"
                ),
            },
            "core_total_ms": round(self.core_total_ms, 2),
            "turn_type": self.turn_type,
            "hangover_ms": self.hangover_ms,
            "prefetch": self.prefetch,
            "ladder_tier": self.ladder_tier,
            "llm_models": list(self.llm_models),
            "notes": self.notes,
        }

    def apply_core(self, breakdown: CoreBreakdown) -> "TurnLatency":
        self.core_total_ms = breakdown.total_ms
        self.line4_ms = breakdown.gate_fsm_policy_ms
        self.line5_ms = round(breakdown.retrieval_ms, 2)
        self.line6_ms = round(breakdown.llm_ms, 2)
        self.line8_ms = round(breakdown.guard_ms, 2)
        self.llm_models = list(breakdown.llm_models)
        return self


# --------------------------------------------------------------------------
# The core probe: lines 5, 6 and 8, from outside agent/
# --------------------------------------------------------------------------


class _Current(threading.local):
    """Per-thread: what this thread's turn is recording, and under what shed."""

    breakdown: CoreBreakdown | None = None
    shed: Any = None


_CURRENT = _Current()
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_REAL_RETRIEVE: Any = None
_REAL_RERANK: Any = None
_REAL_GUARD: Any = None


def current_shed() -> Any:
    """The shed in force on this thread, or `None` outside a measured turn."""
    return _CURRENT.shed


def install() -> None:
    """Wrap the three `agent/` entry points lines 5, 6 and 8 run through.

    Idempotent, process-wide, and reversible (:func:`uninstall`). Nothing in
    `agent/` is edited: the wrapped names are module attributes that
    `agent/core.py` and `agent/retrieval.py` look up on every call, which is
    the same seam `eval/grounding.py` uses to capture guard verdicts.

    Outside a :func:`measure_core` block the wrappers are a single `is None`
    test and a call, so installing them costs the eval harnesses nothing.
    """
    global _INSTALLED, _REAL_RETRIEVE, _REAL_RERANK, _REAL_GUARD
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _REAL_RETRIEVE = agent_retrieval.retrieve
        _REAL_RERANK = agent_retrieval.rerank
        _REAL_GUARD = agent_core.output_guard

        def retrieve(query: str, **kwargs: Any) -> Any:
            breakdown, shed = _CURRENT.breakdown, _CURRENT.shed
            if breakdown is None:
                return _REAL_RETRIEVE(query, **kwargs)
            if shed is not None:
                # §2.4 Tier 1: "cut retrieval `k` from 8 to 4". The 8 is
                # §4.6's `hybrid_k` — the candidate set the reranker sees —
                # and overriding it at the call is a shed rather than a change
                # to what `agent/retrieval.py` does by default.
                kwargs.setdefault("hybrid_k", agent_retrieval.HYBRID_K)
                kwargs["hybrid_k"] = min(int(kwargs["hybrid_k"]), shed.hybrid_k)
            started = time.perf_counter()
            try:
                return _REAL_RETRIEVE(query, **kwargs)
            finally:
                breakdown.retrieval_ms += (time.perf_counter() - started) * 1000.0
                breakdown.retrieval_calls += 1

        def rerank(hits: Sequence[Any], **kwargs: Any) -> list[Any]:
            shed = _CURRENT.shed
            if shed is not None and not shed.rerank:
                # §2.4 Tier 1: "drop the reranker". The fused order stands,
                # which is exactly what losing the metadata reranker costs.
                return list(hits)
            return _REAL_RERANK(hits, **kwargs)

        def output_guard(lines: Sequence[Any], *, support_text: str = "") -> Any:
            breakdown = _CURRENT.breakdown
            if breakdown is None:
                return _REAL_GUARD(lines, support_text=support_text)
            started = time.perf_counter()
            try:
                return _REAL_GUARD(lines, support_text=support_text)
            finally:
                breakdown.guard_ms += (time.perf_counter() - started) * 1000.0
                breakdown.guard_calls += 1

        agent_retrieval.retrieve = retrieve  # type: ignore[assignment]
        agent_retrieval.rerank = rerank  # type: ignore[assignment]
        agent_core.output_guard = output_guard  # type: ignore[assignment]
        _INSTALLED = True


def uninstall() -> None:
    """Put the real functions back. For tests; the server never calls it."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if not _INSTALLED:
            return
        agent_retrieval.retrieve = _REAL_RETRIEVE  # type: ignore[assignment]
        agent_retrieval.rerank = _REAL_RERANK  # type: ignore[assignment]
        agent_core.output_guard = _REAL_GUARD  # type: ignore[assignment]
        _INSTALLED = False


@contextlib.contextmanager
def measure_core(shed: Any = None) -> Iterator[CoreBreakdown]:
    """Collect lines 5, 6 and 8 for one turn on this thread.

    `shed` is a `server/ladder.Shed` (or `None`). It rides the same
    thread-local as the recorder because the two are asked the same question —
    *what is this thread's turn doing?* — and keeping them together means a
    shed can never outlive the turn that chose it.
    """
    install()
    breakdown = CoreBreakdown()
    previous_breakdown, previous_shed = _CURRENT.breakdown, _CURRENT.shed
    _CURRENT.breakdown, _CURRENT.shed = breakdown, shed
    started = time.perf_counter()
    try:
        yield breakdown
    finally:
        breakdown.total_ms = (time.perf_counter() - started) * 1000.0
        _CURRENT.breakdown, _CURRENT.shed = previous_breakdown, previous_shed


# --------------------------------------------------------------------------
# Line 6: the model handle
# --------------------------------------------------------------------------


class TimedLLM:
    """An `agent.llm.LLM` that charges its calls to §2.2 line 6.

    Also the seam §2.4's Tiers 2 and 3 shed through, because both of them are
    properties of *this call* rather than of the core that makes it:

    * **Tier 2 — shrink the prompt.** "the compact prompt profile: diagnostic
      state + top-3 chunks only". The chunk list handed to `decide` is cut
      here. §2.4's other half — "taxonomy summary instead of full entries" —
      is **not** shed: the taxonomy catalogue is inside `agent/llm.py`'s system
      prompt, and this milestone does not modify `agent/`. `server/README.md`
      states that plainly rather than letting the tier claim more than it does.
    * **Tier 3 — smaller reasoning model.** `decide` is routed at the fast
      model tier, which for `agent/llm.py` means the micro model id in the
      place the pro model id normally goes.

    `classify` is never rerouted: it is already the micro model, and §2.4's
    Tier 3 is about the *reasoning* call.
    """

    def __init__(self, inner: Any, *, breakdown: CoreBreakdown, shed: Any = None) -> None:
        self.inner = inner
        self._breakdown = breakdown
        self._shed = shed

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", "llm")

    def _charge(self, started: float, model: str) -> None:
        self._breakdown.llm_ms += (time.perf_counter() - started) * 1000.0
        self._breakdown.llm_calls += 1
        if model and model not in self._breakdown.llm_models:
            self._breakdown.llm_models.append(model)

    def classify(self, utterance: str) -> Any:
        started = time.perf_counter()
        try:
            return self.inner.classify(utterance)
        except Exception:
            self._breakdown.llm_errors += 1
            raise
        finally:
            self._charge(started, str(getattr(self.inner, "micro_model_id", "") or "classify"))

    def decide(self, **kwargs: Any) -> Any:
        shed = self._shed
        target = self.inner
        model = str(getattr(self.inner, "pro_model_id", "") or "decide")
        if shed is not None and shed.prompt_profile == "compact":
            chunks = kwargs.get("chunks") or []
            kwargs = dict(kwargs)
            kwargs["chunks"] = list(chunks)[: shed.prompt_chunks]
        if shed is not None and shed.model_tier == "fast":
            target = _fast_tier(self.inner)
            model = str(getattr(target, "pro_model_id", "") or "decide-fast")
        started = time.perf_counter()
        try:
            return target.decide(**kwargs)
        except Exception:
            self._breakdown.llm_errors += 1
            raise
        finally:
            self._charge(started, model)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _fast_tier(llm: Any) -> Any:
    """The same handle, reasoning on the fast model tier (§2.4 Tier 3, §8.3).

    A shallow copy with `pro_model_id` pointed at the micro id, cached on the
    original so a sustained Tier 3 does not build a handle per turn. Nothing
    in `agent/llm.py` changes: the model id is a constructor argument and this
    is what supplying a different one looks like from outside.

    Wrappers are unwrapped first. `server/app.py` installs
    `server/prefetch.MemoLLM` round the real handle, and `MemoLLM.__getattr__`
    delegates — so setting `pro_model_id` on the *wrapper* would write a field
    nobody reads while `decide` kept calling the pro model. The copy therefore
    descends to whatever is at the bottom and is rebuilt on the way out.
    """
    import copy

    cached = llm.__dict__.get("_rove_fast_tier") if hasattr(llm, "__dict__") else None
    if cached is not None:
        return cached

    inner = llm.__dict__.get("inner") if hasattr(llm, "__dict__") else None
    if inner is not None:
        fast_inner = _fast_tier(inner)
        if fast_inner is inner:
            return llm
        fast = copy.copy(llm)
        fast.inner = fast_inner
    else:
        micro = getattr(llm, "micro_model_id", None)
        if micro is None or not hasattr(llm, "pro_model_id"):
            return llm
        fast = copy.copy(llm)
        fast.pro_model_id = micro

    with contextlib.suppress(Exception):  # a Protocol stub may be read-only
        llm.__dict__["_rove_fast_tier"] = fast
    return fast


def timed_llm(llm: Any, breakdown: CoreBreakdown, shed: Any = None) -> Any:
    """Wrap a model handle for line 6, honouring the shed. `None` stays `None`.

    §2.4 Tier 4 — "degrade to scripted" — is the one tier that answers `None`:
    `agent/core.py` runs its rule-based floor when there is no model, which is
    exactly the tier's "FSM runs the taxonomy's own `Must ask` questions
    directly as templated speech. No free-form generation."
    """
    if llm is None:
        return None
    if shed is not None and shed.generation == "scripted":
        return None
    return TimedLLM(llm, breakdown=breakdown, shed=shed)


# --------------------------------------------------------------------------
# The session's book, and the summary §7.2 asks for
# --------------------------------------------------------------------------


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def distribution(values: Sequence[float]) -> dict[str, Any] | None:
    """n / min / median / p95 / max, or `None` when nothing was measured."""
    numbers = [float(v) for v in values if v is not None]
    if not numbers:
        return None
    return {
        "n": len(numbers),
        "min": round(min(numbers), 2),
        "median": round(statistics.median(numbers), 2),
        "p95": round(_percentile(numbers, 0.95), 2),
        "max": round(max(numbers), 2),
    }


class LatencyBook:
    """One session's turns, and the running numbers the ladder reads.

    Thread-safe, because the voice path writes it from the media loop and the
    `/healthz` and trace readers read it from the API loop.
    """

    def __init__(self, *, window: int = 20) -> None:
        #: §2.4's tiers 1–3 are keyed off "p95 over a 20-turn window".
        self.window = window
        self._lock = threading.Lock()
        self._turns: list[TurnLatency] = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)

    def record(self, turn: TurnLatency) -> TurnLatency:
        with self._lock:
            self._turns.append(turn)
        return turn

    def turns(self) -> list[TurnLatency]:
        with self._lock:
            return list(self._turns)

    # -- the running numbers ----------------------------------------------

    def _m7_values(self, *, window: int | None = None, replies_only: bool = True) -> list[float]:
        turns = self.turns()
        if window:
            turns = turns[-window:]
        return [
            t.m7_server_ms
            for t in turns
            if t.m7_server_ms is not None
            and (not replies_only or t.first_audible == "reply")
        ]

    def running_median_ms(self, *, window: int | None = None) -> float | None:
        values = self._m7_values(window=window)
        return round(statistics.median(values), 2) if values else None

    def running_p95_ms(self, *, window: int | None = None) -> float | None:
        values = self._m7_values(window=window or self.window)
        return round(_percentile(values, 0.95), 2) if values else None

    def consecutive_breaches(self, threshold_ms: float) -> int:
        """How many of the most recent turns in a row exceeded `threshold_ms`.

        §2.4 Tier 5's trigger is "two consecutive turns breach 4 s", which is a
        statement about the tail of the session and not about a window.
        """
        count = 0
        for turn in reversed(self.turns()):
            if turn.m7_server_ms is None:
                continue
            if turn.m7_server_ms > threshold_ms:
                count += 1
            else:
                break
        return count

    def projected_ms(self) -> float | None:
        """§2.4 Tier 0's "prediction made at endpoint, from live component timings".

        The median of each measurable line so far, added up. `None` until a
        turn has completed: a projection with no live timings in it is a
        restatement of the budget, and §2.4 asks for live timings.
        """
        turns = self.turns()
        if not turns:
            return None
        total = 0.0
        for number in MEASURABLE_LINES:
            values = [v for t in turns if (v := t.value(number)) is not None]
            if values:
                total += statistics.median(values)
        return round(total, 2)

    # -- the session summary (docs/06 §7.2) --------------------------------

    def summary(self) -> dict[str, Any]:
        turns = self.turns()
        per_line: dict[str, Any] = {}
        for budget in BUDGET:
            if budget.status == "unmeasurable_here":
                per_line[budget.key] = {
                    "line": budget.number,
                    "name": budget.name,
                    "status": UNMEASURED,
                    "ms": UNMEASURED,
                    "budget_median_ms": budget.median_ms,
                    "note": budget.note,
                }
                continue
            values = [v for t in turns if (v := t.value(budget.number)) is not None]
            per_line[budget.key] = {
                "line": budget.number,
                "name": budget.name,
                "status": budget.status,
                "distribution_ms": distribution(values),
                "budget_median_ms": budget.median_ms,
                "budget_p95_ms": budget.p95_ms,
                "note": budget.note,
            }
        reply_m7 = [
            t.m7_server_ms for t in turns if t.m7_server_ms is not None and t.first_audible == "reply"
        ]
        filler_m7 = [
            t.m7_server_ms for t in turns if t.m7_server_ms is not None and t.first_audible == "filler"
        ]
        measured_totals = [t.measured_total_ms for t in turns if t.measured_total_ms]
        return {
            "turns": len(turns),
            "per_line": per_line,
            "measured_total_ms": distribution(measured_totals),
            "measurable_target_median_ms": round(MEASURABLE_TARGET_MEDIAN_MS, 1),
            # §7.2: "Turns answered by click or typing are reported
            # separately". Same rule, same reason, for a turn whose first
            # audible sound was §2.4's filler rather than the reply.
            "m7_server_ms": distribution(reply_m7),
            "m7_filler_turns_ms": distribution(filler_m7),
            "m7_ceiling_ms": M7_CEILING_MS,
            "browser_lines_1_and_9": UNMEASURED,
            "browser_lines_note": (
                "lines 1 and 9 need a browser leg. The headless peer measures its "
                "own loopback leg and Harness C reports it under `loopback_ms`; it "
                "is never quoted as a browser number (server/README.md)."
            ),
        }


# --------------------------------------------------------------------------
# Reading a trace back
# --------------------------------------------------------------------------


def summarise(events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The same summary, rebuilt from `latency.turn` events in a trace.

    `server/trace.py` calls this so that a session summary carries the §7.2
    breakdown whether or not the process that wrote the trace is still alive.
    """
    records = [e for e in events if e.get("type") == "latency.turn"]
    if not records:
        return None
    book = LatencyBook()
    for record in records:
        turn = TurnLatency(
            turn=int(record.get("turn") or 0),
            modality=str(record.get("modality") or "voice"),
            core_total_ms=float(record.get("core_total_ms") or 0.0),
            m7_server_ms=record.get("m7_server_ms"),
            first_audible=str(record.get("first_audible") or "reply"),
            turn_type=str(record.get("turn_type") or ""),
            ladder_tier=int(record.get("ladder_tier") or 0),
        )
        for line in record.get("lines") or []:
            number = line.get("line")
            value = line.get("ms")
            if isinstance(number, int) and isinstance(value, (int, float)):
                setattr(turn, f"line{number}_ms", float(value))
        book.record(turn)
    return book.summary()


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def format_summary(summary: dict[str, Any] | None, *, title: str = "§2.2 latency") -> str:
    """The nine lines as a table, budget beside measurement."""
    if not summary:
        return f"{title}: no turns measured."
    rows = [
        f"{title} — {summary['turns']} turn(s)",
        "",
        f"{'#':>2}  {'component':<52} {'median':>9} {'p95':>9} {'budget':>8} {'n':>4}",
        "-" * 92,
    ]
    for budget in BUDGET:
        cell = summary["per_line"][budget.key]
        name = budget.name[:52]
        if cell.get("status") == UNMEASURED:
            rows.append(
                f"{budget.number:>2}  {name:<52} {UNMEASURED:>9} {'':>9} "
                f"{budget.median_ms:>7.0f}m {'':>4}"
            )
            continue
        dist = cell.get("distribution_ms")
        if not dist:
            rows.append(
                f"{budget.number:>2}  {name:<52} {'—':>9} {'—':>9} "
                f"{budget.median_ms:>7.0f}m {0:>4}"
            )
            continue
        rows.append(
            f"{budget.number:>2}  {name:<52} {dist['median']:>9.1f} {dist['p95']:>9.1f} "
            f"{budget.median_ms:>7.0f}m {dist['n']:>4}"
        )
    rows.append("-" * 92)
    total = summary.get("measured_total_ms")
    if total:
        rows.append(
            f"    lines 2–8 measured total{'':<28} {total['median']:>9.1f} "
            f"{total['p95']:>9.1f} {summary['measurable_target_median_ms']:>7.0f}m "
            f"{total['n']:>4}"
        )
    m7 = summary.get("m7_server_ms")
    if m7:
        rows.append(
            f"    M7 end-of-speech → first audible (server){'':<11} {m7['median']:>9.1f} "
            f"{m7['p95']:>9.1f} {M7_CEILING_MS:>7.0f}c {m7['n']:>4}"
        )
    rows.append("")
    rows.append(
        "    budget column: 'm' = §2.2 target median, 'c' = `01` M7's 1.2 s ceiling."
    )
    rows.append(f"    lines 1 and 9: {UNMEASURED} — {summary['browser_lines_note']}")
    return "\n".join(rows)
