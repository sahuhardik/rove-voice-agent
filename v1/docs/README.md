# Rove Voice Troubleshooting Agent — Step 1 Design Docs

Status: **Step 1 complete with initial hypotheses from model knowledge. Step 1b (web
verification) still needed before production, but prototype can proceed.** Design only.
No code in this repo yet.
Date: 2026-11-07

A **web-based** voice support agent for Rove dashcams. The user opens a page in a browser,
grants microphone permission, and speaks; audio travels over WebRTC. There is no phone call
and no phone number (scope correction, 2026-11-07 — `01` "Scope correction", `06` §0.1). The
agent must **diagnose** — identify the device, establish what changed, ask for what is
missing, rank causes, recommend one next step, verify the result, and hand off to a human
when it should. The screen it has is **ours**, and the rule is voice-complete,
screen-accelerated: every path must be completable by voice alone (`06` §1.4.1).

---

## Read this first: the two layers

Step 1 asked for research against `rovedashcam.com`, Rove firmware and release notes, and
public review text. **None of it was retrieved.** WebSearch, WebFetch, and outbound `curl`
were denied by the session permission layer in the original session, and WebSearch was
re-attempted and denied again when `02` and `03` were written. This is a permission denial
on our side — not a 404, not a robots block, not a site outage.

Consequence, stated plainly: **these documents contain no verified fact about any Rove
device.** Not a model name, not a firmware version, not a menu path, not an SD card spec,
not a single fix. Every candidate fix is marked `TO VERIFY — do not present as fact`.
Every symptom pattern is marked `Review signal (unretrieved)` or `Inferred`. Nothing is
marked `Official doc`, because we have read no official doc.

What we produced instead is the part of the work that does not depend on retrieval: the
problem framing, the voice constraints, the failure modes, the diagnostic structure, the
questions worth asking, and the evaluation design. That is real work and it holds up. But
`02` is a question list and a hypothesis map, not an answer set, and `03` grades reasoning,
not correctness.

### The two layers

