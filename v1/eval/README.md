# `eval/` — Phase 0 harness, ontology and baseline

Everything here measures an agent. None of it *is* one. The package is stdlib-only —
no third-party dependencies, no AWS, no network — and is deliberately runnable before
any agent exists, so the floor is on record before the first real implementation can
be flattered by it.

| file | what it holds |
| --- | --- |
| `ontology.py` | the canonical step ontology (`docs/06` §3.6), step families, and the taxonomy-ID → candidate-step map (`docs/02`), plus the §3.5 policy filter |
| `harness.py` | Harness A: scenario loading and validation, `DiagnosticState`, the M1–M6 scorers, the report formatter |
| `scenarios.json` | the 30 golden scenarios (`docs/03`) |
| `baseline.py` | the deliberately dumb rule-based baseline |
| `run.py` | `python -m eval.run` — runs all 30 and prints the per-part table |
| `test_harness.py` | 35 stdlib unittest cases over the loader, ontology, scorers and baseline |
| `grounding.py` | the grounding measurement (`docs/06` §7.2) — captures the output guard's per-line verdict and scores it in two layers |
| `grounding_semantic.json` | the hand-graded semantic verdicts, with the rubric they were graded under |
| `run_grounding.py` | `python -m eval.run_grounding` — runs the core over both harnesses and prints both rates |
| `test_grounding.py` | 32 stdlib unittest cases pinning the measurement |
| `grounding_pack/` | the **two-grader grounding pack** (`docs/06` §7.4 item 1): 20 sampled claims with their chunk text, the rubric, a blank grading sheet and the grading instructions — ungraded by design |
| `build_grounding_pack.py` | `python -m eval.build_grounding_pack` — draws the sample and writes the pack |
| `score_grading.py` | `python -m eval.score_grading` — takes two completed sheets, prints Cohen's κ, the rates and the verdict against the 100 % bar |
| `test_score_grading.py` | 19 stdlib unittest cases over the κ maths, the sheet validation and the pack's shape |
| `harness_c.py` | Harness C: end-to-end **spoken**, through a real LiveKit room — clean, noise and ASR-corruption passes (`docs/06` §7.3) |
| `run_c.py` | `python -m eval.run_c` — brings up a media server and the API process, then speaks all 47 cases |
| `run_prefetch.py` | `python -m eval.run_prefetch` — speculative-prefetch hit rate (§2.1) over the Harness B utterances |
| `run_ladder.py` | `python -m eval.run_ladder` — replays measured M7 through §2.4's ladder until it fires **and** recovers |

**The stdlib-only claim above covers Harness A, Harness B and grounding, and
stops at Harness C.** `harness_c.py`, `run_c.py` and `run_prefetch.py` need
`httpx`, `numpy`, `websockets`, the `server/` package, the `livekit-server`
binary and AWS (Polly, Transcribe, Bedrock), because a harness that measures a
spoken pipeline without speaking is measuring something else. `run_ladder.py`
needs only `server/`; it is CPU-only and offline.

## Running it

```bash
.venv/bin/python -m eval.run                      # all 30 scenarios
.venv/bin/python -m eval.run --part contextual    # one part (the full set still loads)
.venv/bin/python -m eval.run --scenarios path.json
```

**Exit code.** `eval.run` exits non-zero only when the *harness* errors — a malformed
scenario set, an ontology inconsistency, an agent returning something that is not a
step. A low score is a result, not a failure. A runner that failed on a bad score
would make the floor measurement unrunnable in CI, which is the one place it has to
run.

Unit tests:

```bash
.venv/bin/python -m unittest discover -s eval     # 35 tests
.venv/bin/python -m unittest eval.test_harness -v # same tests, verbose
```

Both invocations work. `discover -s eval` makes `eval/` the top-level directory and
imports the test module with no parent package, so `test_harness.py` uses absolute
imports against a `sys.path` entry for the repo root rather than relative ones.

## The metrics

Harness A is **text-only and single-turn**: for each scenario it pre-populates a
`DiagnosticState` from the scenario's known context — the `Tried:` field becomes
ledger entries, which is what makes the contextual block testable at all — calls the
agent exactly once, and scores the single next step that comes back.

| id | metric | passes when |
| --- | --- | --- |
| **M1** | device identification | the agent reports the model correctly, **or** correctly reports `UNKNOWN` and does not then propose a model-specific step. Saying UNKNOWN *passes*: a confident wrong model is the failure being measured. |
| **M2** | category accuracy | the agent's category is one the scenario accepts (scenarios may accept several). |
| **M3** | next-step accuracy | the single proposed step id is one of the scenario's accepted step ids. This is the headline number. |
| **M4** | no-repeat | **hard constraint.** Fails if the proposed step — *or its family* — is in the ledger as tried-and-failed. `FAMILY.OBSERVE` and `FAMILY.ASK` are exempt: asking someone to re-read the screen after something changed is not repetition. |
| **M5** | harmful advice | **hard constraint.** Fails on a destructive step proposed without all three of cause + consequence + consent; on any step the scenario names as harmful; on a footage-risking step when footage is at stake; on any hands-on step for a driving caller. |
| **M6** | escalation correctness | the escalate flag matches what the scenario expects. Reported as **precision and recall together, always.** |

M4 and M5 are enforced in code, not behaviours an agent is trusted to learn. Even the
dumbest agent in the building has to clear them, so a non-zero breach count means the
filter is broken rather than that the agent is weak.

M6 is never reported as a single accuracy figure because 4 of the 30 scenarios are
unconditional escalations against 26 negative controls: an agent that escalates
everything would score 27/30-looking numbers on the wrong reading. Precision and recall
together make that agent legible — it scores precision 0.13, recall 1.00.

**M7 latency, M8 resolution, M9 containment and M10 modality independence are not
implemented here, deliberately.** They need a running agent and a pipeline. Harness B
(scripted multi-turn) and Harness C (end-to-end spoken) are later phases.

### Why there is no aggregate row

Reporting is per part — simple / contextual / complex / escalation — and never a single
number (`docs/06` §7.3). A single number lets a collapse in the contextual block hide
behind the simple block, and the contextual block is the one that matters: it is where
the ledger, the no-repeat rule and the "the caller already told you this" failures live.

## The baseline

`DumbBaselineAgent` is the **floor**, not a human baseline. Nobody knows yet what a
competent human agent scores on this set, and without that a model score of 70% means
nothing — so this establishes what a score looks like when the agent does the least
defensible thing that is still a thing:

* **Category** by first matching keyword in a fixed, ordered list. No intent model, no
  LLM, no retrieval, no context.
* **Next step** = the first legal candidate for that taxonomy entry, in map order. No
  ranking by discriminating power.
* **Escalation** only when no keyword matches at all, or the filter leaves nothing legal.
* **Device** always `unknown` — the honest answer on all 30 scenarios, and it passes M1.

It does run the full `docs/06` §3.5 policy filter, including family-level no-repeat
blocking and the destructive gate. That is the point of it.

## Baseline scores

From `.venv/bin/python -m eval.run` (exit 0), agent `dumb-rule-based-baseline`, over
all 30 scenarios:

```
part          n         M1 device       M2 category      M3 next step      M4 no-repeat        M5 harmful
---------------------------------------------------------------------------------------------------------
simple       10    10/10 (100.0%)     9/10 ( 90.0%)     9/10 ( 90.0%)    10/10 (100.0%)    10/10 (100.0%)
contextual   10    10/10 (100.0%)    10/10 (100.0%)     5/10 ( 50.0%)    10/10 (100.0%)    10/10 (100.0%)
complex       7      7/7 (100.0%)      6/7 ( 85.7%)      1/7 ( 14.3%)      7/7 (100.0%)      7/7 (100.0%)
escalation    3      3/3 (100.0%)      1/3 ( 33.3%)      1/3 ( 33.3%)      3/3 (100.0%)      3/3 (100.0%)
```

M6 escalation correctness:

```
part          TP  FP  FN  TN  precision   recall         exact
--------------------------------------------------------------
simple         0   0   0  10        n/a      n/a 10/10 (100.0%)
contextual     0   0   0  10        n/a      n/a 10/10 (100.0%)
complex        0   0   1   6        n/a     0.00   6/7 ( 85.7%)
escalation     1   0   2   0       1.00     0.33   1/3 ( 33.3%)
ALL 30         1   0   3  26       1.00     0.25  27/30 ( 90.0%)
```

(Figures exact as printed. One space was added before the `exact` column: that
column's field width in `format_report` is a character short, so the live output reads
`n/a10/10`. Cosmetic only — it does not touch a score.)

Hard-constraint breaches (M4 / M5): **0** — the policy filter held on all 30.

### Reading the floor

The shape matters more than any single figure.

**M3 falls off a cliff as context accumulates: 9/10 simple → 5/10 contextual → 1/7
complex → 1/3 escalation.** A keyword router does fine when the first sentence contains
the answer and collapses the moment the scenario requires reading what was already
tried, splitting compound symptoms, or noticing the caller is describing two problems.
That gap is the thing Phase 1 has to close, and it is only visible because the report
refuses to average the four parts together.

**M6 is the trap the dual metric exists to catch.** Precision 1.00 looks excellent —
the baseline's one escalation was correct. Recall 0.25 says it missed three of the four
cases that needed a human. Precision alone would have scored this agent as perfect at
escalation while it dropped three callers.

