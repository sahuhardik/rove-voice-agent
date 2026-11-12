"""Harness B -- scripted multi-turn (docs/06 §7.3).

    For the items `03` marks multi-turn (EVAL-23, EVAL-26, EVAL-27) plus any
    scenario whose expected outcome branches (EVAL-07, EVAL-16, EVAL-17,
    EVAL-20, EVAL-21). A scripted responder plays the user with deterministic
    replies per branch. Verifies that the agent takes the branch its own
    question implies -- the failure where an agent asks the right question and
    then ignores the answer.

That paragraph is the whole specification, and three things in it decide the
shape of this module.

**"A scripted responder plays the user."** `SCRIPTS` below holds one script per
scenario: the branching question `docs/03` expects on the first turn, and one
`Branch` per outcome `docs/03`'s **Expected outcome** line names. Every reply is
a sentence written to carry the content of that line and nothing else; the
branch's `source` field quotes the line it came from. Nothing here is invented
-- where `docs/03` is silent (what happens on a *third* turn, for instance), the
harness grades the hard constraints and reports the rest as not graded rather
than inventing an expectation.

**"The branch its own question implies."** The responder answers the question
the agent actually asked. If the agent asks the scripted branching question, the
responder plays the chosen branch and that branch is what the agent's own
question implied; the next turn is then checked against that branch's signature
-- escalate or not, category, resolved or not, and the steps that would prove
the answer was ignored (re-asking the question it just got answered). If the
agent never asks the branching question there is no implied branch, the
responder falls back to a deterministic off-script reply, and the run is
reported as a branch failure with that reason. An agent cannot pass the branch
check by never asking.

**"Multi-turn."** The agent is driven by calling its own public turn function
repeatedly, carrying the same `DiagnosticState` and `thread_id` across turns
through the graph checkpointer (`agent/graph.py`). No diagnosis happens in here.
The one thing the harness keeps for itself is a **second, independent ledger**:
it records every step the agent proposes against the outcome the script
declares for the reply, and M4 is scored against *that*, never against the
ledger the agent maintains. An agent that forgets to write its own ledger
therefore fails M4 instead of being let off by it, and because the harness
ledger spans the whole conversation, M4 is checked **across turns** -- the
property `docs/01` M4 actually claims ("the ledger must hold over a whole
conversation"), which a per-turn check cannot see.

Scoring reuses `eval.harness.score` unchanged (`docs/06` §7.3 grades the same
five axes in both harnesses, and a second copy of the scorers would be a second
thing to drift). A turn is graded by building the scenario *as it stands at that
turn* -- same scenario, ledger replaced with the harness ledger so far, expected
step / category / escalation replaced with the branch's -- and handing it to
`score`. Nothing in `eval/harness.py` is modified.

What is deliberately **not** here: M7 latency, M8 resolution, M9 containment and
M10 modality independence (`docs/06` §7.2-7.3 put M10 in Harness A and the rest
behind a real pipeline, which is Harness C).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from . import ontology
from .harness import (
    AgentOutput,
    Scenario,
    ScenarioResult,
    load_scenarios,
    score,
    state_from_scenario,
)
from .ontology import AttemptedStep

# --------------------------------------------------------------------------
# What Harness B covers (docs/06 §7.3)
# --------------------------------------------------------------------------

#: The three `docs/03` marks *multi-turn*.
MULTI_TURN_IDS: tuple[str, ...] = ("EVAL-23", "EVAL-26", "EVAL-27")

#: The five whose **Expected outcome** line branches on the answer to the very
#: question `docs/03` expects the agent to ask.
BRANCHING_IDS: tuple[str, ...] = (
    "EVAL-07",
    "EVAL-16",
    "EVAL-17",
    "EVAL-20",
    "EVAL-21",
)

#: The eight, in scenario order.
HARNESS_B_IDS: tuple[str, ...] = tuple(
    sorted(set(MULTI_TURN_IDS) | set(BRANCHING_IDS))
)

#: Ceiling on turns per run. Two is the minimum that can test a branch at all
#: (ask, answer); the third exists so the no-repeat ledger is exercised *after*
#: the branch turn, and the fourth covers an agent that asks the branching
#: question a turn late. `docs/06` §3.2 sets no turn limit on the agent -- this
#: is a harness bound, not a policy one.
MAX_TURNS = 4


# --------------------------------------------------------------------------
# The script
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Branch:
    """One outcome the scenario's **Expected outcome** line names.

    Two different jobs are kept apart on purpose:

    * the **signature** -- `escalate`, `categories`, `resolved`,
      `forbidden_step_ids` -- is what classifies which branch the agent took.
      These are the axes `docs/03` itself distinguishes the outcomes on.
    * `step_ids` is an **M3 expectation only**. It never classifies a branch.
      Which single step is best on the turn after the answer is a judgement
      `docs/03` mostly does not make, and letting it decide the branch verdict
      would turn a next-step disagreement into a branch failure.
    """

    name: str
    #: The user's reply, played when the agent asks the branching question.
    reply: str
    #: The ledger outcome this reply reports (`ontology.VALID_OUTCOMES`).
    outcome: str
    #: The `docs/03` sentence this branch is taken from. Quoted, not invented.
    source: str
    #: Signature + M6. `None` where `docs/03` does not say.
    escalate: bool | None = None
    #: Signature + M2. `None` where `docs/03` does not say.
    categories: tuple[str, ...] | None = None
    #: M3 only. `None` means the turn is not graded on next-step accuracy.
    #: `None` *inside* the tuple means "no step at all" -- an honest close.
    step_ids: tuple[str | None, ...] | None = None
    #: Signature: proposing one of these proves the answer was ignored.
    forbidden_step_ids: tuple[str, ...] = ()
    #: Signature, where the driver can observe it (the core can; a stateless
    #: baseline cannot, and the check is then skipped rather than guessed).
    resolved: bool | None = None


@dataclass(frozen=True)
class Script:
    """One scenario's scripted conversation."""

    scenario_id: str
    #: The branching question `docs/03` expects on the first turn. Asking any
    #: of these is what makes a branch playable.
    question_step_ids: tuple[str, ...]
    branches: tuple[Branch, ...]
    note: str = ""

    def branch(self, name: str) -> Branch:
        for b in self.branches:
            if b.name == name:
                return b
        raise KeyError(f"{self.scenario_id} has no branch {name!r}")


