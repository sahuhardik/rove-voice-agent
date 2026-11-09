# 02 — Issue Taxonomy v0: Rove Dashcam Voice Support

Status: Step 1 draft. No code. Design only.
Date: 2026-11-07
Companion to `01-problem-definition.md` — read its RESEARCH STATUS first.

**Amended 2026-11-07 by Milestone 5.2 (Phase 2 knowledge completion).** A new
[Category H](#category-h--known-gaps-gap-rear-channel--gap-timelapse) adds the **four
taxonomy entries** `05` confirmed were missing — rear channel, GPS / live speed, mounting,
time-lapse — plus **five guards** for the other `05` finds. Nothing in Categories A–G was
changed. Category H is written the other way round from A–G: those were hypotheses later
checked against sources, these were written *from* the sources, so they carry
`Evidence: Official doc (Tier 1)` and a per-entry `docs/05` status. The v0 rule that no
entry may be marked `Official doc` applies to the original 28 and is not relaxed for them.

---

## RESEARCH STATUS — READ FIRST

**No external source was retrieved for this doc either.** WebSearch was re-attempted in
this session and denied by the permission layer. Same position as `01`:

- Nothing below is marked `Official doc`. We have read no Rove manual, support page,
  firmware release note, or review corpus.
- `Review signal (unretrieved)` means: this is a symptom pattern drawn from general prior
  knowledge of consumer dashcam complaints. It is a hypothesis about what callers say.
  It is **not** evidence of frequency and **not** a retrieved quote.
- `Inferred` means: a cause hypothesis derived from how this class of device generally
  works, not from Rove documentation.
- **Every "next step" below is `TO VERIFY — do not present as fact`.** None has been
  confirmed against a Rove source. No step here is cleared for an agent to speak to a
  caller until Step 1b promotes it with a URL and a retrieval date.
- No firmware version, SD card class, capacity limit, SSID, default password, menu name,
  or model capability appears here as fact. Where one would normally go, the text says
  `Unknown`.

**What this document actually is right now:** a ranked question list and a cause-hypothesis
map. It tells the agent what to *ask* and what to *suspect*. It does not yet tell the agent
what to *say*.

---

## Initial hypotheses from model knowledge

Added 2026-11-07, on instruction to stop treating the research denial as a blocker.

**What this section is.** Reasoning from prior model knowledge, written down so a prototype
can be built and tested. It is **not** research. Nothing here was retrieved, read, or checked
against a Rove source. Every claim carries `Initial hypothesis — to verify` and a confidence
level, and the rule in the Research Status above still stands: **none of this is cleared for
an agent to speak to a caller.** What has changed is that Step 1b is now a *verification* task
against a concrete list, rather than a creation task against an empty one.

**What the confidence levels mean here:**

| Level | Meaning |
|---|---|
| High | General consumer-dashcam behaviour that holds across the product class. Rove-independent. |
| Medium | Specific to Rove as recalled from prior knowledge. Plausible, unchecked, and possibly conflated with a neighbouring brand. |
| Low | The name, the feature, or the whole model may be wrong. Treat as a prompt for Step 1b, not as information. |

---

### 1. Likely Rove model line

All of the following are `Initial hypothesis — to verify`. Expect Step 1b to correct names,
add models, and delete at least one of these outright.

**Rove R2-4K** — Confidence: Medium.
The volume product, and almost certainly the modal caller's device; sold predominantly through
Amazon. Single front channel at 4K, a small colour LCD (roughly 2–2.5 inches), built-in GPS
with a speed and location overlay on the footage, a 2.4 GHz Wi-Fi access point for phone
transfer, a fixed wide lens, and microSD storage. Parking mode is believed to depend on a
separately sold hardwire kit rather than on the cigarette-lighter socket.

**Rove R2-4K Pro** — Confidence: Low–Medium.
A later revision of the R2-4K line. Likely differences are sensor and night processing, possibly
voice control, possibly a larger screen. The *diagnostic surface* is probably identical to the
R2-4K — same app, same Wi-Fi AP model, same microSD behaviour, same hardwire-dependent parking
mode — so until verified it should share a diagnostic branch rather than get its own.

**Rove R2-4K Duo / dual-channel variant** — Confidence: Low.
A front-plus-rear two-channel variant. If it exists, it introduces a failure mode this taxonomy
does not carry at all: rear channel black, missing, or intermittent because of the rear camera
cable. (That cabling failure is the most common dual-channel complaint in the product class —
Confidence: High as a general dashcam fact, Unknown as a Rove fact.)

**Rove R3** — Confidence: Low.
Named in the brief. Prior knowledge cannot reliably distinguish it from the R2 line and may be
conflating it with another brand entirely. Until verified, assume a 4K front camera with the
same app, Wi-Fi, and microSD surface — and do **not** let the agent branch on R2-versus-R3,
which also sidesteps the `R2`/`R3` ASR confusion flagged in `01` §2.

**Rove Stealth / low-profile wedge-style models** — Confidence: Low.
A screenless or minimal-screen body designed to sit discreetly behind the mirror.
**This is the single most consequential model fact to verify**, because a screenless model
invalidates every "ask the caller to read the screen aloud" step in this taxonomy — currently
the agent's primary evidence-gathering move (`WIFI-02`, `REC-02`, `SD-01`). If any in-scope
model has no screen, the taxonomy needs a parallel evidence path built on LED colour and beep
patterns instead.

**Rove Horizon / wide-angle or 360-type model** — Confidence: Low.
Recalled as a Rove name; capabilities unclear. Listed only so that Step 1b checks for it.

**Discontinued units still in customers' hands** — Confidence: Medium that these exist in
meaningful numbers (the line has been on sale since the late 2010s), Low on which ones. These
are also the callers most likely to be running firmware that no current release note describes.

**Cross-model hypotheses:**

| Claim | Confidence | Affects |
|---|---|---|
| Wi-Fi is 2.4 GHz only; no 5 GHz | High (class), Medium (Rove) | `WIFI-02` cause 4, `WIFI-05` cause 5 |
| The camera accepts one connected client at a time | Medium | `APP-04` cause 1 — currently `Unknown` |
| No cloud, no LTE, no remote access; everything is local and caller-performed | Medium–High | `01` §4 scope, `WIFI-01` (no internet route) |
| GPS is built in across the 4K line | Medium | A missing category — see §5 below |
| The device UI is button-driven menus, not touch | Medium | Every spoken menu path Step 1b has to collect |

---

### 2. Likely app and connection model

`Initial hypothesis — to verify` throughout.

- **App identity** — Confidence: Medium. A vendor-published "Rove" app on both iOS and Android.
  The exact listing name and current version are unverified, and the agent must not state a
  version number (`APP-02`).
- **Connection model** — Confidence: High (class), Medium (Rove). The camera hosts its own Wi-Fi
  access point. The phone joins that SSID — usually from the phone's own Wi-Fi settings,
  sometimes triggered from inside the app — and the app then talks to the camera directly over
  that local link. The camera provides **no internet route**.
- **SSID pattern** — Confidence: Low. Model name plus a serial or MAC fragment, in the shape of
  `ROVE_<model>_<hex>` — **pattern illustration only, NOT a verified SSID**. The agent must not
  tell a caller what name to look for; it should ask them to read out what they see.
- **Default password** — Confidence: Low. Dashcams in this class commonly ship with a simple
  numeric default. **No specific Rove default is known, and none may be guessed or spoken aloud.**
  `WIFI-03` already states this, and this section does not relax it.
- **Two consequences that drive this taxonomy** — Confidence: High that these mechanisms exist on
  current phones; Medium that they are the actual Rove failure:
  1. Because the camera's access point has no internet route, modern iOS and Android flag it as
     "no internet" and may silently move the phone back to cellular. That is `WIFI-01` cause 1,
     and probably the most common Wi-Fi complaint in the whole category.
  2. Recent OS versions gate local-device discovery behind a local-network or nearby-devices
     permission, and gate Wi-Fi scanning behind location on some Android versions. A denied — or
     OS-update-revoked — permission produces exactly the "connected but the app can't find it"
     signature in `APP-01`, `APP-02`, and `APP-03`.

---

### 3. SD card requirements — general dashcam knowledge, not Rove-verified

Everything in this subsection is **general product-class knowledge**, explicitly not a Rove
specification. The confidence column refers to the class claim, not to Rove.

| Claim | Confidence | Note |
|---|---|---|
| Dashcams need **high-endurance** cards; ordinary consumer cards fail early under continuous rewrite | High | The strongest general fact available to this taxonomy (`SD-04`) |
| 4K continuous recording wants **U3 / V30** sustained write as a floor; Class 10 / U1 is marginal | High | Rove's own stated minimum is `Unknown` |
| Cards should be **formatted in the camera**, not on a computer | High | A computer-formatted card is a very common cause of "card error" (`SD-01` cause 1) |
| Above 32 GB the expected filesystem is **exFAT**; Windows will not produce FAT32 above 32 GB without third-party tools | High | Why "I formatted it on my laptop" so often makes things worse |
| Dashcams commonly cap supported capacity at **128 GB or 256 GB**, and an over-capacity card may mount and then fail later | Medium | Rove's ceiling is `Unknown` and must not be quoted |
| A hard-worked dashcam card has a service life measured in **months to a couple of years** | Medium | Supports `SD-04` cause 1 |
| A card that needs reformatting every few weeks is at **end of life** | High | `SD-04`'s central hypothesis |
| Counterfeit cards reporting false capacity are common in this market | High | `SD-01` cause 5 |

**Consequence:** the *shape* of the cause rankings in `SD-01`, `SD-02`, and `SD-04` is probably
right. The *numbers* — capacity ceiling, minimum class, accepted filesystem — remain `Unknown`
and stay a Step 1b task. The agent may reason with the shape; it may not speak the numbers.

---

### 4. Likely firmware update method, and why updates break Wi-Fi and pairing

`Initial hypothesis — to verify` throughout.

**Two plausible paths. Which one Rove uses, per model, is `Unknown`:**

1. **Card-side file copy** — Confidence: Medium that this exists for at least some models.
   Download a firmware file on a computer, copy it to the root of a card that was formatted in
   the camera, insert the card, power the camera from a continuous supply, and let it flash on
   boot. The camera usually renames or deletes the file afterwards so it does not re-flash.
   This path is what makes `FW-04` potentially unsolvable by voice: it needs a computer and a
   card reader that the caller may not have.
2. **In-app over-the-air update** — Confidence: Low for Rove, Medium that it exists somewhere in
   the current line. The app downloads the firmware and pushes it over the camera's own Wi-Fi.

**Version numbering:** no real version is known. Where a version pattern is needed for
illustration only, write it as `e.g. 2.x — example pattern only, NOT a verified version`. The
agent must never state, infer, or confirm a firmware version to a caller.

**Why an update plausibly breaks Wi-Fi or pairing.** Each row is a hypothesis, and together they
are the reason `FW-03` sits upstream of half the Wi-Fi and app entries:

| Mechanism | Confidence | Presents as |
|---|---|---|
| The update resets settings to factory defaults, turning Wi-Fi, parking mode, audio, or the timestamp overlay off | Medium–High (class) | `FW-03`, `REC-04`, `VID-03` — looks exactly like a regression, costs one setting check to disprove |
| The update regenerates the SSID and/or password; the phone still holds the old saved network | Medium | `WIFI-03` — "wrong password" on a password the caller never changed |
| The camera-side protocol or API version is bumped and an older app build can no longer discover the camera | Medium | `APP-01`, `APP-02` — "connected but no device found" |
| A write interrupted by power loss leaves partial firmware | High (this is the mechanism of a brick) | `FW-01` turning into `FW-02` |
| The firmware file left sitting on the card consumes space, and on some designs is re-read at every boot | Medium | `SD-02`, plus a boot loop that looks like `FW-02` but clears with the card out |

That last row is why `FW-02`'s card-removed test is worth a turn: it is the cheapest
discriminator available for a symptom whose other branch is a dead device.

---

### 5. What this section changes about the taxonomy

Stated plainly, so Step 1b knows where to look first:

- **Three gaps are now visible.** These 28 entries carry no **rear-channel** entry (if a dual
  model exists), no **GPS / speed-overlay** entry (if GPS is built in), and no
  **mounting / adhesive / suction** entry — the last being, in general dashcam experience, one of
  the highest-volume complaints in the category and absent here entirely. Confidence that
  mounting belongs in a real taxonomy: High. Confidence that it ranks in Rove's top categories:
  Unknown without call-mix data (`01` §8 Q10).
- **One structural assumption may not hold.** Every "read the screen aloud" step assumes a
  screen. See the Stealth note in §1.
- **The strongest hypotheses are also the cheapest to verify.** `SD-01`/`SD-04` (card class and
  endurance) and `WIFI-01` (no-internet auto-switch) are general class facts that a single manual
  page or a single phone settings screen would confirm or kill.
- **Nothing here promotes any entry to speakable.** The `Evidence` field on all 28 entries is
  unchanged. This section adds a reasoning layer, not a source.

---

## How to read an entry

| Field | Meaning |
|---|---|
| **Symptom (caller)** | How this arrives by voice, in the caller's words. Not a diagnosis. |
| **Models** | `Unknown` throughout — we have no verified model list. See `01` §8 Q2. |
| **Must ask** | The missing information without which the agent cannot rank causes. Asked **one per turn** (`01` §2). |
| **Causes (ranked)** | Most to least likely, by inference. Ranking is unvalidated. |
| **Next step** | The cheapest step that *discriminates between* the top causes, not the most common fix. All `TO VERIFY`. |
| **Most plausible next step (initial hypothesis)** | Added 2026-11-07. One concrete step drawn from model knowledge, with one line on why it splits the top two causes. `Initial hypothesis — to verify`, with a confidence level. Not cleared to speak. |
| **What would confirm / disconfirm it** | Added 2026-11-07. The observable caller answer that decides which branch the call takes next. This is the field that makes the hypothesis testable in a prototype. |
| **Escalate when** | The trigger that ends diagnosis and hands to a human. |
| **Evidence** | `Review signal (unretrieved)` / `Inferred`. Never `Official doc` in v0. |

**Discriminating-step principle:** prefer a step whose outcome splits the cause list. A step
that "usually works" but tells you nothing when it fails is worth less on a voice call, where
every step costs a turn and the caller's patience.

**Cross-cutting rule — the change event.** Before any category default fires, establish what
changed: firmware update, new phone, phone OS update, new SD card, new mounting, new vehicle,
new power source, weather change. A stated change event re-ranks every cause list below
(`01` §5, "category collapse").

**Cross-cutting escalation triggers** (apply to all 28 entries, in addition to each entry's own):

1. Two next-steps attempted, symptom unchanged.
2. The agent's top hypothesis repeats for a third turn with no new information.
3. Caller reports smoke, burning smell, swelling, heat damage, or exposed wiring — stop
   diagnosis immediately, instruct to disconnect, escalate.
4. Caller needs footage for an insurance claim, a police report, or litigation, and any
   candidate step risks that footage.
5. Caller is driving (`01` §2 safety gate) — defer, do not diagnose.
6. Request leaves scope: billing, RMA, warranty, returns, non-Rove device (`01` §4).

---

## Category A — Wi-Fi connectivity (WIFI-01 … WIFI-05)

### WIFI-01 — Phone connects to the camera, then drops back to cellular
- **Symptom (caller):** "It connects for a second and then my phone just goes back to normal internet. It says no internet so it kicks me off."
- **Models:** Unknown
- **Must ask:** 1) iPhone or Android, and roughly which OS version; 2) does the phone show the camera's network as connected at the moment the app fails; 3) was this working before, and what changed.
- **Causes (ranked):** 1. Phone OS auto-switching away from a network with no internet route (the camera's AP has no uplink). 2. Phone "smart network switch" / Wi-Fi assistant setting. 3. Camera AP idle timeout dropping the client. 4. Signal/distance — phone inside, camera on the windscreen.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — have the caller re-connect and, when the phone offers to stay on a network with no internet, accept and keep it. Exact prompt wording and setting name differ per OS version and are **Unknown**; the agent must not speak a menu path it cannot verify.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §"'No Internet' message? That's normal"; `data/raw/help-center/wifi-connected-disconnected.html`; `data/text/manuals/User Manual For New R2-4K.txt` §WIFI (p.61) — **the cause is confirmed, the step is not.** There is no camera-side AP timeout to discriminate against: Wi-Fi offers `OFF` / `ON - Once` / `Always On` and "can stay ON at all times". The documented action is to accept the no-internet prompt and keep the connection — **iPhone: tap "Keep Trying Wi-Fi"; Android: wait 10–15 seconds for the pop-up, then tap "Always connect"** (or tick "Don't ask again for this network" → YES). Rove states the cause outright: the camera gives no internet, so the phone leaves — "this is how Apple designed its operating system to work".
- **What would confirm / disconfirm it:** The caller says the camera's network is still in the list but the phone has moved itself back to mobile data → phone-side auto-switching (causes 1–2). The network vanishes from the list at the moment of the drop → camera-side (cause 3), and the phone is not the variable.
- **Escalate when:** the phone never holds the connection across two attempts, or the OS setting path cannot be established by voice.
- **Evidence:** Review signal (unretrieved) + Inferred.

### WIFI-02 — Camera's network does not appear in the phone's Wi-Fi list
- **Symptom (caller):** "I don't even see it. There's nothing in my list that looks like the camera."
- **Models:** Unknown
- **Must ask:** Is the camera powered on and awake right now, and does its screen show anything about Wi-Fi?
- **Causes (ranked):** 1. Wi-Fi not enabled on the camera, or the camera must be put into a pairing/Wi-Fi mode first. 2. Camera asleep / in parking mode / powered down with ignition off. 3. Camera busy recording and not broadcasting (behaviour **Unknown** per model). 4. Phone scanning a band the camera does not use. 5. Camera fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — confirm the camera is awake and in whatever mode exposes its network. The menu path and the mode's name are **Unknown**; ask the caller to read the screen aloud rather than guiding blind.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §"How to turn on WiFi on each ROVE model" and §"Can't see the ROVE network?"; `data/raw/help-center/wifi-not-connecting.html`; `data/raw/help-center/wifi-name-not-showing.html` — reading the screen is sound, but the documented first move is to **switch Wi-Fi on at the camera** using the model-specific control: **R2-4K and R2-4K PRO — press and hold the Emergency Lock button for 2 seconds** (or System Settings > WiFi); **R3 — tap the screen > Settings > System Settings > WiFi icon** (solid red = on). Cause 4 is verified and under-ranked: on **DUAL, DUAL PRO and R3** the camera may be broadcasting on 5 GHz, which some phones will not list — **change WiFi Mode from 5 GHz to 2.4 GHz in the camera's System Settings**. On the R2-4K there is nothing to switch (2.4 GHz only). Range is about 10 m / 33 ft.
- **What would confirm / disconfirm it:** The caller reads out a network name or describes a Wi-Fi symbol on the camera's screen → the camera is broadcasting and the problem is phone-side scanning or band. No Wi-Fi indication of any kind on a camera confirmed awake → camera-side mode or fault.
- **Escalate when:** the camera shows no Wi-Fi indication at all after being confirmed awake — suspected camera-side fault.
- **Evidence:** Review signal (unretrieved) + Inferred.

### WIFI-03 — Password rejected
- **Symptom (caller):** "It keeps saying wrong password. I'm typing what it says on the screen."
- **Models:** Unknown
- **Must ask:** Where is the caller reading the password from — the camera's screen, the manual, or a sticker?
- **Causes (ranked):** 1. Password changed previously and forgotten. 2. Case-sensitivity or character confusion (0/O, 1/l/I, 5/S) — a voice-specific hazard. 3. Reading a password that belongs to a different device. 4. Phone cached a stale password for a previously-saved network of the same name.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — have the phone forget the saved network and re-enter, with the password read back character by character including case (`01` §2, no copy-paste). Default credentials are **Unknown** and must never be guessed aloud.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` pp.33, 61; `data/text/manuals/ROVE R2-4K User Manual.txt` pp.33, 57; `data/text/manuals/dc3831.txt` pp.33, 44; `data/text/manuals/r3-manual-website-files.txt`; `data/raw/official/connect-rove-to-phone.html` §FAQ — the forget-and-re-enter step stands, but **the entry's central restriction is wrong. The default Wi-Fi password is `12345678`**, published in four manuals and on the official site, and **the camera displays it on its own screen while Wi-Fi is on**. The agent may state it and ask the caller to compare. Cause 1 remains live: the Wi-Fi name and password *can* be changed by the owner (`data/raw/help-center/know-your-dashcam-how-to.html` §"How to change the WiFi name and password of my dash cam?"), so a rejection on `12345678` is informative, not conclusive.
- **What would confirm / disconfirm it:** The connection succeeds after the forget-and-read-back → character confusion or a cached credential (causes 2 and 4). Still rejected with every character confirmed → the password was changed, or belongs to another device (causes 1 and 3), which heads toward the gated reset.
- **Escalate when:** the caller cannot locate any password source on the device, and reset-to-default would be the only path (destructive gate, `01` §5).
- **Evidence:** Inferred.

### WIFI-04 — Connection drops every few minutes
- **Symptom (caller):** "It stays on for maybe two minutes and then I lose it and have to start over."
- **Models:** Unknown
- **Must ask:** Does it drop at a consistent interval, and is the phone in the car or has the caller walked away from it?
- **Causes (ranked):** 1. Camera-side idle/session timeout by design (duration **Unknown**). 2. Phone moving out of range. 3. Phone roaming to a remembered home/other AP. 4. Interference, including from the vehicle's own hotspot. 5. Camera overheating and cycling (cross-check `PWR-02`).
- **Next step:** `TO VERIFY` · `Initial hypothesis` — reproduce once while standing beside the camera with no other known network in range, and time the drop. A consistent interval points to a designed timeout; a variable one points to range or interference.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/text/manuals/ROVE R2-4K User Manual.txt` §WIFI VOICE GUIDANCE (p.63); `data/text/manuals/User Manual For New R2-4K.txt` p.61; `data/raw/official/connect-rove-to-phone.html`; `data/text/manuals/r3-manual-website-files.txt` §"Wi-Fi Connection Issues" — **cause 1 is not supported by any Tier 1 source and the manual says the opposite:** "ROVE dash cams are equipped with a WiFi feature that can stay ON at all times", with an `Always On` setting that survives restart. No idle or session timeout is documented anywhere. The documented causes are **range — about 10 m / 33 ft with no obstructions** — and phone-side priority switching away from a no-internet network, named for Apple devices specifically. Step becomes: confirm the caller is within 10 m with line of sight to the camera, then treat as `WIFI-01`.
- **What would confirm / disconfirm it:** The link holds while the app is busy and drops only after the caller stops interacting → designed idle timeout (cause 1), likely not a fault. It still drops mid-stream at a consistent interval → a camera-side session limit; at a variable interval → range, interference, or `PWR-02`.
- **Escalate when:** the drop is consistent *and* occurs mid-transfer, making the app unusable for its stated purpose.
- **Evidence:** Review signal (unretrieved).

### WIFI-05 — Connected, but playback or download is unusably slow
- **Symptom (caller):** "It connects fine but when I try to watch a video it just buffers forever."
- **Models:** Unknown
- **Must ask:** Is the caller trying to play the video in the app, or download it to the phone first?
- **Causes (ranked):** 1. Streaming high-bitrate footage over a slow link — expected behaviour, not a fault. 2. Distance and windscreen/metal obstruction. 3. Card read speed limiting transfer. 4. Phone storage full, stalling the download. 5. Band/throughput ceiling of the camera's radio (**Unknown**).
- **Next step:** `TO VERIFY` · `Initial hypothesis` — try the lower-resolution/preview stream if one exists, or download rather than stream. Whether a preview stream exists per model is **Unknown**.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §"How to turn on WiFi on each ROVE model", §Tip and §FAQ "How fast are downloads?"; `data/text/manuals/B0F9SX3JB9.txt` §"Dual Band WiFi 6"; `data/text/manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.txt` §3 — ask the caller to download one short clip rather than play it, and report whether it completes and roughly how long it takes. Tier 1 now supplies the figures to judge the answer against: **R2-4K — WiFi 6 on 2.4 GHz, speed "not stated in the manual"; R2-4K DUAL — up to 20 MB/s; DUAL PRO and R3 — up to 30 MB/s over 5 GHz.** Two additions: joining from the phone's own Wi-Fi settings rather than through the app is "about 2× faster", and on DUAL / DUAL PRO / R3 a phone sitting on the camera's 2.4 GHz band will be far slower than on 5 GHz — check the band before calling it a fault. Lagging playback **on a PC** is attributed to high bit-rate files and a slow computer, not to the link (`User Manual For New R2-4K.txt` §Troubleshooting, p.76).
- **What would confirm / disconfirm it:** A short clip downloads in a reasonable time but playback still stalls → expected behaviour on a slow local link (cause 1); close honestly. The download also crawls or fails outright → link, card read speed, or phone storage (causes 2–4), which is a real fault path.
- **Escalate when:** even a short download fails repeatedly, which moves suspicion to the card (`SD-03`) or the camera.
- **Evidence:** Review signal (unretrieved) + Inferred.

---

## Category B — Firmware update / compatibility (FW-01 … FW-04)

### FW-01 — Update stalls partway
- **Symptom (caller):** "It got to about halfway and just sat there. I left it twenty minutes."
- **Models:** Unknown
- **Must ask:** Was the camera on continuous external power for the whole update, or running on its internal power?
- **Causes (ranked):** 1. Power interruption mid-write (ignition cut, loose plug). 2. Wrong or partially-copied firmware file. 3. Card fault or wrong card state. 4. Update genuinely still running — some writes are slow and look stalled.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — **do not** power-cycle as the first move; a cut during a write is what creates `FW-02`. First establish whether the camera shows any activity indicator. The safe wait time before a power-cycle is **Unknown** and must come from a Rove source.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/raw/official/update-firmware-r2-4k.html` §"AT A GLANCE"; `data/raw/official/firmware-update-downloads.html` §"Manual Firmware Update Guide" (heading: **"Don't Disconnect the Power"**) and §"Over The Air Firmware Update" — tell the caller explicitly not to unplug anything yet, then ask them to watch for a full minute and say whether any indicator is still changing. **The indicator can now be named instead of described.** Card-side update: "you should see the blinking RED LED which means the firmware is being updated" / "the flashing RED/BLUE LED on the left upper corner". OTA update: "the camera screen will display the progress of the firmware update — allow the update to complete without interruption." Completion signal on both paths: **the camera restarts by itself.** Rove's own instruction is "let it go through its cycle and make sure the power doesn't get disconnected during the firmware update".
- **What would confirm / disconfirm it:** Any indicator moving, blinking, or a percentage advancing within that minute → the write is live; keep waiting and keep power on. Nothing changes at all over a full minute on confirmed continuous power → halted, and the call escalates rather than power-cycling.
- **Escalate when:** no activity indication and the caller has already power-cycled — treat as potential `FW-02`.
- **Evidence:** Inferred. **High-risk entry: the wrong advice here destroys the device.**

### FW-02 — Device will not boot after an update
- **Symptom (caller):** "Since the update it just shows the logo and nothing happens. It's dead."
- **Models:** Unknown
- **Must ask:** What exactly is on the screen, and does anything change if external power is removed and reapplied once?
- **Causes (ranked):** 1. Interrupted firmware write. 2. Incompatible firmware for this hardware revision. 3. Card holding a bad firmware file that the camera re-reads on every boot. 4. Coincidental hardware failure.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — removing the SD card and powering on is a plausible discriminator (it tells you whether a file on the card is driving the loop), but whether this is safe and whether a recovery path exists is **Unknown**. **Firmware downgrade is never agent-initiated** (`01` §5).
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/raw/official/firmware-update-downloads.html` §"Manual Firmware Update Guide"; `data/raw/official/update-firmware-r2-4k.html`; `data/raw/help-center/camera-does-not-turn-on.html` §"Remove the memory card" and §"Perform a hard reset"; `data/text/manuals/r3-manual-website-files.txt` §"Display and Touch Screen Issues" — while the escalation is already in motion, have the caller power down, remove the card, and power on once with the card out. **Cause 3 is officially acknowledged:** Rove instructs formatting the card immediately after any update "so your camera does not keep updating the firmware every time it restarts", and the Help Center runs the same card-out test ("if the camera turns on without the card, the memory card may be corrupted or incompatible"). Two model facts the entry lacked: the **R2-4K family has a RESET button on the bottom of the camera, beside the serial-number label (R2XXXXXXXXX)**, pressed with a paper clip while powered; the **R3 has no reset button** — there, a failed update presents as missing icons or a dead touchscreen and the documented route is to email customer care for a manual reflash.
- **What would confirm / disconfirm it:** The camera behaves differently with the card out — gets past the logo, shows a no-card message, or errors differently → a file on the card is driving the loop (cause 3). An identical logo hang with the card removed → internal, and the human owns it from there.
- **Escalate when:** immediately, in parallel with any step. This is a suspected-brick case and a human owns the outcome. The agent may suspect hardware; it may not declare it (`01` §4).
- **Evidence:** Review signal (unretrieved). **Escalation-first entry.**

### FW-03 — Something that worked before the update stopped working after it
- **Symptom (caller):** "It was fine. I did the update because it told me to, and now the parking mode doesn't work."
- **Models:** Unknown
- **Must ask:** What is the firmware version now, and what was it before (if the caller knows)?
- **Causes (ranked):** 1. Known regression in a specific build — **this is the single highest-value thing to check and we have no feed for it** (`01` §8 Q5). 2. Update reset settings to defaults, and the feature is simply off now. 3. Feature behaviour changed intentionally in the new build. 4. Unrelated coincident fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — check whether the relevant setting survived the update before doing anything else. A settings reset mimics a regression and is far cheaper to fix. The settings menu path is **Unknown**.
- **Most plausible next step (initial hypothesis):** **UNVERIFIED** (Step 1b, `05`) · Searched: all 6 manuals, 3 official pages, 12 Help Center pages — no hit. **No Tier 1 source states that a firmware update resets settings to defaults.** The step is not contradicted, it is simply unevidenced, and stays `TO VERIFY` — not speakable. What the corpus does hold, and the agent may use as context only: two specific real post-update issues (a compass-direction bug *fixed* by updating, and a failed update leaving icons missing or the touchscreen unresponsive — `data/text/manuals/r3-manual-website-files.txt`), and a recurring "restore default settings, set date/time, then format the card" opening in several official flows (`data/raw/help-center/missing-videos.html`; `data/raw/help-center/r3-no-gps-live-speed.html` §Step 4). **There is still no public known-issue or release-note feed** (`01` §8 Q5), so this entry remains undiagnosable and escalation-bound.
- **What would confirm / disconfirm it:** The setting is off → the update reset it; re-enable, retest, and the call can close. The setting is confirmed on and the feature still does nothing → a suspected regression, which the agent cannot confirm without a known-issue feed (`01` §8 Q5) and must escalate.
- **Escalate when:** the setting is present and correct and the feature still fails — that is a suspected regression and must reach someone who can confirm against a known-issue list.
- **Evidence:** Review signal (unretrieved) + Inferred.

### FW-04 — Caller cannot carry out the update at all
- **Symptom (caller):** "I downloaded the file but I don't know what to do with it. I don't have a computer here."
- **Models:** Unknown
- **Must ask:** Does the caller have access to a computer and a card reader, or is the phone their only device?
- **Causes (ranked):** 1. No computer available and the update path requires one. 2. File downloaded but still zipped/renamed by the browser. 3. File placed in a subfolder rather than where the camera looks. 4. Wrong file for the model.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — establish which update paths exist for this model (over-the-air via app vs. card-side file copy). Which paths exist is **Unknown**, and this determines whether the call can succeed at all (`01`, "What is still unknown").
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §"How to update your dash cam's firmware"; `data/raw/official/firmware-update-downloads.html` §"Over The Air Firmware Update"; `data/text/manuals/User Manual For New R2-4K.txt` §FIRMWARE UPDATE (p.12); `data/text/manuals/ROVE R2-4K User Manual.txt` §FIRMWARE UPDATE (p.12) — **do not ask the caller to go and find out whether an in-app path exists. It does, on every current model, and its location is published — navigate them to it.** Connect the phone to the camera's Wi-Fi → open the ROVE app → **"Firmware Update" in the app's left menu** → follow the on-screen steps → keep the camera powered until it restarts itself. The card-side path is the documented fallback: format the card in the camera → copy the **unzipped** firmware files to the card → camera plugged in and **switched OFF** → insert card → **press Power once** → red LED blinks → camera restarts → **format the card again** or it re-flashes at every restart. A caller with no card reader can reach the card over USB with **"Connect as USB Flash Drive"** — except on the **DUAL PRO, which cannot connect to a computer at all** and must use the app or a card reader. **The entry's open question is answered: a phone-only caller can complete an update.**
- **What would confirm / disconfirm it:** The app shows an update entry for the camera → an app-side path exists and the computer is unnecessary. No such entry anywhere, and the caller has no computer and card reader → the only known path needs hardware they do not have; defer or escalate rather than improvise a file procedure.
- **Escalate when:** the only available path needs hardware the caller does not have — a voice call cannot close this.
- **Evidence:** Inferred.

---

## Category C — Mobile app pairing (APP-01 … APP-04)

### APP-01 — Phone is on the camera's Wi-Fi, but the app says no device found
- **Symptom (caller):** "My phone says I'm connected to the camera but the app just spins and says it can't find it."
- **Models:** Unknown
- **Must ask:** Does the phone's Wi-Fi screen show the camera's network as connected *right now*, while the app is open?
- **Causes (ranked):** 1. Local-network / local-device permission not granted to the app. 2. App connected to a stale cached session; needs a full close and reopen. 3. Camera left the pairing mode while the caller was in the phone's settings. 4. App version and firmware version mismatch. 5. VPN or private-relay feature on the phone intercepting local traffic.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — fully close the app (not just background it) and reopen while the Wi-Fi connection is confirmed live. This is cheap and discriminates cause 2 from the rest. Exact permission names per OS are **Unknown**.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §Step-by-step (caption: "tap Retry Connect to Dash Cam if it doesn't connect on its own"); `data/raw/help-center/wifi-not-connecting.html`; `data/raw/help-center/wifi-name-not-showing.html` — a swipe-close is not the documented move. Tier 1's cheap first steps are **tap "Retry Connect to Dash Cam" on the app's Live Video screen**, and **confirm the correct dash cam model is selected in the app** — a failure mode this entry does not carry at all and which Rove calls out twice. Tier 1's stale-session remedy is heavier than a restart: clear the app cache, or uninstall and reinstall, then **allow all permissions**. Two causes confirmed and two added: VPN interception is named explicitly ("turn OFF your VPN / anti-virus software / Wi-Fi calling"), **a memory card must be inserted for the camera's Wi-Fi to work at all**, and CarPlay / Android Auto and cellular data should be turned off on the phone.
- **What would confirm / disconfirm it:** The camera appears on reopen → stale session (cause 2), resolved. Still "no device found" with the phone confirmed on the camera's network at that moment → permission, pairing-mode, or app/firmware mismatch (causes 1, 3, 4, 5).
- **Escalate when:** permissions are confirmed granted, the Wi-Fi link is confirmed live, and the app still cannot see the device.
- **Evidence:** Review signal (unretrieved) + Inferred.

### APP-02 — App broke after a phone OS update
- **Symptom (caller):** "It used to work. I updated my phone and now the app won't even open properly."
- **Models:** Unknown
- **Must ask:** Which phone OS version is it on now, and did the app also update around the same time?
- **Causes (ranked):** 1. OS update revoked or reset a permission the app depends on. 2. App version predates the OS and is incompatible. 3. OS tightened local-network handling. 4. Coincidence; the camera changed, not the phone.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — confirm the app is on its current version before touching anything else, since an outdated app makes every other step meaningless. Current app version numbers are **Unknown**.
- **Most plausible next step (initial hypothesis):** **UNVERIFIED** (Step 1b, `05`) · Searched: all 6 manuals, 3 official pages, 12 Help Center pages — no hit. **Nothing in the Tier 1 corpus mentions phone OS updates, app-version compatibility, or the store listing's Update/Open button.** The only app-repair guidance Rove publishes is uninstall and reinstall from the official Android and iOS links, then allow all permissions (`data/raw/help-center/wifi-not-connecting.html`; `data/raw/help-center/sign-in-error-rove-app.html` §Step 4). The hypothesis is untested rather than wrong, and stays `TO VERIFY` — not speakable.
- **What would confirm / disconfirm it:** The store offers "Update" → the app is behind the new OS (cause 2); update first and retest. It reads "Open", so the app is already current → the OS update revoked or tightened a permission (causes 1 and 3), and the branch moves to `APP-03`.
- **Escalate when:** app is current, permissions are granted, and the failure persists — likely a real compatibility defect worth recording.
- **Evidence:** Review signal (unretrieved).

### APP-03 — App installs but never gets past the permission or setup screen
- **Symptom (caller):** "It keeps asking me for location. Why does a camera app need my location? I said no."
- **Models:** Unknown
- **Must ask:** Which permission prompt is on screen, and what did the caller answer?
- **Causes (ranked):** 1. A denied permission that the pairing flow genuinely requires (on some OS versions, Wi-Fi scanning is gated behind location). 2. Permission granted "once" and since expired. 3. Caller denied and the OS no longer re-prompts, so it must be changed in settings.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — explain *why* the permission is needed before asking for it again; a caller who refused on privacy grounds will refuse a second time without a reason. The exact permission set required is **Unknown** and the explanation must not be invented.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/raw/official/connect-rove-to-phone.html` §"Before you start"; `data/raw/help-center/wifi-not-connecting.html` — give the caller a one-sentence reason the permission is needed, then ask whether they are willing to allow it. **The reason no longer has to be invented; Rove publishes it:** "Allow location access when the app asks. The app uses it to find and auto-connect to nearby ROVE dash cams." The Help Center widens the set the agent should check: "grant access or permissions to the app, such as Location, Media Library, and Camera. Sometimes, phone apps are unable to connect to Wi-Fi without having the necessary permissions." The escalation trigger stands: a firm refusal is a product limitation, not a fault.
- **What would confirm / disconfirm it:** The caller accepts the explanation and grants it → misunderstanding, and pairing can proceed. The caller declines as a firm decision → a product limitation to state honestly and close on, not a fault to keep diagnosing.
- **Escalate when:** the caller declines the permission as a firm decision — that is a product limitation, not a fault to diagnose.
- **Evidence:** Inferred.

### APP-04 — Worked on the old phone, will not pair with the new one
- **Symptom (caller):** "I got a new phone. The camera still works with my old one but the new one won't pair."
- **Models:** Unknown
- **Must ask:** Is the old phone still nearby, and is it currently connected to the camera?
- **Causes (ranked):** 1. Camera supports one connected client at a time and the old phone is holding the slot. 2. Password known only to the old phone's saved networks. 3. Permissions not yet granted on the new phone (see `APP-03`). 4. Camera-side pairing list needs clearing.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — turn Wi-Fi off entirely on the old phone, then retry on the new one. This discriminates cause 1 in one move at no risk. Whether the camera is single-client is **Unknown**.
- **Most plausible next step (initial hypothesis):** **UNVERIFIED** (Step 1b, `05`) · Searched: all 6 manuals, 3 official pages, 12 Help Center pages — no hit. **No Tier 1 source states that the camera accepts only one connected client at a time.** Cause 1 is unevidenced and the old-phone test cannot yet be justified on the record; it stays `TO VERIFY`. One Tier 1 fact does reshape this entry and belongs in the cause list as the leading new-phone cause: **the ROVE app requires a registered account, and sign-up needs ordinary internet** — "create your free account first, while your phone is on home WiFi or mobile data. Don't connect to the dash cam's WiFi yet: the app needs normal internet to register you" (`data/raw/official/connect-rove-to-phone.html` §"Before you start"). Account and verification-email failures have their own article (`data/raw/help-center/sign-in-error-rove-app.html`).
- **What would confirm / disconfirm it:** The new phone pairs as soon as the old phone is off Wi-Fi → the camera accepts one client at a time (cause 1). The new phone still fails with the old one fully off-network → credentials or permissions on the new phone (causes 2 and 3), which is `WIFI-03` or `APP-03` territory.
- **Escalate when:** old phone is fully off-network and the new phone still fails after permissions are confirmed.
- **Evidence:** Inferred.

---

## Category D — Not recording / loop recording (REC-01 … REC-04)

### REC-01 — No footage of the incident the caller actually cares about
- **Symptom (caller):** "Somebody hit my car and there's nothing there. I need that video."
- **Models:** Unknown
- **Must ask:** Has the camera been used since the incident, and is it still recording right now?
- **Causes (ranked):** 1. Loop recording has already overwritten the clip (most likely if the camera kept running). 2. The camera was not recording at the time — power, card, or fault. 3. The file exists but is in a locked/event folder the caller has not checked. 4. Card fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — **stop further recording immediately** by removing the card or cutting power, before any diagnosis. Every minute of continued recording reduces the chance of recovery. This is the one case where the first step is preservation, not diagnosis.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §LOOP RECORDING "IMPORTANT" (p.46) and §NOTE (p.14); `data/raw/official/connect-rove-to-phone.html` §"How to move videos to a computer instead" — before any diagnostic question, have the caller power the camera down and remove the card, then set it aside untouched. **The ordering is now sourced and mandatory:** "do NOT insert/remove the memory card while the camera is turned ON — only do so when it is turned OFF", and "always turn the camera off before you remove or insert the memory card". **The urgency is greater than this entry assumed: locked event files are not permanently safe.** The event directory is capped at **30 % of the card**, and once that allocation is full "the camera will also delete your oldest locked video to add that new latest event video". Rove's own instruction: "download any locked video ASAP to prevent it from being deleted." Cause 3 (file sitting in a locked/event folder) is confirmed as a real, checkable branch.
- **What would confirm / disconfirm it:** The caller confirms the camera is off and the card is out → preservation achieved, and only then ask whether the camera has been running since the incident and whether they have checked a locked or event folder. If they say it has been recording ever since → the clip is probably already overwritten, and that must be said plainly rather than implied.
- **Escalate when:** always, if the footage matters for a claim or a report. Recovery is not a voice-agent task and the stakes are the caller's, not ours (`01` §8 Q7).
- **Evidence:** Review signal (unretrieved). **High-stakes entry: preserve first, diagnose second.**

### REC-02 — Camera is on but does not start recording
- **Symptom (caller):** "It turns on, the screen is on, but it never starts recording. No red dot, nothing."
- **Models:** Unknown
- **Must ask:** Is there an SD card in it right now, and does the screen show any message or icon?
- **Causes (ranked):** 1. No card, unreadable card, or full card with looping disabled (`SD-01`, `SD-02`). 2. Camera is in a mode that does not record (playback, settings, menu). 3. Recording was manually stopped and never restarted. 4. Firmware state after an update (`FW-03`). 5. Camera fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — have the caller read the screen aloud verbatim. An error string is worth more than any guess, and card-vs-mode is the first fork. Specific on-screen strings are **Unknown**.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §CAUTION under VOICE GUIDANCE (p.64) and §Troubleshooting (pp.75–77); `data/raw/help-center/missing-videos.html` §"Start recording and confirm the red dot/timer" — ask the caller to read out everything on the screen, word for word. **The targets are now concrete rather than open-ended:** the documented strings are **"Memory Card Error"**, **"Please Insert microSD Card"** and **"Card Full"**, and the positive indicator is "the flashing red dot and the recording timer counting up on the top-right area of the screen", started with the **OK** button. **A better voice-native opening also exists:** the camera has a failsafe that **announces every 30 seconds that it is NOT recording**, so the agent can ask what the caller *hears* — which costs the caller nothing and works while they are standing away from the car.
- **What would confirm / disconfirm it:** The screen mentions the card, or shows a no-card or format prompt → card branch (`SD-01`, `SD-02`). The screen shows playback, a menu, or a stopped state with no card complaint → mode branch, and the card is not the variable.
- **Escalate when:** card is confirmed present and healthy, the camera is confirmed in recording mode, and it still does not record.
- **Evidence:** Review signal (unretrieved).

### REC-03 — Loop recording overwrote files the caller wanted
- **Symptom (caller):** "It deleted my old videos by itself. I didn't delete anything."
- **Models:** Unknown
- **Must ask:** Was the clip ever locked or marked as an event, or was it a normal recording?
- **Causes (ranked):** 1. Loop recording working as designed — the caller does not know what loop recording is. 2. Event/G-sensor lock did not trigger, so the clip was treated as ordinary footage. 3. G-sensor sensitivity set too low. 4. Locked-file area full, so new locks silently fail or old locks get recycled.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — explain that loop recording overwrites oldest-first by design, then establish whether the caller needs the lock behaviour configured. Many of these calls are an expectation problem, not a fault, and should be closed as such — honestly.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §LOOP RECORDING "IMPORTANT" (p.46) and §Troubleshooting "Camera Locks many videos automatically" (p.76); `data/text/manuals/B0F9SX3JB9.txt` §"Emergency Video Lock" — the question is right; **the branch it feeds is wrong.** A locked clip disappearing is **not automatically a defect**: loop recording starts once normal + event files exceed **90 %** of the card, the directory is pre-allocated **60 % normal / 30 % event**, and when the event allocation is full "the camera will also delete your oldest locked video to add that new latest event video" — "you can't lock unlimited videos to your memory card". So the escalation trigger must change: escalate only if a locked clip vanished while the event area was demonstrably **not** full. A second documented cause this entry lacks: a G-sensor set too sensitive locks so many clips that the event area fills — "Camera Locks many videos automatically → change your G-Sensor Setting to a higher setting."
- **What would confirm / disconfirm it:** Ordinary unlocked clips → loop recording behaving as designed (cause 1); explain it and close honestly as a non-fault. The caller is confident a clip they locked has disappeared → a real defect in the lock or event path, which escalates.
- **Escalate when:** the caller asserts a clip *was* locked and it still vanished — that is a defect, not an expectation gap.
- **Evidence:** Review signal (unretrieved) + Inferred.

### REC-04 — Nothing recorded while the car was parked
- **Symptom (caller):** "It's supposed to record when I'm parked but there's nothing from overnight."
- **Models:** Unknown
- **Must ask:** How is the camera powered when the ignition is off — a hardwire kit, a battery pack, or the cigarette-lighter socket?
- **Causes (ranked):** 1. Socket is switched with ignition, so the camera has no power when parked — the most common and most invisible cause. 2. Parking mode not enabled, or reset by an update (`FW-03`). 3. Parking mode is motion/impact-triggered and nothing triggered it — working as designed. 4. Hardwire kit's low-voltage cutoff tripped to protect the car battery. 5. Card full with parking clips not looping.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — establish the power source first. If the camera has no power when parked, every setting-level step is wasted. Which models support which parking modes and which kits is **Unknown**.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §24-HR AUTO PARKING MODE (p.51), §AUTO POWER ON/OFF CAUTION (p.19) and spec table; `data/text/manuals/B0F9SX3JB9.txt` §"24-Hour Parking Monitor"; `data/text/manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.txt` §3; `data/text/manuals/r3-manual-website-files.txt` — ask how the camera is powered with the ignition off. **The hardware dependency is confirmed across the whole line: 24-hour parking mode requires the ROVE Ultimate USB Type-C Hardwire Kit, sold separately on every model including the DUAL PRO.** No kit, no parking mode, and no setting can substitute. Cause 1 is confirmed in Rove's own words — "some trucks'/cars' 12V cigarette outlet is always HOT" — with the converse (a socket that dies with the ignition) as the normal case. Cause 4 is now quantifiable: the kit's battery-drain cutoff is selectable at **11.8 / 12.0 / 12.2 / 12.4 V**. A kit that is fitted but mis-wired has its own symptom and article: "Hardwire kit Not Detected" (`data/raw/help-center/troubleshoot-index.html`).
- **What would confirm / disconfirm it:** The camera runs off the cigarette-lighter socket and the caller confirms the socket dies with the ignition → no power while parked (cause 1), and no setting can fix it. Continuous power is confirmed → move to the parking-mode setting and trigger-threshold branch (causes 2–5).
- **Escalate when:** power is confirmed continuous, parking mode is confirmed enabled, and no clips are produced.
- **Evidence:** Review signal (unretrieved) + Inferred.

---

## Category E — SD card / storage (SD-01 … SD-04)

### SD-01 — Card error on screen
- **Symptom (caller):** "It says card error. Or insert card. It's in there, I can see it."
- **Models:** Unknown
- **Must ask:** What is the card's brand, capacity, and speed marking, and how long has it been in use?
- **Causes (ranked):** 1. Card not formatted in the camera (formatted on a computer, or filesystem the camera does not accept). 2. Card worn out — dashcam write cycles kill cards, and this is the single most common consumable failure in this product class. 3. Card not seated, or inserted the wrong way round. 4. Capacity or speed class outside what the camera supports (limits **Unknown**). 5. Counterfeit card reporting a false capacity. 6. Card slot fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — reseat the card first (free, instant, and rules out the dumbest cause), then establish the card's specs. **Formatting is a destructive step** and is gated: it needs an explicit cause, the caller's consent, and the consequence stated aloud (`01` §5).
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §Troubleshooting "Camera showing 'Memory Card Error' or 'Please Insert microSD Card'" (p.77) and "microSD Card is crooked" (p.76); `data/raw/help-center/memory-card-too-slow.html` — **reseating is not Rove's documented procedure for this error, and a sharper discriminator exists.** The official order is: (1) confirm the card is at least **Class 10 / U3** and from a trusted vendor — "there are many fake cards out there online, remember if it's cheap, it's fake"; (2) **format in the camera**, power off, unplug and re-plug; (3) **hold MENU to switch to PHOTO mode and press OK** — "if you hear the shutter sound, then your camera is fine — replace your memory card. If you still get the same memory card error message, then your camera's memory card assembly has become defective." **That photo test splits card from slot on one action**, which is what this entry wanted reseating to do, and it is official. Seating is still worth a sentence, but as orientation rather than reseating: "align the microSD card with the gold contacts facing towards the Lens." The formatting gate in `01` §5 still applies to step 2.
- **What would confirm / disconfirm it:** The error clears on reseating → contact or seating (cause 3), resolved for free. The error returns immediately on a card confirmed correctly seated → move to brand, capacity, speed marking, and age, which separates wear (cause 2) from a format or spec mismatch (causes 1, 4, 5).
- **Escalate when:** a second, known-good card produces the same error — that points at the slot, i.e. hardware.
- **Evidence:** Review signal (unretrieved). **Strongest single hypothesis in the taxonomy; still unverified.**

### SD-02 — "Memory full", recording stops instead of looping
- **Symptom (caller):** "It just says full and stops. I thought it was supposed to record over the old stuff."
- **Models:** Unknown
- **Must ask:** Roughly how much of the card is taken up by locked or protected event files?
- **Causes (ranked):** 1. Card filled with locked/event files that loop recording is not allowed to overwrite. 2. Loop recording disabled in settings, or reset by an update. 3. Non-video files on the card (photos, the firmware file from `FW-04`) consuming space. 4. Filesystem damage making free space unusable.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — establish the locked-file volume before proposing any deletion. If locked files are the cause, the fix is selective and the caller must choose what to lose. The menu path to review locked files is **Unknown**.
- **Most plausible next step (initial hypothesis):** **REJECTED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` §LOOP RECORDING (p.46) and §Error/Message "Card Full" (p.75); `data/text/manuals/dc3831.txt` p.43 — **the discriminating premise does not exist, so the question is not worth a turn.** Locked files filling the card *cannot* stop recording: when the event allocation (30 %) is full the camera deletes the oldest locked file and carries on. Cause 1 should be struck. The documented cause of a hard stop is cause 2 alone — **Loop Recording set to OFF**: "the camera will continue to record each file 4GB in size until the memory card becomes full and then it will give you a 'Card Full' message. It will NOT record any further until you either delete files to make room or format the memory card." **Replacement step:** ask the caller to check **Video Mode settings > Loop Recording** and report whether it reads OFF or a duration. Documented fix: format, then set Loop Recording to 1, 3, 5 or 10 minutes.
- **What would confirm / disconfirm it:** A substantial number of deliberately saved or event-locked clips → locked files are consuming the card (cause 1), and any deletion is selective and caller-chosen. Few or none → loop recording disabled, or non-video files on the card (causes 2 and 3).
- **Escalate when:** locked files are not the cause, loop recording is confirmed on, and the card still fills and stops.
- **Evidence:** Inferred.

### SD-03 — Files play on the camera but are corrupt on the computer
- **Symptom (caller):** "I can see them on the camera but when I put the card in my laptop half of them won't open."
- **Models:** Unknown
- **Must ask:** Were the files copied off the card first, or is the caller playing them directly from the card?
- **Causes (ranked):** 1. Card removed or powered off mid-write, leaving the last clip unfinalised. 2. Failing card producing read errors. 3. Player on the computer lacks the right codec — the file is fine. 4. Copy interrupted. 5. Power instability during recording (cross-check `PWR-04`).
- **Next step:** `TO VERIFY` · `Initial hypothesis` — try a different player on the computer before concluding the files are damaged. Codec problems and corruption look identical to a caller and this separates them at zero cost.
- **Most plausible next step (initial hypothesis):** **VERIFIED** (Step 1b, `05`) · Source: `data/text/manuals/User Manual For New R2-4K.txt` p.11 and §"Correct Video Player To Play 4K VIDEOS" (p.41); `data/text/manuals/dc3831.txt` p.11 and p.38; `data/raw/official/connect-rove-to-phone.html` §"Playing videos"; `data/raw/help-center/no-audio-sound.html` — ask the caller to open one failing file in a different player. **This is Rove's own advice, and the player can now be named rather than described: VLC Media Player, and explicitly "do NOT use Windows Media Player or QuickTime Player (Mac)" — they are not made for these files.** `O2` repeats the VLC recommendation; the Help Center uses the same move for audio ("try playing the file in a different media player if needed"). One cause to add: slow or stuttering playback on a PC is attributed to high bit-rate 4K files and a slow computer, not to corruption — "please record videos at lower resolution and try again."
- **What would confirm / disconfirm it:** The file plays in a different player → the files are fine and the player was the problem (cause 3); nothing is broken. The same files fail in every player, after being copied off the card cleanly → real corruption (causes 1, 2, 4, 5), and the branch moves to the power path.
- **Escalate when:** multiple players fail on multiple files copied cleanly — likely a failing card plus possible data-recovery need.
- **Evidence:** Review signal (unretrieved) + Inferred.

### SD-04 — Card keeps needing to be reformatted
- **Symptom (caller):** "Every couple of weeks it stops working and I have to format it again."
- **Models:** Unknown
- **Must ask:** Is this the same card each time, and is it rated for continuous recording?
- **Causes (ranked):** 1. Card at end of life — a repeating format cycle is the classic wear signature. 2. Card not rated for dashcam write loads (ordinary consumer card in a continuous-write role). 3. Power interruptions corrupting the filesystem repeatedly (cross-check `PWR-03`, `PWR-04`). 4. Counterfeit card.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — swap to a different card and observe over the next week. This is a slow test, so the call ends without a confirmed resolution and must be marked as such, not closed (`01` §5, "false resolution"). Required card ratings are **Unknown**.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium — ask for the card's brand, its capacity, and the speed and endurance markings printed on it. It discriminates between "an ordinary consumer card doing a job it was never rated for" and "the camera corrupting a perfectly suitable card", which are the two live causes, and it does so before committing the caller to a week-long swap test.
- **What would confirm / disconfirm it:** An ordinary consumer card with no endurance rating → wrong card for continuous recording (cause 2), and a correctly rated replacement is the test. A high-endurance, U3/V30-class card of reasonable age failing the same way → suspicion moves to the camera's power or write path (cause 3), which is an escalation, not a card purchase.
- **Escalate when:** a new, correctly-rated card shows the same cycle within days — that moves suspicion to the camera's power or write path.
- **Evidence:** Review signal (unretrieved).

---

## Category F — Power / overheating (PWR-01 … PWR-04)

### PWR-01 — Will not power on
- **Symptom (caller):** "Nothing. No lights, no screen, nothing at all."
- **Models:** Unknown
- **Must ask:** Does anything else work from that same socket in the car, and has the caller tried a different cable or adapter?
- **Causes (ranked):** 1. Blown fuse on the accessory socket circuit — very common and nothing to do with the camera. 2. Failed cable or car adapter (the cable fails far more often than the camera). 3. Socket switched off with the ignition. 4. Internal power component failure. 5. Camera fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — test the same socket with any other device. One answer eliminates the whole car-side branch, and it is the cheapest discriminator in the taxonomy.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: High (this is car-side, not Rove-specific) — ask whether any other device works from that same socket. It discriminates by eliminating or confirming the entire car-side branch — blown fuse and ignition-switched socket together — on one answer, which makes it the cheapest discriminating step anywhere in this taxonomy.
- **What would confirm / disconfirm it:** Nothing else works from that socket → fuse or socket (causes 1 and 3); the camera is probably fine and this is not really a camera call. Another device works there → the socket is live, which moves the call to the cable and adapter (cause 2), and then to suspected hardware.
- **Escalate when:** the socket is confirmed live, a second known-good cable is confirmed, and the camera stays dead — suspected hardware, escalate (the agent does not declare it, `01` §4).
- **Evidence:** Inferred.

### PWR-02 — Shuts down in heat
- **Symptom (caller):** "On hot days it just turns itself off. In winter it's fine."
- **Models:** Unknown
- **Must ask:** Is the camera in direct sun on the windscreen, and does it recover on its own once the car cools?
- **Causes (ranked):** 1. Thermal protection cutting off by design — expected behaviour in a parked car in direct sun. 2. Mounting position with no airflow, behind glass, in full sun. 3. Internal battery degradation (swelling is a safety stop — see cross-cutting trigger 3). 4. Power adapter overheating rather than the camera.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — establish whether it recovers once cool. Recovery points to thermal protection working; no recovery points to damage. Operating temperature limits are **Unknown** and must not be quoted.
- **Most plausible next step (initial hypothesis):** **CORRECTED** (Step 1b, `05`, amended by Milestone 4.3) · Source: `data/raw/help-center/overheating.html` (whole article); `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §NOTE under 24-HR AUTO PARKING MODE (p.59) and §Temperature Guideline (p.13); `data/text/manuals/User Manual For New R2-4K.txt` §Temperature Guideline (p.12) and §Troubleshooting "Camera gets HOT" (p.76) — **the recovery question stands; the entry's gag on temperature limits does not.** Thermal protection is documented rather than inferred: the camera "has a built-in temperature sensor", a locked car in direct sun "turns into a greenhouse effect", and "when this happens, the camera will automatically shut down to prevent damage to the unit." **The limits are published, and they are model-dependent** — −4 °F to 140 °F (−20 °C to 60 °C) for the line as a whole, but **14 °F to 131 °F (−10 °C to 55 °C) on the DUAL PRO** — so they may be spoken once the model is known, and cause 1 is confirmed. **Cause 3 is wrong for most of the line:** the USB-C R2-4K, DUAL, DUAL PRO and R3 have a supercapacitor and no battery (see `PWR-04`). **Three documented causes the entry does not carry:** a non-U3 or counterfeit card making the processor work harder, unsupported power sources (power banks, OBD2 adapters, third-party chargers) drawing unstable current, and **Parking Mode left running in extreme heat**. The prevention list is citable in full: U3 card, in-camera format every 1–2 weeks, shade or a sunshade, ROVE-approved power, a shorter parking timer (1–3 hours) or Parking Mode off on hot days. The escalation trigger gains a documented form alongside swelling and burning smell: a camera that "consistently overheats, shuts off without warning, or displays a 'High Temperature' error" → stop using it and contact support. **The entry's own discriminator is still unverified:** no Tier 1 source states that the camera recovers by itself once the car cools, so "does it come back on?" stays `TO VERIFY` and the agent must not promise recovery. That is why this is CORRECTED and not VERIFIED.
- **What would confirm / disconfirm it:** It recovers on its own when the car is cool → thermal protection or mounting position (causes 1 and 2), and the honest answer is partly "working as designed", with a mounting suggestion. It never comes back, or the caller mentions swelling, deformation, or a burning smell → stop diagnosis, instruct disconnection, escalate.
- **Escalate when:** the caller reports swelling, deformation, or a burning smell — stop, instruct disconnect, escalate immediately.
- **Evidence:** Review signal (unretrieved) + Inferred.

### PWR-03 — Does not start or stop with the ignition, or drains the car battery
- **Symptom (caller):** "It stays on after I turn the car off and now my car battery is flat."
- **Models:** Unknown
- **Must ask:** Is the camera on a hardwire kit, and if so, was it fitted to a switched circuit or a constant one?
- **Causes (ranked):** 1. Hardwired to a constant-live circuit with no low-voltage cutoff, or the cutoff set too low. 2. Parking mode drawing power indefinitely by design. 3. Socket is permanently live in this vehicle (varies by make). 4. Fault in the camera's power-state handling.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — establish the wiring arrangement before any setting change. A settings fix cannot compensate for a constant-live circuit, and recommending one here would waste the call. **Do not give wiring instructions by voice** — vehicle electrical work is out of scope.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium — ask whether the camera is on a hardwire kit and, if so, whether the installer set or mentioned a low-voltage cutoff. It discriminates because an installation on a constant-live circuit and a parking mode left running produce the same flat battery, but only one of them is even in the agent's scope to touch.
- **What would confirm / disconfirm it:** A hardwire kit on a constant-live circuit with no cutoff, or a cutoff the caller cannot describe → installation cause (cause 1); escalate, because wiring advice is out of scope (`01` §4). Socket-powered, with the socket permanently live in that vehicle → vehicle behaviour (cause 3), not a camera fault.
- **Escalate when:** the installation is the cause. Wiring advice is out of scope for the agent (`01` §4); route to a human or an installer.
- **Evidence:** Inferred.

### PWR-04 — Loses date and time, or complains about power at every start
- **Symptom (caller):** "Every time I start the car it asks me to set the date again."
- **Models:** Unknown
- **Must ask:** How old is the camera, and does the date survive if it is left connected to power for an hour and then restarted?
- **Causes (ranked):** 1. Internal battery/supercapacitor at end of life — the classic signature for this symptom. 2. Setting never saved properly (exited the menu without confirming). 3. Firmware state after an update (`FW-03`). 4. Power to the camera cut abruptly every time, before it can write its state (cross-check `SD-03` for matching corruption).
- **Next step:** `TO VERIFY` · `Initial hypothesis` — set the date, leave powered, restart, and check. This separates "never saved" from "cannot hold". Whether the internal cell is user-serviceable is **Unknown**.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium — have the caller set the date, leave the camera on power for about an hour, then restart it and check. It discriminates because "the setting was never saved" and "the camera cannot hold its state without power" are indistinguishable from the caller's description, and this is the only test that separates them.
- **What would confirm / disconfirm it:** The date survives the restart after a long period on power → the earlier attempts were never saved (cause 2), or the internal cell simply needed charging. The date is lost again after even a short disconnection → the internal cell or supercapacitor is at end of life (cause 1), a hardware answer the agent may suspect but not declare.
- **Escalate when:** the date never survives a restart on a unit still in warranty — suspected hardware.
- **Evidence:** Review signal (unretrieved) + Inferred.

---

## Category G — Video quality / settings (VID-01 … VID-03)

### VID-01 — Footage too unclear to read a number plate
- **Symptom (caller):** "The video looks okay but when I try to read a licence plate it's just a blur. What's the point."
- **Models:** Unknown
- **Must ask:** Is the blur on every recording, or only on moving vehicles and at distance?
- **Causes (ranked):** 1. Expectation gap — plate legibility at speed and distance is limited for every dashcam, and this is often not a fault. 2. Resolution/bitrate set below the camera's maximum. 3. Protective film never peeled off the lens (genuinely common). 4. Dirty windscreen, dirty lens, or a tinted/heated strip in the camera's view. 5. Lens or sensor fault.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — check the lens for a protective film and for dirt before touching any setting. It costs one turn and is the only cause here with a complete, immediate fix.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium–High (the protective-film cause is a general class fact) — ask the caller to check the lens for a clear plastic film still stuck on it, and whether the lens and the glass in front of it are clean. It discriminates the only cause in this entry with a complete, immediate, free fix, and skipping it risks closing a solvable call as a product limitation.
- **What would confirm / disconfirm it:** A film is present, or the lens or windscreen is visibly dirty → remove or clean, then retest; resolved. The lens is confirmed clean and bare and the resolution setting is already at maximum → expectation gap (cause 1) or an optical fault, and the caller deserves the plain version of that.
- **Escalate when:** the lens is clean, the setting is at maximum, and stationary objects at close range are still blurred — that is an optical fault.
- **Evidence:** Review signal (unretrieved).

### VID-02 — Night footage unusable, or reflections across the whole image
- **Symptom (caller):** "At night I can't see anything. And I can see my dashboard reflected in it."
- **Models:** Unknown
- **Must ask:** Does the caller see reflections of the car's own interior in the footage?
- **Causes (ranked):** 1. Windscreen reflecting a light dashboard or a dash mat — the fix is in the car, not the camera. 2. Exposure/WDR-type settings not at their useful values (names **Unknown**). 3. Camera mounted behind a tinted band or a dirty area of the glass. 4. Genuine low-light limitation of the sensor.
- **Next step:** `TO VERIFY` · `Initial hypothesis` — confirm whether the interior is visible in the image. If it is, this is a reflection problem and no camera setting will resolve it.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium–High (windscreen reflection is a general class fact) — ask whether the caller can see their own dashboard or car interior in the footage. It discriminates because a visible interior is proof of a reflection, and no camera setting whatsoever fixes a reflection — the answer sends the call down an in-car branch rather than a settings branch.
- **What would confirm / disconfirm it:** The interior is visible in the image → reflection (cause 1); the fix is in the car — a dark dash mat, removing light or shiny objects from the dashboard — not in the camera. No interior visible, glass confirmed clean → exposure and WDR-type settings (cause 2), then an honest statement of low-light limits.
- **Escalate when:** no reflection, clean glass, settings confirmed, and night footage is still unusable — possible defect or an honest product limitation that the caller deserves to be told about plainly.
- **Evidence:** Review signal (unretrieved) + Inferred.

### VID-03 — No audio on recordings, or the timestamp is wrong or missing
- **Symptom (caller):** "There's no sound on any of the videos. And the date on them says 2020."
- **Models:** Unknown
- **Must ask:** Which is it — audio, timestamp, or both? (They have different causes and must not be merged into one answer.)
- **Causes (ranked):** 1. Audio recording muted, either in settings or by a button press the caller does not remember. 2. Settings reset to defaults by an update (`FW-03`). 3. Date never set, or not holding (`PWR-04`). 4. Timestamp watermark disabled in settings. 5. Microphone fault (audio only).
- **Next step:** `TO VERIFY` · `Initial hypothesis` — take the audio branch and the timestamp branch separately, audio first. Treating them as one symptom is how an agent ends up fixing neither. Menu paths are **Unknown**.
- **Most plausible next step (initial hypothesis):** `Initial hypothesis — to verify` · Confidence: Medium — take the audio branch alone first, and ask whether the camera's screen shows a muted or crossed-out microphone indicator, or whether the caller remembers pressing a button that changed an icon. It discriminates the most likely cause — and the only one with an instant fix — from the hardware branch, while keeping the timestamp symptom out of the way.
- **What would confirm / disconfirm it:** A mute indicator is present, or the caller recalls the button press → unmute and retest; resolved. Audio is confirmed enabled and recordings are still silent → microphone hardware (cause 5). Either way, the timestamp is then handled as a separate thread (`PWR-04`).
- **Escalate when:** audio is confirmed enabled and recordings are still silent — microphone hardware.
- **Evidence:** Inferred.

---

## Category H — Known gaps (GAP-REAR-CHANNEL … GAP-TIMELAPSE)

Added 2026-11-07, Milestone 5.2. These are the four symptoms `05`
("What Tier 1 adds that the taxonomy has no entry for") confirmed have Tier 1 content and
no diagnostic branch, and which `06` §4.7 routes to the `KNOWN-GAP` outcome until entries
exist. These are the entries.

**How Category H differs from A–G, and why the difference matters.**

| | Categories A–G | Category H |
|---|---|---|
| Written from | Prior model knowledge, then verified in Step 1b | The Tier 1 corpus, directly |
| `Next step` | Was `TO VERIFY`; some promoted by `05` | Sourced on arrival |
| `Evidence` | `Review signal (unretrieved)` / `Inferred` | **`Official doc (Tier 1)`** |
| Status | Assigned by `05` after the fact | Assigned here, per the `05` convention |

**Sourcing rules these entries were written under**, and they are not decorative:

1. **Tier 1 only** — the 7 manuals in `data/text/manuals/`, the 18 Help Center bodies in
   `data/raw/help-center/`, the 3 official pages in `data/raw/official/`. No web, no
   listings, no reviews, no inference from the product class.
2. **Citation form.** Extracted manual text is cited as
   `file` §SECTION (p.*page*; line *N*) — the line is the line in the `.txt` on disk, so a
   reviewer can re-read the exact span. HTML has no stable line numbering, so Help Center
   and official pages are cited by `§`heading, as `05` does.
3. **Marked per the `05` convention** — VERIFIED / CORRECTED / UNVERIFIED. A fact that is
   not in a Tier 1 source is marked **UNVERIFIED** and is **not speakable**, however
   plausible it is. Three such facts are named below rather than quietly dropped.
4. **Every quotation was re-read against the file on disk** before this document was
   committed, and the citations were re-derived rather than trusted. That pass changed
   nine page numbers, four line ranges, four quotations and one `Models` line, and it is
   logged line by line in `05` §"Re-verification pass". Where the extracted text and a
   plausible reading of the PDF disagree — *"Me Key"* for what is almost certainly a MENU
   button glyph — **the corpus wins and the oddity is flagged**, because the agent can
   only ever retrieve what is on disk.
5. **The R2-4K PRO is absent on purpose.** Its manual is still not on disk (`04`
   §"Download status"; Shopify 404, mirror bot-blocked, re-attempted and failed again in
   this milestone). Where an entry's `Models` line omits the PRO, that is the honest state:
   nothing here may be inherited to the PRO from the R2-4K or the DUAL PRO.

### GAP-REAR-CHANNEL — Rear camera shows nothing, or drops in and out
- **Symptom (caller):** "The front camera's fine but the back one's just a black screen."
  / "The rear picture keeps cutting in and out." / "It records the front but there's
  nothing from the back on any of the files."
- **Models:** R2-4K DUAL, R2-4K DUAL PRO, R3 only. **Not applicable to the single-channel
  R2-4K** (either revision) — it has no rear channel and no rear port, so a caller
  describing a rear camera on an R2-4K has been mis-identified and the model question must
  be re-asked (`06` §3.4). The R2-4K PRO is single-channel per its listing; with no manual
  on disk that is **UNVERIFIED** and the agent must ask rather than assume.
- **Must ask:** Which end is the cable loose at — is the rear camera's cable plugged into
  the **rear-camera port** on the front camera, and does the caller remember hearing it
  click in?
- **Causes (ranked):**
  1. **Cable in the wrong port.** Documented on the **R3** specifically: *"Rear camera
     cable connected to sticky mount power port"* is Rove's own first named reason for no
     rear live feed. On the **DUAL PRO** the body carries **two separate USB-C sockets** —
     item 2 *"USB TYPE-C Rear Cam Port"* (lines 622–623) and item 14 *"USB TYPE-C … Power
     Port"* (lines 688–689; the callout number sits between the two halves of the label in
     the extracted text, which is a two-column layout artefact, not a second label) — so
     the same mistake is physically available, but Rove does **not** name it as a DUAL PRO
     cause and the agent must not say that it does.
  2. **Cable not seated.** *"Rear camera not securely connected"* (R3); on the DUAL PRO,
     *"Make sure that you align and properly connect the rear camera cable properly.
     Otherwise, the front/main camera will not be able to detect it."* The R3 manual gives
     the confirmation signal: *"Push gently until you hear a clicking sound to make sure it
     is connected securely."*
  3. **Rear camera was hot-plugged and is damaged.** *"Make sure only to plug in the rear
     camera when the main (front) camera is turned OFF, otherwise it may damage the rear
     camera."* A caller who plugged the rear camera in while the unit was running has a
     documented damage path, not a settings problem.
  4. **Nothing is wrong — the caller is on the wrong view.** The DUAL PRO's **DOWN** button
     is *"Switch Front & Rear View"*; the R3 has a **Rear Camera View** icon on its
     touchscreen. A front-only screen is a view selection before it is a fault.
  5. **Card, not channel.** Rove's list of why recording *"may start and stop even with
     properly connected cables"* leads with *"Using a low-quality memory card"* and only
     then *"Rear camera connector not connected properly"* — so an intermittent rear
     channel shares a cause with `SD-01`.
  6. Cable damaged by the run (routed over an airbag, pinched in trim, or — for an
     outside-mounted rear camera — wet: *"The rear camera is NOT waterproof. Therefore it
     is only designed to be mounted inside the vehicle."*).
- **Next step:** **VERIFIED** · Source: `data/text/manuals/r3-manual-website-files.txt`
  §"Rear Camera Live View Issue" (line 41–42) and §"Page 24" wiring (line 14);
  `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §"Installing the rear camera" IMPORTANT
  (p.23; lines 935–937) and NOTE (p.21; lines 883–885) — **ask which socket the rear cable
  is in, before anything else.** It is free, it is Rove's own first named cause on the R3,
  and it splits "plugged into the wrong hole" from "plugged in badly" from "camera at
  fault" in one answer. **Then, and only with the camera powered OFF**, have the caller
  unplug and re-seat the rear cable at both ends until it clicks. The power-off ordering is
  not optional politeness — hot-plugging is documented as damaging the rear camera.
- **What would confirm / disconfirm it:** The rear picture returns after re-seating → cable
  seating or wrong port (causes 1–2); resolved, and worth telling the caller which port to
  use next time. Rear channel still black with the cable confirmed in the rear-cam port and
  clicked home → suspect the rear camera or the cable itself (causes 3, 6), which is
  hardware and escalates. The rear picture appears as soon as the caller presses DOWN or
  taps the rear-view icon → cause 4; nothing was broken.
- **Escalate when:** the cable is confirmed in the correct port and seated, and the rear
  channel is still dead; or the caller reports they plugged the rear camera in while the
  camera was running (documented damage path — the agent may suspect it, not declare it,
  `01` §4). Cable routing past airbags is a safety stop, not a diagnostic step: `01` §4
  puts vehicle wiring out of scope and the DUAL PRO manual warns that a cable run past a
  side-curtain airbag *"can prevent the airbags from deploying."*
- **Evidence:** Official doc (Tier 1).
- **Status: CORRECTED** (Milestone 5.2). The gap itself is real and `05` predicted it
  correctly, but `05` records the two named causes — *"rear camera cable connected to
  sticky mount power port"*, *"rear camera not securely connected"* — as applying to
  "(DUAL, DUAL PRO, R3)". **They are R3 quotes.** The sticky-mount power port is an R3
  mount feature; the DUAL and DUAL PRO take power into the camera body, not through the
  mount (`ROVE-R2-4K-DUAL-PRO.txt` §UNIT STRUCTURE items 1, 2 and 14, pp.14–15; lines
  613–689). The causes still *rank* the same way on the dual models, but on different
  evidence, and the agent must not quote the mount-port cause at a DUAL or DUAL PRO caller.

### GAP-GPS — No GPS, no live speed, or no speed/location stamp on the footage
- **Symptom (caller):** "The speed on the screen just says zero." / "There's no speed on
  my videos any more." / "The GPS player won't show the route."
- **Models:** R2-4K (USB-C), R2-4K DUAL, R2-4K DUAL PRO, R3 — GPS is built in across the
  documented line, and quad-mode (GPS / GLONASS / Galileo / BeiDou) on the DUAL PRO. The
  original mini-USB R2-4K also carries *"Built-in GPS Geo-Tagging Support"*. **R2-4K PRO:
  no manual on disk — UNVERIFIED, ask.**
- **Must ask:** Which of the three is missing — the **live speed on the camera's screen**,
  the **speed/GPS stamp burnt into the video**, or the **route in the GPS Player**? They
  are three different settings and merging them is how this call gets fixed wrongly.
- **Causes (ranked):**
  1. **The camera has no satellite fix yet.** The camera reports this itself: the DUAL PRO
     home screen carries a **GPS Indicator** icon with a distinct **"GPS Not Connected"**
     state, and the R2-4K has a **GPS INFO** screen showing live latitude and longitude.
     Rove's own date/time fix says to *"wait until you get GPS signal LOCK"* — a fix takes
     time and sky, and indoors there is usually none at all.
  2. **A stamp was switched off, not the GPS.** `VIDEO STAMPS` has independent
     `Speed Stamp` and `GPS Location Stamp` toggles, *"By default, they are all ON"*, and
     turning one off means *"when you play your video on GPS Player, you will NOT see any
     speed associated with the video"*.
  3. **`LIVE SPEED & COMPASS` was switched off** — this changes only the screen, not the
     recording: *"By turning off this feature, it does NOT turn OFF the Driving Speed or
     the GPS metadata."* So a caller who sees no speed on the screen but has it on their
     files is in cause 3, and nothing is broken.
  4. **The master GPS setting is OFF.** On the **DUAL PRO** there is one: `System Settings
     > GPS`, default **ON**, and *"NO GPS related data will be used across the device.
     (i.e. Live Speed, Speed Stamp, GPS Coordinates)"* when it is off. **There is no such
     master toggle documented on the R2-4K** — do not send an R2-4K caller looking for it.
  5. **Mount not fully seated (R3).** Rove's *"R3: NO GPS Live Speed?"* opens with it:
     *"ensure that the mount and the main camera are connected properly and that there are
     no gaps between them"*.
  6. **Placement near the vehicle's own GPS antenna** — Rove recommends *"placing/installing
     the camera in a location that is distant from your vehicle's GPS antenna, minimizing
     potential signal conflicts"*.
  7. Firmware, then a settings restore — Rove's steps 3 and 4, in that order.
- **Next step:** **VERIFIED** · Source:
  `data/raw/help-center/r3-no-gps-live-speed.html` §Step 1–§Step 4;
  `data/text/manuals/User Manual For New R2-4K.txt` §GPS INFO (p.66; lines 2283–2295),
  §VIDEO STAMPS (p.58; lines 2036–2052), §LIVE SPEED & COMPASS (p.59; lines 2069–2077);
  `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §GPS (p.74; lines 2865–2874) and
  §"Home Screen Status Icons" (p.33; lines 1353–1436) — **ask the caller to take the
  camera somewhere with open sky, leave it powered for a few minutes, and read out the GPS
  indicator or the GPS INFO screen.** It discriminates the whole top of the list in one
  move: a camera with a fix and no stamps is a settings call (causes 2–4), a camera that
  never gets a fix is a hardware, mount or placement call (causes 5–6). It also costs the
  caller nothing and needs no menu navigation. On an **R3** specifically, add the mount
  check first — it is Rove's own step 1 and it is a five-second physical check.
- **What would confirm / disconfirm it:** The GPS INFO screen shows a latitude and
  longitude, or the indicator shows connected → the camera has a fix; the missing thing is
  a stamp or a screen setting, and the call is cause 2 or 3. Still no fix after several
  minutes under open sky → mount seating (R3), placement, or hardware. The caller says the
  speed is missing on the **screen** but present on the **files** → cause 3, working as
  designed, close honestly.
- **Escalate when:** the camera is confirmed to get no fix under open sky after the mount
  is confirmed seated, the stamps are confirmed on, and (DUAL PRO) the GPS setting is
  confirmed ON — that is a GPS hardware answer the agent may suspect and not declare.
- **Evidence:** Official doc (Tier 1).
- **Status: CORRECTED** (Milestone 5.2), and the correction is to our own documents, not to
  a caller-facing fact. `05` §"What Tier 1 adds" and `06` §4.7 both state the mechanism as
  fact — *"on the R3 the GPS lives in the magnetic mount, so a gap between mount and camera
  kills it"*. **No Tier 1 prose says that.** `r3-no-gps-live-speed.html` says to close the
  gap; it does not say why. The only corpus text putting GPS inside an R3 mount is a
  **storefront product title** on `data/raw/official/firmware-update-downloads.html`
  (*"R3 Magnetic Mount with GPS…"*, *"Magnetic Mount with Built-In GPS"*) — and `04`
  §"Download status" is explicit that listing material is Tier 2/3 in substance and must
  not be spoken as verified. So: **the step is VERIFIED and speakable** (close the gap
  between mount and camera — Rove's own step 1); **the mechanism is UNVERIFIED and must not
  be spoken** (the agent does not tell a caller their GPS is inside the mount). `06` §4.7
  carries the mechanism as speakable and should be reconciled — logged in `05`.

### GAP-MOUNTING — Camera falls off the windscreen, or will not stay put
- **Symptom (caller):** "It keeps falling off. Third time this week." / "The suction cup
  won't hold at all." / "It fell on a hot day and now it hangs off the mount."
- **Models:** All documented models. Mount hardware differs — suction and 3M sticky on the
  R2-4K family, *"a suction mount or magnetic sticky mount"* on the R3 — so the *fix* is
  model-specific even though the *constraint* is not. **R2-4K PRO: UNVERIFIED, ask.**
- **Must ask:** **How steeply raked is the windscreen where the mount sits — is the glass
  close to vertical?** This is the question no one thinks to ask and it is the one that can
  end the call honestly in one turn.
- **Causes (ranked):**
  1. **The windscreen is too flat for the mount to work at all.** Rove is unambiguous:
     *"The short answer is - NO. Due to the camera and lens design, our mounts will NOT
     work properly on a flat windshield as they require at least a 20° slope/angle."* This
     is a **product limitation, not a fault**, and the only remedy Rove offers is
     third-party: *"You may want to try using a universal mount, but please use it with
     caution"*. The agent may state the 20° requirement; it must not recommend or endorse a
     specific third-party mount.
  2. **Suction cup on the dot-matrix band.** The R2-4K manual illustrates it as
     **AVOID THIS**: *"dot-matrix pattern, as suction mount will NOT be able to get a strong
     suction, hence it will fall down if you mount on top of it."* The black ceramic dots
     around the edge of the glass are exactly where people mount, and this is the single
     most actionable cause in the entry.
  3. **Suction mount never locked.** The documented action is two-handed: *"Press & hold it
     tight towards the windshield to remove any air between the suction mount and the
     windshield. While pressing & holding towards the windshield, turn the LOCKING Knob
     towards CLOCKWISE to LOCK in place."* A mount pressed on and then locked without
     holding pressure traps air and lets go later.
  4. **Glass not prepared.** *"Make sure to clean your windshield from dust particles and
     evaporated grease from the dashboard surface"* — the grease film off a hot dashboard
     is the invisible version of this.
  5. **Sticky / magnetic mount fitted without the electrostatic film, or fitted badly.**
     The documented sequence is clean → air-dry → electrostatic film → credit card out the
     bubbles → peel the red 3M liner → *"apply even pressure to the camera from both sides
     for about 30 seconds"*, and the mount must end up with **no gap**.
  6. **Rear camera on a defrosted rear screen.** *"If your vehicle have defroster lines in
     the back, pick a spot where those lines are further away to create a strong bond.
     Rarely it is NOT possible to apply electrostatic film successfully as some cars might
     have too rigid and closer defroster lines, and in this case, the electrostatic film
     will NOT work for you."*
  7. Heat. `PWR-02` documents the greenhouse effect inside a locked car; adhesive behaviour
     in that heat is **UNVERIFIED** in this corpus and the agent must not claim it.
- **Next step:** **VERIFIED** · Source:
  `data/raw/help-center/know-your-dashcam-how-to.html` §"Can I mount the dashcam on a flat
  windshield?"; `data/text/manuals/User Manual For New R2-4K.txt` §INSTALLATION steps 2–4
  (pp.16–17; lines 556–605); `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §"Installing the
  rear camera" NOTE (p.20; lines 847–860);
  `data/text/manuals/r3-manual-website-files.txt` (lines 9–12) — **ask about the rake of
  the glass and whether the mount sits on or near the band of black dots at the edge of the
  windscreen.** Two sentences, and between them they cover the one cause nothing can fix
  and the one cause that is fixed by moving the mount four inches.
- **What would confirm / disconfirm it:** The caller describes a near-vertical or very
  shallow windscreen → cause 1; say plainly that the mounts need about a 20° rake, that
  this is a design limit rather than a faulty mount, and do not improvise a workaround. The
  mount is on or overlapping the dotted band → cause 2; move it onto clear glass and
  re-seat. Steeply raked glass, clear of the dots, properly locked, and it still falls →
  mount hardware, which is a parts question and leaves the diagnostic path.
- **Escalate when:** the glass is confirmed suitable, the surface is confirmed prepared and
  clear of the dot-matrix band, the lock procedure is confirmed followed, and the mount
  still will not hold — that is a defective mount and a replacement-part conversation
  (`01` §4 puts parts and returns out of scope).
- **Evidence:** Official doc (Tier 1).
- **Status: VERIFIED** (Milestone 5.2). `05` predicted this gap and quoted the 20°
  constraint correctly; the quote is verbatim and the entry adds the dot-matrix and locking
  causes around it.

### GAP-TIMELAPSE — Everything plays back in fast motion
- **Symptom (caller):** "All my videos are sped up, like a cartoon." / "Everything's in
  fast-forward and I can't slow it down." / "The whole drive is thirty seconds long."
- **Models:** R2-4K (both revisions), R2-4K DUAL PRO and R3 — `TIME LAPSE RECORD` is a
  documented setting on each (`M1`, `M2`, `M3`, `M7`; the R3 as *"The Time-Lapse Video
  feature"*). **Behaviour differs by hardware revision** — see the cause list. **R2-4K
  DUAL: UNVERIFIED.** Its manual
  (`data/text/manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.txt`) does not mention
  time-lapse anywhere — not in the settings, not in the troubleshooting table — so the
  agent must ask rather than assume the setting exists, and must not inherit the
  restart-persistence behaviour below to it. **R2-4K PRO: UNVERIFIED, ask.**
- **Must ask:** Is **every** file in fast motion, or only the ones recorded while the car
  was parked?
- **Causes (ranked):**
  1. **`Time Lapse Record` is switched on.** Rove states the cause and the fix together:
     *"Your footage looks like a time-lapse because the Time-Lapse Record setting is turned
     on. This is a quick, one-step fix directly in your camera's video settings menu."* The
     setting lives in **Video Settings** — `MENU` (short press) → `Video Settings` →
     `TIME LAPSE RECORD` → `OFF`; the other options are 4, 2 and 1 frame/second.
  2. **It stays on across restarts — on the current models.** *"Enabling this feature will
     keep it activated at all times, even after the camera restarts, resulting in
     time-lapse speed (faster playing) for your videos. If you prefer regular speed
     playback, please ensure to turn this feature OFF before powering off your camera."*
     This is why a caller who "didn't change anything" can have weeks of fast footage.
     **The original mini-USB R2-4K is the exception and behaves the opposite way**:
     *"Time-Lapse is OFF by default. It also programmed to set to OFF when the camera
     restarts every time"*. So on that revision, persistent fast motion is **not** explained
     by cause 1 and the agent must not close the call on it (`05` §"A note on `M1` vs
     `M2`/`M3`").
  3. **Parking mode, working as designed.** On the R3, *"If an impact occurs while the car
     is turned off, the dash cam will record a Time-Lapse Video"*, and the DUAL PRO's
     parking mode is a documented **"Time-Lapse 1fps & G-Sensor"** mode. Fast-motion clips
     that are *only* from a parked car are the product working correctly — an expectation
     gap, not a fault, and turning `Time Lapse Record` off will not change them.
  4. Playback-side speed control in a player or the app — **UNVERIFIED**; no Tier 1 source
     describes a playback speed control, so the agent must not send the caller looking for
     one.
- **Next step:** **VERIFIED** · Source:
  `data/raw/help-center/troubleshoot-index.html` §"Why does my video play in a fast motion?
  (Time-Lapse)"; `data/text/manuals/User Manual For New R2-4K.txt` §TIME LAPSE RECORD
  (p.48; lines 1664–1681) and §UNDERSTANDING CAMERA SETTINGS (p.45; lines 1551–1554);
  `data/text/manuals/ROVE R2-4K User Manual.txt` §TIME LAPSE RECORD (p.48; lines
  1496–1508); `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §TIME LAPSE RECORD (p.57; lines
  2240–2259); `data/text/manuals/dc3831.txt` §TIME-LAPSE VIDEO (p.41; lines 1381–1398) —
  **have the caller read out what `Video Settings > Time Lapse Record` is set to.** One
  turn, one menu level, and the answer either closes the call (`OFF` it and done) or rules
  the whole entry out. Before navigating, note that entering settings **stops recording**:
  *"Short press Me Key to enter the setting interface after power on. In this case, the
  video recording will be stopped"* — say so, and `REC-01`'s preserve-first rule outranks
  this step if the caller has footage they need. (*"Me Key"* is what all four manuals'
  extracted text reads; the PDF prints a button glyph between *"Me"* and *"Key"* that the
  extraction drops. The quote is left as the corpus has it rather than silently repaired
  to *"MENU"*, which is an inference about a glyph nobody on this project has seen.)
- **What would confirm / disconfirm it:** It reads 1, 2 or 4 frame/second → cause 1; set it
  to `OFF`, confirm a new clip plays at normal speed, and tell the caller it would otherwise
  have survived the next restart. It already reads `OFF` and every file is still fast →
  either the parked-car branch (cause 3) or, on the mini-USB revision, something this entry
  does not explain; escalate rather than improvise. Only the parked clips are fast →
  cause 3, working as designed.
- **Escalate when:** `Time Lapse Record` is confirmed `OFF`, the clips are not parking-mode
  clips, and playback is still fast — there is no second documented cause and guessing at
  one would be invention.
- **Evidence:** Official doc (Tier 1).
- **Status: VERIFIED** (Milestone 5.2; re-verified against the sources in the same
  milestone). One addition beyond what `05` recorded: the one-step fix is one step only on
  the current models. The mini-USB revision documents the opposite persistence behaviour,
  and the parked-car branch is a second, separate cause. **One claim was withdrawn on
  re-verification**: this entry first said *all* documented models have
  `TIME LAPSE RECORD`. The R2-4K DUAL manual does not mention time-lapse at all, so the
  `Models` line now marks the DUAL UNVERIFIED. The quoted cause and fix are unaffected —
  they were never DUAL quotes.

---

## Category H guards — the other `05` finds

`05` lists five further symptoms with Tier 1 content behind them and no entry:
the three-option boot prompt, "Hardwire kit Not Detected", a frozen screen, a camera
cycling on and off, and random restarts. They are **guards, not entries** — no ranked cause
list, no discriminating-step analysis — for one reason each, stated below. A guard says
what the agent **must** and **must not** do or say, and nothing else. All five are grounded
under the same rules as the entries above.

Guards are still IDs: they carry a `docs/05` status, they gate chunks, and `06` §4.7's
`KNOWN-GAP` outcome routes to them. What they do not carry is a diagnostic branch.

### GAP-BOOT-PROMPT — "Connect to PC/MAC" with three options at every start
**Why a guard, not an entry:** there is nothing to diagnose. The prompt is a documented
feature of the camera's USB handling and the cause is published.

**Status: VERIFIED.** Source: `data/text/manuals/User Manual For New R2-4K.txt` §"B. On
PC/MAC" (p.40; lines 1382–1397) and §spec table "Type-C USB Function" (p.12; line 382);
`data/text/manuals/ROVE R2-4K User Manual.txt` §"B. On PC/MAC" (p.40; lines 1289–1304);
`data/text/manuals/dc3831.txt` (p.36; lines 1244–1251);
`data/raw/help-center/know-your-dashcam-how-to.html` §"Why does it says Connect to USB or
Connect to PC or Operate camera normally whenever I start my car?" and §"Initial screen
asking how to use the dash cam"; `data/raw/help-center/troubleshoot-index.html` §"Dash cam
not playing Automatically and giving three options";
`data/raw/official/connect-rove-to-phone.html` §"How to move videos to a computer instead".

**The agent must:**
- Name the three options as the camera prints them — **"Connect as USB Flash Drive"**,
  **"Connect as PC/MAC Webcam"**, **"Operate Camera Normally"** — and tell the caller to
  choose **Operate Camera Normally** to use the camera as a dash cam.
- Say plainly that this is **not a fault**. The camera has three documented USB functions
  (*"1. Storage, 2. Charging, 3. Webcam"*) and the prompt is it asking which one.
- State the documented cause: it happens *"if the dashcam is plugged into a USB port using
  the short data cable"* — connecting to the car's direct USB port with the 2.5 ft data
  cable *"may connect to your car's music system or computer"*.
- Note the useful half: **"Connect as USB Flash Drive"** is the documented way to reach the
  card from a computer without a card reader (`FW-04`) — except on the DUAL PRO, which has
  no direct computer connection at all.

**The agent must not:**
- Treat a recurring prompt as a defect, a firmware problem, or a card problem.
- **State that moving to the 12 V socket stops the prompt coming back.** The Help Center
  sentence that would say so is **truncated in the captured body** — the remedy half of
  *"In this ca…"* was never retrieved. The manual's own installation step is to power from
  the cigarette-lighter socket with the supplied cord (`User Manual For New R2-4K.txt` §
  INSTALLATION step 5, p.17), and the agent may describe that as the documented
  arrangement — but **"that will fix it" is UNVERIFIED** and must not be promised.
- Recommend the **Webcam** option. Nothing in the corpus describes what it does beyond its
  name.

### GAP-HWK-NOT-DETECTED — "Hardwire kit Not Detected" on screen
**Why a guard, not an entry:** the only remedy Tier 1 publishes is a wiring check, and
`01` §4 puts vehicle wiring out of scope. An entry would be a cause list the agent is not
allowed to act on.

**Status: VERIFIED.** Source: `data/raw/help-center/troubleshoot-index.html` §"Hardwire kit
Not Detected"; `data/raw/help-center/know-your-dashcam-how-to.html` §"Why do I need
hardwire kit for 24-Hour (24-HR) parking mode?";
`data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §24-HR AUTO PARKING MODE CAUTION (p.59; lines
2294–2302) and §"Home Screen Status Icons" (p.33; line 1414).

**The agent must:**
- Recognise it as the kit, not the camera, and say so: Rove's guidance is *"please ensure
  that the wires are connected properly and in the correct position. Double-check all
  wiring connections to ensure they are securely attached and properly positioned."*
- Confirm the consequence honestly — **24-hour parking mode will not run without the kit
  detected** (`REC-04`), so the caller's parking footage is not being recorded right now.
- Ask whether the kit was fitted by the caller or an installer, and capture that for the
  handoff.
- Carry the safety line verbatim when wiring comes up: *"Never connect the dash cam
  directly to your car's 12/24V battery by modifying wires… You must connect the dash cam
  using the ROVE Ultimate USB Type-C Hardwire Kit and connect it to the car's fuse box (NOT
  to battery terminals directly)."*

**The agent must not:**
- Give wiring instructions of any kind — which fuse, which tap, which lead is which.
  Out of scope (`01` §4, `PWR-03`), and the hazard is the caller's car, not the camera.
- Suggest a settings change as a substitute. No setting makes an undetected kit detected.
- Confirm or deny that the kit is faulty. Escalate: this one hands to a human or an
  installer early, by design.

### GAP-FROZEN-SCREEN — Screen frozen, buttons unresponsive
**Why a guard, not an entry:** Rove publishes a fixed four-step order and the steps do not
branch. Reproducing it as a ranked cause list would add nothing and risk reordering it.

**Status: VERIFIED.** Source: `data/raw/help-center/frozen-screen.html` (whole article);
`data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §Troubleshooting *"Camera Freezing/Lagging or
Crashing"* (pp.85–86; lines 3295–3315); `data/text/manuals/ROVE R2-4K Dual Dash Cam Instruction
Manual.txt` §7 Troubleshooting row *"Dash cam freezes or crashes"* (p.13; lines 186–190 —
the row's three columns interleave in the extracted text, so the cell reads across
non-adjacent lines);
`data/text/manuals/r3-manual-website-files.txt` (lines 8, 39).

**The agent must:**
- Follow Rove's order and no other: **(1)** unplug the power cable, wait a few seconds,
  reconnect — *"A power restart is the fastest way to clear a temporary frozen screen"*;
  **(2)** press the **RESET** button once with a paper clip, *if the model has one*;
  **(3)** power off, remove the memory card, power on, and report whether it still freezes;
  **(4)** try a known-good Class 10 / U3 card.
- State the R3 exception every time reset comes up: *"This step is not applicable to the
  ROVE R3 because the R3 does not have a reset button."* On the R3, *"unplugging and
  replugging the power cable can resolve any issues"*.
- Read the card test the way Rove reads it: stops freezing without the card → *"the memory
  card may be faulty, too slow, corrupted, or worn out"*; still freezes without the card →
  continue or escalate.

**The agent must not:**
- Offer formatting as the first move. The documented card step is **removal and retest**,
  not a format; formatting is destructive, is gated (`01` §5), and destroys the evidence a
  `REC-01` caller may need.
- Call a frozen screen a dead camera. It is a distinct symptom from `PWR-01`, and the
  camera may well be recording behind a frozen display.
- Promise that a restart fixes it — Rove says *"most"* frozen-screen issues clear this way,
  not all.

### GAP-ON-OFF-CYCLING — Camera repeatedly turning on and off
**Why a guard, not an entry:** the published procedure is an isolation sequence — power,
cable, card — run in a fixed order, not a ranked set of hypotheses. It also overlaps
`PWR-01` and `PWR-03` and the guard's main job is to keep the three apart.

**Status: VERIFIED.** Source: `data/raw/help-center/repeatedly-on-off.html` (whole
article); `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §Troubleshooting *"Camera turns
ON/OFF frequently automatically"* (p.86; lines 3328–3332).

**The agent must:**
- Lead with the cause Rove leads with: *"the most common cause is unstable or insufficient
  power"*, from the car's USB/12 V outlet, the ROVE car charger, the USB cable, or a loose
  connection.
- Run the isolation in Rove's order: reset (where a reset button exists) → **test indoors
  on a 110 V wall outlet with a phone USB charger** → try **both** supplied ROVE cables →
  remove the card and repeat the wall-outlet test.
- Read the wall-outlet result as Rove does: works at home → *"the issue may be related to
  your vehicle's power outlet, USB car charger, or vehicle power setup"*; still restarts at
  home → cable and card next, then the camera.
- Keep this separate from `PWR-01` (never powers on at all) and `PWR-03` (powers on and
  never powers off). Different symptom, different article, different cause ranking.

**The agent must not:**
- Jump to firmware. The DUAL PRO manual's row for this symptom does say *"Try updating the
  firmware again"*, but the Help Center's dedicated article does not, and `FW-01` is the
  entry where wrong advice destroys the device. Firmware is not the first move here.
- Diagnose the vehicle's electrics. "Your fuse box is the problem" is out of scope
  (`01` §4).
- Declare the camera faulty. Rove names the camera **last** in its own list of causes —
  *"the USB car charger, USB power cable, vehicle power source, memory card, or in rare
  cases the dash cam itself"* — and the four isolation steps exist to reach it by
  elimination. The agent gets there the same way, and then escalates rather than
  declaring. (Rove states that list in the article's **opening paragraph**, not after the
  steps; the ordering is a ranking, not a sequence.)

### GAP-RANDOM-RESTART — Camera randomly restarting during use
**Why a guard, not an entry:** Rove attributes it to a single documented class of cause and
publishes a short isolation, not a differential. It shares its article family with
`GAP-ON-OFF-CYCLING` and the guard exists mainly to carry the charger fact.

**Status: VERIFIED.** Source: `data/raw/help-center/random-restarting.html` (whole
article); `data/text/manuals/r3-manual-website-files.txt` (lines 3, 40);
`data/text/manuals/User Manual For New R2-4K.txt` §INSTALLATION CAUTION (p.17; lines
609–612), §Charging NOTE (p.19; lines 672–674), §"OUT OF THE BOX INSTRUCTIONS" (p.9; lines
264–266); `data/text/manuals/ROVE R2-4K User Manual.txt` (p.17, lines 555–556; p.19,
line 612);
`data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` §"Wiring at a glance" CAUTION (p.23; lines
931–933); `data/raw/help-center/know-your-dashcam-how-to.html` §"Can I use my own cord with
Type-C to Type C ports?".

**The agent must:**
- Ask **what is powering the camera** before anything else, and name the documented cause:
  *"If you're using a non-ROVE USB Car Charger, your car's direct USB might not provide
  enough power, which can cause reboots."* The manuals put it as a CAUTION on the
  installation page: *"Only use ROVE's USB Car Charger, otherwise the camera may frequently
  reboot or flicker LCD due to insufficient power."*
- Carry the second documented cause too: the card. *"Using other micro SD cards can affect
  the dashcam's performance and force it to reboot randomly during recording"*, and Rove's
  own isolation is to *"turn off the camera, remove the memory card, and repeat the test
  using a 110V wall outlet and both ROVE USB cables"*.
- Mention the Type-C caveat where the caller is using their own cable: Rove *"do not
  recommend powering your ROVE dash cam directly with a third-party USB Type-C to Type-C
  cable"*.
- State the R3 exception on reset: *"It does not apply to the ROVE R3 dashcam, as it does
  not have a reset button."*

**The agent must not:**
- **Quote a single charger current figure.** The requirement is printed differently across
  revisions — *"5V, 1.5 AMP power output (Max 3.4 AMP)"* in one R2-4K printing and a
  **3.1 AMP** ceiling in another. The agent may say the camera needs the supplied ROVE
  charger and that an over-rated charger is documented as able to damage it; it may not
  state the number (`06` §4.6 reasoning, applied to a spec that genuinely differs by
  printing).
- Tell the caller a reset restores factory settings without gating it. The Help Center says
  a full reset *"will clear any temporary glitches and return the camera to its factory
  settings"* — that is a destructive action under `01` §5 and needs cause, consent and the
  consequence said out loud.
- Blame the camera first. Rove reaches *"or, in rare cases, the dash cam itself"* last.

---

## Coverage summary

| Category | IDs | Count | Dominant evidence type |
|---|---|---|---|
| A. Wi-Fi connectivity | WIFI-01 … 05 | 5 | Review signal (unretrieved) + Inferred |
| B. Firmware update / compatibility | FW-01 … 04 | 4 | Inferred; `FW-02` escalation-first |
| C. Mobile app pairing | APP-01 … 04 | 4 | Inferred |
| D. Not recording / loop recording | REC-01 … 04 | 4 | Review signal (unretrieved) |
| E. SD card / storage | SD-01 … 04 | 4 | Review signal (unretrieved) |
| F. Power / overheating | PWR-01 … 04 | 4 | Inferred |
| G. Video quality / settings | VID-01 … 03 | 3 | Review signal (unretrieved) |
| **Subtotal (v0, Categories A–G)** | | **28** | **0 entries marked `Official doc`** |
| H. Known gaps **(5.2)** | GAP-REAR-CHANNEL, GAP-GPS, GAP-MOUNTING, GAP-TIMELAPSE | 4 | **Official doc (Tier 1)** |
| H. Guards **(5.2)** | GAP-BOOT-PROMPT, GAP-HWK-NOT-DETECTED, GAP-FROZEN-SCREEN, GAP-ON-OFF-CYCLING, GAP-RANDOM-RESTART | 5 guards | **Official doc (Tier 1)** |
| **Total** | | **32 entries + 5 guards** | **9 marked `Official doc (Tier 1)`** |

**Category H statuses** (`05` convention): `GAP-REAR-CHANNEL` **CORRECTED**, `GAP-GPS`
**CORRECTED**, `GAP-MOUNTING` **VERIFIED**, `GAP-TIMELAPSE` **VERIFIED**; all five guards
**VERIFIED**. The two CORRECTED outcomes correct *our own* documents — `05` and `06` §4.7
— not a caller-facing fact; see each entry's Status line.

### Entries that are expectation gaps, not faults

`REC-03`, `VID-01`, `VID-02`, and parts of `WIFI-05` and `PWR-02` are frequently the device
working as designed. The agent must be able to close these honestly — "this is how loop
recording works" — rather than inventing a fix for a non-fault. A taxonomy that cannot say
"nothing is broken" produces agents that break things.

**(5.2)** Category H adds three more, and one of them is a limitation rather than a
behaviour: `GAP-TIMELAPSE` cause 3 (parking mode records time-lapse by design),
`GAP-BOOT-PROMPT` (the camera asking which USB function to use), and `GAP-MOUNTING` cause 1
— a windscreen flatter than about 20° is a **product limitation Rove states outright**, and
the honest close is to say so rather than keep troubleshooting a mount that cannot work.

### Entries where the first step is not diagnosis

- `REC-01` — preserve the card before anything else.
- `FW-01` / `FW-02` — do not power-cycle reflexively; the reflex is what bricks the unit.
- Any report of smoke, swelling, or burning smell — disconnect and escalate.
- **(5.2)** `GAP-REAR-CHANNEL` — the camera must be **powered off** before the rear cable
  is touched; hot-plugging the rear camera is documented as damaging it.
- **(5.2)** `GAP-HWK-NOT-DETECTED` — wiring is out of scope; this guard hands off early
  rather than diagnosing.

---

## What is still unknown

- **Every fix.** Twenty-eight entries, zero verified next steps. The "Next step" field is
  currently a hypothesis about what *would* discriminate, not an instruction that may be
  spoken to a caller.
- **Every menu path, setting name, on-screen string, and error message.** The agent cannot
  guide anyone through a UI it has never seen described.
- **Card requirements** — capacity ceiling, speed class, endurance rating. `SD-01` and
  `SD-04` carry the taxonomy's strongest hypothesis and the least evidence.
- **Model differentiation.** Every entry says `Models: Unknown`. If Rove models differ
  materially in Wi-Fi behaviour, parking mode, or update path, this taxonomy is really
  seven taxonomies and we do not yet know which.
- **Known-issue feed** (`01` §8 Q5). Without it, `FW-03` is undiagnosable — recognising a
  bad build is exactly the thing a human engineer does that we cannot currently replicate.
- **Cause rankings.** Every "ranked" list is ordered by inference. Real call data could
  invert any of them, and the rankings drive the agent's first question.
- **Whether these 28 are the right 28.** No call-mix data (`01` §8 Q10). We may be missing
  mounting/adhesive, GPS, and accessory issues entirely, and we have no way to know.
  **(5.2) Partly closed.** Mounting, GPS, rear channel and time-lapse are now entries
  (Category H) and five further `05` finds are guards. The underlying problem is not
  closed: **there is still no call-mix data**, so Category H's existence is evidence that
  the corpus documents these symptoms, not evidence that callers ring about them. Whether
  32 entries are the right 32 remains unanswerable until the Phase 4 pilot.
- **(5.2) What Category H could not source.** Four facts were wanted and are **not in any
  Tier 1 source**, so they are marked UNVERIFIED and are not speakable: the mechanism
  behind the R3 mount-seating step (`GAP-GPS`); whether moving off the car's USB data port
  stops the boot prompt recurring (`GAP-BOOT-PROMPT` — the Help Center sentence is
  truncated in the captured body); how heat affects mount adhesive (`GAP-MOUNTING`
  cause 7); and **whether the R2-4K DUAL has a `TIME LAPSE RECORD` setting at all** — its
  manual never mentions time-lapse, so `GAP-TIMELAPSE` cannot be applied to the DUAL
  without asking first.
- **(5.2) The R2-4K PRO is still the one model with no manual on disk.** A third attempt
  was not made in this milestone — `04` records two failures (Shopify 404 on the link
  published on `O1`, manuals.plus bot-blocked) and nothing has changed. Every Category H
  entry therefore leaves the PRO out of its `Models` line rather than inheriting a fact
  from the R2-4K or the DUAL PRO.
