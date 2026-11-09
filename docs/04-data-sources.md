# 04 — Data Sources for the Voice Troubleshooting Agent

Date: 2026-11-07
Researched by: Muse, via web (web browsing works for Muse; it was denied to Claude Code headless)
Status: **Initial inventory.** Tier 1 sources verified as reachable — `rovedashcam.com`
returns HTTP 200 from EC2. Tier 2 and Tier 3 were **sampled, not exhaustively collected**.
Scope: Voice-only, Rove models R2-4K, R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO, R3

Companion to `02-issue-taxonomy.md`. This document is the Step 1b source list — it says
where ground truth lives. It does **not** promote any taxonomy entry to `Official doc` on
its own; that happens only when a chunk is actually retrieved, dated, and attached.

---

## How to use this file

- **Tier 1 = Ground truth.** Only Tier 1 may be spoken as a verified fix.
- **Tier 2 = Discovery.** Use for symptom language, frequency, and eval scenarios — never
  as a fix on its own.
- **Tier 3 = Supplementary.** Use for cross-checks, never as sole evidence.

---

## Tier 1 — Ground truth (Official Rove)

### 1.1 rovedashcam.com — Firmware Update & Downloads

- **URL:** https://www.rovedashcam.com/pages/firmware-update-downloads
- **What it gives:** OTA update steps via ROVE App (Connect app > App Menu > Firmware
  Update > check > UPDATE), manual update via SD card (format card in camera, copy unzipped
  firmware files, keep camera plugged in and OFF, insert card, press power once, red/blue
  LED flashing, auto-reboot, then FORMAT card again so it does not re-update on every
  restart), SD card guidance.
- **Key facts verified:** ROVE recommends ROVE PRO / Ultimate / Industrial microSD cards;
  basic requirement Class 10 or U3; other cards can cause random reboots during recording.
- **Use in app:** RAG chunks for FW-01…FW-04, SD-01…SD-04. Metadata: model, update method
  (OTA vs manual).
- **Access:** Public HTML, curl returns HTTP 200 (verified from EC2). Scrapeable.

### 1.2 rovedashcam.com — Connect a ROVE Dash Cam to Your Phone (blog/guide, 2026-10-27)

- **URL:** https://www.rovedashcam.com/blogs/rove-dash_cam/connect-rove-dash-cam-to-phone-app
  — `TO CHECK`: the path segment mixes an underscore (`rove-dash_cam`) with hyphens
  elsewhere. Verify the exact slug before crawling; do not "correct" it by guessing.
- **What it gives:** Model-by-model Wi-Fi table.
  - **R2-4K:** press & hold Emergency Lock 2 sec, or System Settings > WiFi; SSID
    `ROVE_R2-4K_`; WiFi 6, 2.4GHz
  - **R2-4K DUAL:** same button; SSID `ROVE_R2-4K-DUAL_`; dual-band 5GHz & 2.4GHz; up to
    20MB/s
  - **R2-4K DUAL PRO:** same button; SSID `ROVE_R2-4K-DUAL_PRO`; WiFi 6, dual-band; up to
    30MB/s over 5GHz
  - **R3:** tap screen > Settings > System Settings > WiFi icon; SSID `ROVE_R3_` /
    `Rove_R3_`; dual-band; up to 30MB/s
  - Default password `12345678`, also shown on camera screen. Range ~10m / 33ft. "No
    Internet" is normal — iPhone tap Keep Trying Wi-Fi, Android wait 10-15 sec then tap
    Always connect. If phone does not show 5GHz, switch camera WiFi Mode to 2.4GHz in
    System Settings.
  - App cannot watch remotely; camera Wi-Fi gives no internet.
- **Use in app:** RAG chunks for WIFI-01…WIFI-05, APP-01…APP-04. This is the single best
  source for model-specific Wi-Fi steps.
- **Access:** Public HTML.

### 1.3 Rove Help Center (Gorgias) — Troubleshoot index

- **URL:** https://hc1.gorgias.help/en-US/articles/troubleshoot-128437 — `TO CHECK`: the
  index path carries an `/articles/` segment that the individual article URLs below do not.
  One of the two patterns is likely wrong; confirm by fetching rather than normalising.
