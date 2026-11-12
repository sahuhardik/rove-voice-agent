"""A deliberately dumb rule-based baseline agent.

`docs/06` §9.1 Phase 0: "run the 30 scenarios against a deliberately dumb
baseline". `docs/03`: "No baseline. We do not know what a competent human agent
scores on this set. Without that, a model score of 70% means nothing."

This is the *floor*, not the human baseline. It establishes what a score looks
like when the agent does the least defensible thing that is still a thing:

  * **Category** by the first matching keyword in a fixed, ordered list.
    No intent model, no LLM, no retrieval, no context.
  * **Next step** = the first legal candidate for that taxonomy entry, in the
    order `ontology.TAXONOMY_CANDIDATES` lists them. No ranking by
    discriminating power. No reading of the ledger beyond the filter.
  * **Escalation** only when no keyword matches at all.
  * **Device** always reported as `unknown`, which is the honest answer on all
    30 scenarios and passes M1.

What it *does* do is run the `docs/06` §3.5 policy filter: no-repeat (including
family-level blocking) and the destructive gate. That is the point. M4 and M5
are hard constraints enforced in code, not behaviours an agent is trusted to
learn, so even the dumbest agent in the building has to clear them. If this
baseline ever scores a non-zero M4 or M5 breach, the filter is broken -- which
is exactly the signal Phase 0 exists to give.
"""

from __future__ import annotations

from . import ontology
from .harness import AgentOutput, DiagnosticState

#: Ordered (keywords, taxonomy_id). First hit wins. The ordering is arbitrary
#: in the way a keyword router always is: "memory full" has to beat "card", and
#: "password" has to beat "wifi", or the rules below it never fire. That
#: arbitrariness is a property of the baseline, not a bug in it.
RULES: list[tuple[tuple[str, ...], str]] = [
    (("refund", "money back", "send it back", "get my money", "warranty"), "OUT_OF_SCOPE"),
    (("password",), "WIFI-03"),
    (("firmware",), "FW-01"),
    (("parking",), "REC-04"),
    (("app",), "APP-01"),
    (("wifi", "wi-fi"), "WIFI-02"),
    (("connect",), "WIFI-01"),
    (("memory full",), "SD-02"),
    (("card", "sd card"), "SD-01"),
    (("record",), "REC-02"),
    (("deleting", "deleted"), "REC-03"),
    (("sound", "audio"), "VID-03"),
    (("date", "time"), "PWR-04"),
    (("dead", "turn on", "power"), "PWR-01"),
    (("blurry", "number plate", "plate"), "VID-01"),
    (("night", "dashboard", "reflection"), "VID-02"),
    (("hot", "overheat"), "PWR-02"),
    (("hardwire", "battery went flat"), "PWR-03"),
    (("corrupt", "won't open"), "SD-03"),
]


def match_taxonomy(utterance: str) -> str:
    """First keyword hit wins; no hit means no hypothesis."""
    text = utterance.lower()
    for keywords, taxonomy_id in RULES:
        if any(keyword in text for keyword in keywords):
            return taxonomy_id
    return "NO_MATCH"


class DumbBaselineAgent:
    """Keyword category match, first legal candidate step, no LLM, no retrieval."""

    name = "dumb-rule-based-baseline"

    def propose(self, state: DiagnosticState) -> AgentOutput:
        taxonomy_id = match_taxonomy(state.problem.verbatim_symptom)
        category = ontology.category_of(taxonomy_id)

        candidates = ontology.legal_candidates(
            taxonomy_id,
            state.ledger.attempted,
            # The baseline has no way to establish cause, obtain consent, or
            # state a consequence, so it may never take a destructive step
            # (06 §6.4). Dropping them here is the policy layer doing its job.
            allow_destructive=False,
            model_known=state.device.confidence != "UNKNOWN",
            driving=state.safety.driving == "yes",
            footage_at_stake=state.safety.footage_at_stake != "none",
        )
        kept = [c.step_id for c in candidates if c.kept]
        step_id = kept[0] if kept else None

        # Escalate only when there is no hypothesis at all, or when the filter
        # left nothing legal to do. Note that this is the *whole* escalation
        # policy: the baseline has no notion of a suspected brick, a hazard, or
        # an out-of-scope request beyond the keyword rule above.
        escalate = taxonomy_id in ("NO_MATCH", "OUT_OF_SCOPE") or step_id is None

        return AgentOutput(
            category=category,
            taxonomy_id=taxonomy_id,
            step_id=step_id,
            escalate=escalate,
            device_model="unknown",
            device_confidence="UNKNOWN",
            destructive_gate=None,
            rationale=(
                f"keyword rule -> {taxonomy_id}; first legal candidate of "
                f"{len(candidates)}"
            ),
            candidates=candidates,
        )
