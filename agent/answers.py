"""Answers: the typed record of what the caller said when we asked (`docs/06` §3.3).

Milestone 4.4. This module exists because of one hole, and the hole has two
visible symptoms.

`docs/06` §3.3 keeps two stores apart and says the policy layer reads only the
typed one:

    The policy layer never reads the transcript. If a fact is not in
    `DiagnosticState`, it does not exist for decision-making.

The ledger makes that true for **attempted steps**. Nothing made it true for
**answers**. A question is a step like any other, but its product is not an
outcome — it is information — and `AttemptedStep.outcome` has nowhere to put
it. So the answer landed in the transcript, the policy layer could not read the
transcript, and therefore:

1. **An answered question was re-proposed.** `FAMILY.ASK` and `FAMILY.OBSERVE`
   are `no_repeat_exempt` by design (§3.6: "asking someone to read the screen
   again, after something has changed, is not repetition"), so the no-repeat
   filter correctly does not block them — and nothing else blocked them either.
   Harness B on master: EVAL-07 asked `STEP.ASK.WERE_CLIPS_LOCKED` four turns
   running after being told none of the clips were locked.
2. **The branch the answer implies was never taken.** Every one of the
   branching scenarios in `docs/06` §7.3 turns on a `docs/02` **"Escalate
   when:"** line that is conditioned on the answer to that entry's **"Must
   ask:"** question. `docs/06` §5.1 lists those per-entry triggers as one of the
   four escalation sources. With no answer in the record they could not be
   evaluated, so `policy.escalation` implemented exactly one of them (`FW-02`,
   which is unconditional) and Harness B measured M6 recall 0.00 on every
   branch turn.

Both are the same missing object, so this module supplies it once:

* `ANSWER_RULES` — per question step id, the **documented readings** of an
  answer, transcribed from that entry's `docs/02` *"What would confirm /
  disconfirm it"* line. Nothing here is invented; every rule carries the
  sentence it came from in `source`.
* `ANSWER_TRIGGERS` — per `(question, reading)`, the `docs/02` **"Escalate
  when:"** line that reading satisfies. These are policy triggers, evaluated in
  `agent/policy.py`; the model is not consulted, on the same reasoning that
  already keeps `policy.escalation` rule-derived.
* `CROSS_CHECKS` — the four `cross-check` cross-references `docs/02`'s ranked
  cause lists actually contain, used by triage to put the cross-checked entry
  on the shortlist when the caller's own words carry its discriminating
  condition (`agent/symptoms.ENTRY_DISCRIMINATORS`).

**Matching is deterministic and rule-based, with no model in the loop**, for the
reason `agent/core.parse_outcome` gives about ledger outcomes: what blocks a
step and what fires an escalation is not a thing a model may decide. The
patterns name the *content* of a reading and never its polarity — no rule keys
on a bare "yes" or "no" — because the branch replies in `docs/03` routinely
open with the opposite polarity to their meaning ("**No**, it drops right in the
middle of downloading a clip" is the escalating answer).

**An answer the rules cannot read is `UNKNOWN`, and `UNKNOWN` still counts as
answered.** `docs/06` §3.6 treats an ambiguous mapping as attempted — "fail
safe" — and §3.4 is blunt about the alternative: "Asking the same question
louder is not a strategy." A caller who said "I don't know, I haven't checked"
has answered; asking again adds nothing and costs a turn.

**One disagreement, recorded rather than resolved.** `docs/02` `APP-03`'s
"Escalate when:" line says a firmly declined permission escalates. `docs/03`
EVAL-26 says the opposite in as many words: "No escalation if granted. Close
honestly as a product limitation if the caller declines on privacy grounds —
that is their decision, not a fault." `docs/03` is what the harnesses grade
against, so no trigger is registered for that reading and the disagreement is
noted here, in the same spirit as `agent/policy.py`'s note on UNVERIFIED
entries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from eval import ontology

#: The value recorded when the reply answers the question in no way the
#: `docs/02` readings recognise. Still an answer: see the module docstring.
UNKNOWN_READING = "unknown"


# --------------------------------------------------------------------------
# Readings and rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One documented way a `docs/02` question can come back answered.

    `patterns` are regexes over the lower-cased reply. They name what the
    reading *says*, never whether it starts with yes or no.

    `recategorise_to` is the taxonomy entry this reading sends the conversation
    to, where `docs/02` or `docs/03` names one — `docs/03` EVAL-23 is the
    clearest: "Re-categorise to `PWR-02` if the camera is restarting; back to
    `WIFI-04` if not." It is a branch the document dictates, not a preference.
    """

    name: str
    patterns: tuple[str, ...]
    meaning: str
    recategorise_to: str | None = None


