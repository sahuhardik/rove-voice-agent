"""The next-step policy (`docs/06` §3.5), plus the §6 safety stops.

The design claim this module exists to make true:

> The LLM never chooses what to do. It chooses *among what it is permitted to
> do*, and it chooses the words. (`docs/06` §3.1)

Everything here runs **before** the model sees anything. The candidate set it
is offered has already had the illegal moves removed, so a model that proposes
a formatted card after the caller formatted the card cannot be obeyed — the
step is not in the list, and `core.py` validates the reply against the list.

Filter order, from §3.5 and §6, strongest stop first:

| # | Filter | Drops |
| --- | --- | --- |
| 1 | HAZARD STOP | everything except the handoff (§6.1) |
| 2 | NEVER-AGENT-INITIATED | firmware downgrade, always (§6.4) |
| 3 | FW-01 INTERLOCK | the power-cycle family while an update is believed in progress (§6.4) |
| 4 | NO-REPEAT | the step id, **and its family**, if the ledger has it as tried-and-failed (EVAL-12) |
| 4b | ASKED-AND-ANSWERED | a question the caller has already answered, while nothing has changed since (§3.6) |
| 5 | MODEL CLEARANCE | model-specific steps while the model is UNKNOWN (§3.4) |
| 6 | DRIVING GATE | anything needing hands (§6.2) |
| 7 | PRESERVATION | anything risking footage when footage is at stake — **no consent path** (§6.4) |
| 8 | DESTRUCTIVE GATE | destructive steps without cause + consequence + consent (§6.4) |

Source clearance (§3.5 line 1) is the one filter that is **recorded rather than
applied**, and the reason is a genuine disagreement between two design
documents that this code cannot resolve on its own:

* `docs/06` §4.5 and §9.1 Phase 1 say an `UNVERIFIED` entry must escalate
  rather than improvise.
* `docs/03` grades four scenarios on UNVERIFIED entries — EVAL-14 (`APP-02`),
  EVAL-19 (`APP-04`), EVAL-21 (`FW-03`), EVAL-23 (`PWR-02`) — and expects a
  diagnostic question and **no escalation** on all four.

Dropping the candidates would fail the eval set; ignoring the status would let
an unevidenced step be spoken as a fix. So the candidate survives carrying an
`unverified-entry` flag, and `core.py`'s output guard refuses to phrase it as a
fix and says plainly that it cannot be confirmed against Rove's documentation.
This is flagged in `agent/README.md` as an open question for whoever owns
`docs/03`.

**Filter 4b is an addition to filter 4, never a relaxation of it.** It is
guarded on `step.no_repeat_exempt` — exactly the set filter 4 is designed to
let through — so a step the ledger blocks is already dropped before 4b is
reached. The two read different records (`ledger.attempted` and `answers`) and
neither can shorten the other's reach. See Milestone 4.4 in `agent/answers.py`
for why the gap existed: `docs/06` §3.6 exempts the question families from
no-repeat *conditionally* — "after something has changed" — and the code read
the exemption as unconditional.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent import answers as agent_answers
from agent import intake as agent_intake
from agent import state as agent_state
from agent.state import UNKNOWN, Answer, DiagnosticState, GateDecision
from eval import ontology

#: Families that are blocked outright while a firmware update is believed to be
#: in progress (`docs/06` §6.4, the FW-01 interlock). A cut during a write is
#: what creates FW-02, and EVAL-22's caller is about to make it.
FW01_BLOCKED_FAMILIES = frozenset({"FAMILY.POWER_CYCLE"})

#: Never agent-initiated under any circumstances (`docs/01` §5, `docs/06` §3.5).
#: Not gated — blocked.
NEVER_INITIATED_FAMILIES = frozenset({"FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE"})

#: Plain-words consequences, spoken *before* consent is requested (§6.4 item 2).
#: Written out per family because "this is destructive" is not a consequence —
#: the caller has to know what they lose.
CONSEQUENCE_BY_FAMILY: dict[str, str] = {
    "FAMILY.DESTRUCTIVE.ERASE_CARD": (
        "This erases everything on the card, including anything you have saved "
        "or locked."
    ),
    "FAMILY.DESTRUCTIVE.RESET_DEVICE": (
        "This clears the camera's settings and puts it back to how it came out "
        "of the box. You would need to set the time and your preferences again."
    ),
    "FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE": (
        "This replaces the camera's software with an older version and can "
        "leave it unusable."
    ),
}

ESCALATION_HANDOFF = "STEP.ESCALATE.HANDOFF"
ESCALATION_OUT_OF_SCOPE = "STEP.ESCALATE.OUT_OF_SCOPE_TRANSFER"


@dataclass
class CandidateDecision:
    """One candidate with a kept/dropped verdict and the reason (`docs/06` §7.5).

    Every candidate is returned, kept or not. A no-repeat breach has to be
    debuggable in one look, and a filter that silently shortens a list is not.
    """

    step_id: str
    kept: bool
    drop_reason: str | None = None
    origin: str = "taxonomy"  # taxonomy | retrieval
    flags: list[str] = field(default_factory=list)
    gate: GateDecision | None = None

    def as_ontology_candidate(self) -> ontology.Candidate:
        """The shape `eval.harness.AgentOutput.candidates` carries."""
        return ontology.Candidate(
            step_id=self.step_id, kept=self.kept, drop_reason=self.drop_reason
        )


def candidate_steps(
    state: DiagnosticState,
    *,
    taxonomy_id: str | None = None,
    retrieved_step_ids: list[str] | None = None,
) -> list[CandidateDecision]:
    """Run the §3.5 filter chain over one taxonomy entry's candidates.

    `candidates = steps_for(taxonomy_id) ∪ steps_from(cleared_chunks)` — the
    retrieved half carries `origin="retrieval"` so the trace shows where a step
    the taxonomy map never listed came from.
    """
    entry = taxonomy_id or state.problem.taxonomy_id or "NO_MATCH"
    step_ids = list(ontology.TAXONOMY_CANDIDATES.get(entry, []))
    for step_id in retrieved_step_ids or []:
        if step_id not in step_ids and step_id in ontology.STEPS:
            step_ids.append(step_id)
    origins = {
        step_id: (
            "taxonomy"
            if step_id in ontology.TAXONOMY_CANDIDATES.get(entry, [])
            else "retrieval"
        )
        for step_id in step_ids
    }

    blocked = state.ledger.blocked
    #: Milestone 4.4. The ledger's sibling, and deliberately a *separate* set:
    #: nothing below reads it in place of `blocked`, only in addition to it.
    answered = state.answered_questions
    unverified_entry = not state.speakable_as_fix
    out: list[CandidateDecision] = []

    for step_id in step_ids:
        step = ontology.STEPS[step_id]
        reason: str | None = None
        flags: list[str] = []
        gate: GateDecision | None = None

        if unverified_entry:
            flags.append("unverified-entry")

        # 1. HAZARD STOP — pre-empts everything (§6.1).
        if state.safety.hazard_stop and step.family != "FAMILY.ESCALATE":
            reason = (
                "hazard stop: "
                + ", ".join(state.safety.hazard_flags)
                + " reported; diagnosis stops and the device is disconnected (06 §6.1)"
            )

        # 2. Never agent-initiated (§6.4).
        elif step.family in NEVER_INITIATED_FAMILIES:
            reason = "never agent-initiated: firmware downgrade is blocked, not gated"

        # 3. The FW-01 interlock (§6.4).
        elif state.firmware_update_in_progress and step.family in FW01_BLOCKED_FAMILIES:
            reason = (
                "FW-01 interlock: a firmware update is believed to be in progress and "
                "cutting power mid-write is what creates FW-02"
            )

        # 4. NO-REPEAT, including family-level blocking (§3.5, EVAL-12).
        elif not step.no_repeat_exempt and step_id in blocked:
            reason = "no-repeat: this exact step is in the ledger as tried-and-failed"
        elif not step.no_repeat_exempt and step.family in blocked:
            reason = (
                f"no-repeat: {step.family} is in the ledger as tried-and-failed — "
                "a different step in the same family is equally blocked (EVAL-12)"
            )

        # 4b. ASKED-AND-ANSWERED (Milestone 4.4; §3.6, §3.4, 01 §3.3).
        #
        # Strictly *after* filter 4 and strictly *narrower* than it: the guard
        # is `step.no_repeat_exempt`, which is the exact set of steps filter 4
        # lets through by design. A step filter 4 blocks is already gone before
        # this line is reached, so the no-repeat ledger cannot be weakened
        # here, only supplemented.
        #
        # `docs/06` §3.6 exempts the question families from no-repeat because
        # "asking someone to read the screen again, **after something has
        # changed**, is not repetition" — a conditional licence that the code
        # was reading as an unconditional one. `state.answered_questions`
        # applies the condition: an answer stops standing as soon as an action
        # step is attempted after it. Until then the question has been put and
        # answered, and §3.4 says what putting it again is worth: "asking the
        # same question louder is not a strategy".
        elif step.no_repeat_exempt and step_id in answered:
            answer = state.answers[step_id]
            reason = (
                "asked-and-answered: this question was put on turn "
                f"{answer.turn} and the caller answered it ({answer.reading}); "
                "nothing has changed since, so re-asking it buys nothing "
                "(06 §3.6, §3.4)"
            )

        # 5. MODEL CLEARANCE (§3.4, §4.6).
        elif step.model_specific and state.device.confidence == UNKNOWN:
            reason = (
                "model clearance: the step differs by model and the model is UNKNOWN"
            )

        # 6. The driving gate (§6.2).
        elif state.safety.driving == "yes" and step.needs_hands:
            reason = "driving gate: the caller is driving and this step needs hands"

        # 7. Preservation overrides the gate entirely (§6.4).
        elif state.safety.footage_at_stake != "none" and step.risks_footage:
            reason = (
                "preservation: footage is at stake, so every footage-erasing step is "
                "removed from the set — there is no consent path"
            )

        # 8. The destructive gate (§6.4): cause + consequence + consent.
        elif step.destructive:
            gate = _gate_for(state, step, entry)
            state.gates.append(gate)
            if gate.decision != "allowed":
                reason = (
                    "destructive gate: needs cause + consequence + explicit consent; "
                    f"consent is {gate.consent_state}"
                )

        out.append(
            CandidateDecision(
                step_id=step_id,
                kept=reason is None,
                drop_reason=reason,
                origin=origins.get(step_id, "taxonomy"),
                flags=flags,
                gate=gate,
            )
        )
    return out


def _gate_for(state: DiagnosticState, step: ontology.Step, entry: str) -> GateDecision:
    """Build and record the three-part gate decision for a destructive step.

    All three parts are structured fields, never inferred from the transcript
    (§6.4). In text mode there is no consent surface at all, so the honest
    value of `consent_state` is `not_requested` and the honest `decision` is
    `blocked`. The record is still written: a gate that refuses silently is
    indistinguishable from a filter that forgot.
    """
    hypothesis = state.problem.top_hypothesis
    cause = (
        f"{entry}: {hypothesis.text}"
        if hypothesis is not None
        else f"{entry}: {step.description}"
    )
    consequence = CONSEQUENCE_BY_FAMILY.get(step.family, "")
    granted = bool(state.consent.get(step.id))
    gate = GateDecision(
        step_id=step.id,
        step_family=step.family,
        cause=cause,
        consequence=consequence,
        consent_state="granted" if granted else "not_requested",
        decision="allowed" if (granted and cause and consequence) else "blocked",
        turn=state.turn,
    )
    return gate


def answers_held(state: DiagnosticState) -> list[Answer]:
    """Answers the record currently holds, oldest first (`docs/06` §3.3).

    Every answer counts, not only the still-current ones: an answer that a
    later action superseded for *re-asking* purposes has not stopped being
    true. The caller said a clip they locked disappeared; power-cycling the
    camera afterwards does not unsay it.
    """
    return sorted(state.answers.values(), key=lambda a: (a.turn, a.step_id))


def legal_step_ids(decisions: list[CandidateDecision]) -> list[str]:
    return [d.step_id for d in decisions if d.kept]


def cross_entry_discriminators(
    state: DiagnosticState,
    per_entry_decisions: dict[str, list[CandidateDecision]],
    shortlist: list[str],
) -> list[tuple[str, str]]:
    """`(step_id, entry)` for every legal candidate that splits the **live** causes.

    Milestone 4.6, and the one piece of `docs/06` §3.5's rank that cannot be
    delegated.

    §3.5 ranks candidates by "expected information gain **across the live
    causes**, divided by user cost". Phase 1 hands that ranking to the model
    (`select` below), and for ordinary candidates that is the right division of
    labour: which of two probes inside one cause is cheaper is a judgement, and
    the model sees the chunks. But one class of candidate is not a judgement.
    When two taxonomy entries are both live and a single question's documented
    readings land on *both* of them, that question's answer does not re-rank
    the causes — it **decides** which one the session is in. Every other
    candidate on the list is a probe inside a cause that may turn out to be the
    wrong one.

    `docs/03` EVAL-23 states it as an instruction rather than a preference —
    "Re-categorise to `PWR-02` if the camera is restarting; back to `WIFI-04`
    if not" — and `agent/core._implied_entry` already takes the *answer* half
    of that sentence deterministically for exactly this reason. This is the
    other half: the question that produces the answer. Harness B measured the
    gap directly. The heat question was legal and on the option list in every
    run since Milestone 4.4's cross-check landed, and the model, which is told
    the options but never which causes are live, chose a Wi-Fi probe every
    time; `docs/03` says of that scenario "the heat detail is the whole
    scenario and ignoring it is the failure being tested".

    This adds nothing to the legal set and removes nothing from it — it reads
    `kept` decisions only, so every §3.5 and §6 filter has already run, and a
    question the caller has already answered is excluded on the same §3.6
    grounds filter 4b applies. It ranks; it does not permit.
    """
    live = [entry for entry in shortlist if entry not in RESIDUAL_ENTRIES]
    if len(live) < 2:
        return []
    answered = state.answered_questions
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in live:
        for decision in per_entry_decisions.get(entry, []):
            if not decision.kept or decision.step_id in seen:
                continue
            if decision.step_id in answered:
                continue
            targets = agent_answers.recategorisation_targets(decision.step_id)
            # "Across the live causes": the readings have to reach at least two
            # entries triage currently holds. A question that can only ever
            # name the entry it already sits under splits nothing.
            if len(targets & set(live)) < 2:
                continue
            seen.add(decision.step_id)
            found.append((decision.step_id, entry))
    return found


def select(
    decisions: list[CandidateDecision], preferred: str | None = None
) -> CandidateDecision | None:
    """Take the preferred step if it is legal, otherwise the first legal one.

    `docs/06` §3.5 ranks by discriminating power divided by user cost. Phase 1
    delegates that ranking to the LLM, which sees the live causes and the
    retrieved chunks; this function is the cap that follows it — **one action,
    the top candidate only** — and the guarantee that a model's preference
    cannot override a filter.
    """
    legal = [d for d in decisions if d.kept]
    if not legal:
        return None
    if preferred:
        for decision in legal:
            if decision.step_id == preferred:
                return decision
    return legal[0]


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------

#: Taxonomy entries that are escalation-bound by their own `docs/02` entry.
#: FW-02 is the suspected-brick case: "Escalate when: immediately, in parallel
#: with any step." The agent may suspect hardware; it may not declare it.
ESCALATION_BOUND_ENTRIES = frozenset({"FW-02"})

#: The two non-taxonomy outcomes. Neither is a diagnosis; both are a statement
#: that triage found nothing to diagnose, which is why §5.1 lists them as
#: *structural* triggers — and why, since Milestone 3.1, they only count as
#: triggers when triage really did come back empty. See `escalation` below.
RESIDUAL_ENTRIES = frozenset({"NO_MATCH", "OUT_OF_SCOPE"})


@dataclass
class EscalationDecision:
    escalate: bool
    reason_code: str = ""
    reason: str = ""
    triggers: list[str] = field(default_factory=list)
    #: Every trigger's code, in the order they fired. `reason_code` is the
    #: first of them and decides what happens; this is the whole list, which
    #: is what lets `core.escalation_phrase` say the true thing to the caller
    #: when more than one trigger is live at once.
    codes: list[str] = field(default_factory=list)
    #: Triggers that were considered and deliberately not honoured, kept for
    #: the trace. A classifier vote that did not escalate has to be visible,
    #: or "the agent ignored the model" is indistinguishable from "the model
    #: said nothing".
    declined: list[str] = field(default_factory=list)
    #: Milestone 6.7. True when the only reason to escalate was `NO_MATCH` on a
    #: symptom too vague to triage, and the intake agent is allowed to ask. The
    #: turn then goes to the intake question tree (`agent/intake.py`) rather
    #: than to a human.
    route_to_intake: bool = False


#: Rule flags that are the caller's own request or a scope verdict. Each has its
#: own trigger in `escalation`; a vague symptom alongside one is not vague, it
#: is something else, so intake stays out of it.
INTAKE_BLOCKING_FLAGS = frozenset(
    {"requests_human", "out_of_scope", "out_of_scope_device", "vehicle_electrical"}
)


def intake_can_ask(
    state: DiagnosticState,
    *,
    rule_flags: list[str] | None = None,
    genuine_no_match: bool = False,
    has_dashcam_context: bool = True,
    is_clear_out_of_scope: bool = False,
) -> bool:
    """Whether a `NO_MATCH` should be asked about instead of escalated.

    Milestone 6.7. `docs/06` §5.1's trigger is "`NO_MATCH` from triage", and a
    caller who has said only that something is wrong has not given triage
    anything to fail on. That is an under-specified symptom, and the answer to
    one is a question. It is **not** the answer when:

    * a hazard stands (§6.1 stops diagnosis outright);
    * the caller asked for a person, or a scope flag fired -- those have their
      own triggers and the caller has already said what they want;
    * triage reported a *specific* symptom no `docs/02` entry explains
      (`triage_no_match`, EVAL-28): that is a real gap and a hand-off;
    * the intake agent already asked and could not get an answer.
    """
    if state.safety.hazard_stop:
        return False
    if INTAKE_BLOCKING_FLAGS & set(rule_flags or []):
        return False
    if genuine_no_match:
        return False
    # Finish fix (Milestone 6.7, revised): do not open a new intake tree for
    # a turn that is *clearly* about something else. The router's SYMPTOM
    # intent is a catch-all, so a weather question, a joke, or the capital of
    # France reaches here as NO_MATCH; asking "which Rove camera is this?"
    # for those is wrong, and deferring the escalation to intake leaves the
    # turn with no escalation at all. But an *unclear* turn -- a fragment
    # such as "what you needed", with no dashcam mention and no well-formed
    # question -- is not clearly out-of-scope; it is asked about, with a
    # generic clarifying question (see intake.consult), not escalated. The
    # caller passes has_dashcam_context (the utterance mentions a dashcam, or
    # the session already knows the model / has a subject) and
    # is_clear_out_of_scope (a well-formed question/request or a foreign
    # subject). Only a tree that is not already open is gated, so a reply to
    # an open question is still read as its answer.
    if (
        not agent_intake.load(state).active
        and not has_dashcam_context
        and is_clear_out_of_scope
    ):
        return False
    return not agent_intake.load(state).gave_up


def escalation(
    state: DiagnosticState,
    *,
    taxonomy_id: str | None,
    legal_steps: list[str],
    flags: list[str] | None = None,
    routable_alternatives: list[str] | None = None,
    intake_can_ask: bool = False,
) -> EscalationDecision:
    """Every §5.1 / `docs/02` cross-cutting escalation trigger, evaluated.

    Escalation is a **policy** decision, not a model one. The LLM's vote is
    recorded in the trace and deliberately not honoured here: `docs/03` runs 26
    negative controls against 4 unconditional escalations precisely because an
    agent that escalates when it feels uncertain scores 4/30, not 4/4.

    **Milestone 3.1: a classification is not a trigger.** Measured across three
    runs, most of the core's 7–9 false positives were the classifier reaching
    for `NO_MATCH` or `OUT_OF_SCOPE` — or flagging `out_of_scope`,
    `requests_human` or `hazard` on a scenario that was none of those — after
    which this function did exactly what it was told. Every `flag` reaching
    here is now a *rule-derived* one (`core.scan_utterance`, deterministic
    keyword detection on the caller's own words); the classifier's flags are
    recorded in the trace and read by nothing, on the same reasoning that
    already applies to its `escalate` field.

    `docs/06` §5.1's structural trigger is "`NO_MATCH` **from triage**", not
    "`NO_MATCH` was on the shortlist". So `NO_MATCH` and `OUT_OF_SCOPE`
    escalate only when `routable_alternatives` is empty — when triage has no
    other entry left that offers a legal step. With an alternative in hand,
    triage has not finished, and the turn routes back to a clarifying question
    instead of to a human.

    **Milestone 3.3: what counts as an alternative.** `routable_alternatives`
    is built by `core.step_select_step`, and since 3.3 it excludes an entry
    that explains only a minority of the symptoms the caller reported while
    its own discriminating condition is absent from their words. `docs/06`
    §4.7 calls that "force it into the nearest category... the EVAL-28 failure
    and the most damaging thing the agent can do". A forced category is not a
    route, so it does not defeat `NO_MATCH` here — see `agent/symptoms.py`.

    What this deliberately does **not** weaken:

    * **`FW-02`** still escalates immediately, in parallel with any step
      (`docs/02`): a suspected brick is a human's outcome.
    * **`UNVERIFIED` entries** keep the handling the module docstring
      describes — the candidate survives carrying an `unverified-entry` flag
      and `core.py` refuses to phrase it as a fix. `docs/06` §3.2 makes an
      UNVERIFIED entry a ceiling only when *no cross-model cleared step
      exists*, which the empty-legal-set trigger below already covers, and
      `docs/03` grades four UNVERIFIED scenarios as **no escalation**.
    """
    entry = taxonomy_id or state.problem.taxonomy_id
    flags = flags or []
    routable_alternatives = routable_alternatives or []
    triggers: list[tuple[str, str]] = []
    declined: list[str] = []
    route_to_intake = False

    if state.safety.hazard_stop:
        triggers.append(
            (
                "hazard",
                "caller reports "
                + ", ".join(state.safety.hazard_flags)
                + " — stop diagnosis, disconnect, escalate (02 trigger 3)",
            )
        )
    if "out_of_scope" in flags:
        triggers.append(
            ("out_of_scope", "request is billing, RMA, warranty or returns (01 §4)")
        )
    if entry in RESIDUAL_ENTRIES:
        if routable_alternatives:
            declined.append(
                f"{entry.lower()}: classified {entry}, but triage still holds "
                + ", ".join(routable_alternatives)
                + " with a legal step — a classification is not a 5.1 trigger, so "
                "this routes back to a clarifying question rather than to a human"
            )
        elif entry == "NO_MATCH" and intake_can_ask:
            route_to_intake = True
            declined.append(
                "no_match: the symptom is too vague to triage, so this routes to "
                "the intake question tree rather than to a human (Milestone 6.7)"
            )
        elif entry == "NO_MATCH" and _intake_gave_up_unanswered(state):
            triggers.append(
                (
                    "intake_unanswered",
                    "the intake agent asked twice for the same detail and could "
                    "not get an answer, so a person can take it from here",
                )
            )
        elif entry == "NO_MATCH":
            triggers.append(
                (
                    "no_match",
                    "triage found no taxonomy entry for the symptom and has no other "
                    "candidate left; forcing it into the nearest category is the "
                    "EVAL-28 failure (06 §4.7)",
                )
            )
        else:
            triggers.append(
                (
                    "out_of_scope",
                    "triage has nothing but an out-of-scope reading: billing, RMA, "
                    "warranty or returns (01 §4)",
                )
            )
    if entry in ESCALATION_BOUND_ENTRIES:
        triggers.append(
            (
                "suspected_brick",
                "FW-02 is escalation-first: a suspected brick is a human's outcome, "
                "and the agent may suspect hardware but not declare it",
            )
        )
    # Milestone 4.4: the rest of §5.1's **per-entry** triggers. `FW-02` above
    # is the only one `docs/02` states unconditionally; every other one is a
    # condition on the answer to that entry's "Must ask" question, and before
    # the answer was in the typed record none of them could be evaluated at
    # all. Reading the answer is deterministic (`agent/answers.py`), so this
    # stays what the docstring above promises: a policy decision, not a model
    # one.
    for recorded in answers_held(state):
        trigger = agent_answers.trigger_for(recorded.step_id, recorded.reading)
        if trigger is not None:
            triggers.append((trigger.reason_code, trigger.reason))
    if "vehicle_electrical" in flags:
        triggers.append(
            (
                "out_of_scope_vehicle_electrical",
                "a third-party installation or vehicle wiring is implicated, and "
                "vehicle electrical work is out of scope (01 §4) — characterise, "
                "then hand over",
            )
        )
    if "requests_human" in flags:
        triggers.append(("user_requests_human", "the caller asked for a person"))
    if "undocumented_model" in flags:
        triggers.append(
            (
                "undocumented_model",
                "identified as a model with no manual in the corpus; clearance is "
                "none (06 §3.4)",
            )
        )
    if not legal_steps:
        triggers.append(
            ("no_legal_step", "the legal candidate set is empty (06 §3.2 ceiling)")
        )
    for breach in state.ceiling_breaches():
        triggers.append(("ceiling", breach))

    if not triggers:
        return EscalationDecision(
            escalate=False, declined=declined, route_to_intake=route_to_intake
        )
    code, reason = triggers[0]
    return EscalationDecision(
        escalate=True,
        reason_code=code,
        reason=reason,
        triggers=[f"{c}: {r}" for c, r in triggers],
        codes=[c for c, _ in triggers],
        declined=declined,
    )


def _intake_gave_up_unanswered(state: DiagnosticState) -> bool:
    record = agent_intake.load(state)
    return record.gave_up and record.give_up_reason == agent_intake.REASON_UNANSWERED


def escalation_step(decisions: list[CandidateDecision], taxonomy_id: str | None) -> str | None:
    """The step that *carries out* an escalation, if one is legal.

    `docs/03` EVAL-29 is explicit that an out-of-scope request is transferred
    without demanding a troubleshooting session as the price of the handoff, so
    the out-of-scope transfer is a different step from the engineer handoff.
    """
    legal = legal_step_ids(decisions)
    preferred = (
        ESCALATION_OUT_OF_SCOPE if taxonomy_id == "OUT_OF_SCOPE" else ESCALATION_HANDOFF
    )
    if preferred in legal:
        return preferred
    for step_id in (ESCALATION_HANDOFF, ESCALATION_OUT_OF_SCOPE):
        if step_id in legal:
            return step_id
    return legal[0] if legal else None


__all__ = [
    "CandidateDecision",
    "EscalationDecision",
    "answers_held",
    "candidate_steps",
    "cross_entry_discriminators",
    "escalation",
    "escalation_step",
    "intake_can_ask",
    "legal_step_ids",
    "select",
    "agent_state",
]
