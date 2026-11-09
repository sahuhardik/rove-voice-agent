# Tier 2 review samples — ROVE Dash Cam

Retrieved: 2026-11-08
Milestone: Tier 2 review samples (app and Amazon)
Companion to `docs/04-data-sources.md` §2.1 and §2.2.

## Tier 2 means discovery, not fixes

Per `docs/04-data-sources.md`:

> **Tier 2 = Discovery.** Use for symptom language, frequency, and eval scenarios — never
> as a fix on its own.

Everything in this directory is customer-written text. Use it for **how users phrase a
symptom**, **how often a symptom appears**, and **eval scenario seeds**. A reviewer's
suggested remedy is **never** a verified fix and must never reach the agent's spoken
output. Only Tier 1 (official Rove docs and Help Center articles) may be spoken as a fix.
Every review object in these files carries a `tier` field restating this.

Collecting these samples does not promote any taxonomy entry. It touches no runtime code,
so constraints C-1 (web-based voice assistant, not telephonic) and C-2 (AWS models only)
are unaffected.

## What was collected

| File | Source | Reviews | Filter | Date range | Versions seen |
|---|---|---|---|---|---|
| `google-play-com.rovedashcam.android.json` | Google Play — `com.rovedashcam.android` | **100** | 1–2 star only | 2026-06-09 → 2026-11-05 | 5.0.4 – 6.2.0 (92/100 carry a version) |
| `app-store-id1606959035.json` | Apple App Store — `id1606959035` | **100** | 1–2 star only | 2026-01-14 → 2026-11-04 | 5.0.4 – 6.0.7 (100/100 carry a version) |

**200 low-rated reviews total**, both at the top of the 50–100 per app target.

Rating split — Google Play 81 × 1-star, 19 × 2-star; App Store 75 × 1-star, 25 × 2-star.

Each review object has: `review_id`, `source`, `source_url`, `retrieved_utc`, `tier`,
`rating`, `date`, `app_version`, `author`, `title`, `text`, `thumbs_up`. The App Store
objects also carry `source_feed_url` (the exact paginated feed the record came from).
Google Play reviews have no title field, so `title` is `null` there.

### How it was collected

Both files come from the same public endpoints the npm packages `google-play-scraper` and
`app-store-scraper` call:

- Google Play — `https://play.google.com/_/PlayStoreUi/data/batchexecute`, rpcid `UsvDTd`,
  newest-first, paginated. 200 reviews scanned over 2 pages, 1–2 star kept.
- App Store — `https://itunes.apple.com/us/rss/customerreviews/`, `sortby=mostrecent`,
  pages 1–3 (the feed ran out at page 4). 150 reviews scanned, 1–2 star kept.
  `sortby=mostcritical` was tried first and returned HTTP 500 from Apple, so it was skipped.

The requests were made directly with `python3` + `urllib` rather than through the npm
packages. **The npm registry is reachable** — `registry.npmjs.org` returned 200 for both
`google-play-scraper` (10.1.4) and `app-store-scraper` (0.18.0) — but `npm`, `npx` and
`node -e` are **blocked by this repo's permission policy** in `.claude/settings.json`, and
this was a non-interactive session with no way to approve them. `python3` is allowlisted,
and `data/raw/DOWNLOAD_LOG.txt` shows the same urllib-fetcher approach was already used for
the Tier 1 pass. No `curl`/`wget`, no web fetch/search was used.

Collector: `scripts/collect_app_reviews.py` (re-runnable).

### Symptom-language frequency (Tier 2 signal, not a diagnosis)

Keyword presence across the 100 reviews in each file. A review can match more than one row;
these are coarse regex hits for eval-scenario weighting, not a validated taxonomy mapping.

| Theme | Google Play | App Store |
|---|---|---|
| Wi-Fi / connect / pair | 46 | 48 |
| Update / firmware regression | 27 | 20 |
| Download / transfer / slow | 11 | 24 |
| Login / account / verification email | 14 | 14 |
| SD card / format | 7 | 10 |
| App crash / freeze | 6 | 8 |
| Support / warranty / refund | 4 | 7 |
| Live view / playback | 2 | 4 |
| Recording / files missing | 3 | 3 |
| GPS / speed | 2 | 4 |
| Power / reboot | 2 | 4 |
| Audio | 2 | 2 |