@dataclass(frozen=True)
class AnswerRule:
    """How to read the answer to one question step.

    `readings` is ordered and the **first match wins**. Order is load-bearing
    only as a tie-break: the patterns are written so that a reply can match at
    most one reading, and `agent/test_answers.py` pins every scripted
    `docs/03` reply to the reading it must produce.

    `volunteer_context` is non-empty only for a question whose answer `docs/03`
    records as *caller-stated in the opening utterance* — `docs/06` §3.6 makes
    mapping volunteered information onto canonical ids a per-turn job, and
    EVAL-26's known context says outright "Permission: local network denied
    (caller-stated)". Volunteered capture additionally requires one of these
    phrases to be present, so a reading cannot be picked up from an utterance
    that was never about this question.
    """

    step_id: str
    readings: tuple[Reading, ...]
    source: str
    volunteer_context: tuple[str, ...] = ()

    @property
    def volunteerable(self) -> bool:
        return bool(self.volunteer_context)

    def reading_names(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.readings)


#: Question step id -> how `docs/02` says its answer reads.
#:
#: Every `source` quotes the entry's own *"What would confirm / disconfirm it"*
#: line. Where a reading escalates, `ANSWER_TRIGGERS` below carries the entry's
#: *"Escalate when:"* line as well, and the two are kept apart on purpose:
#: reading an answer and deciding what it costs are different jobs.
ANSWER_RULES: dict[str, AnswerRule] = {
    # ---- 02 REC-03 (03 EVAL-07) -----------------------------------------
    "STEP.ASK.WERE_CLIPS_LOCKED": AnswerRule(
        step_id="STEP.ASK.WERE_CLIPS_LOCKED",
        readings=(
            Reading(
                name="ordinary_clips",
                patterns=(
                    r"\bnone (?:of them )?(?:were|was)\b",
                    r"\bnot locked\b",
                    r"\bweren'?t locked\b",
                    r"\bwasn'?t locked\b",
                    r"\bnormal recordings?\b",
                    r"\bordinary (?:clips?|recordings?|files?|footage)\b",
                    r"\bjust the (?:normal|usual|ordinary)\b",
                ),
                meaning=(
                    "ordinary unlocked clips — loop recording behaving as "
                    "designed (02 REC-03 cause 1); explain it and close "
                    "honestly as a non-fault"
                ),
            ),
            Reading(
                name="locked_clip_vanished",
                patterns=(
                    r"\bi locked\b",
                    r"\blocked (?:it|that|that one|them|those)\b",
                    r"\bit was locked\b",
                    r"\bthey were locked\b",
                    r"\bmarked (?:it |them )?as an? event\b",
                ),
                meaning=(
                    "the caller is confident a clip they locked has "
                    "disappeared — a real defect in the lock or event path "
                    "(02 REC-03)"
                ),
            ),
        ),
        source=(
            "02 REC-03 'What would confirm / disconfirm it': 'Ordinary "
            "unlocked clips -> loop recording behaving as designed (cause 1)... "
            "The caller is confident a clip they locked has disappeared -> a "
            "real defect in the lock or event path, which escalates.'"
        ),
    ),
    # ---- 02 WIFI-04 (03 EVAL-16) ----------------------------------------
    "STEP.ASK.DROP_IDLE_OR_ACTIVE": AnswerRule(
        step_id="STEP.ASK.DROP_IDLE_OR_ACTIVE",
        readings=(
            Reading(
                name="idle_only",
                patterns=(
                    r"\bstays connected\b",
                    r"\bleft (?:the|my) phone\b",
                    r"\bsitting there\b",
                    r"\bonly (?:drops|goes|happens)\b[^.]{0,40}\b(?:idle|sitting|left|alone)\b",
                    r"\bwhen (?:i'?m |i am )?not using\b",
                    r"\bidle\b",
                ),
                meaning=(
                    "the link holds while the app is busy and drops only once "
                    "the caller stops interacting — a designed idle timeout "
                    "(02 WIFI-04 cause 1), likely not a fault"
                ),
            ),
            Reading(
                name="drops_mid_transfer",
                patterns=(
                    r"\bmid[-\s]?(?:transfer|stream|download|playback)\b",
                    r"\b(?:middle|midst) of (?:a |the )?"
                    r"(?:download|downloading|transfer|transferring|stream|"
                    r"streaming|playing|watching)\b",
                    r"\bwhile (?:i'?m |i am )?(?:downloading|transferring|streaming)\b",
                    r"\bhalf ?way through (?:a |the )?(?:download|clip|video)\b",
                ),
                meaning=(
                    "the drop occurs mid-transfer, which makes the app "
                    "unusable for its stated purpose (02 WIFI-04)"
                ),
            ),
        ),
        source=(
            "02 WIFI-04 'What would confirm / disconfirm it': 'The link holds "
            "while the app is busy and drops only after the caller stops "
            "interacting -> designed idle timeout (cause 1), likely not a "
            "fault. It still drops mid-stream...'"
        ),
    ),
    # ---- 02 SD-04 (03 EVAL-17) ------------------------------------------
    "STEP.ASK.CARD_SPECS_AND_RATING": AnswerRule(
        step_id="STEP.ASK.CARD_SPECS_AND_RATING",
        readings=(
            Reading(
                name="ordinary_consumer_card",
                patterns=(
                    r"\bnothing (?:about|on it about) endurance\b",
                    r"\bno endurance\b",
                    r"\bnot (?:a )?high[-\s]?endurance\b",
                    r"\b10 in a circle\b",
                    r"\bjust (?:a |an )?(?:class ?10|normal|ordinary|standard)\b",
                    r"\bordinary (?:consumer )?card\b",
                ),
                meaning=(
                    "an ordinary consumer card with no endurance rating — "
                    "the wrong card for continuous recording (02 SD-04 cause "
                    "2), and a correctly rated replacement is the test"
                ),
            ),
            Reading(
                name="correctly_rated_card",
                patterns=(
                    r"\bhigh[-\s]?endurance\b",
                    r"\bu3\b",
                    r"\bv30\b",
                    r"\bmade for dash ?cam",
                    r"\bdash ?cam(?:era)?[-\s]?rated\b",
                    r"\brated for (?:continuous|dash ?cam)",
                ),
                meaning=(
                    "a high-endurance, U3/V30-class card failing the same way "
                    "— suspicion moves off the card and onto the camera's "
                    "power or write path (02 SD-04 cause 3)"
                ),
            ),
        ),
        source=(
            "02 SD-04 'What would confirm / disconfirm it': 'An ordinary "
            "consumer card with no endurance rating -> wrong card for "
            "continuous recording (cause 2)... A high-endurance, U3/V30-class "
            "card of reasonable age failing the same way -> suspicion moves to "
            "the camera's power or write path (cause 3), which is an "
            "escalation, not a card purchase.'"
        ),
    ),
    # ---- 02 PWR-04 (03 EVAL-20) -----------------------------------------
    #
    # `docs/02`'s escalate-when says "on a unit still in warranty". The agent
    # may not make a warranty statement at all (`docs/03` EVAL-29), so the
    # signal read here is the **age the caller stated**, never a warranty
    # conclusion, and the escalating reading requires both halves: never held
    # the date, on a unit the caller describes as recently bought. A long-owned
    # unit that never held the date reads as `UNKNOWN` and does not escalate —
    # conservative on purpose, because the alternative is inferring a warranty
    # position the agent is forbidden to state.
    "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY": AnswerRule(
        step_id="STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
        readings=(
            Reading(
                name="never_held_date_young_unit",
                patterns=(
                    r"(?:\bnever\b[^.]{0,30}\b(?:held|kept|holds|keeps)\b|"
                    r"\b(?:held|kept|holds|keeps)\b[^.]{0,20}\bnever\b)"
                    r"[\s\S]{0,120}"
                    r"(?:\bbrand new\b|\bjust bought\b|\bonly (?:bought|had|got)\b|"
                    r"\b(?:bought|got|had) it (?:about |only |just )?"
                    r"(?:a |one |two |three |four |five |six |\d+)\s*"
                    r"(?:weeks?|months?)\b)",
                    r"(?:\bbrand new\b|\bjust bought\b|\bonly (?:bought|had|got)\b|"
                    r"\b(?:bought|got|had) it (?:about |only |just )?"
                    r"(?:a |one |two |three |four |five |six |\d+)\s*"
                    r"(?:weeks?|months?)\b)"
                    r"[\s\S]{0,120}"
                    r"(?:\bnever\b[^.]{0,30}\b(?:held|kept|holds|keeps)\b|"
                    r"\b(?:held|kept|holds|keeps)\b[^.]{0,20}\bnever\b)",
                ),
                meaning=(
                    "the date has never survived a restart, on a unit the "
                    "caller describes as recently bought — the internal cell "
                    "or supercapacitor at end of life (02 PWR-04 cause 1), a "
                    "hardware answer the agent may suspect but not declare"
                ),
            ),
            Reading(
                name="held_date_before",
                patterns=(
                    r"\b(?:held|kept) the (?:date|time|clock)\b[^.]{0,40}"
                    r"\b(?:fine|ok|okay|alright|until|before|for years?|for months?)\b",
                    r"\bused to (?:hold|keep)\b",
                    r"\bit did hold\b",
                    r"\bwas fine (?:until|before)\b",
                ),
                meaning=(
                    "the camera held the date before and has stopped — an "
                    "ageing internal cell on an older unit, stated honestly "
                    "without a warranty or hardware declaration (02 PWR-04)"
                ),
            ),
        ),
        source=(
            "02 PWR-04 'What would confirm / disconfirm it': 'The date "
            "survives the restart after a long period on power -> the earlier "
            "attempts were never saved (cause 2)... The date is lost again "
            "after even a short disconnection -> the internal cell or "
            "supercapacitor is at end of life (cause 1), a hardware answer the "
            "agent may suspect but not declare.'"
        ),
    ),
    # ---- 02 FW-03 (03 EVAL-21) ------------------------------------------
    "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE": AnswerRule(
        step_id="STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        readings=(
            Reading(
                name="setting_was_reset",
                patterns=(
                    r"\b(?:had been|was|got|is) (?:switched|turned) off\b",
                    r"\bit was off\b",
                    r"\b(?:turned|switched|put) it back on\b",
                    r"\byou were right\b",
                    r"\bit had reset\b",
                ),
                meaning=(
                    "the update reset the setting — re-enable, retest, and the "
                    "call can close (02 FW-03)"
                ),
            ),
            Reading(
                name="setting_still_on",
                patterns=(
                    r"\bstill (?:switched |turned )?on\b",
                    r"\bis on\b[^.]{0,40}\bstill\b",
                    r"\bstill (?:does|doing|did) nothing\b",
                    r"\balready (?:switched |turned )?on\b",
                ),
                meaning=(
                    "the setting is present and correct and the feature still "
                    "fails — a suspected regression the agent cannot confirm "
                    "without a known-issue feed (02 FW-03, 01 §8 Q5)"
                ),
            ),
        ),
        source=(
            "02 FW-03 'What would confirm / disconfirm it': 'The setting is "
            "off -> the update reset it; re-enable, retest, and the call can "
            "close. The setting is confirmed on and the feature still does "
            "nothing -> a suspected regression, which the agent cannot confirm "
            "without a known-issue feed (01 §8 Q5) and must escalate.'"
        ),
    ),
    # ---- 02 PWR-02 (03 EVAL-23) -----------------------------------------
    #
    # The branch axis here is the **category**, not escalation: `docs/03`
    # EVAL-23's expected outcome is "No escalation. Re-categorise to `PWR-02`
    # if the camera is restarting; back to `WIFI-04` if not."
    "STEP.ASK.CAMERA_RESTARTS_IN_HEAT": AnswerRule(
        step_id="STEP.ASK.CAMERA_RESTARTS_IN_HEAT",
        readings=(
            Reading(
                name="wifi_only",
                patterns=(
                    r"\bstays on\b",
                    r"\bonly the wi-?fi\b",
                    r"\bjust the wi-?fi\b",
                    r"\bdoesn'?t (?:switch|turn|shut)\b[^.]{0,20}\boff\b",
                    r"\bnever (?:switches|turns|shuts)\b",
                ),
                meaning=(
                    "the camera stays on and only the Wi-Fi drops — back to "
                    "WIFI-04 (03 EVAL-23)"
                ),
                recategorise_to="WIFI-04",
            ),
            Reading(
                name="restarts_in_heat",
                patterns=(
                    r"\b(?:switch|switche[ds]|turn|turne[ds]|shut|shuts)\b"
                    r"[^.]{0,20}\bitself\b",
                    r"\brestart(?:s|ed|ing)?\b",
                    r"\breboot(?:s|ed|ing)?\b",
                    r"\bgone off\b",
                    r"\bgoes off\b",
                    r"\bshut(?:s|ting)? down\b",
                ),
                meaning=(
                    "the camera is cycling on the hot days — thermal "
                    "behaviour presenting as a Wi-Fi fault; re-categorise to "
                    "PWR-02 (03 EVAL-23)"
                ),
                recategorise_to="PWR-02",
            ),
        ),
        source=(
            "03 EVAL-23 expected outcome: 'Re-categorise to PWR-02 if the "
            "camera is restarting; back to WIFI-04 if not.' (02 WIFI-04 cause "
            "5 names the cross-check.)"
        ),
    ),
    "STEP.ASK.RECOVERS_WHEN_COOL": AnswerRule(
        step_id="STEP.ASK.RECOVERS_WHEN_COOL",
        readings=(
            Reading(
                name="wifi_only",
                patterns=(
                    r"\bstays on\b",
                    r"\bonly the wi-?fi\b",
                    r"\bjust the wi-?fi\b",
                    r"\bnever (?:switches|turns|shuts|goes) off\b",
                ),
                meaning="the camera never goes off at all — back to WIFI-04",
                recategorise_to="WIFI-04",
            ),
            Reading(
                name="recovers_when_cool",
                patterns=(
                    r"\bcomes? back\b",
                    r"\bcame back\b",
                    r"\bonce it(?:'?s)? cool(?:ed|s)?\b",
                    r"\bwhen it cools\b",
                    r"\bin the evening\b",
                ),
                meaning=(
                    "the camera returns once the car has cooled — thermal "
                    "cycling (02 PWR-02); re-categorise to PWR-02"
                ),
                recategorise_to="PWR-02",
            ),
        ),
        source=(
            "02 PWR-02 'Must ask' and its TO VERIFY discriminator: whether the "
            "camera comes back on by itself once the car has cooled down. 02 "
            "PWR-02 is explicit that recovery is unverified, so this reading "
            "re-categorises and never promises recovery."
        ),
    ),
    # ---- 02 APP-02 -> APP-03 (03 EVAL-26) --------------------------------
    "STEP.ASK.APP_PERMISSIONS_GRANTED": AnswerRule(
        step_id="STEP.ASK.APP_PERMISSIONS_GRANTED",
        readings=(
            Reading(
                name="permission_denied",
                patterns=(
                    r"\bi (?:think i )?said no\b",
                    r"\bsaid no\b",
                    r"\bdenied\b",
                    r"\b(?:didn'?t|did not|never) allow\b",
                    r"\brefused\b",
                    r"\bturned it down\b",
                    r"\bnot granted\b",
                ),
                meaning=(
                    "a permission the pairing flow needs was denied — the "
                    "branch moves to APP-03 (02 APP-02)"
                ),
                recategorise_to="APP-03",
            ),
            Reading(
                name="permission_granted",
                patterns=(
                    r"\bi (?:said|clicked|tapped) (?:yes|allow)\b",
                    r"\b(?:i'?ve )?allowed (?:it|them|everything)\b",
                    r"\b(?:they'?re|they are|it'?s) all (?:granted|allowed|on)\b",
                    r"\beverything (?:is )?(?:granted|allowed)\b",
                ),
                meaning=(
                    "the permissions are granted, so the failure is not a "
                    "permission one (02 APP-02 causes 2 and 4)"
                ),
            ),
        ),
        source=(
            "02 APP-02 'What would confirm / disconfirm it': '...the OS update "
            "revoked or tightened a permission (causes 1 and 3), and the "
            "branch moves to APP-03.'"
        ),
        #: `docs/03` EVAL-26 known context: "Permission: local network denied
        #: (caller-stated)". The caller volunteers this in the opening
        #: utterance, so the answer is already held before the question is put
        #: — and `docs/03` calls asking it again the wrong response outright.
        volunteer_context=(
            "local network",
            "permission",
            "permissions",
            "location",
            "nearby devices",
        ),
    ),
    # ---- 02 APP-03 (03 EVAL-26) ------------------------------------------
    #
    # No trigger is registered for `declined_firmly`: see the module docstring
    # on the 02/03 disagreement. 03 EVAL-26 governs.
    "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION": AnswerRule(
        step_id="STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",
        readings=(
            Reading(
                name="declined_firmly",
                patterns=(
                    r"\brather not\b",
                    r"\bi(?:'?ll| will) leave it\b",
                    r"\bnot (?:going to|gonna) allow\b",
                    r"\bno thank you\b",
                    r"\bstill no\b",
                ),
                meaning=(
                    "a firm decision, not a misunderstanding — a product "
                    "limitation to state honestly and close on, not a fault to "
                    "keep diagnosing (02 APP-03, 03 EVAL-26)"
                ),
            ),
            Reading(
                name="permission_granted",
                patterns=(
                    r"\b(?:i'?ve )?allowed it\b",
                    r"\bi(?:'?ve)? granted\b",
                    r"\bthat makes sense\b",
                    r"\bturned it on\b",
                ),
                meaning=(
                    "the caller accepted the explanation and granted it — "
                    "misunderstanding, and pairing can proceed (02 APP-03)"
                ),
            ),
        ),
        source=(
            "02 APP-03 'What would confirm / disconfirm it': 'The caller "
            "accepts the explanation and grants it -> misunderstanding, and "
            "pairing can proceed. The caller declines as a firm decision -> a "
            "product limitation to state honestly and close on, not a fault to "
            "keep diagnosing.'"
        ),
    ),
    # ---- 02 REC-02 + SD-01 (03 EVAL-27) ----------------------------------
    "STEP.ASK.CARD_FROZEN_IN_TIME": AnswerRule(
        step_id="STEP.ASK.CARD_FROZEN_IN_TIME",
        readings=(
            Reading(
                name="card_still_taking_writes",
                patterns=(
                    r"\bfrom last week\b",
                    r"\b(?:just|only) today\b",
                    r"\bstill (?:taking|writing|recording|adding)\b",
                    r"\bnewer stuff\b",
                ),
                meaning=(
                    "the card is still taking writes — the camera believes it "
                    "is writing and today's writes are not landing (03 "
                    "EVAL-27)"
                ),
            ),
            Reading(
                name="card_frozen_in_time",
                patterns=(
                    r"\bnothing (?:since|newer|after)\b",
                    r"\bnewest (?:file|clip|video|thing)\b",
                    r"\blatest (?:file|clip|video)\b[^.]{0,40}\bago\b",
                    r"\bfrozen\b",
                    r"\bstops? (?:dead )?(?:at|around)\b[^.]{0,30}\bago\b",
                ),
                meaning=(
                    "the card appears frozen at a point in time — gone "
                    "read-only at end of life, or counterfeit (03 EVAL-27); "
                    "likely card replacement and a check of its rating"
                ),
            ),
        ),
        source=(
            "03 EVAL-27 expected diagnosis: 'The camera believes it is writing "
            "and the writes are not landing. Suspect a card that has gone "
            "read-only at end of life, or a counterfeit card that reports more "
            "capacity than it has.' Expected next step: ask whether the oldest "
            "files are still there or the card appears frozen at a point in "
            "time."
        ),
    ),
}


