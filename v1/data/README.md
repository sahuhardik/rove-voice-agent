# data/ — Downloaded source corpus

Snapshot taken **2026-11-07**. Every row below is a file that exists on disk under
`data/raw/` or `data/text/`. For automatically fetched files the source URL is taken
verbatim from `data/raw/DOWNLOAD_LOG.txt`.

- **16 of 21** attempted automated downloads succeeded; **5 failed** (all HTTP 403 bot
  challenges).
- Separately, **5 manual PDFs were added by hand by Hardik on 2026-11-07**. They are not
  in `DOWNLOAD_LOG.txt`, so no source URL is recorded for them.
- **Milestone 4.3 (Track C) added 7 more Tier 1 documents** on 2026-11-07: Rove's own
  91-page **R2-4K DUAL PRO** manual (`M7`, fetched from the Rove Shopify CDN, so it *does*
  carry a source URL) and the bodies of **6 Help Center articles**. These post-date
  `DOWNLOAD_LOG.txt`, which was not re-run — their URLs are recorded in the tables below and
  in `docs/04-data-sources.md`.
- All **7** manual PDFs have been extracted to plain text under `data/text/manuals/` —
  **351 pages** across 7 files.
- Total on disk: **59,260,245 bytes ≈ 56.5 MB** across **36** corpus files (28 raw
  downloads/uploads + the log + 7 extracted text files; this README excluded).
- Tier numbering follows `docs/04-data-sources.md`. Manual content is verified in
  `docs/05-step1b-verification.md`.
- **The R2-4K PRO manual is still missing** — see "Failed downloads" below. It is the one
  model in the line with no manual on disk.

## Verification performed

| Check | Applies to | Result |
| --- | --- | --- |
| File size > 10 KB | all 21 HTML files | PASS — smallest is 148.3 KB |
| Contains the text `Rove` (case-insensitive) | all 21 HTML files | PASS |
| First bytes are `%PDF` | all 7 PDFs | PASS |
| Text extraction produced non-empty output | all 7 PDFs | PASS — 7 files, 351 pages |
| Content checked against the taxonomy claims | all 7 manuals | See `docs/05-step1b-verification.md` |
| Chunked, validated, 0 errors | whole corpus | PASS — `python -m ingest.validate`, 24/24 entries covered |

## Tier 1 — Official Rove site (`data/raw/official/`)

| File | Size (KB) | Source URL | Tier | Status |
| --- | ---: | --- | --- | --- |
| `official/firmware-update-downloads.html` | 546.8 | https://www.rovedashcam.com/pages/firmware-update-downloads | Tier 1 | OK |
| `official/connect-rove-to-phone.html` | 562.5 | https://www.rovedashcam.com/blogs/rove-dash_cam/connect-rove-dash-cam-to-phone-app | Tier 1 | OK |
| `official/update-firmware-r2-4k.html` | 519.0 | https://www.rovedashcam.com/pages/update-firmware-rove-r2-4k-dash-cam | Tier 1 | OK |

## Tier 1 — Rove Help Center, Gorgias (`data/raw/help-center/`)