- **What it gives:** 20+ step-by-step troubleshooting articles, each is a ready-made
  diagnostic procedure. Examples found:
  - **WiFi NOT Connecting** — https://hc1.gorgias.help/en-US/wifi-not-connecting-477922 —
    turn on, card inserted, 10m range, reset to default settings, forget network, reinstall
    app and allow all permissions, turn OFF VPN / cellular data / Wi-Fi calling, turn Wi-Fi
    ON (R2-4K/PRO: hold emergency lock 2 sec; R3: tap blue WiFi icon), join
    `ROVE_R***_******` with `12345678`, Android "No Internet" tap stay connected.
  - **ROVE dash cam repeatedly saying "WiFi Is Connected - WiFi Is Disconnected"** —
    https://hc1.gorgias.help/en-US/rove-dash-cam-repeatedly-saying-%E2%80%9Cwifi-is-connected--wifi-is-disconnected%E2%80%9D-472820
    (`TO CHECK`: percent-encoded smart quotes and a double hyphen in the slug — verify it
    resolves before relying on it) — voice guidance, phone drops to cellular because camera
    gives no internet, turn Wi-Fi OFF when not needed, or turn off WiFi voice guidance in
    System Settings after firmware update, or turn off Auto Join.
  - **ROVE WIFI name not showing on my phone** (`TO CHECK`: no URL captured in the draft —
    locate from the Troubleshoot index) — turn OFF VPN, cellular data, Wi-Fi calling, reset
    to default, forget network, reinstall app, restart phone.
  - **My Camera does NOT Turn ON** — swap cable, remove memory card, press power, hard reset
    with paper clip at bottom near serial number, test indoors with phone USB charger +
    short cable.
  - **I have missing videos** — power loss, card issue, date/time wrong, overnight test with
    wall charger.
  - **Why my video recording has no Audio/Sound** — Record Audio ON, microphone not muted
    (UP button can mute), Speaker Volume Med/High not OFF.
  - **Receiving "Memory Card Too Slow" Error** — format or replace with Class 10 U3
    high-speed card.
  - **My Camera does NOT Turn OFF (Always stays ON)** — vehicle 12V socket stays live, 5
    fixes from 2-sec power press to hardwire kit.
  - **R3:** NO GPS Live Speed, Hardwire kit Not Detected, overheating, screen frozen,
    blurry, randomly restarting, Card Full, etc.
- **Use in app:** This is the PRIMARY RAG corpus. Each article = 1-3 chunks, tagged by
  model, category, symptom. Also the best source to verify taxonomy entries
  WIFI/APP/REC/SD/PWR/VID.
- **Access:** Public HTML, crawlable. Support contact in articles: help@rovedashcam.com,
  text 1-844-ROVE-CAM / 1-844-768-3226, 7 days/week 9am-5pm PST.

### 1.4 User Manuals (PDF)

- R2-4K, R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO, R3 manuals via manuals.plus /
  manualslib.com, and Rove Downloads page.
- **Examples:** R2-4K manual — 4K 2880x2160 @24fps, Sony IMX335, Novatek NT-96660, 150°
  wide, built-in GPS, loop recording, up to 512GB Class 10 U3 required; System Settings >
  Firmware Version to check version; WiFi SSID `ROVE R2-4K-*********` password `12345678`.
- R3 manual — 1440P + 1080P + 1080P, 3" IPS touch, up to 512GB Class 10 U3, GPS Player
  software for PC/Mac.
- R2-4K Dual PRO manual — Dual Band WiFi 6 (5GHz & 2.4GHz), troubleshooting table for power
  / recording stops / blurry / WiFi slow / parking mode.
- **Use in app:** Specs, menu paths, troubleshooting tables. Extract PDFs to text, chunk by
  section, tag by model.
- **Access:** Public PDFs. Need PDF text extraction. Some manuals.plus pages are mirrors —
  prefer Rove Downloads page as canonical, use manuals.plus as fallback.

### 1.5 Rove Downloads — GPS Player, apps, manuals