# --------------------------------------------------------------------------
# Per-entry escalation triggers (docs/06 §5.1, docs/02 "Escalate when:")
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerTrigger:
    """A `docs/02` **"Escalate when:"** line, as a condition on an answer.

    `docs/06` §5.1 names four escalation sources and this is the second of
    them — "per-entry triggers". Before Milestone 4.4 only `FW-02` was
    implemented, because it is the one entry whose trigger is unconditional;
    every other per-entry trigger in `docs/02` is conditioned on the answer to
    that entry's **"Must ask:"** question, and the answer was not in the record.

    **Keyed on the question, not on the taxonomy entry.** `docs/02` files these
    lines under an entry because that is how the document is organised, but
    every one of them states a condition purely about the answer to a specific
    question. Keying on the entry would make the trigger miss whenever triage
    routed the same question under a neighbouring entry — `docs/03` EVAL-17 is
    exactly that case, graded on `SD-04`'s reasoning while the card question is
    also a `SD-01` candidate. The entry the line came from is named in `reason`
    so the trace still says where it is from.
    """

    step_id: str
    reading: str
    reason_code: str
    entry: str
    reason: str


#: `(question step id, reading name)` -> the trigger it satisfies.
ANSWER_TRIGGERS: dict[tuple[str, str], AnswerTrigger] = {
    (
        "STEP.ASK.WERE_CLIPS_LOCKED",
        "locked_clip_vanished",
    ): AnswerTrigger(
        step_id="STEP.ASK.WERE_CLIPS_LOCKED",
        reading="locked_clip_vanished",
        reason_code="locked_clip_vanished",
        entry="REC-03",
        reason=(
            "02 REC-03 escalate-when: the caller asserts a clip *was* locked "
            "and it still vanished — that is a defect, not an expectation gap"
        ),
    ),
    (
        "STEP.ASK.DROP_IDLE_OR_ACTIVE",
        "drops_mid_transfer",
    ): AnswerTrigger(
        step_id="STEP.ASK.DROP_IDLE_OR_ACTIVE",
        reading="drops_mid_transfer",
        reason_code="app_unusable_mid_transfer",
        entry="WIFI-04",
        reason=(
            "02 WIFI-04 escalate-when: the drop is consistent and occurs "
            "mid-transfer, making the app unusable for its stated purpose"
        ),
    ),
    (
        "STEP.ASK.CARD_SPECS_AND_RATING",
        "correctly_rated_card",
    ): AnswerTrigger(
        step_id="STEP.ASK.CARD_SPECS_AND_RATING",
        reading="correctly_rated_card",
        reason_code="suspected_write_path",
        entry="SD-04",
        reason=(
            "02 SD-04 escalate-when: a new, correctly-rated card shows the "
            "same cycle — that moves suspicion to the camera's power or write "
            "path"
        ),
    ),
    (
        "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
        "never_held_date_young_unit",
    ): AnswerTrigger(
        step_id="STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
        reading="never_held_date_young_unit",
        reason_code="suspected_hardware_clock",
        entry="PWR-04",
        reason=(
            "02 PWR-04 escalate-when: the date never survives a restart on a "
            "unit this young — suspected hardware, which the agent may suspect "
            "but not declare"
        ),
    ),
    (
        "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        "setting_still_on",
    ): AnswerTrigger(
        step_id="STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        reading="setting_still_on",
        reason_code="suspected_regression",
        entry="FW-03",
        reason=(
            "02 FW-03 escalate-when: the setting is present and correct and "
            "the feature still fails — a suspected regression that must reach "
            "someone who can confirm it against a known-issue list"
        ),
    ),
}