| File | Size (KB) | Source URL | Tier | Status |
| --- | ---: | --- | --- | --- |
| `help-center/troubleshoot-index.html` | 511.5 | https://hc1.gorgias.help/en-US/articles/troubleshoot-128437 | Tier 1 | OK |
| `help-center/wifi-not-connecting.html` | 170.8 | https://hc1.gorgias.help/en-US/wifi-not-connecting-477922 | Tier 1 | OK |
| `help-center/wifi-connected-disconnected.html` | 159.0 | https://hc1.gorgias.help/en-US/rove-dash-cam-repeatedly-saying-%E2%80%9Cwifi-is-connected--wifi-is-disconnected%E2%80%9D-472820 | Tier 1 | OK |
| `help-center/missing-videos.html` | 188.2 | https://hc1.gorgias.help/en-US/i-have-missing-videos-on-my-rove-dash-cam-472877 | Tier 1 | OK |
| `help-center/camera-does-not-turn-on.html` | 174.8 | https://hc1.gorgias.help/en-US/my-camera-does-not-turn-on-472872 | Tier 1 | OK |
| `help-center/r3-no-gps-live-speed.html` | 148.3 | https://hc1.gorgias.help/en-US/r3--no-gps-live-speed-477968 | Tier 1 | OK |
| `help-center/no-audio-sound.html` | 178.3 | https://hc1.gorgias.help/en-US/why-my-video-recording-has-no-audiosound-476108 | Tier 1 | OK |
| `help-center/memory-card-too-slow.html` | 161.0 | https://hc1.gorgias.help/en-US/receiving-%E2%80%9Cmemory-card-too-slow%E2%80%9D-error-503340 | Tier 1 | OK |
| `help-center/camera-does-not-turn-off.html` | 205.8 | https://hc1.gorgias.help/en-US/my-camera-does-not-turn-off-(always-stays-on)-477921 | Tier 1 | OK |
| `help-center/wifi-name-not-showing.html` | 151.8 | https://hc1.gorgias.help/en-US/rove-wifi-name-not-showing-on-my-phone-2106568 | Tier 1 | OK |
| `help-center/sign-in-error-rove-app.html` | 159.5 | https://hc1.gorgias.help/en-US/i-am-getting-an-error-when-i-sign-in-to-my-rove-app-2041277 | Tier 1 | OK |
| `help-center/know-your-dashcam-how-to.html` | 639.8 | https://hc1.gorgias.help/en-US/articles/know-your-dashcam-%7C-how-to-128439 | Tier 1 | OK |

Added by Milestone 4.3 (Track C) on 2026-11-07, after `DOWNLOAD_LOG.txt` was written. The
URLs below are the canonical ones embedded in the saved pages themselves.

| File | Size (KB) | Source URL | Tier | Status |
| --- | ---: | --- | --- | --- |
| `help-center/overheating.html` | 163.8 | https://hc1.gorgias.help/en-US/why-is-my-dashcam-overheating-%E2%80%94-what-causes-it-and-how-can-i-prevent-it-2143477 | Tier 1 | OK |
| `help-center/licence-plate.html` | 178.2 | https://hc1.gorgias.help/en-US/why-can%E2%80%99t-i-read-the-license-plate-number-clearly-6249872 | Tier 1 | OK |
| `help-center/blurry-video.html` | 179.3 | https://hc1.gorgias.help/en-US/why-is-my-video-blurry-or-out-of-focus-6265378 | Tier 1 | OK |
| `help-center/random-restarting.html` | 152.2 | https://hc1.gorgias.help/en-US/my-dashcam-is-randomly-restarting-%E2%80%93-how-to-diagnose-the-issue-2005853 | Tier 1 | OK |
| `help-center/repeatedly-on-off.html` | 178.9 | https://hc1.gorgias.help/en-US/dash-cam-repeatedly-turning-on-and-off-6267097 | Tier 1 | OK |
| `help-center/frozen-screen.html` | 176.7 | https://hc1.gorgias.help/en-US/dash-cam-screen-is-frozen-6260254 | Tier 1 | OK |

## Tier 1 — Manuals, source PDFs (`data/raw/manuals/`)

7 PDFs, **53,188,580 bytes ≈ 50.7 MB**, 351 pages. Model identification and page counts
are those established in `docs/05-step1b-verification.md`.