#: Deterministic off-script replies. Used when the agent proposes something the
#: script has no answer for -- the responder still has to say *something*, and
#: what it says must not depend on anything but the step's family.
OFF_SCRIPT_QUESTION = ("I don't know, I haven't checked that.", "not_attempted")
OFF_SCRIPT_ACTION = ("I tried that and there is no change at all.", "no_change")


SCRIPTS: dict[str, Script] = {
    # ---- EVAL-07 (REC-03) ------------------------------------------------
    # "Expected outcome: No escalation if unlocked. Escalate if the caller is
    #  confident a locked clip disappeared."
    "EVAL-07": Script(
        scenario_id="EVAL-07",
        question_step_ids=("STEP.ASK.WERE_CLIPS_LOCKED",),
        branches=(
            Branch(
                name="clips_were_ordinary",
                reply=(
                    "No, none of them were locked or marked as events - they were "
                    "just the normal recordings."
                ),
                outcome="unclear",
                source="03 EVAL-07 expected outcome: 'No escalation if unlocked.'",
                escalate=False,
                categories=("REC",),
                # Loop recording working as designed. The only other REC-03
                # candidate (02) is the G-sensor check; an honest close is the
                # other legitimate move, so `None` is accepted.
                step_ids=(None, "STEP.SETTINGS.CHECK_GSENSOR_SENSITIVITY"),
                forbidden_step_ids=("STEP.ASK.WERE_CLIPS_LOCKED",),
            ),
            Branch(
                name="locked_clip_vanished",
                reply=(
                    "Yes - I locked that one myself, I'm certain of it, and now "
                    "it's gone."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-07 expected outcome: 'Escalate if the caller is "
                    "confident a locked clip disappeared.'"
                ),
                escalate=True,
                categories=("REC",),
                step_ids=(None, "STEP.ESCALATE.HANDOFF"),
                forbidden_step_ids=("STEP.ASK.WERE_CLIPS_LOCKED",),
            ),
        ),
        note=(
            "A vanished *locked* clip is the real defect hiding behind an "
            "expectation gap (03 EVAL-07 wrong-response note)."
        ),
    ),
    # ---- EVAL-16 (WIFI-04) ----------------------------------------------
    # "No escalation if idle-only (likely designed behaviour, close honestly).
    #  Escalate if it drops mid-transfer -- that makes the app unusable."
    "EVAL-16": Script(
        scenario_id="EVAL-16",
        question_step_ids=("STEP.ASK.DROP_IDLE_OR_ACTIVE",),
        branches=(
            Branch(
                name="idle_only",
                reply=(
                    "It only drops when I've left the phone sitting there. While "
                    "I'm actually using the app it stays connected."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-16 expected outcome: 'No escalation if idle-only "
                    "(likely designed behaviour, close honestly).'"
                ),
                escalate=False,
                categories=("WIFI",),
                step_ids=(None,),
                forbidden_step_ids=(
                    "STEP.ASK.DROP_IDLE_OR_ACTIVE",
                    "STEP.PHONE.FORGET_AND_REJOIN_NETWORK",
                    "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
                ),
            ),
            Branch(
                name="drops_mid_transfer",
                reply=(
                    "No, it drops right in the middle of downloading a clip, every "
                    "single time."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-16 expected outcome: 'Escalate if it drops "
                    "mid-transfer -- that makes the app unusable.'"
                ),
                escalate=True,
                categories=("WIFI",),
                step_ids=(None, "STEP.ESCALATE.HANDOFF"),
                forbidden_step_ids=(
                    "STEP.ASK.DROP_IDLE_OR_ACTIVE",
                    "STEP.PHONE.FORGET_AND_REJOIN_NETWORK",
                    "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
                ),
            ),
        ),
        note=(
            "Forget-and-rejoin and move-closer are already in the ledger from "
            "turn 1; they stay forbidden on every later turn (01 M4)."
        ),
    ),
    # ---- EVAL-17 (SD-04) -------------------------------------------------
    # "No escalation if the card is an ordinary consumer card. Escalate if it
    #  is correctly rated -- that points at the camera."
    "EVAL-17": Script(
        scenario_id="EVAL-17",
        question_step_ids=("STEP.ASK.CARD_SPECS_AND_RATING",),
        branches=(
            Branch(
                name="ordinary_consumer_card",
                reply=(
                    "It just says 64GB and a 10 in a circle. Nothing about "
                    "endurance."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-17 expected outcome: 'No escalation if the card is "
                    "an ordinary consumer card.'"
                ),
                escalate=False,
                categories=("SD",),
                step_ids=None,  # 03 names no second step on this branch
                forbidden_step_ids=(
                    "STEP.ASK.CARD_SPECS_AND_RATING",
                    "STEP.CARD.REPLACE_CARD",
                ),
            ),
            Branch(
                name="correctly_rated_card",
                reply=(
                    "It says High Endurance on it, and U3 V30, made for dash "
                    "cameras."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-17 expected outcome: 'Escalate if it is correctly "
                    "rated -- that points at the camera.'"
                ),
                escalate=True,
                categories=("SD",),
                step_ids=(None, "STEP.ESCALATE.HANDOFF"),
                forbidden_step_ids=(
                    "STEP.ASK.CARD_SPECS_AND_RATING",
                    "STEP.CARD.REPLACE_CARD",
                ),
            ),
        ),
        note=(
            "Formatting stays an M5 breach on every turn of both branches "
            "(03 EVAL-17 harmful steps)."
        ),
    ),
    # ---- EVAL-20 (PWR-04) ------------------------------------------------
    # "No escalation if out of warranty (state the likely cause honestly).
    #  Escalate if in warranty -- suspected hardware."
    #
    # Both replies state the camera's *age and history*, never the word
    # "warranty": `core.scan_utterance` flags that word as an out-of-scope
    # trigger, and a branch that passes because the caller said a keyword would
    # measure the keyword, not the reasoning 03 is asking for.
    "EVAL-20": Script(
        scenario_id="EVAL-20",
        question_step_ids=("STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",),
        branches=(
            Branch(
                name="old_camera_held_date_before",
                reply=(
                    "I've had it about three years, and it held the date fine "
                    "until a few months ago."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-20 expected outcome: 'No escalation if out of "
                    "warranty (state the likely cause honestly).'"
                ),
                escalate=False,
                categories=("PWR",),
                step_ids=(None,),
                forbidden_step_ids=(
                    "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
                    "STEP.SETTINGS.SET_DATE_TIME",
                    "STEP.SETTINGS.SET_DATE_TIME_AND_RETEST",
                ),
            ),
            Branch(
                name="young_camera_never_held_date",
                reply=(
                    "I only bought it four months ago, brand new, and it has "
                    "never held the date. Not once."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-20 expected outcome: 'Escalate if in warranty -- "
                    "suspected hardware.'"
                ),
                escalate=True,
                categories=("PWR",),
                step_ids=(None, "STEP.ESCALATE.HANDOFF"),
                forbidden_step_ids=(
                    "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
                    "STEP.SETTINGS.SET_DATE_TIME",
                    "STEP.SETTINGS.SET_DATE_TIME_AND_RETEST",
                ),
            ),
        ),
        note=(
            "The whole FAMILY.DATE_TIME is already blocked by the turn-1 ledger "
            "and stays blocked across the conversation (03 EVAL-20 note)."
        ),
    ),
    # ---- EVAL-21 (FW-03) -------------------------------------------------
    # "No escalation if the setting was reset. Escalate as a suspected
    #  regression if the setting is on and the feature still fails."
    "EVAL-21": Script(
        scenario_id="EVAL-21",
        question_step_ids=("STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",),
        branches=(
            Branch(
                name="setting_had_been_reset",
                reply=(
                    "You were right - parking mode had been switched off. I've "
                    "turned it back on and that's fixed it."
                ),
                outcome="success",
                source=(
                    "03 EVAL-21 expected outcome: 'No escalation if the setting "
                    "was reset.'"
                ),
                escalate=False,
                categories=("FW", "REC"),
                step_ids=(None,),
                forbidden_step_ids=(
                    "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
                    "STEP.FW.DOWNGRADE",
                ),
                resolved=True,
            ),
            Branch(
                name="setting_still_on",
                reply=(
                    "No, it is still switched on, and parking mode still does "
                    "nothing at all."
                ),
                outcome="no_change",
                source=(
                    "03 EVAL-21 expected outcome: 'Escalate as a suspected "
                    "regression if the setting is on and the feature still "
                    "fails -- we have no known-issue feed.'"
                ),
                escalate=True,
                categories=("FW", "REC"),
                step_ids=(None, "STEP.ESCALATE.HANDOFF"),
                forbidden_step_ids=(
                    "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
                    "STEP.FW.DOWNGRADE",
                ),
                resolved=False,
            ),
        ),
        note=(
            "A firmware downgrade is never agent-initiated and is an M5 breach "
            "on either branch (03 EVAL-21 harmful steps)."
        ),
    ),
    # ---- EVAL-23 (WIFI-04 / PWR-02), 03 marks this multi-turn ------------
    # "No escalation. Re-categorise to PWR-02 if the camera is restarting;
    #  back to WIFI-04 if not."
    #
    # The branch axis here is the *category*, not escalation: this is the
    # scenario where the agent's own question is the only thing that can tell
    # a thermal fault from a Wi-Fi one.
    "EVAL-23": Script(
        scenario_id="EVAL-23",
        question_step_ids=(
            "STEP.ASK.CAMERA_RESTARTS_IN_HEAT",
            "STEP.ASK.RECOVERS_WHEN_COOL",
        ),
        branches=(
            Branch(
                name="camera_restarts_in_heat",
                reply=(
                    "Now you mention it, yes - it has switched itself off a "
                    "couple of times on the hot days."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-23 expected outcome: 'Re-categorise to PWR-02 if "
                    "the camera is restarting.'"
                ),
                escalate=False,
                categories=("PWR",),
                step_ids=None,  # 03 names the re-categorisation, not a step
                forbidden_step_ids=(
                    "STEP.PHONE.FORGET_AND_REJOIN_NETWORK",
                    "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
                ),
            ),
            Branch(
                name="wifi_drops_only",
                reply=(
                    "No, the camera stays on the whole time. It is only the wifi "
                    "that goes."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-23 expected outcome: '... back to WIFI-04 if not.'"
                ),
                escalate=False,
                categories=("WIFI",),
                step_ids=None,
                forbidden_step_ids=(),
            ),
        ),
        note=(
            "03 EVAL-23: 'the heat detail is the whole scenario and ignoring it "
            "is the failure being tested'. Harness B tests the other half -- "
            "asking about the heat and then ignoring the answer."
        ),
    ),
    # ---- EVAL-26 (APP-02 + APP-03), 03 marks this multi-turn -------------
    # "No escalation if granted. Close honestly as a product limitation if the
    #  caller declines on privacy grounds -- that is their decision, not a
    #  fault."
    #
    # Neither branch escalates, so escalation cannot separate them. What
    # separates them is whether the session closes *resolved*. A driver that
    # cannot observe resolution (the stateless baseline) has that check
    # skipped, and the run says so rather than guessing.
    "EVAL-26": Script(
        scenario_id="EVAL-26",
        question_step_ids=("STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",),
        branches=(
            Branch(
                name="permission_granted",
                reply=(
                    "That makes sense. I've allowed it now and that's fixed it - "
                    "the picture's showing."
                ),
                outcome="success",
                source="03 EVAL-26 expected outcome: 'No escalation if granted.'",
                escalate=False,
                categories=("APP",),
                step_ids=(None,),
                forbidden_step_ids=(
                    "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",
                    "STEP.APP.REINSTALL",
                ),
                resolved=True,
            ),
            Branch(
                name="permission_declined",
                reply=(
                    "No, I would rather not let an app onto my home network. I "
                    "will leave it."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-26 expected outcome: 'Close honestly as a product "
                    "limitation if the caller declines on privacy grounds -- "
                    "that is their decision, not a fault.'"
                ),
                escalate=False,
                categories=("APP",),
                step_ids=(None,),
                forbidden_step_ids=(
                    "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",
                    "STEP.APP.REINSTALL",
                ),
                resolved=False,
            ),
        ),
        note=(
            "03 EVAL-26 wrong response: re-asking without explaining 'will "
            "refuse again', and reinstalling 'does not reliably re-prompt once "
            "denied' -- both are forbidden on both branches."
        ),
    ),
    # ---- EVAL-27 (REC-02 + SD-01), 03 marks this multi-turn --------------
    # "No escalation. Likely card replacement and a TO VERIFY check of the card
    #  against spec requirements that are Unknown."
    #
    # The branch is the diagnosis 03 states: a card frozen at a point in time
    # is the read-only / counterfeit end-of-life card; a card that is still
    # taking writes is not, and the search goes back to why today's clips are
    # missing. Footage is at stake on both branches, so formatting is an M5
    # breach on every turn of both.
    "EVAL-27": Script(
        scenario_id="EVAL-27",
        question_step_ids=("STEP.ASK.CARD_FROZEN_IN_TIME",),
        branches=(
            Branch(
                name="card_frozen_in_time",
                reply=(
                    "Yes, the newest file on there is from about three weeks ago. "
                    "Nothing since."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-27 expected diagnosis + outcome: a card gone "
                    "read-only at end of life or counterfeit; 'No escalation. "
                    "Likely card replacement and a TO VERIFY check of the card "
                    "against spec requirements.'"
                ),
                escalate=False,
                categories=("SD", "REC"),
                step_ids=(
                    None,
                    "STEP.ASK.CARD_SPECS_AND_RATING",
                    "STEP.CARD.REPLACE_CARD",
                ),
                forbidden_step_ids=("STEP.ASK.CARD_FROZEN_IN_TIME",),
            ),
            Branch(
                name="card_still_taking_writes",
                reply=(
                    "No, there is stuff on there from last week. It is just "
                    "today that is missing."
                ),
                outcome="unclear",
                source=(
                    "03 EVAL-27 expected diagnosis: the camera believes it is "
                    "writing and the writes are not landing; 'No escalation.'"
                ),
                escalate=False,
                categories=("SD", "REC"),
                step_ids=None,  # 03 names no step for the not-frozen reading
                forbidden_step_ids=("STEP.ASK.CARD_FROZEN_IN_TIME",),
            ),
        ),
        note=(
            "03 EVAL-27 wrong response: 'formatting, which on a read-only or "
            "counterfeit card confirms nothing and destroys the remaining "
            "footage'."
        ),
    ),
}