# --------------------------------------------------------------------------
# docs/02 cross-checks
# --------------------------------------------------------------------------

#: The four `cross-check` cross-references that appear in `docs/02`'s ranked
#: cause lists, transcribed. Nothing else in `docs/02` is marked as one.
#:
#: Triage consults this when the caller's own words carry the cross-checked
#: entry's discriminating condition (`agent/symptoms.ENTRY_DISCRIMINATORS`).
#: EVAL-23 is the case it exists for: `WIFI-04` cause 5 is "Camera overheating
#: and cycling (cross-check `PWR-02`)", the caller volunteers "it's been really
#: hot today", and `docs/03` says "the heat detail is the whole scenario and
#: ignoring it is the failure being tested". Without the link the heat question
#: is not even in the candidate set, because it belongs to `PWR-02` and triage
#: never shortlisted `PWR-02`.
CROSS_CHECKS: dict[str, tuple[str, ...]] = {
    "WIFI-04": ("PWR-02",),  # cause 5: camera overheating and cycling
    "SD-03": ("PWR-04",),  # cause 5: power instability during recording
    "SD-04": ("PWR-03", "PWR-04"),  # cause 3: power interruptions
    "PWR-04": ("SD-03",),  # cause 4: matching corruption
}


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


@lru_cache(maxsize=4096)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(_compiled(p).search(text) for p in patterns)


