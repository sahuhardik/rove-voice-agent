# Tier 3 manual mirrors — NOT Tier 1

This directory holds third-party mirror copies of manuals. Nothing here is
Tier 1 ground truth and nothing here is read by the ingest pipeline
(`ingest/` only reads `data/raw/manuals/`). Do NOT move a file from here into
`data/raw/manuals/` without a Tier 1 source confirming it.

## ROVE_R2-4K_PRO_User_Manual_ManualsLib-mirror.pdf

- Model: ROVE R2-4K PRO
- Source: ManualsLib, https://www.manualslib.com/manual/3130610/Rove-R2-4k-Pro.html
- Retrieved: 2026-11-08 (by Muse's browser; reCAPTCHA completed, no account, no payment)
- Size: 8,636,977 bytes; SHA-256: 76236f6da23d8df17637e5e83509dd7a0613e64cb94eb8b3a61616c151142fd2
- Pages: 83 (ManualsLib lists 79 pages of content); extracted text 2,916 lines
- Verified content markers: header "ROVE R2-4K PRO USER MANUAL", FCC ID
  2A3IW-R24KPRO (3 mentions), "supercapacitor" (17), firmware string
  ROVE-R2-4K-PRO-04-01-2023 (1)
- Tier: 3 (mirror). The official PDF on Rove's Shopify CDN
  (ROVE_R2-4K-PRO_User_Manual_Updated_JAN-2025.pdf) still returns 404.

USE: cross-check and discovery only — e.g. comparing its claims against Tier 1
sources, or finding candidate taxonomy entries to verify.
DO NOT USE: no PRO fact from this file may be spoken as a verified fix, and no
chunk from it may enter the Tier 1 store, until a Tier 1 source confirms it.
The agent must still never state a firmware version (the ROVE-R2-4K-PRO-04-01-2023
string above is recorded here for verification only, not for speaking).