class ScriptError(AssertionError):
    """A script is not the thing `docs/03` describes."""


def validate_scripts(scripts: dict[str, Script] | None = None) -> None:
    """Fail loudly if a script drifts from the ontology or the golden set."""
    scripts = scripts if scripts is not None else SCRIPTS
    if tuple(sorted(scripts)) != HARNESS_B_IDS:
        raise ScriptError(
            f"Harness B covers {list(HARNESS_B_IDS)} (06 §7.3); scripts cover "
            f"{sorted(scripts)}"
        )
    for scenario_id, script in scripts.items():
        if script.scenario_id != scenario_id:
            raise ScriptError(f"{scenario_id} script is labelled {script.scenario_id}")
        if not script.question_step_ids:
            raise ScriptError(f"{scenario_id} script names no branching question")
        for step_id in script.question_step_ids:
            if step_id not in ontology.STEPS:
                raise ScriptError(
                    f"{scenario_id} branching question {step_id!r} is not a step"
                )
        if len(script.branches) < 2:
            raise ScriptError(
                f"{scenario_id} has {len(script.branches)} branch(es); a branch "
                "check needs at least two outcomes to tell apart"
            )
        names = [b.name for b in script.branches]
        if len(set(names)) != len(names):
            raise ScriptError(f"{scenario_id} has duplicate branch names")
        for branch in script.branches:
            if branch.outcome not in ontology.VALID_OUTCOMES:
                raise ScriptError(
                    f"{scenario_id}/{branch.name} declares outcome "
                    f"{branch.outcome!r}, which is not one of "
                    f"{sorted(ontology.VALID_OUTCOMES)}"
                )
            if not branch.reply.strip():
                raise ScriptError(f"{scenario_id}/{branch.name} has an empty reply")
            if not branch.source.strip():
                raise ScriptError(
                    f"{scenario_id}/{branch.name} cites no docs/03 line -- every "
                    "branch has to come from the expected outcome, not from here"
                )
            for step_id in branch.forbidden_step_ids + tuple(
                s for s in (branch.step_ids or ()) if s is not None
            ):
                if step_id not in ontology.STEPS:
                    raise ScriptError(
                        f"{scenario_id}/{branch.name} names step {step_id!r}, "
                        "which is not in the ontology"
                    )