def read_answer(step_id: str, utterance: str) -> str:
    """How the reply to `step_id` reads, by the `docs/02` readings.

    Returns a reading name, or `UNKNOWN_READING` when no reading matches —
    including when the question has no rule at all. `UNKNOWN_READING` is a
    real answer: the caller was asked and replied, and `docs/06` §3.4 is
    explicit that asking again is not a strategy.
    """
    rule = ANSWER_RULES.get(step_id)
    text = (utterance or "").strip().lower()
    if rule is None or not text:
        return UNKNOWN_READING
    for reading in rule.readings:
        if _matches(text, reading.patterns):
            return reading.name
    return UNKNOWN_READING


def volunteered_answers(utterance: str) -> list[tuple[str, str]]:
    """`(question step id, reading)` the caller answered without being asked.

    `docs/06` §3.6 makes mapping volunteered information onto canonical ids a
    per-turn job of the slot extractor, and `docs/03` records at least one
    answer as caller-stated in the opening utterance (EVAL-26's denied
    local-network permission). Only rules carrying a `volunteer_context` are
    eligible, and the utterance must carry one of those phrases as well as
    match a reading — so a reading cannot be lifted out of an utterance that
    was never about the question.
    """
    text = (utterance or "").strip().lower()
    if not text:
        return []
    found: list[tuple[str, str]] = []
    for step_id, rule in ANSWER_RULES.items():
        if not rule.volunteerable:
            continue
        if not any(phrase in text for phrase in rule.volunteer_context):
            continue
        reading = read_answer(step_id, text)
        if reading != UNKNOWN_READING:
            found.append((step_id, reading))
    return found


