# 01 — Problem Definition: Rove Voice Troubleshooting Agent

Status: Step 1 draft. No code. Design only.
Date: 2026-11-07

---

## RESEARCH STATUS — READ FIRST

The prompt for this step asked for web research against `rovedashcam.com`, Amazon review
text, and Rove firmware/release notes.

**No external source was retrieved.** WebSearch, WebFetch, and outbound `curl` were all
denied by the session permission layer. This is a permission denial on our side, not a
site error, a 404, or a robots block.

Consequences for every doc in `docs/`:

- Nothing in these docs is marked `Official doc`. We retrieved no official doc.
- Entries that reflect customer phrasing or symptom frequency are marked
  `Review signal (unretrieved)` — meaning the pattern is drawn from general prior
  knowledge of consumer dashcam complaints, **not** from a review corpus we actually read.
  Treat these as hypotheses about what users say, not as evidence of frequency.
- Every candidate fix is marked `TO VERIFY — do not present as fact`.
- No firmware version number, SD card spec, model capability, SSID, or default password
  appears in these docs as fact.

**Step 1b (blocking, before any build):** re-run the research with web access granted,
then promote entries from `Inferred` to `Official doc` with a URL and retrieval date.
Until that happens, the taxonomy is a question list, not an answer set.

---

## SCOPE CORRECTION, 2026-11-07 (Hardik)

**This is not a telephonic system.** It is a **web-based voice assistant with a UI we
provide**. The user opens a page in a browser, grants microphone permission, and speaks.
Audio travels over WebRTC from the browser. There is no phone call, no SIP, no PSTN, no
phone number and no SIP trunk anywhere in this design.

This document has been re-worded to match: it says **user** and **session** where it
previously said *caller* and *call*. `06-architecture.md` §0.1 carries the same correction
and re-derives the architecture under it. **No verified fact, number, target or scope
boundary changed** — the device, the taxonomy and what counts as success do not care how
the audio arrives. The two entries in §2 that genuinely did change are the ones about the
screen, and they are marked below.

`02-issue-taxonomy.md` and `03-golden-eval-set.md` still use the older *caller* / *call*
wording. They describe the same person and the same interaction.

---

## 1. Problem statement

Rove dashcam owners come to support with device faults they cannot describe precisely —
"it won't connect," "it stopped recording," "it broke after the update." A human support
engineer resolves these by narrowing: establish the model, establish what changed,
establish what the user already tried, form a ranked hypothesis, test the cheapest
discriminating step first, and confirm the symptom is actually gone. We want a voice
agent that does the same thing in a browser session — diagnosing rather than retrieving —
while staying inside verified guidance and handing off to a human the moment its
confidence drops or the problem leaves its scope.

## 2. Who is using this, and what voice costs us

The user is a consumer, not a technician. They own one Rove dashcam. They open our page in
a browser, grant microphone permission, and speak. They are often in or beside the car,
sometimes with the device in their hand, sometimes not — and therefore often **away from
the screen they opened the session on**, which may be a laptop indoors or a phone in their
pocket. They may be mid-trip. They usually do not know the model name, the firmware
version, or the SD card class.

Voice-first imposes hard constraints that a chat agent does not have:

| Constraint | Consequence for the agent |
|---|---|
| **Voice-complete, screen-accelerated** *(corrected: there is a screen, and it is ours)* | Every diagnostic path must be completable **by voice alone**, because the user may be hands-free beside the car. The screen makes the same path faster and safer, **never different**. A menu path must still be speakable as a path the user can follow by ear; it may *also* be rendered. |
| Short turns | One question per turn. A three-part question gets one answer, usually to the last part. |
| Noisy environment | Road noise, engine, passengers, laptop speakers. ASR will mishear model names and numbers. Confusable tokens: "R2" / "R3" / "are two", "4K" / "forty", "SD" / "SB". |
| Interruptions / barge-in | The user will talk over instructions. The agent must stop speaking immediately and re-anchor, not restart the step from the top. |
| Accents and non-native speakers | Model identification cannot depend on a clean spelling of a product name. Need fallbacks: physical description, screen text, purchase date, box text. |
| User cannot hold long steps in memory | Maximum one action per turn, then an explicit confirmation before the next. No "then, after that, go to…". |
| User may be driving | Safety gate: if the user indicates they are driving, defer any step that needs the device or phone in hand. A browser session does not make this go away — a phone travels. |
| Copy-paste exists, but only at the screen *(corrected)* | Serial numbers, firmware filenames and support ticket IDs can be **typed** when the user is at the screen, which removes the confusion entirely. When they are not, the old rule stands: read back and confirm digit by digit. The agent may never assume they are at the screen. |
| Latency is audible | Any silence over roughly a second reads as a dropped connection and triggers "hello? hello?". |

## 3. What success means

Success is **verified resolution**, not a correct-sounding answer.

1. **Verified resolution.** The user performed the step and confirmed the symptom is
   gone, in the same session. An unconfirmed instruction is not a resolution.
2. **Correct escalation.** Low-confidence, out-of-scope, and suspected-hardware sessions
   reach a human. Escalating correctly counts as success; escalating late counts as
   failure; escalating everything is not a win either.
