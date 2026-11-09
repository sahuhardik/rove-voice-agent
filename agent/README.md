# `agent/` — the Phase 1 text-only diagnostic core

Milestone 3 of `docs/06` §9.1. One text turn in, one text turn out: a caller's
words plus the current state become a hypothesis, exactly one next step, and a
list of chunk ids that back whatever was said. No voice and no multi-turn
session store — those are Phases 2b and 3. Since Milestone 4.2 there *is* a
database, but it holds the corpus and the source registry only; state is still
in memory.

The point of this phase is not the score. It is that every hard constraint —
no-repeat, the destructive gate, the grounding rule — is enforced in code that
the model cannot talk its way past, and that the whole thing degrades to the
Phase 0 baseline rather than to nothing when Bedrock is unavailable.

## How to run

```bash
# the tests — stdlib unittest. The store tests skip without Postgres; the rest
# need no network and no AWS credentials.
.venv/bin/python -m unittest eval.test_harness ingest.test_ingest agent.test_core \
    agent.test_graph agent.test_retrieval

# the Postgres + pgvector chunk store (docs/06 §8.5): what is in it, and
# rebuilding it from data/processed/ (--no-embed skips the Bedrock calls)
.venv/bin/python -m agent.store --verify
.venv/bin/python -m agent.store --migrate

# the Phase 0 floor, for comparison
.venv/bin/python -m eval.run

# this agent, against Bedrock (needs an AWS profile with Nova access)
.venv/bin/python -m eval.run --agent core

# this agent with every model call stubbed out as a failure — no AWS,
# exercises retrieval, the policy filter and the output guard on their own
.venv/bin/python -m eval.run --agent core --no-llm

# one part at a time
.venv/bin/python -m eval.run --agent core --part escalation

# the compiled graph: 13 nodes and the §3.2 edges it wired
.venv/bin/python -m agent.graph

# the §8.6 flip-condition measurement — per-turn graph overhead, LLM stubbed
.venv/bin/python -m agent.graph --bench 30
```

`eval.run` exits non-zero only when the *harness* breaks. A low score is a
measurement, not a failure (`docs/06` §9.1).

A single turn, in process:

```python
from agent import core
from agent.llm import BedrockLLM
from agent.state import DiagnosticState

state = DiagnosticState(session_id="demo")
result = core.diagnose("my card keeps giving an error", state, llm=BedrockLLM())
print(result.response_text)   # what the agent would say
print(result.step_id)         # the one action it is proposing
print(result.citations)       # the Tier-1 chunk ids behind it
print(result.trace)           # shortlist, option set, fallbacks, retrieval funnel
```

Environment: `ROVE_BEDROCK_REGION` (default `us-east-1`), `ROVE_MICRO_MODEL_ID`,
`ROVE_PRO_MODEL_ID`, `ROVE_EMBED_MODEL_ID` (default
`amazon.titan-embed-text-v2:0`) and `ROVE_PG_DSN` (default
`postgresql://ubuntu@/rove?host=/var/run/postgresql`, peer auth over the Unix
socket — there is no password anywhere in the repo). AWS credentials come from
the ambient profile. Dependencies are the Python standard library plus `boto3`,
`langgraph` (1.2.20), `psycopg` and `pgvector`.

## Architecture

```
utterance + DiagnosticState
        │
        ▼
  scan_utterance ─────────────► hazard / driving / footage / scope flags
        │
        ▼
  TRIAGE ── llm.classify (Nova Micro) ──┐
        │                               ├──► shortlist: ≤4 taxonomy entries
        └── baseline.match_taxonomy ────┘     (the keyword router is always
        │                                      appended, so the shortlist is
        │   symptoms.assess ─────────────────► never empty); or the §3.2
        │     facet coverage vs docs/02        NO_MATCH exit, when nothing
        ▼     (06 §3.2 / §4.7)                 shortlisted explains the symptom
  retrieval.retrieve  ── per shortlisted entry: model filter → Tier-1 only →
        │                BM25 → top 3, with chunk ids
        ▼
  policy.candidate_steps ── the §3.5 filter chain, in order:
        │     hazard stop → never-agent-initiated → FW-01 interlock →
        │     no-repeat (step *and* family) → model clearance →
        │     driving gate → footage preservation → destructive gate
        │                                  │
        ▼                                  └──► every candidate kept, with a
  the legal option set                          drop reason, for the trace
        │
        ▼
  llm.decide (Nova Pro) ── chooses from the legal set, or is rejected
        │
        ▼
  policy.select ── the cap: one action, the model's pick only if it survived
        │          the filter, otherwise the first legal candidate
        ▼
  policy.escalation ── never the model's call
        │
        ▼
  _compose → output_guard ── drops uncited device claims and any
        │                    version-shaped token; rewrites a step line to its
        ▼                    de-specified form rather than losing the action
  TurnResult(response_text, state, citations, step_id, escalate, trace)
```

| module | what it owns |
| --- | --- |
| `state.py` | the typed `DiagnosticState`: 13 FSM states with a legal-transition table, the attempted-step ledger, hypotheses and ruled-out causes, device identification with CONFIRMED / PROBABLE / UNKNOWN, the structured gate record |
| `retrieval.py` | in-process retrieval over `data/processed/chunks.jsonl` — model-first metadata filtering, Tier-1 speakable chunks only, stdlib BM25 with taxonomy and category boosts, top 3 with chunk ids and a funnel trace |
| `policy.py` | the `docs/06` §3.5 next-step policy: no-repeat with family-level blocking, the destructive gate, the FW-01 interlock, the §6 safety stops, and the escalation decision |
| `symptoms.py` | symptom-facet coverage: what the caller actually reported, what each `docs/02` entry explains, and §4.7's "force it into the nearest category" as a predicate — the `NO_MATCH` exit from `TRIAGE` (§3.2) |
| `llm.py` | a thin `boto3` Bedrock wrapper: Nova Micro for classification, Nova Pro for turn reasoning, strict JSON, `LLMError` on anything else |
| `core.py` | the turn itself: signals, shortlist, retrieval, filter, model call, guard, and the `CoreAgent` adapter behind the Harness A `Agent` protocol |
| `graph.py` | the same turn as a LangGraph `StateGraph`: the 13 states as nodes, the §3.2 transition table as authored edges, pure-function routers, `InMemorySaver` checkpointing the typed record (`docs/06` §8.6 / D-13) |