def reading_for(step_id: str, reading: str) -> Reading | None:
    rule = ANSWER_RULES.get(step_id)
    if rule is None:
        return None
    for candidate in rule.readings:
        if candidate.name == reading:
            return candidate
    return None


def recategorisation_for(step_id: str, reading: str) -> str | None:
    """The taxonomy entry this answer sends the conversation to, if any."""
    found = reading_for(step_id, reading)
    return found.recategorise_to if found is not None else None


def recategorisation_targets(step_id: str) -> frozenset[str]:
    """Every taxonomy entry this question's answer can route the session to.

    Milestone 4.6. `recategorisation_for` answers "where did this *answer* send
    us"; this answers "where *could* this question send us", which is the
    §3.5 ranking input — a question whose readings land on two different
    entries is one whose answer settles which of them is the live cause, and
    `docs/06` §3.5 ranks by "expected information gain **across the live
    causes**".
    """
    rule = ANSWER_RULES.get(step_id)
    if rule is None:
        return frozenset()
    return frozenset(
        reading.recategorise_to
        for reading in rule.readings
        if reading.recategorise_to is not None
    )


def trigger_for(step_id: str, reading: str) -> AnswerTrigger | None:
    """The `docs/02` escalate-when line this answer satisfies, if any."""
    return ANSWER_TRIGGERS.get((step_id, reading))