validate_scripts()


# --------------------------------------------------------------------------
# The scripted responder
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    text: str
    outcome: str
    on_script: bool
    branch_name: str | None = None


@dataclass
class ScriptedResponder:
    """Plays the user, deterministically.

    The only input is the id of the step the agent just proposed. Given the
    same script, the same branch and the same sequence of proposed steps, the
    sequence of replies is identical -- there is no sampling, no clock, no
    randomness and no model in here. That is what makes a Harness B failure
    attributable to the agent.

    The branch reply is played **once**, the first time the agent asks the
    branching question. Everything else gets one of the two off-script replies,
    chosen by whether the step was a question (`FAMILY.ASK` / `FAMILY.OBSERVE`,
    the two families `docs/06` §3.6 exempts from no-repeat) or an action.
    """

    script: Script
    branch: Branch
    #: The turn index on which the branching question was asked, once it is.
    answered_at_turn: int | None = None

    def reply_to(self, step_id: str | None, turn: int) -> Reply:
        if step_id is None:
            return Reply("", "", on_script=False)
        if (
            self.answered_at_turn is None
            and step_id in self.script.question_step_ids
        ):
            self.answered_at_turn = turn
            return Reply(
                self.branch.reply,
                self.branch.outcome,
                on_script=True,
                branch_name=self.branch.name,
            )
        step = ontology.STEPS[step_id]
        text, outcome = (
            OFF_SCRIPT_QUESTION if step.no_repeat_exempt else OFF_SCRIPT_ACTION
        )
        return Reply(text, outcome, on_script=False)


# --------------------------------------------------------------------------
# Driving an agent across turns
# --------------------------------------------------------------------------


@dataclass
class Observation:
    """One turn, as the harness sees it.

    `AgentOutput` is `eval/harness.py`'s and is not changed. The two extra
    fields are things a *session* can observe and a single-turn output cannot:
    whether the agent confirmed a resolution, and where its state machine
    stopped. Both are `None` for a driver that has no session state, and every
    check that reads them is skipped in that case rather than guessed.
    """

    output: AgentOutput
    resolved: bool | None = None
    fsm_state: str | None = None
    response_text: str = ""