The package reads `eval.ontology` for the step ontology and the taxonomy →
candidate-step map, and `ingest.metadata` for the `docs/05` verification
statuses. A second copy of either would be a second thing to drift.

## How the LLM is used

Two calls, two models, one rule.

| call | model | job | what happens when it fails |
| --- | --- | --- | --- |
| `classify` | `amazon.nova-micro-v1:0` | category, a shortlist of taxonomy ids, safety/scope flags, model-ID signals | the keyword router in `eval/baseline.py` supplies the shortlist alone |
| `decide` | `amazon.nova-pro-v1:0` | hypothesis and next-step selection, given the state summary and the retrieved chunks | the first legal candidate of the first shortlisted entry — the Phase 0 baseline step |

Temperature is 0 and both calls must return a single JSON object; the reasoning
call must return exactly `category`, `taxonomy_id`, `next_step`, `hypothesis`,
`escalate`, `reason`. A refusal, a preamble, prose around the JSON, or a step id
that is not in the legal set is treated as a failed call rather than a worse
answer — `docs/06` §3.1 has the model choosing among what it is *permitted* to
do, so an answer from outside the permitted set is not an answer.

The rule, and the reason this phase exists:

- **The model never sees an illegal step.** The option list handed to `decide`
  is built from kept candidates only. The filter runs first, always.
- **The model's pick is checked anyway.** Being prompted with the legal set is
  not the same as being constrained to it. `core.diagnose` verifies membership
  and drops to the floor otherwise, recording the rejection in
  `trace["fallbacks"]`. Without that check M4 and M5 would be properties of the
  prompt rather than properties of the code — `agent/test_core.py` scripts a
  model into naming `STEP.CARD.FORMAT_IN_CAMERA` on EVAL-12 to prove it.
- **The model does not decide to escalate.** `decide` returns an `escalate`
  field; it is recorded as a vote in the trace and read by nothing.
  `policy.escalation` decides.
- **The model cannot introduce a device fact.** Whatever it writes passes
  through `output_guard`, which drops any device-specific claim with no Tier-1
  chunk behind it and any firmware-version-shaped token on any path at all.

## Results

Harness A, all 30 golden scenarios, run on 2026-11-07 with
`.venv/bin/python -m eval.run --agent core` against Bedrock Nova in
`us-east-1`. The `dumb` column is `.venv/bin/python -m eval.run` on the same
day — the Phase 0 floor recorded in Milestone 1, unchanged.

**M1–M5, per part.** `core` first, `dumb` in brackets.

| part | n | M1 device | M2 category | M3 next step | M4 no-repeat | M5 harmful |
| --- | --- | --- | --- | --- | --- | --- |
| simple | 10 | 8/10 *(10/10)* | 9/10 *(9/10)* | 8/10 *(9/10)* | 10/10 *(10/10)* | 10/10 *(10/10)* |
| contextual | 10 | 9/10 *(10/10)* | 10/10 *(10/10)* | **8/10** *(5/10)* | 10/10 *(10/10)* | 10/10 *(10/10)* |
| complex | 7 | 7/7 *(7/7)* | 6/7 *(6/7)* | **2/7** *(1/7)* | 7/7 *(7/7)* | 7/7 *(7/7)* |
| escalation | 3 | 3/3 *(3/3)* | **2/3** *(1/3)* | **3/3** *(1/3)* | 3/3 *(3/3)* | 3/3 *(3/3)* |

**M6 escalation correctness.** Precision and recall, always together — an
all-escalate agent scores precision 0.13, recall 1.00, which is why a single
number is never reported.

| part | TP | FP | FN | TN | precision | recall | exact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| simple | 0 | 3 | 0 | 7 | 0.00 | n/a | 7/10 |
| contextual | 0 | 2 | 0 | 8 | 0.00 | n/a | 8/10 |
| complex | 1 | 2 | 0 | 4 | 0.33 | 1.00 | 5/7 |
| escalation | 3 | 0 | 0 | 0 | 1.00 | 1.00 | 3/3 |
| **all 30** | 4 | 7 | 0 | 19 | **0.36** *(dumb 1.00)* | **1.00** *(dumb 0.25)* | 23/30 *(27/30)* |

No aggregate M1–M5 row, by design (`docs/06` §7.3): one number lets a collapse
in the contextual block hide behind the simple block.

### Run-to-run variance

`agent/llm.py` sets `TEMPERATURE = 0.0`, and the scores still do not reproduce.
Three runs of `python -m eval.run --agent core` on the same code — Run A is the
table above; Runs B and C are verification re-runs afterwards:

| part | metric | Run A | Run B | Run C |
| --- | --- | --- | --- | --- |
| simple | M1 / M2 / M3 | 8/10 · 9/10 · 8/10 | 10/10 · 8/10 · 7/10 | 8/10 · 10/10 · 8/10 |
| contextual | M1 / M2 / M3 | 9/10 · 10/10 · 8/10 | 10/10 · 10/10 · 5/10 | 10/10 · 9/10 · 8/10 |
| complex | M1 / M2 / M3 | 7/7 · 6/7 · 2/7 | 7/7 · 4/7 · 2/7 | 7/7 · 5/7 · 2/7 |
| escalation | M1 / M2 / M3 | 3/3 · 2/3 · 3/3 | 3/3 · 2/3 · 3/3 | 3/3 · 2/3 · 2/3 |
| all 30 | M6 precision | 0.36 | 0.25 | 0.27 |
| all 30 | M6 recall | 1.00 | 0.75 | 0.75 |
| all 30 | M6 exact | 23/30 | 20/30 | 21/30 |

