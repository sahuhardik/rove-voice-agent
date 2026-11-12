# 06 — Architecture: Rove Voice Troubleshooting Agent

Status: **Step 2 — architecture design. Design only. No code.**
Date: 2026-11-07
Builds on `01-problem-definition.md`, `02-issue-taxonomy.md`, `03-golden-eval-set.md`,
`04-data-sources.md`, `05-step1b-verification.md`, and the corpus inventory in
`data/README.md`.

---

## 0. What this document is allowed to assume

### 0.1 Scope correction, 2026-11-07 (Hardik)

**This is not a telephonic system.** It is a **web-based voice assistant with a UI we
provide**. The user opens a page in a browser, grants microphone permission, and speaks.
Audio travels over **WebRTC from the browser**. There is **no phone call, no SIP, no PSTN,
no phone number and no SIP trunk** anywhere in this design, and nothing in this document may
assume one.

Everything that follows was re-derived under that correction. The earlier revision of this
document assumed an inbound phone call; §8 has been re-decided from scratch and §2's latency
budget rebuilt on a browser leg instead of a carrier leg. The Rove facts from `05` are
unchanged — the device, the taxonomy and the clearance model do not care how the audio
arrives.

**Terminology.** `02` and `03` were written for phone calls and say *caller* and *call*;
`01` has since been corrected to *user* and *session* alongside this document. This document
says **user** and **session**. They are the same person and the same interaction; quotations
from the earlier docs keep their original wording.

### 0.2 Established facts and what they force

Everything below is grounded in the Step 1 / Step 1b record. The facts this architecture is
built on, and the constraints they impose, in one place:

| Established fact | Where | What it forces in the architecture |
|---|---|---|
| **Voice-first, but not voice-only.** The user has a screen — ours — and can also click and type. The *device* still cannot be shown a menu path it will follow; the **user** can be shown one. | `01` §2 as corrected, §1.4 | **Voice-complete, screen-accelerated** (§1.4.1): every diagnostic path must be completable by voice alone, because the user may be hands-free beside the car; the screen makes the same path faster and safer, never different. One action per turn still holds. Latency is still a correctness property. |
| The user may be **hands-free, outdoors, or away from the screen** mid-session — walking to the car, holding the camera, reading its screen. | `01` §2 | The UI may never become load-bearing. Every prompt that renders a clickable affordance must also be answerable by speech, and the FSM must not branch on *which* modality answered it (§1.4.1, M10). |
| **8 dash cam rows** in the verified line: R1 (legacy, undocumented), R2-4K **mini-USB**, R2-4K **USB-C**, R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO, R3, R4 (pre-launch, undocumented). | `05` §"The verified Rove dash cam line" | Model identification is a first-class sub-dialogue with its own state, not a slot fill. Two of the 8 have no manual at all and must route to a human. |
| Two **R2-4K hardware revisions**: mini-USB + 250 mAh Li-ion + RESET button, vs USB-C + supercapacitor (~2 s hold) + RESET button. | `05` §M1 vs M2/M3, `PWR-04` | "An R2-4K" is not an identified device. `PWR-04` and the reset path diverge on revision. |
| **Every model has a screen.** Stealth and Horizon **REJECTED** — zero occurrences across all 21 Tier 1 files. | `05` §"Is any in-scope model screenless?" | The "read the screen aloud" evidence path is structurally safe. **No LED/beep parallel path is needed** — do not build one. |
| The cameras **speak**: failsafe announcement every 30 s when on but not recording; Wi-Fi connected/disconnected announcements; parking-mode alert. | `05` `REC-02`, §"screenless question" caveat 2 | A voice-native evidence channel exists. "What is it saying?" is a first-class probe, cheaper than "what does the screen say" for a user standing away from the car. |
| **28 taxonomy entries: 10 VERIFIED, 13 CORRECTED, 1 REJECTED (`SD-02`), 4 UNVERIFIED (`FW-03`, `APP-02`, `APP-04`, `PWR-02`).** | `05` §"Headline counts" | Clearance-to-speak is per-entry and per-chunk, enforced in code. The 4 UNVERIFIED entries are undiagnosable and escalation-bound today. |
| **30 eval scenarios**, 4 unconditional escalations, 26 negative controls. | `03` §"Coverage summary" | The harness must report escalation precision and recall together, never one alone. |
| Wi-Fi password **`12345678`** is published, is shown on the camera's own screen, and **is speakable**. | `05` §"Password `12345678` — VERIFIED" | Removes the `WIFI-03` prohibition. It is also perfectly speakable digit-by-digit, which matters on a noisy line. |
| **SSID prefixes known** per model: `ROVE_R2-4K_`, `ROVE_R2-4K-DUAL_`, `ROVE_R2-4K-DUAL_PRO`, `ROVE_R3_`/`Rove_R3_`; generic `ROVE_R***_******`. | `05` §"Wi-Fi SSID patterns" | The SSID is the **strongest voice-available model discriminator** we have, and it is on the camera screen. |
| **Card ceiling is model-dependent:** 512 GB on R2-4K, R2-4K PRO, R3; **up to 1 TB** on DUAL and DUAL PRO. Class 10 / U3 minimum everywhere. | `05` `SD-04` | A capacity answer is wrong unless the model is confirmed. Metadata filtering by model is not an optimisation, it is a safety control. |
| **Exactly one firmware version string exists anywhere in the corpus** — `ROVE-R2-4K-06102017 (First - Original Firmware)`, the shipping build of the mini-USB R2-4K. No current version is retrievable; `O1` renders them client-side. | `05` §"Firmware version numbers actually printed" | **The agent must never state, infer or confirm a firmware version.** This is an output-layer regex guard, not a prompt instruction. |
| **Four confirmed gaps with no taxonomy entry at all:** rear-channel (DUAL/DUAL PRO/R3), GPS / live speed, mounting (**mounts need ≥ 20° windscreen slope**), time-lapse "video plays in fast motion". | `05` §"What Tier 1 adds that the taxonomy has no entry for" | The router needs a fifth outcome besides the 7 categories: `KNOWN-GAP`. These are not unknown symptoms — they are known symptoms with no diagnostic branch yet. |
| `RS2` / `RS4` are **borescopes, not dash cams**. | `05` §"Not dash cams" | An `R`+digit pattern match mis-routes them. Explicit guard. |
| Support contact published: help@rovedashcam.com, 1-844-ROVE-CAM, **7 days/week, 9am–5pm PST**. | `04` §1.3 | Escalation availability has stated hours. `01` §7 assumption 1 can be partially tested against them. |
| **HARD CONSTRAINT — AWS models only, and only those AWS grants without asking.** No Bedrock model-access request, no support ticket to enable a model. | Hardik, 2026-11-07 | Any model that needs a Bedrock model-access request is **out of scope**, including the Anthropic models on Bedrock. §8.3 is restricted to AWS-native candidates likely to be default-enabled; §8.2 and §8.4 are pinned to Amazon Transcribe and Amazon Polly, which are managed services needing only IAM permissions. Every model choice in §8 is **TO VERIFY** against the console (§9.3 item 0). |

**What this document does not do:** invent a firmware version, a model, a menu path, a
latency measurement, or a vendor benchmark. Every number in §2 is a *budget* — an allocation
we intend to measure against — and is labelled as such. **It also does not assert which
specific Bedrock models are default-enabled in any region** — that is a console fact, not a
document fact, and §8 marks every model choice `TO VERIFY` accordingly.

**Sources for §8.** No web access was used *from this document*. The 2026 framework
landscape and the AWS prices in §8 come from a research pass run by **Muse on 2026-11-07**,
are attributed inline where they carry weight, and are second-hand: re-check them before any
commitment. Where that research and a console disagree, the console wins.

---

## 1. System overview

### 1.1 The shape of the thing

This is **not** an LLM with a microphone bolted on. It is a **diagnostic state machine** that
uses an LLM for the three jobs an LLM is actually good at — understanding what a user just said,
ranking hypotheses against evidence, and phrasing one step in plain speech — while the
machine owns everything that must be guaranteed: which step is legal to propose, whether it
has already failed, whether it is destructive, whether the model is confirmed, whether the
source is Tier 1, and when to stop.

The division is deliberate and it maps directly onto `01` §5. Every failure mode in that
table that is listed as "hard constraint" lives in the deterministic layer. Everything that
is listed as "quality" lives in the model layer.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │  BROWSER — React web UI (§1.4)                                   │
   │  mic capture · browser AEC/AGC/NS · Opus · 20 ms frames · playout│
   │  live transcript · current step · model + diagnostic state       │
   │  click-or-type fallback on every prompt — same session (§1.4.1)  │
   └──────────────────────────────────────┬───────────────────────────┘
                                         │ WebRTC, duplex (DTLS-SRTP) · data channel
                                         │ carrying UI state and click/type events ·
                                         │ short-lived token, minted server-side (§1.4.2)
   ┌──────────────────────────────────────▼───────────────────────────┐
   │  WEBRTC EDGE — one room per session (§8.1)                       │
   │  the agent joins the room as a participant; a human support      │
   │  agent can join the SAME room (§5.3) · jitter buffer · 16 kHz    │
   │  consent-gated recording tap (§6.3)                              │
   └──────────────────────────────────────┬───────────────────────────┘
                                         │ duplex audio frames (20 ms, real-time pace)
                         ┌───────────────▼──────────────────────┐
                         │          VOICE PIPELINE              │
                         │                                      │
     user audio ────────▶│  VAD ──▶ Streaming ASR ──▶ Endpointer│
                         │   │          │ (partials)      │     │
                         │   │          ▼                 │     │
                         │   │   ┌──────────────┐         │     │
                         │   │   │ SPECULATIVE  │◀────────┘     │
                         │   │   │  PREFETCH    │  (on partials)│
                         │   │   └──────┬───────┘               │
                         │   │          │ warm RAG candidates   │
                         │   ▼          ▼                       │
                         │  BARGE-IN   ┌──────────────────────┐ │
                         │  CONTROL ──▶│  TURN DISPATCHER     │ │
                         │   (kills    └──────────┬───────────┘ │
                         │    TTS)                │             │
                         │                        │ final text  │
                         │  ◀── incremental TTS ──┤             │
   agent audio  ◀────────│      (sentence-wise)   │             │
                         └────────────────────────┼─────────────┘
                                                  │
         ┌────────────────────────────────────────▼──────────────────────────┐
         │                    DIAGNOSTIC CORE  (deterministic)               │
         │                                                                   │
         │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
         │  │ SAFETY GATE │  │ DIALOGUE FSM │  │   DIAGNOSTIC STATE       │  │
         │  │ driving ·   │─▶│ states +     │─▶│   model · confidence ·   │  │
         │  │ smoke/heat ·│  │ transitions  │  │   change event ·         │  │
         │  │ footage ·   │  │ turn & loop  │  │   hypothesis stack ·     │  │
         │  │ scope       │  │ ceilings     │  │   ATTEMPTED-STEP LEDGER  │  │
         │  └─────────────┘  └──────┬───────┘  └────────────┬─────────────┘  │
         │                          │                       │                │
         │                  ┌───────▼───────────────────────▼─────────────┐  │
         │                  │        NEXT-STEP POLICY                     │  │
         │                  │  candidate steps from taxonomy ID           │  │
         │                  │   ─ no-repeat filter (hard)                 │  │
         │                  │   ─ model-clearance filter (hard)           │  │
         │                  │   ─ Tier-1 clearance filter (hard)          │  │
         │                  │   ─ destructive gate (hard)                 │  │
         │                  │   ─ cheapest-discriminator ranking          │  │
         │                  └───────┬─────────────────────────────────────┘  │
         └──────────────────────────┼────────────────────────────────────────┘
                                    │ legal candidate set (may be empty)
         ┌──────────────────────────▼────────────────────────────────────────┐
         │                    REASONING LAYER  (LLM)                         │
         │   understand turn · extract slots · rank the LEGAL candidates ·    │
         │   phrase ONE step in spoken English · never invents a step         │
         └──────────────────────────┬────────────────────────────────────────┘
                                    │ draft utterance + chosen step_id + citations
         ┌──────────────────────────▼────────────────────────────────────────┐
         │                    OUTPUT GUARD  (deterministic, pre-TTS)         │
         │   firmware-version regex · one-action check · citation check ·     │
         │   destructive-phrase check · "unknown must stay unknown" check     │
         └──────────────────────────┬────────────────────────────────────────┘
                                    │
         ┌────────────────┬─────────▼──────────┬──────────────────────────────┐
         │ KNOWLEDGE      │  ESCALATION        │  OBSERVABILITY               │
         │ Tier-1 index   │  handoff builder   │  per-turn trace · latency    │
         │ (speakable)    │  same-room join,   │  components · guard verdicts │
         │ Tier-2/3 index │  callback · ticket │  session outcome tags        │
         │ (never spoken) │                    │  eval harness feed           │
         └────────────────┴────────────────────┴──────────────────────────────┘