class Session(Protocol):  # pragma: no cover - structural type
    def turn(self, utterance: str) -> Observation:
        ...

    def record_attempt(self, entry: AttemptedStep) -> None:
        """Hand the harness's ledger entry to an agent that keeps no state."""


class Driver(Protocol):  # pragma: no cover - structural type
    name: str

    def open(self, scenario: Scenario, session_key: str) -> Session:
        ...


class CoreSession:
    """The Phase 1 core, driven across turns through its own public entry point.

    One `DiagnosticState` and one `thread_id` for the whole conversation, which
    is `agent/graph.py`'s contract: re-invoking on the same thread resumes the
    session from the checkpoint rather than restarting it. The harness calls
    `core.diagnose` and reads what comes back; it does not sequence nodes, touch
    the FSM, or write to the agent's ledger.
    """

    def __init__(self, scenario: Scenario, session_key: str, llm: Any, chunks_path):
        from agent import core

        self._core = core
        self.state = core.state_from_harness(state_from_scenario(scenario))
        self.thread_id = session_key
        self.llm = llm
        self.chunks_path = chunks_path
        self.results: list[Any] = []

    def turn(self, utterance: str) -> Observation:
        result = self._core.diagnose(
            utterance,
            self.state,
            llm=self.llm,
            chunks_path=self.chunks_path,
            thread_id=self.thread_id,
        )
        self.results.append(result)
        output = AgentOutput(
            category=result.category,
            taxonomy_id=result.taxonomy_id,
            step_id=result.step_id,
            escalate=result.escalate,
            device_model=self.state.device.reported_model,
            device_confidence=self.state.device.confidence,
            destructive_gate=result.destructive_gate,
            rationale=result.rationale,
            candidates=[c.as_ontology_candidate() for c in result.candidates],
        )
        return Observation(
            output=output,
            resolved=bool(
                self.state.notes.get("resolution_confirmed_at_turn") == self.state.turn
            ),
            fsm_state=self.state.state.value,
            response_text=result.response_text,
        )

    def record_attempt(self, entry: AttemptedStep) -> None:
        """No-op, deliberately.

        The core keeps its own ledger inside `EVALUATE_OUTCOME`. Feeding it the
        harness's copy would make M4 self-certifying: the agent would be scored
        against the ledger the harness wrote for it. Leaving this empty is what
        makes "the agent forgot to record a failed step" a measurable M4 breach.
        """


class CoreDriver:
    name = "core-text-diagnostic"

    def __init__(self, llm: Any | None = None, *, chunks_path: str | None = None):
        if llm is None:
            from agent import llm as llm_module

            llm = llm_module.BedrockLLM()
        self.llm = llm
        self.chunks_path = chunks_path

    def open(self, scenario: Scenario, session_key: str) -> CoreSession:
        return CoreSession(scenario, session_key, self.llm, self.chunks_path)


class BaselineSession:
    """The Phase 0 floor, given a conversation it has no way to use.

    The dumb baseline is single-turn by construction: a keyword router over the
    caller's words and the first legal candidate. Harness B gives it everything
    the core gets -- the full transcript so far as the symptom text, and the
    ledger, which it cannot build for itself -- so that when it fails the branch
    check the reason is that a first-keyword-wins router has no notion of a
    question it asked, not that it was starved of the answer.
    """

    def __init__(self, scenario: Scenario):
        from .baseline import DumbBaselineAgent

        self.agent = DumbBaselineAgent()
        self.state = state_from_scenario(scenario)
        self.transcript: list[str] = []
        self.ledger: list[AttemptedStep] = list(scenario.ledger)

    def turn(self, utterance: str) -> Observation:
        self.transcript.append(utterance)
        self.state.problem.verbatim_symptom = " ".join(self.transcript)
        self.state.ledger.attempted = list(self.ledger)
        return Observation(output=self.agent.propose(self.state))

    def record_attempt(self, entry: AttemptedStep) -> None:
        self.ledger.append(entry)


class BaselineDriver:
    name = "dumb-rule-based-baseline"

    def open(self, scenario: Scenario, session_key: str) -> BaselineSession:
        return BaselineSession(scenario)


#: Same two names Harness A offers, for the same reason: the comparison is only
#: meaningful if both agents go through identical scoring.
DRIVER_NAMES = ("dumb", "core")


def build_driver(name: str = "dumb", **kwargs: Any) -> Driver:
    if name == "dumb":
        if kwargs:
            raise TypeError(f"the dumb baseline takes no options; got {sorted(kwargs)}")
        return BaselineDriver()
    if name == "core":
        return CoreDriver(**kwargs)
    raise ValueError(f"unknown driver {name!r}; expected one of {DRIVER_NAMES}")


# --------------------------------------------------------------------------
# Running one scripted conversation
# --------------------------------------------------------------------------

#: Which metrics a turn is graded on. The first turn has `docs/03`'s own
#: expectation; the branch turn has the branch's; any other turn has neither,
#: so only the hard constraints and the device rule are graded. Grading a turn
#: `docs/03` says nothing about would be inventing an expected answer, which is
#: the one thing a golden set may not do.
ALL_METRICS = ("m1_device", "m2_category", "m3_next_step", "m4_no_repeat", "m5_harmful")
HARD_ONLY = ("m1_device", "m4_no_repeat", "m5_harmful")


@dataclass
class TurnRecord:
    index: int
    utterance: str
    observation: Observation
    result: ScenarioResult
    #: Metric attribute names graded on this turn.
    graded: tuple[str, ...]
    #: Whether M6 (escalation) is graded on this turn.
    graded_m6: bool
    #: The harness ledger as it stood *before* this turn was scored.
    ledger_before: tuple[str, ...]
    role: str  # "opening" | "branch" | "follow-up"
    reply: Reply | None = None

    @property
    def output(self) -> AgentOutput:
        return self.observation.output


@dataclass
class RunResult:
    scenario_id: str
    part: str
    driver_name: str
    branch_name: str
    turns: list[TurnRecord] = field(default_factory=list)
    #: The turn on which the agent asked the scripted branching question.
    question_asked_at: int | None = None
    branch_turn_index: int | None = None
    branch_implied: str | None = None
    branch_taken: str | None = None
    branch_pass: bool = False
    branch_detail: str = ""

    @property
    def m4_breaches(self) -> list[tuple[int, str]]:
        return [(t.index, b) for t in self.turns for b in t.result.m4_breaches]

    @property
    def m5_breaches(self) -> list[tuple[int, str]]:
        return [(t.index, b) for t in self.turns for b in t.result.m5_breaches]

    @property
    def hard_constraints_held(self) -> bool:
        return not self.m4_breaches and not self.m5_breaches

    @property
    def passed(self) -> bool:
        """A run passes when the agent took the branch its question implied and
        broke neither hard constraint. M2/M3 are scores, not gates (`docs/03`:
        "Hard constraints are pass/fail, not scored")."""
        return self.branch_pass and self.hard_constraints_held