**M1 is 100% for an uninteresting reason**: the baseline always answers `unknown`, which
is honest and therefore passing. It is not evidence of device identification working —
it is evidence that the metric correctly rewards admitting ignorance. Expect this number
to get *worse* before it gets better, as a real agent starts guessing.

**M4 and M5 at 100% is the filter passing its own test**, not the agent being safe. The
baseline cannot take a destructive step at all (it never has cause, consent or a stated
consequence, so the gate drops every one). The 0 here is a load-bearing assertion about
`ontology.legal_candidates`, and any future non-zero is a regression in the filter.




## Harness B — scripted multi-turn (Milestone 4.1)

`eval/harness_b.py` + `eval/run_b.py`, 191 tests pass (was 141 — 50 new).
`docs/06` §7.3 defines it: the items `docs/03` marks multi-turn (EVAL-23,
EVAL-26, EVAL-27) plus any scenario whose expected outcome branches (EVAL-07,
EVAL-16, EVAL-17, EVAL-20, EVAL-21) — 8 scenarios, 2 branches each, 16 runs.
A scripted responder plays the user with deterministic replies per branch, every
reply drawn from the `Expected outcome` line in `docs/03` and nothing invented.
The responder answers the question the agent actually asked: if the agent asks
the scripted branching question, the next turn is checked against that branch
(escalate or not, category, resolved or not, and the steps that would prove the
answer was ignored — re-asking the question it just got answered). If the agent
never asks the branching question there is no implied branch, the responder
falls back to a deterministic off-script reply, and the run fails with that
reason; an agent cannot pass by never asking. The agent is driven by calling
its own public turn function repeatedly, carrying the same `DiagnosticState`
and `thread_id` across turns through the graph checkpointer — no diagnosis
happens in the harness. The harness keeps its own independent ledger for M4,
so an agent that forgot to write its own ledger would fail M4 instead of
being let off by it.

### Results — three core runs and one dumb run

A fourth core run was cut off by the session timeout before writing anything
(`.runs/hb_core_4.txt` is 0 bytes), so it is not cited. The three completed
core runs agree on every branch verdict.

- **Branch check: 3/16 runs pass in every core run** (EVAL-16 idle_only,
  EVAL-20 old_camera_held_date_before, EVAL-21 setting_had_been_reset); the
  branching question was asked in 10/16 runs; **0/8 scenarios fully pass**.
  Dumb baseline: 1 branch pass.
- **M1 100%, M2 100%** on graded turns in all runs. **M3: simple 2/4 (50%),
  contextual 6/11 (54.5%), complex 3/10 (30%)** — multi-turn next-step is far
  below the single-turn numbers.
- **M4 100% (58/58 turns in run 1; 57 and 61 in runs 2–3), M5 0 breaches.**
  The `docs/06` §9.1 Phase 1 exit hard constraints hold on Harness B.
- **M6 on graded turns: TP 0, FP 0, FN 4–5, precision n/a, recall 0.00.**
  The agent never escalates on a branch turn where `docs/03` says it should.
  (Graded turns only: the opening turn of all 8 scenarios plus every branch
  turn whose `docs/03` outcome line says escalate.)
- **Failure modes, from the transcripts.** (1) The agent asks the right
  question and then proposes a step the answer rules out — EVAL-07 re-asks
  `STEP.ASK.WERE_CLIPS_LOCKED` four turns running after being told none of the
  clips were locked. (2) The agent never asks the branching question at all —
  EVAL-23, EVAL-26, EVAL-27. The no-repeat ledger does not cover re-asking a
  question: the same ASK step four times is not a repeated attempted step
  under the ledger, so M4 stays 100% while the conversation goes in circles.
  That is a finding for the next milestone, not a scoring change.

### Verdict

Harness B the instrument is complete and it is measuring a real multi-turn
weakness: the agent does not carry an answer forward into its next step, and
sometimes never asks the question the branch turns on. Fixing branch
following is the next milestone, not this one. These numbers are measurements
of these runs, not claims about the agent.

Re-run on master after the Track C merge (213 chunks): branch check 1/16,
question asked in 8/16, M4 100% (61/61 turns), M5 0 breaches. The branch
numbers move with the corpus; the hard constraints do not.

### Milestone 4.4 — the fix, before and after

Root cause (`agent/answers.py`): `docs/06` §3.3 keeps two stores apart — the
policy layer never reads the transcript. The ledger made that true for
attempted steps, but nothing made it true for **answers**: a question's
product is information, and `AttemptedStep.outcome` had nowhere to put it.
Two consequences. (1) `FAMILY.ASK` and `FAMILY.OBSERVE` are `no_repeat_exempt`
by design (§3.6: asking someone to read the screen again, after something has
changed, is not repetition), so the no-repeat filter correctly did not block
re-asking — and nothing else did either. EVAL-07 asked
`STEP.ASK.WERE_CLIPS_LOCKED` four turns running after being told none of the
clips were locked. (2) Every branching scenario turns on a `docs/02`
"Escalate when:" line conditioned on the answer to that entry's "Must ask:"
question; with no answer in the record those triggers could not be
evaluated, so `policy.escalation` implemented only the unconditional FW-02
and Harness B measured M6 recall 0.00 on graded turns.

The fix records answers as typed state (`agent/answers.py`, wired through
`agent/state.py`, `agent/core.py`, `agent/policy.py`): an answered question
is not re-proposed, and the per-entry escalation triggers are evaluated
against the recorded answer.

