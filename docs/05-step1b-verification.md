# 05 — Step 1b Verification Report

Status: **Step 1b complete for the Tier 1 corpus held on disk.** Design only. No code.
Date: 2026-11-07
Verifies: every `Initial hypothesis` in [`02-issue-taxonomy.md`](02-issue-taxonomy.md).

**Amended 2026-11-07 by Milestone 4.3 (Track C).** Seven Tier 1 documents that did not
exist on disk when this report was written are now here: Rove's own 91-page **R2-4K DUAL
PRO** manual (`M7`) and the bodies of **six Help Center articles** that were previously
index entries with no text behind them. Every amendment is marked **(4.3)**, nothing in the
original pass has been deleted, and the one entry whose outcome changed — `PWR-02` — says
so in its own row with the source that moved it. The deltas are collected in
["Milestone 4.3 — what the Track C sources changed"](#milestone-43--what-the-track-c-sources-changed).

**Amended 2026-11-07 by Milestone 5.2 (Phase 2 knowledge completion).** The four missing
taxonomy entries and five guards named in
["What Tier 1 adds that the taxonomy has no entry for"](#what-tier-1-adds-that-the-taxonomy-has-no-entry-for)
are now written, verified and statused. No source was added — the corpus is unchanged at
28 Tier 1 documents. The deltas are in
["Milestone 5.2 — Phase 2 knowledge completion"](#milestone-52--phase-2-knowledge-completion),
and that section also corrects one claim this document itself made (the R3 mount-GPS
mechanism).

---

## Scope and method

Every claim below was checked **only** against Tier 1 material already on disk. No web
access was used, and nothing was inferred from outside the corpus.

| Source group | Path | Files |
|---|---|---|
| Manuals (extracted text) | `data/text/manuals/*.txt` | 6 — 260 pages · **(4.3)** 7 — 351 pages |
| Official Rove site | `data/raw/official/*.html` | 3 |
| Rove Help Center (Gorgias) | `data/raw/help-center/*.html` | 12 · **(4.3)** 18 |

Method: targeted `grep` over the extracted manual text and over tag-stripped HTML, then a
read of the matching section. No file was read end-to-end on spec.

### Source short codes used in this document

| Code | File | What it is |
|---|---|---|
| `M1` | `data/text/manuals/dc3831.txt` | ROVE R2-4K, **original mini-USB revision** — 250 mAh Li-ion battery (72 pp) |
| `M2` | `data/text/manuals/ROVE R2-4K User Manual.txt` | ROVE R2-4K, USB-C revision, supercapacitor (79 pp) |
| `M3` | `data/text/manuals/User Manual For New R2-4K.txt` | ROVE R2-4K, USB-C revision, later printing (80 pp) |
| `M4` | `data/text/manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.txt` | ROVE R2-4K DUAL (14 pp) |
| `M5` | `data/text/manuals/B0F9SX3JB9.txt` | ROVE R2-4K DUAL PRO (12 pp) |
| `M6` | `data/text/manuals/r3-manual-website-files.txt` | ROVE R3 (3 pp, condensed) |
| `M7` **(4.3)** | `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt` | ROVE R2-4K DUAL PRO — Rove's own manual, 91 pp, with a source URL |
| `O1` | `data/raw/official/firmware-update-downloads.html` | Firmware Update & Downloads |
| `O2` | `data/raw/official/connect-rove-to-phone.html` | "Connect a ROVE Dash Cam to Your Phone: ROVE App Guide" |
| `O3` | `data/raw/official/update-firmware-r2-4k.html` | "How to UPGRADE FIRMWARE For Rove R2-4K Dashcam" |
| `H:<name>` | `data/raw/help-center/<name>.html` | Help Center article |

**(4.3) `M5` vs `M7`.** Both are the DUAL PRO. `M5` is the 12-page manuals.plus capture
uploaded by hand with no source URL; `M7` is Rove's own 91-page printing, fetched from
`cdn.shopify.com`, and it carries the troubleshooting table, the temperature guideline and
the parking-mode thermal note that `M5` has nothing of. Both stay in the registry — `M5` is
not wrong, it is thin — but where the two could be cited for the same fact, `M7` is cited.

**(4.3) The six Help Center bodies now on disk.** `H:overheating`, `H:licence-plate`,
`H:blurry-video`, `H:random-restarting`, `H:repeatedly-on-off`, `H:frozen-screen`. Four of
these were named in "What is still unknown" item 4 below as articles whose bodies were not
captured; that item is now closed.

**A note on `M1` vs `M2`/`M3`.** These are three printings of the *same model name* covering
**two different hardware revisions**. `M1` documents a mini-USB body with a 250 mAh internal
Li-ion battery and a RESET button; `M2`/`M3` document a USB-C body with a supercapacitor and
no battery. This distinction was not in the taxonomy and it changes two entries outright
(`PWR-04`, `FW-02`). Any agent that asks "which Rove do you have?" and stops at "an R2-4K"
has not finished identifying the device.

---

## Headline counts

| Outcome | Count | Entries |
|---|---:|---|
| **VERIFIED** | **10** | `WIFI-05`, `FW-01`, `FW-02`, `APP-03`, `REC-01`, `REC-02`, `REC-04`, `SD-03`, `VID-01`, `VID-03` |
| **CORRECTED** | ~~13~~ **14** **(4.3)** | `WIFI-01`, `WIFI-02`, `WIFI-03`, `WIFI-04`, `FW-04`, `APP-01`, `REC-03`, `SD-01`, `SD-04`, `PWR-01`, **`PWR-02`**, `PWR-03`, `PWR-04`, `VID-02` |
| **REJECTED** | **1** | `SD-02` |
| **UNVERIFIED** | ~~4~~ **3** **(4.3)** | `FW-03`, `APP-02`, `APP-04` |
| **Total** | **28** | |

**(5.2) This table covers Categories A–G only.** Nine more items — the four Category H
entries and the five guards — were added in Milestone 5.2 and none of them changed a row
here. The combined count is in
["Headline counts after 5.2"](#headline-counts-after-52).

**(4.3) One entry moved: `PWR-02`, UNVERIFIED → CORRECTED.** Nothing else changed status.
Nineteen entries gained a source without changing outcome — the whole of categories A, D, E,
F and G plus `FW-04` — because `M7` documents the DUAL PRO in depth where `M5` only
summarised it. See the deltas section.

Separately, in `02` §1 (the model-line section, not one of the 28 entries):
**2 model hypotheses REJECTED** (Stealth, Horizon) and **4 models added** that the taxonomy
did not carry. See "The model list and the screenless question" below.

### How to read the outcomes

- **VERIFIED** — a Tier 1 source states the fact or endorses the step. These are the
  entries whose next step can now be promoted from `TO VERIFY` toward speakable.
- **CORRECTED** — the entry is salvageable but something in it was wrong: a cause ranked in
  the wrong place, a fact marked `Unknown` that is actually published, or a step that Tier 1
  replaces with a better one. The correct fact is given in the table and written into `02`.
- **REJECTED** — the hypothesis's own discriminating premise does not exist in the product.
  The step is not worth a turn and has been replaced.
- **UNVERIFIED** — no Tier 1 source in this corpus covers it. Not "wrong" — unevidenced.
  These stay `TO VERIFY` and must not be spoken.

**Eleven of the thirteen CORRECTED entries were corrected in the same direction:** the
taxonomy marked something `Unknown` that Rove publishes plainly. The dominant failure of
`02` was not bad reasoning, it was assumed secrecy.

---

## Per-issue verification table

### Category A — Wi-Fi connectivity

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `WIFI-01` | **CORRECTED** | The cause is confirmed and named: the camera's AP carries no internet, so the phone leaves it — *"This is how Apple designed its operating system to work."* But the hypothesised step (watch the Wi-Fi list to split phone-side from a camera-side AP timeout) is the wrong move, because **no camera-side timeout exists** — Wi-Fi has `OFF` / `ON - Once` / `Always On`, and *"can stay ON at all times."* The documented action is to accept the no-internet prompt: iPhone → **Keep Trying Wi-Fi**; Android → wait 10–15 s, then **Always connect** (or tick *Don't ask again for this network* → YES). | `O2` §"'No Internet' message? That's normal"; `H:wifi-connected-disconnected`; `M3` §WIFI (p.61), §WIFI VOICE GUIDANCE |
| `WIFI-02` | **CORRECTED** | Reading the screen is reasonable but is not the documented first move. Wi-Fi must be switched on **at the camera**, by a model-specific control: R2-4K and R2-4K PRO → press and hold the **Emergency Lock** button for 2 s (or System Settings > WiFi); R3 → tap the screen > Settings > System Settings > WiFi icon (solid red = on). The taxonomy's cause 4 (phone scanning a band the camera does not use) is **verified and under-ranked**: on DUAL, DUAL PRO and R3 the camera may be on 5 GHz, which some phones will not show — change **WiFi Mode** from 5 GHz to 2.4 GHz in System Settings. On the R2-4K there is nothing to switch. | `O2` §"How to turn on WiFi on each ROVE model", §"Can't see the ROVE network?"; `H:wifi-not-connecting`; `H:wifi-name-not-showing`; `M3` p.61 |
| `WIFI-03` | **CORRECTED** | The forget-and-re-enter step stands, but the entry's central restriction is wrong. The default Wi-Fi password is **`12345678`**, it is published in four manuals and on the official site, and **the camera displays it on its own screen when Wi-Fi is on**. The agent may state it. The SSID is also knowable rather than secret (see the SSID table below). Cause 1 (password changed previously) is real: changing the Wi-Fi name and password is a documented feature. | `M2` p.33 and p.57; `M3` p.33 and p.61; `M1` p.44; `M6`; `O2` §FAQ *"What is the ROVE dash cam WiFi password?"*; `H:know-your-dashcam-how-to` §"How to change the WiFi name and password of my dash cam?" |
| `WIFI-04` | **CORRECTED** | Cause 1 — a camera-side idle/session timeout by design — **is not documented anywhere in the corpus**, and the manual states the opposite: the Wi-Fi feature *"can stay ON at all times"*, with an explicit `Always On` setting that survives restart. The documented drop causes are (a) range — Wi-Fi reaches **about 10 m / 33 ft** with no obstructions — and (b) phone-side priority switching away from a no-internet network, named for Apple devices specifically. Step becomes: confirm the caller is within 10 m with the camera in view, then treat it as `WIFI-01`. | `M2` §WIFI VOICE GUIDANCE (p.63); `M3` p.61; `O2` §Quick answer, §"Can't see the ROVE network?"; `H:wifi-not-connecting`; `M6` §"Wi-Fi Connection Issues" |
| `WIFI-05` | **VERIFIED** | Download-rather-than-stream is the right discriminator, and Tier 1 now supplies the numbers to judge the answer against: R2-4K — WiFi 6 on 2.4 GHz, *"not stated in the manual"*; R2-4K DUAL — up to **20 MB/s**; DUAL PRO and R3 — up to **30 MB/s over 5 GHz**. Two additions: connecting from the phone's own Wi-Fi settings rather than through the app is *"about 2× faster"*, and on a PC, lag on playback is attributed to high bit-rate files, not to the card. | `O2` §"How to turn on WiFi on each ROVE model", §Tip, §FAQ *"How fast are downloads?"*; `M4` §3; `M5` §"Dual Band WiFi 6"; `M3` §Troubleshooting *"My Video playback on PC is lagging"* |

### Category B — Firmware update / compatibility

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `FW-01` | **VERIFIED** | "Do not unplug, watch for a moving indicator" is exactly the documented instruction, and the indicator can now be named. Card-side update: *"You should see the blinking RED LED which means the firmware is being updated"* (`O3`), *"the flashing RED/BLUE LED on the left upper corner"* (`O1`), under the heading **"Don't Disconnect the Power"**. OTA update: *"The camera screen will display the progress of the firmware update. Allow the update to complete without interruption."* Completion signal: the camera restarts by itself. | `O3` §"AT A GLANCE"; `O1` §"Manual Firmware Update Guide", §"Over The Air Firmware Update" |
| `FW-02` | **VERIFIED** | The card-out test is confirmed and so is the mechanism behind it. Rove instructs formatting the card **immediately after** an update *"so your camera does not keep updating the firmware every time it restarts"* — cause 3 (a firmware file on the card re-read at every boot) is real and officially acknowledged. The Help Center also runs a card-out step: *"If the camera turns on without the card, the memory card may be corrupted or incompatible."* Two further additions: the R2-4K family has a **RESET button at the bottom of the camera, near the serial-number label (R2XXXXXXXXX)**, while the **R3 has no reset button** — on the R3 a failed update presents as missing icons or an unresponsive touchscreen and the documented route is to email customer care for a manual reflash. | `O1` §"Manual Firmware Update Guide"; `O3`; `H:camera-does-not-turn-on` §"Remove the memory card", §"Perform a hard reset"; `M3` §Troubleshooting (p.75); `M6` §"Display and Touch Screen Issues" |
| `FW-03` | **UNVERIFIED** | **No Tier 1 source in this corpus states that a firmware update resets settings to defaults.** The entry's central premise is unevidenced — not contradicted, just unsupported. What the corpus does hold: two specific real post-update issues (a compass-direction bug fixed *by* updating; a failed update leaving icons missing or the touchscreen dead), and a recurring "restore defaults, set date/time, format the card" opening move in several troubleshooting flows. There is still **no public known-issue or release-note feed**, so `01` §8 Q5 remains open and this entry remains undiagnosable by the agent. | `M6` §"G-Sensor Settings", §"Firmware Update Issue"; `H:missing-videos`; `H:r3-no-gps-live-speed` §Step 4 |
| `FW-04` | **CORRECTED** | The hypothesis asks the caller to go and find out whether an in-app update path exists. It does, on every current model, and its location is published — so the agent should **navigate the caller to it rather than discover it**: connect the phone to the camera's Wi-Fi, open the ROVE app, tap **Firmware Update in the app's left menu**, follow the on-screen steps, keep the camera powered. The card-side path is the fallback and is fully documented (format in camera → copy unzipped firmware to the card root → camera plugged in and **turned OFF** → insert card → press Power once → red LED blinks → camera restarts itself → **format the card again**). A caller with no card reader can reach the card over the camera's own USB using **"Connect as USB Flash Drive"** — except on the DUAL PRO, which cannot connect to a computer at all. | `O2` §"How to update your dash cam's firmware", §"How to move videos to a computer instead"; `O1`; `O3` §STEP 2; `M3` §FIRMWARE UPDATE (p.12); `M2` §FIRMWARE UPDATE (p.12) |

### Category C — Mobile app pairing

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `APP-01` | **CORRECTED** | A swipe-close-and-reopen is not the documented move. Tier 1's cheap first steps are **tap "Retry Connect to Dash Cam"** on the app's Live Video screen, and **confirm the correct dash cam model is selected in the app** — a failure mode the taxonomy does not carry at all. Tier 1's stale-session remedy is heavier than a restart: clear cache, or uninstall and reinstall, then allow all permissions. Two causes are confirmed and two are added: VPN interception is explicitly called out (*"Turn OFF your VPN / anti-virus software / Wi-Fi calling"*), **a memory card must be inserted for Wi-Fi to work at all**, and CarPlay / Android Auto and cellular data should be turned off. | `O2` §Step-by-step, caption *"tap Retry Connect to Dash Cam"*; `H:wifi-not-connecting`; `H:wifi-name-not-showing` |
| `APP-02` | **UNVERIFIED** | **Nothing in this corpus mentions phone OS updates, app-version compatibility, or checking the store listing's Update/Open button.** The only app-repair guidance is uninstall and reinstall from the published Android and iOS links. The hypothesis is untested, not wrong. | `H:wifi-not-connecting`; `H:sign-in-error-rove-app` §Step 4 |
| `APP-03` | **VERIFIED** | The step is right and, more usefully, the explanation no longer has to be invented — Rove publishes it: *"Allow location access when the app asks. The app uses it to find and auto-connect to nearby ROVE dash cams."* The Help Center widens the set: *"grant access or permissions to the app, such as Location, Media Library, and Camera. Sometimes, phone apps are unable to connect to Wi-Fi without having the necessary permissions."* The agent may now give the caller a sourced reason rather than a plausible one. | `O2` §"Before you start"; `H:wifi-not-connecting` |
| `APP-04` | **UNVERIFIED** | **No Tier 1 source states that the camera accepts only one client at a time.** The hypothesis is untested and the old-phone test cannot yet be justified on the record. One Tier 1 fact does reshape the entry and belongs in the cause list: the ROVE app requires a **registered account**, and *"the app needs normal internet to register you"* — so a new phone must complete sign-up over home Wi-Fi or mobile data **before** joining the camera's network. Account and verification-email problems have their own Help Center article. | searched: all 6 manuals, `O1`–`O3`, 12 Help Center files — no hit; `O2` §"Before you start"; `H:sign-in-error-rove-app` |

### Category D — Not recording / loop recording

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `REC-01` | **VERIFIED** | Preserve-first is correct and the ordering is now sourced: *"Do NOT insert/remove the memory card while the camera is turned ON. Only do so when it is turned OFF"*, and *"Always turn the camera off before you remove or insert the memory card."* The urgency is **greater** than the entry assumes. Locked event files are **not** permanently safe: the event directory is capped at **30 % of the card**, and once that allocation is exhausted *"the camera will also delete your oldest locked video to add that new latest event video."* Rove's own instruction is to *"download any locked video ASAP to prevent it from being deleted."* | `M3` §LOOP RECORDING IMPORTANT (p.46), §NOTE (p.14); `O2` §"How to move videos to a computer instead" |
| `REC-02` | **VERIFIED** | Reading the screen is right, and Tier 1 adds a stronger voice-native alternative: the camera has a **failsafe that announces every 30 seconds that it is NOT recording**, so the agent can ask what the caller *hears* rather than what they can see. The screen targets are now concrete too — the documented strings are **"Memory Card Error"**, **"Please Insert microSD Card"** and **"Card Full"**, and the positive indicator is *"the flashing red dot and the recording timer counting up on the top-right area of the screen"*, started with the **OK** button. | `M3` §CAUTION under VOICE GUIDANCE (p.64), §Troubleshooting (pp.75–77); `H:missing-videos` §"Start recording and confirm the red dot/timer" |
| `REC-03` | **CORRECTED** | The question (were the clips locked, or ordinary?) is right. **The branch it feeds is wrong.** The entry escalates "a clip I locked disappeared" as a defect; Tier 1 documents that exact behaviour as designed. Loop recording begins when normal + event files exceed **90 %** of the card; normal is pre-allocated **60 %** and event **30 %**; and when the event allocation is full the oldest *locked* file is deleted to make room for a new one. *"You can't lock unlimited videos to your memory card."* A second documented cause the entry lacks: a G-sensor set too sensitive locks so many clips that the event area fills — *"Camera Locks many videos automatically → change your G-Sensor Setting to a higher setting."* | `M3` §LOOP RECORDING IMPORTANT (p.46), §Troubleshooting *"Camera Locks many videos automatically"* (p.76); `M5` §"Emergency Video Lock" |
| `REC-04` | **VERIFIED** | Establishing the power source first is correct and the hardware dependency is confirmed across the whole line: 24-hour parking mode **requires the ROVE Ultimate USB Type-C Hardwire Kit, sold separately** — no kit, no parking mode, on every model including the DUAL PRO. Cause 1 is confirmed in Rove's own words: *"Some trucks'/cars' 12V cigarette outlet is always HOT"*, and the converse — a socket that dies with the ignition — is the normal case. Cause 4 is now quantifiable: the kit has selectable battery-drain cutoffs at **11.8 / 12.0 / 12.2 / 12.4 V**. A separate Help Center article covers *"Hardwire kit Not Detected"*. | `M3` §24-HR AUTO PARKING MODE (p.51), §AUTO POWER ON/OFF CAUTION (p.19), §spec table; `M5` §"24-Hour Parking Monitor"; `M4` §3; `M6`; `H:troubleshoot-index` |

### Category E — SD card / storage

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `SD-01` | **CORRECTED** | Reseating is not Rove's documented procedure for this error, and a better discriminator exists. For *"Memory Card Error"* or *"Please Insert microSD Card"*, the manual's ordered steps are: (1) confirm the card is at least **Class 10 / U3** and from a trusted vendor — *"there are many fake cards out there online"*; (2) format in the camera, power off, unplug and re-plug; (3) **switch to PHOTO mode (hold MENU) and press OK** — *"if you hear the shutter sound, your camera is fine, replace your memory card. If you still get the same memory card error, then your camera's memory card assembly has become defective."* That photo test splits card from slot on one action, which is cleaner than reseating and it is official. Misalignment is covered separately: *"align microSD card correctly with gold contacts facing towards the Lens."* | `M3` §Troubleshooting (p.77), §Troubleshooting *"microSD Card is crooked"* (p.76); `H:memory-card-too-slow` |
| `SD-02` | **REJECTED** | The hypothesis asks how many clips the caller has locked, on the premise that locked files filling the card can stop recording. **That cannot happen.** When the event allocation is full the camera deletes the oldest locked file and carries on — it does not stop. The documented cause of a hard stop is the other branch, alone: **Loop Recording set to OFF**, in which case *"the camera will continue to record each file 4GB in size until the memory card becomes full and then it will give you a 'Card Full' message. It will NOT record any further."* Replacement step: check Loop Recording and set it to 1, 3, 5 or 10 minutes (Video Mode settings > Loop Recording), after formatting. | `M3` §LOOP RECORDING (p.46), §Error/Message "Card Full" (p.75); `M1` p.43 |
| `SD-03` | **VERIFIED** | Trying a different player is exactly Rove's advice, and the player can now be named instead of described: **VLC Media Player**, and explicitly *"Do NOT use Windows Media Player or QuickTime Player (Mac). They are NOT made..."* for these files. `O2` repeats the VLC recommendation. The Help Center uses the same move for audio: *"Try playing the file in a different media player if needed."* A second cause worth carrying: slow playback on a PC is attributed to high bit-rate files and a slow computer, not to corruption. | `M3` p.11 and §"Correct Video Player To Play 4K VIDEOS" (p.41); `M1` p.11 and p.38; `O2` §"Playing videos"; `H:no-audio-sound` |
| `SD-04` | **CORRECTED** | Asking for brand, capacity and speed markings is right, and the limits the entry marked `Unknown` are published — but they are **model-dependent**, which the entry does not allow for: **Class 10 / U3 minimum** on every model; **512 GB maximum** on R2-4K, R2-4K PRO and R3; **up to 1 TB** on R2-4K DUAL and DUAL PRO. The symptom framing also needs correcting: *"I have to format it every couple of weeks"* is not automatically an end-of-life signature, because **Rove instructs formatting every 2–3 weeks** as routine maintenance (the DUAL and DUAL PRO manuals say at least monthly). The agent must establish whether the caller means scheduled maintenance or a card that has failed. Counterfeit cards (cause 4) are called out repeatedly. | `M3` p.6, p.14, §spec table; `M2` §spec table; `M6`; `M4` §6; `M5` §"MicroSD Card Management"; `O1` §"Manual Firmware Update Guide" (card note); `H:know-your-dashcam-how-to` §"Should I format the memory card?"; `H:memory-card-too-slow` |

### Category F — Power / overheating

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `PWR-01` | **CORRECTED** | The socket test is a good step but it is not Rove's first one, and Rove's is stronger. The documented order starts by **removing the vehicle from the equation**: bring the camera indoors and power it from a **110 V wall outlet** with the short USB cable — which eliminates socket, fuse *and* car-side wiring together, not just the socket. Then: swap to the other included cable → remove the memory card → **press the Power button once** (*"on some ROVE models, the camera does not automatically power on when connected"*) → hard reset with a paper clip at the **RESET button on the bottom, near the serial-number label** → contact support. Note the R3 has **no reset button**; unplug and re-plug instead. | `H:camera-does-not-turn-on` §"Before you begin", §"Try these options one by one"; `M3` §Troubleshooting *"Camera does not turn ON"* (p.75); `M6` |
| `PWR-02` | ~~UNVERIFIED~~ **CORRECTED (4.3)** | **The overheating article's body is now on disk, and it documents the thermal cut-off the entry hypothesised.** *"ROVE dash cams are designed to operate between -4°F and 140°F (-20°C to 60°C). To protect itself, the device may slow down, shut off, or stop recording beyond that."* `M7` states the mechanism outright: the camera has a **built-in temperature sensor**, a locked car in direct sun *"turns into a greenhouse effect"*, and *"when this happens, the camera will automatically shut down to prevent damage to the unit."* **Cause 1 is therefore confirmed, and the entry's instruction that operating limits are `Unknown` and `must not be quoted` is wrong** — they are published, and they are **model-dependent**: −4 °F to 140 °F (−20 °C to 60 °C) on the R2-4K family, **14 °F to 131 °F (−10 °C to 55 °C) on the DUAL PRO**, storage −4 °F to 158 °F. **Cause 3 (battery degradation) is wrong for most of the line** — the USB-C R2-4K, DUAL, DUAL PRO and R3 have a supercapacitor and no battery (see `PWR-04`). **Three causes the entry does not carry are documented:** a non-U3 or counterfeit card making the processor work harder, unsupported power sources (power banks, OBD2 adapters, third-party chargers) drawing unstable current, and **Parking Mode left running in extreme heat**. The prevention list is citable in full: U3 card, in-camera format every 1–2 weeks, shade or a sunshade, ROVE-approved power, a shorter parking timer (1–3 hours) or Parking Mode off on hot days. The escalation trigger gains a documented form alongside swelling and burning smell: *"consistently overheats, shuts off without warning, or displays a 'High Temperature' error"* → stop using the device and contact support. **What is still not verified is the entry's own discriminator:** no Tier 1 source states that the camera recovers by itself once the car cools, so "does it come back on?" stays `TO VERIFY` and the agent must not promise recovery. That is why this is CORRECTED and not VERIFIED. **A correction to the original pass, too:** the thermal-shutdown note was already in `M2` and `M3`; the first pass missed it, and the Help Center body is what made it unmissable. | `H:overheating` (whole article); `M7` §24-HR AUTO PARKING MODE NOTE (p.59), §Temperature Guideline (p.13), §Troubleshooting *"Camera gets HOT"* (p.86); `M2` §NOTE (p.50), §Temperature Guideline; `M3` §Temperature Guideline (p.12), §Troubleshooting (p.76); `M6` |
| `PWR-03` | **CORRECTED** | The entry treats a hardwire kit as the likely cause and rules the whole category out of scope. Tier 1 ranks it the other way and offers fixes the agent **can** give. The normal case is a socket-powered camera in a vehicle whose 12 V socket is permanently live — *"Your dash cam is working correctly — this is a vehicle power socket issue"* — because the camera is designed to power on when it receives power and off when power is removed. Five documented solutions, easiest first: (1) move to a **vehicle USB port that cuts with the ignition**; (2) **press and hold Power for 2 seconds** after parking — *"works on all ROVE models"*; (3) unplug the car charger; (4) re-route the 12 V fuse to a switched circuit; (5) fit a hardwire kit. Only (4) and (5) are out of scope — (1) to (3) are in scope and the entry currently forbids them. Where a kit is fitted, the cutoff values are 11.8 / 12.0 / 12.2 / 12.4 V. | `H:camera-does-not-turn-off` §"Why does this happen?", §"5 ways to fix this"; `M3` §AUTO POWER ON/OFF CAUTION (p.19), §MANUAL POWER ON/OFF; `M3` §spec diagram (cutoff voltages) |
| `PWR-04` | **CORRECTED** | Cause 1 (internal cell at end of life) is wrong for most of the line and the hour-on-power test does not discriminate. On the USB-C R2-4K, R2-4K PRO, R2-4K DUAL and R3 there is **no battery at all** — a supercapacitor that *"will hold the charge for about 2 seconds"* by design, so not holding the time unpowered is expected, not a fault. Only the **original mini-USB R2-4K** has an internal battery (250 mAh). The documented cause and fix is the clock source: **System Settings > Time Zone Setting > set the correct GMT value > OK**, after which *"every time you have GPS signal, you will always have correct date and time."* Replacement step: check the GMT/time-zone setting and whether the camera is getting a GPS lock, before suspecting hardware. | `M3` §Troubleshooting *"My date and time is not staying the same"* (p.77), §ABOUT SUPERCAPACITOR (p.21); `M1` §spec table (250 mAh Li-ion); `M6` §Supercapacitor; `H:know-your-dashcam-how-to` §"How to set GPS Time Zone Setting"; `H:missing-videos` |

### Category G — Video quality / settings

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `VID-01` | **VERIFIED** | The protective-film-and-dirt check is Rove's own first step, in the manual and in both dual-model troubleshooting tables: *"Make sure to remove the Plastic Lens Screen Protector"*; *"Ensure the protective film has been removed from the lenses"*; *"Video is fuzzy → make sure the lens of the camera is clean and there is no dirt or grease on the windshield."* Two model-specific additions: where a **CPL filter** is fitted, adjust or remove it to test; and the DUAL PRO has a **Dual Video IQ Mode** whose default, *Clarity Priority*, is *"optimized for sharp license plate details"* — so a caller on Color Priority has a setting-level fix the entry does not know about. Rove treats persistent close-range blur as a possible manufacturing defect, which matches the entry's escalation trigger. | `M3` p.21 and §Troubleshooting *"Video is fuzzy"* (p.75); `M5` §Troubleshooting, §"Dual Video IQ Mode"; `M4` §7 |
| `VID-02` | **CORRECTED** | The reflection diagnosis is supported, but the entry's conclusion — *"no camera setting whatsoever fixes a reflection"* — is wrong for this product line, and acting on it would close a solvable call. Rove sells and documents a **CPL (circular polarising) filter** for exactly this: *"reduce glare and reflections from the windshield, improving video clarity"*, *"reducing glare and reflections, improving color saturation and contrast."* It ships in the box with the DUAL and DUAL PRO and is sold separately for the R2-4K and R2-4K PRO. The in-car advice (dark dash mat, clear the dashboard) still holds, and `WDR` is a real named setting on the R2-4K that *"improves the exposure"*. | `M5` §"Attach CPL Filter", §Troubleshooting; `M4` §3 and §7; `M3` §WDR (p.47); `H:know-your-dashcam-how-to` §"How to effectively install the CPL filter?" |
| `VID-03` | **VERIFIED** | Splitting audio from timestamp and taking audio first is right, and both halves are now concrete. Audio: the mute control is the **UP button** — *"Press Once - to Mute/UN-Mute Microphone while in Video Mode"*, confirmed by the Help Center (*"On many ROVE models, pressing the UP button while recording can mute or unmute the microphone"*), with **Microphone ON / Microphone OFF** indicators on screen and a `Record Audio` setting in the menu. On the **R3, audio recording is OFF by default**, so a caller who never changed it has no fault at all. The Help Center adds a cause the entry lacks: playback audio routed to Bluetooth, headphones or the car stereo rather than the phone. The timestamp half routes to `PWR-04`, which is now the GPS time-zone branch. | `M3` §button table (p.16), §RECORD AUDIO (p.60), §screen icons (p.24); `H:no-audio-sound`; `M6` §"Audio recording and parking mode" |

---

## The model list and the screenless question

### The verified Rove dash cam line

Taken from the official downloads page's own manual links and product listings, plus the
model names printed inside the manuals.

| Model | Status in Tier 1 | Screen | Wi-Fi | Card maximum |
|---|---|---|---|---|
| **ROVE R1** | Named in `M2`/`M3` only, as a legacy supercapacitor model. No manual, no listing. | Unknown | Unknown | Unknown |
| **ROVE R2-4K** (original, mini-USB) | Manual on disk (`M1`). 250 mAh Li-ion battery, RESET button. | **2.4" LCD** | — | 512 GB, Class 10 / U3 |
| **ROVE R2-4K** (USB-C) | Manuals on disk (`M2`, `M3`); current product. | **2.4" IPS** | WiFi 6, **2.4 GHz only** | 512 GB, Class 10 / U3 |
| **ROVE R2-4K PRO** | Listed, manual linked (`ROVE_R2-4K-PRO_User_Manual_Updated_JAN-2025.pdf`), **not downloaded**. | **2.4" IPS** (from the product listing) | 5 GHz / dual-band (listing) | 512 GB (listing) |
| **ROVE R2-4K DUAL** | Manual on disk (`M4`). Front + rear. | **3" IPS** | Dual-band **5 GHz + 2.4 GHz**, up to 20 MB/s | **Up to 1 TB** (128 GB included) |
| **ROVE R2-4K DUAL PRO** | Manual on disk (`M5`). Front 4K + rear 2K, STARVIS 2 IMX678/IMX675. | **3" IPS** | **WiFi 6 dual-band 5 GHz + 2.4 GHz**, up to 30 MB/s | **Up to 1 TB** (128 GB included) |
| **ROVE R3** | Manual on disk (`M6`). 3-channel (front / cabin / rear). | **Touchscreen LCD** | Dual-band 5 GHz, up to 30 MB/s | 512 GB, Class 10 / U3 |
| **ROVE R4** | Pre-launch only — early-access signup on the downloads page. No manual, no specs. | Unknown | Unknown | Unknown |

**Not dash cams.** `ROVE RS2` and `ROVE RS4` appear on the same site and in the same manual
index; both are **articulating borescope inspection cameras**. An agent that pattern-matches
`R`+digit will mis-route these. Worth a guard.

### Verdicts on the §1 model hypotheses

| Hypothesis in `02` §1 | Verdict | Basis |
|---|---|---|
| Rove R2-4K | **VERIFIED**, with a correction: it is **two hardware revisions**, mini-USB/Li-ion and USB-C/supercapacitor, which diverge on `PWR-04` and on the reset path | `M1` vs `M2`/`M3` |
| Rove R2-4K Pro | **VERIFIED** as a real, current model | `O1` manual link and product listings |
| "Rove R2-4K Duo / dual-channel variant" | **CORRECTED** — it exists, is called **R2-4K DUAL**, and there is also a **R2-4K DUAL PRO**. The taxonomy was right that this opens a rear-channel failure mode it does not carry, and Tier 1 confirms the mode: *"rear camera cable connected to sticky mount power port"*, *"rear camera not securely connected"* | `M4`, `M5`, `O1`, `M6` |
| Rove R3 | **VERIFIED** as a real, current model — and it is **3-channel with a touchscreen**, which the taxonomy did not know. The instruction *"do not let the agent branch on R2-versus-R3"* is now **wrong**: they differ on screen type, Wi-Fi control, channel count, reset availability and audio default | `M6`, `O1`, `O2` |
| **Rove Stealth** | **REJECTED** | Zero occurrences of "stealth" across all 6 manuals, all 3 official pages and all 12 Help Center pages |
| **Rove Horizon** | **REJECTED** | Zero occurrences of "horizon" across the same 21 files |
| Discontinued units in customers' hands | **VERIFIED** | The mini-USB R2-4K (`M1`, firmware dated 2017) is a distinct earlier revision still documented separately, and `H:wifi-connected-disconnected` carries a dedicated *"Manual Firmware Update for ROVE R2-4K mini-USB version"* procedure |
| Models missed entirely | **R1** (legacy, named in `M2`/`M3`) and **R4** (pre-launch) | `M2` p.49, `M3` p.52, `O1` |

### Is any in-scope model screenless?

**No. This was the single most consequential question in `02` §1 and the answer clears it.**

Every Rove dash cam documented in the Tier 1 corpus has a screen: 2.4" LCD on the original
R2-4K, 2.4" IPS on the USB-C R2-4K and the R2-4K PRO, 3" IPS on the DUAL and DUAL PRO, and a
touchscreen on the R3. No model in the line is described as screenless, low-profile,
wedge-style or mirror-mounted anywhere in the corpus.

**Consequence:** the "ask the caller to read the screen aloud" steps in `WIFI-02`, `REC-02`
and `SD-01` are structurally sound and the parallel LED-and-beep evidence path that `02` §5
called for is **not needed**. Two caveats, both from Tier 1:

1. **A screen saver can hide the screen.** The DUAL PRO's screen saver activates after one
   minute of inactivity; the R2-4K and R3 have configurable screen-saver and LCD-off
   settings, including *"turning off only the LCD while continuing to record"*. A caller
   reporting a blank screen is not necessarily reporting a dead camera.
2. **A voice-native channel exists and is better suited to a phone call than reading a
   screen.** The cameras speak: a failsafe announcement **every 30 seconds** when the camera
   is on but not recording, Wi-Fi connected/disconnected announcements, and a parking-mode
   activation alert. On a voice call, "what is it saying?" may outperform "what does it say
   on the screen?" — a design opportunity the taxonomy does not currently use anywhere.

### Wi-Fi SSID patterns, password and bands

**SSID — CORRECTED.** The taxonomy's shape (`ROVE_<model>_<hex>`) was close, but it told the
agent *not* to name a network. It can, and should, name the prefix:

| Model | Network name starts with | Band |
|---|---|---|
| ROVE R2-4K | `ROVE_R2-4K_` (printed as `ROVE_R2-4K_*********`; the older mini-USB manual prints `ROVE R2-4K-*********`) | WiFi 6, 2.4 GHz only |
| ROVE R2-4K DUAL | `ROVE_R2-4K-DUAL_` | Dual-band 5 GHz + 2.4 GHz |
| ROVE R2-4K DUAL PRO | `ROVE_R2-4K-DUAL_PRO` | WiFi 6, dual-band 5 GHz + 2.4 GHz |
| ROVE R3 | `ROVE_R3_` or `Rove_R3_` | Dual-band 5 GHz + 2.4 GHz |

Generic form used by the Help Center: `ROVE_R***_******`.
Source: `O2` §"How to turn on WiFi on each ROVE model"; `M3` p.61; `M2` p.57; `M1` p.44;
`H:wifi-not-connecting`.

**Password `12345678` — VERIFIED.** It is the published default on every model and it is
also **shown on the camera's own screen** when Wi-Fi is on. It appears in `M2` (pp.33, 57),
`M3` (pp.33, 61), `M1` (pp.33, 44), `M6`, `O2` (§FAQ) and `H:wifi-not-connecting`. The
`WIFI-03` prohibition on speaking it is lifted. The name and password **can** be changed by
the owner, so a rejection on `12345678` is informative rather than conclusive.

**2.4 vs 5 GHz — CORRECTED.** The hypothesis "Wi-Fi is 2.4 GHz only; no 5 GHz" is true for
exactly one model. It holds for the **R2-4K**, which *"only uses 2.4GHz, so there's nothing
to switch."* It is false for the **DUAL**, **DUAL PRO** and **R3**, all dual-band, and the
R2-4K PRO is listed as 5 GHz. This matters twice over: 5 GHz is where the 20–30 MB/s
download figures come from, and *"some phones don't show 5GHz networks"* — so on those three
models, **changing WiFi Mode from 5 GHz to 2.4 GHz in the camera's System Settings** is a
real, documented fix for `WIFI-02` that the taxonomy does not carry.

### Firmware update paths

Both hypothesised paths exist. Neither is `Unknown` any longer.

**OTA, via the ROVE app — all current models.** Connect the phone to the camera's Wi-Fi →
open the ROVE app → **Firmware Update** in the app's left menu → the app checks and reports
*"There is a NEW Firmware Update Available!"* → tap **UPDATE Firmware** → progress shows on
the camera screen → the camera restarts itself on completion.
Source: `O2` §"How to update your dash cam's firmware"; `O1` §"Over The Air Firmware
Update"; `M3` §FIRMWARE UPDATE (p.12); `M2` §FIRMWARE UPDATE (p.12).

**Manual, card-side — documented for the R2-4K including the mini-USB revision.** Format the
card in the camera → download and copy the **unzipped** firmware files to the card → keep the
camera **powered and switched OFF** → insert the card → **press the Power button once** →
blinking red (or red/blue) LED means it is writing → **do not disconnect power** → the camera
restarts and starts recording → **format the card again immediately**, otherwise it re-flashes
on every restart. Card access without a reader: connect over USB and choose **"Connect as USB
Flash Drive"** (not available on the DUAL PRO, which has no direct computer connection).
Source: `O3`; `O1` §"Manual Firmware Update Guide"; `H:wifi-connected-disconnected`; `M6`.

**`FW-04`'s open question is answered:** a caller with only a phone *can* complete an update,
because every current model supports OTA. The computer is required only for the manual
fallback.

### Firmware version numbers actually printed in the manuals

**Exactly one, and it is not usable as a current version.**

`M1` (`dc3831.txt`, p.51, §FIRMWARE VERSION) prints:

> `ROVE-R2-4K-06102017 (First - Original Firmware)`

That is the shipping firmware of the original mini-USB R2-4K, labelled as such. The newer
manuals (`M2`, `M3`) carry the same §FIRMWARE VERSION menu description — *"here you can check
the current firmware version installed on your camera"* — but print **no version string**.
`O1`'s per-model firmware downloads are rendered client-side and no version numbers survive
in the saved HTML.

**The `02` §4 rule therefore stands unchanged: the agent must never state, infer or confirm a
firmware version.** It may ask the caller to read theirs out — the camera shows it under
System Settings > Firmware Version, and the ROVE app displays it on the connected-camera
screen.

### App identity — VERIFIED

The app is **ROVE Dash Cam** (searched for as "ROVE"), free, on both the App Store and Google
Play. One fact the taxonomy did not have and that changes `APP-01`–`APP-04`: **it requires a
registered ROVE account, and sign-up needs ordinary internet** — *"Create your free account
first, while your phone is on home WiFi or mobile data. Don't connect to the dash cam's WiFi
yet: the app needs normal internet to register you."* There is also a desktop companion, the
free **ROVE Dash Cam GPS Player** for PC and Mac. No subscription exists for any of it.
Source: `O2`; `M2` p.32; `M3` p.32; `M5`; `H:sign-in-error-rove-app`;
`H:know-your-dashcam-how-to` §"Is there any monthly/annual Subscription and charges".

---

## What Tier 1 adds that the taxonomy has no entry for

Three of these were predicted as gaps in `02` §5. All three are now confirmed, and a fourth
is new.

> **(5.2) All nine items in this section now exist in `02`** — the four numbered below as
> full entries in Category H, the five in the paragraph after them as guards. Read this
> section as the statement of the gap and
> ["Milestone 5.2"](#milestone-52--phase-2-knowledge-completion) as what was found when it
> was filled. Item 2 below is **wrong in one clause** and is corrected there.

1. **Rear-channel failures (DUAL, DUAL PRO, R3).** Predicted in `02` §5 and now sourced:
   *"rear camera cable connected to sticky mount power port"* and *"rear camera not securely
   connected"* are named causes of no rear live view. Needs its own entry.
2. **GPS / live speed.** Built-in across the line (quad-mode GPS on the DUAL PRO). A whole
   Help Center article, *"R3: NO GPS Live Speed?"*, covers mount seating, placement, firmware
   and default-settings restore — and on the R3 the GPS lives **in the magnetic mount**, so a
   gap between mount and camera kills it. No taxonomy entry exists.
   **(5.2) The mount clause is not Tier 1.** Rove's step 1 is to close the gap; it never
   says why, and the only corpus text putting GPS inside the mount is a storefront product
   title. The step is speakable, the mechanism is not — see the `GAP-GPS` row below.
3. **Mounting.** Predicted as a likely high-volume gap and confirmed as a documented one,
   with a hard constraint the agent would otherwise never think to ask about: the mounts
   *"will NOT work properly on a flat windshield as they require at least a 20° slope/angle."*
4. **"Why does my video play in fast motion?"** — Time-Lapse Record left on. A one-step fix
   with its own Help Center article, and nothing in the taxonomy would catch it.

Also uncovered and worth entries or guards: *"Dash cam not playing automatically and giving
three options"* (the Operate Normally / Webcam / Storage boot prompt), *"Hardwire kit Not
Detected"*, *"Dash Cam Screen is Frozen"*, *"Dash Cam Repeatedly Turning ON and OFF"*, and
*"My dashcam is randomly restarting"* — the last of which Rove attributes to non-ROVE car
chargers not supplying enough power.
**(5.2) All five are now guards** — `GAP-BOOT-PROMPT`, `GAP-HWK-NOT-DETECTED`,
`GAP-FROZEN-SCREEN`, `GAP-ON-OFF-CYCLING`, `GAP-RANDOM-RESTART`. The non-ROVE-charger
attribution is confirmed, with one adjustment: it is the **manuals** that name the charger
(*"Only use ROVE's USB Car Charger, otherwise the camera may frequently reboot"*), while
the Help Center article itself is broader and names the cable and the card as well.
Item 4's *"one-step fix"* also needs a caveat — it is one step on the current models only.

---

## Milestone 4.3 — what the Track C sources changed

Seven documents were added: `M7` (Rove's own 91-page DUAL PRO manual) and the bodies of
`H:overheating`, `H:licence-plate`, `H:blurry-video`, `H:random-restarting`,
`H:repeatedly-on-off` and `H:frozen-screen`. This section is the whole of the delta. It was
produced by re-checking each per-issue row against the new files, not by re-running the
original pass.

**One entry changed outcome.**

| ID | Was | Now | What moved it |
|---|---|---|---|
| `PWR-02` | UNVERIFIED | **CORRECTED** | `H:overheating` documents the thermal cut-off, the published operating limits and four ranked causes; `M7` p.59 states the mechanism (built-in temperature sensor, greenhouse effect, automatic shutdown). The entry's recovery discriminator is still unsourced, which is why this is not VERIFIED. |

**Nineteen entries gained a source and kept their outcome** — `WIFI-01`…`WIFI-05`, `FW-04`,
`REC-01`…`REC-04`, `SD-01`, `SD-03`, `SD-04`, `PWR-01`, `PWR-03`, `PWR-04`, `VID-01`,
`VID-02`, `VID-03`. In nearly every case the new source is `M7`, which documents the DUAL
PRO in depth where `M5` only summarised it. `SD-03` and `VID-01` also gain
`H:licence-plate`; `VID-01` and `VID-02` also gain `H:blurry-video`; `SD-04` also gains
`H:overheating`.

**`VID-01` was re-checked and deliberately left VERIFIED.** `H:blurry-video` leads with
*"Remove the protective lens film"* and then *"Clean the dash cam lens"* and *"Clean the
windshield inside and outside"* — which is this entry's hypothesised first step, in Rove's
own order. `H:licence-plate` confirms cause 1, the expectation gap, in Rove's own words:
plate readability *"depends on lighting, distance, speed, angle, windshield glare, video
resolution, and how the video is played back"*. Both bodies corroborate the entry; neither
contradicts it; so there is nothing to correct and the status does not move. The one thing
they add is a playback caveat already carried by `SD-03` — judge quality from the original
file in **VLC** or the **ROVE GPS Player**, never from a compressed copy, a social-media
upload or a phone preview.

**`M7` is deliberately absent from `FW-01` and `FW-02`.** It documents no card-side update
path at all, and its one "BLINKING RED LED" line means *recording*, not *updating* — the
exact confusion `docs/02` calls device-destroying. It was not widened into those rules.

**Three of the six new articles support no taxonomy entry** — `H:random-restarting`,
`H:repeatedly-on-off`, `H:frozen-screen`. They are indexed and are UNVERIFIED and
unspeakable, which is the correct state for Tier 1 material with no Step 1b entry to hang a
status on. Writing those entries is Phase 2 work.

**Still open after 4.3.** The four missing taxonomy entries named above — rear-channel, GPS
/ live speed, mounting and time-lapse / fast-motion — were **not** written in this
milestone. They remain Phase 2 work (`docs/06` §9.1), and the three unmapped articles above
belong with them. `FW-03`, `APP-02` and `APP-04` were searched again against all seven new
files and are still unhit.
**Closed by Milestone 5.2** — see the next section.

---

## Milestone 5.2 — Phase 2 knowledge completion

**Amended 2026-11-07.** The four missing entries are written, and the five other finds in
"What Tier 1 adds that the taxonomy has no entry for" have guards. They live in
[`02` Category H](02-issue-taxonomy.md#category-h--known-gaps-gap-rear-channel--gap-timelapse).
Nothing above this section was deleted; nothing in Categories A–G changed status.

No new sources were added. The corpus is unchanged at **28 Tier 1 documents** — 7 manuals
(351 pages), 3 official pages, 18 Help Center articles. Category H was written entirely out
of material that was already on disk and already indexed, which is the point: `05`'s own
"What Tier 1 adds" list said this content existed, and this milestone spends it.

### The four entries

| ID | Outcome | What Tier 1 actually says | Source |
|---|---|---|---|
| `GAP-REAR-CHANNEL` | **CORRECTED** | The gap is real and the causes are named, but **the two quotes `05` recorded are R3 quotes, not line-wide ones.** *"Rear camera cable connected to sticky mount power port"* and *"rear camera not securely connected"* are the R3 manual's two reasons for no rear live feed; the **sticky-mount power port is an R3 mount feature**, and the DUAL and DUAL PRO take power into the camera body (`M7` §UNIT STRUCTURE: item 2 *"USB TYPE-C Rear Cam Port"*, item 14 *"USB TYPE-C … Power Port"* — the callout number falls between the two halves of the label in the extracted text — pp.14–15). The dual models have their own evidence: *"Make sure that you align and properly connect the rear camera cable properly. Otherwise, the front/main camera will not be able to detect it"*, and a damage path the taxonomy had nowhere to put — *"Make sure only to plug in the rear camera when the main (front) camera is turned OFF, otherwise it may damage the rear camera."* Two causes that are not cable faults at all: the **DOWN button switches front/rear view**, and Rove ranks *"Using a low-quality memory card"* **above** the rear connector as a cause of recording starting and stopping. | `M6` §"Rear Camera Live View Issue" (line 41–42), §"Recording Issues" (line 40–41), §Page 24 wiring (line 14); `M7` pp.14–15 (lines 613–689), p.16 (line 730), p.21 (lines 883–885), p.22 (lines 899–900), p.23 (lines 935–937); `M4` §4 steps 3–4 (lines 93–97); `M5` §3 (lines 84–88) |
| `GAP-GPS` | **CORRECTED** | The symptom is real, Rove's four-step R3 procedure is verbatim usable, and the corpus supplies three settings the entry needs: `VIDEO STAMPS` (independent `Speed Stamp` / `GPS Location Stamp`, *"By default, they are all ON"*), `LIVE SPEED & COMPASS` (*"By turning off this feature, it does NOT turn OFF the Driving Speed or the GPS metadata"* — screen only), and a **master `GPS` ON/OFF on the DUAL PRO** (*"NO GPS related data will be used across the device. (i.e. Live Speed, Speed Stamp, GPS Coordinates)"*) **which the R2-4K does not document**. The camera also reports its own fix state — a **GPS Indicator** icon with a distinct *"GPS Not Connected"* state, and a `GPS INFO` screen showing live latitude/longitude. **The correction is to this document.** `05` above, and `06` §4.7, state as fact that *"on the R3 the GPS lives in the magnetic mount"*. **No Tier 1 prose says that.** `H:r3-no-gps-live-speed` says to close the gap, not why; the only corpus text putting GPS inside an R3 mount is a **storefront product title on `O1`** (*"R3 Magnetic Mount with GPS…"*), which `docs/04` §"Download status" classes as listing material that must not be spoken. **The step is speakable; the mechanism is not.** | `H:r3-no-gps-live-speed` §Steps 1–4; `M3` §VIDEO STAMPS (p.58; lines 2036–2052), §LIVE SPEED & COMPASS (p.59; lines 2069–2077), §GPS INFO (p.66; lines 2283–2295); `M7` §GPS (p.74; lines 2865–2874), §"Home Screen Status Icons" (p.33; lines 1353–1436), §Quad-Mode GPS (p.77); `O1` §Mounts (listing — **not** cleared) |
| `GAP-MOUNTING` | **VERIFIED** | The constraint `05` predicted is published verbatim and it is a **product limitation, not a fault**: *"The short answer is - NO. Due to the camera and lens design, our mounts will NOT work properly on a flat windshield as they require at least a 20° slope/angle. You may want to try using a universal mount, but please use it with caution"*. Three documented causes sit under it that `05` did not have: the **dot-matrix band** (*"AVOID THIS … suction mount will NOT be able to get a strong suction, hence it will fall down if you mount on top of it"*), the two-handed **lock procedure** (*"Press & hold it tight towards the windshield to remove any air … While pressing & holding towards the windshield, turn the LOCKING Knob towards CLOCKWISE"*), and the rear-screen **defroster lines** note. | `H:know-your-dashcam-how-to` §"Can I mount the dashcam on a flat windshield?", §"How to effectively install the Suction Mount?", §"How to effectively install the 3M Sticky Mount?"; `M3` §INSTALLATION (pp.16–17; lines 556–605); `M7` p.20 (lines 847–860); `M6` (lines 9–12); `M4` §4 (lines 88–93) |
| `GAP-TIMELAPSE` | **VERIFIED** | Cause and fix are published together: *"Your footage looks like a time-lapse because the Time-Lapse Record setting is turned on. This is a quick, one-step fix directly in your camera's video settings menu."* Two things `05` did not record. **(a) It is one step only on the current models.** `M2`, `M3` and `M7` all warn that the setting survives a restart (*"Enabling this feature will keep it activated at all times, even after the camera restarts"*), while the **mini-USB `M1` documents the opposite** — *"Time-Lapse is OFF by default. It also programmed to set to OFF when the camera restarts every time"* — so on that revision persistent fast motion is unexplained by this entry. **(b) Parking mode records time-lapse by design** on the R3 and the DUAL PRO, so fast clips *only* from a parked car are an expectation gap, not a fault. **(c) Found on re-verification:** `M4`, the R2-4K DUAL manual, **does not mention time-lapse at all**, so the entry's `Models` line marks the DUAL UNVERIFIED rather than claiming the setting line-wide. | `H:troubleshoot-index` §"Why does my video play in a fast motion? (Time-Lapse)"; `M3` §TIME LAPSE RECORD (p.48; lines 1664–1681), §UNDERSTANDING CAMERA SETTINGS (p.45; lines 1551–1554); `M2` (p.48; lines 1496–1508); `M7` (p.57; lines 2240–2259), §"Time-Lapse + G-Sensor" parking (pp.61–62); `M1` §TIME-LAPSE VIDEO (p.41; lines 1381–1398); `M6` (line 31) |

### The five guards

A guard is not an entry: no ranked causes, no discriminating-step analysis. Each says what
the agent must and must not do or say, and each carries the reason it is a guard rather
than an entry. All five are **VERIFIED**.

| ID | Why a guard | What Tier 1 actually says | Source |
|---|---|---|---|
| `GAP-BOOT-PROMPT` | Nothing to diagnose — the prompt is documented behaviour | The camera prints three options — **"Connect as USB Flash Drive" / "Connect as PC/MAC Webcam" / "Operate Camera Normally"** — because it has three documented USB functions (*"1. Storage, 2. Charging, 3. Webcam"*). Documented cause: it happens *"if the dashcam is plugged into a USB port using the short data cable"*, which *"may connect to your car's music system or computer"*. **The remedy half of that sentence is truncated in the captured body**, so "moving to the 12 V socket stops it" is UNVERIFIED and unspeakable. | `M3` §"B. On PC/MAC" (p.40; lines 1382–1397), §spec "Type-C USB Function" (p.12; line 382); `M2` (p.40; lines 1289–1304); `M1` (p.36; lines 1244–1251); `H:know-your-dashcam-how-to` §"Why does it says Connect to USB…", §"Initial screen asking how to use the dash cam"; `H:troubleshoot-index` §"Dash cam not playing Automatically and giving three options"; `O2` §"How to move videos to a computer instead" |
| `GAP-HWK-NOT-DETECTED` | The only published remedy is a wiring check, and `01` §4 puts wiring out of scope | *"please ensure that the wires are connected properly and in the correct position. Double-check all wiring connections to ensure they are securely attached and properly positioned."* Consequence is `REC-04`: no kit detected, no 24-hour parking mode. Safety line to carry verbatim: *"Never connect the dash cam directly to your car's 12/24V battery by modifying wires… connect it to the car's fuse box (NOT to battery terminals directly)."* | `H:troubleshoot-index` §"Hardwire kit Not Detected"; `H:know-your-dashcam-how-to` §"Why do I need hardwire kit for 24-Hour (24-HR) parking mode?"; `M7` §24-HR AUTO PARKING MODE CAUTION (p.59; lines 2294–2302), icon *"24HR Auto Trigger Parking Mode ON - HWK Connected"* (p.33; line 1414) |
| `GAP-FROZEN-SCREEN` | Rove publishes a fixed four-step order that does not branch | Restart by unplugging → **RESET** once with a paper clip *if the model has one* → remove the card and retest → try a known-good Class 10 / U3 card. R3 exception stated twice: *"This step is not applicable to the ROVE R3 because the R3 does not have a reset button."* Card result reads both ways: *"the memory card may be faulty, too slow, corrupted, or worn out"* vs *"continue troubleshooting or contact ROVE Customer Care"*. **Formatting is not the documented card step** — removal and retest is. | `H:frozen-screen` (whole article); `M7` §Troubleshooting *"Camera Freezing/Lagging or Crashing"* (pp.85–86; lines 3295–3315); `M4` §7 row *"Dash cam freezes or crashes"* (p.13; lines 186–190, column-interleaved); `M6` (lines 8, 39) |
| `GAP-ON-OFF-CYCLING` | An isolation sequence in a fixed order, not a ranked differential; it also needs keeping apart from `PWR-01` and `PWR-03` | *"the most common cause is unstable or insufficient power"* — vehicle outlet, car charger, USB cable or loose connection. Order: reset → **110 V wall outlet indoors with a phone USB charger** → both supplied ROVE cables → card out, repeat. Result reading is published for each branch. `M7`'s row for the same symptom says *"Try updating the firmware again"*; the dedicated article does not, and `FW-01` is where wrong advice destroys the device — so firmware is **not** the first move. | `H:repeatedly-on-off` (whole article); `M7` §Troubleshooting *"Camera turns ON/OFF frequently automatically"* (p.86; lines 3328–3332) |
| `GAP-RANDOM-RESTART` | One documented class of cause plus a short isolation; shares an article family with `GAP-ON-OFF-CYCLING` | `05` above records this as *"Rove attributes it to non-ROVE car chargers"* — **confirmed, and the attribution is in the manuals rather than the article**. `M6`: *"If you're using a non-ROVE USB Car Charger, your car's direct USB might not provide enough power, which can cause reboots."* `M2`/`M3`/`M7` carry it as an installation CAUTION: *"Only use ROVE's USB Car Charger, otherwise the camera may frequently reboot or flicker LCD due to insufficient power."* The Help Center body itself is broader — *"insufficient or unstable power … caused by the USB car charger, the USB power cable, or, in rare cases, the dash cam itself"* — and adds the card: *"Using other micro SD cards can affect the dashcam's performance and force it to reboot randomly during recording."* **One figure must not be spoken:** the charger ceiling is printed as **3.4 AMP** in one R2-4K printing and **3.1 AMP** in another. | `H:random-restarting` (whole article); `M6` (lines 3, 40); `M3` §INSTALLATION CAUTION (p.17; lines 609–612), §Charging NOTE (p.19; lines 672–674), §"OUT OF THE BOX INSTRUCTIONS" (p.9; lines 264–266); `M2` (p.17, lines 555–556; p.19, line 612); `M7` (p.23; lines 931–933); `H:know-your-dashcam-how-to` §"Can I use my own cord with Type-C to Type C ports?" |

### Re-verification pass

Category H was written out of the corpus, and then **every quotation and every citation in
it was re-read against the file on disk** before the milestone was committed — a separate
pass, deliberately adversarial, on the assumption that a document written *from* sources
is exactly the kind that accumulates citations nobody re-checks. 70 quoted spans in `02`
Category H were matched against the 28 Tier 1 documents by exact text after whitespace and
smart-punctuation normalisation; the misses were then read by hand in context.

**The four entries, after re-verification:**

| ID | Status | Re-verification outcome |
|---|---|---|
| `GAP-REAR-CHANNEL` | **CORRECTED** (unchanged) | Every quote found verbatim in `M6`, `M7`, `M4`, `M5`. One citation tightened: `M7` §UNIT STRUCTURE now reads lines 613–689, so the range contains the heading on p.14 as the `pp.14–15` claim requires. Item 14's label is column-split in the extracted text and is now quoted that way. **The single-channel exclusion was tested, not assumed**: `M2` and `M3` contain the string "rear camera" zero times. |
| `GAP-GPS` | **CORRECTED** (unchanged) | The R3 four-step procedure, the three settings, the DUAL PRO master toggle and both fix-state readouts all confirmed. **One quote corrected**: the manuals read *"when you play your video on GPS Player"*, not *"on the GPS Player"* — the definite article came from the adjacent GPS-Location clause. Two quotes had a sentence-final period added that the source does not have. `M3` §GPS INFO is **p.66, not p.65**; `M7` §"Home Screen Status Icons" is **p.33 only**, not pp.33–34 (p.34 begins at the LED indicator table). The headline correction — that the mount-GPS *mechanism* is not Tier 1 — was re-tested and stands. |
| `GAP-MOUNTING` | **VERIFIED** (unchanged) | The 20° constraint, the dot-matrix AVOID THIS panel, the two-handed lock procedure, the electrostatic-film sequence and the defroster-line note all found verbatim. **One `Models` claim corrected**: the R3's mounts are *"a suction mount or magnetic sticky mount"*; **"3M slide" appears nowhere in the corpus** and was an invention. `M3` §INSTALLATION is **pp.16–17, not pp.15–17**. |
| `GAP-TIMELAPSE` | **VERIFIED** (unchanged) | Cause, fix, both restart-persistence notes and the parking-mode branch all confirmed. **One `Models` claim withdrawn**: the entry said all documented models have `TIME LAPSE RECORD`; `M4` (R2-4K DUAL) **does not mention time-lapse at all**, so the DUAL is now UNVERIFIED on this entry. **One quote corrected**: all four manuals read *"Short press Me Key"*, not *"MENU Key"* — the PDF prints a button glyph the extraction drops, and the corpus text is kept rather than repaired by inference. `M1` §TIME-LAPSE VIDEO is **p.41, not p.38**. |

**The five guards, after re-verification:** all five remain **VERIFIED**. `GAP-BOOT-PROMPT`,
`GAP-HWK-NOT-DETECTED` and `GAP-FROZEN-SCREEN` needed only line-range and page tightening
(the `M3`/`M2` PC-MAC ranges stopped one line short of *"Operate Camera Normally"*, the
third of the three options the guard tells the agent to name). `GAP-RANDOM-RESTART` needed
three page numbers fixed in `M3` (§Charging NOTE p.19 not p.18; §"OUT OF THE BOX
INSTRUCTIONS" p.9 not p.6) and both AMP figures re-read and confirmed (3.4 in `M3` p.9,
3.1 in `M2` p.9 and p.19, and in `M1` p.19). **`GAP-ON-OFF-CYCLING` carried one substantive
error**: it said Rove reaches *"or in rare cases the dash cam itself"* only after all four
isolation steps. Rove states it in the article's **opening paragraph**, last in a ranked
list of causes. The guard's instruction to the agent is unchanged — reach the camera last —
but the reason given for it was wrong and is now stated correctly.

**Nothing in Categories A–G was re-opened by this pass**, and no status in the table below
moved. What moved was nine page numbers, four line ranges, four quotations, two `Models`
lines and one claim about where a sentence sits in an article.

### Headline counts after 5.2

| Outcome | Categories A–G | Category H | Total |
|---|---:|---:|---:|
| **VERIFIED** | 10 | 2 entries + 5 guards | **17** |
| **CORRECTED** | 14 | 2 | **16** |
| **REJECTED** | 1 | 0 | **1** |
| **UNVERIFIED** | 3 | 0 | **3** |
| **Total** | 28 | 4 entries + 5 guards | **32 entries + 5 guards** |

### What 5.2 could not source

Named rather than dropped, and **not speakable**:

1. **Why the R3 mount gap kills GPS.** The step is Rove's own; the mechanism is a
   storefront product title. See the `GAP-GPS` row.
2. **Whether moving off the car's USB data port stops the boot prompt recurring.** The
   Help Center sentence ends mid-word in the captured body (*"In this ca…"*).
3. **Whether the R2-4K DUAL has a time-lapse setting at all.** `M4` never mentions
   time-lapse. `GAP-TIMELAPSE` therefore cannot be applied to the DUAL without asking
   first, and the restart-persistence behaviour must not be inherited to it.
4. **How heat affects mount adhesive.** `H:overheating` documents what heat does to the
   camera, nothing about the mount.
5. **The third reason for no rear live feed.** `M6` says *"There could be three reasons"*
   and then lists two. The same article does it again for recording start/stop. The third
   reason, in both cases, is not in the corpus.
6. **The R2-4K PRO, still.** No third fetch was attempted; `04` records two failures and
   nothing changed. **The PRO is still the one model in the supported line with no manual
   on disk**, and no Category H entry inherits a fact to it. Where an entry's `Models` line
   omits the PRO, that is the state of the evidence, not an oversight.

### A document-level inconsistency to reconcile

`06` §4.7 carries *"R3 GPS: the GPS is in the magnetic mount, so a gap between mount and
camera kills it"* in the list of single Tier-1 facts the `KNOWN-GAP` outcome may surface to
close a session. The first clause is not Tier-1 prose (see the `GAP-GPS` row); the second
is. `06` was not edited in this milestone — the finding is recorded here, and reconciling
§4.7 is a one-line change for whoever next owns that document.

---

## What is still unknown after Step 1b

1. **Four entries have no Tier 1 coverage at all** — `FW-03`, `APP-02`, `APP-04`, `PWR-02`.
   They stay `TO VERIFY`.
   **(4.3) Now three — `FW-03`, `APP-02`, `APP-04`.** `PWR-02` is covered by `H:overheating`
   and `M7` and is CORRECTED. The other three were searched again against `M7` and the six
   new Help Center bodies and are still unhit.
2. **No known-issue or release-note feed is public.** `01` §8 Q5 is unanswered and `FW-03`
   stays undiagnosable. This is the single biggest remaining gap and it is not solvable by
   more reading — it needs an internal feed.
3. **The R2-4K PRO manual was never downloaded.** Its listing is on `O1`
   (`ROVE_R2-4K-PRO_User_Manual_Updated_JAN-2025.pdf`); everything stated about the PRO above
   comes from product listings, not from its manual.
   **(4.3) Still true, and it survived a second attempt.** Track C fetched the *DUAL* PRO
   manual (`M7`) successfully from the same Shopify CDN, but the **R2-4K PRO** manual did
   not: the CDN link off `O1` returns a Shopify 404 and the manuals.plus mirror is still
   bot-blocked. **The PRO is therefore the one model in the line with no manual on disk, and
   nothing may be stated about it from a product listing** — not its band, not its SSID, not
   its temperature limits. Where the corpus is silent on the PRO specifically, the agent
   treats it as unknown rather than inheriting a DUAL PRO or R2-4K fact. See `docs/04`
   §"Download status".
   **(5.2) Still true after a third milestone.** No fetch was re-attempted here — nothing
   has changed on either host and web access was not used in this milestone. The practical
   effect now reaches Category H: every one of the four new entries leaves the PRO out of
   its `Models` line and says so, rather than inheriting from the R2-4K or the DUAL PRO.
4. **Four Help Center articles are indexed but their bodies were not captured** — overheating,
   licence-plate legibility, blurry video and random restarting. `PWR-02` and part of `VID-01`
   depend on them.
   **(4.3) Closed.** All four bodies are on disk, along with two more
   (`H:repeatedly-on-off`, `H:frozen-screen`). `PWR-02` moved to CORRECTED on the strength
   of `H:overheating`; `VID-01` was already VERIFIED and `H:licence-plate` and
   `H:blurry-video` confirm it rather than change it — see the deltas section.
5. **No firmware version numbers for any current model.** `O1` renders them client-side.
6. **Still no call-mix data.** Every re-ranking in this document is a correction against
   documentation, not against what callers actually ring about (`01` §8 Q10).
7. **Model identification is now harder, not easier.** Eight dash cam models across two
   hardware revisions of the R2-4K, differing on band, card ceiling, screen type, reset
   availability and computer connectivity. "Which Rove do you have?" is no longer one
   question, and the `R2`/`R3` ASR confusion flagged in `01` §2 now has real consequences —
   the earlier instruction not to branch on R2-versus-R3 must be withdrawn.
   **(5.2) Category H makes this worse, not better.** `GAP-REAR-CHANNEL` does not apply to
   the single-channel R2-4K at all; `GAP-GPS`'s master GPS toggle exists on the DUAL PRO
   and is not documented on the R2-4K; `GAP-TIMELAPSE`'s persistence behaviour is
   *inverted* between the mini-USB and USB-C revisions of the same model name; and the
   reset button that `GAP-FROZEN-SCREEN`, `GAP-ON-OFF-CYCLING` and `GAP-RANDOM-RESTART` all
   depend on does not exist on the R3. Model identification is a prerequisite for four of
   the nine new items, not a nicety.
8. **(5.2) Five facts Category H wanted and could not source** (the sixth, the PRO manual,
   is item 3 above). The R3 mount-GPS mechanism; the boot prompt's recurrence remedy
   (sentence truncated in the captured body); whether the R2-4K DUAL has a time-lapse
   setting at all (`M4` never mentions one); heat vs mount adhesive; and the *third*
   reason `M6` twice promises and twice lists only two of.
   All are marked UNVERIFIED in `02` Category H and are not speakable. See
   ["What 5.2 could not source"](#what-52-could-not-source).