def _raw_ledger(entries: list[AttemptedStep]) -> list[dict[str, Any]]:
    return [
        {
            "step_id": e.step_id,
            "step_family": e.step_family,
            "source": e.source,
            "outcome": e.outcome,
            "count": e.count,
            "verbatim": e.verbatim,
            "also_blocks": list(e.also_blocks),
        }
        for e in entries
    ]


def turn_scenario(
    scenario: Scenario,
    ledger: list[AttemptedStep],
    *,
    categories: tuple[str, ...] | None = None,
    step_ids: tuple[str | None, ...] | None = None,
    escalate: bool | None = None,
) -> Scenario:
    """The scenario *as it stands at this turn*, for `eval.harness.score`.

    Same scenario -- same harmful steps, same footage-at-stake, same driving
    flag, same expected device -- with the ledger replaced by the harness's
    running copy and the expectation replaced by the branch's where there is
    one. Building the input rather than copying the scorers is what keeps one
    implementation of M1-M6 in the repository.
    """
    return replace(
        scenario,
        known_context={**scenario.known_context, "tried": _raw_ledger(ledger)},
        expected_category=(
            list(categories) if categories is not None else scenario.expected_category
        ),
        expected_step_ids=(
            list(step_ids) if step_ids is not None else scenario.expected_step_ids
        ),
        escalation_expected=(
            bool(escalate) if escalate is not None else scenario.escalation_expected
        ),
    )


def branch_matches(branch: Branch, observation: Observation) -> bool:
    """Does this turn look like the branch? Signature only -- never M3."""
    output = observation.output
    if branch.escalate is not None and output.escalate != branch.escalate:
        return False
    if branch.categories is not None and output.category not in branch.categories:
        return False
    if output.step_id is not None and output.step_id in branch.forbidden_step_ids:
        return False
    if (
        branch.resolved is not None
        and observation.resolved is not None
        and observation.resolved != branch.resolved
    ):
        return False
    return True


def _check_contract(driver_name: str, scenario_id: str, output: AgentOutput) -> None:
    """The same two contract checks `harness.run_harness` makes."""
    if output.step_id is not None and output.step_id not in ontology.STEPS:
        raise ValueError(
            f"{driver_name} proposed step {output.step_id!r} on {scenario_id}, "
            "which is not in the ontology -- free text is not a step (06 §3.6)"
        )
    if output.category not in ontology.CATEGORIES:
        raise ValueError(
            f"{driver_name} returned category {output.category!r} on "
            f"{scenario_id}, which is not one of {sorted(ontology.CATEGORIES)}"
        )


def run_script(
    driver: Driver,
    scenario: Scenario,
    script: Script,
    branch: Branch,
    *,
    max_turns: int = MAX_TURNS,
) -> RunResult:
    """One scripted conversation: one scenario, one branch, up to `max_turns`."""
    session_key = f"harness-b::{driver.name}::{scenario.id}::{branch.name}"
    session = driver.open(scenario, session_key)
    responder = ScriptedResponder(script, branch)
    ledger: list[AttemptedStep] = list(scenario.ledger)
    run = RunResult(
        scenario_id=scenario.id,
        part=scenario.part,
        driver_name=driver.name,
        branch_name=branch.name,
    )

    utterance = scenario.utterance
    for index in range(1, max_turns + 1):
        ledger_before = tuple(e.step_id for e in ledger)
        observation = session.turn(utterance)
        _check_contract(driver.name, scenario.id, observation.output)

        is_branch_turn = (
            responder.answered_at_turn is not None
            and index == responder.answered_at_turn + 1
        )
        if index == 1:
            role, graded, graded_m6 = "opening", ALL_METRICS, True
            scored = turn_scenario(scenario, ledger)
        elif is_branch_turn:
            role, graded_m6 = "branch", branch.escalate is not None
            graded = tuple(
                m
                for m in ALL_METRICS
                if m in HARD_ONLY
                or (m == "m2_category" and branch.categories is not None)
                or (m == "m3_next_step" and branch.step_ids is not None)
            )
            scored = turn_scenario(
                scenario,
                ledger,
                categories=branch.categories,
                step_ids=branch.step_ids,
                escalate=branch.escalate,
            )
        else:
            role, graded, graded_m6 = "follow-up", HARD_ONLY, False
            scored = turn_scenario(scenario, ledger)

        record = TurnRecord(
            index=index,
            utterance=utterance,
            observation=observation,
            result=score(scored, observation.output),
            graded=graded,
            graded_m6=graded_m6,
            ledger_before=ledger_before,
            role=role,
        )
        run.turns.append(record)

        if is_branch_turn:
            run.branch_turn_index = index
            run.branch_implied = branch.name
            run.branch_pass = branch_matches(branch, observation)
            if run.branch_pass:
                run.branch_taken = branch.name
                run.branch_detail = "took the branch its own question implied"
            else:
                others = [
                    b.name
                    for b in script.branches
                    if b.name != branch.name and branch_matches(b, observation)
                ]
                run.branch_taken = others[0] if len(others) == 1 else None
                run.branch_detail = _branch_failure_detail(branch, observation, others)

        step_id = observation.output.step_id
        if step_id is None or observation.output.escalate:
            #: Nothing left to answer: the turn closed the session, or the
            #: handoff has been delivered and §3.2 sends the next turn to CLOSE.
            break

        reply = responder.reply_to(step_id, index)
        record.reply = reply
        if responder.answered_at_turn == index:
            run.question_asked_at = index
        step = ontology.STEPS[step_id]
        ledger.append(
            AttemptedStep(
                step_id=step_id,
                step_family=step.family,
                source="agent_proposed",
                outcome=reply.outcome,
                turn=index,
                verbatim=reply.text,
            )
        )
        session.record_attempt(ledger[-1])
        utterance = reply.text

    if run.branch_turn_index is None:
        run.branch_implied = None
        run.branch_taken = None
        run.branch_pass = False
        run.branch_detail = (
            "never asked the branching question "
            f"({' or '.join(script.question_step_ids)}), so there was no answer "
            "to act on and no branch to take"
        )
    return run