M4 and M5 were 100% everywhere in all three runs, with 0 hard-constraint
breaches.

Read plainly: **the core scores vary run to run by two to three scenarios per
part despite temperature 0, so no single run is the core score.** Contextual M3
ranged 5/10 to 8/10, complex M2 4/7 to 6/7, simple M1 8/10 to 10/10 — spreads
as large as the differences this README draws conclusions from.

Two claims are stable across all three runs and are the only ones worth
leaning on:

- **M4/M5: 0 breaches, every run.** These are enforced in code, so they do not
  move.
- **The direction of the M6 problem.** The core over-escalates — seven, nine
  and eight false positives across Runs A, B and C — against a dumb baseline
  that under-escalates at recall 0.25. The precision and recall *values* move
  between runs; the shape of the failure does not.

The earlier reproducibility bullet in "Reading this honestly" was removed in
the same pass that rewrote that section, because its claims did not survive
Runs A–C.

### Milestone 3.1 — model-ID narrowing and over-escalation

Everything above this heading measures the **pre-fix** core. Two of the defects
it names were fixed on 2026-11-07; this section is the measurement afterwards,
and where it disagrees with the tables above, this section is the later word.

**What changed.**

- **`narrows_to` is populated, from the seven-probe ladder.** `docs/06` §3.4's
  discriminator table — SSID prefix, lens count, touch-vs-buttons, connector,
  serial prefix, band behaviour, in-box accessory — now exists as data in
  `agent/state.py`, and `ModelSignal.from_probe` resolves each probe answer to
  the candidate set it leaves standing. `DeviceIdentification.confidence` reads
  that through a new `narrowed` gate: **confidence cannot rise above `UNKNOWN`
  until some signal has actually cut the candidate set.** The `unknown` at
  `PROBABLE` pair behind the M1 failures is now unreachable rather than
  unlikely. A narrowed-but-unresolved set reports a family label — "R2-4K,
  revision not yet established" — instead of `unknown`.
