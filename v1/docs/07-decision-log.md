# 07 — Decision Log: Rove Voice Troubleshooting Agent

Status: **Step 2 record. Design only. No code.**
Date: 2026-11-07
Companion to `06-architecture.md`. Every entry here is a decision that `06` makes; this
document is where the *reasoning* is kept so it can be audited, argued with, and reversed on
evidence rather than on memory.

---

## What this document is, and what it is not

`06` is the architecture. It is long, and a decision stated inside a long document is a
decision that gets re-litigated in six months by someone who cannot find the paragraph. This
log pulls every major choice out into one place and gives each the same four things:

1. **The decision** — what was chosen, and its status.
2. **The alternatives considered** — the real ones, with what each was actually good at.
   An alternative listed only to be dismissed is not an alternative, it is decoration.
3. **Why this one over the others** — the argument that decided it, not a restatement of
   the choice.
4. **The flip condition** — the evidence that would reverse it, where `06` §8 states one.
   Where it does not, the entry says so rather than inventing one.

**This document adds nothing to `06`.** Every decision, alternative, price, latency budget
and flip condition below is drawn from `06` — principally §8, plus §3 and §5 for the two
flow decisions. Where `06` marks something `TO VERIFY`, so does this log. Where `06` says a
number is a budget rather than a measurement, this log repeats that. Nothing here is
promoted, rounded up, or quietly firmed.

**Provenance of the vendor claims.** The 2026 framework landscape and the AWS prices quoted
below come from a research pass run by **Muse on 2026-11-07** (`06` §8 preamble). No web
access was used from `06`, and none was used from here. Every vendor claim is therefore
**second-hand and dated**, and is to be re-checked before any contract or commitment. Where
that research and an AWS console disagree, the console wins.

---

## The two governing constraints

Neither of these is an engineering decision. Both are inputs, and between them they decide
or constrain almost everything in the log.

### C-1 — This is a web-based voice assistant, not a telephonic system

**Source:** Hardik, 2026-11-07 (`06` §0.1).

The user opens a page in a browser, grants microphone permission, and speaks. Audio travels
over **WebRTC from the browser**. There is **no phone call, no SIP, no PSTN, no phone number
and no SIP trunk** anywhere in the design.

**What it forced.** `06` §8 was re-decided from scratch under this correction — a telephony
component is not a web component with a different label. §2's latency budget was rebuilt on
a browser leg instead of a carrier leg. The single largest consequence is **D-17**:
escalation stops needing a transfer primitive and becomes "admit a second participant to the
room", which in turn is the main justification for **D-02**.

**What it did not change.** The Rove facts in `05`, the taxonomy, and the clearance model.
The device, the issue list and what the agent is cleared to say do not care how the audio
arrives.

### C-2 — AWS models only, and only those AWS grants without asking

**Source:** Hardik, 2026-11-07 (`06` §0.2, §8 preamble).

No Bedrock model-access request. No support ticket to enable a model. A model that needs one
is **out of scope**, not merely deprioritised.

**What it forced.** The Anthropic models on Bedrock — Claude Sonnet, Claude Haiku, Claude
Opus — were `06`'s previous recommendation for the reasoning role and are **removed** under
this constraint (D-06). Every generative and embedding model in this log is an AWS-native
Amazon candidate chosen because it is the *most likely* to be default-enabled, and *most
likely* is a judgement rather than a fact — hence **every model row below is `TO VERIFY`**.

**What it does not bind.** The framework, the transport, the web stack, the database and the
orchestration library. Those are ordinary open-source and infrastructure choices (D-01,
D-02, D-12, D-13, D-14, D-15). **Amazon Transcribe (D-05) and Amazon Polly (D-10) are also
outside the Bedrock access question** — they are managed services governed by IAM
permissions, which is precisely why the ASR and TTS rows can be pinned rather than left
conditional. Whether the constraint reaches an in-process open-weights VAD is itself an open
question (D-03; `06` §9.3 item 12).

**The procedure this constraint obliges, before any model ID is written into code**
(`06` §8.3):

1. Open **AWS Console → Bedrock → Model access** in the **target region**.
2. **Record the actually enabled list in `06` §8.3**, with the date and region it was read.
   That list is a deployment fact and belongs in the design record.
3. If a model named below needs an access request, **do not raise one** — fall back to the
   next default-enabled Amazon model for that role and record the substitution.
4. If no default-enabled model can serve the turn-reasoning role, that is a **blocking
   finding for Hardik**, not an engineering workaround.

---

## Summary

| # | Decision area | Chosen | Status | Flip condition exists? |
|---|---|---|---|---|
| D-01 | Voice transport | WebRTC from the browser | Decided | Effectively none (§8.1) |
| D-02 | Voice agent framework | LiveKit Agents 1.0 (production target); Pipecat SmallWebRTC (spike + fallback) | Decided | Yes — three stated |
| D-03 | Voice activity detection | Silero VAD v5 | Decided, one reading to confirm | Yes — constraint reading |
| D-04 | Pipeline shape | Cascaded with a text chokepoint; **not** end-to-end speech-to-speech | Decided, deliberately | Yes — two stated |
| D-05 | ASR | Amazon Transcribe Streaming | Decided (pinned; no access request needed) | Yes — two stated |
| D-06 | LLM — turn reasoning | Amazon Nova Pro | **TO VERIFY** | Yes |
| D-07 | LLM — fast path | Amazon Nova Micro | **TO VERIFY** | Yes |
| D-08 | LLM — latency fallback | Amazon Nova Lite | **TO VERIFY** | Yes |
| D-09 | LLM — offline judge | Amazon Nova Pro, or Amazon Titan Text | **TO VERIFY** | Yes |
| D-10 | TTS | Amazon Polly, Neural engine, streaming | Decided (pinned; no access request needed) | Yes — three stated |
| D-11 | Embeddings | Amazon Titan Embeddings | **TO VERIFY** | Yes |
| D-12 | Vector store | Postgres + pgvector | Decided | Yes — two stated |
| D-13 | Orchestration | LangGraph `StateGraph`, no planner framework | Decided | Yes — two stated |
| D-14 | Backend | Python + FastAPI | Decided | Yes — conditional reserve |
| D-15 | Web UI framework | React (plain React before Next.js) | Decided | Yes — two stated |
| D-16 | Diagnostic flow | Deterministic state machine; 7-probe model-ID ladder; CONFIRMED / PROBABLE / UNKNOWN | Decided | Only by relaxing `01` §3 |
| D-17 | Escalation flow | Human joins the same web room/session; no SIP transfer | Decided | Yes — mechanic choice is open |

---

## D-01 — Voice transport: WebRTC from the browser

**Decision.** Audio travels between the browser microphone and our process over **WebRTC**,
Opus, 20 ms frames, DTLS-SRTP.
**Status.** Decided. `06` calls it "A, WebRTC, with no serious contest."
**Specified in.** `06` §8.1; consequences in §1.4.2, §2.1, §2.2 lines 1 and 9, §7.3, §7.5.

**Alternatives considered.**