def _branch_failure_detail(
    branch: Branch, observation: Observation, others: list[str]
) -> str:
    output = observation.output
    reasons: list[str] = []
    if branch.escalate is not None and output.escalate != branch.escalate:
        reasons.append(
            f"escalate={output.escalate}, branch implies {branch.escalate}"
        )
    if branch.categories is not None and output.category not in branch.categories:
        reasons.append(
            f"category={output.category}, branch implies "
            f"{'/'.join(branch.categories)}"
        )
    if output.step_id is not None and output.step_id in branch.forbidden_step_ids:
        reasons.append(f"proposed {output.step_id}, which the answer rules out")
    if (
        branch.resolved is not None
        and observation.resolved is not None
        and observation.resolved != branch.resolved
    ):
        reasons.append(
            f"resolved={observation.resolved}, branch implies {branch.resolved}"
        )
    tail = f"; looks like branch {others[0]}" if len(others) == 1 else ""
    return "; ".join(reasons) + tail if reasons else "signature did not match" + tail


# --------------------------------------------------------------------------
# Running the set
# --------------------------------------------------------------------------


@dataclass
class HarnessBReport:
    driver_name: str
    runs: list[RunResult]

    @property
    def parts(self) -> list[str]:
        seen: list[str] = []
        for run in self.runs:
            if run.part not in seen:
                seen.append(run.part)
        return seen

    def graded_turns(self, metric: str, part: str | None = None) -> list[TurnRecord]:
        return [
            t
            for run in self.runs
            if part is None or run.part == part
            for t in run.turns
            if metric in t.graded
        ]

    def m6_turns(self, part: str | None = None) -> list[TurnRecord]:
        return [
            t
            for run in self.runs
            if part is None or run.part == part
            for t in run.turns
            if t.graded_m6
        ]

    @property
    def total_turns(self) -> int:
        return sum(len(run.turns) for run in self.runs)

    @property
    def m4_breaches(self) -> list[tuple[RunResult, int, str]]:
        return [(r, i, b) for r in self.runs for i, b in r.m4_breaches]

    @property
    def m5_breaches(self) -> list[tuple[RunResult, int, str]]:
        return [(r, i, b) for r in self.runs for i, b in r.m5_breaches]

    @property
    def branch_passes(self) -> int:
        return sum(1 for r in self.runs if r.branch_pass)

    @property
    def questions_asked(self) -> int:
        return sum(1 for r in self.runs if r.question_asked_at is not None)

    def scenario_verdicts(self) -> dict[str, bool]:
        """A scenario passes only if **every** branch of it passed."""
        out: dict[str, bool] = {}
        for run in self.runs:
            out[run.scenario_id] = out.get(run.scenario_id, True) and run.passed
        return out


def harness_b_scenarios(
    scenarios: list[Scenario] | None = None,
    ids: tuple[str, ...] = HARNESS_B_IDS,
) -> list[Scenario]:
    """The `docs/06` §7.3 scenarios, taken from the full golden set.

    The whole set is loaded and validated first: a Harness B that could run
    against a drifted scenario file would be measuring something other than the
    golden set.
    """
    scenarios = scenarios if scenarios is not None else load_scenarios()
    by_id = {s.id: s for s in scenarios}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ScriptError(f"golden set is missing Harness B scenarios: {missing}")
    return [by_id[i] for i in ids]


def run_harness_b(
    driver: Driver,
    scenarios: list[Scenario] | None = None,
    scripts: dict[str, Script] | None = None,
    *,
    max_turns: int = MAX_TURNS,
) -> HarnessBReport:
    """Every branch of every scripted scenario, one conversation each."""
    scripts = scripts if scripts is not None else SCRIPTS
    ids = tuple(sorted(scripts))
    runs: list[RunResult] = []
    for scenario in harness_b_scenarios(scenarios, ids):
        script = scripts[scenario.id]
        for branch in script.branches:
            runs.append(
                run_script(driver, scenario, script, branch, max_turns=max_turns)
            )
    return HarnessBReport(driver_name=driver.name, runs=runs)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

_METRIC_LABELS = [
    ("m1_device", "M1 device"),
    ("m2_category", "M2 category"),
    ("m3_next_step", "M3 next step"),
    ("m4_no_repeat", "M4 no-repeat"),
    ("m5_harmful", "M5 harmful"),
]


def _cell(turns: list[TurnRecord], metric: str) -> str:
    if not turns:
        return "n/a"
    passes = sum(1 for t in turns if getattr(t.result, metric))
    return f"{passes}/{len(turns)} ({100.0 * passes / len(turns):5.1f}%)"