This is consistent with `docs/04-data-sources.md` §2.2's recurring-theme list, and is the
first time that list is backed by a counted sample rather than an impression. Wi-Fi and
connection language dominates both stores; the "update broke it" signal is strong enough on
both to be worth its own eval scenario.

## What was NOT collected, and why

**Amazon product reviews for R2-4K, R2-4K DUAL, R2-4K DUAL PRO and R3 — zero reviews.**

Recorded in full in `amazon-NOT-COLLECTED.json`, including every URL probed and its exact
response. Summary:

- `amazon.com` was **deliberately never requested**, per the constraint to use aggregators
  or an API only.
- **Desertcart** (the mirror named in `docs/04` §2.1) is no longer usable: product pages
  return HTTP 403 behind a Cloudflare interstitial, the `/reviews` sub-path 403s, candidate
  JSON APIs 404, and the search page returns a client-rendered shell with no product links
  and no server-rendered review text.
- **Rainforest API** answers, but with HTTP 503 and `"reviews request type is temporarily
  unavailable"` — the review endpoint is disabled vendor-side, and would need a paid key
  anyway.
- **Amazon PA-API v5** needs signed Associate credentials; none are in the environment, and
  `Bash(aws:*)` is denied. It also returns rating summaries, not review text.
- **ReviewMeta** is defunct (its host now serves a bare Kubernetes 403).
- **Keepa** (needs a paid key; carries price/rank history, not review text), **Apify**
  (needs an account token) and **Ubuy** (403) were also probed and rejected.

This is a **source-access** failure, not a network failure: general outbound HTTPS works
from this host — `openlibrary.org` returned 200 in the same probe run, and both app-store
collections above succeeded.

Per instruction, that half was stopped rather than filled in. **No Amazon review text was
written from memory, inferred, or reconstructed.** The theme list in `docs/04` §2.1 remains
an unverified impression from an earlier browsing pass — it is not corroborated by anything
in this directory.

### Knock-on gaps

- **Per-model frequency is unavailable.** The app reviews cover the ROVE app as a whole and
  only **5 of the 200** name a model at all (3 on Google Play, 2 on the App Store). Amazon
  was the source that would have split symptom frequency across R2-4K / DUAL / DUAL PRO /
  R3, so Tier 2 currently gives app-level frequency only, with no per-model breakdown.
- **ASINs for R2-4K, R2-4K DUAL and R3 are still unknown.** Only `B0F9SX3JB9` (R2-4K DUAL
  PRO, from `docs/05`) and an unconfirmed `B0DB7261DP` (from a failed `manuals.plus` fetch
  in `data/raw/DOWNLOAD_LOG.txt`) appear anywhere in the repo. They were not guessed.
- **Hardware-only symptoms are under-sampled.** Mounting, adhesive, heat, cable and
  physical-defect complaints live mostly in Amazon reviews; an app-store-only sample skews
  toward connectivity and software.

### Lead for a later pass (not collected here, out of this task's scope)

`https://www.rovedashcam.com/products.json?limit=5` returned HTTP 200 — the official store
is a Shopify instance with a readable product feed. If it carries on-site product reviews,
that would be a reachable substitute for per-model frequency. Not pursued here: this
milestone's scope was Amazon reviews, and a Rove-hosted review is a different source that
needs its own tier call in `docs/04`.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/collect_app_reviews.py` | Collects both app-store files. Re-runnable. |
| `scripts/probe_play.py` | One-off probe that established the Google Play RPC shape. |
| `scripts/probe_amazon_aggregators.py` | Round 1 Amazon aggregator reachability probe. |
| `scripts/probe_amazon_round2.py` | Round 2, incl. the egress control check. |

The probe scripts are kept as the evidence behind `amazon-NOT-COLLECTED.json` — rerun them
to confirm the half is still blocked before anyone retries it.