| Alternative | What it was genuinely good at | Why it was not chosen |
|---|---|---|
| **B. Raw PCM over a WebSocket** | Trivially simple and visible end to end: `getUserMedia` → `AudioWorklet` → binary frames → our socket. No ICE, no TURN, no media server. | **It is re-implementing WebRTC, badly.** No echo cancellation, no jitter buffer, no packet-loss concealment, TCP head-of-line blocking stalling live audio, hand-written reconnection. Each is a solved problem being re-opened. |
| **C. Chunked HTTP upload** (`MediaRecorder` → POST every N ms) | Simplest possible plumbing; works through any proxy. | Chunk-quantised latency added to §2.2 line 1; no duplex path for agent audio; **barge-in is structurally impossible**. It is not a real-time transport. |
| **D. A phone call** | What the previous revision of `06` assumed. | Out of scope under **C-1**. And factually worse: lower audio bandwidth, no second channel, no screen, and a carrier leg we cannot measure. |

**Why WebRTC over the others.** The argument that decides it is **acoustic echo cancellation
with the true playout reference**. The browser's WebRTC stack does AEC, gain control and
noise suppression on the capture path, with the real reference signal, because playout and
capture are in the same process. Without that, the agent's own TTS reaches the VAD and
barge-in fires on itself — and the fix for that is to implement AEC, "at which point we have
chosen A with extra steps and no community" (`06` §8.1). B is the only option a reasonable
person would argue for and the argument dissolves there. C is not in the running for duplex
audio at all. Beyond AEC, WebRTC brings the adaptive jitter buffer, loss concealment and
congestion control that a laptop on domestic broadband beside a car actually needs, and the
2026-11-07 research names it the standard for real-time browser audio.

**What it costs us, accepted knowingly.** Signalling, ICE/STUN/TURN and a media path to
operate — unless a framework or hosted room service owns them (D-02). A **TURN relay must be
budgeted** for users behind restrictive NAT, and TURN costs bandwidth. Connection quality
becomes a first-class observable (`06` §7.5: RTT, jitter, loss, reconnections). And the test
harness must drive a **real peer connection** rather than splice audio in behind it — Harness
C measures the transport, so a harness that bypasses the transport is measuring a different
system (`06` §7.3).

**Flip condition.** `06` states effectively none: *"nothing short of the browser deprecating
WebRTC."* The one case that genuinely re-opens the question is a client that is not a browser
— a native mobile app or an embedded device. Note that even then, **everything above §2.2
line 1 is unchanged**, which is the point of keeping the transport boundary clean.

---

## D-02 — Voice agent framework: LiveKit Agents 1.0, with Pipecat as the spike and the fallback

**Decision.** **LiveKit Agents 1.0 as the production target**, chosen primarily for the room
model rather than for the pipeline. **Pipecat SmallWebRTC is the Phase 2b/3 spike and the
documented fallback** — not a discarded option.
**Status.** Decided, with a Phase 3 exit criterion attached (see below).
**Specified in.** `06` §8.1.1; build sequence in §9.1 Phases 2b and 3.

**Alternatives considered.**

| Alternative | What it was genuinely good at | Why it was not chosen as the production target |
|---|---|---|
| **B. Pipecat** (Python pipeline framework; SmallWebRTC transport runs a peer connection inside the Python process via `aiortc`) | **The lowest-operations path to a working browser voice agent**: one process, one dependency, no media server, no cluster. The pipeline shape maps cleanly onto `06` §2.1 and the processor boundaries are natural instrumentation points for §2.2. Excellent for a spike. | A peer connection inside the Python process is a **two-party construct**. Admitting a human support agent to the same session (D-17) means adding a media server anyway — which is the thing Pipecat was being chosen to avoid. `aiortc` in the GIL also puts media handling on the same interpreter as the agent logic. |
| **C. Ten Framework** (audio processing in C++, outside the Python GIL) | Genuinely faster where media-path jitter under Python dominates. The right answer *if* that turns out to be the problem. | **It optimises the 55 ms.** `06` §2.2 says lines 2, 6 and 7 are 78 % of the target median and the two transport lines together are 55 ms. C solves a problem we have not measured. Smaller ecosystem; more of the stack becomes ours to understand. |
| **D. No framework** — WebRTC and the pipeline written directly against the browser and the AWS SDKs | Total control; no abstraction to fight; every line of §2.2 visible. | We would own **echo cancellation, jitter handling and reconnection** — the same three things that sank transport option B in D-01, and "the exact three things that look cheap in week one and are still being fixed in month four." |

**Why LiveKit over the others**, in `06`'s own order of weight:

1. **Escalation is a hard requirement and the room model satisfies it directly.** D-17 says a
   human joins the user's existing session. In a room-based framework that is "admit a second
   participant". In a pipeline-with-embedded-peer-connection framework it is a
   re-architecture. *We are not choosing a framework for the happy path; we are choosing it
   for the handoff, because the handoff is the part that is expensive to retrofit.*
2. **Browser-first matters when the client is a browser.** Client SDK, permission handling,
   device switching and reconnection are the unglamorous majority of the work and are solved.
3. **Maturity.** The 2026-11-07 research puts it as the leading open-source WebRTC agent
   framework, which is the bar `06` §8's preamble sets: *mature and proven over new and
   interesting.*
4. **The plugin boundary is the right shape for C-2.** STT, LLM and TTS are swappable behind
   an interface — exactly the position the unresolved Bedrock access question leaves us
   needing.

**Why Pipecat is kept rather than discarded.** SmallWebRTC gets a real browser conversation
running in a single Python process with nothing to operate, which is the fastest honest way
to measure §2.2 lines 2, 6 and 7 against *our* audio and *our* users. `06` §9.1 Phase 2b
builds the spike there, keeps the diagnostic core (§3) behind an interface so it stays
framework-agnostic, and Phase 3 promotes to LiveKit for the room model.