3. **No repetition of attempted steps.** If the user says they already reset it twice,
   the agent never proposes a reset again without a stated new reason ("you reset it, but
   not with the card removed — that's a different test").
4. **No harmful advice.** No firmware downgrade, no unguarded factory reset, no format of
   a card holding footage the user needs, no advice to operate the device while driving.
5. **Honest uncertainty.** When the agent does not know, it says so and escalates, rather
   than producing a plausible fix.

## 4. Scope

### In scope for v1

- Browser-based voice sessions about Rove dashcams only.
- Diagnosis and guided resolution for the seven categories in `02-issue-taxonomy.md`:
  Wi-Fi connectivity, firmware update/compatibility, mobile app pairing, not
  recording / loop recording, SD card / storage, power / overheating, video quality /
  settings.
- Model identification, including by physical description when the user cannot name it.
- Context capture: firmware version if obtainable, phone OS, SD card details, what was
  already tried, what changed before the fault.
- Session memory: attempted steps, outcomes, and the current hypothesis.
- Explicit confirmation of each step and of final resolution, by voice or on the screen.
- Structured escalation handoff: symptom, model, context, steps tried and their outcomes,
  current hypothesis, reason for escalation.

### Out of scope for v1

- Billing, refunds, order status, shipping, warranty claims.
- Returns and RMA processing.
- The decision that hardware is faulty and must be replaced — the agent may *suspect*
  hardware and escalate; a human makes the call.
- Non-Rove devices, including other brands the company sells.
- Chat, email and SMS as separate support channels. The session's click-or-type path
  exists to accelerate a voice session, not to become a text-chat product.
- Agent-initiated outbound contact of any kind. A callback is something a human performs
  after an escalation; the agent does not place it.
- Anything requiring account authentication or PII lookup.
- Writing to the device, remote diagnostics, or any telemetry pull. The agent is
  advisory only; the user performs every action.
- Legal/insurance questions about footage ("can I use this in court").

## 5. Failure modes to design against

| Failure mode | What it looks like | Mitigation direction |
|---|---|---|
| Repeating a failed step | User already power-cycled; agent opens with "let's try turning it off and on". | Attempted-step memory must be consulted before every recommendation, and a step already marked `tried → failed` is blocked unless re-proposed with a stated difference. |
| Category collapse | "It won't connect to my phone since the update" answered with generic Wi-Fi advice. | A stated change event (update, new phone, OS upgrade, new card) must re-rank causes before any category default fires. |
| Destructive advice | Format, factory reset, or firmware downgrade proposed early or without warning. | Destructive steps gated: require explicit cause, explicit user consent, and a stated consequence ("this erases the footage on the card"). Downgrade is never agent-initiated. |
| Hallucinated fix | A menu path, setting name, or firmware version that does not exist. | Agent may only speak **or render** steps traceable to a verified source. Unverified steps are either withheld or spoken with an explicit hedge and routed to escalation. The screen is not a loophole: a step that may not be spoken may not be displayed. Pending Step 1b, this means almost everything. |
| Phantom model | Agent assumes a model and gives model-specific instructions. | Model must be confirmed, not inferred. Unconfirmed model → model-agnostic steps only. |
| Instruction overload | Four steps in one turn. | Hard limit: one action per turn, confirmation required. |
| False resolution | Agent closes on "that should fix it". | Close requires the user to state the symptom is gone, or a scheduled re-test ("drive and check tomorrow") with an explicit non-closure. |
| Silent escalation failure | Agent loops on the same hypothesis for ten turns. | Turn-count and repeat-hypothesis ceilings that force escalation. |
| ASR-driven misdiagnosis | "R3" heard as "R2", wrong branch taken. | Confusable fields (model, numbers, versions) require read-back confirmation — or, when the user is at the screen, correction against the displayed transcript. |
| Guessing at silence | User says nothing; agent fills in. | No inference from non-answers. Re-ask once, then mark `Unknown` and branch accordingly. |

## 6. PROPOSED measurable targets

**These are proposed starting points for discussion, not agreed requirements, and not
benchmarks anyone has validated.** No baseline exists yet. The honest position today is
that we do not know what is achievable on this task; these numbers exist so Step 2 has
something to argue with. Do not quote them to a stakeholder as a commitment, and do not
claim 95%/99% anywhere.

| # | Metric | Definition | PROPOSED starting target | Measured how |
|---|---|---|---|---|
| M1 | Device identification | Correct model confirmed (or correctly marked `Unknown` and handled) before model-specific advice | PROPOSED ~85% | Golden set + session audit |
| M2 | Intent/category accuracy | Correct top-level category assigned by end of turn 3 | PROPOSED ~90% | Golden set, labelled |
| M3 | Next-step accuracy | The single next question/action matches the expected one in `03-golden-eval-set.md` | PROPOSED ~80% | Golden set, graded against expected next step |
| M4 | No-repeat compliance | Zero recommendations of a step already marked tried-and-failed | PROPOSED 100% (hard constraint, not a target) | Automated transcript check |
| M5 | Harmful-advice rate | Destructive step without cause + consent + consequence stated | PROPOSED 0 (hard constraint) | Automated check + human audit |
| M6 | Escalation correctness | Escalated when expected; not escalated when not expected | PROPOSED ~90% on the 3 escalation scenarios + negative controls | Golden set |
| M7 | End-of-speech to first audible response | User stops speaking → first audio out | PROPOSED under ~1.2 s median, with a filler token if the hypothesis step runs long | Pipeline instrumentation |
| M8 | Verified resolution rate | User confirms symptom gone, in-session | PROPOSED: establish baseline first, then set a target | Session outcome tagging |
| M9 | Containment | Sessions resolved without human handoff | PROPOSED: report only, do not optimise in v1 | Session outcome tagging |

Note on M9: containment is deliberately not a target. Optimising containment before
resolution quality is measured would reward suppressing escalations.

## 7. Assumptions

1. Session volume is low enough that escalation to a human is available during support
   hours. If it is not, escalation is not a real fallback and the design changes.
2. The user has the device, or can get to it, during the session. Users who are driving
   are deferred, not diagnosed.
3. Official Rove manuals and firmware notes exist and are retrievable once web access is
   granted. If they are not public, ground truth must come from internal support
   documentation instead, and Step 1b must be re-planned around that.
4. Rove's device-side UI (menus, settings names) is stable enough per model that spoken
   menu paths stay correct across firmware revisions. Unverified.
5. The agent has no device telemetry, no account lookup, and no ability to act on the
   device. Everything is user-performed.
6. English-only for v1.
7. One device per session.
8. We may record and transcribe sessions for evaluation, subject to legal review and
   consent requirements that have not been checked.

## 8. Open questions

1. **Ground truth source.** Are Rove manuals, firmware release notes, and a support KB
   publicly available and machine-retrievable? What is the licence position on ingesting
   them? This blocks the entire knowledge layer.
2. **Model line.** What is the exact, current list of Rove models in support scope,
   including discontinued units still in customers' hands? Which differ enough to need
   separate diagnostic branches?
3. **Model identification without a model number.** How does a user who has thrown away
   the box identify their unit by voice? Is there a distinguishing physical or on-screen
   cue per model, and does one exist at all?
4. **Firmware version retrieval by voice.** Can a user read their firmware version off
   the device menu reliably? What is the exact menu path per model, and how long does it
   take to walk a user there?
5. **Known-issue feed.** Is there an internal list of firmware regressions and batch
   defects, and can it be kept current? Without it, the agent cannot do the single most
   valuable thing a human engineer does — recognise a known bad build.
6. **Escalation mechanics.** Does a human join the user's existing session, or is it a
   callback, or a ticket? What are the hours, the queue, and the SLA? This determines
   what the agent promises the user. (There is no phone transfer — see the scope
   correction above, and `06-architecture.md` §5.3.)
7. **Destructive-action policy.** Who owns the rule for when a format or factory reset
   may be recommended, given it can destroy footage the user needs for an insurance
   claim? Does legal need to sign this off?
8. **Session recording and consent.** What jurisdictions, what disclosure, what
   retention? And, specific to a web UI: **displaying** a live transcript in the user's
   own browser and **storing** it are two decisions, and they may not have the same
   answer. Affects whether we can build an evaluation corpus at all.
9. **Baseline.** What is the current human-agent verified resolution rate and average
   handle time for these categories? Without it, every target in §6 is invented.
10. **Volume and mix.** What is the real distribution across the seven categories? The
    taxonomy's implicit ranking is currently guesswork.

## What is still unknown

- **Update, 2026-11-07:** initial hypotheses now exist for the items below. `02` carries a
  section, "Initial hypotheses from model knowledge", plus a `Most plausible next step
  (initial hypothesis)` and a `What would confirm / disconfirm it` field on each of its 28
  entries, all labelled `Initial hypothesis — to verify` with a Low/Medium/High confidence.
  That changes what Step 1b is: **verification of a concrete list, not creation from an empty
  one.** It does not change what is *known* — nothing below has been promoted to fact, and no
  hypothesis is cleared for the agent to speak to a user.
- Everything that requires a retrieved source: model list, firmware behaviour, menu
  paths, SD card requirements, app names, default credentials, and every specific fix.
- Whether the seven categories in §4 actually cover the real session mix, or whether they
  reflect our assumptions about dashcam faults.
- Whether voice-first diagnosis is viable for the firmware-update category at all, given
  it may require the user to use a computer mid-session.
- Real latency budget. **Components have now been chosen** — `06` §8 picks the transport,
  framework, VAD, ASR, LLM roles, TTS, embeddings, vector store, orchestration, backend and
  UI framework, and `07` records why — so this is no longer blocked on a missing stack. What
  is still unknown is the *measurement*: `06` §2.2's 9-component table is explicitly a
  **budget, not a measurement**, because no pipeline has been built. Its Bedrock model rows
  are also still `TO VERIFY` against the AWS console (`06` §9.3 item 0).
- Whether the PROPOSED targets in §6 are ambitious, trivial, or impossible. We have no
  baseline, and we will not know until Step 1b and a first evaluation run.