- **`NO_MATCH` / `OUT_OF_SCOPE` alone no longer escalates; a §5.1 trigger is
  required.** §5.1's structural trigger is "`NO_MATCH` *from triage*", not
  "`NO_MATCH` was on the shortlist". Both residual entries now escalate only
  when triage has nothing else to offer — no other shortlisted entry with a
  legal step (`policy.escalation`'s `routable_alternatives`) and no
  deterministic hazard or refund/RMA keyword corroborating them
  (`core._demote_residual_entries`). The classifier's flags are recorded in the
  trace and read by nothing that could *add* an escalation; they are still
  honoured where they only make the turn more cautious. `FW-02` still escalates
  immediately, in parallel with any step, and the UNVERIFIED handling is
  unchanged.

20 new unit tests cover the ladder and the no-escalation paths. `eval`,
`ingest` and `agent` run 96 tests, all passing.

**The runs.** Pre-fix is `core_pre_A`, the diagnostic run that motivated the
fix. Posts 1 and 2 are back-to-back `.venv/bin/python -m eval.run --agent core`
on the fixed code; post 3 is an independent verification run of the same code.
`.venv/bin/python -m eval.run` — the Phase 0 floor — is byte-identical to its
pre-fix output, so the baseline column everywhere above still stands.

| part | M1 / M2 / M3 | pre-fix | post 1 | post 2 | post 3 |
| --- | --- | --- | --- | --- | --- |
| simple | M1 · M2 · M3 | 9/10 · 8/10 · 7/10 | 10/10 · 9/10 · 6/10 | 10/10 · 9/10 · 7/10 | 10/10 · 8/10 · 6/10 |
| contextual | M1 · M2 · M3 | 10/10 · 8/10 · 8/10 | 10/10 · 10/10 · 9/10 | 10/10 · 10/10 · 9/10 | 10/10 · 10/10 · 5/10 |
| complex | M1 · M2 · M3 | 7/7 · 4/7 · 2/7 | 7/7 · 7/7 · 2/7 | 7/7 · 7/7 · 2/7 | 7/7 · 7/7 · 2/7 |
| escalation | M1 · M2 · M3 | 3/3 · 3/3 · 3/3 | 3/3 · 2/3 · 2/3 | 3/3 · 2/3 · 2/3 | 3/3 · 2/3 · 2/3 |

| M6, all 30 | pre-fix | post 1 | post 2 | post 3 |
| --- | --- | --- | --- | --- |
| precision | 0.29 | 1.00 | 1.00 | 0.30 |
| recall | 1.00 | 0.75 | 0.75 | 0.75 |
| false positives | 10 | 0 | 0 | 7 |
| false negatives | 0 | 1 | 1 | 1 |
| exact | 20/30 | 29/30 | 29/30 | 22/30 |

M4 and M5 were 100% with 0 hard-constraint breaches in all four runs.

**The verdict, in ranges.** Three runs is thin evidence against the two-to-
three-scenario spread the variance section measures, so none of these is "the"
score:

- **M1 is 10/10 in every part, in all three post-fix runs** — simple 10/10,
  contextual 10/10, complex 7/7, escalation 3/3, with no device-identification
  failure reported in any of them. Pre-fix, simple M1 ranged 8/10 to 10/10, and
  one pre-fix run also hit 10/10, so three clean runs alone do not establish
  stability. The reason to believe it this time is structural rather than
  statistical: the `narrowed` gate makes `unknown` at `PROBABLE` unrepresentable
  rather than unlikely, and `agent/test_core.py` asserts that directly. Call it
  stable at 10/10 on the mechanism, pending more runs.
- **False positives are down, but not uniformly: 0 to 7 post-fix against 7 to
  10 pre-fix.** Two runs removed them entirely; the third reproduced very nearly
  the pre-fix worst case. The bottom of the range moved a long way and the top
  barely moved, so the honest claim is that the distribution improved, not that
  over-escalation is fixed. Precision correspondingly ranges 0.30 to 1.00.
- **Recall held at 0.75, and did not hold at 1.00.** Pre-fix recall ranged 0.75
  to 1.00; all three post-fix runs sit at the bottom of that range. All three
  miss the same true escalation — **EVAL-28**, the unmatched-symptom scenario,
  which posts 1 and 2 route to `PWR-02` instead of a handoff. That scenario is
  the one `docs/06` §4.7 names as the reason `NO_MATCH` exists, and pre-fix
  Run A caught it. Trading ten false positives for a false negative on *that*
  scenario is the cost of this fix, and it is the first thing to look at next.

### Milestone 3.2 — LangGraph StateGraph orchestration

`docs/06` §8.6 / D-13 chose LangGraph `StateGraph` **as an implementation of
the explicit hand-written state machine, not as a replacement for it**. This
milestone builds that. No agent behaviour changed: the nodes, the routers, the
filter chain and the prompts are the same code the Milestone 3.1 section
measures. What changed is what drives them.

**Version.** `langgraph` **1.2.20**, verified installed in `.venv`.

**What the graph is.** `agent/graph.py` — a `StateGraph` over the 13 states of
the `docs/06` §3.2 machine, 26 edges, all authored:

- **Every edge comes from the transition table.** `_LEGAL_EDGES` is checked at
  import time against `agent.state.LEGAL_TRANSITIONS`, which is imported rather
  than re-typed — one table, not two to drift apart. Every transition still
  goes through `DiagnosticState.transition`, so the typed record, not the
  router, is what accepts or refuses a move.
- **The LLM never chooses a node.** There is no planner, no tool-calling loop
  and no prebuilt agent anywhere in the module. The routers are pure functions
  over the checkpointed record; they never see the utterance, the retrieved
  chunks or anything the model produced. The LLM is called only *inside*
  `core.step_triage` and `core.step_select_step`, as a function, over a set the
  filter chain has already narrowed.
- **Checkpointer: `InMemorySaver`.** The persisted channel is the §3.3 typed
  record. The per-turn working set — retrieval hits, filter verdicts, the
  option list — rides `core.TurnContext` in the run context and is deliberately
  not checkpointed, which keeps the write proportional to the record rather
  than to the corpus. The Postgres checkpointer of §8.5 / D-12 is Phase 2.

23 new unit tests cover the edge table, the routers and the checkpoint
round-trip. `eval`, `ingest` and `agent` now run **119 tests, all passing**
(was 96).

**The §8.6 flip-condition measurement.** `.venv/bin/python -m agent.graph
--bench 30` — 30 passes over the 30 golden scenarios, 900 turns per path, the
LLM stubbed out with `NullLLM` so what is left is LangGraph's own cost. The
same nodes and routers driven by a plain loop (`run_turn_direct`) are option A
exactly:

| per turn | mean | median |
| --- | --- | --- |
| direct loop (option A) | 0.995 ms | 0.980 ms |
| graph, no checkpointer | 4.145 ms | — |
| graph + `InMemorySaver` | 8.076 ms | 8.043 ms |
| **graph overhead** | **7.081 ms** | **7.063 ms** |
| of which, checkpoint write | 3.931 ms | — |

**Is it material? No, against latency line 4.** `docs/06` §2.2 line 4 budgets
20 ms median / 50 ms p95 for the safety gate, FSM and policy filters together.
The whole graphed turn — nodes, routing, channel writes and the checkpoint —
costs **8.043 ms median**, inside that 20 ms budget with room left; the
overhead the graph itself adds is 7.063 ms median, about a third of the line.
Against §8.3's end-to-end voice budget, where a single model call is hundreds
of milliseconds, 7 ms is not visible at all. **The §8.6 flip condition is not
met and we are not flipping back to the hand-written loop.** Worth recording
for Phase 2: 3.931 ms of the 7.081 ms is the checkpoint write, and that is the
number the Postgres swap moves — it is the one that needs re-measuring, not
the graph.

**The runs.** Posts 1 and 2 are back-to-back `.venv/bin/python -m eval.run
--agent core` on the migrated code; post 3 is an independent verification run
of the same code. `.venv/bin/python -m eval.run` — the Phase 0 floor — is
byte-identical to its pre-migration output, so every `dumb` column above still
stands.

| part | M1 / M2 / M3 | post 1 | post 2 | post 3 |
| --- | --- | --- | --- | --- |
| simple | M1 · M2 · M3 | 10/10 · 9/10 · 6/10 | 10/10 · 10/10 · 8/10 | 10/10 · 9/10 · 6/10 |
| contextual | M1 · M2 · M3 | 10/10 · 10/10 · 8/10 | 10/10 · 10/10 · 9/10 | 10/10 · 10/10 · 7/10 |
| complex | M1 · M2 · M3 | 7/7 · 7/7 · 2/7 | 7/7 · 7/7 · **0/7** | 7/7 · 7/7 · 2/7 |
| escalation | M1 · M2 · M3 | 3/3 · 2/3 · 2/3 | 3/3 · 2/3 · 2/3 | 3/3 · 2/3 · 2/3 |

| M6, all 30 | post 1 | post 2 | post 3 |
| --- | --- | --- | --- |
| precision | 1.00 | 0.75 | 1.00 |
| recall | 0.75 | 0.75 | 0.75 |
| false positives | 0 | 1 | 0 |
| false negatives | 1 | 1 | 1 |
| exact | 29/30 | 28/30 | 29/30 |

M4 and M5 were 100% with 0 hard-constraint breaches in all three runs.

**The verdict, in ranges.** Mostly yes, with one exception that has to be said
plainly:

- **M1 held at 10/10 in every part, in all three runs** — simple 10/10,
  contextual 10/10, complex 7/7, escalation 3/3. Same as the three post-3.1
  runs.
- **M6 false positives: 0, 1, 0 — inside the post-3.1 range of 0 to 7**, and at
  the good end of it. Precision 0.75 to 1.00 against post-3.1's 0.30 to 1.00.
  Three runs is not enough to claim the distribution tightened; what it does
  support is that the migration did not widen it.
- **Recall held at 0.75 in all three runs**, exactly as in all three post-3.1
  runs, and missing the same scenario — **EVAL-28**, which posts 1 and 2 route
  to `PWR-04` and `PWR-02` instead of a handoff. Unchanged, still the first
  thing to look at next.
- **M4 / M5: 0 breaches, every run.**
- **Complex M3 fell out of range once: 0/7 in post 2, against 2/7 in all four
  runs in the Milestone 3.1 section.** Posts 1 and 3 are back at 2/7, so this
  is one run of three, not a trend — but 2/7 was the one complex-M3 number that
  had not moved across four prior runs, and it moved. Complex M3 is now 0/7 to
  2/7. Nothing in the graph can select a different step — the routers never see
  model output — so the likely cause is the same run-to-run variance the
  variance section measures, landing on an already-near-zero number. It is not
  evidence of a regression and it is not evidence against one; it needs more
  runs before complex M3 can be quoted as 2/7 again.

**Where this leaves us against `docs/06`.** LangGraph is now present as §8.6 /
D-13 specifies — the orchestration decision is implemented, not deferred.
Still missing, unchanged by this milestone: **Harness B** (multi-turn grading,
§7.4), **hybrid dense retrieval** (`retrieval.py` is still stdlib BM25),
**Postgres / pgvector** (§8.5 — no session store, no resumable call, and the
checkpointer is in-memory), and **voice / UI** (no ASR, no TTS, no barge-in,
none of the §8.3 latency budget). The list below is unchanged.

### Milestone 3.3 — the EVAL-28 regression

The thing both sections above call "the first thing to look at next". Fixed on
2026-11-07; where this disagrees with anything above it, this section is the
later word.

**The defect.** All six post-3.1 and post-3.2 runs missed the same true
escalation. On EVAL-28 — *"There's this clicking noise coming from it and
sometimes the screen goes all stripey and then it restarts itself"* — the
classifier put `NO_MATCH` on the shortlist alongside `PWR-02`,
`_demote_residual_entries` dropped `NO_MATCH` because `PWR-02` counted as a
routable alternative, and `policy.escalation` saw a non-empty
`routable_alternatives` list and declined. The turn went to a `PWR-02` step.
`PWR-02` is *Shuts down in heat*: it explains **one of the three** symptoms the
caller reported, and its own discriminating condition — heat, recovery once
cool — appears nowhere in the utterance. `docs/03` is explicit that this is the
worst available outcome: "Forcing it into the nearest category... is the
hallucination failure in `01` §5 and the most damaging thing the agent can do
here."

**What changed.** Milestone 3.1 measured "triage could have routed this" as
*any other shortlisted entry with a legal step*. That test is too weak, and
`docs/06` says why in two places:

- §3.2's state table: `TRIAGE` exits with "Taxonomy ID **or** `KNOWN-GAP`
  **or** `NO_MATCH` assigned | 1 turn; `NO_MATCH` → `ESCALATE` (this is
  EVAL-28)". Alternatives, not a ranking — a shortlist holding both `NO_MATCH`
  and a partial match has not finished triaging.
- §4.7: `KNOWN-GAP` handling "is explicitly **not** 'force it into the nearest
  category', which is the EVAL-28 failure and the most damaging thing the agent
  can do (`03`)".

New module **`agent/symptoms.py`**, which reads the caller's words and `docs/02`
and nothing else:

- **`reported_facets`** splits an utterance into distinct symptom facets by
  whole-phrase match — deterministic, the same kind of rule as
  `eval/baseline.RULES`, but on word boundaries, so "time" cannot fire inside
  "sometimes" the way the keyword router's does.
- **`ENTRY_EXPLAINS` / `ENTRY_DISCRIMINATORS`** transcribe, per `docs/02`
  entry, which facets its *Symptom (caller)* line covers and what its *Must
  ask* line turns on. Entries are credited generously — `PWR-02` is credited
  with EVAL-28's restarts — because over-crediting only makes the new exit
  *harder* to reach.
- **`is_nearest_category_force`** is §4.7's phrase as a predicate: two or more
  reported facets, the entry explains a **strict** minority of them, and its
  discriminating condition is absent. Strict, so EVAL-25's `SD-03` (one of two)
  and EVAL-24's `REC-04` are still routes; condition-aware, so EVAL-23's
  volunteered "it's been really hot today" keeps `PWR-02` routable there.
- **`assess`** concludes `NO_MATCH` only when every shortlisted entry is such a
  force *and* some reported facet is explained by no `docs/02` entry at all —
  `audible_noise`, `display_artefact`, `frozen_screen`, which are §4.7's own
  list of `docs/05` finds with "no diagnostic branch for any of them".

`core.step_triage` takes that exit and sets the shortlist to `["NO_MATCH"]`;
`_demote_residual_entries` and `core.step_select_step`'s
`routable_alternatives` both stop counting a forced category as an alternative.
Everything 3.1 fixed is intact and asserted: a `NO_MATCH`/`OUT_OF_SCOPE` vote
alongside a genuine single-symptom route still does not escalate, `FW-02` still
escalates immediately, `UNVERIFIED` handling is untouched, and the no-repeat
ledger, destructive gate and FW-01 interlock were not opened.

9 new unit tests. `eval`, `ingest` and `agent` now run **128 tests, all
passing** (was 119). Two of them are the reason to believe this generalises
past one scenario: **no taxonomy entry at all** — all 28, not just the one the
classifier offered — can route EVAL-28, and **no other scenario in the set**
reports a facet outside `docs/02`, which is the precondition for the new exit.
The mechanism also holds with Bedrock down: `--no-llm` scores EVAL-28 `PASS ·
NO_MATCH · STEP.ESCALATE.HANDOFF`, where the keyword router alone had forced it
to `PWR-04`.

**The runs.** Posts 1 and 2 are back-to-back `.venv/bin/python -m eval.run
--agent core` on the fixed code. `.venv/bin/python -m eval.run` — the Phase 0
floor — is byte-identical to its recorded output, so every `dumb` column above
still stands.

| part | M1 / M2 / M3 | post-3.2 range | 3.3 post 1 | 3.3 post 2 |
| --- | --- | --- | --- | --- |
| simple | M1 · M2 · M3 | 10/10 · 9–10/10 · 6–8/10 | 10/10 · 9/10 · 6/10 | 10/10 · 9/10 · 6/10 |
| contextual | M1 · M2 · M3 | 10/10 · 10/10 · 7–9/10 | 10/10 · 10/10 · 8/10 | 10/10 · 10/10 · 8/10 |
| complex | M1 · M2 · M3 | 7/7 · 7/7 · 0–2/7 | 7/7 · 7/7 · 3/7 | 7/7 · 7/7 · 2/7 |
| escalation | M1 · M2 · M3 | 3/3 · 2/3 · 2/3 | 3/3 · **3/3** · **3/3** | 3/3 · **3/3** · **3/3** |

| M6, all 30 | post-3.2 range | 3.3 post 1 | 3.3 post 2 |
| --- | --- | --- | --- |
| precision | 0.75–1.00 | 1.00 | 1.00 |
| recall | 0.75 | **1.00** | **1.00** |
| false positives | 0–1 | 0 | 0 |
| false negatives | 1 | **0** | **0** |
| exact | 28–29/30 | 30/30 | 30/30 |

M4 and M5 were 100% with 0 hard-constraint breaches in both runs.

**The verdict, in ranges.** Two runs is thin — the variance section measures
two-to-three scenarios of spread per part — so these are ranges over two runs,
not a score:

- **EVAL-28 escalated in both runs**, as `NO_MATCH` → `STEP.ESCALATE.HANDOFF`,
  which is `docs/03`'s expected outcome and one of its two expected steps. It
  also escalates with the model stubbed out and with the model scripted to
  insist on `PWR-02`, so this one is structural rather than statistical: the
  `--no-llm` and scripted-model tests assert it without Bedrock.
- **False positives stayed at 0 in both runs**, at the good end of the
  post-3.1 range of 0 to 7 and inside the post-3.2 range of 0 to 1. The
  over-escalation 3.1 closed did not reopen. The reason to expect that to hold
  is the §4.7 unmapped-facet precondition, which no other scenario in the set
  meets — asserted directly in `agent/test_core.py` rather than inferred from
  these two runs.
- **Recall was 1.00 in both runs**, against 0.75 in all six prior post-fix
  runs, and above the 0.75 floor this milestone had to hold. Both runs caught
  all four escalations with zero false positives — precision and recall 1.00
  together, 30/30 exact. That is the first time both have been at 1.00 in the
  same run, and two runs is not enough to call it the steady state.
- **M1 held at 10/10 in every part, in both runs.** Unchanged since 3.1.
- **M4 / M5: 0 breaches, both runs.**
- **Complex M3 came back to 2–3/7**, against post-3.2's 0–2/7. Simple M3 sat at
  6/10 both runs, the bottom of its 6–8/10 range. Neither moved for a reason
  this milestone can claim: nothing here changes step selection on a scenario
  that routes.

### Milestone 4.2 — hybrid retrieval on Postgres + pgvector

`docs/06` §8.5 option B, built on 2026-11-07. `retrieval.py` was stdlib BM25
over `chunks.jsonl`; it is now BM25 over `tsvector` lexemes plus Titan dense
vectors, both computed in Postgres, fused 0.5/0.5 as §4.6 specifies. New
module `agent/store.py` owns the schema, the migration and the SQL;
`retrieval.py` owns the filter chain, the fusion and the rerank and writes no
SQL. Where this disagrees with anything above it, this section is the later
word.

**What is actually running.** Verified from the store itself, not from a
changelog:

| | |
| --- | --- |
| Postgres | `PostgreSQL 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1) on x86_64-pc-linux-gnu, compiled by gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0, 64-bit` |
| pgvector | `vector` `0.8.1` |
| connection | `postgresql://ubuntu@/rove?host=/var/run/postgresql` — Unix socket, peer auth, no password in the repo or the environment |
| embedding model | `amazon.titan-embed-text-v2:0`, `us-east-1` (`docs/07` D-11) |
| embedding dimension | **1024** |
| loaded | 21 source-registry rows, 161 chunks, 122 speakable, 122 embeddings, 23 238 lexeme rows |

**Note — master reload after the Track C merge.** The 161/122 figures in this
section describe the branch-time load. The store on master now holds **28
sources, 213 chunks, 159 speakable, 159 embeddings at dim 1024**
(`amazon.titan-embed-text-v2:0`), and `agent/test_retrieval.py` pins those
numbers. Everything else below — the schema, the probe, the weights — is
unchanged by the reload.

The dimension is **probed, never declared**. §8.5 says "the schema must not
hard-code it", so `migrate()` embeds one throwaway string, reads `len()` off
the result, and creates `vector(n)` with whatever came back; `(model_id, dim)`
goes into the `embedding_model` table and retrieval reads it from there. The
1024 above was re-verified three ways after the fact rather than copied
forward: a fresh Titan call returned 1024, `atttypmod` on
`chunk_embeddings.embedding` is 1024, and `SELECT DISTINCT
vector_dims(embedding)` over all 122 stored vectors returns exactly one row,
1024. Nothing in the source files contains the number.

**The hybrid, in the weights it actually uses.** §4.6's `0.5 · BM25(query +
taxonomy_id + step vocabulary) + 0.5 · dense(query)`, with each half min-max
normalised over the surviving pool first — a raw BM25 score and a cosine are
not on the same scale, and summing them unnormalised would make the 0.5/0.5
decorative. BM25 is Okapi with the textbook `k1 = 1.5`, `b = 0.75`, computed in
SQL from the generated `tsvector`, with document frequencies taken over the
whole speakable corpus rather than the post-filter subset. The dense half is
`1 - (embedding <=> query)`. The reranker over the k = 8 is unchanged from the
lexical-only milestone: taxonomy `× 1.6`, category `× 1.25`, safety-critical
`× 1.1`, then `[:3]`. When Titan is unreachable the dense half drops and BM25
carries at weight 1.0 rather than being halved against a column of zeroes;
when Postgres is unreachable the module falls back to `chunks.jsonl` with
in-process BM25. Both show in the retrieval funnel (`store jsonl`, `dense
scored 0`), so a run cannot quietly report hybrid numbers it did not produce.

**Tests: 153, all passing** (was 128 at 3.3), via

```bash
.venv/bin/python -m unittest eval.test_harness ingest.test_ingest \
    agent.test_core agent.test_graph agent.test_retrieval
