"""The latency ladder (`docs/06` §2.4).

> A graded ladder, applied automatically on measured breach, logged every time.
> No step in it is allowed to weaken a hard constraint.

§2.4's table has six tiers, and this module is all six of them. Two properties
decide its shape, and both are in §2.4 rather than invented here.

**"Applied automatically on measured breach."** The trigger is a number out of
`server/latency.py`'s :class:`~server.latency.LatencyBook` — the same book the
trace is written from — so the ladder cannot be reading one latency while the
report shows another. §2.4 keys tiers 1–3 off **p95 over a 20-turn window**,
not off the median; the running median is tracked too, because Tier 0's
projection is a median and because §7.2 reports both.

**"No step in it is allowed to weaken a hard constraint."** §2.4 is explicit:

> Latency may be bought with *reasoning quality*, and quality loss must be
> visible in the eval harness. Latency may **never** be bought with the
> no-repeat check, the destructive gate, the model-clearance filter, the
> Tier-1 clearance filter, or the output guard.

So :class:`Shed` has no field that could turn any of those off. It can drop the
reranker, cut the candidate set, shorten the prompt, change the model tier and
stop generating altogether — and that is the whole of it. The policy filter in
`eval/ontology.py` and the guard in `agent/core.py` run on every turn at every
tier, which is also why they are cheap enough not to be worth shedding: §2.2
lines 4 and 8 total 25 ms at the median.

What each tier actually does
----------------------------

| tier | §2.4 trigger | what this module changes |
|---|---|---|
| 0 | turn projected > 800 ms | `filler=True` — the caller hears "Let me check that." while the turn runs |
| 1 | p95 > 2.0 s over 20 turns | `rerank=False`, `hybrid_k=4`, `semantic_endpointing=False` |
| 2 | p95 > 2.5 s | `prompt_profile="compact"` — state + top-3 chunks |
| 3 | p95 > 3.0 s, or the model is erroring | `model_tier="fast"` |
| 4 | ASR / LLM / knowledge layer unavailable | `generation="scripted"` — the core's rule-based floor |
| 5 | two consecutive turns breach 4 s, or Tier 4 cannot run | `escalate=True` |

Every one of those is applied where the work happens:
`server/latency.py`'s wrappers carry tiers 1–4 into `agent.retrieval.retrieve`,
`agent.retrieval.rerank` and the model handle without editing `agent/`, and
`server/endpointing.py` reads `semantic_endpointing` directly. `server/
test_latency.py` asserts each one *changes an observable*, because a ladder
that is wired and not effective is worse than no ladder: it reports relief it
did not deliver.

**Coming back down.** §2.4 says nothing about recovery, and a ladder that only
climbs is a ratchet — one slow minute would leave a session on the fast model
for an hour. The release rule is therefore ours and is stated as such:
a tier is released when the same window's p95 has sat :data:`RECOVERY_MARGIN_MS`
below its own trigger for :data:`RECOVERY_TURNS` consecutive turns, and tiers
are released **one at a time, in reverse order**. The margin is the hysteresis
that stops a session oscillating across a threshold; the count stops one fast
turn undoing a sustained breach.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from server import latency

# --------------------------------------------------------------------------
# §2.4's triggers
# --------------------------------------------------------------------------

#: Tier 0: "Turn projected > 800 ms". §2.2's aspiration line.
TIER0_PROJECTION_MS = 800.0

#: §2.4's Tier 0 note: "Becomes a tic if used every turn — cap at ~1 in 3 turns."
TIER0_MIN_TURNS_BETWEEN = 3

#: Tiers 1–3, as p95 over the 20-turn window §2.4 names.
TIER1_P95_MS = 2000.0
TIER2_P95_MS = 2500.0
TIER3_P95_MS = 3000.0

#: Tier 5: "Two consecutive turns breach 4 s".
TIER5_BREACH_MS = 4000.0
TIER5_CONSECUTIVE = 2

#: Ours, not §2.4's. See the module docstring.
RECOVERY_MARGIN_MS = 250.0
RECOVERY_TURNS = 3

#: §2.4 Tier 0's words, and deliberately not a generic "mmm": *"Emit a short,
#: honest filler through TTS immediately: 'Let me check that.' Not a generic
#: 'mmm'."*
FILLER_TEXT = "Let me check that."

#: §2.4 Tier 5: "Tell the user plainly that the connection is struggling."
TIER5_TEXT = (
    "I'm sorry — this connection is struggling and I'm taking too long. "
    "Let me get a person onto this with you."
)

#: The p95 trigger for each tier that has one.
P95_TRIGGERS: dict[int, float] = {1: TIER1_P95_MS, 2: TIER2_P95_MS, 3: TIER3_P95_MS}


# --------------------------------------------------------------------------
# What a tier buys
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Shed:
    """What the pipeline is allowed to stop doing at this tier.

    Frozen, and with no field that could weaken a hard constraint — see the
    module docstring. A `Shed` is handed to one turn and discarded; it is
    never a global, because two sessions on one process may legitimately be at
    different tiers.
    """

    tier: int = 0
    #: §2.4 Tier 1 — "Drop the reranker".
    rerank: bool = True
    #: §2.4 Tier 1 — "cut retrieval `k` from 8 to 4". §4.6's `hybrid_k`.
    hybrid_k: int = 8
    #: §2.4 Tier 1 — "drop the semantic endpoint classifier back to fixed
    #: hangovers". Read by `server/endpointing.py`.
    semantic_endpointing: bool = True
    #: §2.4 Tier 2 — `full` or `compact`.
    prompt_profile: str = "full"
    #: §2.4 Tier 2 — "top-3 chunks only".
    prompt_chunks: int = 3
    #: §2.4 Tier 3 — `primary` or `fast` (§8.3's fast model tier).
    model_tier: str = "primary"
    #: §2.4 Tier 4 — `llm` or `scripted` (the core's rule-based floor).
    generation: str = "llm"
    #: §2.4 Tier 0 — speak the filler before the turn's own reply.
    filler: bool = False
    #: §2.4 Tier 5 — hand to a human and say so.
    escalate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "rerank": self.rerank,
            "hybrid_k": self.hybrid_k,
            "semantic_endpointing": self.semantic_endpointing,
            "prompt_profile": self.prompt_profile,
            "prompt_chunks": self.prompt_chunks,
            "model_tier": self.model_tier,
            "generation": self.generation,
            "filler": self.filler,
            "escalate": self.escalate,
        }


#: §2.4's table as data. Tier *n* is the accumulation of tiers 0..n, because
#: §2.4's actions are cumulative — Tier 2 does not put the reranker back.
def shed_for(tier: int, *, filler: bool = False) -> Shed:
    """The `Shed` in force at `tier`."""
    shed = Shed(tier=max(0, tier), filler=filler)
    if tier >= 1:
        shed = replace(shed, rerank=False, hybrid_k=4, semantic_endpointing=False)
    if tier >= 2:
        shed = replace(shed, prompt_profile="compact", prompt_chunks=3)
    if tier >= 3:
        shed = replace(shed, model_tier="fast")
    if tier >= 4:
        shed = replace(shed, generation="scripted")
    if tier >= 5:
        shed = replace(shed, escalate=True)
    return shed


#: §2.4's "What it costs" column, carried into the trace so that a tier change
#: in a log says what was given up rather than only which number it was.
TIER_COST: dict[int, str] = {
    0: "nothing, if used sparingly; a tic if used every turn (capped at ~1 in 3)",
    1: "slightly worse chunk ordering; measurable in eval; acceptable",
    2: "reasoning quality on complex/multi-symptom scenarios (docs/03 Part 3)",
    3: "noticeable on correlation scenarios (EVAL-23/24/25); session flagged",
    4: "no ranking, no adaptation; the session still progresses and can escalate",
    5: "containment, which `01` §6 M9 explicitly says not to optimise for",
}


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


@dataclass
class LadderEvent:
    """One tier change, in the shape the trace takes whole."""

    at: float
    previous: int
    tier: int
    direction: str  # fired | recovered
    reason: str
    p95_ms: float | None
    median_ms: float | None
    turns: int
    cost: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": round(self.at, 3),
            "previous_tier": self.previous,
            "tier": self.tier,
            "direction": self.direction,
            "reason": self.reason,
            "p95_ms": self.p95_ms,
            "median_ms": self.median_ms,
            "turns": self.turns,
            "cost": self.cost,
        }


class Ladder:
    """§2.4's six tiers over one session's :class:`~server.latency.LatencyBook`.

    One object per session. :meth:`evaluate` is called once per completed turn
    and returns the `LadderEvent` if the tier moved, or `None`; :meth:`shed`
    is called at the top of the next turn and returns what that turn may stop
    doing.
    """

    def __init__(
        self,
        book: latency.LatencyBook,
        *,
        on_change: Callable[[LadderEvent], None] | None = None,
        enabled: bool = True,
    ) -> None:
        self.book = book
        self.enabled = enabled
        self._on_change = on_change
        self.tier = 0
        self.history: list[LadderEvent] = []
        #: Set by the caller when §2.4 Tier 4's "ASR, LLM or knowledge layer
        #: unavailable" is a fact rather than a latency reading. A string, so
        #: the trace says *which* layer.
        self.unavailable: str = ""
        #: Set when §2.4 Tier 3's "or primary LLM erroring" is true.
        self.model_erroring: bool = False
        #: Turn index of the last Tier-0 filler, for the ~1-in-3 cap.
        self._last_filler_turn = -TIER0_MIN_TURNS_BETWEEN
        self._calm_turns = 0

    # -- what the next turn may stop doing ---------------------------------

    def shed(self) -> Shed:
        """What the current tier sheds. Pure: no Tier-0 decision, no state.

        Safe to ask as often as you like — the endpointer asks once per arming
        and the typed path asks once per turn.
        """
        if not self.enabled:
            return Shed()
        return shed_for(self.tier)

    def shed_for_turn(self, turn: int) -> Shed:
        """The same, **plus** §2.4's Tier-0 decision for this turn.

        Call exactly once per turn, from the path that can act on `filler`:
        asking consumes the ~1-in-3 cap, so a second caller would silently
        make the filler rarer than §2.4 allows.
        """
        if not self.enabled:
            return Shed()
        return shed_for(self.tier, filler=self._filler_due(turn))

    def _filler_due(self, turn: int) -> bool:
        """§2.4 Tier 0: projected over 800 ms, and not more than 1 turn in 3.

        The projection is `LatencyBook.projected_ms`, which is `None` until a
        turn has completed — §2.4 asks for "live component timings", and there
        are none on the first turn of a session. So Tier 0 cannot fire on turn
        1, by construction and on purpose.
        """
        if self.tier >= 4:
            # At Tier 4 the turn is scripted and fast; at Tier 5 the caller is
            # being handed over. Neither wants a "let me check that" in front.
            return False
        projected = self.book.projected_ms()
        if projected is None or projected <= TIER0_PROJECTION_MS:
            return False
        if turn - self._last_filler_turn < TIER0_MIN_TURNS_BETWEEN:
            return False
        self._last_filler_turn = turn
        return True

    # -- climbing and coming back down -------------------------------------

    def _target_tier(self) -> tuple[int, str]:
        """The tier §2.4's triggers put us at right now, and why."""
        if self.unavailable:
            # §2.4 Tier 4's trigger is a fact about a dependency, not a
            # latency reading, so it jumps straight there rather than
            # climbing — and Tier 5 is where it goes if it cannot even run.
            return 4, f"{self.unavailable} unavailable (§2.4 tier 4)"

        breaches = self.book.consecutive_breaches(TIER5_BREACH_MS)
        if breaches >= TIER5_CONSECUTIVE:
            return 5, (
                f"{breaches} consecutive turns over {TIER5_BREACH_MS:.0f} ms "
                "(§2.4 tier 5)"
            )

        p95 = self.book.running_p95_ms()
        if p95 is not None and p95 > TIER3_P95_MS:
            return 3, f"p95 {p95:.0f} ms > {TIER3_P95_MS:.0f} ms (§2.4 tier 3)"
        if self.model_erroring:
            return 3, "the primary model is erroring (§2.4 tier 3)"
        if p95 is not None and p95 > TIER2_P95_MS:
            return 2, f"p95 {p95:.0f} ms > {TIER2_P95_MS:.0f} ms (§2.4 tier 2)"
        if p95 is not None and p95 > TIER1_P95_MS:
            return 1, f"p95 {p95:.0f} ms > {TIER1_P95_MS:.0f} ms (§2.4 tier 1)"
        return 0, f"p95 {p95:.0f} ms within budget" if p95 is not None else "no breach"

    def _may_release(self, to_tier: int) -> bool:
        """Is the p95 far enough under `to_tier + 1`'s trigger, for long enough?

        Ours, not §2.4's. See the module docstring.
        """
        trigger = P95_TRIGGERS.get(to_tier + 1)
        if trigger is None:
            return True
        p95 = self.book.running_p95_ms()
        if p95 is None:
            return False
        return p95 <= trigger - RECOVERY_MARGIN_MS and self._calm_turns >= RECOVERY_TURNS

    def evaluate(self, *, now: float | None = None) -> LadderEvent | None:
        """Re-read the book after a turn. Returns the tier change, if any.

        Climbs straight to whatever tier the triggers demand — a 3 s p95 is a
        Tier 3 session and making it pass through Tiers 1 and 2 first would
        spend two more slow turns getting there. Comes down **one tier at a
        time**, because each release has to be justified by the window that
        follows it.
        """
        if not self.enabled:
            return None
        now = time.time() if now is None else now
        target, reason = self._target_tier()

        if target > self.tier:
            self._calm_turns = 0
            return self._move(target, "fired", reason, now)

        # Not breaching. Count the calm turns, then release at most one tier.
        self._calm_turns += 1
        if self.tier == 0:
            return None
        if self.unavailable or self.model_erroring:
            return None
        if target >= self.tier:
            return None
        if not self._may_release(self.tier - 1):
            return None
        p95 = self.book.running_p95_ms()
        released = self.tier - 1
        detail = (
            f"p95 {p95:.0f} ms has been {RECOVERY_MARGIN_MS:.0f} ms under the tier "
            f"{self.tier} trigger for {self._calm_turns} turns"
            if p95 is not None
            else "no breach in the window"
        )
        self._calm_turns = 0
        return self._move(released, "recovered", detail, now)

    def _move(self, tier: int, direction: str, reason: str, now: float) -> LadderEvent:
        previous, self.tier = self.tier, tier
        event = LadderEvent(
            at=now,
            previous=previous,
            tier=tier,
            direction=direction,
            reason=reason,
            p95_ms=self.book.running_p95_ms(),
            median_ms=self.book.running_median_ms(),
            turns=len(self.book),
            cost=TIER_COST.get(tier, ""),
        )
        self.history.append(event)
        if self._on_change is not None:
            self._on_change(event)
        return event

    # -- reporting ---------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "enabled": self.enabled,
            "shed": self.shed().as_dict(),
            "p95_ms": self.book.running_p95_ms(),
            "median_ms": self.book.running_median_ms(),
            "projected_ms": self.book.projected_ms(),
            "turns": len(self.book),
            "unavailable": self.unavailable,
            "model_erroring": self.model_erroring,
            "changes": [e.as_dict() for e in self.history],
            "fired": sum(1 for e in self.history if e.direction == "fired"),
            "recovered": sum(1 for e in self.history if e.direction == "recovered"),
        }