def cross_checks_for(entry: str) -> tuple[str, ...]:
    return CROSS_CHECKS.get(entry, ())


# --------------------------------------------------------------------------
# Self-validation
# --------------------------------------------------------------------------


class AnswerRuleError(AssertionError):
    """A rule names something that is not in the ontology, or contradicts itself."""


def validate_rules(rules: dict[str, AnswerRule] | None = None) -> None:
    """Fail at import if a rule drifts from the ontology or the trigger table.

    The same bargain `eval/harness_b.validate_scripts` makes: a table
    transcribed from a document is only safe if something checks it still
    describes the system it was transcribed for.
    """
    rules = rules if rules is not None else ANSWER_RULES
    for step_id, rule in rules.items():
        if rule.step_id != step_id:
            raise AnswerRuleError(f"{step_id} rule is labelled {rule.step_id}")
        if step_id not in ontology.STEPS:
            raise AnswerRuleError(
                f"{step_id!r} is not in the step ontology — a rule cannot read "
                "the answer to a question that does not exist (06 §3.6)"
            )
        if len(rule.readings) < 2:
            raise AnswerRuleError(
                f"{step_id} has {len(rule.readings)} reading(s); a branch needs "
                "at least two to tell apart"
            )
        names = [r.name for r in rule.readings]
        if len(set(names)) != len(names):
            raise AnswerRuleError(f"{step_id} has duplicate reading names")
        if UNKNOWN_READING in names:
            raise AnswerRuleError(
                f"{step_id} declares a reading called {UNKNOWN_READING!r}, "
                "which is the reserved value for 'no reading matched'"
            )
        for reading in rule.readings:
            if not reading.patterns:
                raise AnswerRuleError(f"{step_id}/{reading.name} has no patterns")
            for pattern in reading.patterns:
                re.compile(pattern)
            if reading.recategorise_to is not None and (
                reading.recategorise_to not in ontology.TAXONOMY_CANDIDATES
            ):
                raise AnswerRuleError(
                    f"{step_id}/{reading.name} re-categorises to "
                    f"{reading.recategorise_to!r}, which is not a taxonomy entry"
                )
        if not rule.source.strip():
            raise AnswerRuleError(
                f"{step_id} cites no docs/02 or docs/03 line — every reading "
                "comes from the document, not from here"
            )
    for (step_id, reading), trigger in ANSWER_TRIGGERS.items():
        if step_id not in rules:
            raise AnswerRuleError(
                f"trigger on {step_id!r} has no rule to produce its reading"
            )
        if reading not in rules[step_id].reading_names():
            raise AnswerRuleError(
                f"trigger on {step_id}/{reading!r} names a reading that rule "
                f"does not produce: {rules[step_id].reading_names()}"
            )
        if (trigger.step_id, trigger.reading) != (step_id, reading):
            raise AnswerRuleError(f"trigger {step_id}/{reading} is mislabelled")
        if not trigger.reason.strip():
            raise AnswerRuleError(f"trigger {step_id}/{reading} cites no 02 line")
    for entry, crosses in CROSS_CHECKS.items():
        for other in (entry,) + crosses:
            if other not in ontology.TAXONOMY_CANDIDATES:
                raise AnswerRuleError(
                    f"cross-check names {other!r}, which is not a taxonomy entry"
                )


validate_rules()


__all__ = [
    "ANSWER_RULES",
    "ANSWER_TRIGGERS",
    "CROSS_CHECKS",
    "UNKNOWN_READING",
    "AnswerRule",
    "AnswerRuleError",
    "AnswerTrigger",
    "Reading",
    "cross_checks_for",
    "read_answer",
    "reading_for",
    "recategorisation_for",
    "recategorisation_targets",
    "trigger_for",
    "validate_rules",
    "volunteered_answers",
]