```

The 25 new ones are in two halves. The fusion arithmetic, the k = 8 cut, the
rerank and the dense-unavailable degradation run against a hand-built backend
with canned scores — no database, no network, so they never skip. The safety
properties run against the real store, because that is where they are
enforced: the model filter is the `WHERE` clause of the pool query, and
`test_the_excluded_chunk_is_not_even_in_the_pool` asserts the wrong-model chunk
is never scored rather than filtered out afterwards. Two tests assert the
schema itself refuses a Tier-2 row and refuses `speakable` on an `UNVERIFIED`
entry, and one asserts the SQL model filter and the Python one return identical
pools across all seven confidence/model branches.

Four of those tests failed on first run and **the tests were wrong, not the
retrieval** — they were written alongside the implementation and never
executed. Recorded because a corrected expectation is worth less than an
uncorrected one unless it says what it was:

- Two had canned scores that tie under min-max normalisation, so the assertion
  could not have held for any implementation. One of them asserted a
  *structurally impossible* property: under equal weights, a chunk with no
  lexical overlap sits at the pool floor and fuses to at most 0.5, exactly what
  the lexical leader gets from its own half, so it can tie for first but never
  take it. What the dense half really buys such a chunk is admission to the
  k = 8 at all — BM25 alone scores it 0 and drops it. The test now asserts
  that, and the ceiling is written into the test as a comment.
- One expected a boosted chunk to land second when `0.667 × 1.6 = 1.067`
  clears the unboosted leader's `1.0` — the test's arithmetic, not the code's.
- One asserted the top hit for a chunk's own text is that chunk. It is on BM25
  alone (that premise is a separate passing test) and it is not under the
  hybrid: the chunk in question is a firmware-update passage sitting inside a
  Wi-Fi article, and the three dedicated firmware chunks beat it on the dense
  half. It now asserts the property the model filter actually owns, which is
  rank-independent — present in its own model's candidate set, absent from
  every other model's at any `k`.

That last one is the clearest thing this milestone learned about the dense
half: it ranks by what a passage is *about*, which demoted an exact lexical
match from first to fourth. M3 did not notice, but it is the kind of change
that would show up in a grounding measurement, which does not exist yet.

**The runs.** Two back-to-back `.venv/bin/python -m eval.run --agent core` on
the hybrid code, against Bedrock Nova in `us-east-1`:

| part | M1 / M2 / M3 | post-3.3 | 4.2 run 1 | 4.2 run 2 |
| --- | --- | --- | --- | --- |
| simple | M1 · M2 · M3 | 10/10 · 9/10 · 6/10 | 10/10 · 9/10 · 6/10 | 10/10 · 9/10 · **8/10** |
| contextual | M1 · M2 · M3 | 10/10 · 10/10 · 8/10 | 10/10 · 10/10 · 8/10 | 10/10 · 10/10 · **9/10** |
| complex | M1 · M2 · M3 | 7/7 · 7/7 · 2–3/7 | 7/7 · 7/7 · 2/7 | 7/7 · 7/7 · 2/7 |
| escalation | M1 · M2 · M3 | 3/3 · 3/3 · 3/3 | 3/3 · 3/3 · 3/3 | 3/3 · 3/3 · 3/3 |

| M6, all 30 | post-3.3 | 4.2 run 1 | 4.2 run 2 |
| --- | --- | --- | --- |
| precision | 1.00 | 1.00 | 1.00 |
| recall | 1.00 | 1.00 | 1.00 |
| false positives | 0 | 0 | 0 |
| false negatives | 0 | 0 | 0 |
| exact | 30/30 | 30/30 | 30/30 |

M4 and M5 were 100% in every part with 0 hard-constraint breaches in both runs.
`.venv/bin/python -m eval.run` — the Phase 0 floor — is byte-identical to its
recorded output (simple 10/10 · 9/10 · 9/10, contextual 10/10 · 10/10 · 5/10,
complex 7/7 · 6/7 · 1/7, escalation 3/3 · 1/3 · 1/3; M6 precision 1.00, recall
0.25, 27/30 exact), so every `dumb` column above still stands.

**What the runs are and are not evidence for.** Every post-3.3 guarantee held:
M1 10/10 in all four parts in both runs, M6 precision and recall both 1.00 on
0 false positives, M4/M5 clean, EVAL-28 still escalating. Simple M3 8/10 and
contextual M3 9/10 in run 2 are the best either has scored since 3.1 — and the
variance section above measures two-to-three scenarios of spread per part at
temperature 0, so **two runs cannot distinguish that from noise, and this
milestone does not claim the hybrid improved M3.** What it claims is narrower
and is what §8.5 asked for: the retrieval is hybrid, it runs on the store that
also holds the source registry, and nothing regressed.

**Alignment with `docs/06`, stated explicitly.**

*Present now.* §8.5 option B is built, not planned: Postgres 18.6 with pgvector
0.8.1 holds the chunks and the source registry in one database, with §4.4's
"no chunk without a registry entry is indexed" as a literal foreign key and
§4.5's tier and status rules as `CHECK` constraints rather than application
filters. §4.6's hybrid search is both halves for the first time — the dense
half had never existed before this milestone.

*Still missing, and not narrowed by this work.*

- **Session state.** The store holds chunks and the registry. It does **not**
  hold session records, attempted-step ledgers, orchestration checkpoints or
  traces — the four other things §8.5 gives as the reason to choose Postgres
  at all. `DiagnosticState` still lives for the lifetime of one process, so
  there is still no resumable call and no handoff payload.
- **Harness B.** `docs/06` §7.4's multi-turn harness does not exist. It is a
  **parallel track, not a dependency of this one**: Harness A grades one turn,
  this milestone changed what that turn retrieves, and neither blocks the
  other.
- **Grounding measurement.** There is still no retrieval-level precision or
  recall. Retrieval is graded only through its effect on M3, which is exactly
  the measurement the demotion noted above would not show up in. This is now
  the most useful missing number, and it got more useful, not less, by adding
  a second ranking signal nobody can eyeball.
- **Voice and UI.** Unchanged and untouched: no ASR, no TTS, no barge-in, none
  of the §8.3 latency budget, and no web client. The ~10–20 ms database hop
  §8.5 predicted for line 5 is now real but unmeasured, because there is no
  line 5 to measure it in.

### Reading this honestly

Everything in this subsection was written against the pre-fix Runs A, B and C
and is superseded, where the two disagree, by the Milestone 3.1 section above.
Every claim below is stated across Runs A, B and C from the variance section
above. Where a number moved between runs it is given as a range, not as the
Run A value.

- **Hard constraints: 0 breaches on all 30, in both agents.** M4 and M5 are
  code, not behaviour. `agent/test_core.py` also re-runs the whole set with the
  model stubbed to fail and asserts zero breaches there too. This held in all
  three runs.
- **The contextual block is where the core moves M3 most, and the move is not
  stable.** Contextual M3 ranged 5/10 to 8/10 across Runs A, B and C, against a
  baseline of 5/10 — one run matched the baseline exactly, two beat it by
  three. That block is the one where the answer depends on what the caller
  already tried, which is what a keyword router cannot see, and it is the right
  place to look for the core's value. But on this evidence the core cannot be
  said to earn its keep there: the spread is as wide as the gain.
- **Escalation recall ranged 0.75 to 1.00, precision 0.25 to 0.36, on 7 to 9
  false positives.** The direction is stable and the values are not: the core
  over-escalates, against a baseline that under-escalates at recall 0.25,
  precision 1.00. It also missed a scenario that should have escalated in two
  of the three runs, so it does not reliably catch everything either.
  Precision is still the single biggest thing to fix next. The baseline's 1.00
  precision is not a virtue — it escalates almost never, so it is nearly never
  wrong when it does. Most false positives are the classifier reaching for
  `NO_MATCH` or `OUT_OF_SCOPE` on a scenario it could have routed, after which
  the escalation policy does exactly what it is told.
- **M2 moves between runs and does not separate the two agents.** Simple M2
  ranged 8/10 to 10/10 against the floor's 9/10, contextual 9/10 to 10/10
  against 10/10, complex 4/7 to 6/7 against 6/7 — the core's spread straddles
  the baseline in each. Only escalation M2 is both stable and above the floor,
  at 2/3 in all three runs against 1/3. Routing is not where the core is
  winning or losing; step *selection* is.
- **M1 has a real code defect behind it, but the scenario count is not
  stable.** In Run A, EVAL-02 and EVAL-06 were both reported as model `unknown`
  at confidence `PROBABLE` — two values that should not be able to disagree.
  That combination is reachable, and on this path unavoidable: `core.py` builds
  every `ModelSignal` without `narrows_to` (`agent/core.py:544`), so
  `device.candidates` never narrows below all six models, and `device.model` is
  only ever assigned once the candidate set reaches one
  (`agent/state.py:232`). Any feature signal therefore raises confidence to
  `PROBABLE` or better while the model stays `unknown`, and `reported_model`
  passes that `unknown` through because confidence is no longer `UNKNOWN`
  (`agent/state.py:218`). The defect is real; the two-scenario count is Run A's
  alone — simple M1 ranged 8/10 to 10/10 across the three runs, and Run B lost
  none. See the known defect below.

## What is still missing

**Voice.** Nothing in this package speaks or listens. No ASR, no TTS, no
barge-in, no turn-taking, none of the `docs/06` §8.3 latency budget. `core.py`
produces text through `spoken_form` and `output_guard` with speech in mind —
asking rather than asserting, no versions, no unbacked specifics — but it has
never been spoken. Phase 2b.

**Postgres — half of it, since Milestone 4.2.** The chunks and the source
registry are in Postgres with pgvector, and `retrieval.py` is hybrid BM25 +
Titan dense over that store. What is still not there is the half §8.5 actually
chose Postgres for: *state*. `DiagnosticState` lives in an object for the
lifetime of one process, there is no session store, no ledger that survives a
transfer, no orchestration checkpoint and no handoff payload a human agent
could open. The `ingest` side still writes JSONL, which `store.migrate()` then
loads. Phase 3.

**Also not built, in rough order of how much they matter:**

- *Escalation precision.* Written against the pre-3.1 core's seven false
  positives out of 26 negative controls. Post-3.1 runs range 0 to 7 and both
  Milestone 3.3 runs are at 0, so this is no longer the top item — but two
  clean runs do not retire it either.
- *Multi-turn.* Harness A grades one turn. `state.py` has the FSM, the turn
  ceilings and the ledger-update path for a conversation, but nothing drives
  them; Harness B (`docs/06` §7.4) does not exist.
- *The consent surface.* `policy._gate_for` always records
  `consent_state="not_requested"`, because in text mode there is nothing to ask
  with. Every destructive step is therefore blocked — correct for Phase 1,
  and untested against a real consent path.
- *A known M1 defect.* On one run the agent reported model `unknown` with
  confidence `PROBABLE` on EVAL-02 — a weak model signal raising confidence
  without ever resolving a model name. The two values should not be able to
  disagree like that. `state.DeviceIdentification.confidence` needs to depend
  on the candidate set having actually narrowed.
- *Retrieval quality.* Hybrid BM25 + dense with hand-tuned rerank boosts, still
  evaluated only through its effect on M3. There is no retrieval-level
  precision/recall measurement, and Milestone 4.2 made that gap matter more:
  there are now two ranking signals and no way to grade either directly.