```

### 1.2 Component responsibilities

| Component | Owns | Must never |
|---|---|---|
| **Web UI (browser)** | Mic capture and playout, browser AEC/AGC/noise suppression, rendering the live transcript, the current diagnostic step, the confirmed model and the diagnostic state, and offering a click-or-type affordance for every spoken prompt (§1.4). | Be required. Every path it accelerates must also be completable by voice alone. Hold authoritative state — it renders state, it does not own it. |
| **WebRTC edge / room** | Session setup from a short-lived server-minted token, duplex audio over WebRTC, one room per session, admitting the agent and (on escalation) a human participant, jitter buffering, 20 ms framing, consent-gated recording tap. | Hold conversational state. Accept a long-lived credential from the browser. |
| **Voice pipeline** | VAD, streaming ASR, endpointing, barge-in, incremental TTS, speculative prefetch trigger. | Decide anything diagnostic. |
| **Safety gate** | Driving gate, hazard stop (smoke/swelling/burning smell), footage-preservation interrupt, out-of-scope detection. | Be bypassable by the LLM. It runs *before* the FSM on every turn. |
| **Dialogue FSM** | Which state the session is in, what the legal transitions are, turn and repeat-hypothesis ceilings. | Let the LLM choose the state. The LLM proposes; the FSM transitions. Branch on *which modality* answered a prompt (§1.4.1). |
| **Diagnostic state** | Model + revision + confidence, change event, hypothesis stack, **attempted-step ledger**, verification status of the current claim. | Be reconstructed from raw transcript. It is a typed record, separate from conversation history. |
| **Next-step policy** | Producing the *legal* candidate set and ranking by discriminating power. | Produce a step that is not in the step ontology. |
| **Reasoning layer (LLM)** | Understanding, slot extraction, ranking within the legal set, phrasing. | Introduce a step, a menu path, a spec, or a version that did not come from a cleared chunk. |
| **Output guard** | Last-line deterministic checks before audio is synthesised. | Be skipped under latency pressure. It is sub-millisecond. |
| **Knowledge layer** | Tier-1 speakable index, Tier-2/3 discovery index, source registry. | Serve a Tier-2 chunk into the speech path. Physically separate stores. |
| **Escalation** | Handoff payload construction and delivery. | Promise a mechanic or an SLA that has not been configured (`01` §8 Q6). |
| **Observability** | Per-turn traces, latency decomposition, guard verdicts, outcome tags, modality of each answer, eval feed. | Store raw audio or transcripts without a consent decision attached. |

### 1.3 The three-layer clearance model

Nothing reaches the user — spoken **or rendered on our screen** — that has not passed all
three. The screen is not a loophole: a step that may not be spoken may not be displayed
either, and the clearance filters run before the turn is split into audio and UI payload.

1. **Source clearance** — the chunk is Tier 1, has a source registry entry, and its taxonomy
   entry is `VERIFIED` or `CORRECTED` in `05`. `UNVERIFIED` and `REJECTED` are never spoken
   as a fix.
2. **Model clearance** — the chunk's `model_applicability` includes the *confirmed* model
   and hardware revision, or the chunk is cross-model.
3. **Policy clearance** — the step is not in the attempted-failed ledger, is not destructive
   without the three-part gate, and is a single action.

A step that fails any of the three is not softened, hedged or reworded. It is removed from
the candidate set before the LLM sees it. If the set empties, the agent says it does not
know and escalates — which is `01` §3.5, honest uncertainty, implemented as a data flow
rather than as a personality trait.

### 1.4 The web client

The user opens a page, grants microphone permission, and speaks. There is no phone call and
no phone number. What the page gives us that a phone call cannot is a **second channel that
is ours** — and the whole design question is how much weight that channel is allowed to carry.

**What the UI renders, continuously, during a session:**

| Panel | Contents | Why it is there |
|---|---|---|
| **Live transcript** | Both sides, turn by turn, with the agent's turns marked as they are spoken. ASR partials may be shown greyed; finals replace them. | The single cheapest fix for the `R2`/`R3` problem (`01` §2, §3.4): the user *sees* what we heard and can correct it without another spoken round-trip. |
| **Current diagnostic step** | The one action being proposed, in text, exactly as spoken — plus the sub-step index if the step was interrupted. | `01` §2, "user cannot hold long steps in memory". The step stays on screen while they walk to the car. One action per turn still holds; the screen does not get a longer list. |
| **Model and diagnostic state** | Confirmed model + hardware revision and the confidence (`CONFIRMED` / `PROBABLE` / `UNKNOWN`), the current category, and the attempted-step ledger as a visible list. | Makes `01` §5's "phantom model" and "repeating a failed step" failures *visible to the user*, who is the best available auditor of both. "No, I never formatted it" is a correction we want cheaply. |
| **Click-or-type affordances** | A button per legal answer on closed questions (yes / no / "it says something else"), and a text field for strings the voice channel mangles — SSIDs, serial numbers, card markings, error text. | Confusable tokens stop being confusable. `01` §2's "no copy-paste" constraint is lifted *when the user is at the screen*, and only then. |
| **Escalation state** | Whether a human has been requested, and once requested, that they are joining this same session (§5.3). | The user is never told to call a number or wait for a different channel. |

#### 1.4.1 Voice-complete, screen-accelerated

**The rule: every diagnostic path must be completable by voice alone. The screen makes the
same path faster and safer, never different.**

This is not UI conservatism. `01` §2 holds: the user may be hands-free, outdoors, holding
the camera, reading its screen, or standing at the back of the car with the laptop indoors.
If the UI becomes load-bearing, the agent breaks exactly when the user is doing the thing
we asked them to do.

Three consequences, all enforced in code rather than in a prompt:

1. **Dual affordance.** Any prompt that renders a clickable or typable affordance must also
   be answerable by speech, and the spoken phrasing must stand alone — "is the red light
   blinking, or steady?" never "tap whichever one you see".
2. **Modality-blind FSM.** A click, a typed string and a transcribed utterance enter the turn
   dispatcher as the *same* event type, carrying `{value, modality, confidence}`. The FSM and
   the policy layer read `value`; they may not branch on `modality`. The trace records it, and
   §7.2's **M10** measures that the branch taken is identical either way.
3. **No context loss on switching.** Modality is per-answer, not per-session. A user who
   types the SSID in turn 4 and then speaks turn 5 has one session, one `DiagnosticState`,
   one ledger. There is no "text mode" to enter or leave, because a mode is a thing you can
   be stuck in. Typed input is **higher**-confidence than ASR for the fields §3.4 calls
   confusable, and the evidence record says so (`asr_confidence` becomes
   `modality: typed, confidence: 1.0`), which legitimately shortens the model-ID ladder.

The inverse also holds and matters more: **the screen may never carry a claim the voice
channel is not cleared to speak** (§1.3). Rendering an uncleared chunk "just as reference
material" would route around the entire clearance model.

#### 1.4.2 Session establishment and credentials

- The browser never holds a long-lived credential, and it never holds an AWS credential at
  all. The React app authenticates to our backend; the backend mints a **short-lived,
  single-room, single-identity token** (minutes, not hours) and returns it; the browser uses
  it to join exactly one room.
- One room per session. The agent process joins that room as a participant. The room is the
  unit that a human can later be admitted to (§5.3), which is why escalation needs no
  transfer primitive of any kind.
- **Audio is fed to the pipeline at real-time pace, in 20 ms frames.** That is what the
  browser produces and it is what the VAD, the endpointer and the barge-in detector are
  tuned against. It is stated here because the eval harness is where it gets violated:
  Harness C (§7.3) replays synthesised audio, and replaying it faster than real time
  produces endpointing and barge-in numbers that mean nothing. Injected audio is paced.
- Reconnection is expected, not exceptional — laptops sleep, phones switch from Wi-Fi to
  cellular. A re-join with the same session identity restores the session: `DiagnosticState`
  lives server-side, so a dropped connection costs the in-flight turn and nothing else.

---

## 2. The real-time voice pipeline

### 2.1 Flow

```
 t=0   user speaking ────────────────────────────────────────────────┐
       │                                                             │
       ├─ VAD marks speech onset (frame-level, ~20 ms frames)        │
       ├─ Streaming ASR emits partial hypotheses every ~100–300 ms   │
       │     │                                                       │
       │     └─▶ SPECULATIVE PREFETCH fires at ~60% confidence on a  │
       │          category-bearing partial ("card error", "won't     │
       │          connect", "won't turn on"): runs the metadata-     │
       │          filtered retrieval for the 2–3 most likely         │
       │          taxonomy IDs and warms the LLM prompt prefix.      │
       │          Discarded silently if the final transcript         │
       │          disagrees. Cost: wasted retrieval. Benefit: the    │
       │          whole RAG hop leaves the critical path.            │
       │                                                             │
 t=E   user stops ◀──────────────────────────────────────────────────┘
       ├─ ENDPOINTER decides end-of-turn (see 2.3)
       ├─ ASR flushes final transcript
       ├─ SAFETY GATE  →  FSM  →  POLICY  (deterministic, bounded)
       ├─ LLM streams tokens
       ├─ first clause complete  ─▶ OUTPUT GUARD ─▶ TTS synthesises chunk 1
 t=F   FIRST AUDIBLE RESPONSE  ◀── this is what M7 measures
       └─ TTS continues sentence-wise; barge-in may kill it at any point
```

**Barge-in.** The VAD runs continuously, including while the agent is speaking. On detected
user speech the TTS stream is cancelled within one frame and the playback buffer is flushed
— both server-side and in the browser, since audio already handed to the peer connection
will otherwise keep playing for the length of the jitter buffer. Critically — `01` §2 — the
agent **re-anchors rather than restarting**: the diagnostic state records exactly how far
through the proposed step it got (`step_id`, `sub_step_index`, `spoken_prefix`), so the
resume phrasing can be "sorry — you were saying?" followed, when appropriate, by continuing
from the un-spoken remainder, not from the top. The un-spoken remainder is still on screen
(§1.4), which is the one case where the browser leg is strictly better than a phone call.

**Echo and self-trigger.** This is the clearest win of the browser transport: the WebRTC
stack in the browser already does acoustic echo cancellation, gain control and noise
suppression on the capture path, and it does it with the true reference signal because
playout and capture are in the same process. We enable it and we do not rebuild it. On top,
the same hard rule as before: the server-side VAD ignores energy correlated with the
outbound stream. A user on laptop speakers beside the car is the normal case, not the edge
case — and browser AEC is tuned for exactly that geometry.

### 2.2 Latency budget: end of speech → first audible response

`01` M7 proposes **under ~1.2 s median**. The field has moved since that was written: the
research summarised in §8 puts **sub-800 ms first audio** as the bar the 2026 WebRTC voice
stacks hit, and puts a **tuned cascaded AWS stack (Transcribe → Bedrock → Polly) at
700–900 ms voice-to-voice**. Those are other people's measurements of other people's
systems, quoted as a reference point, not as our forecast.

The browser transport changes two lines of this table and only two: **1** and **9**. A
WebRTC leg from a laptop on domestic broadband to a region we choose is cheaper and far more
observable than a carrier leg — we can measure it end to end, and if it is bad we can see
why. Everything in the middle is unchanged, which is the honest headline: **transport was
never the problem.**

All three columns below are **budgets, not measurements** — no pipeline exists and nothing
has been built (`01` "What is still unknown"). They exist to make the trade-offs arguable
and to give the instrumentation something to compare against.

| # | Component | Best case | Target median | p95 ceiling | Notes |
|---|---|---:|---:|---:|---|
| 1 | Browser capture → WebRTC uplink + jitter buffer | 15 ms | 25 ms | 70 ms | Opus, 20 ms frames, DTLS-SRTP. Levers that are actually ours: deploy in the user's region, keep the jitter buffer adaptive-low for speech, and do not add a proxy hop. |
| 2 | **Endpoint decision (Silero VAD v5 hangover + semantic classifier)** | **150 ms** | **250 ms** | 650 ms | Still the single largest controllable line item, and still the one with a direct quality cost — see 2.3. |
| 3 | ASR final flush after endpoint | 40 ms | 80 ms | 200 ms | Streaming ASR has already transcribed the audio; this is finalisation and punctuation only. |
| 4 | Safety gate + FSM + policy filters | 5 ms | 20 ms | 50 ms | Pure in-process logic over a typed state record. Should never appear in a flame graph. |
| 5 | RAG retrieval **not hidden by prefetch** | 0 ms | 30 ms | 240 ms | 0 on a prefetch hit. 240 ms at p95 is the full cold path: embed → filter → hybrid search → rerank. |
| 6 | **LLM time-to-first-token** | **180 ms** | **300 ms** | 850 ms | Dominated by prompt length. Cached prompt prefix (system + taxonomy + state schema) is the lever. |
| 7 | **TTS time-to-first-audio** | **70 ms** | **120 ms** | 320 ms | Requires streaming synthesis that emits on a partial clause, not on a complete sentence. |
| 8 | Output guard | <1 ms | 5 ms | 10 ms | Regex and set membership. Never skipped. |
| 9 | WebRTC downlink + browser playout | 15 ms | 30 ms | 80 ms | Includes the playout buffer, which is also what barge-in has to flush (§2.1). |
| | **Total** | **~476 ms** | **~860 ms** | **~2.47 s** | |

Reading the table honestly:

- **Our target median lands at ~860 ms, which is ~60 ms over the 800 ms bar.** That is
  stated rather than fixed, because the only line big enough to fix it with is line 2, and
  line 2 is bought with diagnostic accuracy. A 150 ms hangover truncates users who pause
  mid-sentence to look at the camera, which costs M3 (`01` §2: a three-part question gets
  one answer). **Trading M3 for M7 is a product decision, not an engineering one** (§9.3
  item 10). Report 800 ms as the aspiration, ~860 ms as the plan, and 1.2 s — `01` M7 — as
  the line that must not be crossed at the median.
- The best-case column is reachable only when lines 2, 6 and 7 all land aggressively *at
  once*, on a cached prompt prefix, with a prefetch hit, on a good connection. It is a p25
  figure. Do not quote it as a target.
- Lines 2, 6 and 7 together are **78 %** of the target median. Everything else is noise. Do
  not spend engineering effort on lines 1, 4, 8 or 9 — and note that the two transport lines
  together (55 ms) are now small enough that moving them is not worth a sprint.
- p95 is ~2.5 s, past the point where a user starts clicking things. The browser gives us a
  mitigation a phone call did not: the UI can show "thinking" state and the partial
  transcript, which buys real patience. It does **not** buy permission to be slow — the
  filler policy below is still part of the design.

### 2.3 Endpointing, and why it is the hard problem

A fixed silence threshold cannot serve this session type. The users in `01` §2 pause to look
at a camera, to read a screen, to find a card, to answer a passenger. A 400 ms hangover cuts
them off; a 1,200 ms hangover makes the agent feel dead.

Design: **a hybrid endpointer with a context-dependent hangover**, set by the FSM state, not
globally. The frame-level voice activity detection underneath it is **Silero VAD v5**, which
is the 2026 default for this job and runs in-process on CPU (§8.1.1).

| Dialogue context | Hangover | Why |
|---|---|---|
| Yes/no confirmation ("is it plugged in?") | 180–250 ms | The answer is one word; waiting is pure latency. And on this one the UI usually answers first — a click short-circuits the hangover entirely (§1.4.1). |
| Model identification / read-back of a code or SSID | 700–900 ms | The user is reading characters aloud with natural pauses. Cutting them mid-string is the `R2`/`R3` failure in a new costume. Offer the text field in parallel; a typed SSID skips this line of the budget altogether. |
| Open symptom description (turn 1) | 600–800 ms | Let them finish. The first utterance carries the change event and the attempted steps. |
| User performing a physical action | 2,000 ms + explicit "tell me when you've done that" | They are walking to the car, away from the screen. Silence is not end-of-turn. |

The browser adds one signal a phone call does not have: **the user is typing.** Keystrokes in
the text field, or focus in it, suppress the endpointer's impatience the same way continued
speech does. Someone part-way through typing an SSID has not finished their turn.

Layer on top: a lightweight **semantic endpoint classifier** over the ASR partial, deciding
"is this a complete thought?" — which lets a confident "yeah it's on" close at 180 ms while
"it says… um…" holds. This is a small, fast classifier, not an LLM call; putting an LLM in
the endpoint path would blow line 6 twice per turn.

### 2.4 What to do when latency slips

A graded ladder, applied automatically on measured breach, logged every time. No step in it
is allowed to weaken a hard constraint.

| Tier | Trigger | Action | What it costs |
|---|---|---|---|
| **0 — Conversational cover** | Turn projected > 800 ms (prediction made at endpoint, from live component timings) | Emit a short, honest filler through TTS immediately: *"Let me check that."* Not a generic *"mmm"*. `01` M7 explicitly allows this. The UI shows the same state visually, which is free and does not consume a turn. | Nothing, if used sparingly. Becomes a tic if used every turn — cap at ~1 in 3 turns. |
| **1 — Shed the optional** | p95 > 2.0 s over a 20-turn window | Drop the reranker; cut retrieval `k` from 8 to 4; drop the semantic endpoint classifier back to fixed hangovers. | Slightly worse chunk ordering. Measurable in eval; acceptable. |
| **2 — Shrink the prompt** | p95 > 2.5 s | Switch to the compact prompt profile: diagnostic state + top-3 chunks only, taxonomy summary instead of full entries. | Reasoning quality on complex/multi-symptom scenarios (`03` Part 3). Track EVAL-21…27 pass rate as the canary. |
| **3 — Smaller reasoning model** | p95 > 3.0 s, or primary LLM erroring | Route the turn to the fast model tier (§8.3). | Noticeable on correlation scenarios (EVAL-23/24/25). Flag the session in the trace. |
| **4 — Degrade to scripted** | ASR, LLM or knowledge layer unavailable | FSM runs the taxonomy's own `Must ask` questions directly as templated speech **and as UI prompts**. No free-form generation. Still safe: the questions are from `02`, the gates still run. | No ranking, no adaptation. The session still progresses and can still escalate. |
| **5 — Escalate** | Two consecutive turns breach 4 s, or Tier 4 cannot run | Hand to a human in the same session (§5.3) with the partial handoff summary. Tell the user plainly that the connection is struggling. | Containment. Which `01` §6 M9 explicitly says not to optimise for. |

**The rule that governs the ladder:** latency may be bought with *reasoning quality*, and
quality loss must be visible in the eval harness. Latency may **never** be bought with the
no-repeat check, the destructive gate, the model-clearance filter, the Tier-1 clearance
filter, or the output guard. Those are cheap (line 4 and line 8 total 30 ms at median) and
removing them would not help anyway.

---

## 3. The diagnostic state machine

### 3.1 Why a state machine and not an unrestricted LLM

`01` §5 lists ten failure modes. Six of them — repeating a failed step, destructive advice,
hallucinated fix, phantom model, instruction overload, silent escalation failure — are
*guarantees*, and a prompt instruction is not a guarantee. `01` §3 calls no-repeat and
no-harmful-advice **hard constraints**, and the README for Step 2 says it directly: "M4
(no-repeat) is a hard constraint and it needs a data structure, not a prompt instruction."

So: the LLM never chooses what to do. It chooses *among what it is permitted to do*, and it
chooses the words.

### 3.2 States

```
                  ┌──────────────────────────────────────────────────┐
                  │  INTERRUPTS — evaluated before every transition  │
                  │  HAZARD_STOP · DRIVING_GATE · PRESERVE_FOOTAGE   │
                  │  OUT_OF_SCOPE · USER_REQUESTS_HUMAN              │
                  └──────────────────────────────────────────────────┘
                                      │ (any fires → leaves the main path)
  ┌─────────┐   ┌──────────────┐   ┌──▼───────────┐   ┌──────────────────┐
  │  GREET  │──▶│ SYMPTOM_     │──▶│ TRIAGE       │──▶│ MODEL_ID         │
  │ consent │   │ CAPTURE      │   │ → category   │   │ (3.3) may run    │
  └─────────┘   │ verbatim     │   │ → taxonomy ID│   │ in parallel or   │
                │ + change     │   │ → KNOWN-GAP? │   │ be deferred      │
                │   event      │   └──────┬───────┘   └────────┬─────────┘
                │ + already-   │          │                    │
                │   tried      │          └────────┬───────────┘
                └──────────────┘                   │
                                        ┌──────────▼────────────┐
                                        │ HYPOTHESISE           │
                                        │ rank causes from `02` │
                                        │ re-rank on change     │
                                        │ event (cross-cutting) │
                                        └──────────┬────────────┘
                                                   │
                              ┌────────────────────▼─────────────────────┐
                              │ SELECT_STEP  (policy, §3.5)              │
                              │ legal set empty? ──────────▶ ESCALATE    │
                              │ destructive? ──▶ DESTRUCTIVE_GATE ──┐    │
                              └────────────────────┬────────────────┘    │
                                                   │                ◀────┘
                                        ┌──────────▼────────────┐
                                        │ PROPOSE_STEP          │
                                        │ exactly ONE action    │
                                        └──────────┬────────────┘
                                                   │
                                        ┌──────────▼────────────┐
                                   ┌───▶│ AWAIT_OUTCOME         │
                                   │    │ long hangover; "tell  │
                                   │    │ me when you've done"  │
                                   │    └──────────┬────────────┘
                                   │               │ outcome recorded
                                   │    ┌──────────▼────────────┐
                                   │    │ EVALUATE_OUTCOME      │
                                   │    │ symptom gone?         │
                                   │    └───┬──────────────┬────┘
                                   │     no │              │ yes
                                   │        │              │
                                   │   ┌────▼──────────┐   │
                                   └───┤ update ledger │   │
                                       │ + hypothesis  │   │
                                       │ ceilings? ────┼───┼──▶ ESCALATE
                                       └───────────────┘   │
                                                   ┌───────▼─────────┐
                                                   │ VERIFY_RESOLVED │
                                                   │ user states     │
                                                   │ symptom is gone │
                                                   └───────┬─────────┘
                                                           │
                                       ┌───────────────────▼──────────────┐
                                       │ CLOSE  (resolved / non-fault /   │
                                       │ deferred-retest / not-closed)    │
                                       └──────────────────────────────────┘
```

**State table, with the ceilings that force termination** (`01` §5 "silent escalation
failure"; `02` cross-cutting triggers 1 and 2):

| State | Entry condition | Exit | Ceiling |
|---|---|---|---|
| `GREET` | Session opened, microphone permission granted, room joined | Consent disclosure delivered (§6.3) | 1 turn |
| `SYMPTOM_CAPTURE` | Greeting done | Verbatim symptom + change event + prior attempts captured, or user stops volunteering | 3 turns |
| `TRIAGE` | Symptom captured | Taxonomy ID or `KNOWN-GAP` or `NO_MATCH` assigned | 1 turn; `NO_MATCH` → `ESCALATE` (this is EVAL-28) |
| `MODEL_ID` | Needed for a model-specific step | `CONFIRMED` / `PROBABLE` / `UNKNOWN` | 4 turns, then `UNKNOWN` and model-agnostic only |
| `HYPOTHESISE` | Category known | Ranked cause list | — |
| `SELECT_STEP` | Hypothesis exists | One legal step, or empty set | Empty set → `ESCALATE` |
| `DESTRUCTIVE_GATE` | Selected step is destructive | Consent granted / refused | Refusal is final for that step |
| `PROPOSE_STEP` | Step cleared | Spoken | One action. Enforced by output guard. |
| `AWAIT_OUTCOME` | Step spoken | User reports, by voice or by clicking the step's outcome control | No turn limit; a 90 s silence prompts once |
| `EVALUATE_OUTCOME` | Outcome stated | Ledger updated | — |
| `ESCALATE` | Any trigger | Handoff built and delivered | — |
| `CLOSE` | Verified resolution, honest non-fault, or explicit non-closure | — | — |

**Global ceilings, any of which forces `ESCALATE`:**
- 2 next-steps attempted with the symptom unchanged (`02` cross-cutting trigger 1).
- The same top hypothesis survives 3 turns with no new information (trigger 2).
- 12 total diagnostic turns.
- The legal candidate set is empty.
- The current taxonomy entry's status is `UNVERIFIED` and no cross-model cleared step exists.

### 3.3 Conversation state vs diagnostic state

Two stores. Keeping them apart is what makes M4 enforceable.

**Conversation state** (append-only, for the LLM's understanding):
turn log, ASR confidence per turn, **the modality each answer arrived on** (§1.4.1),
barge-in events, interruptions, spoken prefix on an interrupted step, reconnections.

**Diagnostic state** (typed, validated, the only thing the policy layer reads):

```
DiagnosticState
  session_id                                                 # one web session, one room
  safety {
    driving: unknown | yes | no | deferred_at_turn_n
    hazard_flags: [smoke | burning_smell | swelling | heat_damage | exposed_wiring]
    footage_at_stake: none | wanted | insurance_or_police   # drives REC-01 preservation
  }
  device {
    model: one of the 8 rows | unknown | not_a_dashcam(RS2|RS4) | non_rove
    hw_revision: mini_usb | usb_c | n/a | unknown           # R2-4K only
    confidence: CONFIRMED | PROBABLE | UNKNOWN
    evidence: [ {signal, value, turn, modality, confidence} ]  # §3.4; modality per §1.4.1
    firmware_version: user_reported_string | unknown        # NEVER agent-generated
    card: {brand?, capacity?, speed_marking?, age?}
    power: {source: socket | hardwire_kit | usb_port | unknown, kit_cutoff_v?}
  }
  problem {
    verbatim_symptom: string                                # for the handoff, never paraphrased away
    category: one of 7 | KNOWN_GAP | NO_MATCH
    taxonomy_id: WIFI-01..VID-03 | null
    change_event: {type, when} | none_stated                # re-ranks everything (02 cross-cutting)
    hypothesis_stack: [ {cause_id, rank, confidence, turns_held} ]
  }
  ledger {                                                   # THE no-repeat structure
    attempted: [ AttemptedStep ]                             # rendered in the UI (§1.4)
  }
  clearance {
    spoken_claims: [ {claim, chunk_ids, tier, retrieval_date} ]   # audit trail
  }
  escalation { triggered: bool, reason_code, at_turn }

AttemptedStep
  step_id            # canonical ontology ID, NOT free text — see 3.6
  step_family        # e.g. FAMILY.DESTRUCTIVE.ERASE_CARD
  source             # user_volunteered | agent_proposed
  count              # "I've reset it twice" → 2
  outcome            # success | no_change | worse | not_attempted | unclear
  preconditions      # {card_present: true, power: continuous, ...}
  turn
```

The policy layer never reads the transcript. If a fact is not in `DiagnosticState`, it does
not exist for decision-making. This is what stops the classic failure where the user said
"I already formatted it" in turn 2 and the agent proposes a format in turn 9 because the
sentence fell out of the context window.

`DiagnosticState` lives server-side and is the thing the UI renders. That is deliberate in
both directions: the browser cannot mutate it except by answering a prompt, and a browser
that disappears mid-session does not take the session with it (§1.4.2).

### 3.4 Model identification: 8 models, 2 revisions, and the R2/R3 problem

This is the hardest sub-dialogue in the system and `05` §7 says so outright: *"Model
identification is now harder, not easier… 'Which Rove do you have?' is no longer one
question."*

**Principle: identify by feature, never by name.** A spoken model name is the *least*
reliable signal available — it is exactly the token ASR mangles (`01` §2: `R2`/`R3`/"are
two", `4K`/"forty"). A user saying "R2" is treated as **one weak signal**, never as
identification.

**Discriminator ladder, cheapest and most reliable first:**

| # | Probe | Splits | Reliability |
|---|---|---|---|
| 1 | *"Does the camera's screen show a network name — something starting with R-O-V-E? Read it out, or type it in the box."* | **Everything.** `ROVE_R2-4K_` / `ROVE_R2-4K-DUAL_` / `ROVE_R2-4K-DUAL_PRO` / `ROVE_R3_` (`05` SSID table) | **Highest.** The string is on the screen, it is read not recalled, and it is spelled. **Typed, it is exact** — this is the probe the web UI most improves. Costs one Wi-Fi-on step on some models. |
| 2 | *"How many camera lenses are there in total — just the one facing forward, or is there a second one, or a third?"* | 1 → R2-4K / PRO · 2 → DUAL / DUAL PRO · 3 → R3 (front/cabin/rear) | High. A physical count, immune to ASR. Renders as three buttons. |
| 3 | *"Do you change settings by tapping the screen, or by pressing buttons on the side?"* | Touch → **R3** · buttons → everything else | **High — and this is the R2-vs-R3 answer.** It never requires the user to say "R2" or "R3". |
| 4 | *"The cable that goes into the camera — does the plug go in either way up, or only one way?"* | Reversible → **USB-C revision** · one way only → **mini-USB revision** | Medium-high. **This is the R2-4K revision split** that `05` says changes `PWR-04` and the reset path. |
| 5 | *"On the underside there's a label with a serial number starting R2 — read or type what's printed there."* | Confirms family; `R2XXXXXXXXX` is the documented format (`05` `FW-02`) | Medium by voice, **high when typed**. Requires the camera in hand. |
| 6 | Band behaviour: did the phone see the network at all, and is the phone 5 GHz-capable | R2-4K is **2.4 GHz only**; DUAL / DUAL PRO / R3 are dual-band; PRO is listed 5 GHz | Low on its own; useful as corroboration. |
| 7 | *"Was there a second camera for the back window in the box, and a filter that clips over the lens?"* | CPL ships in-box on DUAL / DUAL PRO (`05` `VID-02`) | Low-medium, corroborative. |

**Confidence rules:**

- `CONFIRMED` requires **two independent signals in agreement**, at least one of which is
  not a spoken model name. Probe 1 alone counts as confirmed *if* the user spells the
  suffix, because it is read from the device — and a **typed** SSID counts on its own, since
  the transcription error the two-signal rule exists to defeat cannot occur.
- `PROBABLE` = one signal. Unlocks **family-level** steps only — steps identical across the
  members still in contention. Example: with "one lens, buttons", R2-4K and R2-4K PRO are
  both live; the Emergency-Lock-2-seconds Wi-Fi control is identical on both (`05`
  `WIFI-02`), so it may be spoken. The card ceiling may not be, because it differs across
  other candidates.
- `UNKNOWN` → cross-model chunks only. This is `01` §5 "phantom model" made structural.

**Specific guards:**

- **`R2`/`R3` is never resolved by asking again.** Repetition over a noisy microphone
  reproduces the same error. Resolve it with probe 3 (touch vs buttons) or probe 2 (lens
  count) — or, when the user is at the screen, by letting them read it off the transcript
  and correct it. Asking the same question louder is not a strategy.
- **ASR biasing.** The recogniser is given a hotword/phrase list: `ROVE`, `R2-4K`, `R3`,
  `DUAL`, `DUAL PRO`, `Emergency Lock`, `microSD`, `hardwire`, `supercapacitor`, the four
  SSID prefixes, and `12345678`. Post-ASR, a phonetic alias table maps the known confusions
  ("are two" / "R too" / "R2" → `R2?`, "forty" / "4K" → `4K?`, "do all" / "dual" → `DUAL?`)
  into *candidate* tokens carrying their own uncertainty — never into resolved values.
- **Non-dash-cam guard.** `RS2` and `RS4` are borescopes (`05`). Any identification landing
  there routes to `OUT_OF_SCOPE` → human, with a plain explanation. `R`+digit pattern
  matching is explicitly forbidden.
- **Undocumented models.** `R1` (legacy, named only in `M2`/`M3`) and `R4` (pre-launch) have
  **no manual in the corpus**. Identification as either sets `clearance = none` and routes
  to escalation. The agent must not reason about a device it has zero Tier-1 coverage for.
- **R2-4K PRO caveat.** Everything we hold about the PRO comes from product listings, not
  its manual, which was never downloaded (`05` §"What is still unknown" item 3). PRO-specific
  claims are treated as `PROBABLE` source confidence and the band/card facts carry a hedge.
  This is an open item for Hardik (§9.3).
- **Deferral.** Model ID is not always turn 2. `03` EVAL-01 is explicit: asking for the model
  first is *wrong* there, because it does not change the next question. The FSM runs
  `MODEL_ID` **lazily** — only when the policy layer finds that the candidate steps diverge
  by model. That is a direct consequence of grading on the next step.

### 3.5 Next-step policy

Input: taxonomy ID, hypothesis stack, diagnostic state, retrieved cleared chunks.
Output: a ranked **legal** candidate set, possibly empty.

```
candidates = steps_for(taxonomy_id) ∪ steps_from(cleared_chunks)

  ─ filter: SOURCE CLEARANCE     drop if chunk tier ≠ 1, or entry status ∈ {UNVERIFIED, REJECTED}
  ─ filter: MODEL CLEARANCE      drop if model_applicability ∌ confirmed model/revision
  ─ filter: NO-REPEAT            drop if step_id ∈ ledger with outcome ∈ {no_change, worse}
                                 drop if step_family ∈ ledger-failed families      ← EVAL-12
                                 UNLESS a non-empty, user-audible `delta` exists    ← 01 §3.3
  ─ filter: SAFETY               drop if driving gate active and step needs hands
                                  drop if footage_at_stake and step risks footage
                                 drop firmware DOWNGRADE always — never agent-initiated
  ─ gate:   DESTRUCTIVE          route through DESTRUCTIVE_GATE (§6.4)
  ─ rank:   DISCRIMINATING POWER expected information gain across the live causes,
                                 divided by user cost (turns, effort, risk)         ← 02 principle
  ─ cap:    ONE ACTION           the top candidate only; the rest stay queued
```

The "cheapest discriminating step, not the most common fix" principle from `02` is the
ranking function, and it is where the design most visibly differs from a retrieval bot. The
canonical example from `05` `SD-01`: the official photo-mode shutter test splits *card* from
*slot* on a single action, which is strictly better than reseating even though reseating is
the more obvious move.

**Re-proposal with a delta.** `01` §3.3 permits re-proposing a failed step *with a stated new
reason*. Implementation: the candidate carries a `delta` object naming the changed
precondition (`{precondition: "card_present", was: true, now: false}`), and the output guard
**requires** the spoken utterance to contain that distinction. "You reset it, but not with
the card out — that's a different test" passes. "Let's try resetting it again" does not, and
is rejected pre-TTS. The same text is what the UI renders, so the distinction is audible
*and* legible; the guard does not have a separate, laxer path for the screen.

### 3.6 The step ontology, and why free text cannot work

The no-repeat rule is only enforceable if "what the user already tried" and "what the agent
is about to propose" are the same kind of object. Free-text matching fails on exactly the
cases `03` Part 2 is built to catch — the user says "I formatted it in the camera", the
agent proposes "perform an in-camera format", and a string comparison sees two different
sentences.

So every step is a canonical ID with a family:

```
FAMILY.DESTRUCTIVE.ERASE_CARD
  STEP.CARD.FORMAT_IN_CAMERA
  STEP.CARD.FORMAT_ON_COMPUTER        ← different step, SAME family (EVAL-12)
FAMILY.DESTRUCTIVE.RESET_DEVICE
  STEP.DEVICE.RESTORE_DEFAULT_SETTINGS
  STEP.DEVICE.HARD_RESET_PINHOLE      ← R2-4K family only; R3 has no reset button
FAMILY.POWER_CYCLE
  STEP.DEVICE.POWER_CYCLE
  STEP.DEVICE.UNPLUG_REPLUG
FAMILY.APP_STATE
  STEP.APP.FORCE_CLOSE_REOPEN
  STEP.APP.RETRY_CONNECT_BUTTON       ← the Tier-1 correct first move (05 APP-01)
  STEP.APP.CLEAR_CACHE
  STEP.APP.REINSTALL
FAMILY.OBSERVE   (never destructive, never blocked by no-repeat)
  STEP.OBSERVE.READ_SCREEN_VERBATIM
  STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT   ← the 30 s "not recording" failsafe (05 REC-02)
  STEP.OBSERVE.READ_SSID
  STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST   ← card-vs-slot discriminator (05 SD-01)
```

The LLM's slot-extraction job on every user turn includes mapping volunteered attempts
onto these IDs. Ambiguous mappings are recorded as `unclear` with the verbatim text attached,
and `unclear` is treated as **attempted** for no-repeat purposes — fail safe, since
re-proposing a step the user may have already done is the exact behaviour `01` M4 forbids.
Because the ledger is on screen (§1.4), an `unclear` entry is also the cheapest thing in the
system to correct: the user can see we think they formatted the card, and say otherwise.

`FAMILY.OBSERVE` is deliberately exempt from the no-repeat block: asking someone to read the
screen again, after something has changed, is not repetition.

---

## 4. Knowledge layer and RAG design

### 4.1 Corpus

The speakable corpus is exactly what is on disk and verified in `05` — **21 Tier 1
documents**: 6 manuals (260 pages, extracted to `data/text/manuals/`), 3 official Rove pages
(`data/raw/official/`), 12 Help Center articles (`data/raw/help-center/`). Nothing else.

This is small. That is an architectural advantage, not a limitation: at this size, every
chunk can be human-reviewed once, and the per-chunk clearance flags in §4.3 are maintainable
by hand rather than inferred.

### 4.2 Chunking

Different source types need different strategies, and one rule overrides all of them.

**The overriding rule: a procedure is atomic.** The card-side firmware update (`05`
§"Firmware update paths") is format-in-camera → copy unzipped files → camera **powered and
OFF** → insert card → press Power once → red LED → **do not disconnect power** → it restarts
→ **format again**. A chunk boundary anywhere inside that sequence can surface "insert the
card and press power" without "the camera must be off" or without "do not disconnect". `02`
flags `FW-01` as *"High-risk entry: the wrong advice here destroys the device."* Procedures
are never split. If a procedure exceeds the chunk budget, the chunk exceeds the budget.

| Source type | Unit | Target size | Notes |
|---|---|---|---|
| Manuals (`M1`–`M6`) | One named manual section (`§LOOP RECORDING`, `§24-HR AUTO PARKING MODE`, `§Troubleshooting` row) | 200–400 tokens | Page range retained — `05` cites by page and the handoff/audit trail should too. Troubleshooting tables chunk **one row per chunk**, since each row is a self-contained symptom→action pair. |
| Official pages (`O1`–`O3`) | One H2/H3 section | 200–400 tokens | `O2`'s per-model Wi-Fi table is chunked **one row per model**, so metadata filtering can isolate a single model's SSID/band/control. |
| Help Center (`H:*`) | One article, or one numbered step-group within it | 150–350 tokens | `04` §1.3 already notes "each article = 1–3 chunks". Each is already a ready-made diagnostic procedure. |

Overlap: a one-sentence rolling header carrying model applicability and section name, so a
retrieved chunk is self-describing when read in isolation. No sliding-window overlap of body
text — with a corpus this small it buys nothing and doubles the duplicate-citation problem.

### 4.3 Chunk metadata schema

Every chunk carries all of this. A chunk missing any required field is **not indexed into the
speakable store**.

```
chunk_id              e.g. M3#LOOP_RECORDING#p46
text
doc_code              M1..M6 | O1..O3 | H:<name>          (the codes 05 uses)
source_path           data/text/manuals/...  |  data/raw/...
source_url            URL  |  null                         ← see 4.4
retrieval_date        2026-11-07
tier                  1 | 2 | 3                            ← only 1 is in the speakable store
provenance            crawler | operator_upload            ← 5 manuals are operator_upload
page_range            e.g. 46-47  |  null
section               "LOOP RECORDING — IMPORTANT"

model_applicability   [ R2-4K_MINI_USB, R2-4K_USB_C, R2-4K_PRO,
                        R2-4K_DUAL, R2-4K_DUAL_PRO, R3 ]    ← explicit, never "all"
                      (R1 and R4 appear in no chunk — that is correct, we have no manual)
hw_revision_specific  true | false
firmware_applicability { version: "unknown" }               ← single-valued; see 4.6

category              WIFI | FW | APP | REC | SD | PWR | VID | GAP
taxonomy_ids          [ WIFI-02, WIFI-04 ]
step_ids              [ STEP.WIFI.ENABLE_EMERGENCY_LOCK_2S ]

verification_status   VERIFIED | CORRECTED | UNVERIFIED | REJECTED   ← from 05, per entry
speakable             true | false                          ← the single gate (4.5)
destructive           true | false
safety_critical       true | false                          ← FW-01, FW-02, REC-01
expectation_gap       true | false                          ← REC-03, VID-01, VID-02, WIFI-05, PWR-02
```

### 4.4 The source registry, and the provenance hole

`04` §"Collection plan" item 5 is a requirement, not a nicety: *"every RAG chunk must carry
source URL + retrieval date + Tier. No chunk without a source may be spoken as a fix."*

The registry is a single table keyed by `doc_code`, holding `source_url`, `retrieval_date`,
`tier`, `provenance`, content hash, and licence note. Every chunk joins to it. Every spoken
claim records the chunk IDs it rested on, in `clearance.spoken_claims`, which is what makes
a post-hoc audit of "where did the agent get that from" a lookup rather than an
investigation.

**The hole, stated plainly:** 5 of the 6 manuals — `dc3831.pdf`, `User Manual For New
R2-4K.pdf`, `ROVE R2-4K User Manual.pdf`, `ROVE R2-4K Dual Dash Cam Instruction Manual.pdf`,
`B0F9SX3JB9.pdf` — were uploaded by hand by Hardik on 2026-11-07 and have **no source URL**
in `DOWNLOAD_LOG.txt` (`data/README.md`; `04` §"Manuals added manually"). Only the R3 manual
has a URL, from the Rove CDN.

Those five are the bulk of the 260 pages and the source of most of the verified facts in
`05`. Applying the rule literally would make almost nothing speakable.

**Proposed resolution** (needs Hardik — §9.3): add `provenance: operator_attested` as a
third class alongside `crawler` and `null`. It requires a one-time signed record per file —
who obtained it, from where, on what date — recorded in the registry. It is weaker than a
crawler-captured URL and the registry must show that difference, not hide it. Until that
record exists, these five are `speakable: true` **for the prototype only**, and the
production gate in §9.1 Phase 4 does not pass without it. Also unresolved: whether
`B0F9SX3JB9.pdf` is the same document as the failed `manuals.plus/asin/B0F9SX3JB9` fetch
(`data/README.md`) — the ASIN matches, the identity was never established.

### 4.5 The speakable rule

> **Only Tier 1 may be spoken as a verified fix.** (`04` §"How to use this file")

Implementation, in order of strength:

1. **Physical separation.** Tier 1 lives in the `speakable` collection. Tier 2 (Amazon / app
   store review corpora) and Tier 3 (comparison sites, YouTube, aggregators) live in a
   **separate store that neither the speech path nor the UI payload builder has a client
   for**. Not a flag, not a filter — a different connection. A filter bug is a plausible
   event; a missing client is not.
2. **Tier 2/3 has exactly two jobs**, neither of which reaches the user — in audio or on
   screen: symptom-language matching to help the router recognise user phrasing, and
   eval-scenario authoring
   (`03` says every utterance is currently written by us and should be replaced by real
   language). Their output into the live path is a **category hint with no text**, never a
   span of review text.
3. **Status gate.** Within Tier 1, `verification_status ∈ {UNVERIFIED, REJECTED}` sets
   `speakable: false`. That removes the four unevidenced entries — `FW-03`, `APP-02`,
   `APP-04`, `PWR-02` — and the rejected premise of `SD-02`, exactly as `05` requires.
4. **Citation requirement.** The LLM's structured output must name the `chunk_id`s backing
   any device-specific claim. The output guard drops the turn if a device-specific claim
   carries no citation. A step with no cleared chunk behind it becomes "I don't want to guess
   at that — let me get you to someone who can check" → escalate.

**What this costs, honestly:** `FW-03` (something broke after the update) is one of the
highest-value request types and it is **undiagnosable** under this rule, because there is no
known-issue feed (`01` §8 Q5; `05` §"What is still unknown" item 2). The agent's correct
behaviour on those sessions is to capture context and escalate. That is a known, accepted hole,
and it is the strongest single argument for the internal feed in §9.3.

### 4.6 Metadata filtering: model, firmware, category

**Filter first, then search. Never semantic-only.**

```
if device.confidence == CONFIRMED:
      model_filter = { model_applicability contains (model, hw_revision) }
elif device.confidence == PROBABLE:
      model_filter = { model_applicability ⊇ all still-live candidates }   # family-safe only
else:
      model_filter = { model_applicability ⊇ all 6 documented models }     # cross-model only

category_filter  = { category == triaged_category }  ∪  { cross-cutting }
status_filter    = { speakable == true }
tier             = implicit (separate store)

hits = hybrid_search(query, filters = ALL of the above, k = 8)
     = 0.5 · BM25(query + taxonomy_id + step vocabulary)
     + 0.5 · dense(query)
hits = rerank(hits)[:3]
```

Why model filtering is a **safety** control here, not relevance tuning: the card ceiling is
512 GB on R2-4K / PRO / R3 and **up to 1 TB** on DUAL / DUAL PRO (`05` `SD-04`). An
unfiltered semantic search for "how big a card can I use" returns both, and either answer is
wrong for half the line. Likewise the reset button (R2-4K family has one; **R3 does not**),
the Wi-Fi control (Emergency Lock hold vs touchscreen), the band (R2-4K is 2.4 GHz only),
and computer connectivity (**DUAL PRO cannot connect to a computer at all**).

**The firmware facet is deliberately degenerate.** There is exactly one version string in the
entire corpus and it is the 2017 shipping build of a discontinued revision (`05`). So:
`firmware_applicability.version = "unknown"` on every chunk; the facet exists so the schema
does not need migrating when a real feed arrives; and **no retrieval path, prompt, or
template may emit a version string**. The output guard carries a regex for version-shaped
tokens (`\b\d+\.\d+(\.\d+)?\b` near firmware vocabulary, and `ROVE-R\d-4K-\d{8}`) and blocks
the turn — and the same regex runs on the UI payload, because a version rendered on our own
page is the same false claim as a version spoken. The agent may only *ask* the user to read
theirs out — System Settings > Firmware Version, or the app's connected-camera screen
(`05`) — and the version it captures is stored as `user_reported_string`, never promoted.

### 4.7 The four known gaps

`05` confirms four symptoms with **no taxonomy entry**: rear-channel failure (DUAL / DUAL PRO
/ R3), GPS / live speed, mounting (the **≥ 20° windscreen slope** requirement), and
time-lapse "plays in fast motion". There is Tier 1 content for all four, and no diagnostic
branch for any of them.

They are handled as a distinct routing outcome, `KNOWN-GAP`, which behaves as:

- recognise the symptom and say so — the user gets acknowledgement, not a wrong category;
- surface the single Tier-1 fact if one closes the session cleanly (time-lapse: Time-Lapse
  Record is on → turn it off; mounting: the mount needs at least a 20° slope and will not
  hold on flat glass; R3 GPS: the GPS is in the magnetic mount, so a gap between mount and
  camera kills it);
- otherwise escalate with full context.

This is explicitly **not** "force it into the nearest category", which is the EVAL-28 failure
and the most damaging thing the agent can do (`03`). Writing proper taxonomy entries for
these four, plus guards for the other `05` finds (boot prompt with three options, hardwire
kit not detected, frozen screen, repeated on/off, random restarts attributed to non-ROVE
chargers), is Phase 2 work (§9.1).

---

## 5. Human escalation

### 5.1 Triggers

Escalation is a success mode (`01` §3.2), and it fires from four sources:

1. **Cross-cutting triggers** (`02`, all 28 entries): two steps attempted with no change;
   same hypothesis for a third turn; smoke / burning smell / swelling / heat damage /
   exposed wiring; footage needed for insurance, police or litigation where any step risks
   it; user driving; out of scope (billing, RMA, warranty, returns, non-Rove).
2. **Per-entry triggers** — each of the 28 entries carries its own.
3. **Structural triggers**: empty legal candidate set; `NO_MATCH` from triage; taxonomy entry
   is `UNVERIFIED`; model resolves to R1 / R4 / RS2 / RS4 / non-Rove; turn ceiling.
4. **User request.** Immediate, no troubleshooting toll. `03` EVAL-29 is explicit: do not
   demand a diagnostic session as the price of a handoff. The UI carries a permanent
   "talk to a person" control; clicking it is the same event as saying it (§1.4.1).

**Escalation-first entries.** `FW-02` (will not boot after update) escalates *in parallel
with* the card-out question, not after it (`02`). `REC-01` preserves the card first, then
escalates. The FSM supports escalation as a concurrent action, not only as a terminal state.

### 5.2 The handoff payload

The target is that the human never asks the user a question the agent already asked. The
`verbatim_symptom` field is carried word-for-word — a paraphrase loses the detail that
turned out to matter (EVAL-23's "it's been really hot today actually" is the entire
scenario).

Because the human joins the same session (§5.3), the payload is not a message sent
somewhere — it is **the panel the joining human sees**, rendered from `DiagnosticState` at
the moment they are admitted, and live thereafter. The same record serves the ticket and the
callback cases unchanged.

```
HANDOFF
  session_id · started_at · duration · agent_version · corpus_snapshot_date

  USER SAID (verbatim, turn 1)        "..."
  SYMPTOM SUMMARY                     one line
  CATEGORY / TAXONOMY ID              SD-01  (or KNOWN_GAP / NO_MATCH)

  DEVICE
    model + hw revision               R2-4K (USB-C revision)
    confidence + why                  CONFIRMED — SSID read "ROVE_R2-4K_…", single lens, buttons
    firmware                          user read "…" | not obtained        ← never agent-stated
    card                              brand / capacity / speed marking / age
    power                             socket | hardwire kit (cutoff V) | USB port

  CONTEXT
    change event                      firmware update, 2 days ago
    environment                       in car / at home / driving (deferred)
    footage at stake                  none | wanted | INSURANCE OR POLICE   ← red flag

  ALREADY TRIED  (the ledger, in order)
    1. STEP.DEVICE.POWER_CYCLE          ×10  user-volunteered     no change
    2. STEP.CARD.FORMAT_IN_CAMERA       ×2   user-volunteered     worked for ~2 days, recurred
    3. STEP.OBSERVE.READ_SCREEN_VERBATIM ×1  agent-proposed       "Memory Card Error" (typed)

  AGENT'S HYPOTHESIS
    top                               card at end of life — confidence MEDIUM
    ruled out and why                 seating (photo-mode shutter test passed → camera fine)
    NOT ruled out                     card slot assembly

  WHAT WAS SAID, AND ON WHAT AUTHORITY
    spoken claims + chunk_ids + doc_code + page + tier + retrieval date

  ESCALATION
    reason code                       TWO_STEPS_NO_CHANGE | SUSPECTED_HARDWARE | OUT_OF_SCOPE |
                                      LOW_CONFIDENCE | USER_REQUEST | SAFETY_HAZARD |
                                      UNVERIFIED_ENTRY | DRIVING_DEFERRED
    safety flags                      hazard / footage / driving
    recording + consent status        recorded: y/n · consent: obtained/declined/not-required
    transcript pointer                (subject to §6.3 retention policy)
```

Two things the agent must **not** put in the payload: a declaration that the hardware is
faulty (`01` §4 — the agent may suspect, a human decides), and any warranty, returns-window
or policy statement (`03` EVAL-29 — all `Unknown` and none of it ours to state).

### 5.3 Mechanics

**There is no transfer.** This is the single largest simplification the web transport buys,
and it is worth stating as a principle before the options: **the user's session does not
move.** Escalation admits a second participant to the room the user is already in. No
transfer primitive, no bridge, no second connection for the user to establish, nothing for
them to re-explain, and no window in which they are connected to neither party. The session
ID, the transcript, the ledger and the `DiagnosticState` are continuous across the handoff
because nothing about the session changed except who else is in it.

`01` §8 Q6 is still open — live handoff, callback, or ticket — and the design still does not
pick one. All three sit behind a single `EscalationChannel` interface so the choice is
configuration, not a rewrite:

| Mechanic | What the agent promises | What happens | Needs |
|---|---|---|---|
| **Same-session join** (the one the architecture is built for) | "I'm bringing someone in now — stay on the page." | The backend signals the support queue with the handoff payload; an available human joins the **same room** as a third participant. The agent announces the join, stops proposing steps, and drops to transcribing and recording the ledger. The human sees the §5.2 panel as they arrive. | A live queue, an available human, and an agent-side console that can join a room and render the handoff. Best experience; highest operational cost. |
| **Callback** | "Someone will get back to you — I'll take the best number or email." | Session closes with an explicit non-closure; the handoff payload becomes a queued work item. | Queue + an SLA we can actually state. |
| **Ticket** | "I've written this up and someone will be in touch by email." | Handoff payload is filed. | Ticketing integration. Weakest for a user standing at the car. |

Two mechanics that are explicitly **not** here: transferring the user to a phone number, and
asking them to call one. Both discard the session, and the session is the asset.

Degradation is ordered and honest: if no human is available for a same-session join, the
agent says so and offers the callback, and only then the ticket. It never announces a join
that has not happened (§7.6), and it never silently downgrades — "someone will come in now"
followed by nobody arriving is worse than "nobody's free right now".

What the agent says is **templated per configured mechanic** and never invented. If no
mechanic is configured, or the session is outside the published support window (the Help
Center lists 7 days/week, 9am–5pm PST — `04` §1.3), the agent says what is actually true
about when someone will reach them. `01` §7 assumption 1 — that escalation is available
during support hours — is testable against those hours and should be, before launch.

**What the same-room design still owes a decision on** (§9.3 item 2): whether the human
hears the user directly or only reads the transcript, whether the agent stays in the room
after the join (recommended: yes, muted, as the recorder), and whether the user is told the
human can see the transcript — which is a consent question, not a UX one (§6.3).

---

## 6. Safety, privacy, consent, destructive actions, driving

### 6.1 Hazard stop

Highest priority, pre-empts everything including an in-progress TTS turn. Triggered by
smoke, burning smell, swelling, deformation, heat damage, or exposed wiring (`02`
cross-cutting trigger 3). Behaviour: stop diagnosis immediately, instruct the user to
disconnect the device from power, escalate. No further diagnostic questions, no "let's just
check one thing first". The UI clears the current-step panel at the same moment — a hazard
stop that leaves "insert the card and press power" on screen is a hazard stop that failed.

Detection is keyword-and-classifier based on every user turn **and on typed input**, not
only at triage — `PWR-02` reaches it mid-session when a user mentions swelling after four
turns about heat.

### 6.2 The driving gate

`01` §2 and `02` cross-cutting trigger 5. A user who is driving is **deferred, not
diagnosed**. A browser does not make this go away: the session runs on a phone as readily as
on a laptop, and a phone travels.

- **Detection:** explicit statement ("I'm driving", "I'm on the motorway"), plus implicit
  cues (sustained road noise, "hang on, let me pull over"). An ambiguous cue triggers one
  direct question — *"Are you driving at the moment?"* — never an assumption either way
  (`01` §5: no inference from non-answers). **Do not infer "not driving" from the fact that
  the session is in a browser**, and do not infer it from a click either.
- **Behaviour when active:** every candidate step carrying `requires_hands: true` or
  `requires_device_access: true` is filtered out in the policy layer (§3.5) — this is a
  data filter, not a reminder in the prompt. What remains is information capture:
  symptom, change event, what they already tried, model by description, and what they *hear*
  (the camera's 30-second "not recording" announcement is audible while driving, which makes
  `STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT` one of the very few probes that survives the gate).
- **Close:** offer a callback, or hold the captured context so that **resuming the session
  later does not start from zero** — the session is a server-side record with a resumable
  identity (§1.4.2), so "come back to this page when you've parked" is a real offer and not
  a polite fiction.
- **Never:** "pull over so we can carry on." Whether to stop driving is the user's
  decision, and pressing for it is itself a safety risk.

### 6.3 Recording, consent and privacy

`01` §8 Q8 is open and this is a legal decision, not an engineering one. The architecture is
built so that the answer is configurable and so that the *unsafe default is impossible*:

- **Recording is off until a consent decision exists for the session.** The recording tap is
  at the WebRTC edge, on the server side of the room, and is gated on a per-session
  `consent_state`. No consent decision → no audio written to disk. A one-party/two-party
  jurisdiction matrix drives whether disclosure is announcement-only or requires an
  affirmative answer. Note what the web transport changes here: the **live transcript is
  rendered in the browser whether or not it is retained**, so "displayed" and "stored" are
  separate decisions and the consent gate governs storage, not display.
- **Disclosure happens in `GREET`**, before any diagnostic exchange, in one sentence, spoken
  *and* shown — a consent notice that only exists in audio the user may have missed is weak
  evidence of consent. A user who declines still gets full service: the diagnostic state
  record is kept (it is needed for the handoff), the audio and verbatim transcript are not
  retained.
- **A second consent surface exists at escalation.** A human joining the room can hear the
  user and read the transcript. That is a disclosure in its own right and the agent makes it
  before the join, not after (§5.3).
- **Two retention classes.** *Operational*: the handoff payload and outcome tag, retained as
  long as the support case needs. *Evaluation*: audio and transcripts for the eval corpus,
  which requires separate opt-in and a shorter retention clock, and which `01` §7 assumption
  8 already flags as subject to legal review. Note the dependency: `03` says the written
  utterances should be replaced with real transcripts, and that cannot happen until this is
  answered.
- **Data minimisation.** No account lookup, no PII lookup, no telemetry (`01` §4). Serial
  numbers, and any contact details taken for a callback, are identifiers: they go into the
  handoff payload, and are redacted by default from the evaluation corpus and from traces.
- **No recordings or footage are ever uploaded anywhere.** The agent is advisory only; the
  user performs every action on their own device (`01` §4). The web UI is deliberately
  **not** given a file-upload control for footage — it would be the obvious next feature
  request and it would drag the whole system into content handling it has no basis for.
- **Credentials never reach the browser.** The page holds a short-lived room token and
  nothing else (§1.4.2); no AWS credential, no corpus access, no model endpoint.

### 6.4 Destructive-action policy

Destructive classes, from `01` §5 and `05`:

| Class | Examples | Default |
|---|---|---|
| **Erases footage** | format card in camera, format on computer | Gated |
| **Erases configuration** | restore default settings, factory reset, pinhole hard reset | Gated |
| **Risks the device** | power-cycling during a firmware write; removing/inserting a card while powered **ON** (the manual says *"do NOT… only do so when it is turned OFF"* — `05` `REC-01`) | Blocked outright in the states where they are dangerous |
| **Never agent-initiated** | firmware **downgrade** | Permanently blocked. Not gated — blocked (`01` §5). |

**The three-part gate.** A destructive step may only be spoken when all three are present,
and all three are logged as structured fields, not inferred from the transcript:

1. **Cause** — a specific hypothesis this step tests or fixes, naming the taxonomy entry.
   "Let's just try formatting it" has no cause and fails the gate.
2. **Consequence, spoken first** — in plain words, before consent is requested. *"This will
   erase everything on the card, including anything you've saved."*
3. **Consent, explicit and affirmative** — a clear yes. Silence, "I suppose so", or a
   question is not consent; the agent re-asks once and otherwise treats it as refusal.
   A **click on an affirmative control counts as consent and is recorded as such**, with the
   modality stored — this is one of the few places where the UI genuinely strengthens the
   record rather than merely speeding it up. What it must never become is a pre-selected
   default, a single button the user taps to get past a dialog, or a consent that can be
   given before the consequence has been rendered.

**Preservation overrides the gate entirely.** If `footage_at_stake ∈ {wanted,
insurance_or_police}`, every footage-erasing step is removed from the candidate set, full
stop — there is no consent path. `REC-01` runs preserve-first (power down, remove card, set
aside untouched) *before* any diagnostic question, and `05` sharpens the urgency: the event
directory is capped at **30 % of the card**, and once it is full the camera **deletes the
oldest locked video** to make room. Locked is not safe. The agent says so.

**The `FW-01` interlock.** While a firmware update is believed in progress, the power-cycle
family is hard-blocked and the first spoken content addresses the user's proposed action —
because EVAL-22's user will unplug it during the pause. The documented behaviour is to
watch for the indicator (blinking red, or red/blue on the upper left) and wait for the camera
to restart by itself (`05` `FW-01`). The safe wait time is still not published, so the agent
asks for a full minute of observation rather than inventing a duration.

---

## 7. Reliability, observability and measurement

### 7.1 The distinction that matters

Some of `01` §6 are **targets** (aim at them, miss them sometimes, improve). Two are **hard
constraints** — M4 no-repeat = 100 %, M5 harmful advice = 0 — and those are not targets at
all. They are implemented as runtime invariants in §3.5 and §6.4. The metric does not make
them true; the metric proves the code works. **A non-zero M5 is a code defect, not a model
regression**, and it is handled as an incident.

### 7.2 Metrics

| Metric | Definition | Where it comes from | How enforced / measured |
|---|---|---|---|
| **Verified resolution rate** (M8) | User states the symptom is gone, in-session. An unconfirmed instruction is not a resolution. | `01` §3.1 | Session outcome tagging in `CLOSE`, with four distinct outcomes: `resolved_verified`, `non_fault_closed_honestly`, `deferred_retest` (explicit non-closure), `escalated`. Baseline unknown — establish first, then target (`01` §8 Q9). |
| **Escalation correctness** (M6) | Escalated when expected, not escalated when not. | `01` §3.2, `03` | Golden set: 4 unconditional escalations vs **26 negative controls**. **Precision and recall reported together, always.** An all-escalate agent scores 4/30 on recall-weighted correctness, not 4/4. |
| **No-repeat compliance** (M4) | Zero proposals of a step already `no_change`/`worse` in the ledger. | `01` §3.3 | Enforced by the policy filter. Measured by an automated transcript+trace check: every proposed `step_id` vs the ledger at that turn. **Target 100 %. Any breach is a P1 defect.** |
| **Harmful advice** (M5) | Destructive step without cause + consent + consequence; any step given to a driving user; any footage-risking step with footage at stake; any firmware downgrade. Counted on **both** output surfaces — spoken and rendered. | `01` §3.4 | Enforced by the destructive gate and the safety filter. Measured by automated check plus human audit of a sample. **Target 0.** |
| Device identification (M1) | Correct model+revision confirmed, or correctly marked `UNKNOWN` and handled model-agnostically | `01` M1 | Golden set + session audit. Note: correctly saying `UNKNOWN` **passes**. |
| Category accuracy (M2) | Correct category by end of turn 3 | `01` M2 | Golden set, labelled. `KNOWN-GAP` counts as correct where it is correct. |
| Next-step accuracy (M3) | The single next move matches `03`'s expected next step | `01` M3, `03` | Golden set, judged (§7.4). |
| Latency (M7) | End-of-speech → first audible audio | `01` M7, §2.2 | Pipeline instrumentation, decomposed by the 9 components of §2.2. Report median, p95, and the component breakdown — a single number hides which of lines 2/6/7 moved. Turns answered by click or typing are reported **separately**, not blended into the median; they are a different measurement and mixing them flatters the number. |
| Containment (M9) | Resolved without handoff | `01` M9 | **Report only. Do not optimise.** Optimising containment before resolution quality is measured rewards suppressing escalations. |

Three additions this architecture needs that `01` does not list:

- **Grounding rate** — proportion of device-specific claims carrying at least one cleared
  Tier-1 chunk citation, across both output surfaces. Target 100 %, enforced by the output
  guard, measured from traces.
- **Unknown-handling rate** — on the 4 `UNVERIFIED` entries and the `KNOWN-GAP` symptoms,
  how often the agent admits it cannot verify and escalates, versus producing something
  plausible. This is the direct measure of `01` §3.5.
- **M10 — modality independence** (new, and specific to the web client). For a sampled set of
  turns, the answer is replayed through the *other* modality — a spoken "yes" re-run as a
  click, a typed SSID re-run as a transcript — and the resulting next step must be
  **identical**. Target 100 %. This is the enforcement mechanism for §1.4.1's rule that the
  FSM may not branch on modality, and it is the metric that catches the UI quietly becoming
  load-bearing. A divergence is a defect, not a quality score; measured in Harness A, cheaply,
  because both modalities are just events.

### 7.3 Running the 30-scenario golden eval set

Three harnesses, in increasing cost and decreasing isolation. `03` is explicit that it grades
**the next step**, not the reply, and that no-repeat and safety are **pass/fail, not scored**.

**Harness A — text-only, single turn (the default loop).**
Feed the utterance plus `known context` as a pre-populated `DiagnosticState` (the "Tried:"
field becomes ledger entries — this is what makes the contextual block testable). Capture the
single next step the agent produces. Score the five axes. Runs in seconds, costs almost
nothing, catches most regressions. This is the loop that runs on every prompt or policy
change.

Harness A is also where **M10** runs: each scenario is scored once with the answer delivered
as a transcript and once as a click or typed string, and the two next steps must match.

**Harness B — scripted multi-turn.**
For the items `03` marks multi-turn (EVAL-23, EVAL-26, EVAL-27) plus any scenario whose
expected outcome branches (EVAL-07, EVAL-16, EVAL-17, EVAL-20, EVAL-21). A scripted responder
plays the user with deterministic replies per branch. Verifies that the agent takes the
branch its own question implies — the failure where an agent asks the right question and then
ignores the answer.

**Harness C — end-to-end spoken, through a real browser.**
Synthesised speech over the real pipeline, with added road noise, laptop-speaker
colouration, and accent variation. Two rules that are easy to get wrong and that invalidate
the results silently when you do: the audio is injected **at real-time pace in 20 ms
frames** (§1.4.2), and it goes **through an actual WebRTC peer connection** — a headless
browser or a native WebRTC client — not spliced in behind the transport. Endpointing,
barge-in and the whole of §2.2 lines 1 and 9 are properties of the transport; a harness that
bypasses the transport is measuring a different system. Two things only this harness can
measure:
- the **ASR degradation pass** `03` demands — "No ASR degradation yet… every utterance here
  is a clean transcript". Inject the specific corruptions `01` §2 names: `R2`↔`R3`,
  `4K`↔"forty", `SD`↔`SB`, clipped turns, mis-segmented turns, barge-in mid-instruction.
  The measurable target here is **not** "still gets it right" — it is "does not act on a
  mis-heard model", i.e. M1's `UNKNOWN`-handling branch fires.
- latency (M7) and turn-taking, which `03` correctly says this set does not test.

**Reporting.** Per-axis, per-part (simple / contextual / complex / escalation), never a
single aggregate — a single number lets a collapse in the contextual block hide behind the
simple block. Hard-constraint breaches are listed individually, with the trace, every run.

### 7.4 Judge validation

"Semantically equivalent next step" needs a grader, and `03` notes neither a validated judge
nor human-agreement measures exist. Plan:

1. Two human graders score all 30 for a candidate agent; measure inter-rater agreement
   (Cohen's κ). If humans do not agree, the expected next step in `03` is ambiguous and
   **`02`/`03` get fixed first** — `README` already calls these "design bugs worth fixing
   before any code exists".
2. Build the LLM judge (a stronger, offline model — §8.3) and validate it against the human
   labels. Ship it only above an agreed κ against humans.
3. Re-validate whenever `02`, `03` or the judge model changes.
4. **Baseline.** Score a competent human support agent on the same 30 (Harness A, written
   answers). Without it, a 70 % model score means nothing (`01` §8 Q9). This is cheap and
   should happen in Phase 1.

### 7.5 Observability

**Per turn**, one structured trace record: ASR final + confidence + alternates; **the
modality the answer arrived on**; the full `DiagnosticState` diff; triage decision; **the
candidate set before and after each filter, with the drop reason for every dropped step**
(this is what makes a no-repeat breach debuggable in one look); retrieved chunk IDs with
scores; LLM tokens in/out; the guard verdict on both the spoken and rendered payload; and
the 9-component latency decomposition.

**Per session**: outcome tag, escalation reason code, hard-constraint breaches, model
confidence trajectory, turn count, total duration, modality mix, **WebRTC connection quality
(RTT, jitter, packet loss, reconnections)**. The last one matters because it is the only way
to tell a slow pipeline from a bad network, and users will report both as "it's laggy".

**Alerts** (as distinct from dashboards): any M4 or M5 breach, any M10 divergence,
grounding-rate drop below 100 %, p95 latency ladder reaching Tier 3, knowledge layer
unavailable, escalation channel unavailable during published support hours, and a rise in
failed room joins — which is an outage the user experiences as a page that does nothing.

### 7.6 Reliability posture

| Failure | Response |
|---|---|
| ASR unavailable | Escalate immediately. There is no degraded mode for not hearing the user — but note the browser gives one partial mitigation a phone call could not: the session can continue by typing while we say plainly that the microphone path is down. That is a **degraded session, announced as such**, not a silent fallback to text. |
| LLM unavailable / timeout | Latency ladder Tier 3 → Tier 4 (scripted FSM questions from `02`'s `Must ask` fields) → Tier 5. |
| TTS unavailable | Secondary voice provider; the voice change is audible and should be acknowledged in one line rather than ignored. If no voice is available, the UI carries the turn and the agent says so in text. |
| Vector store unavailable | **No fallback to ungrounded generation.** Cross-model cached chunks for the top ~20 procedures serve a reduced set; anything else escalates. An agent that improvises when its knowledge layer is down is the hallucination failure mode on a timer. |
| WebRTC connection lost | The browser re-joins the same room with the same session identity; `DiagnosticState` is server-side, so the cost is the in-flight turn (§1.4.2). The UI shows the reconnection rather than freezing. Repeated drops in one session are logged and are an escalation trigger, not a retry loop. |
| Room / media edge unavailable | The page cannot establish a session at all, which the user experiences as a dead button. Fail loudly with a published support contact — `04` §1.3's address and hours — rather than a spinner. |
| Escalation channel unavailable | Tell the user the truth, capture contact details, create the handoff record for follow-up. **Never announce a join that has not happened** (§5.3). |
| Corpus snapshot changed | `corpus_snapshot_date` is stamped on every session and every handoff. A re-crawl re-runs the full eval set before it goes live. |

---

## 8. Technology choices — options, trade-offs, and what would change the decision

Every subsection below gives real alternatives and the condition under which the
recommendation flips. This section was **re-decided from scratch** under the §0.1 scope
correction: the previous revision chose telephony components, and a telephony component is
not a web component with a different label.

**What this section rests on.** A research pass was run by Muse on **2026-11-07** covering
the 2026 open-source voice-agent landscape and current AWS pricing. Its findings are used
here and are attributed where they are load-bearing. **No web access was used from this
document**, so every vendor claim below is second-hand from that pass, carries its date, and
is to be re-checked before any contract or commitment. Latency figures remain the §2.2
budget allocations — ours to hit or miss — not product claims.

**The bias, stated up front: mature and proven over new and interesting.** Every candidate
below is judged first on whether a team can run it in production in 2026 without becoming
its maintainer. This is a support system for consumers with a broken device; it is not a
venue for finding out whether something works.

**Governing constraint, repeated because it is easy to lose in a long section:** the model
layer uses only AWS models that AWS grants without asking (§0). That constraint binds the
*models*. It does not bind the framework, the transport, or the web stack — those are
ordinary open-source and infrastructure choices.

**Governing constraint (§0, from Hardik):** the model layer uses **only AWS models that AWS
grants without asking** — no Bedrock model-access request, no support ticket. That rules out
the Anthropic models on Bedrock, which this document previously recommended in §8.3. The
replacements below are AWS-native candidates chosen because they are the *most likely* to be
default-enabled; "likely" is not "verified", so each is marked **TO VERIFY**. Before any
build work in §9.1 Phase 0, open **AWS Console → Bedrock → Model access** in the target
region, record the actually enabled list in this document, and reconcile §8.3 and §8.5
against it. Amazon Transcribe (§8.2) and Amazon Polly (§8.4) are **managed services governed
by IAM permissions, not Bedrock model access** — they need no access request at all, which is
why the ASR and TTS rows can be pinned rather than left conditional.

### 8.1 Voice transport

The question is how audio gets from a browser microphone to our process and back, twice a
second, for several minutes, without the user noticing the machinery.

| Option | For | Against |
|---|---|---|
| **A. WebRTC** | The browser's native real-time audio path and, per the 2026-11-07 research, **the standard for real-time audio in the browser**. Opus at 20 ms frames, adaptive jitter buffer, packet loss concealment, congestion control — and, decisively, **acoustic echo cancellation with the true playout reference**, which is what makes barge-in work at all (§2.1). Survives network changes. Every serious 2026 voice-agent stack is built on it. | Signalling, ICE/STUN/TURN and a media path to operate — unless a framework or a hosted room service owns them (§8.1.1). TURN is needed for restrictive networks and costs bandwidth. |
| **B. Raw PCM over a WebSocket** | Trivially simple: `getUserMedia` → `AudioWorklet` → binary frames → our socket. No ICE, no TURN, no media server. Visible end to end. | **We would be re-implementing WebRTC, badly.** No echo cancellation (so barge-in self-triggers on our own TTS), no jitter buffer, no loss concealment, TCP head-of-line blocking stalling live audio, and reconnection written by hand. Every one of those is a solved problem we would be re-opening. |
| **C. Chunked HTTP upload** (`MediaRecorder` → POST every N ms) | Simplest possible plumbing; works through any proxy | Chunk-quantised latency added to §2.2 line 1, no duplex path for agent audio, and barge-in is structurally impossible. Not a real-time transport. |
| **D. A phone call** | What the previous revision assumed | Out of scope per §0.1. Also, factually, worse: lower audio bandwidth, no second channel, no screen, and a carrier leg we cannot measure. |

**Decision: A, WebRTC, with no serious contest.** B is the only alternative a reasonable
person would argue for, and the argument dissolves on echo cancellation: without AEC, the
agent's own voice reaches the VAD, barge-in fires on itself, and the fix is to implement AEC
— at which point we have chosen A with extra steps and no community. C is not in the running
for duplex audio.

**What would flip it:** nothing short of the browser deprecating WebRTC. If a future client
is not a browser at all — a native mobile app, an embedded device — the transport question
genuinely re-opens, but the pipeline above §2.2 line 1 does not change, which is the point
of keeping the boundary clean.

**Consequences we accept by choosing it:** a TURN relay must be budgeted for users behind
restrictive NAT; connection quality becomes a first-class observable (§7.5); and the test
harness must drive a real peer connection rather than splice audio in behind it (§7.3).

### 8.1.1 Voice agent framework — the decision that shapes the most code

WebRTC settles the wire. It does not settle who runs the VAD, who holds the peer connection,
who cancels TTS on barge-in, and who lets a second human into the room. Per the 2026-11-07
research, four shapes exist:

| Option | What it is | For | Against |
|---|---|---|---|
| **A. LiveKit Agents 1.0** | Per the research, **the leading open-source WebRTC agent framework** in 2026. Browser-first. Rooms, with the agent joining as a participant. Python and Node SDKs. A plugin model for STT / LLM / TTS. | The room model **is** our escalation design (§5.3): a human joins a room the same way the agent does, which turns the hardest remaining mechanic into a configuration detail. Self-hostable or hosted, so the operational decision is separable from the code decision. Browser-first means the client SDK, reconnection and device handling are solved. Mature enough to be the default choice, which is the bar §8's preamble sets. | A media server to run (or a hosted bill to pay). The plugin layer is an abstraction that will occasionally need to be reached around; we must keep the §2.2 component timings visible through it, which is a requirement to verify, not assume. |
| **B. Pipecat** | A Python **pipeline** framework: processors for VAD → STT → LLM → TTS composed in sequence. 100+ integrations. Its **SmallWebRTC** transport uses `aiortc` to run a peer connection **inside the Python process — no media server to operate**. | The lowest-operations path to a working browser voice agent: one process, one dependency, no cluster. The pipeline shape maps cleanly onto §2.1, and the processor boundaries are natural instrumentation points for §2.2. Excellent for a spike. | A peer connection in the Python process is a **two-party** construct. Admitting a human support agent to the same session (§5.3) means adding a media server anyway — which is the thing we would be choosing B to avoid. `aiortc` in the GIL also puts media handling on the same interpreter as the agent logic. |
| **C. Ten Framework** | Runs audio processing in **C++, outside the Python GIL**, for latency-critical work. | The right answer if media-path jitter under Python turns out to dominate §2.2. Genuinely faster where it counts. | Solves a problem we have not measured. Our budget says lines 2, 6 and 7 are 78 % of the median and the transport lines are 55 ms combined — C optimises the 55 ms. Smaller ecosystem; more of the stack becomes ours to understand. |
| **D. No framework** | WebRTC and the pipeline written directly against the browser and the AWS SDKs. | Total control; no abstraction to fight; every line of §2.2 is ours to see. | We own **echo cancellation, jitter handling and reconnection** — the exact three things the research names as the cost of this path, and the exact three things that look cheap in week one and are still being fixed in month four. Rejected for the same reason as transport option B. |

**Decision: A, LiveKit Agents 1.0, as the production target — chosen primarily for the room
model, not for the pipeline.**

The reasoning that decides it, in order:

1. **Escalation is a hard requirement and the room model satisfies it directly.** §5.3 says
   a human joins the user's existing session. In a room-based framework that is "admit a
   second participant". In a pipeline-with-embedded-peer-connection framework it is a
   re-architecture. We are not choosing a framework for the happy path; we are choosing it
   for the handoff, because the handoff is the part that is expensive to retrofit.
2. **Browser-first matters when the client is a browser.** The client SDK, permission
   handling, device switching and reconnection are the unglamorous majority of the work, and
   they are solved here.
3. **Maturity.** The research puts it as the leading open-source option in this category,
   which is the standard §8's preamble sets.
4. **The plugin boundary is the right shape for the §0 constraint.** STT, LLM and TTS are
   swappable behind an interface, which is precisely the position the unresolved Bedrock
   access question (§9.3 item 0) leaves us needing.

**What the decision costs, honestly.** We run a media server, or pay someone to. And we
inherit an abstraction between our code and the §2.2 component boundaries — so a Phase 3
exit criterion is that **the 9-component latency decomposition is actually obtainable
through the framework**. If it is not, §2.4's ladder cannot fire, and that would be a
genuine reason to reconsider.

**Pipecat is not discarded — it is the Phase 3 spike and the fallback.** SmallWebRTC gets a
real browser conversation running in a single Python process with nothing to operate, which
is the fastest honest way to measure lines 2, 6 and 7 against *our* audio and *our* users.
Build the spike there, keep the diagnostic core (§3) behind an interface so it is
framework-agnostic, and promote to LiveKit for the room model.

**Flip conditions, stated so the decision can be reversed on evidence:**
- **To B (Pipecat)** if escalation lands on callback/ticket only (§9.3 item 2) — the
  same-session join is the whole argument for A, and without it B's one-process simplicity
  wins.
- **To C (Ten)** only if measurement shows Python-side media handling dominating §2.2 lines
  1 and 9 *after* lines 2, 6 and 7 have been optimised. Not before. That ordering is the
  decision.
- **To D (no framework)** never, for this system, on this timeline.

#### Voice activity detection

**Silero VAD v5**, which the 2026-11-07 research identifies as the current default. It runs
in-process on CPU, costs a frame of latency, and is supported by both LiveKit Agents and
Pipecat, so it survives the flip conditions above. The alternatives are energy-threshold VAD
(too crude for a car park or a kitchen — it will take an engine for speech) and the ASR
vendor's own endpointing (opaque, and §2.3 needs the hangover to be *ours* to vary by
dialogue state, which is the single largest controllable line in the budget).

One point to confirm rather than assume (§9.3): Silero is open-weights and runs in our own
process, touching no Bedrock endpoint. We read §0's AWS constraint as governing the
**Bedrock model layer** — ASR, LLM, TTS — and not an in-process VAD. If Hardik reads it more
broadly, the fallback is the ASR vendor's endpointing and §2.3 gets materially worse. Worth
one sentence of confirmation.

### 8.2 ASR

| Option | For | Against |
|---|---|---|
| **A. Amazon Transcribe Streaming** — the AWS-native managed streaming ASR | Available on IAM permissions alone, **no Bedrock model-access request**, so it satisfies §0 outright; true streaming partials (which the speculative prefetch in §2.1 depends on); vocabulary / custom-vocabulary biasing for `ROVE`, `R2-4K`, `DUAL`, SSID prefixes. Per the 2026-11-07 research, **about $0.60 per hour** of streaming audio — at a support-session scale that is not a number that decides anything | Per-minute cost; biasing behaviour on our specific confusables is unmeasured and must be tested, not assumed |
| **B. Self-hosted open-weights ASR** | No per-minute cost; audio never leaves our boundary (helps §6.3); tunable | Real streaming and endpointing need work; GPU capacity to run; accent robustness is the weak spot and `01` §2 names accents as a constraint |
| **C. Framework-bundled / third-party ASR plugin** | Zero integration — LiveKit Agents and Pipecat both ship STT plugins for several vendors | Fails §0 unless the vendor is AWS. Useful only as a swap-in if the plugin layer makes it free to try, and even then the biasing support is usually the weakest part |

**Recommendation: A, Amazon Transcribe Streaming — pinned as the AWS-native default** under
the §0 constraint. It is a managed service: it needs IAM permissions, **not** a Bedrock
model-access request, so nothing here waits on an approval.

The evaluation criteria are unchanged by the constraint, and they still decide whether this
holds up: *vocabulary biasing quality* on the ROVE vocabulary — `ROVE`, `R2-4K`, `R3`,
`DUAL`, `DUAL PRO`, the four SSID prefixes, `12345678` — and *partial-emission latency*, not
headline word error rate. The decisive evaluation is a held-out set of the confusable tokens
from `01` §2 — `R2`/`R3`, `4K`/forty, `SD`/`SB`, `DUAL` — recorded over road noise and
speakerphone. **Flip to B** if the consent/privacy answer (§6.3) requires audio to stay
in-boundary, or if volume makes per-minute cost dominate; those flip conditions stand as
written.

A note that outranks the vendor choice: **no ASR will reliably separate "R2" from "R3" over
road noise**, which is why §3.4 resolves model identity by feature instead. Vendor selection
reduces the error rate; the architecture is what makes the residual error harmless. The web
client adds a second, cheaper mitigation the telephony design could not have — the user can
read the transcript and type the string (§1.4) — but it does **not** replace the first one,
because the user may be nowhere near the screen.

### 8.3 LLM

Three roles, three different requirements. Using one model for all three is the easy mistake.

**Scope restriction (§0).** Only AWS models that AWS grants without asking are eligible.
**The Anthropic models on Bedrock — Claude Sonnet, Claude Haiku, Claude Opus — require a
Bedrock model-access request and are therefore OUT OF SCOPE under this constraint.** They
were this section's previous recommendation; they are removed, not merely deprioritised. The
candidates below are the AWS-native Amazon models most likely to be default-enabled. *Most
likely* is a judgement, not a fact: **every row is TO VERIFY in the target region.**

| Role | Requirement | Candidate (TO VERIFY in target region) | Price per 1M tokens in / out (research, 2026-11-07) |
|---|---|---|---|
| **Turn reasoning** (understand, extract slots, rank the legal candidates, phrase one step) | Fast TTFT (line 6 of §2.2), reliable structured output, good instruction adherence | **Amazon Nova Pro** — *TO VERIFY* | $0.80 / $3.20 |
| **Fast-path classification** (triage, semantic endpointing support, slot extraction, step-ID mapping) | Very low latency, cheap, narrow task | **Amazon Nova Micro** — *TO VERIFY*. These are small classification jobs that do not need the reasoning tier | $0.035 / $0.14 |
| **Latency fallback** (§2.4 Tier 3) | Materially faster than Pro, materially better than Micro at ranking | **Amazon Nova Lite** — *TO VERIFY* | $0.06 / $0.24 |
| **Offline** (eval judge, taxonomy promotion review, handoff summarisation QA) | Maximum quality, latency irrelevant | **Amazon Nova Pro**, or **Amazon Titan Text** if it is the stronger default-enabled option — *TO VERIFY* | — |

The price spread is worth reading before optimising it: Micro is roughly **23× cheaper on
input** than Pro. That makes the three-role split cheap to justify *and* makes it tempting to
push reasoning down a tier. Resist that on cost grounds alone — the scenarios that break are
named below, and they are the ones the system exists for.

**The speech-to-speech question, and why the answer is no (for now).** The research names
**Amazon Nova 2.5 Sonic**, an end-to-end speech-to-speech model on Bedrock: audio in, audio
out, no transcript in the middle. Its default-access status under §0 is **TO VERIFY** like
everything else here. But the access question is not what decides it:

> An end-to-end speech-to-speech model **removes the text chokepoint that the entire
> clearance model depends on.**

§1.3 clears a step before it is spoken. §3.5 filters a candidate set. §4.5 requires a
`chunk_id` citation on every device-specific claim. §4.6 blocks version-shaped tokens with a
regex. The output guard (§1.1) is deterministic, pre-TTS, and **reads text**. A model that
goes from audio to audio has no point at which a regex can refuse a firmware version, and no
structured `step_id` to check against the ledger. M4 and M5 are hard constraints (`01` §3);
they are not achievable on a pipeline with no text in it.

So: **cascaded, deliberately.** Transcribe → policy → Nova → guard → Polly. The research puts
a tuned cascaded AWS stack at **700–900 ms voice-to-voice**, which §2.2 shows is enough. We
are paying latency for auditability and we would make the same trade again.

What would reopen it: a speech-to-speech model that emits a parallel structured text channel
we can gate on, or a product decision to downgrade M4/M5 from constraints to targets — which
`01` §3 forbids and which would be Hardik's call, not engineering's. Worth re-checking in a
year; not worth prototyping now.

**What the build must do before writing any model ID into code** — this is a procedure, not
advice:

1. Open **AWS Console → Bedrock → Model access** in the **target region** (the region itself
   is still unfixed — §9.3 item 0).
2. **Record the actually enabled list in this document** (§8.3), with the date it was read
   and the region it was read in. The list is a deployment fact and belongs in the design
   record, not in someone's memory.
3. If a model named above — any Nova or Titan row — turns out to **need an access request**,
   do not raise one. **Fall back to the next default-enabled Amazon model** for that role and
   **record the substitution here**, with which role it serves and what it replaced.
4. If no default-enabled model can serve the turn-reasoning role, that is a blocking finding
   for Hardik, not an engineering workaround. Say so rather than quietly requesting access.

Trade-offs and alternatives, honestly:

- **One model for everything (Nova Pro).** Simpler, fewer prompts to maintain, fewer failure
  modes. Costs latency on the trivial classifications that happen several times per turn.
  Worth it if the split adds more operational complexity than it saves milliseconds — measure
  before splitting.
- **A smaller model for turn reasoning (Nova Micro or Nova Lite).** Tempting for latency and
  for a 23× cost difference. The scenarios that break are `03` Part 3 — EVAL-23 (heat
  correlating with Wi-Fi drops), EVAL-24 (two symptoms pointing opposite ways), EVAL-25
  (corruption and clock loss sharing a cause). Those are the sessions where the agent earns
  its existence. **Use Nova Lite as the Tier-3 latency fallback (§2.4), not as the default**,
  and track EVAL-23/24/25 as the canary when it fires.
- **Open-weights self-hosted.** Removes per-token cost and keeps transcripts in-boundary.
  Costs serving infrastructure, and structured-output reliability needs careful evaluation —
  the policy layer depends on well-formed step IDs and citations on every turn. Note that
  self-hosting sits outside the Bedrock access question entirely, which makes it the natural
  escape hatch if step 4 above is reached.
- **Structured output is the risk the model swap actually carries.** The policy layer in §3.5
  consumes step IDs and citations as typed values, and §4.5 drops any turn whose
  device-specific claim lacks a `chunk_id`. Whatever model the console turns out to allow,
  schema-conformance rate on the §3.6 step ontology is a Phase 1 exit criterion, not a
  nice-to-have. Measure it on the 30 scenarios before trusting the choice.
- **Fine-tuning.** Not now. We have 30 written scenarios and zero real transcripts (`03`).
  Fine-tuning on our own invented utterances would tune to the wrong distribution. Revisit
  after real session data exists.

**Prompt-side lever that matters more than the model choice:** a stable cached prefix
(system instructions + taxonomy summary + state schema + output contract) with only the
`DiagnosticState` diff and retrieved chunks varying per turn. Line 6 is driven by prompt
length, and this is the largest single latency lever in the whole design.

### 8.4 TTS

| Option | For | Against |
|---|---|---|
| **A. Amazon Polly, Neural engine, streaming** — the AWS-native managed TTS | Available on IAM permissions alone, **no Bedrock model-access request**, so it satisfies §0 outright; streaming synthesis for line 7; SSML control for digit-by-digit and spelling modes. Research, 2026-11-07: **$16 per million characters** | Per-character cost; voice availability varies by region and engine, and clause-level first-audio behaviour is unmeasured |
| **A′. Amazon Polly, Generative engine** | Same service, same IAM position, better prosody | **$30 per million characters** — roughly 2× Neural. Latency characteristics differ and are unmeasured. Buy it only if Phase 3 shows Neural's prosody actually costing comprehension on digit strings and menu paths |
| **B. Self-hosted neural TTS** | No per-use cost; audio stays in-boundary | First-audio latency and prosody are usually worse; GPU capacity |
| **C. Framework-bundled / third-party TTS plugin** | Zero integration via the LiveKit or Pipecat plugin layer | Fails §0 unless the vendor is AWS; and bundled options are typically sentence-level rather than clause-level streaming, which breaks the incremental synthesis §2.1 depends on |

**Recommendation: A, Amazon Polly Neural, streaming — pinned as the AWS-native default**
under the §0 constraint, with **A′ (Generative) as a measured upgrade, not a default.** Like
Transcribe, Polly is a managed service governed by IAM permissions, **not** by Bedrock model
access, so no approval gates it. Start on Neural at $16/M characters; a support turn is a
few hundred characters, so the engine choice is a quality decision long before it is a cost
one.

The selection criteria are unchanged, and they are the two that are easy to forget:
(1) **time to first audio on a partial clause**, not on a complete sentence; (2)
**cancellation latency**, because barge-in that takes 300 ms to stop talking feels like being
ignored — and on a WebRTC leg, cancelling at the synthesiser is not enough: the browser's
playout buffer has to be flushed too (§2.1). Both must be measured against Polly specifically
in Phase 3 — pinning the vendor does not exempt it from the test. Prosody matters here more
than in most applications: this agent reads out `12345678`, SSIDs, and menu paths to a
stressed user beside a car, so digit-by-digit and spelling modes need to be controllable.
**Flip to A′** if Phase 3 shows Neural mis-reading digit strings in a way SSML cannot fix.
**Flip to B** if audio must stay in-boundary, or **to a secondary provider** per §7.6 if
Polly is unavailable.

One mitigation the web client provides for free, and which should reduce how hard we have to
push TTS: **anything hard to hear is also on screen** (§1.4). The SSID, the password, the
menu path and the current step are rendered as text. That does not excuse bad prosody — the
user may be at the car, not the screen — but it does mean a marginal prosody difference is
not worth 2× the character cost without evidence.

### 8.5 Vector store

The corpus is 21 Tier-1 documents. Realistically a few hundred chunks.

| Option | For | Against |
|---|---|---|
| **A. Embedded vector store** (in-process, file-backed) | Zero network hop — directly helps line 5; trivial to run; versioned with the code; a few hundred chunks fit in memory many times over | Scaling and multi-writer concerns if the corpus grows by orders of magnitude |
| **B. Postgres + pgvector** | One database for chunks, source registry, session records, ledgers and traces; transactional consistency between a chunk and its registry row; mature ops. The 2026-11-07 research puts pgvector as **the default for teams that do not need a dedicated vector database**, which is exactly this team at a few hundred chunks | A network hop in line 5; hybrid search needs assembling from BM25/`tsvector` + vector |
| **C. Managed vector service** | Scales, managed | Network hop; overkill at this size; another vendor; metadata filtering expressiveness varies, and §4.6's filters are mandatory, not optional |

**Recommendation: B, Postgres + pgvector.** Not for the vector search — A would be faster —
but because **the source registry, the clearance flags, the attempted-step ledgers, the
orchestration checkpoints (§8.6) and the traces all want to be in the same transactional
store as the chunks**, and §4.4's rule ("no chunk without a registry entry is indexed") is
naturally a foreign key. The hop costs ~10–20 ms of line 5, which the speculative prefetch
hides anyway. It is also the boring answer, which at this corpus size is the correct one. **Flip to A** if line 5 is
measured as a real contributor at p95 and prefetch hit rates are poor. **Flip to C** only if
the corpus grows past the point where a human can review every chunk's clearance flags —
which would itself be a change in the safety posture.

**Embeddings (§0 constraint).** The store is provider-agnostic; the embedding model is not.
Use **Amazon Titan Embeddings** — *TO VERIFY* that it is default-enabled in the target
region, and if it needs an access request, fall back to the next default-enabled Amazon
embedding model and record the substitution in §8.3's recorded list alongside the generation
models. Two consequences worth stating now: the embedding dimensionality is set by whichever
model the console allows, so the schema must not hard-code it; and **changing the embedding
model later means re-embedding the whole corpus and re-running the full eval set**, exactly
as a corpus re-crawl does (§7.6). Settle it from the console before Phase 1 ingests anything.

### 8.6 Orchestration

The requirement is §3: a state machine the LLM cannot steer, over a typed state record, with
the filters in §3.5 as the only route to a spoken step.

| Option | For | Against |
|---|---|---|
| **A. Explicit hand-written state machine** (typed states, typed transitions, pure policy functions) | Exactly matches §3; every transition testable without a model in the loop; guarantees are readable in one file; the fastest thing to debug at 2am | We write the plumbing — persistence, retries, timeouts, resume-after-reconnect, concurrency with the audio loop |
| **B. LangGraph `StateGraph`** — an explicit graph of nodes and edges over a typed state object, with checkpointing and human-in-the-loop interrupts | Per the 2026-11-07 research, part of the mature 2026 Python backend stack. **The graph is written by us, not planned by the model** — nodes are our functions, edges are our conditions, so it is option A with the plumbing already written. **Checkpointing** persists `DiagnosticState` per turn, which is exactly what §1.4.2's reconnect-and-resume needs and what we would otherwise hand-roll onto Postgres. **Human-in-the-loop interrupts** are a first-class concept and map onto §5.3's escalation and §6.4's destructive gate. Checkpoints land in the same Postgres as everything else (§8.5) | A dependency, with its own idioms and upgrade cadence. Its agentic features include planner-shaped patterns we must **not** use; the discipline is ours to keep. Per-turn checkpoint write lands in §2.2 line 4 — small, but it must be measured, not assumed |
| **C. Agent framework with tools and a planner** | Fast to prototype; flexible | **The planner is the thing we are deliberately removing.** An LLM that chooses the next action cannot guarantee M4 or M5. Fighting a framework to constrain it is worse than not having it |
| **D. Workflow engine** (durable execution) | Durability, retries, visibility | Designed for long-running workflows; a sub-second conversational turn is the wrong shape for it; per-turn overhead lands in line 4 |

**Recommendation: B, LangGraph `StateGraph` — as an implementation of A, not as a
replacement for it.**

This needs saying carefully, because the previous revision of this document recommended A
"emphatically" and the reasoning behind that has not weakened at all. The central
architectural commitment is unchanged: **`01` §5's hard constraints are not achievable on
top of a planner that is free to choose.** The LLM is called as a *function* at specific,
bounded points — understand, extract, rank-within-legal-set, phrase — and never as a
controller.

What changed is the recognition that the plumbing in A's "against" column is not small, and
that two pieces of it are now first-class requirements of the web design:

1. **Resume after reconnect** (§1.4.2). Browsers disconnect. `DiagnosticState` must survive
   a dropped peer connection, per turn, transactionally. That is checkpointing, and writing
   it ourselves is a week we do not need to spend.
2. **Human-in-the-loop interrupt** (§5.3, §6.4). Escalation and the destructive-consent gate
   are both "halt the graph, wait for an external decision, resume with it". Hand-rolled,
   that is the kind of state machine that works until two interrupts overlap.

A `StateGraph` with explicit nodes and conditional edges *is* the explicit state machine of
§3.2 — the states are nodes, the ceilings are edge conditions, the policy filters are pure
functions inside a node. Nothing about the guarantee model is delegated.

**The rule that makes this safe, and it is a review rule, not a library setting:** the graph
is authored, never planned. No node may be reached by model choice. If a future change
introduces a model-chosen edge, that is a breach of §1.3 and §3.1 and it is caught in review
and in M4/M5. Writing it down here is the point — a constrained use of a flexible library
degrades silently unless someone states the constraint.

**Flip to A (plain hand-written)** if LangGraph's per-turn overhead shows up in line 4, or
if its idioms start dictating our state shape rather than the reverse. The §3 design is the
specification and it is portable; the migration cost is bounded precisely because the graph
is ours. **Flip to C** only if the constraint set is relaxed to soft targets, which would be
a product decision, not an engineering one.

### 8.7 Backend

| Option | For | Against |
|---|---|---|
| **A. Python + FastAPI** | The ML/ASR/vector ecosystem; LangGraph (§8.6) is Python-first; LiveKit Agents and Pipecat both ship Python SDKs; the eval harness, chunkers and judges all want to be Python; `scripts/html2txt.py` is already Python. The 2026-11-07 research names **FastAPI + LangGraph + Postgres/pgvector + React** as the mature 2026 stack, and matching a well-trodden path is worth more than a marginal technical edge | Concurrency for a real-time audio loop needs care (async throughout, no blocking calls on the media path) |
| **B. TypeScript/Node** | Strong async I/O story; shares a language with the React UI; LiveKit Agents has a Node SDK too | ML tooling weaker; the eval harness, chunkers and judge drift to a second language — and those are where most of the actual code is |
| **C. Go** | Best concurrency and latency predictability for the media path | Weakest ecosystem for the ML side; the team would be writing more glue |

**Recommendation: A, Python with FastAPI, for the diagnostic core, knowledge layer, agent
process and eval harness.** FastAPI specifically because the backend's non-audio surface is
small and well-shaped for it: mint the short-lived room token (§1.4.2), serve the session
record, expose the handoff to the support console, and carry the traces. Keep C or B in
reserve for the media edge **only** if measurement shows the Python event loop is the
bottleneck — which §2.2 says it will not be, since lines 1 and 9 together are 55 ms.

That reserve is credible because §1.1 keeps a clean boundary between the WebRTC edge and the
diagnostic core. If it ever has to be crossed, §8.1.1's Ten Framework option is the shape
that crossing takes. Start single-language; split only on evidence.

### 8.8 Web UI framework

New in this revision — the previous one had no UI to choose for.

| Option | For | Against |
|---|---|---|
| **A. React (with Next.js)** | The 2026-11-07 research names React/Next.js as part of the mature 2026 stack. **The voice framework's browser SDK is a first-class React citizen** (§8.1.1), which is the whole reason this is not a free choice — room connection, track subscription, device permissions and reconnection all arrive as hooks rather than as code we write. Largest hiring pool and the most prior art for exactly this UI shape | A build toolchain and a framework's worth of concepts for what is, at v1, four panels. Next.js in particular brings server rendering we barely need |
| **B. Plain TypeScript, no framework** | Nothing to learn; smallest bundle; the UI genuinely is small | Every piece of state we would hand-roll — connection lifecycle, transcript list, step panel, ledger — is a thing React already solves, and the UI grows. We would also be first to integrate the browser SDK this way |
| **C. Server-rendered HTML + a thin sprinkle of JS** | Simplest deployment; one language | The page is a **live, bidirectional, stateful** surface — transcript, step, ledger and connection state all updating several times per turn. This is the shape server-rendered pages are worst at |
| **D. A component library / design system first** | Looks finished sooner | Premature. We do not yet know what the panels need to be; `03` Part 2 will change them |

**Recommendation: A, React — and plain React before Next.js.** The decision is made by the
voice framework, not by the UI: if the browser SDK's idiomatic integration is React hooks,
choosing anything else means maintaining the glue ourselves, for a client whose entire job
is to be reliable. Next.js is worth adopting if we need server-side rendering, routing and
an API surface in one place; for v1 the page is one route behind authentication, so start
with React and add Next.js when there is a second reason to.

**Three constraints on the UI that outrank any framework question**, restated here because
this is where they get violated:

1. **It may never become load-bearing** (§1.4.1). Voice-complete, screen-accelerated.
2. **It renders `DiagnosticState`; it does not own it** (§3.3). The browser's copy is a
   projection. A reload loses nothing.
3. **It is a cleared output surface** (§1.3). The output guard runs on what is rendered, not
   only on what is spoken. There is no "reference material" pane.

**Flip to B** if §8.1.1 flips to a framework with no React affinity *and* the UI is still
four panels. **Never D** before Phase 4 — the pilot is what tells us what to build.

---

## 9. Build plan and open decisions

### 9.1 Phases

**Phase 0 — Harness before agent (days).**
Build Harness A (§7.3) and run the 30 scenarios against a deliberately dumb baseline, plus a
human baseline (§7.4 item 4). Produce the step ontology (§3.6) and the taxonomy-ID →
candidate-step map. *Why first:* `README` says disagreements about the expected next step are
design bugs worth fixing before any code exists, and a baseline is required before any score
means anything (`01` §8 Q9). **Also in this phase, because it gates every later one:** read
AWS Console → Bedrock → Model access in the target region and record the default-enabled list
in §8.3, with date and region (§0 constraint; §9.3 item 0). **Exit:** the 30 scenarios run
automatically; two human graders agree at a measured κ; a human baseline score exists; the
default-enabled model list is recorded in this document and §8.3/§8.5 are reconciled against
it.

**Phase 1 — Text-only diagnostic core (1–2 weeks).**
`DiagnosticState`, the FSM, the policy filters, the attempted-step ledger, the destructive
gate, the output guard. Ingest and chunk the 21 Tier-1 documents with full metadata; stand up
the source registry; build the hybrid retrieval with model filtering. **No voice at all.**
*Why:* every hard constraint in `01` §5 is testable in text, and debugging a no-repeat failure
through an audio pipeline is miserable. **Exit:** M4 = 100 % and M5 = 0 on Harness A and B;
grounding rate 100 %; the `UNVERIFIED` entries escalate rather than improvise.

**Phase 2 — Knowledge completion (parallel with Phase 1).**
Write the four missing taxonomy entries (rear-channel, GPS, mounting ≥ 20°, time-lapse) and
guards for the other `05` finds. Capture the four missing Help Center bodies (overheating,
plate legibility, blurry, random restarting) — `PWR-02` and part of `VID-01` depend on them.
Obtain the R2-4K PRO manual. Close the provenance gap on the five hand-uploaded manuals
(§4.4). **Exit:** every spoken chunk has a registry entry; `PWR-02` has Tier-1 coverage or is
formally accepted as escalation-bound.

**Phase 2b — Web client and transport spike (parallel, days).**
A single-page React client that joins a room, streams microphone audio and plays audio back,
plus the server-side token mint (§1.4.2). Do this **as a Pipecat SmallWebRTC spike first**
(§8.1.1) — one Python process, nothing to operate — purely to get real browser audio through
a real peer connection early. *Why separately and early:* it de-risks the only part of the
system nobody has built before, and it produces the first honest numbers for §2.2 lines 1
and 9. **Exit:** a browser holds a stable duplex session for 10 minutes, survives a network
drop and re-join, and reports RTT/jitter/loss into the trace.

**Phase 3 — Voice pipeline (2–3 weeks).**
Promote to LiveKit Agents (§8.1.1), then: streaming Transcribe with biasing, Silero VAD v5,
context-dependent endpointing, barge-in with browser-side playout flush, incremental Polly
synthesis, speculative prefetch, the React panels of §1.4, the click-or-type path, and the
full 9-component latency instrumentation. Harness C with noise and the ASR-corruption pass,
driven through a real peer connection at real-time pace. *First measurement that matters:*
the real distribution of lines 2, 6 and 7 — 78 % of the budget. **Exit:** M7 median at or
under the §2.2 target with the component breakdown published and `01` M7's 1.2 s not
breached at the median; **the 9-component decomposition is obtainable through the framework**
(§8.1.1); M10 = 100 %; the latency ladder demonstrably fires and recovers; the
corrupted-transcript pass shows mis-heard models producing `UNKNOWN` rather than a wrong
branch.

**Phase 4 — Supervised pilot (4+ weeks).**
Live sessions with a human monitoring and able to **join the room** at any moment (§5.3) —
which is also the first real test of the escalation mechanic, not a separate exercise.
Collect real transcripts (consent permitting — §6.3) and **replace `03`'s written utterances
with real user language**, accepting that pass rates before and after are not comparable
(`03`). Establish the real M8 baseline and the real session mix (`01` §8 Q10). **Production
gate — all of:** M4 = 100 %, M5 = 0 and M10 = 100 % across the whole pilot; escalation
precision *and* recall both acceptable against the agreed figure; every speakable chunk has
a complete registry entry; consent and destructive-action policies signed off by their
owners; escalation mechanic configured with real hours and a real SLA.

**Phase 5 — Production, narrow.**
Launch on the categories with the strongest Tier-1 coverage — the 10 VERIFIED entries plus
the salvageable CORRECTED ones. `FW-03` stays escalation-bound until a known-issue feed
exists. Expand per category only on measured evidence, re-running the full eval set on every
corpus change.

### 9.2 What is deliberately *not* built

- **An LED/beep evidence path.** `05` settled the screenless question: no in-scope model is
  screenless. Building it would be work against a hypothesis that was disproved.
- **Any device integration, telemetry, remote diagnostics or account lookup** (`01` §4).
- **A firmware version catalogue.** There is nothing to catalogue, and a half-built one is an
  invitation to speak a version.
- **Multilingual.** English-only for v1 (`01` §7).
- **Containment optimisation** (`01` §6 M9).
- **A text-only chat product.** The click-or-type path exists to accelerate a voice session
  (§1.4.1), not to become a second product with its own flows. The moment it has flows of
  its own, M10 stops being measurable and the UI has become load-bearing.
- **Footage upload.** No control for it, deliberately (§6.3). The agent is advisory.
- **Phone-call fallback, SIP, or a phone number of any kind** (§0.1). Not deprioritised —
  out of scope.
- **An end-to-end speech-to-speech pipeline** (§8.3). It removes the text chokepoint M4 and
  M5 are enforced at.

### 9.3 Open decisions that need Hardik

Ordered by what blocks the most work.

| # | Decision | Blocks | Why it cannot be decided in engineering |
|---|---|---|---|
| 0 | **Confirm the Bedrock default-enabled model list in the target region, and record it** (§0, §8.3). Which region are we deploying to, and which models does AWS Console → Bedrock → Model access already grant there *without* a request? Under Hardik's constraint, no access request and no support ticket may be raised — so a model that needs one is simply unavailable, and we fall back to the next default-enabled Amazon model and record that. | §8.3's three roles and §8.5's embedding model; Phase 0 and Phase 1 cannot write a model ID until the list exists | The target region and the account's existing entitlements are an account fact, readable only from that console. Engineering cannot assume it and must not resolve it by requesting access |
| 1 | **Known-issue / firmware regression feed** — does an internal one exist, can it be kept current? (`01` §8 Q5; `05` "the single biggest remaining gap… not solvable by more reading") | `FW-03` entirely; the single most valuable thing a human engineer does on these calls | It is an internal data source, or it does not exist |
| 2 | **Escalation mechanics** — same-session join, callback, or ticket; hours; queue; SLA (`01` §8 Q6). Plus the three sub-questions in §5.3: does the joining human speak to the user or only read, does the agent stay in the room, and is the user told the human can see the transcript | What the agent *promises* the user; `01` §7 assumption 1; **and the §8.1.1 framework decision**, whose main justification is the same-session join | Operational commitment, and it needs a support-side console that can join a room. The Help Center's published 9am–5pm PST, 7 days is a starting point, not an answer |
| 3 | **Destructive-action policy owner, and legal sign-off** (`01` §8 Q7) | The `REC-01` preserve-first rule, the format gate, the EVAL-22 handling, and the missing `REC-01` eval scenario (`03` appendix: *"what is actually missing is a decision, not a fact"*) | Footage can matter for an insurance claim. Someone has to own that |
| 4 | **Session recording and consent** — jurisdictions, disclosure, retention (`01` §8 Q8). The web client splits this in two: **displaying** a live transcript in the user's own browser versus **storing** it (§6.3), and they may not have the same answer | Whether an evaluation corpus of real sessions can exist at all; whether `03`'s written utterances can ever be replaced | Legal |
| 5 | **Provenance for the 5 hand-uploaded manuals** — where each came from, on what date; and whether `B0F9SX3JB9.pdf` is the ASIN document it appears to be (`data/README.md`; `04`) | §4.4's speakable rule, and the Phase 4 production gate | Only the person who downloaded them knows |
| 6 | **R2-4K PRO manual** — obtain it (`05` item 3) | PRO-specific claims currently rest on product listings, not a manual |  Needs the file |
| 7 | **Four uncaptured Help Center bodies** — overheating, plate legibility, blurry, random restarting (`05` item 4) | `PWR-02` (one of the 4 UNVERIFIED) and part of `VID-01` | Needs a re-crawl with web access |
| 8 | **Baseline and call mix** — current human verified-resolution rate, AHT, and the real distribution across the 7 categories (`01` §8 Q9, Q10) | Every target in `01` §6; the cause rankings in `02` that drive the agent's first question | It is in support's historical data, or nowhere |
| 9 | **Are R1 and R4 in scope?** Both are in the verified line; neither has a manual (`05`) | Whether those calls get a graceful "I can't help with that one" or an attempt | Product decision |
| 10 | **Is the sub-800 ms bar a requirement or an aspiration?** (§2.2) Our budget lands at ~860 ms, and the only line big enough to close the gap is the endpointer hangover | The endpointer design, and therefore diagnostic accuracy on open-ended turns | It is a trade against M3, and the trade is a product call |
| 11 | **Licence position on the corpus** — `04` notes Rove content is for support use in this assessment and manuals must not be republished verbatim. The web UI sharpens this: **rendering** a manual excerpt on screen is closer to republishing than speaking it is | Whether excerpts need length limits and attribution, spoken *and* displayed | Legal / commercial |
| 12 | **Does the §0 AWS-models constraint cover an in-process open-weights VAD?** We read it as governing the Bedrock model layer — ASR, LLM, TTS — and not Silero VAD v5, which runs in our own process and calls no AWS endpoint (§8.1.1) | §2.3's context-dependent endpointing, which is §2.2's largest controllable line. The fallback is the ASR vendor's own endpointing, and it is materially worse | It is a reading of Hardik's constraint, and only Hardik can settle what he meant |
| 13 | **Who runs the media server?** Self-hosted LiveKit on our AWS account, or the hosted service (§8.1.1) | Phase 3's operational shape, the TURN bandwidth bill, and whether §6.3's audio-in-boundary answer is even available | Cost and data-residency commitment, not an engineering preference |
| 14 | **Is there a support-side console that can join a room?** §5.3's same-session join needs one, and it does not exist | The escalation mechanic, and with it the main justification for §8.1.1's framework choice | It is a build decision about support tooling, with an owner outside this project |

### 9.4 The honest summary

The knowledge layer is in better shape than `01` and `02` feared: 23 of 28 entries now have
Tier-1 backing, the model line is known, the password and SSID prefixes are speakable, and
the screenless worry — the one that would have forced a parallel evidence path — is dead.

**What the move to a web client changed, and what it did not.** It made four things easier:
echo cancellation and jitter are the browser's problem now; the transport lines of the
latency budget shrank to 55 ms combined; escalation stopped needing a transfer primitive and
became "admit a second participant"; and the confusable tokens that `01` §2 named as the
hardest ASR problem can now be *typed*. It made one thing harder, and it is a discipline
problem rather than a technical one: **there is now a second output surface, and every
guarantee in this document has to hold on both.** The clearance model, the output guard, the
destructive gate and the firmware-version regex all run on what is rendered, not only on
what is spoken — and the temptation to treat the screen as "just reference material" is the
single most likely way this design gets quietly broken. M10 exists to catch it.

What is genuinely hard is unchanged, and it is not the RAG and it was never the transport.
It is that **model identification got harder, not easier** (8 rows, two R2-4K revisions, a
touchscreen R3 that must now be branched on, over a channel that cannot reliably distinguish
"R2" from "R3" — and the user may be nowhere near the keyboard that would fix it), that
**four entries have no evidence at all and must escalate rather than improvise**, that
**`FW-03` is undiagnosable without a feed nobody has**, and that **the sub-800 ms bar and
good endpointing are in direct tension** — lines 2, 6 and 7 are 78 % of the budget, and line
2 is bought with diagnostic accuracy.

None of those are solved by a better prompt, a faster framework, or a nicer page. They are
solved by the state machine in §3, the clearance model in §1.3, and the organisational
decisions in §9.3 that are not ours to make. The decisions this document *did* make, with
the alternatives weighed and the reasons recorded, are in `07-decision-log.md`.