Since the original write-up, `02` has gained a section called **"Initial hypotheses from
model knowledge"**, and every one of the 28 entries has gained a `Most plausible next step
(initial hypothesis)` and a `What would confirm / disconfirm it` field. That splits the
knowledge in these docs into two layers, and keeping them apart is the whole point:

- **Layer 1 — intelligence hypotheses. Usable now.** Reasoning from general product-class
  knowledge and from what is recalled about Rove specifically, written down and labelled
  `Initial hypothesis — to verify` with a confidence of Low, Medium, or High. This layer is
  enough to build a prototype against, enough to run the eval set as a design check, and
  enough to argue about. It is **not** enough to speak to a customer. Confidence `High` in
  this layer means "this holds across consumer dashcams generally", never "this is true of
  a Rove".
- **Layer 2 — web-verified facts. Step 1b, still outstanding.** Model names, firmware
  behaviour, menu paths, card limits, app and SSID details, every specific fix — each with a
  URL and a retrieval date. Nothing in these docs is in this layer yet; `0` entries are
  marked `Official doc`. **No step is cleared for an agent to say out loud until it reaches
  Layer 2.**

**Step 1b is no longer blocking Step 2 — it is blocking production.** Its character has
changed too: it is now *verification against a concrete list* rather than creation against an
empty one. Re-run the research with web access granted, promote entries from `Inferred` to
`Official doc` with a URL and a retrieval date, correct or delete the hypotheses in `02`'s new
section, and re-grade which "next steps" the agent is actually cleared to speak. If Rove
documentation turns out not to be public, the fallback is internal support documentation and
Step 1b must be re-planned around that (`01` §7, assumption 3).

---

## The nine documents

| Doc | What it is | Use it for |
|---|---|---|
| [`01-problem-definition.md`](01-problem-definition.md) | Problem statement, who the user is, what voice-first costs us, what success means, scope boundaries, failure modes, PROPOSED targets, assumptions, open questions. Carries the 2026-11-07 scope correction to a web-based UI. | Settling arguments about scope and about what counts as success. Start here. |
| [`02-issue-taxonomy.md`](02-issue-taxonomy.md) | A model-knowledge hypothesis section (model line, app, card requirements, firmware paths), then 28 issues across 7 categories — each with the customer's wording, the missing information to ask for, ranked causes, a discriminating next step, a most-plausible next step with what would confirm or disconfirm it, an escalation trigger, and an evidence type. | The agent's diagnostic map. Also the Step 1b verification worklist — each `TO VERIFY` and each `Initial hypothesis` is one research task. |
| [`03-golden-eval-set.md`](03-golden-eval-set.md) | 30 scenarios: 10 simple, 10 contextual, 7 complex, 3 escalation. Spoken-style utterance, known context, expected diagnosis, exactly one expected next step, what a wrong response looks like, expected outcome. | Grading any candidate agent — including before one exists, as a design check. |
| [`04-data-sources.md`](04-data-sources.md) | Tiered inventory of Rove data sources researched by Muse via web on 2026-11-07 — Tier 1 official Rove pages, Help Center and manuals (ground truth, reachable), Tier 2 review corpora (discovery only), Tier 3 supplementary — with URLs, what each yields, access notes, a collection plan, gaps, and the mapping from Tier 1 sources to the taxonomy entries they can verify. | Running Step 1b: where to retrieve from, in what order, and which `TO VERIFY` entry each source answers. |
| [`05-step1b-verification.md`](05-step1b-verification.md) | Step 1b verification of the taxonomy against the Tier 1 corpus held on disk — 6 manuals (260 pages), 3 official Rove pages, 12 Help Center articles — with each checked entry marked VERIFIED, CORRECTED or UNVERIFIED, and the source codes `M1`…`M6`, `O1`…`O3`, `H:<name>` it cites. | Finding out which taxonomy entries now have a Tier 1 source behind them, and which are still unevidenced. |
| [`06-architecture.md`](06-architecture.md) | Step 2 architecture, fully re-derived for the web-based UI. System overview and component diagram, the browser client and the voice-complete/screen-accelerated rule, the real-time voice pipeline with a 9-component latency budget and a degradation ladder, the diagnostic state machine (model identification across the 8 models and 2 R2-4K revisions, the attempted-step ledger and the no-repeat rule), RAG design with metadata filtering and the source registry, human escalation into the same room, safety and consent, measurement and the eval harness, technology choices with alternatives, and the phased build plan. | Building it. Also the list of decisions that are not ours to make (§9.3). |
| [`07-decision-log.md`](07-decision-log.md) | The decision record behind `06` §8. Two governing constraints (web-not-telephonic; AWS models only, no Bedrock access request) and 17 decisions — transport, voice framework, VAD, cascaded-vs-speech-to-speech, ASR, four LLM roles, TTS, embeddings, vector store, orchestration, backend, UI framework, the diagnostic flow, and the escalation flow — each with the alternatives considered, why this one won, what it costs, and the flip condition that would reverse it. | Re-opening a decision without re-litigating it, and knowing which `06` §9.3 open item gates which choice. |
| [`08-diagrams.md`](08-diagrams.md) | The Mermaid-source companion to `06` and `07`. Six diagrams — system architecture, the voice turn as a sequence with the 9-component latency budget under it, the diagnostic state machine with the 7-probe model-ID ladder and the global ceilings, the framework and model responsibility map, the data/RAG flow from 21 Tier-1 documents to a cleared spoken or rendered turn, and the accuracy-assurance picture. Adds nothing to `06`; every box and number is drawn from it. | Rendering, embedding or diffing the architecture instead of reading ASCII art. `06` remains the source of truth. |
| `README.md` | This file. | Index, research status, what Step 2 is. |

### Key numbers

- **9** docs · **5,516** lines · **11** catalogued data sources across 3 tiers
  (**5** Tier 1 ground-truth, `04`)
- **17** recorded technology/design decisions + **2** governing constraints (`07`), of which
  **5** are `TO VERIFY` against the AWS console
- **28** taxonomy entries · **7** categories · **0** marked `Official doc`
- **30** eval scenarios · **4** expecting escalation · **26** negative controls
- **9** proposed metrics (`01` §6), **2** of them hard constraints, **0** with a baseline

---

## How to use the eval set

**Grade the next step, not the reply.** For each scenario the agent produces one next
question or action given the utterance and the known context. That single move is what is
scored. Do not grade wording — grading wording teaches an agent to sound right rather than
reason right, which is exactly the failure mode we are trying to avoid.

**Five axes per scenario:** category, next step, no-repeat, safety, escalation. The first
two are scored. No-repeat and safety are **pass/fail** — a correct diagnosis delivered with
a destructive step is a failed scenario, not a partial credit. See `03`, "How to use this set".

**Watch the negative controls.** 26 of 30 scenarios expect *no* escalation. An agent that
escalates everything is not safe, it is useless, and it will look excellent on the three
escalation cases alone. Report escalation precision and recall together, never one of them.

**The contextual block is the sharpest instrument here.** All ten of EVAL-11 … EVAL-20 state
something the caller already tried and that already failed. An agent that proposes any of
those steps again has failed on the one constraint that most visibly separates a support
engineer from a search index.

**Three ways to run it:**

1. *Design check, now.* Read a scenario, write down what you think the agent should ask,
   compare. Disagreements about the expected next step are design bugs worth fixing in `02`
   before any code exists.
2. *Prompt iteration, later.* Text-only, scripted caller responses for the multi-turn items.
   Fast, cheap, and it isolates reasoning from the voice pipeline.
3. *End-to-end, eventually.* Synthesised speech over the real pipeline, with noise. Note
   that this set does **not** test latency, barge-in, or turn-taking — those need their own
   harness (`03`, "What is still unknown").

**Expect to rewrite it.** Every utterance here was written by us, not collected. The first
batch of real call transcripts should replace them, and the pass rates before and after will
not be comparable.

---

## Step 2 — architecture (done: `06`, `07`, `08`)

Step 2 is design, not implementation, and it **has now been written**: the architecture is
[`06-architecture.md`](06-architecture.md), the reasoning behind its technology choices is
[`07-decision-log.md`](07-decision-log.md), and the Mermaid-source diagrams are
[`08-diagrams.md`](08-diagrams.md). It did not wait on Step 1b: Layer 1 gave it enough to
design a knowledge layer around, and the hypotheses carry their own confidence labels, which
is itself a design input.

The questions Step 2 had to answer, and where each is answered:

- **Knowledge layer.** What is ground truth, where does it live, and how does a fix get
  promoted from `TO VERIFY` to speakable? How does the known-issue feed stay current
  (`01` §8 Q5) — without it the agent cannot recognise a bad firmware build, which is the
  single most valuable thing a human engineer does on these calls.
  → `06` §4. The known-issue feed is **still open** — `06` §9.3 item 1, and `FW-03` stays
  escalation-bound until it exists.
- **Dialogue state.** How attempted steps, outcomes, the current hypothesis, and confidence
  are represented and carried across turns. M4 (no-repeat) is a hard constraint and it needs
  a data structure, not a prompt instruction.
  → `06` §3.3 (`DiagnosticState`, separate from conversation state) and §3.6 (step ontology).
- **Diagnostic policy.** How `02`'s ranked causes become a next-step choice. Cheapest
  discriminating step first, one action per turn, with an explicit stopping rule.
  → `06` §3.5.
- **Guardrails.** Where the destructive-action gate lives, where the "no unverified step"
  check lives, and how the safety rules in `01` §5 are enforced rather than merely prompted.
  → `06` §1.3 (three-layer clearance), §6.4 (destructive gate), §1.1 (output guard).
- **Voice pipeline.** ASR, turn detection, barge-in handling, TTS, and the latency budget
  (`01` M7). Confusable-token handling and read-back for models, versions, and numbers.
  → `06` §2 and §3.4.
- **Escalation.** The handoff payload — symptom, model, context, steps tried and their
  outcomes, hypothesis, reason — and the mechanics (warm transfer, callback, or ticket),
  which are still an open question (`01` §8 Q6).
  → `06` §5. The payload is settled; **which mechanic** is still open (`06` §9.3 item 2), and
  there is no warm transfer — the human joins the same room.
- **Model choice and cost.** Latency against diagnostic quality, and where a smaller model
  is sufficient.
  → `06` §8.3 and `07` D-06…D-09. Every Bedrock model row is `TO VERIFY` against the console.
- **Evaluation harness.** How `03` is actually run and scored, including judge validation.
  → `06` §7.3 (Harnesses A/B/C) and §7.4 (judge validation and the human baseline).

**Not in Step 2:** writing the agent. Architecture first.

---

## What is still unknown

The short version. Each doc carries its own longer list.

1. **Everything requiring a source.** Model list, firmware behaviour, menu paths, card
   specs, app names, error strings, every fix. Layer 1 now holds a labelled hypothesis for
   each of these; Layer 2 holds nothing. This blocks production, not the prototype.
2. **Whether the 7 categories and 28 entries match real calls.** We have no call-mix data
   (`01` §8 Q10). We may be missing mounting, GPS, and accessory issues entirely.
3. **Whether the cause rankings are right.** All ordered by inference, and they drive the
   agent's first question — so if they are wrong, the agent asks the wrong thing first.
4. **Whether the PROPOSED targets in `01` §6 are ambitious, trivial, or impossible.** No
   baseline exists. Do not quote them to anyone as commitments.
5. **Whether voice-only diagnosis is viable for the firmware category at all**, given it may
   require the caller to have a computer mid-call (`02` `FW-04`).
6. **Escalation mechanics, consent and recording law, and the destructive-action policy** —
   all three are organisational decisions, not engineering ones, and all three change the
   design (`01` §8 Q6, Q7, Q8).
