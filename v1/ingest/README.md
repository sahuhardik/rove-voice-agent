# `ingest/` — Milestone 2, Tier-1 ingestion

Turns the 21 Tier-1 documents under `data/` into **161 chunks** carrying the full
`docs/06` §4.3 metadata schema, plus a source registry (§4.4). Stdlib only — no
third-party packages, no network, no AWS. Nothing here reads anything that is not
already on disk, so the ingest is reproducible from the committed corpus alone.

| file | what it holds |
| --- | --- |
| `metadata.py` | the source registry (21 documents), the model vocabulary, the `docs/05` evidence map, and every rule that turns a span of text into a metadata record |
| `chunk.py` | the two parsers (stdlib `html.parser` for HTML, page-aware plain text for the extracted manuals), the piece builder and the packer |
| `run.py` | `python -m ingest.run` → `data/processed/{chunks.jsonl,sources.json}` |
| `validate.py` | `python -m ingest.validate` — rule checks (fatal) and coverage gaps (reported) |
| `test_ingest.py` | 15 stdlib unittest cases over atomicity, metadata defaults, the validator and the M6 boilerplate |

## Running it

```bash
.venv/bin/python -m ingest.run        # rewrites both files under data/processed/
.venv/bin/python -m ingest.validate   # exits 0 only when there are no ERRORS
.venv/bin/python -m unittest ingest.test_ingest
```

`ingest.run` is deterministic: same corpus in, byte-identical files out. Both outputs
are committed, so a reviewer can read the chunks without running anything, and a
regeneration that changes them shows up as a diff.

**Exit codes.** `ingest.validate` separates two findings and the difference is the
point. **ERRORS** are breaches of a stated requirement — a chunk with no source, an
empty required field, a firmware version in the text, a speakable UNVERIFIED chunk, a
split procedure — and exit non-zero. **COVERAGE GAPS** — a VERIFIED or CORRECTED entry
in `docs/02` that no speakable chunk grounds — exit zero: that is a fact about the
corpus, not a bug in the ingest, and failing the build on it would hide it behind a
red light. There are currently 0 errors and 0 gaps: 23/23 cleared entries are
grounded, and the 5 entries `docs/05` left UNVERIFIED or REJECTED have no speakable
chunk, as they should.

## Chunking rules

**A procedure is atomic.** The overriding rule (`docs/06` §4.2). The card-side firmware
update is *format in camera → copy files → camera powered and OFF → insert card →
press Power once → red LED → do not disconnect power → it restarts → format again*. A
boundary anywhere inside that run can surface "insert the card and press power"
without "the camera must be off", and `docs/02` calls FW-01 a high-risk entry where
the wrong advice destroys the device. So a numbered run is never split, and **if a
procedure exceeds the chunk budget, the chunk exceeds the budget** — 5 of the 161
chunks do. An immediately following NOTE / IMPORTANT / CAUTION paragraph is pulled
into the run, because "do not disconnect the power" is part of the procedure it sits
under.

**Budget: 300–800 token-equivalents** (`metadata.estimate_tokens`, ~1.3 tokens per
word — no tokenizer needed to hold a budget to). Adjacent material merges up to 800; a
chunk closes as soon as it has reached 300 and the next piece opens a new top-level
section, so section boundaries are respected wherever the budget allows.

**Overlap: one sentence**, carried from the previous chunk, and only where the text
actually continues — never across a top-level section boundary.

**Headings become `section_path`** and are restated in `context_header`, so a
retrieved chunk is self-describing when read in isolation. A document that supplies no
heading at all falls back to its registry title (see M6 below); `section_path` is
never empty.

**Table rows stay whole.** A row is assembled into one block with each cell labelled by
its column heading, so the per-model Wi-Fi table never puts an SSID in one chunk and
the model it belongs to in another — model filtering is a safety control (§4.6).

**Boilerplate is removed at parse time**: scripts, nav, footers, the Gorgias pages'
duplicated mobile copy, running headers and page numbers, and the storefront furniture
described below.

## Metadata schema

One JSON object per line in `data/processed/chunks.jsonl`, in `docs/06` §4.3 order:

| group | fields |
| --- | --- |
| identity | `chunk_id`, `text`, `token_estimate` |
| provenance | `doc_code`, `source_path`, `source_url`, `retrieval_date`, `tier`, `provenance`, `attested_by` |
| location | `page_range`, `section`, `section_path`, `context_header`, `overlap_sentence` |
| applicability | `model_applicability`, `cross_model`, `hw_revision_specific`, `firmware_applicability` |
| routing | `category`, `categories`, `taxonomy_ids`, `step_ids` |
| gating | `verification_status`, `speakable`, `speakable_scope`, `speakable_reason`, `destructive`, `safety_critical`, `expectation_gap` |
| audit | `redactions` |

Four of these carry the rules rather than describe the text:

- **`model_applicability` is explicit, never "all"** (§4.3). A manual inherits its
  model from the registry; a shared page is read per chunk, and a chunk that genuinely
  covers every model is marked `cross_model` instead of listing them.
- **`firmware_applicability` is always `{"version": "unknown"}`** and version strings
  are redacted out of `text` (§4.6). The corpus cannot tell which firmware a caller is
  on, so no chunk is allowed to imply that it can. 1 version string was redacted; the
  validator fails the build if one reappears.
- **`verification_status`** is the strongest status among the `docs/05` entries a chunk
  is evidence for, and a chunk backing no entry is UNVERIFIED — unevidenced, not wrong.
- **`speakable`** requires VERIFIED or CORRECTED *and* a source. `speakable_reason`
  records which test decided it, in both directions. 122 of 161 chunks are speakable.

`sources.json` holds one entry per document — URL, retrieval date, tier, provenance,
`content_sha256`, chunk counts, models, note — so "where did the agent get that from"
is a lookup, not an investigation.

## The provenance hole

**5 of the 6 manuals (M1–M5) carry no source URL.** They were uploaded by hand on
2026-11-07 and `data/raw/DOWNLOAD_LOG.txt` has no record of where they came from.
Rather than discard them or quietly treat them as crawled, they are a third provenance
class: `provenance=operator_attested`, `attested_by=Hardik`, `speakable_scope=prototype`
(§4.4). The validator accepts a named attestation with a named date as a source, which
is what makes them speakable at all — and `speakable_scope` is the field that stops
that from being mistaken for production clearance.

This is a hole, not a solved problem. The §9.1 Phase 4 production gate does not pass
until a signed per-file record exists for each of them. It is restated verbatim in
`sources.json` under `provenance_hole`, so the artefact carries the caveat even when
this README is not in the room. M6, by contrast, has a crawler-captured URL and is
`speakable_scope=production`.

## M6: the storefront came in with the PDF

M6 is the R3 manual as published on the Rove storefront, and the PDF was printed from
that page. Two consequences, both handled in `chunk.py` and recorded in the M6 `note`
field of `sources.json`:

**No headings.** Pages 1–2 extract empty and page 3 carries the entire manual as one
unbroken run of prose with no heading in it. The heading path is therefore genuinely
empty, and the chunker used to emit `section_path: []` — a required field, present but
empty, which the validator rightly failed on (5 ERRORS, `M6#SECTION#p3` … `p3-5`).
`_section_path_for` now falls back to the document's registry title, which is true, is
what a reader needs in order to place the chunk, and is already restated in
`context_header`. The fallback applies to any document with no headings, not just M6.

**Storefront text in the body.** The extraction brought the shop with it: the age gate
("Are you at least 18 years old? … Come back when you're older."), the
"FREE 3 DAY SHIPPING ON ALL DASH CAMS" banner, the firmware/downloads page lead-in
("Below, you'll find all the latest firmware…"), the community / EMAIL US / QR-code
furniture, and a trailing SEO keyword list. All of it is non-manual, all of it reads
like speakable prose, and none of it was removable by the whole-line noise rule because
it is spliced *inside* lines. `_MANUAL_INLINE_NOISE` strips it by pattern and
`_is_seo_keyword_run` drops the keyword list structurally (three or more short
fragments, each naming both the brand and the product) rather than by listing keywords.

Manual content was deliberately not touched. The magnetic- and suction-mount steps on
page 3 are real manual content and remain; so do the Wi-Fi pairing steps, the memory
card requirements and the troubleshooting guide. `test_ingest.py` asserts both halves —
the boilerplate is gone *and* the mounting steps are still there — because dropping
genuine content would be the worse of the two failures and the silent one.