def format_report_b(report: HarnessBReport, *, transcripts: bool = False) -> str:
    lines: list[str] = []
    runs = report.runs
    lines.append(
        f"Harness B — scripted multi-turn ({len(runs)} runs over "
        f"{len(set(r.scenario_id for r in runs))} scenarios, "
        f"{report.total_turns} turns) — agent: {report.driver_name}"
    )
    lines.append("")

    # ---- the branch check: the reason this harness exists ----------------
    lines.append(
        "Branch check — did the agent take the branch its own question implied?"
    )
    header = (
        f"{'scenario':<10}{'branch played':<31}{'asked':<8}"
        f"{'branch taken':<31}{'verdict':<7}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for run in runs:
        asked = f"turn {run.question_asked_at}" if run.question_asked_at else "never"
        taken = run.branch_taken or "—"
        lines.append(
            f"{run.scenario_id:<10}{run.branch_name:<31}{asked:<8}"
            f"{taken:<31}{'PASS' if run.branch_pass else 'FAIL':<7}"
        )
        if not run.branch_pass:
            lines.append(f"{'':<10}  ↳ {run.branch_detail}")
    lines.append("")
    lines.append(
        f"  branch check: {report.branch_passes}/{len(runs)} runs; the branching "
        f"question was asked in {report.questions_asked}/{len(runs)}."
    )
    lines.append(
        "  A run that never asks the question cannot pass: there is no answer to "
        "ignore or act on."
    )
    lines.append("")

    # ---- M1-M5, per part -------------------------------------------------
    lines.append("M1–M5 across the multi-turn runs, per part, over graded turns")
    header = f"{'part':<12}{'runs':>5}{'turns':>6}  " + "  ".join(
        f"{label:>16}" for _, label in _METRIC_LABELS
    )
    lines.append(header)
    lines.append("-" * len(header))
    for part in report.parts:
        part_runs = [r for r in runs if r.part == part]
        turns = sum(len(r.turns) for r in part_runs)
        row = f"{part:<12}{len(part_runs):>5}{turns:>6}  " + "  ".join(
            f"{_cell(report.graded_turns(metric, part), metric):>16}"
            for metric, _ in _METRIC_LABELS
        )
        lines.append(row)
    lines.append("")
    lines.append(
        "No aggregate row by design (06 §7.3). A cell counts only the turns that "
        "metric is"
    )
    lines.append(
        "graded on: turn 1 against docs/03's own expectation, the branch turn "
        "against the"
    )
    lines.append(
        "branch, and any further turn on the hard constraints and M1 alone — "
        "docs/03 states"
    )
    lines.append("no expected next step for a third turn, so none is invented.")
    lines.append("")

    # ---- M6 --------------------------------------------------------------
    lines.append("M6 escalation correctness — precision and recall, always together")
    esc_header = (
        f"{'part':<12}{'TP':>4}{'FP':>4}{'FN':>4}{'TN':>4}"
        f"{'precision':>11}{'recall':>9}{'exact':>15}"
    )
    lines.append(esc_header)
    lines.append("-" * len(esc_header))
    totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    graded_m6_all = report.m6_turns()
    for part in report.parts:
        counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        turns = report.m6_turns(part)
        for t in turns:
            counts[t.result.escalation_class] += 1
        for k in counts:
            totals[k] += counts[k]
        lines.append(_esc_row(part, counts, turns))
    lines.append(_esc_row("ALL", totals, graded_m6_all))
    lines.append("")
    lines.append(
        "  Counted over graded turns only: the opening turn of all 8 scenarios "
        "(03 expects no"
    )
    lines.append(
        "  escalation on any of them) plus every branch turn whose docs/03 "
        "outcome line says."
    )
    lines.append("")

    # ---- hard constraints ------------------------------------------------
    m4 = report.m4_breaches
    m5 = report.m5_breaches
    lines.append(
        f"Hard-constraint breaches — M4: {len(m4)}, M5: {len(m5)} "
        f"(over all {report.total_turns} turns of all {len(runs)} runs)"
    )
    for run, index, breach in m4:
        lines.append(
            f"  [M4] {run.scenario_id}/{run.branch_name} turn {index}: {breach}"
        )
    for run, index, breach in m5:
        lines.append(
            f"  [M5] {run.scenario_id}/{run.branch_name} turn {index}: {breach}"
        )
    if not m4 and not m5:
        lines.append(
            "  none — the policy filter held across every turn of every "
            "conversation."
        )
    lines.append("")

    # ---- per-scenario verdict -------------------------------------------
    lines.append(
        "Per-scenario verdict (every branch must pass, and no hard constraint "
        "may break):"
    )
    verdicts = report.scenario_verdicts()
    for scenario_id, ok in verdicts.items():
        branch_runs = [r for r in runs if r.scenario_id == scenario_id]
        detail = ", ".join(
            f"{r.branch_name}={'pass' if r.passed else 'fail'}" for r in branch_runs
        )
        lines.append(
            f"  {scenario_id}  {'PASS' if ok else 'FAIL'}  {detail}"
        )
    passed = sum(1 for ok in verdicts.values() if ok)
    lines.append(f"  {passed}/{len(verdicts)} scenarios")
    lines.append("")

    # ---- Phase 1 exit criterion -----------------------------------------
    m4_turns = report.graded_turns("m4_no_repeat")
    m4_pass = sum(1 for t in m4_turns if t.result.m4_no_repeat)
    lines.append("docs/06 §9.1 Phase 1 exit, measured on Harness B:")
    lines.append(
        f"  M4 no-repeat: {m4_pass}/{len(m4_turns)} turns "
        f"({100.0 * m4_pass / len(m4_turns) if m4_turns else 0.0:.1f}%) — "
        f"required 100%"
    )
    lines.append(f"  M5 harmful advice: {len(m5)} breaches — required 0")
    lines.append(
        "  This is a measurement of these runs, not a claim about the agent. "
        "Phase 1 exit"
    )
    lines.append(
        "  needs M4 = 100% and M5 = 0 on Harness A **and** B; the Harness A "
        "half is `eval.run`."
    )

    if transcripts:
        lines.append("")
        lines.append("Transcripts:")
        for run in runs:
            lines.append(f"  {run.scenario_id} / {run.branch_name}")
            for t in run.turns:
                lines.append(f"    user  {t.index}: {t.utterance}")
                lines.append(
                    f"    agent {t.index}: [{t.role}] {t.output.taxonomy_id} "
                    f"{t.output.step_id or '<no step>'}"
                    f"{' ESCALATE' if t.output.escalate else ''}"
                )
    return "\n".join(lines)


def _esc_row(label: str, counts: dict[str, int], turns: list[TurnRecord]) -> str:
    predicted = counts["tp"] + counts["fp"]
    actual = counts["tp"] + counts["fn"]
    precision = f"{counts['tp'] / predicted:.2f}" if predicted else "n/a"
    recall = f"{counts['tp'] / actual:.2f}" if actual else "n/a"
    exact = (
        f"{sum(1 for t in turns if t.result.m6_escalation)}/{len(turns)}"
        if turns
        else "n/a"
    )
    return (
        f"{label:<12}{counts['tp']:>4}{counts['fp']:>4}{counts['fn']:>4}"
        f"{counts['tn']:>4}{precision:>11}{recall:>9}{exact:>15}"
    )


__all__ = [
    "BRANCHING_IDS",
    "HARNESS_B_IDS",
    "MAX_TURNS",
    "MULTI_TURN_IDS",
    "SCRIPTS",
    "Branch",
    "BaselineDriver",
    "CoreDriver",
    "HarnessBReport",
    "Observation",
    "Reply",
    "RunResult",
    "Script",
    "ScriptError",
    "ScriptedResponder",
    "TurnRecord",
    "branch_matches",
    "build_driver",
    "format_report_b",
    "harness_b_scenarios",
    "run_harness_b",
    "run_script",
    "turn_scenario",
    "validate_scripts",
]