**What the decision costs, honestly.** We run a media server, or pay someone to (`06` §9.3
item 13 — who runs it is Hardik's call). And we inherit an abstraction between our code and
the §2.2 component boundaries. Hence a **Phase 3 exit criterion: the 9-component latency
decomposition must actually be obtainable through the framework.** If it is not, §2.4's
degradation ladder cannot fire, and that is a genuine reason to reconsider.

**Flip conditions** (`06` §8.1.1, stated so the decision can be reversed on evidence):

- **To Pipecat** if escalation lands on callback/ticket only (`06` §9.3 item 2). The
  same-session join is the *whole* argument for LiveKit; without it, Pipecat's one-process
  simplicity wins.
- **To Ten Framework** only if measurement shows Python-side media handling dominating §2.2
  lines 1 and 9 **after** lines 2, 6 and 7 have been optimised. Not before. **That ordering
  is the decision.**
- **To no framework: never**, for this system, on this timeline.

---

## D-03 — Voice activity detection: Silero VAD v5

**Decision.** **Silero VAD v5** for frame-level voice activity detection, underneath the
context-dependent hangover and semantic endpoint classifier of `06` §2.3.
**Status.** Decided, with one reading of **C-2** to confirm.
**Specified in.** `06` §8.1.1 "Voice activity detection"; used in §2.2 line 2 and §2.3.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Energy-threshold VAD** | Trivial; no model; no dependency. | **Too crude for a car park or a kitchen — it will take an engine for speech.** The users in `01` §2 are beside a car, often with road and engine noise. |
| **The ASR vendor's own endpointing** | Nothing to run; already in the ASR stream. | **Opaque**, and `06` §2.3 needs the hangover to be *ours* to vary by dialogue state — 180–250 ms on a yes/no, 700–900 ms on an SSID read-back, 2,000 ms+ while the user walks to the car. §2.2 line 2 is **the single largest controllable line in the budget**; handing it to a vendor gives away the main lever. |

**Why Silero.** The 2026-11-07 research identifies it as the current default for this job. It
runs **in-process on CPU**, costs a frame of latency, and — decisively for D-02 — is
**supported by both LiveKit Agents and Pipecat**, so it survives the framework flip
conditions intact. Choosing it does not re-open if the framework decision does.

**The open reading, flagged rather than assumed.** Silero is open-weights, runs in our own
process, and calls no Bedrock endpoint. `06` reads **C-2** as governing the *Bedrock model
layer* — ASR, LLM, TTS — and not an in-process VAD. If Hardik reads the constraint more
broadly, the fallback is the ASR vendor's endpointing and §2.3 gets **materially worse**.
This is `06` §9.3 item 12 and it is explicitly "worth one sentence of confirmation".

**Flip condition.** A broader reading of **C-2** by Hardik. No technical flip condition is
stated.

---

## D-04 — Pipeline shape: cascaded, with a text chokepoint — not end-to-end speech-to-speech

**Decision.** **Cascaded, deliberately:** Transcribe → policy → Nova → output guard → Polly.
The 2026-11-07 research names **Amazon Nova 2.5 Sonic**, an end-to-end speech-to-speech model
on Bedrock (audio in, audio out, no transcript in the middle). It is **rejected for v1**.
**Status.** Decided, and listed in `06` §9.2 among the things deliberately *not* built.
**Specified in.** `06` §8.3 "The speech-to-speech question"; §9.2.

**Why this is a major decision and not a model choice.** The access question under **C-2** is
not what decides it. `06` puts the reason in one sentence:

> An end-to-end speech-to-speech model **removes the text chokepoint that the entire
> clearance model depends on.**

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **End-to-end speech-to-speech** (Amazon Nova 2.5 Sonic — default-access status itself `TO VERIFY`) | Fewer hops, lower theoretical latency, more natural prosody and turn-taking; no transcription error between the user and the model. | It has **no point at which a regex can refuse a firmware version, and no structured `step_id` to check against the ledger.** `06` §1.3 clears a step before it is spoken; §3.5 filters a candidate set; §4.5 requires a `chunk_id` citation on every device-specific claim; §4.6 blocks version-shaped tokens with a regex; the output guard is deterministic, pre-TTS, and **reads text**. M4 (no-repeat) and M5 (harmful advice) are **hard constraints** under `01` §3 — they are not achievable on a pipeline with no text in it. |

**Why cascaded, with the cost named.** We are paying latency for auditability. The research
puts a tuned cascaded AWS stack at **700–900 ms voice-to-voice**, and `06` §2.2's budget
(~860 ms target median) shows that is enough. `06` says it plainly: *"we would make the same
trade again."*

**Flip conditions.** Two, both stated:

- A speech-to-speech model that **emits a parallel structured text channel we can gate on**.
- A product decision to **downgrade M4/M5 from hard constraints to targets** — which `01` §3
  forbids, and which would be Hardik's call, not engineering's.

Worth re-checking in a year; not worth prototyping now.

---

## D-05 — ASR: Amazon Transcribe Streaming

**Decision.** **Amazon Transcribe Streaming**, pinned as the AWS-native default.
**Status.** Decided and pinned. It needs **IAM permissions, not a Bedrock model-access
request**, so nothing here waits on an approval under **C-2**.
**Specified in.** `06` §8.2; biasing vocabulary in §3.4.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **B. Self-hosted open-weights ASR** | No per-minute cost; **audio never leaves our boundary**, which directly helps the open consent/privacy question (`06` §6.3); tunable. | Real streaming and endpointing need work; GPU capacity to run; **accent robustness is the weak spot**, and `01` §2 names accents and non-native speakers as a standing constraint. |
| **C. Framework-bundled / third-party ASR plugin** | Zero integration — both LiveKit Agents and Pipecat ship STT plugins for several vendors. | **Fails C-2 unless the vendor is AWS.** Useful only as a swap-in if the plugin layer makes it free to try, and even then vocabulary-biasing support is usually the weakest part of a bundled plugin. |

**Why Transcribe.** It satisfies **C-2** outright with no approval gate; it offers **true
streaming partials**, which the speculative prefetch in `06` §2.1 depends on; and it supports
custom-vocabulary biasing for the tokens that actually matter here — `ROVE`, `R2-4K`, `R3`,
`DUAL`, `DUAL PRO`, the four SSID prefixes and `12345678`. Per the 2026-11-07 research it is
**about $0.60 per hour** of streaming audio, which at support-session scale is not a number
that decides anything.

**What is explicitly unmeasured.** Biasing behaviour on *our* confusables. `06` is firm that
the decisive evaluation is not headline word error rate but **(a)** vocabulary-biasing quality
on the ROVE vocabulary and **(b)** partial-emission latency, tested on a held-out set of the
`01` §2 confusables — `R2`/`R3`, `4K`/"forty", `SD`/`SB`, `DUAL` — recorded over road noise
and speakerphone.

**The note that outranks the vendor choice.** *No ASR will reliably separate "R2" from "R3"
over road noise.* That is why D-16 resolves model identity by **feature, never by name**.
Vendor selection reduces the error rate; **the architecture is what makes the residual error
harmless.** The web client adds a second, cheaper mitigation telephony could not have — the
user reads the transcript and types the string — but it does not replace the first, because
the user may be nowhere near the screen.

**Flip conditions.** **To B (self-hosted)** if the consent/privacy answer (`06` §6.3,
§9.3 item 4) requires audio to stay in-boundary, **or** if volume makes per-minute cost
dominate.

---

## D-06 — LLM, turn reasoning: Amazon Nova Pro

**Decision.** **Amazon Nova Pro** for the turn-reasoning role — understand the turn, extract
slots, rank the *legal* candidate set, phrase one step in spoken English.
**Status. TO VERIFY** in the target region. This is a console fact, not a document fact.
**Price (research, 2026-11-07).** $0.80 / $3.20 per 1M tokens in / out.
**Specified in.** `06` §8.3.

**Requirement this role has.** Fast time-to-first-token (§2.2 line 6 — 300 ms target median,
and one of the three lines making up 78 % of the budget), **reliable structured output**, and
good instruction adherence.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Claude Sonnet / Haiku / Opus on Bedrock** | `06`'s **previous recommendation** for this role. | **Removed, not deprioritised**, under **C-2**: the Anthropic models on Bedrock require a Bedrock model-access request. |
| **One model for everything (Nova Pro across all roles)** | Simpler; fewer prompts to maintain; fewer failure modes. | Costs latency on the trivial classifications that happen several times per turn. `06`'s guidance: worth it if the split adds more operational complexity than it saves milliseconds — **measure before splitting**. |
| **A smaller model for turn reasoning (Nova Micro or Nova Lite)** | Tempting: Micro is roughly **23× cheaper on input** than Pro, and faster. | **The scenarios that break are the ones the system exists for** — `03` Part 3: EVAL-23 (heat correlating with Wi-Fi drops), EVAL-24 (two symptoms pointing opposite ways), EVAL-25 (corruption and clock loss sharing a cause). `06`: use Nova Lite as the Tier-3 *latency fallback* (D-08), **not as the default**. |
| **Open-weights, self-hosted** | Removes per-token cost; keeps transcripts in-boundary; **sits outside the Bedrock access question entirely**, which makes it the natural escape hatch if the C-2 procedure reaches step 4. | Costs serving infrastructure, and **structured-output reliability needs careful evaluation** — the policy layer depends on well-formed step IDs and citations on every turn. |
| **Fine-tuning** | Would adapt the model to our task. | **Not now.** We have 30 written scenarios and **zero real transcripts** (`03`). Fine-tuning on our own invented utterances would tune to the wrong distribution. Revisit after real session data exists. |

**Why Nova Pro.** Under **C-2** the field is AWS-native Amazon models, and Pro is the one
whose stated profile matches the role's three requirements. `06` is careful not to overclaim:
it is *"the AWS-native Amazon model most likely to be default-enabled"* for this role, and
"most likely" is a judgement.

**The risk the model swap actually carries — and it is not quality.** It is **structured
output**. The policy layer in `06` §3.5 consumes step IDs and citations as typed values, and
§4.5 drops any turn whose device-specific claim lacks a `chunk_id`. Whatever model the
console turns out to allow, **schema-conformance rate on the §3.6 step ontology is a Phase 1
exit criterion**, not a nice-to-have. Measure it on the 30 scenarios before trusting the
choice.

**The lever that matters more than the model choice.** A **stable cached prompt prefix**
(system instructions + taxonomy summary + state schema + output contract) with only the
`DiagnosticState` diff and retrieved chunks varying per turn. §2.2 line 6 is driven by prompt
length, and `06` calls this *"the largest single latency lever in the whole design."*

**Flip condition.** The console. If Nova Pro needs an access request, **fall back to the next
default-enabled Amazon model and record the substitution in `06` §8.3**. If no default-enabled
model can serve this role, that is a blocking finding for Hardik (C-2 procedure, step 4).

---

## D-07 — LLM, fast path: Amazon Nova Micro

**Decision.** **Amazon Nova Micro** for fast-path classification — triage, semantic
endpointing support, slot extraction, step-ID mapping.
**Status. TO VERIFY** in the target region.
**Price (research, 2026-11-07).** $0.035 / $0.14 per 1M tokens in / out.
**Specified in.** `06` §8.3.

**Requirement this role has.** Very low latency, cheap, narrow task. These jobs run several
times per turn and they are classifications, not reasoning.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Use Nova Pro for these too** (the one-model option) | One prompt surface, one failure mode, no routing logic. | Pays reasoning-tier latency on jobs that do not need it, several times per turn. |
| **Nova Lite** | Stronger than Micro at anything resembling ranking. | Reserved for D-08, where "materially better than Micro at ranking" is the actual requirement. For classification it buys nothing the budget notices. |
| **A non-LLM classifier** | `06` already uses one — the **semantic endpoint classifier** in §2.3 is explicitly *"a small, fast classifier, not an LLM call"*, because putting an LLM in the endpoint path would blow §2.2 line 6 twice per turn. | Not an alternative so much as a boundary: the fast model tier *supports* endpointing, it does not sit in the endpoint decision path. |

**Why Nova Micro.** `06` is blunt: *"these are small classification jobs that do not need the
reasoning tier."* The price spread is the supporting argument rather than the deciding one —
Micro is roughly **23× cheaper on input** than Pro, which makes the three-role split cheap to
justify. `06` immediately adds the warning that matters: that same spread *"makes it tempting
to push reasoning down a tier. Resist that on cost grounds alone"* (see D-06).

**Flip condition.** The console, as D-06. Substitute the next default-enabled Amazon model
and record it.

---

## D-08 — LLM, latency fallback: Amazon Nova Lite

**Decision.** **Amazon Nova Lite** as the Tier-3 rung of the latency degradation ladder
(`06` §2.4): when p95 exceeds 3.0 s, or the primary LLM is erroring, the turn routes here.
**Status. TO VERIFY** in the target region.
**Price (research, 2026-11-07).** $0.06 / $0.24 per 1M tokens in / out.
**Specified in.** `06` §8.3, invoked from §2.4 Tier 3.

**Requirement this role has.** Materially faster than Pro, **materially better than Micro at
ranking**. It has to still be able to choose among the legal candidate set.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Fall back to Nova Micro** | Cheapest and fastest rung available. | Not good enough at ranking to keep the ladder honest. The point of Tier 3 is to lose *some* reasoning quality, not all of it. |
| **No model fallback — skip Tier 3 and go straight to Tier 4 (scripted FSM)** | Simpler ladder; Tier 4 is still safe, since the questions come from `02` and the gates still run. | Loses ranking and adaptation entirely at the first sign of latency pressure, when a cheaper degradation is available. |
| **Make Nova Lite the default reasoning model** | Faster and cheaper on every turn. | Rejected in D-06: the correlation scenarios are where the agent earns its existence. |

**Why Nova Lite, and what it costs when it fires.** It sits in the gap the ladder needs. The
cost is **noticeable on the correlation scenarios — EVAL-23 / 24 / 25** — and `06` requires
the session to be **flagged in the trace** when Tier 3 fires, with those scenarios tracked as
the canary.

**The rule that governs the whole ladder, and therefore this decision.** Latency may be bought
with *reasoning quality*, and the quality loss must be visible in the eval harness. Latency
may **never** be bought with the no-repeat check, the destructive gate, the model-clearance
filter, the Tier-1 clearance filter, or the output guard — those total 30 ms at median and
removing them would not help anyway.

**Flip condition.** The console, as D-06.

---

## D-09 — LLM, offline judge: Amazon Nova Pro, or Amazon Titan Text

**Decision.** **Amazon Nova Pro**, or **Amazon Titan Text if it is the stronger
default-enabled option**, for the offline roles: the eval judge, taxonomy promotion review,
and handoff-summarisation QA.
**Status. TO VERIFY** in the target region — and the choice *between* the two is itself to be
settled against the console.
**Specified in.** `06` §8.3; the judge's validation protocol in §7.4.

**Requirement this role has.** **Maximum quality; latency irrelevant.** Nothing here is in a
user-facing turn, so none of §2.2 applies.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **The same model as turn reasoning, always** | One model to maintain. | Only coincidentally right. The requirement is different — quality at any latency — so the roles are allowed to diverge, and `06` leaves the slot open to whichever default-enabled model is stronger. |
| **Nova Micro / Nova Lite** | Cheap. | Wrong requirement entirely. Latency is free here and quality is the whole point. |
| **Humans only, no LLM judge** | `03` grades reasoning, and a human grader is the ground truth. | Does not scale to every prompt or policy change. `06` §7.4 keeps humans as the **validator** of the judge, not as the judge. |

**Why an offline tier exists at all, and the discipline attached to it.** `06` §7.4 does not
let the judge ship on assertion. The protocol is: **(1)** two human graders score all 30
scenarios and inter-rater agreement is measured (Cohen's κ) — *if humans do not agree, the
expected next step in `03` is ambiguous and `02`/`03` get fixed first*; **(2)** the LLM judge
is built and validated against the human labels, and ships **only above an agreed κ**;
**(3)** it is re-validated whenever `02`, `03` or the judge model changes; **(4)** a competent
human support agent is scored on the same 30 as a baseline, because without one *"a 70 %
model score means nothing"*.

**Flip condition.** The console, and the comparison between Nova Pro and Titan Text on the
judge-validation protocol above. Record the result in `06` §8.3.

---

## D-10 — TTS: Amazon Polly, Neural engine, streaming

**Decision.** **Amazon Polly, Neural engine, with streaming synthesis**, pinned as the
AWS-native default. **Polly Generative is a measured upgrade, not a default.**
**Status.** Decided and pinned. Like Transcribe, Polly is governed by **IAM permissions, not
Bedrock model access**, so no approval gates it under **C-2**.
**Price (research, 2026-11-07).** Neural **$16 per million characters**; Generative **$30 per
million characters**.
**Specified in.** `06` §8.4; used in §2.1, §2.2 line 7.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **A′. Polly, Generative engine** | Same service, same IAM position, **better prosody**. | Roughly **2× the character cost**, and its latency characteristics differ and are unmeasured. `06`: buy it only if Phase 3 shows Neural's prosody actually **costing comprehension** on digit strings and menu paths. |
| **B. Self-hosted neural TTS** | No per-use cost; **audio stays in-boundary**. | First-audio latency and prosody are usually worse; GPU capacity to run. |
| **C. Framework-bundled / third-party TTS plugin** | Zero integration via the LiveKit or Pipecat plugin layer. | **Fails C-2 unless the vendor is AWS** — and bundled options are typically **sentence-level rather than clause-level streaming**, which breaks the incremental synthesis `06` §2.1 depends on. |

**Why Polly Neural.** It satisfies **C-2** with no approval gate; it streams, which §2.2 line
7 requires (first audio on a *partial clause*, not a complete sentence); and it offers SSML
control for digit-by-digit and spelling modes, which this agent needs more than most — it
reads out `12345678`, SSIDs and menu paths to a stressed user standing beside a car. At $16/M
characters and a few hundred characters per turn, **engine choice is a quality decision long
before it is a cost one**.

**The two selection criteria that are easy to forget**, and which pinning the vendor does
**not** exempt from testing in Phase 3:

1. **Time to first audio on a partial clause**, not on a complete sentence.
2. **Cancellation latency** — barge-in that takes 300 ms to stop talking feels like being
   ignored. On a WebRTC leg, cancelling at the synthesiser is **not enough**: the browser's
   playout buffer must be flushed too (`06` §2.1).

**One mitigation the web client gives for free.** Anything hard to hear is **also on screen**
(`06` §1.4) — the SSID, the password, the menu path, the current step. That does not excuse
bad prosody, because the user may be at the car rather than the screen, but it does mean a
marginal prosody difference is **not worth 2× the character cost without evidence**.

**Flip conditions.** **To A′ (Generative)** if Phase 3 shows Neural mis-reading digit strings
in a way SSML cannot fix. **To B (self-hosted)** if audio must stay in-boundary. **To a
secondary provider** per `06` §7.6 if Polly is unavailable — and note §7.6's rule that a voice
change is audible and should be acknowledged in one line rather than ignored.

---

## D-11 — Embeddings: Amazon Titan Embeddings

**Decision.** **Amazon Titan Embeddings** for the dense half of the hybrid retrieval in
`06` §4.6.
**Status. TO VERIFY** that it is default-enabled in the target region.
**Specified in.** `06` §8.5 "Embeddings (§0 constraint)".

**Why this is a separate decision from the store.** `06` states it in one line: *"The store is
provider-agnostic; the embedding model is not."* D-12 chooses where vectors live; this
chooses what produces them, and only this one is bound by **C-2**.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **The next default-enabled Amazon embedding model** | The documented fallback. | Not chosen *against* — it is the explicit substitution path if Titan needs an access request. `06`: fall back and **record the substitution in §8.3's recorded list alongside the generation models**. |
| **A non-AWS embedding model** | Wider field; some are stronger per dollar. | **Fails C-2.** |
| **Self-hosted open-weights embeddings** | Outside the Bedrock access question; no per-call cost. | `06` does not develop this for embeddings specifically; the self-hosting escape hatch is discussed in D-06 for generation. Not chosen, and not ruled out. |

**Two consequences `06` insists on stating now rather than discovering later:**

1. **Embedding dimensionality is set by whichever model the console allows**, so the schema
   **must not hard-code it**.
2. **Changing the embedding model later means re-embedding the whole corpus and re-running
   the full eval set** — exactly as a corpus re-crawl does (`06` §7.6, `corpus_snapshot_date`).

**Therefore:** settle it from the console **before Phase 1 ingests anything** (`06` §9.1).

**Flip condition.** The console. If Titan Embeddings needs an access request, fall back and
record.

---

## D-12 — Vector store: Postgres + pgvector

**Decision.** **Postgres + pgvector**, holding the chunks *and* the source registry, the
clearance flags, the attempted-step ledgers, the orchestration checkpoints (D-13) and the
traces.
**Status.** Decided.
**Specified in.** `06` §8.5; retrieval in §4.6; registry in §4.4.

**The size of the problem, stated first.** The speakable corpus is **21 Tier-1 documents** —
6 manuals (260 pages), 3 official Rove pages, 12 Help Center articles — realistically a few
hundred chunks. `06` §4.1 treats that smallness as an architectural **advantage**: at this
size every chunk can be human-reviewed once, and the per-chunk clearance flags are
maintainable by hand rather than inferred.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **A. Embedded vector store** (in-process, file-backed) | **Zero network hop — directly helps §2.2 line 5.** Trivial to run, versioned with the code, and a few hundred chunks fit in memory many times over. `06` concedes outright: *"A would be faster."* | It optimises the wrong thing here (see below). Scaling and multi-writer concerns if the corpus ever grows by orders of magnitude. |
| **C. Managed vector service** | Scales; managed. | A network hop, **overkill at this size**, another vendor, and **metadata-filtering expressiveness varies** — which is disqualifying, because §4.6's filters are *mandatory, not optional*. |

**Why pgvector, and note that it is not a search argument.** `06` is explicit that the vector
search is not what decides it: **the source registry, the clearance flags, the attempted-step
ledgers, the orchestration checkpoints and the traces all want to be in the same transactional
store as the chunks.** §4.4's rule — *"no chunk without a registry entry is indexed"* — is
naturally a **foreign key**, not an application-level check. The network hop costs ~10–20 ms
of line 5, which the speculative prefetch hides anyway. The 2026-11-07 research puts pgvector
as the default for teams that do not need a dedicated vector database, which at a few hundred
chunks is exactly this team. `06` adds the honest closer: *"It is also the boring answer,
which at this corpus size is the correct one."*

**Why metadata filtering is load-bearing here, not relevance tuning.** `06` §4.6: the card
ceiling is **512 GB on R2-4K / PRO / R3 and up to 1 TB on DUAL / DUAL PRO**. An unfiltered
semantic search for "how big a card can I use" returns both, *and either answer is wrong for
half the line*. Likewise the reset button (the R2-4K family has one; **R3 does not**), the
Wi-Fi control, the band, and computer connectivity (**DUAL PRO cannot connect to a computer at
all**). **Filter first, then search. Never semantic-only.**

**Flip conditions.** **To A (embedded)** if line 5 is measured as a real contributor at p95
*and* prefetch hit rates are poor. **To C (managed)** only if the corpus grows past the point
where a human can review every chunk's clearance flags — **which would itself be a change in
the safety posture**, not merely a scaling event.

---

## D-13 — Orchestration: LangGraph `StateGraph`, and no planner framework

**Decision.** **LangGraph `StateGraph`** — *as an implementation of the explicit hand-written
state machine, not as a replacement for it.* The graph is **authored, never planned**.
**Status.** Decided, reversing the previous revision's "emphatically A" without weakening its
reasoning.
**Specified in.** `06` §8.6; the state machine it implements is §3.2.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **A. Explicit hand-written state machine** (typed states, typed transitions, pure policy functions) | **Exactly matches `06` §3.** Every transition testable without a model in the loop; the guarantees readable in one file; *"the fastest thing to debug at 2am."* | We write the plumbing: persistence, retries, timeouts, resume-after-reconnect, and concurrency with the audio loop. `06`'s change of mind is that **this plumbing is not small**, and two pieces of it are now first-class requirements of the web design. |
| **C. Agent framework with tools and a planner** | Fast to prototype; flexible. | **The planner is the thing we are deliberately removing.** An LLM that chooses the next action **cannot guarantee M4 or M5**. Fighting a framework to constrain it is worse than not having it. |
| **D. Workflow engine** (durable execution) | Durability, retries, visibility. | Designed for long-running workflows; **a sub-second conversational turn is the wrong shape for it**, and per-turn overhead lands in §2.2 line 4. |

**Why LangGraph over plain hand-rolled.** The central architectural commitment is
**unchanged**: `01` §5's hard constraints are not achievable on top of a planner that is free
to choose, so the LLM is called as a *function* at specific bounded points — understand,
extract, rank-within-legal-set, phrase — and **never as a controller**. What changed is the
recognition that two pieces of A's plumbing are now requirements:

1. **Resume after reconnect** (`06` §1.4.2). Browsers disconnect; laptops sleep; phones switch
   from Wi-Fi to cellular. `DiagnosticState` must survive a dropped peer connection, per turn,
   transactionally. **That is checkpointing**, and writing it ourselves is a week we do not
   need to spend. Checkpoints land in the same Postgres as everything else (D-12).
2. **Human-in-the-loop interrupt** (D-17 and the destructive gate, `06` §6.4). Both are "halt
   the graph, wait for an external decision, resume with it". Hand-rolled, *"that is the kind
   of state machine that works until two interrupts overlap."*

A `StateGraph` with explicit nodes and conditional edges **is** the explicit state machine of
`06` §3.2: the states are nodes, the ceilings are edge conditions, the policy filters are pure
functions inside a node. **Nothing about the guarantee model is delegated.**

**The rule that makes this safe — and it is a review rule, not a library setting.** *The graph
is authored, never planned. No node may be reached by model choice.* If a future change
introduces a model-chosen edge, that is a breach of `06` §1.3 and §3.1, and it is caught in
review and by M4/M5. `06` says writing it down is the point: **a constrained use of a flexible
library degrades silently unless someone states the constraint.** LangGraph's agentic features
include planner-shaped patterns we must not use; the discipline is ours to keep.

**What it costs.** A dependency with its own idioms and upgrade cadence, and a per-turn
checkpoint write landing in §2.2 line 4 — small, but **measured, not assumed**.

**Flip conditions.** **To A (plain hand-written)** if LangGraph's per-turn overhead shows up
in line 4, or if its idioms start dictating our state shape rather than the reverse — and note
the migration cost is bounded precisely because the graph is ours and `06` §3 is the portable
specification. **To C (planner framework)** only if the constraint set is relaxed to soft
targets, which would be a product decision, not an engineering one.

---

## D-14 — Backend: Python + FastAPI

**Decision.** **Python with FastAPI** for the diagnostic core, the knowledge layer, the agent
process and the eval harness.
**Status.** Decided, with a conditional reserve for the media edge.
**Specified in.** `06` §8.7.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **B. TypeScript / Node** | Strong async I/O story; **shares a language with the React UI** (D-15); LiveKit Agents ships a Node SDK too. | ML tooling is weaker, and **the eval harness, chunkers and judge drift to a second language — and those are where most of the actual code is.** |
| **C. Go** | **Best concurrency and latency predictability for the media path.** | Weakest ecosystem for the ML side; the team would be writing more glue. |

**Why Python.** The ecosystem argument is not vague here, it is a list: LangGraph (D-13) is
Python-first; LiveKit Agents and Pipecat (D-02) both ship Python SDKs; the eval harness,
chunkers and judges all want to be Python; and `scripts/html2txt.py` already is. The
2026-11-07 research names **FastAPI + LangGraph + Postgres/pgvector + React** as the mature
2026 stack, and `06` is explicit that *matching a well-trodden path is worth more than a
marginal technical edge.*

**Why FastAPI specifically.** The backend's **non-audio** surface is small and well-shaped for
it: mint the short-lived room token (`06` §1.4.2), serve the session record, expose the handoff
to the support console, and carry the traces.

**What it costs.** Concurrency for a real-time audio loop needs care — **async throughout, no
blocking calls on the media path.**

**Flip condition, stated as a reserve rather than a trigger.** Keep Go or Node in reserve for
the **media edge only**, and only if measurement shows the Python event loop is the
bottleneck — which §2.2 says it will not be, since lines 1 and 9 together are **55 ms**. That
reserve is credible because `06` §1.1 keeps a clean boundary between the WebRTC edge and the
diagnostic core; if the boundary ever has to be crossed, **D-02's Ten Framework option is the
shape that crossing takes.** *Start single-language; split only on evidence.*

---

## D-15 — Web UI framework: React

**Decision.** **React — and plain React before Next.js.**
**Status.** Decided. New in this revision of `06`; the previous one had no UI to choose for.
**Specified in.** `06` §8.8; what the UI renders in §1.4.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **B. Plain TypeScript, no framework** | Nothing to learn; smallest bundle; **the UI genuinely is small** — four panels at v1. | Every piece of state we would hand-roll — connection lifecycle, transcript list, step panel, ledger — is a thing React already solves, **and the UI grows**. We would also be first to integrate the browser SDK this way. |
| **C. Server-rendered HTML + a thin sprinkle of JS** | Simplest deployment; one language. | The page is a **live, bidirectional, stateful** surface — transcript, step, ledger and connection state all updating several times per turn. **This is the shape server-rendered pages are worst at.** |
| **D. A component library / design system first** | Looks finished sooner. | **Premature.** We do not yet know what the panels need to be; `03` Part 2 will change them. |

**Why React — and note that the UI did not decide this.** `06` is direct: *"The decision is
made by the voice framework, not by the UI."* LiveKit's browser SDK (D-02) is a first-class
React citizen — room connection, track subscription, device permissions and reconnection all
arrive as hooks rather than as code we write. Choosing anything else means **maintaining that
glue ourselves, for a client whose entire job is to be reliable.** Secondary: largest hiring
pool and the most prior art for this UI shape.

**Why plain React before Next.js.** Next.js is worth adopting when we need server-side
rendering, routing and an API surface in one place. For v1 the page is **one route behind
authentication**, so start with React and add Next.js when there is a second reason to.

**Three constraints on the UI that outrank any framework question** — `06` restates them in
§8.8 precisely because this is where they get violated:

1. **It may never become load-bearing** (`06` §1.4.1). *Voice-complete, screen-accelerated:*
   every diagnostic path must be completable by voice alone; the screen makes the same path
   faster and safer, **never different**. Enforced by **M10 — modality independence**, where a
   sampled answer is replayed through the other modality and the resulting next step must be
   identical. Target 100 %; a divergence is a **defect**, not a quality score.
2. **It renders `DiagnosticState`; it does not own it** (`06` §3.3). The browser's copy is a
   projection. A reload loses nothing.
3. **It is a cleared output surface** (`06` §1.3). The output guard runs on what is rendered,
   not only on what is spoken. **There is no "reference material" pane** — rendering an
   uncleared chunk would route around the entire clearance model.

**Flip conditions.** **To B (no framework)** if D-02 flips to a framework with no React
affinity *and* the UI is still four panels. **Never D** before Phase 4 — the pilot is what
tells us what to build.

---

## D-16 — Diagnostic flow: a deterministic state machine, a 7-probe model-ID ladder, and three confidence tiers

**Decision.** The diagnostic flow is a **deterministic state machine** that calls an LLM as a
bounded function. Model identification is a **first-class sub-dialogue** resolved by a
**7-probe discriminator ladder**, producing one of three confidence tiers — **`CONFIRMED` /
`PROBABLE` / `UNKNOWN`** — each of which unlocks a different amount of the corpus.
**Status.** Decided. It is the architectural centre of `06`, and the one thing D-13's library
choice is explicitly not allowed to change.
**Specified in.** `06` §3 entire; §1.1, §1.3; the step ontology in §3.6.

### D-16a — State machine, not an unrestricted LLM

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **An unrestricted LLM with tools** | Fast to build; flexible; handles the long tail of phrasings without a branch for each. | `01` §5 lists ten failure modes, and **six of them are *guarantees*** — repeating a failed step, destructive advice, hallucinated fix, phantom model, instruction overload, silent escalation failure. **A prompt instruction is not a guarantee.** `01` §3 calls no-repeat and no-harmful-advice hard constraints, and the `README` says it outright: *"M4 (no-repeat) is a hard constraint and it needs a data structure, not a prompt instruction."* |
| **Free-text matching of attempted steps** | No ontology to maintain. | Fails on exactly the cases `03` Part 2 exists to catch: the user says *"I formatted it in the camera"*, the agent proposes *"perform an in-camera format"*, **and a string comparison sees two different sentences.** Hence the canonical step IDs and families of §3.6 — `STEP.CARD.FORMAT_IN_CAMERA` and `STEP.CARD.FORMAT_ON_COMPUTER` are different steps in the **same** family, which is what EVAL-12 tests. |
| **One store for conversation and diagnosis** | Simpler; the transcript is already there. | The classic failure: the user said *"I already formatted it"* in turn 2, the sentence falls out of the context window, and the agent proposes a format in turn 9. `06` §3.3 keeps **two** stores and the policy layer **never reads the transcript** — *"if a fact is not in `DiagnosticState`, it does not exist for decision-making."* |

**Why this division.** The LLM does the three jobs an LLM is actually good at — understanding
what the user just said, ranking hypotheses against evidence, phrasing one step in plain
speech. The machine owns everything that must be **guaranteed**: which step is legal, whether
it has already failed, whether it is destructive, whether the model is confirmed, whether the
source is Tier 1, and when to stop. *The LLM never chooses what to do. It chooses among what
it is permitted to do, and it chooses the words.* Every `01` §5 failure listed as a hard
constraint lives in the deterministic layer; everything listed as quality lives in the model
layer.

**The filter chain this produces** (`06` §3.5), in order, before the LLM sees anything: source
clearance → model clearance → no-repeat (including **step family**, unless a non-empty,
user-audible `delta` exists) → safety → destructive gate → rank by discriminating power →
cap at **one action**. A step failing any filter is **not softened, hedged or reworded — it is
removed from the candidate set.** If the set empties, the agent says it does not know and
escalates, which is `01` §3.5's honest uncertainty *implemented as a data flow rather than as
a personality trait*.

### D-16b — The 7-probe model-ID ladder: identify by feature, never by name

**The problem it solves.** `05` §7 is quoted directly in `06`: *"Model identification is now
harder, not easier… 'Which Rove do you have?' is no longer one question."* There are **8 dash
cam rows** and **two R2-4K hardware revisions** (mini-USB + 250 mAh Li-ion vs USB-C +
supercapacitor), and "an R2-4K" is therefore not an identified device.

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Ask for the model name** | One question; what a human would do first. | **A spoken model name is the *least* reliable signal available** — it is exactly the token ASR mangles (`01` §2: `R2`/`R3`/"are two", `4K`/"forty"). A user saying "R2" is treated as **one weak signal**, never as identification. |
| **Ask again when it is unclear** | Costs nothing to try. | **Repetition over a noisy microphone reproduces the same error.** `06`: *"Asking the same question louder is not a strategy."* Resolve with probe 3 (touch vs buttons) or probe 2 (lens count) instead. |
| **Pattern-match `R` + digit** | Cheap and obvious. | **`RS2` and `RS4` are borescopes, not dash cams** (`05`). The pattern mis-routes them, so it is **explicitly forbidden**; any identification landing there routes to `OUT_OF_SCOPE` → human. |
| **Identify the model first, always** | Tidy; one less branch later. | **Wrong on the eval set.** `03` EVAL-01 is explicit that asking for the model first is *incorrect* there, because it does not change the next question. So `MODEL_ID` runs **lazily** — only when the policy layer finds the candidate steps diverge by model. That is a direct consequence of grading on the next step. |
| **An LED/beep evidence path** | Would help a user who cannot read a screen. | **Disproved, not deprioritised.** `05` found **zero occurrences** of Stealth or Horizon across all 21 Tier-1 files: every in-scope model has a screen. `06` §9.2 lists building it as *"work against a hypothesis that was disproved."* |

**The ladder, cheapest and most reliable first** (`06` §3.4) — SSID on the camera screen ·
lens count · touch-vs-buttons · USB-C-vs-mini-USB plug orientation · underside serial label ·
Wi-Fi band behaviour · in-box CPL filter and rear camera. Probe 1 is the strongest because the
string is **on the screen, read not recalled, and spelled** — and **typed, it is exact**, which
is the probe the web UI most improves. Probe 3 is *"the R2-vs-R3 answer"* and it never requires
the user to say "R2" or "R3" at all. Probe 4 is the hardware-revision split that `05` says
changes `PWR-04` and the reset path.

### D-16c — Three confidence tiers, each unlocking a different corpus

| Tier | What it requires | What it unlocks |
|---|---|---|
| **`CONFIRMED`** | **Two independent signals in agreement**, at least one not a spoken model name. Probe 1 alone counts *if* the user spells the suffix, because it is read from the device — and a **typed SSID counts on its own**, since the transcription error the two-signal rule defends against cannot occur. | Model- and revision-specific chunks. |
| **`PROBABLE`** | One signal. | **Family-level steps only** — steps identical across the members still in contention. With "one lens, buttons", R2-4K and R2-4K PRO are both live: the Emergency-Lock-2-seconds Wi-Fi control is identical on both and **may** be spoken; the card ceiling **may not**, because it differs across other candidates. |
| **`UNKNOWN`** | Nothing resolved, or the 4-turn `MODEL_ID` ceiling reached. | **Cross-model chunks only.** This is `01` §5's "phantom model" made structural. |

**Why tiers rather than a yes/no.** A binary would force a choice between refusing to help any
user who cannot be pinned to one row, and guessing. The middle tier is what lets the agent keep
working on the steps that are genuinely identical across the live candidates while still
refusing the ones that are not — and `06` §4.6 shows why that refusal is a **safety** control
rather than a relevance one (the 512 GB / 1 TB card ceiling, the reset button R3 does not have).

**Undocumented models.** `R1` (legacy) and `R4` (pre-launch) have **no manual in the corpus**.
Identification as either sets `clearance = none` and routes to escalation: *"the agent must not
reason about a device it has zero Tier-1 coverage for."* Whether they are in scope at all is
`06` §9.3 item 9 — a product decision.

**Flip condition.** None in the engineering sense. This design is reversible only by relaxing
`01` §3's hard constraints from constraints to targets, which `06` §8.6 and §8.3 both name as
a product decision rather than an engineering one.

---

## D-17 — Escalation flow: the human joins the same web room/session

**Decision.** **There is no transfer.** Escalation **admits a second participant to the room
the user is already in.** No SIP transfer, no bridge, no phone number, no second connection
for the user to establish.
**Status.** Decided as the architecture's target shape. *Which* mechanic is configured —
same-session join, callback, or ticket — remains open (`06` §9.3 item 2), which is why all
three sit behind one interface.
**Specified in.** `06` §5.3; triggers in §5.1; payload in §5.2.

**The principle, stated before the options.** *The user's session does not move.* Nothing for
them to re-explain, and **no window in which they are connected to neither party**. The session
ID, the transcript, the ledger and the `DiagnosticState` are continuous across the handoff
*"because nothing about the session changed except who else is in it."* `06` calls this **the
single largest simplification the web transport buys** (C-1).

**Alternatives considered.**

| Alternative | What it was good at | Why it was not chosen |
|---|---|---|
| **Same-session join** — *chosen* | Best experience; no re-explanation; the handoff panel is live from the moment the human arrives. | **Highest operational cost**: needs a live queue, an available human, and an agent-side console that can join a room — and **that console does not exist** (`06` §9.3 item 14). |
| **Callback** | Real, honest, and deliverable without a live queue. The agent says *"someone will get back to you — I'll take the best number or email."* | Session closes with an explicit non-closure. Needs a queue **and an SLA we can actually state.** Kept as the **first degradation**, not discarded. |
| **Ticket** | Lowest operational requirement; the handoff payload is simply filed. | **Weakest for a user standing at the car.** Kept as the second degradation. |
| **Transfer the user to a phone number** | What a telephony design would do. | **Explicitly not here.** It discards the session, **and the session is the asset.** Also out of scope under **C-1**. |
| **Ask the user to call a number themselves** | Zero integration. | Same objection, with the re-explanation cost moved onto the user. |

**Why the same-session join is the architecture's target, and what it decided elsewhere.** This
is the decision that chose the framework. `06` §8.1.1's first and heaviest reason for LiveKit
is that *"escalation is a hard requirement and the room model satisfies it directly"* — in a
room-based framework a human joining is "admit a second participant"; in a
pipeline-with-embedded-peer-connection framework it is a re-architecture. D-02's flip
condition is the mirror image: **if escalation lands on callback/ticket only, Pipecat wins.**

**Why the payload is not a message.** Because the human joins the same session, the §5.2
handoff is **not something sent somewhere — it is the panel the joining human sees**, rendered
from `DiagnosticState` at the moment they are admitted and live thereafter. The same record
serves the ticket and callback cases unchanged. `verbatim_symptom` is carried word-for-word,
because *"a paraphrase loses the detail that turned out to matter"* — EVAL-23's *"it's been
really hot today actually"* is the entire scenario. Two things the payload must **never**
contain: a declaration that the hardware is faulty (`01` §4 — the agent may *suspect*, a human
decides), and any warranty, returns-window or policy statement (`03` EVAL-29).

**Degradation is ordered and honest.** If no human is available for a same-session join, the
agent **says so** and offers the callback, then the ticket. It **never announces a join that
has not happened**, and it never silently downgrades — *"someone will come in now" followed by
nobody arriving is worse than "nobody's free right now."* What the agent says is **templated
per configured mechanic and never invented**; outside the published support window — the Help
Center lists **7 days/week, 9am–5pm PST** — it says what is actually true about when someone
will reach them.

**Escalation is a success mode, not a failure** (`01` §3.2). It fires from four sources
(`06` §5.1): cross-cutting triggers, per-entry triggers, structural triggers (empty legal
candidate set, `NO_MATCH`, `UNVERIFIED` entry, R1/R4/RS2/RS4/non-Rove, turn ceiling), and
**user request — immediate, with no troubleshooting toll**, because `03` EVAL-29 forbids
demanding a diagnostic session as the price of a handoff. The UI carries a permanent "talk to a
person" control, and **clicking it is the same event as saying it** (`06` §1.4.1). `FW-02`
escalates *in parallel with* the card-out question rather than after it, so the FSM supports
escalation as a **concurrent action**, not only as a terminal state.

**Flip condition.** `06` §9.3 item 2 — Hardik's choice of mechanic, hours, queue and SLA. All
three mechanics sit behind a single `EscalationChannel` interface **so the choice is
configuration, not a rewrite**. Three sub-questions ride with it: does the joining human speak
to the user or only read the transcript; does the agent stay in the room after the join
(`06` recommends **yes, muted, as the recorder**); and is the user told the human can see the
transcript — **which is a consent question, not a UX one** (`06` §6.3).

---

## What this log deliberately does not decide

Fifteen items in `06` §9.3 are **not engineering decisions** and are not recorded here as
though they were. Five of them would change an entry above:

| `06` §9.3 item | Decision it gates |
|---|---|
| **0 — Confirm the Bedrock default-enabled model list, and the target region** | **D-06, D-07, D-08, D-09, D-11.** Phase 0 and Phase 1 cannot write a model ID until the list exists and is recorded in `06` §8.3. |
| **2 — Escalation mechanics: same-session join, callback, or ticket; hours; queue; SLA** | **D-17**, and through it **D-02** — the same-session join is the main justification for LiveKit. |
| **12 — Does the AWS-models constraint cover an in-process open-weights VAD?** | **D-03.** The fallback is the ASR vendor's endpointing, and `06` §2.3 gets materially worse. |
| **13 — Who runs the media server: self-hosted LiveKit or the hosted service?** | **D-02**'s operational shape, the TURN bandwidth bill, and whether an audio-in-boundary answer is even available for **D-05** and **D-10**. |
| **14 — Is there a support-side console that can join a room?** | **D-17.** It does not exist, and it has an owner outside this project. |

The remaining ten (items 1, 3, 4, 5, 6, 7, 8, 9, 10, 11) shape the knowledge layer, the safety
policy, the targets and the corpus licence position rather than the technology choices. They
are listed in full in `06` §9.3 and are not duplicated here.

**One decision deferred by evidence rather than by authority.** `06` §9.3 item 10 asks whether
the sub-800 ms bar is a requirement or an aspiration. Our budget lands at **~860 ms**, and the
only line big enough to close the gap is the endpointer hangover — which is bought with
diagnostic accuracy on open-ended turns. `06`: *"Trading M3 for M7 is a product decision, not
an engineering one."* Report **800 ms as the aspiration, ~860 ms as the plan, and `01` M7's
1.2 s as the line that must not be crossed at the median.**

---

## How to use this log

- **Before re-opening a decision**, read its "why this one" and its flip condition. If the new
  argument is not the flip condition, it is a re-litigation, not new evidence.
- **When a flip condition is met**, change the entry here *and* the matching subsection in
  `06` — and say which measurement triggered it. A decision reversed without a recorded
  measurement is a decision made twice.
- **When the console is read** (C-2 procedure), record the enabled list in `06` §8.3 with date
  and region, then update D-06, D-07, D-08, D-09 and D-11 to match — including any
  substitution and what it replaced.
- **Treat every price and vendor claim as dated and second-hand.** They come from the
  2026-11-07 research pass, not from a vendor page we read.
- **Nothing in this log is a Rove fact.** The device, the taxonomy and the clearance model live
  in `02` and `05`, and this log does not touch them.