- **URL:** https://www.rovedashcam.com/pages/firmware-update-downloads (same as 1.1, also
  hosts GPS Player for PC/Mac, mobile apps, manuals)
- **Use in app:** Version / compatibility matrix. GPS Player supports multi-view (2-3 videos
  at once).

---

## Tier 2 — Discovery / frequency (Reviews — symptom language, NOT fixes)

### 2.1 Amazon product pages & reviews

- **R2-4K:** 4.2 out of 5 stars, 36,624 reviews (via Desertcart mirror of Amazon). Mixed
  Wi-Fi feedback — some quick connection, others camera not connecting to phones.
- **R2-4K DUAL:** 5G WiFi up to 20MB/s, STARVIS 2 sensor, free 128GB card included.
- **Recurring review themes found:** Wi-Fi disconnects on Android 14, fixed after firmware
  upgrade; "memory card speed is low" error, recording stops; app won't connect if phone is
  on mobile data; Wi-Fi only 2.4GHz not 5GHz on older model despite packaging; transfer slow
  (~1 min for 1-min 1080p clip); camera not recording after 2 years; 12ft cable defective;
  support responded quickly by email.
- **Use in app:** Frequency ranking, customer wording for eval set, symptom taxonomy. NEVER
  use a reviewer's suggested fix as verified.
- **Access / caution:** Amazon blocks direct scraping. Do NOT scrape amazon.com directly.
  Use: Amazon Product Advertising API (if available), review export tools, or aggregator
  mirrors (Desertcart) for sampling, with manual review. For the assessment, a sampled set
  of 50-100 1-2 star reviews per model is enough.

### 2.2 App Store / Google Play reviews — ROVE Dash Cam app

- App supports R2-4K, R2-4K PRO, R2-4K-DUAL, R3. Latest version 6.2.0, last update
  2026-10-30 (AppBrain).
- **Recurring themes:** app crashing, downloads stopping / taking 20 min, app loads partially
  then stops after a minute, "no files", cannot access settings, latest update requires
  serial number repeatedly, cannot connect, app says video downloaded but it did not, must
  turn off cellular and Bluetooth to access videos, update breaks connection again, memory
  card lasts ~2 months, Wi-Fi weak, keeps logging out.
- **Use in app:** App-specific issues APP-01…APP-04, firmware-update regression signal, eval
  scenarios.