| File | Size (KB) | Pages | Model (per `docs/05`) | Source | Tier | Status |
| --- | ---: | ---: | --- | --- | --- | --- |
| `manuals/dc3831.pdf` | 17,577.2 | 72 | R2-4K, original mini-USB revision | Uploaded by Hardik 2026-11-07 | Tier 1 | OK |
| `manuals/User Manual For New R2-4K.pdf` | 8,509.9 | 80 | R2-4K, USB-C revision, later printing | Uploaded by Hardik 2026-11-07 | Tier 1 | OK |
| `manuals/ROVE R2-4K User Manual.pdf` | 8,276.2 | 79 | R2-4K, USB-C revision, supercapacitor | Uploaded by Hardik 2026-11-07 | Tier 1 | OK |
| `manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.pdf` | 1,838.8 | 14 | R2-4K DUAL | Uploaded by Hardik 2026-11-07 | Tier 1 | OK |
| `manuals/B0F9SX3JB9.pdf` | 1,462.7 | 12 | R2-4K DUAL PRO | Uploaded by Hardik 2026-11-07 | Tier 1 | OK |
| `manuals/r3-manual-website-files.pdf` | 138.1 | 3 | R3 (condensed) | https://cdn.prod.website-files.com/6724e2eaaa40b55848edd7ed/67b4fdf3c7d8bc594263f46b_bezog.pdf | Tier 1 | OK |
| `manuals/ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf` | 14,139.1 | 91 | R2-4K DUAL PRO (Rove's own printing) | https://cdn.shopify.com/s/files/1/2287/2433/files/ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf | Tier 1 | OK — added 4.3 |

The filename `B0F9SX3JB9.pdf` is the same ASIN as the failed URL
`https://manuals.plus/asin/B0F9SX3JB9` (line 19 of `DOWNLOAD_LOG.txt`). Whether it is the
same document was not established — no source URL was recorded for the upload.

## Tier 1 — Manuals, extracted text (`data/text/manuals/`)

7 text files, **429,990 bytes ≈ 419.9 KB**, 351 pages. One file per source PDF, same
basename (`M7` excepted — its extracted text is named `ROVE-R2-4K-DUAL-PRO.txt`). These are
what `docs/05-step1b-verification.md` greps; the short codes `M1`…`M7` below are the ones
that document uses.

| File | Size (KB) | Pages | Code | Model (per `docs/05`) |
| --- | ---: | ---: | --- | --- |
| `text/manuals/dc3831.txt` | 83.3 | 72 | `M1` | R2-4K, original mini-USB revision — 250 mAh Li-ion battery |
| `text/manuals/ROVE R2-4K User Manual.txt` | 98.7 | 79 | `M2` | R2-4K, USB-C revision, supercapacitor |
| `text/manuals/User Manual For New R2-4K.txt` | 105.4 | 80 | `M3` | R2-4K, USB-C revision, later printing |
| `text/manuals/ROVE R2-4K Dual Dash Cam Instruction Manual.txt` | 11.1 | 14 | `M4` | R2-4K DUAL |
| `text/manuals/B0F9SX3JB9.txt` | 13.9 | 12 | `M5` | R2-4K DUAL PRO |
| `text/manuals/r3-manual-website-files.txt` | 15.6 | 3 | `M6` | R3 (condensed) |
| `text/manuals/ROVE-R2-4K-DUAL-PRO.txt` | 92.1 | 91 | `M7` | R2-4K DUAL PRO — Rove's own manual, the primary DUAL PRO source |

## Failed downloads (no file on disk)

All five returned `HTTP Error 403: Forbidden` — a bot challenge, not a missing page. These
rows record the *fetch* outcome and are left unchanged; the manual gap they left has since
been covered by the 5 PDFs Hardik uploaded on 2026-11-07 (table above).

| Intended file | Size (KB) | Source URL | Tier | Status |
| --- | ---: | --- | --- | --- |
| — | — | https://manuals.plus/m/40deab8b387341f91679395691256607a3a5aac946af42d95895dcdf2969b1ae | Tier 1 | FAILED |
| — | — | https://manuals.plus/m/a27226c6a9e8699afa2c5cd58f247a3d38499b76318e11f3d9195cb7b67765b5.pdf | Tier 1 | FAILED |
| — | — | https://manuals.plus/asin/B0DB7261DP.pdf | Tier 1 | FAILED |
| — | — | https://manuals.plus/asin/B0F9SX3JB9 | Tier 1 | FAILED |
| — | — | https://www.manualslib.com/manual/1825179/Rove-R2-4k.html | Tier 1 | FAILED |

**Milestone 4.3 retry — the R2-4K PRO manual still failed.** Track C got the *DUAL* PRO
manual off the Rove Shopify CDN without trouble, and tried the **R2-4K PRO** manual at the
same time. Both routes failed again:

| Intended file | Source URL | Tier | Status |
| --- | --- | --- | --- |
| `ROVE_R2-4K-PRO_User_Manual_Updated_JAN-2025.pdf` | Rove CDN link published on the Firmware/Downloads page | Tier 1 | **FAILED — Shopify 404** (link published, file not served) |
| R2-4K PRO manual mirror | https://manuals.plus (R2-4K PRO) | Tier 1 | **FAILED — bot-blocked**, as in the original pass |

The R2-4K PRO is therefore the **only model in the supported line with no manual in the
corpus**. Everything the design documents say about the PRO specifically comes from product
listings and comparison sites — Tier 2/Tier 3 — and **must not be spoken as a verified fact
or inherited from the R2-4K or the DUAL PRO**. See `docs/04-data-sources.md`.

## Processed — chunk counts (`data/processed/`)

Written by `python -m ingest.run`, schema per `docs/06-architecture.md` §4.3/§4.4. Both
files are committed and are byte-reproducible from the corpus above.

**213 chunks · 159 speakable · 28 documents.** Milestone 4.3 took this from 161 chunks /
122 speakable / 21 documents — **+52 chunks, +37 speakable, +7 documents.**

| Group | Documents | Chunks | Speakable |
| --- | ---: | ---: | ---: |
| Manuals (`M1`–`M7`) | 7 | 177 | 131 |
| Official site (`O1`–`O3`) | 3 | 7 | 7 |
| Help Center (`H:…`) | 18 | 29 | 21 |
| **Total** | **28** | **213** | **159** |

Per document:

| Code | Chunks | Speakable | Code | Chunks | Speakable |
| --- | ---: | ---: | --- | ---: | ---: |
| `M1` | 33 | 21 | `H:troubleshoot-index` | 2 | 1 |
| `M2` | 42 | 29 | `H:wifi-not-connecting` | 2 | 2 |
| `M3` | 41 | 32 | `H:wifi-connected-disconnected` | 2 | 2 |
| `M4` | 5 | 5 | `H:missing-videos` | 2 | 2 |
| `M5` | 5 | 4 | `H:camera-does-not-turn-on` | 1 | 1 |
| `M6` | 5 | 4 | `H:r3-no-gps-live-speed` | 1 | 0 |
| `M7` **(4.3)** | 46 | 36 | `H:no-audio-sound` | 1 | 1 |
| `O1` | 2 | 2 | `H:memory-card-too-slow` | 1 | 1 |
| `O2` | 3 | 3 | `H:camera-does-not-turn-off` | 2 | 2 |
| `O3` | 2 | 2 | `H:wifi-name-not-showing` | 1 | 1 |
| | | | `H:sign-in-error-rove-app` | 1 | 0 |
| | | | `H:know-your-dashcam-how-to` | 5 | 4 |
| | | | `H:overheating` **(4.3)** | 1 | 1 |
| | | | `H:licence-plate` **(4.3)** | 1 | 1 |
| | | | `H:blurry-video` **(4.3)** | 2 | 2 |
| | | | `H:random-restarting` **(4.3)** | 1 | 0 |
| | | | `H:repeatedly-on-off` **(4.3)** | 2 | 0 |
| | | | `H:frozen-screen` **(4.3)** | 1 | 0 |

**The four zero-speakable documents are deliberate, not a bug.** `speakable` is a gate
(`docs/06` §4.5): Tier 1, *and* a verification status of VERIFIED or CORRECTED, *and* a
source. `H:random-restarting`, `H:repeatedly-on-off` and `H:frozen-screen` support no
taxonomy entry at all — writing those entries is Phase 2 work — so they are UNVERIFIED and
correctly unspeakable. `H:r3-no-gps-live-speed` and `H:sign-in-error-rove-app` are the same
case from the original pass.

**Verification status across chunks:** 100 VERIFIED, 59 CORRECTED, 54 UNVERIFIED. One
firmware version string was redacted (`docs/06` §4.6 — no chunk may carry a version).

## Other files

| File | Size (KB) | Notes |
| --- | ---: | --- |
| `raw/DOWNLOAD_LOG.txt` | 3.3 | Fetcher log; the authoritative URL → path mapping for the table above. Does **not** cover the 7 documents added by Milestone 4.3 — their URLs are in the tables above. |