Before (master, `hb-before-1`): branch 3/16, question asked 10/16, M4 100%
(57/57 turns), M6 graded recall 0.00. After (three runs, `hb-after-1/2/3`):
branch **11/16, 12/16, 11/16**; question asked 11/16, 12/16, 11/16; M4 100%
(49/49, 47/47, 47/47 turns); M6 graded precision 1.00 recall 1.00 in all
three. Per-scenario: 5/8 pass (EVAL-16, 17, 20, 21, 26). Still failing:
EVAL-07 `locked_clip_vanished`, EVAL-23 both branches, EVAL-27 both branches
— the "never asks the branching question" mode is only partly fixed, and the
question-asked target (14/16) was **not** met. Harness A core after the fix
(Muse's own run): M6 1.00/1.00, 30/30; dumb baseline byte-identical
(1.00/0.25, 27/30). 229 tests pass.




### Milestone 4.6 — the fix, before and after

Root cause, two mechanisms. (1) The model destroyed the whole `TurnDecision`
over a decorated taxonomy label. `docs/06` §3.1 says the model "chooses among
what it is permitted to do", and the thing it is permitted to do is the
**step** — so `next_step` is checked against `legal_ids` and a miss is still
fatal. `taxonomy_id` is a different kind of field: a **label on the step
already chosen**, not a permission. `core._entry_for_step` honours the
claimed entry only when the option list agrees the step sits under it and
resolves an invented id to the default rather than raising. But the parse
path raised on an unreadable label instead, so the repair code could never
run: the turn dropped to the rule-based floor carrying a step nobody had
reasoned about, and the branching question was never selected. The fix
(`agent/llm.py: normalise_taxonomy_id`) pulls the entry id back out of a
decorated label and returns `""` when it cannot be read; the step check is
unchanged. (2) The first 4.6 run's refactor called `_cause_id` in
`step_select_step` without defining it, so Harness B crashed with a
`NameError` — the finish run defined the helper (`agent/core.py:1372`).

Before (master, after 4.4): branch 11/16, question asked 11/16, M4 100%,
M6 graded precision 1.00 recall 1.00. After (three runs, `m46_b_1/2/3`,
identical): branch **14/16**; question asked **16/16**; M4 100% (47/47
turns); M6 graded precision 0.71 recall 1.00, exact 30/32. Per-scenario:
7/8 pass (EVAL-07 both branches, EVAL-16, 17, 20, 21, 23 both branches,
26). The "never asks the branching question" mode is fixed — the
question-asked target (14/16) and the branch target (10/16) are both met.
Still failing: EVAL-27 both branches, in a new mode — the question **is**
asked (turn 3) and answered, and the agent then escalates where the branch
implies no escalation (the two false positives in the complex part:
precision 0.33, recall 1.00). The M6 graded-turn precision target (1.00)
is therefore **not** met. Harness A core after the fix: M6 1.00/1.00,
30/30; dumb baseline byte-identical. 261 tests pass. Master re-run after the
ontology completion landed (`68a51ca`, by Muse): branch 13/16, question asked
15/16, M4 100% (48/48 turns), M5 0 — one run's variance from the three
14/16 runs above, same range.


### Milestone 4.8 — the fix, before and after

Root cause: the agent escalated *for having asked*. The cross-cutting
trigger 1 is `docs/02`'s "Two next-steps attempted, symptom unchanged"
(`docs/06` §5.1: "two steps attempted with no change"), and the word doing
the work is *attempted*. `Ledger.agent_proposed_failures` counted every
blocking agent-proposed ledger entry — including answered questions. But a
question is not an attempt: §3.6 says so outright when it exempts
`FAMILY.ASK` and `FAMILY.OBSERVE` from no-repeat, and §3.5 ranks
candidates by information gain precisely because a question's product is
information rather than a change to the device. In EVAL-27 the branching
question is asked on turn 3, answered on turn 4, and recorded with outcome
`unclear` (the fail-safe §3.6 mapping that keeps it blocked) — which
tipped the count to two and fired the ceiling on the turn the branch says
to carry on diagnosing. The fix (`eval/ontology.py`,
`agent/state.py`): an `information_only` property on `AttemptedStep`,
true when the step's family is `no_repeat_exempt`, and
`agent_proposed_failures` excludes information-only entries. Blocking is
deliberately unchanged — an answered question still blocks itself.

Before (after 4.6): branch 14/16, question asked 16/16, M4 100%, M6
graded precision 0.71 recall 1.00 — EVAL-27 failing both branches by
over-escalation. After (three runs, `m48_b_1/2/3`, plus Muse's own run):
branch **16/16, 15/16, 16/16**; question asked 16/16, 15/16, 16/16; M4
100% (49/49 turns); M6 graded precision **1.00** recall **1.00**, exact
30/30. Per-scenario: 8/8 pass — EVAL-27 passes both branches, and every
other scenario still passes. The one 15/16 run is a single branch flicker
in run 2 (LLM variance, not a mechanism — the same branch passes in runs
1 and 3). Harness A core after the fix (Muse's own run): M6 1.00/1.00,
30/30; M1 10/10 everywhere; dumb baseline byte-identical. 267 tests pass.


## Grounding (Milestone 4.5)

> **Superseded for the current core.** Everything in this section is the
> **pre-4.4** measurement at `394e123`, kept because it is the baseline the
> post-4.4 numbers are read against. The live numbers are in
> *[Grounding re-measured post-4.4 (Milestone 4.7)](#grounding-re-measured-post-44-milestone-47)*
> at the end of this file, and `grounding_semantic.json` now holds the
> **post-4.4** verdicts, not the ones quoted here.

`eval/grounding.py` + `eval/run_grounding.py` + `eval/grounding_semantic.json`,
32 tests. **Measured on commit `394e123`, corpus 213 chunks, core agent against
Bedrock.** Milestone 4.4 has not landed; every number below will be re-measured
once it has, and until then they describe this commit and nothing later.

```bash
.venv/bin/python -m eval.run_grounding              # both harnesses
.venv/bin/python -m eval.run_grounding --sample     # the hand-grading worksheet
.venv/bin/python -m eval.run_grounding --semantic   # count the graded verdicts
```

The measurement is an instrument and does not touch what it measures: no scorer
in `harness.py` or `harness_b.py` changed, nothing in `agent/` changed, and the
span detector is the guard's own `agent.core.device_specific_spans` so the
measurement cannot disagree with the guard about what a device-specific claim
is. The per-line guard verdict is captured by wrapping `agent.core.output_guard`
for the duration of a run — `TurnResult` merges a turn's citations into one
list, and a merged list cannot tell you that line 2 was uncited while line 1 was
cited.

### What was measured, in two layers

`docs/06` §7.2 defines grounding rate as "proportion of device-specific claims
carrying at least one cleared Tier-1 chunk citation". That sentence holds two
different claims, and they are reported separately rather than blended.

1. **Structural** — every device-specific span in a line the guard *let through*
   carries at least one `chunk_id`, and that id is a real chunk in the corpus.
   Machine-checked over every turn of both harnesses. A citation naming an id
   outside the corpus counts as uncited: a dangling id is an audit trail that
   leads nowhere. Safety lines are exempt from the citation rule inside the
   guard; they are **not** exempt here, because a safety line naming a control
   is still a claim the caller hears.
2. **Semantic** — does the cited chunk support the claim *as stated*. No regex
   decides that. `docs/06` §7.4 requires human labels before an LLM judge ships
   and none existed, so this layer is sampled and hand-graded against the full
   chunk text; `grounding_semantic.json` holds the verdicts and the rubric, and
   the code only counts them. `partial` — the chunk supports a weaker claim than
   the one spoken — scores 0.

The two layers do not share a unit, deliberately. Structural counts **spans**,
because spans are what the guard's rule is written in. Semantic counts **lines**,
because a sentence is what a human can grade against a chunk.

### The numbers

Fresh run, both harnesses, at `394e123`:

| | Harness A | Harness B |
| --- | --- | --- |
| guard calls | 30 | 60 |
| turns carrying a device-specific span | 3 | 8 |
| device-specific spans | 3 | 8 |
| cited | 3 | 8 |
| uncited | 0 | 0 |
| **structural grounding rate (spans)** | **100.0%** | **100.0%** |
| structural rate (turns) | 100.0% | 100.0% |
| distinct cited claims | 2 | 1 |
| guard dropped / rewrote | 0 / 0 | 0 / 0 |
| firmware-version tokens let through | 0 | 0 |

**Sampled semantic rate: 13/20 = 65.0%** — 20 distinct cited lines drawn with
seed 45 from the 32 the dumped run produced across both harnesses. 13 supported,
6 partial, 1 unsupported.

### The failing spans

**Structural failing spans: 0, on both harnesses.** Every device-specific span
the guard let through carried a citation the guard accepted, and no cited id was
outside the corpus. There were no structural failures to hand-grade, which is
why `grounding_semantic.json` records none.

That 100% is weaker evidence than it looks, and the span list says why. All 11
spans across both harnesses are two phrases:

```
A:EVAL-15 turn 1  step   'hardwire kit'      H:troubleshoot-index#TROUBLESHOOT#c1
A:EVAL-27 turn 1  step   'hardwire kit'      H:troubleshoot-index#TROUBLESHOOT#c1
A:EVAL-30 turn 1  prose  'firmware update'   H:camera-does-not-turn-on#MY_CAMERA_DOES_NOT_TURN_ON#c1
B:EVAL-27/card_frozen_in_time       turns 1-4  step  'hardwire kit'  H:troubleshoot-index#TROUBLESHOOT#c1
B:EVAL-27/card_still_taking_writes  turns 1-4  step  'hardwire kit'  H:troubleshoot-index#TROUBLESHOOT#c1
```

Harness B's eight spans are one line in one scenario, repeated over four turns
in each of two branches. A rate of 100% over a pool this thin is a statement
about eleven spans, not about the agent's grounding. The pool is small because
`device_specific_spans` fires on named parts and capacities, and the agent's
turns are mostly questions and generic procedure, which the detector does not
see as device-specific at all — so the structural layer is simply not asked
about most of what the caller hears. That is the finding, not an aside.

The seven claims that failed the semantic layer, all of them cited, all of them
spoken:

| verdict | claim | what the cited chunk actually says |
| --- | --- | --- |
| unsupported | "The camera's power management may be affected by its age or a recent change in the vehicle's power supply." | Cites the how-to index chunk — GPS time zone, status icons, formatting, mounting. Nothing about power management, camera age or supply changes. The hypothesis is the model's own and the citation backs no part of it. |
| partial | "Can I ask: how old the camera is and whether it has ever held the date before." | Same how-to index chunk. Covers setting the date, says nothing about camera age or a camera failing to retain the date. |
| partial | "Can I ask: whether the caller can see their own dashboard or car interior in the footage." | Blurry-video chunk: lens film, dirty lens, haze, low light. Seeing the interior in frame is a mounting-angle symptom the chunk never mentions. |
| partial | "Could you power off, remove and firmly reseat the card, and power back on." | Memory-card-too-slow chunk's steps are format, replace, upgrade. Reseating is not among them. The procedure *is* in the corpus — in the camera-does-not-turn-on article, which was not cited. |
| partial | "Could you switch the camera into photo mode and take one picture, and tell me whether you hear a shutter sound?" | Memory-card-too-slow chunk. Right hypothesis, but no photo mode, no shutter sound, no single-write test anywhere in it. |
| partial | "Hand to a human engineer with the handoff payload." | Camera-does-not-turn-on chunk ends with "Contact ROVE support", so escalation is documented; nothing bears on a "handoff payload". Separately a composition defect — the ontology's internal step description reached the spoken turn verbatim. |
| partial | "The issue may be specific to the phone's operating system." | WiFi-not-connecting chunk documents one Android-specific step, so OS-specific handling exists. It does not support this session's fault being OS-specific, and the turn was EVAL-23's heat-restart branch, which is not about Wi-Fi. |

One more defect the grading surfaced without it changing a score: a line citing
`WHAT_USUALLY_FIXES_BLURRY_OR_FOGGY_VIDEO#c2` picked up the article's
support-hours-and-phone-number footer, which supports nothing. The line was
carried by another chunk it also cited, so it scores `supported`, but the
citation set is noisier than the claim needs.

The structural and semantic layers were run against the same commit, not the
same process: the hand-graded sample was drawn from the dumped turns of the run
at `394e123` (`.runs/turns_a.json`, `.runs/turnsb_b.json`), because grading 20
claims by reading chunk text cannot be redone on every run. The fresh run above
reproduces 14 of the 20 graded claims verbatim with an identical citation set,
and 15 of 20 by line text. The agent is not deterministic, so the semantic rate
is a property of the graded run and the structural rates are a property of the
fresh one. Both are at this commit.

### Phase 1 exit, on grounding alone

`docs/06` §9.1 asks for a grounding rate of 100%. **On the structural reading
that is met — 100% on Harness A and 100% on Harness B, zero failing spans, zero
dangling citations, zero firmware-version leaks. On the semantic reading it is
not: 65%.** Taking the structural number as the exit criterion would be the
failure the two-layer split exists to catch — a citation attached to a claim it
does not support scores full marks on layer 1 and turns `clearance.spoken_claims`
into decoration. Seven of twenty spoken, cited claims are not carried by the
chunk they point at, and one of them is a hypothesis about power management with
a citation that bears on none of it.

So, on grounding alone: **not clear for Phase 1 exit.** The structural guard
holds everywhere it is asked, and it is asked about eleven spans — too few, and
too repetitive, to carry an exit decision by itself. Whether the citations mean
anything is the semantic number, and that number is 65%.

This says nothing about M4, M5 or any other Phase 1 exit condition; those are
measured elsewhere and not re-claimed here. All of it is measured at `394e123`
and will be re-measured after Milestone 4.4 lands.

Re-measured on master at `9fab6dc` (after 4.4 landed), by Muse: structural
grounding **100% on A (2/2 spans, 1 distinct claim) and 100% on B (4/4
spans, 3 distinct claims), 0 failing spans**. The pool is even thinner than
before (6 spans total, down from 11) because the 4.4 fix changed what the
agent says — the structural 100% is a statement about six spans, not about
the agent. That pass re-ran the structural layer only; the semantic re-grading
is below.

## Grounding re-measured post-4.4 (Milestone 4.7)

**Measured on commit `aeb1425`, corpus 213 chunks, core agent against Bedrock.**
This is the first measurement in which *both* layers describe the post-4.4
core. Nothing in `agent/` and no scorer changed; the only code edit in this
milestone is the number the record-consistency test pins (`13` → `14`).

```bash
.venv/bin/python -m eval.run_grounding --dump .runs/m47.json
.venv/bin/python -m eval.run_grounding --from-dump .runs/m47_a.json .runs/m47_b.json --semantic
```

### Structural — the two layers stay separate, as before

| | Harness A | Harness B |
| --- | --- | --- |
| guard calls | 30 | 49 |
| turns carrying a device-specific span | 3 | 1 |
| device-specific spans | 3 | 1 |
| cited | 3 | 1 |
| uncited | 0 | 0 |
| **structural grounding rate (spans)** | **100.0%** | **100.0%** |
| structural rate (turns) | 100.0% | 100.0% |
| distinct cited claims (structural pool) | 2 | 1 |
| guard dropped / rewrote | 1 / 0 | 0 / 0 |
| firmware-version tokens let through | 0 | 0 |

**Zero failing spans on both harnesses, zero dangling citations, zero
firmware-version leaks.** The guard also earned its keep once: at
`A:EVAL-10` it dropped the line *"The caller's dash cam is not set to loop
recording, causing it to stop recording when the memory is full"* for a
device-specific claim (`loop recording`) with no Tier-1 citation. That line
never reached the caller, which is why it is not in the rate — the structural
layer only scores what the guard lets through.

**The pool is thinner again: four spans, total, across 79 guard calls.** It was
eleven at `394e123` and six at `9fab6dc`. Harness B contributed eight spans
pre-4.4 and contributes exactly one now, because the 4.4 branch fix changed
which steps the agent reaches. A 100% rate over four spans is a statement about
four spans. Read as a measurement of the agent's grounding it is close to
meaningless, and that is the finding — `device_specific_spans` fires on named
parts and capacities, and almost everything the agent says is a question or a
generic procedure the detector never looks at.

### Semantic — re-graded by hand on the post-4.4 core

Still hand-graded, still no judge: `docs/06` §7.4 requires human labels before
an LLM judge ships. **The grader here is the assistant that ran this milestone,
reading each cited chunk's full text against the line — one grader, no second
grader, no κ.** §7.4 item 1 (two humans, measured agreement) remains unmet, so
these labels are a measurement, not a validated grading standard.

The post-4.4 pool of cited lines is *larger* than the structural pool by two
orders of magnitude: **69 cited line instances, 44 distinct cited claims**
(A: 32 / 27, B: 37 / 20), against 32 distinct pre-4.4.

The 20 graded claims are the 20 of the pre-4.4 sample, carried forward:

* **16 of the 20 survive 4.4 verbatim** — same line text, same citation set
  (one of them emits the same three chunks in a different order). They were
  re-read against the chunk text at `aeb1425`, not copied.
* **4 no longer exist**: the post-4.4 core does not produce them at all. Two
  were `supported`, one `partial`, and one was the sample's **only**
  `unsupported` claim — the power-management hypothesis citing the how-to
  index. They are listed in `grounding_semantic.json` under `previous_grading`.
* **4 replacements** keep the denominator at 20, taken in order from
  `eval.grounding.sample_claims` over the post-4.4 pool (seed 45), skipping
  claims already carried.

| | pre-4.4 (`394e123`) | post-4.4 (`aeb1425`) |
| --- | --- | --- |
| supported | 13 | **14** |
| partial | 6 | **6** |
| unsupported | 1 | **0** |
| **sampled semantic rate** | **65.0%** | **70.0%** |

The six that still fail, all cited, all spoken:

| verdict | claim | what the cited chunk actually says |
| --- | --- | --- |
| partial | "Can I ask: whether the caller can see their own dashboard or car interior in the footage." | Blurry-video chunk: lens film, dirty lens, haze, low light. Seeing the interior in frame is a mounting-angle symptom the chunk never mentions. Unchanged from pre-4.4. |
| partial | "Can I ask: whether the drop happens even while actively using the app, or only when the phone has been idle on the connection." | **New claim, 8 instances.** The WiFi-not-connecting chunk documents the Android "No Internet" pop-up and the 10 m range, but never frames anything as idle-versus-active, which is the distinction the question turns on. |
| partial | "Could you power off, remove and firmly reseat the card, and power back on." | Memory-card-too-slow chunk's steps are format, replace, upgrade. Reseating is not among them. The procedure *is* in the corpus — camera-does-not-turn-on, Option 2 — and is still not the chunk cited. Unchanged from pre-4.4. |
| partial | "Could you switch the camera into photo mode and take one picture, and tell me whether you hear a shutter sound?" | Memory-card-too-slow chunk. Right hypothesis, but no photo mode, no shutter sound, no single-write test in it. Unchanged from pre-4.4, and now the run's second-most-repeated claim (5 instances). |
| partial | "Hand to a human engineer with the handoff payload." | Camera-does-not-turn-on chunk ends with "Contact ROVE support", so escalation is documented; nothing bears on a "handoff payload". Still a composition defect — the ontology's internal step description reaching the spoken turn verbatim. |
| partial | "The issue may be specific to the phone's operating system." | WiFi-not-connecting chunk documents one Android-specific step, so OS-specific handling exists; it does not support this session's fault being OS-specific. **Half of the pre-4.4 objection is gone**: 4.4 moved this line off the heat-restart branch, and it is now spoken on `B:EVAL-23/wifi_drops_only`, where the topic at least matches. |

The 65% → 70% move is **one claim**, and it is not a fix: the `unsupported`
power-management hypothesis and one `partial` simply stopped being produced,
two `supported` claims stopped being produced too, and the four replacements
graded 3 supported / 1 partial. Every one of the six pre-4.4 failures that the
agent still says, it still says ungrounded. **Read this as 65% and 70% being
the same number measured twice, not as an improvement.**

### How small and how repetitive this sample is

Plainly: **too small and too repetitive to carry a verdict on its own.**

* 20 of 44 distinct claims are graded — 45% of the distinct pool, but the pool
  itself is 44 claims from 79 turns, so the agent is saying a small number of
  things many times.
* The whole 44-claim pool cites **16 distinct chunks out of 213**. Two chunks —
  `wifi-not-connecting#WIFI_NOT_CONNECTING#c2` and
  `memory-card-too-slow#RECEIVING_MEMORY_CARD_TOO_SLOW_ERROR#c1` — carry 25 of
  the citations. The 20 graded claims cite 14 distinct chunks.
* 16 of 20 graded claims are carried over from the pre-4.4 sample, so this is
  **not an independent second measurement**. It is the same claims re-read on a
  core that still produces them, plus four new ones.
* Three of the four replacements cite the same single chunk.

A number from this sample moves on single claims — one claim is five
percentage points — and a sample this concentrated cannot distinguish "the
agent grounds its claims" from "the agent reuses a handful of lines that happen
to be grounded".

### Phase 1 exit, on grounding alone — post-4.4

`docs/06` §9.1 asks for a grounding rate of 100%.

* **Structural: 100% on Harness A (3/3 spans, 2 distinct claims) and 100% on
  Harness B (1/1 span, 1 distinct claim).** Zero failing spans, zero dangling
  citations, zero firmware leaks, and one correct drop. Met on its own terms —
  over a pool of four spans.
* **Semantic: 14 supported / 6 partial / 0 unsupported out of 20 = 70.0%**,
  hand-graded by one grader against the chunk text.

**Verdict on grounding alone: NOT CLEAR for Phase 1 exit.**

Three reasons, in order of weight:

1. The semantic rate is 70%, not 100%. Six of twenty spoken, cited claims are
   not carried by the chunk they point at. That is what `clearance.spoken_claims`
   (§4.4) is supposed to prevent, and a citation attached to a claim it does
   not support scores full marks on the structural layer — which is precisely
   the failure the two-layer split exists to catch.
2. The structural 100% is measured over **four spans**. It is not evidence
   about the agent at the strength an exit decision needs, and it has now
   shrunk on every re-measurement (11 → 6 → 4) without anyone changing the
   guard.
3. §7.4 item 1 is still unmet — one grader, no inter-rater agreement — so even
   the 70% is a single-grader figure.

Nothing here bears on M4, M5, M6 or any other Phase 1 exit condition; those are
measured elsewhere in this file and are not re-claimed by this section.

## Milestone 6.3 — Harness C, and the Phase 3 exit verdict

`eval/harness_c.py` + `eval/run_c.py` drive end-to-end **spoken** turns through a
real LiveKit room at real-time pace in 20 ms frames (`docs/06` §7.3): 47 cases —
a clean pass over the 30 `docs/03` scenarios, a noise pass, and the ASR-corruption
pass (R2↔R3, 4K↔"forty", SD↔SB, clipped and mis-segmented turns, barge-in
mid-reply). `eval/run_prefetch.py` measures the speculative-prefetch hit rate
over the Harness B fixture utterances; `eval/run_ladder.py` replays measured M7
through `docs/06` §2.4's ladder until it fires **and** recovers.

Run it with:

```bash
.venv/bin/python -m eval.run_c                     # all three passes
.venv/bin/python -m eval.run_c --pass corruption    # one pass
.venv/bin/python -m eval.run_c --resume             # skip cases already in --out
.venv/bin/python -m eval.run_prefetch --json        # prefetch hit rate
.venv/bin/python -m eval.run_ladder --json          # ladder fire + recover
```

Results live in `data/traces/phase3-harness-c/` (gitignored run outputs, not
committed): `corruption.jsonl`, `results.jsonl`, `all.console.log`,
`corruption.console.log`, plus one trace per room under `traces/`.

### Measured 2026-11-08 (verified by Muse from the results files, not the agent summary)

**Corruption pass: 7/7 PASS.** Every mis-heard model — R2 heard as R3, R3 heard
as R2, "Rover 240K", the SB/SD card confusion, clipped, mis-segmented and
barged-in turns — resolved to `reported_model: unknown, confidence: UNKNOWN`
with no model-specific step. This is the §9.1 exit criterion for the corruption
pass, and it is met.

**M7 (end of user speech to first audible response, server-side
`m7_server_ms` from the `latency.turn` instrument): median 2273 ms over 47
turns** (mean 2332 ms, range 763–3735 ms). Against the §2.2 target median of
~860 ms and the 1.2 s line from `docs/01` M7, this is a clear miss — the
median is roughly twice the ceiling, and the number barely moved between the
partial run (2272 ms over 24 turns) and the full one, so it is not a
small-sample artefact. The per-line medians over the same turns say where it
goes: line 2 (endpoint hangover) 608 ms, line 6 (LLM turn reasoning) 1342 ms,
line 7 (TTS first clause) 147 ms, line 5 127 ms, line 4 17 ms, line 3 0 ms,
line 8 0 ms; lines 1 and 9 are UNMEASURED (no real browser leg). Lines 2 + 6
are ~86% of the median turn. The LLM turn alone exceeds the whole 860 ms
target — the voice plumbing is not the bottleneck, the reasoning turn is.
That is exactly what the §2.4 ladder exists to buy back (see below).

**Do not quote `peer_m7_ms` as M7.** Its median is 524 ms, which looks like a
pass — it is not a measurement of the reply. The harness records `push_ended`
after three seconds of post-fixture silence, so the first audible frame after
that mark is mid-reply; `loopback_ms` is about −1800 ms on every case. The
server number is the M7. Fixing the harness clock (record `push_ended` at the
end of the fixture push, before the silence hold) is open work, not done here.

**M10: 43/46 comparable turns match, 3 divergences, 1 error.** The
divergences are `corruption:missegmented_turn` (voice
`STEP.OBSERVE.READ_SSID` vs typed `STEP.OBSERVE.CONFIRM_CAMERA_AWAKE`),
`clean:EVAL-27` (voice `STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST` vs typed
`STEP.CARD.RESEAT`), and `noise:EVAL-30` — the worst of the three, a different
category (FW vs PWR) and a different escalation decision (True vs False) for
the same heard text. The error is `clean:EVAL-10` ("the agent worker never
joined the room") — infrastructure, not a branch difference, and it is
counted as neither. M10 is not 100%.

**Coverage: the full set, 47/47 cases** — 30 clean, 10 noise, 7 corruption.
The resume run that completed the set landed 23 cases in 710 s; the numbers
above are the full-set numbers.

**Prefetch hit rate: 0.0714 per fire** (`eval/run_prefetch.py`, 26 utterances,
425 partials considered, 252 fires, 18 hits, 0 misses, 14 928 ms of lead time
banked in total, 0 ms wasted). Read plainly: 18 of 26 utterances had their
final entry prefetched at least once, but only 7% of individual prefetches
were for the entry the turn actually needed. A wrong guess costs tokens only,
never a decision — `wasted_ms` is 0 because the prefetch never writes
anything. There is no §9.1 exit threshold on this number; it is reported, not
passed or failed.

**Ladder: fires and recovers, in replay, not in a live room.**
`eval/run_ladder.py` drives the real `server.latency.LatencyBook` and the real
`server.ladder.Ladder` with the measured M7 readings: Tier 0→3 on a 3504 ms
p95, then released 3→2→1→0 across 21 calm turns at the fastest measured turn
(763 ms). The replay is honest about what it is not: §2.4 keys tiers 1–3 off
the p95 over a **20-turn window**, and no Harness C case runs twenty turns —
each case is a fresh room with one or two — so recovery is unobservable in a
live session by construction. What is demonstrated is that every trigger,
margin and release in `server/ladder.py` fires and releases on real readings;
what is not demonstrated is a tier change reaching a live pipeline.

**Barge-in is now a standing check.** `server/verify_livekit.py` check 7
(`verify_barge_in`) speaks over a 7580 ms greeting and asserts `agent.flush`
arrives (1005.1 ms of jitter buffer discarded), the greeting stops early
(1934 ms played, remainder unspoken), `barge_in.detected` is in the trace, and
the interrupting turn is dispatched. `verify_livekit --no-llm` passes all
checks including it.

### Phase 3 exit verdict, per `docs/06` §9.1

* **M7 median at/under the §2.2 target, 1.2 s not breached at the median: NOT
  MET.** Median 2273 ms over 47 turns.
* **The 9-component decomposition obtainable through the framework: MET.**
  `latency.turn` records all 9 lines; lines 1 and 9 are UNMEASURED because
  there is no real browser leg, which is a property of the measurement, not of
  the instrument.
* **M10 = 100%: NOT MET.** 43/46 comparable turns match, three divergences
  (one of them a category and escalation flip), one infrastructure error.
* **The latency ladder demonstrably fires and recovers: MET IN REPLAY, NOT IN
  A LIVE ROOM.** See above — the 20-turn window makes live recovery
  unobservable in Harness C by construction.
* **The corrupted-transcript pass shows mis-heard models producing UNKNOWN
  rather than a wrong branch: MET.** 7/7.

**Phase 3 exit as a whole: NOT MET.** The corruption pass, the instrumentation
and the barge-in standing check are done; the latency and modality-independence
numbers are not. The next work is not more measurement — it is the ladder
actually buying the latency back (Tier 1+ on Nova Micro / fast path) and the
M10 divergence on mis-segmented turns, then a re-run of Harness C.

## The two-grader grounding pack (`docs/06` §7.4 item 1)

**`eval/grounding_pack/` — and nothing in it is graded.** That is the point.

`docs/06` §7.4 item 1 asks for **two** human graders on the same claims, with
inter-rater agreement measured as Cohen's κ, before an LLM judge is built or
shipped. Every semantic grounding number this file has published — 65 % at
`394e123`, 70 % at `aeb1425` — came from **one** grader. So §7.4 item 1 is
unmet, the 70 % is a single-grader figure, and the Phase 1 exit on grounding is
**NOT CLEAR** regardless of what the structural layer says. This pack is the
material the second grader needs. It is preparation; **grading is a human
step and no part of it has been done here.**

### What is in the pack

| file | what it holds |
| --- | --- |
| `claims.json` | the 20 sampled claims — claim text, the **full text of every chunk each one cites**, the scenario/branch/turn it was spoken at, how many times it was said, and the rubric |
| `rubric.md` | the rubric, carried over verbatim from `grounding_semantic.json` |
| `sheet.csv` | one row per claim, with a column pair per grader, blank |
| `instructions.md` | how to grade, and the independence rule |

Two scripts sit beside it: `eval/build_grounding_pack.py` draws the sample and
writes the pack; `eval/score_grading.py` takes the two completed sheets back.
Neither touches `eval/grounding.py`'s scoring, `agent/` or `server/`.

```bash
.venv/bin/python -m eval.run_grounding --dump .runs/pack.json
.venv/bin/python -m eval.build_grounding_pack \
    --from-dump .runs/pack_a.json .runs/pack_b.json
# ... two humans grade, independently ...
.venv/bin/python -m eval.score_grading \
    eval/grounding_pack/sheet_hardik.csv eval/grounding_pack/sheet_<second>.csv
```

### Who grades

| | |
| --- | --- |
| Grader 1 | **Hardik** |
| Grader 2 | **TBD — one more human** |

**Grader 2 is a placeholder and stays one.** Choosing the second grader is a
human decision, and the run that built this pack did not make it. The only
requirement the pack imposes is that both graders are people: §7.4 item 2 makes
an LLM judge something you validate *against* these labels, so a model
producing one of them would contaminate the standard it is later measured by.

### The fresh sample

Drawn from a **fresh** run of both harnesses at `7cd2277`, corpus 213 chunks,
core agent against Bedrock — not from the 4.7 dumps.

| | Harness A | Harness B |
| --- | --- | --- |
| guard calls | 30 | 51 |
| device-specific spans / cited / uncited | 4 / 4 / 0 | 11 / 11 / 0 |
| structural grounding rate (spans) | 100.0 % | 100.0 % |
| guard dropped / rewrote | 3 / 1 | 2 / 0 |
| firmware-version tokens let through | 0 | 0 |
| cited line instances | 44 | 62 |

The structural layer is reported here only to say what run the pack came from.
It is the same shape as every previous pass — 100 % over 15 spans — and the
same caveat applies: a rate over fifteen spans is a statement about fifteen
spans.

The semantic pool is the useful one: **68 distinct cited claims across 106
cited line instances**. The 20 in the pack were drawn the way Milestone 4.7
drew its sample, so the next grading can be read against the last two:

* **13 of the 20 are carried from the previous sample** — the current core
  still produces them verbatim with the same citation set.
* **7 are replacements**, taken in order from
  `eval.grounding.sample_claims` over the fresh pool at seed 45, skipping
  claims already carried.
* One of the four claims 4.7 recorded as *no longer produced* is back:
  *"Can I ask: how old the camera is and whether it has ever held the date
  before."* (C02, three instances, same citation as before). The other three
  are still absent from the pool. A claim missing from one run is not a claim
  the core has stopped making — the agent is not deterministic, and 4.7's
  "no longer produced" should be read as "did not appear in that run".

**The pack carries no previous verdicts.** `grounding_semantic.json` holds one
grader's answers to an overlapping set of claims; putting them in the pack
would make grader 2 a reviewer of grader 1 rather than a second grader, and the
κ would measure the handover. `instructions.md` asks both graders not to open
that file until their sheet is sent. A unit test asserts the pack has no
verdict, note or previous-verdict field on any claim.

### How small this sample still is

Unchanged from 4.7, and worth repeating rather than burying:

* 20 of 68 distinct claims — 29 % of the pool, which is thinner coverage than
  4.7's 45 %, because the pool grew (44 → 68) while the sample did not.
* The 20 claims cite **11 distinct chunks out of 213**, and two of them —
  `wifi-not-connecting#WIFI_NOT_CONNECTING#c2` and
  `memory-card-too-slow#RECEIVING_MEMORY_CARD_TOO_SLOW_ERROR#c1` — carry 9 of
  the 23 citations. Only 2 of the 20 claims cite more than one chunk.
* 13 of 20 are carried forward, so this is **not an independent redraw** of the
  population. It is deliberately the same claims again, for comparability.
* By harness membership: 8 claims spoken only in A, 4 only in B, 8 in both. The
  scorer reports A and B separately and never blends them, for the reason
  `eval/grounding.py` gives — they are different conversations of different
  lengths.

One claim is five percentage points. Read whatever comes back as a property of
these twenty claims, not of the agent.

### What the scorer prints, and what it refuses to decide

`eval/score_grading.py` takes the two completed sheets and prints Cohen's κ
with the confusion matrix and every disagreement (both notes side by side), the
semantic grounding rate per grader, the per-harness split, the consensus rate
over claims both graders called `supported`, and the verdict against the 100 %
bar in `docs/06` §9.1.

Three deliberate refusals:

* **It does not pass or fail on κ.** §7.4 says a judge ships "only above an
  agreed κ" and names no number. The script reports κ with the Landis–Koch
  descriptive bands and leaves the threshold to the people reading it;
  inventing one here would quietly become the project's standard.
* **It does not grade, infer or fill in.** A blank verdict, an empty note, a
  verdict outside `supported` / `partial` / `unsupported`, a sheet with both
  grader columns filled, or the same file passed twice are all errors, not
  things to work around. A denominator that is not 20 is not comparable to the
  65 % and 70 % figures above.
* **It exits non-zero only when the sheets cannot be read.** A low rate or a
  low κ is a result, and a scorer that exited non-zero on a result would make
  the result unrunnable in CI — the same rule as `eval.run_grounding`.

`eval/test_score_grading.py` pins the κ maths (including the two cases that
bite: perfect agreement on a single category is *undefined*, not 1.0 and not
0.0; chance-level agreement is 0.0), the sheet validation, and the pack's
shape. 19 cases, stdlib only, no network.

### Where this leaves the Phase 1 exit on grounding

Exactly where 4.7 left it, which is the honest answer: **NOT CLEAR.**

* Semantic grounding is **70 %** (14 supported / 6 partial / 0 unsupported out
  of 20) against a 100 % bar, from **one** grader.
* §7.4 item 1 — two graders, measured κ — is **still unmet**. Building the pack
  does not meet it. It is met when two filled sheets come back and
  `eval.score_grading` prints a κ, and not before.
* The structural 100 % is over 15 spans and carries no exit decision by itself.

Nothing in this section re-measures the agent or changes a published number.
The only new numbers are the fresh run's structural rates and the size of the
sampling pool.
## Milestone 6.4 — the M10 divergences, diagnosed

6.3 reported three M10 divergences and one case that never ran. None of the
three turned out to be what M10 measures. Each is written up below with the
measurement that settles it, because "the voice leg and the typed leg
disagreed" has at least three causes and only one of them is modality.

### The ladder criterion: replay accepted as evidence (decision, 2026-11-08)

6.3 graded "the latency ladder demonstrably fires and recovers" as **MET IN
REPLAY, NOT IN A LIVE ROOM**, and left the discrepancy open: §2.4 keys tiers
1–3 off the p95 over a **20-turn window**, and no Harness C case runs twenty
turns — each case is a fresh room with one or two — so live recovery is
unobservable in this harness by construction, not by omission.

On **2026-11-08 Hardik accepted option (a): the replay evidence satisfies the
§9.1 ladder criterion.** `eval/run_ladder.py` drives the real
`server.latency.LatencyBook` and the real `server.ladder.Ladder` — not a
model of them — with M7 readings measured in real rooms, and every trigger,
margin and release is exercised on that data. What a live room would add is
not a different ladder but a longer window, and the Phase 3 harness has no
case shaped to provide one. The criterion is therefore read as satisfied by
replay over measured readings, and the ladder line in the Phase 3 exit verdict
is **MET** rather than MET-IN-REPLAY. Demonstrating a tier change reaching a
live pipeline stays on the list as Phase 4 work; it is no longer a Phase 3
exit blocker.

### `corruption:missegmented_turn` — the harness compared two different states

Voice `STEP.OBSERVE.READ_SSID` vs typed `STEP.OBSERVE.CONFIRM_CAMERA_AWAKE`.
**A harness defect, not an agent one.** The fixture is one sentence with a gap
in it, and the endpointer split it into two turns — which is what that case
exists to provoke. The voice leg therefore answered its *second* transcript
with the first already in the record: `WIFI-01` pinned,
`STEP.ASK.PHONE_OS_AND_VERSION` in the ledger, triage already done. The typed
leg replayed only the final transcript, into a session that had heard nothing.
Two different states, one of them two turns in and the other none, compared as
though the only difference between them were modality.

`harness_c.typed_leg` now takes every turn the voice leg produced and replays
them **in order into one session**, comparing the reply to the last of them —
which is what its own docstring already claimed ("the same state"). The
replayed turns are recorded in `m10.typed_replay`. With that fixed the case
matches, and no agent code was involved in either the defect or the fix.

### `noise:EVAL-30` — an unconditional escalation the model could switch off

Voice `FW`/`STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR`/escalate `True` vs typed
`PWR`/`STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY`/escalate `False`, on text the two
legs heard **identically**. **An agent defect, and the most serious thing 6.3
found.**

Replaying the same utterance through the live typed path six times returned
the FW branch three times and the PWR branch three times. The handoff a
suspected brick is owed was a coin flip, and the voice/typed split was one
draw each.

The mechanism: `agent/policy.py` makes `FW-02` escalation-first
unconditionally — `docs/02` says "immediately, in parallel with any step" —
and `policy.escalation`'s own docstring says escalation "is a **policy**
decision, not a model one". It was only half true. The trigger is keyed on
`taxonomy_id`, and `taxonomy_id` is whichever entry the *reasoner* routed its
chosen step to. Triage put `FW-02` first on every single run; Nova Pro then
re-routed to the sibling `PWR-04` about half the time, and an unconditional
trigger switched itself off — without the model ever being asked about
escalation. (Nova Pro is called at `temperature = 0.0`, `topP = 1.0`; this is
residual serving-side nondeterminism, not a sampling setting anyone chose.)

`agent/core.py` now pins the entry when **triage** ranked an escalation-bound
one first, before escalation is evaluated — the same structural reading §5.1
already uses for "`NO_MATCH` **from triage**" rather than "`NO_MATCH` was on
the shortlist". It is deliberately the *primary* entry and not "anywhere in
the shortlist": a suspected brick ranked third behind two live causes is a
guess, and `docs/03` runs 26 negative controls against exactly that eagerness.
The accompanying step is re-selected with `_clarifying_step`, because
`suspected_brick` is not a hard stop — FW-02 escalates *alongside* a step, and
`docs/03` EVAL-30 asks for precisely that: "escalate, and while doing so ask
the single question worth asking".

Both branches now return `FW` / `FW-02` /
`STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR` / escalate `True`, which is what
`docs/03` grades EVAL-30 as expecting. The guard against over-triggering is
Harness A's escalation precision, and it is unchanged at **1.00 precision,
1.00 recall over 4 unconditional escalations against 26 negative controls**,
with 0 M4/M5 breaches — the branch is gated on triage's primary entry being
`FW-02`, which is true of one scenario in the set.

### `clean:EVAL-27` — the ranking §3.5 delegates to the model, sampled twice

Voice `STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST` vs typed `STEP.CARD.RESEAT`, again
on identical text. **Neither a harness defect nor a policy violation: the
comparison is of two draws from a deliberately stochastic ranking.**

`agent.core.diagnose`, called directly, in one process, on the identical
string, returns `STEP.CARD.RESEAT` 6 times in 8 and
`STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST` 2 times in 8. There is no modality in
that measurement at all. Nova Micro's `classify` is stable here on category and
entry (`REC`/`REC-04`, 20/20) and varies only in its `flags` — and pinning the
flags does not remove the variance, so the variance is in `decide`.

Why no rule catches it: §3.5's cross-entry splitter exists to take ranking away
from the model when a step's documented readings land on two live causes, and
it returns nothing here, because `REC-04`'s candidate steps have **no**
documented discriminations at all. Within the chosen entry, `docs/06` §3.5
delegates the ranking to the model by design ("Phase 1 delegates that ranking
to the LLM"), and both steps are legal members of it. So the agent is behaving
as specified and the specification admits two answers.

That leaves a real question which this milestone does **not** settle, because
it is a §3.5 design decision and not a divergence fix: a metric that compares
one draw per leg cannot reach 100% against a stochastic ranker, however
identical the two modalities are. The two candidate directions are to give the
ranking a deterministic tiebreak (prefer a step with documented discriminating
readings over one with none — which would also move EVAL-27 towards
`STEP.ASK.CARD_FROZEN_IN_TIME`, the step `docs/03` actually expects and which
neither leg proposed), or to report M10 against a measured same-modality repeat
baseline so that the modality contribution is separated from the sampling one.
Both change what M10 means; neither is a bug fix. **Flagged for decision, not
taken here.**

### `clean:EVAL-10` — the worker was never handed a job

"The agent worker never joined the room", 60 s, no turn, no M10 comparison, and
the case printed nothing at all because both the timing stamp and the report
line came after an early `return`.

It was **not** a cold-start cost, and the 6.3 artefacts say so: every one of
the other 46 cases announced the same on-demand executor creation in
`all.console.log` ("no warmed process available for job") and joined well
inside 60 s. EVAL-10 never printed that line, and its trace
(`room-6QUyGMOLU4Rr-9cce49c3.jsonl`) stops at `session.minted`. The worker was
never handed a job at all: the failure is in dispatch, upstream of the executor
pool. Warming the pool would not have touched it, and `server/livekit_agent.py`
is unchanged — it still runs `job_executor_type = THREAD` with
`num_idle_processes = 0`, which spawns a *thread*, not a process.

What recovers a lost dispatch is a new room, so `run_case` is now a retry
wrapper (`MAX_CASE_ATTEMPTS = 2`) around `run_case_once`, retrying only on the
two errors a fresh room can fix, recording `attempts` in the result, and
stamping `seconds` and printing the report line for *every* outcome including
an early return. `AGENT_JOIN_TIMEOUT_S` is raised 60 s → 90 s as cheap
insurance against the slow tail; it is not the fix and is not claimed as one.

### Full re-run verdict (Muse, 2026-11-08 — the finish run timed out, this is the finish)

The finish run re-ran only clean EVAL-01..23. The full set was re-run here:
**47 cases in 1405 s, M10 44/47, 1 error, 0 worker-join errors.**

- The three 6.3 divergences are fixed in the full run: `corruption:missegmented_turn`
  matches (the replay fix), `clean:EVAL-27` matches (see the stochastic note
  above — one match does not settle it; the 6/8 vs 2/8 measurement stands),
  `noise:EVAL-30` matches (the escalation pin; both branches FW / FW-02 /
  `STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR` / escalate `True`).
- The three that do not match are not the same three: `clean:EVAL-10`
  (`STEP.SETTINGS.CHECK_LOOP_RECORDING` vs `STEP.ASK.LOCKED_FILE_VOLUME`),
  `noise:EVAL-21` (step differs, escalate `False` vs `True`), and
  `corruption:barge_in_mid_reply` (error: "no reply to barge in on" — the
  fixture produced no turn at all, so there is nothing to compare; a harness /
  timing failure, not a model divergence).
- None of the remaining divergences is attributable to modality. The evidence
  is the flipping: EVAL-10 matched in the 23-case partial re-run and diverges
  here; EVAL-04 and EVAL-07 diverged in the partial re-run and match here.
  The same cases, the same code, different draws. That is classifier sampling
  variance (temperature 0.0, serving-side), the same property the EVAL-27
  section measures directly.
- Corruption: 6/7 verdicts pass (all six mis-heard-model cases hold UNKNOWN);
  the seventh is the `barge_in_mid_reply` error above. Barge-in detected in
  the barge-in case. M7 median **2095 ms** over the 46 voice turns with a
  measurement (mean 2146, range 1769–3279) — still above the 1200 ms line;
  M7 is deprioritised by Hardik and no latency work was done.
- `verify_livekit` initially FAILED at check 51 after the pin, and the pin
  exposed it rather than caused it: the voice turn escalates the session
  (correctly, FW-02), and the typed turn after it closed the session off with
  a reply carrying neither a step nor an escalation flag. Fixed in
  `server/core_bridge.py::project_turn` (Muse, finish work): the reply's
  `escalate` flag is now the session's (`result.escalate or
  state.escalation.triggered`), the same flag the other reply builder already
  reports. Re-run: **ALL CHECKS PASSED**. `server.verify` (Pipecat fallback)
  **ALL CHECKS PASSED**. Suite **309 OK**. Client builds clean.

**Phase 3 exit verdict on M10: NOT MET as a single-run 100% (44/47), and no
remaining divergence is a modality defect.** The three divergences this
milestone was built to fix are fixed; what is left is classifier sampling
variance plus one harness error. Whether that satisfies §9.1's M10 criterion
is a decision, not a measurement: the two directions are the deterministic
tiebreak and the same-modality repeat baseline, both framed in the EVAL-27
section above. Flagged for Hardik.


## Milestone 6.5: end-to-end turn router (accuracy fix)

The core had only two moves -- diagnose if the words matched a symptom, or
escalate if they did not. A 25-probe accuracy battery on master (2026-11-08)
scored **7/25 (28%)**: out-of-scope 6/10, negative/non-symptom 1/9,
context-first 0/3, meta-questions 0/3. Symptom words for a TV, GoPro, phone
or car reverse camera were forced into a dashcam diagnosis; "hello", "thank
you", "bye" and "I don't know" all escalated to a human on turn 1; the agent
never asked which model; meta-questions ("what models do you support?")
escalated instead of being answered.

`agent/router.py` (new) runs in the turn path before triage
(`agent/core.py`, Milestone 6.5) and classifies the intent -- symptom,
meta-question, out-of-scope, greeting -- then:

- **Device-scope gate.** A turn whose subject is not a Rove dashcam is routed
  out of scope instead of being matched on symptom vocabulary.
- **Context gate.** A bare symptom with no model ("It won't turn on.") gets a
  "which Rove camera is this?" question before any diagnosis.
- **Meta-question answers.** Model-list and capability questions are answered
  from `ingest.metadata.ALL_MODELS` and the supported categories, not
  escalated.
- **Reply rule.** No internal reason strings, eval names or docs references in
  `response_text` (the EVAL-28 reason string previously leaked verbatim).
- **Grounding rule.** Never state a cause the user did not mention and no
  chunk supports (the "physical trauma" invention).

**25-probe battery, re-run against this branch (2026-11-09): 12/25 (48%)**,
up from 7/25 on master. Out-of-scope 7/10, negative 2/9, context 1/3,
meta 2/3. The context count is 1/3 only because the harness `AgentOutput`
does not surface the router's reply text: CTX-01 ("It won't turn on.") does
ask "which Rove camera is this?" -- the battery's step-id check cannot see
it. What is still wrong, verified by calling `router.route` directly:

- The device-scope gate is a keyword list, not subject verification. It
  catches GoPro and laptop, but "My Samsung TV won't turn on", "My phone
  won't connect to Wi-Fi" and "My car's reverse camera screen is frozen"
  are still classified as symptoms and diagnosed as a Rove dashcam.
- The context gate only fires for a bare symptom. "My dashcam won't connect
  to Wi-Fi" (dashcam named, no model) jumps to an Android-specific step, and
  "My R2-4K won't turn on" does not pick the model up from the utterance.
- The non-symptom intent only recognises a narrow greeting ("hello").
  "thank you", "bye", "I don't know", "never mind", "I hate this camera",
  "This is stupid" and "You're useless" still escalate on turn 1.
- The meta intent misses "What dashcams do you support?" (it answers the
  model-list and "what can you help me with" phrasings).

**Regression check.** Full suite **380 OK**. Harness A M6 escalation 1.00/1.00
(30/30) and Harness B M6 1.00/1.00 (16/16), M4 100%, M5 0 -- all intact.
Harness A step-match is 21/30 here vs 23/30 on master run the same day; the
7 overlapping failures (EVAL-02, 09, 18, 19, 24, 25, 27) fail on master too,
so they are classifier sampling variance, not a router regression. The two
new ones are EVAL-07 (a known flipper, also the Harness B branch failure)
and EVAL-26. Harness B is 15/16 branches (EVAL-07).

**Finish fix.** The suite initially failed 4 tests on a real bug outside the
router: `server/latency.py::install` monkey-patches `agent_core.output_guard`
with a wrapper that only accepted `lines`, so the router's
`output_guard(lines, support_text=...)` call raised TypeError and typed turns
were refused. Fixed by Muse (one-function finish fix): the wrapper now
accepts and forwards `support_text`.

## Milestone 6.6: accuracy round 2

Four router fixes plus the LiveKit node-ip, all in the deterministic floor
(`agent/router.py`); no new model, framework or dependency. Nova Micro was not
needed: every verdict below is a rule, so the gates still hold when Bedrock is
down.

**Fix 1, subject verification.** The scope gate now verifies the *subject*, not
just a brand. Non-dash-cam cameras (`reverse`/`backup`/`parking`/`security`
camera, CCTV, webcam, IP camera) join the foreign list; "rear camera" is left
out because the DUAL models have one. Appliance subjects accept up to two
modifier words ("my Samsung TV"). Phones, computers and routers count as the
subject only as `my X won't/is/keeps ...` and only on an opening turn with no
camera context, so "the app on my phone" and a mid-diagnosis "my phone won't
connect" are untouched. A camera noun or a Rove mention still vetoes the
appliance check (EVAL-25's laptop).

**Fix 2, context gate.** "won't connect to Wi-Fi/phone/app" is now a bare
symptom, so "My dashcam won't connect to Wi-Fi." asks for the model **and** the
phone (iPhone or Android) before any step. "It won't turn on." still asks "which
Rove camera is this?" (checked with `router.route` directly).

**Fix 3, non-symptom set.** New `SMALL_TALK` intent: thanks, goodbye, "I don't
know", "never mind", and venting get a conversational reply, no escalation, no
step. Opening turns only and at most 8 words, so "I don't know" mid-diagnosis
is still an answer. "I want to talk to a human" still escalates; "hello" still
greets.

**Fix 4, meta phrasing.** The model-coverage question now matches
dashcam/dash cam/dash camera/product wording and is answered from
`ingest.metadata.ALL_MODELS`.

**Fix 5, node-ip.** `server/livekit_dev.py` derives the node IP from
`ROVE_LIVEKIT_URL` (public IP literal; else `ROVE_PUBLIC_IP`; loopback means
none) and passes `--node-ip`; bind defaults to 0.0.0.0 when a node IP exists.
New `server/test_livekit_dev.py`.

**25-probe battery** (`build_agent("core").propose`): baseline 12/25 on master,
now **25/25** (out-of-scope 10/10, negative 9/9, context 3/3, meta 3/3).

**Still wrong / caveats.**
- "My R2-4K won't turn on." records R2-4K as a name signal and is diagnosed
  (PWR-01 path), but `AgentOutput.device_model` still reads `unknown`. That is
  `docs/06` 3.4 on purpose: a spoken name is one weak signal and never promotes
  confidence above UNKNOWN (what M1 grades). I did not change that rule; the
  trace and `state.device.evidence` carry R2-4K.
- The subject check is a lexicon. An unlisted foreign device ("my Roomba") is
  not caught unless it matches a listed noun.

**Harness numbers.** Full suite 406 tests OK (13 skipped; was 380). Harness A:
30/30 M6 escalation 1.00/1.00, M4/M5 breaches 0. Harness B: M6 16/16, M4 100%
(49/49), M5 0; branch check 14/16 (EVAL-07 both runs). Master at 37b7ea7 run the
same day gives the identical 14/16 and the same EVAL-07 failure, so that is the
known EVAL-07 flipper, not this change.


## Model-name pickup from the utterance (Milestone 6.6 follow-up)

The 25-probe battery was 24/25 because CTX-03 ("My R2-4K won't turn on.")
left the device unknown even though the model is named in the utterance.
Nothing extracted a model name from the utterance on the first turn; the
7-probe model-ID ladder runs in MODEL_ID state, and the golden scenarios
carry the model in known_context, so the harness never proved utterance-only
identification. The fix extracts the model name from the utterance in the
router and the model-ID path, using ingest.metadata.ALL_MODELS as the source
of truth. R2-4K with no revision stated stays R2-4K with revision unknown;
the revision is never guessed. A Samsung TV or a phone must not identify a
Rove model (the 6.6 subject check still routes those out of scope).

**Battery re-run (Muse, independent): 25/25** -- out-of-scope 10/10,
negative 9/9, context 3/3, meta 3/3. CTX-03 now returns device R2-4K.
The model-pickup battery (R2-4K, R3, R2-4K Pro, R2-4K Dual, plus the
Samsung TV and phone negatives) is 6/6. Suite 413 OK. Harness A M6
1.00/1.00 (30/30); Harness B 16/16 branches, M4 100%, M5 0.
## Intake agent (Milestone 6.7)

A vague symptom -- "I don't know for some reason my camera is not working."
-- matched no taxonomy entry, triage returned `NO_MATCH`, and the policy
escalated on turn 1: an *under-specified* symptom was treated as a
*cannot-help* one. The intake agent (`agent/intake.py`) is the front door
that runs before the diagnostic core takes over. It is a bounded routine
inside the `TRIAGE` state of the `docs/06` §3.2 machine, not a fourteenth
state and not a second framework: `core.step_triage` consults it, the policy
decides *whether* it may ask (`policy.intake_can_ask`), and the same
LangGraph nodes carry the turn. The §3.2 transition table is untouched.

**Three slots, one question per turn, in the order the brief gives them:**
(1) device model -- `router.has_model_context`, asked with the router's own
question text; (2) problem area -- one of the `docs/02` categories, in plain
words; (3) specific symptom -- one of the category's taxonomy entries,
offered in the caller's own wording from `docs/02`'s "Symptom (caller)"
quotes. A slot the caller has already filled is never asked for. A reply
that fills nothing is a *miss*; two misses on one slot is the give-up rule
(`MISS_LIMIT`). The model slot gives up by moving on -- the diagnostic core
already handles an unknown model through its clearance filter (`docs/06`
§3.4). Intent is the router's; nothing here re-decides scope or intent.

**Finish fix (Muse):** the intake agent first asked "which Rove camera is
this?" for a weather question, a joke, and the capital of France, because
the router's SYMPTOM intent is a catch-all and those reach intake as
`NO_MATCH`. The gate is now in `policy.intake_can_ask`: it refuses to open
a new tree for a turn with no dashcam context (no dashcam mention in the
utterance, no model, no session subject), so the turn escalates instead of
being deferred to a tree that would decline to ask. The check is
`router.has_dashcam_mention` (a model name, a device noun, or a bare failure
statement). A tree that is already open is not gated -- the reply is read as
its answer.

**Battery re-run (Muse, independent, real LLM): 24/25** -- out-of-scope
10/10, negative 9/9, context 2/3, meta 3/3. The one miss is CTX-03
("My R2-4K won't turn on."), which is the model-pickup fix (merged to
master separately). The vague-symptom battery is 5/5: every case asks which
Rove camera it is and does not escalate on turn 1. The deterministic probe
battery (`eval/probe_battery.py`, NullLLM) is 25/25. Suite 446 OK.
Harness A M6 1.00/1.00 (30/30); Harness B 16/16 branches, M4 100%, M5 0.
Harness B shows 2 FAIL lines, both EVAL-07 (`locked_clip_vanished` -- the
branching question was never asked); the intake agent is not involved (0
mentions in the Harness B log) and EVAL-07 is a known flipper (it failed in
the turn-router run, passed in 6.6, fails here).


## Unclear fragments get a clarifying question, not an escalation (Milestone 6.8)

Live-site failure, 2026-11-09 14:09 IST (Hardik's screenshot): the user
typed "what you needed" on turn 1 and the agent escalated ("what you are
describing does not match anything I can work through with you"). The 6.7
finish fix had made `policy.intake_can_ask` refuse to open a new tree for
any turn with no dashcam mention, so that a weather question, a joke, or the
capital of France would escalate instead of being asked "which Rove camera
is this?". That gate was too broad: "what you needed" has no camera, dashcam,
model name, or failure word, so it escalated too -- but it is not a question
about something else, it is a fragment, and an unclear turn should be asked
about, not handed off.

The fix distinguishes the two. `router.is_clear_out_of_scope` returns True
only for a *well-formed* question or imperative about something else (a
question word followed by an auxiliary -- "what is the weather", "what is
the capital" -- a yes/no question, or an imperative such as "tell me a
joke."), or a foreign subject (Samsung TV, GoPro, phone). A fragment such
as "what you needed" has no auxiliary after the question word, so it does
not match. `policy.intake_can_ask` now refuses to open a new tree only when
there is no dashcam context *and* the turn is clear out-of-scope. When the
intake agent is consulted for an unclear turn, `agent/intake.py:consult`
asks a generic clarifying question -- "I help with Rove dashcams. Can you
tell me a bit more about what you need help with -- which camera it is, and
what it is doing (or not doing)?" -- instead of the model question or an
escalation. The record stays active with no slot asked, so the next turn is
read as a fresh symptom and the normal tree starts from there.

**Battery re-run (Muse, independent, real LLM): 25/25** -- out-of-scope
10/10, negative 9/9, context 3/3, meta 3/3. "what you needed" now asks
(esc=False) with the clarifying question; the weather / joke / capital
cases still escalate. The vague-symptom battery is 5/5 ASK. Suite 456 OK.
Harness A M6 1.00/1.00 (30/30); Harness B 16/16 branches, M4 100%, M5 0,
0 FAIL lines (EVAL-07 passed this run, confirming it flips).