- **Access:** Google Play / App Store review APIs, or AppBrain
  (https://www.appbrain.com/app/rove-dash-cam/com.rovedashcam.android) and JustUseApp
  (https://justuseapp.com/en/app/1606959035/rove-dash-cam/reviews) as proxies. JustUseApp
  itself is low-trust for legitimacy claims — use it only for review text.

### 2.3 Rove Community / Facebook / Reddit

- Reviews mention Facebook and Reddit as places where sign-in / verification-email issues
  are discussed as known issues.
- Direct Reddit search returned no strong standalone threads in this pass — treat as a gap,
  not as absence. Need a dedicated search on reddit.com/r/dashcam, r/Rove, Facebook Rove
  Dash Cam Community.
- **Use in app:** Supplementary symptom confirmation, real phrasing.
- **Access:** Reddit API / search, Facebook group is closed — likely not crawlable, use only
  public posts.

---

## Tier 3 — Supplementary

### 3.1 Comparison / review sites

- **FeatureLens** — Best ROVE Dash Cam: R2-4K Dual, Dual Pro, R3 — comparison table, Wi-Fi 6
  ~30MB/s, STARVIS 2 IMX678+IMX675, up to 512GB / 1TB, OTA updates, US support, 1-year
  warranty. URL: https://featurelens.com/best-rove-dash-cams/
- **Use:** Model comparison matrix, cross-check specs. Low authority for fixes.

### 3.2 YouTube / Rove Videos page

- Rove videos: https://www.rovedashcam.com/pages/videos
- Specific firmware video cited in Help Center: https://youtu.be/r0IFU9E9fIw
- **Use:** Transcripts for step-by-step procedures, especially firmware update and Wi-Fi
  setup. Transcripts are secondary to the written Help Center article for the same procedure.

### 3.3 App info aggregators

- AppBrain, APK sites (apk52, a2zapk) — app version history, supported models list (R2-4K,
  R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO, R3), changelog notes (v6.0 easier settings/updates).
- **Use:** Version compatibility matrix only.

---

## What NOT to use as a source

- Generic AI-generated "Rove troubleshooting" blog posts with no model specificity — they
  repeat generic Wi-Fi advice and will cause category collapse.
- JustUseApp legitimacy/scam verdicts — not evidence.
- Any fix that only appears in a single 1-star review.

---

## Collection plan for the app (recommended order)

1. Crawl Help Center Troubleshoot index (20+ articles) + Firmware Downloads +
   Connect-to-Phone blog — save HTML, extract text, chunk by procedure step, tag
   model/category. This alone covers most of Tier 1.
2. Download manuals for R2-4K, R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO, R3 — PDF to text,
   chunk by section, tag model.
3. Sample Amazon + App Store reviews: 50-100 low-rated reviews per model/app, label symptom
   + model + phone OS + attempted steps. Use for taxonomy frequency and eval wording only.
4. Build compatibility matrix from 1.1 + 1.2 + 1.4: model | Wi-Fi band | SSID pattern |
   password | OTA? | manual update? | max SD | app version.
5. Keep a source registry: every RAG chunk must carry source URL + retrieval date + Tier. No
   chunk without a source may be spoken as a fix.

---

## Gaps / risks

- **Firmware version numbers by model:** not yet collected — need the firmware_update_page /
  Downloads page per-model files.
- **The R2-4K PRO manual is still missing** after two attempts (Rove CDN link 404s,
  manuals.plus bot-blocked). Every PRO-specific fact in this document is Tier 2/Tier 3
  listing material and must not be spoken as verified or inherited from a neighbouring
  model. See "Download status — still missing: the R2-4K PRO manual" below.
- **Known-issue / regression feed:** no public feed found. App reviews show update
  regressions, but no official list.
- **Reddit / Facebook:** not yet systematically searched.
- **Amazon:** direct scraping blocked — need API / sampled export.
- **Copyright / ToS:** Rove content is for support use in this assessment; do not republish
  manuals verbatim in the app UI, use short grounded excerpts with source attribution.
- **URLs marked `TO CHECK` above** (1.2 blog slug, 1.3 index path, the "WiFi Is Connected -
  WiFi Is Disconnected" article slug, and the missing URL for "ROVE WIFI name not showing on
  my phone") were not re-fetched individually in this pass. Confirm each by fetching; none
  was corrected by guessing.

---

## How this changes Step 1

`02-issue-taxonomy.md` is not rewritten here. What follows is only the mapping — which
taxonomy entries now have a named Tier 1 source to verify against in Step 1b. Until a chunk
is actually retrieved and dated, every entry below still reads `TO VERIFY` and `0` entries
are marked `Official doc`.

- **WIFI-02, WIFI-03** (network does not appear / password rejected) now have a Tier 1
  answer path: the model-by-model SSID and default-password table in the Connect blog (1.2)
  plus the Help Center "WiFi NOT Connecting" and "ROVE WIFI name not showing on my phone"
  articles (1.3). The `Unknown` placeholders for SSID pattern and default password are
  exactly what these two sources fill.
- **WIFI-01, WIFI-04** (drops back to cellular / drops every few minutes) map to one Help
  Center article each — "WiFi Is Connected - WiFi Is Disconnected" (1.3) — which also names
  a cause the taxonomy only inferred: the camera's Wi-Fi carries no internet, so the phone
  leaves it. Auto-Join and WiFi voice guidance are the named settings.
- **WIFI-05** (playback/download unusably slow) now has per-model band and throughput
  figures from the Connect blog (1.2) — 2.4GHz-only on R2-4K, up to 20MB/s on DUAL, up to
  30MB/s over 5GHz on DUAL PRO and R3 — which turns a vague "slow" complaint into a
  model-dependent expectation check.
- **FW-01 … FW-04** (stalls, will not boot, regression after update, caller cannot do it at
  all) map to the Firmware Update & Downloads page (1.1): the OTA path through the ROVE app
  and the full manual SD-card procedure, including the format-after-update step that
  prevents a re-update loop on every restart. FW-04's "does the caller need a computer
  mid-call" question is answerable from this page.
- **SD-01 … SD-04** (card error, memory full, corrupt files, repeated reformatting) map to
  the card guidance on 1.1 (Class 10 / U3 minimum, recommended ROVE PRO / Ultimate /
  Industrial cards, wrong cards causing random reboots), the 512GB capacity ceiling in the
  manuals (1.4), and the Help Center "Memory Card Too Slow" article (1.3).
- **PWR-01 and PWR-03** (will not power on / does not start or stop with the ignition) map
  to the Help Center "My Camera does NOT Turn ON" and "My Camera does NOT Turn OFF (Always
  stays ON)" articles (1.3), which supply the hard-reset location and the live-12V-socket
  cause. **REC-01, REC-02, REC-04** map to "I have missing videos". **VID-03** (no audio,
  wrong timestamp) maps to "Why my video recording has no Audio/Sound", including the UP-button
  mute that the taxonomy did not have.
- **APP-01 … APP-04** get a split source: the app-side steps in 1.2 and 1.3 are Tier 1 and
  verifiable; the crash, download-stall, and repeated-serial-number complaints are Tier 2
  only (2.2) and may inform eval scenarios and frequency, never a spoken fix.
- **Section-level, not entry-level:** `02` §1 (likely model line), §3 (SD card
  requirements), and §4 (firmware update method) each now have a Tier 1 source to be checked
  against — 1.2 and 1.4 for the model list, 1.1 and 1.4 for cards, 1.1 for update method.
  Two gaps survive this inventory and stay open: **per-model firmware version numbers** are
  still uncollected, and **no known-issue / regression feed exists publicly**, which leaves
  `01` §8 Q5 unanswered and FW-03 without a way to recognise a bad build.

## Known-issue watch (2026-11-08)

There is still no public known-issue / regression feed from Rove, and this
watch does not invent one. What `ingest/known_issues.py` does instead is watch
the three vendor-side surfaces that do exist publicly and change when something
changes at Rove:

1. **help_center_index** — the Gorgias Troubleshoot index. A new article is the
   closest public thing to Rove acknowledging a problem; an edited article is
   the closest thing to Rove revising its advice.
2. **firmware_downloads** — the official firmware/downloads and update pages,
   watched for new or re-versioned download links and changes to the update
   procedure text.
3. **app_changelog** — the ROVE Dash Cam app release notes (Android
   `com.rovedashcam.android`, iOS `id1606959035`). The only surface where the
   vendor writes "fixed" next to a dated version.

Every record the watch emits is a **candidate**, **Tier 2**, `speakable=False`
— enforced in code, not just documented. Its outputs live in
`data/known-issues/` (`snapshot.json`, `candidates.json`), never in
`data/processed/`, and no path it writes is registered in
`ingest.metadata.SOURCES`, so nothing it finds can enter the speakable corpus.
Promotion to Tier 1 is a separate human act (`confirm_with_tier1()`), which the
module never calls and the CLI gives no way to reach. Tests run offline against
the saved fixtures in `data/raw/` (`ingest/test_known_issues.py`, 34 tests).

Limits, stated plainly: a new Help Center article is Rove publishing a
troubleshooting page, not Rove declaring a known defect, and app release notes
are marketing copy about a phone app, not a camera firmware bulletin. The watch
can notice that something changed; it cannot recognise a bad build. **FW-03
stays escalation-bound** until a real vendor feed exists.

## Download status 2026-11-07

16 of 21 files downloaded OK (4.6 MB total). The full per-file inventory — size, source URL,
tier and status — is in `data/README.md`.

- `manuals.plus` and `manualslib` are blocked by a bot challenge returning HTTP 403, so all
  five manual URLs pointing at those two hosts failed.
- Only the R3 manual PDF succeeded, fetched from the Rove site's own CDN rather than from an
  aggregator.
- **Next step:** get the R2-4K / Dual / Dual Pro manuals from the Rove Downloads page (1.5)
  or by downloading them manually.

### Manuals added manually — 2026-11-07

The manual gap above is closed. **Hardik downloaded 5 manual PDFs by hand on 2026-11-07**
and they are on disk in `data/raw/manuals/`: `dc3831.pdf`, `User Manual For New R2-4K.pdf`,
`ROVE R2-4K User Manual.pdf`, `ROVE R2-4K Dual Dash Cam Instruction Manual.pdf`, and
`B0F9SX3JB9.pdf`. With the R3 PDF already fetched from the Rove CDN, Tier 1 now holds **6
manuals, 260 pages**, extracted to text in `data/text/manuals/`.

These 5 were not fetched by the crawler, so **no source URL is recorded for them** in
`data/raw/DOWNLOAD_LOG.txt` — a provenance gap that item 5 of the collection plan above
(every chunk carries source URL + retrieval date + Tier) still needs closed before any of
this content is spoken as a fix.

The content was read and verified against the taxonomy in
[`05-step1b-verification.md`](05-step1b-verification.md), which assigns each manual a model
and a revision and uses them as source codes `M1`…`M6`. Per-file sizes and page counts are
in `data/README.md`.

### Track C additions — Milestone 4.3, 2026-11-07

Seven more Tier 1 documents are on disk. Tier 1 now holds **28 documents: 7 manuals
(351 pages), 3 official pages, 18 Help Center articles.**

**1. Rove's own R2-4K DUAL PRO manual (`M7`) — 91 pages, fetched, with a source URL.**

- **File:** `data/raw/manuals/ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf`, extracted to
  `data/text/manuals/ROVE-R2-4K-DUAL-PRO.txt`
- **URL:** `https://cdn.shopify.com/s/files/1/2287/2433/files/ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf`
- **Why it matters:** it is Rove's own printing, fetched from the Rove CDN, so unlike
  `M1`–`M5` it is `provenance=crawler` and carries a real source URL — it does not sit in
  the provenance hole above. It supersedes nothing: `M5` (`B0F9SX3JB9.pdf`, 12 pp) stays in
  the registry, but `M7` is the primary DUAL PRO source because it carries the
  troubleshooting table, the temperature guideline and the thermal-shutdown note that `M5`
  has nothing of.
- **Caveat on the log:** this fetch post-dates `data/raw/DOWNLOAD_LOG.txt`, which was not
  re-run. The URL above is the record.

**2. Six Help Center article bodies** — previously index entries with no text behind them.
`overheating`, `licence-plate`, `blurry-video`, `random-restarting`, `repeatedly-on-off`,
`frozen-screen`. Per-file URLs are in `data/README.md`; they are the canonical URLs embedded
in the saved pages, again because they post-date `DOWNLOAD_LOG.txt`. Four of these are the
four bodies that `05` §"What is still unknown" item 4 recorded as missing; that item is now
closed. `PWR-02` moved UNVERIFIED → CORRECTED on the strength of `overheating`.

### Download status — still missing: the R2-4K PRO manual

**The R2-4K PRO manual is still not on disk, and a second attempt in Milestone 4.3 failed
too.** It is the one model in the supported line with no manual in the corpus.

| Attempted source | Outcome |
| --- | --- |
| Rove CDN link off the Downloads page (1.5), `ROVE_R2-4K-PRO_User_Manual_Updated_JAN-2025.pdf` | **Shopify 404** — the link is published on `O1` but the file is not served |
| `manuals.plus` mirror | **Bot-blocked**, as in the original pass (HTTP 403 challenge) |

The DUAL PRO manual came off the same Shopify CDN without trouble, so this is a missing
file on Rove's side rather than a blocked host.

**The constraint this puts on the agent — it is not a formality.** Everything this document
or `02` says about the **R2-4K PRO** specifically — its Wi-Fi band, its SSID pattern, its
temperature limits, its card ceiling — comes from **product listings, comparison sites and
the app's supported-models list, which are Tier 2 and Tier 3**. None of it is Tier 1 and
**none of it may be spoken as a verified fact, or quietly inherited from the R2-4K or the
DUAL PRO.** Where the corpus is silent on the PRO, the honest answer is that it is not
known. Treat "PRO facts from listings" the same way `What NOT to use as a source` above
treats a fix that appears only in a single review.
