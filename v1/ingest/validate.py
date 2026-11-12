"""`python -m ingest.validate` -- check the ingested corpus against the rules.

Two classes of finding, and the difference is the point:

**ERRORS** are breaches of a rule the design record states as a requirement.
They exit non-zero.

    - a chunk with no source, or no `doc_code`
      (`docs/04` item 5: "No chunk without a source may be spoken as a fix")
    - a chunk with an empty `model_applicability` that is not marked
      `cross_model` (`docs/06` §4.3: explicit, never "all")
    - a chunk missing any required metadata field (`docs/06` §4.3: "a chunk
      missing any required field is not indexed into the speakable store")
    - a firmware version string in chunk text (`docs/06` §4.6)
    - a speakable chunk whose status is UNVERIFIED or REJECTED
      (`docs/06` §4.5 item 3)
    - a numbered procedure split across two chunks (`docs/06` §4.2)

**COVERAGE GAPS** are not errors. A VERIFIED or CORRECTED entry in `docs/02`
with no speakable chunk behind it is a fact about the corpus, not a bug in the
ingest: it means Step 1b verified something this corpus cannot currently
ground. Reporting it is the whole point; failing the build on it would hide
it behind a red light. They exit zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import metadata as md
from .chunk import REPO_ROOT

CHUNKS_PATH = REPO_ROOT / "data" / "processed" / "chunks.jsonl"
SOURCES_PATH = REPO_ROOT / "data" / "processed" / "sources.json"

#: Every field of the `docs/06` §4.3 schema that must be present and set.
#: `source_url` and `page_range` are nullable by design (§4.4, and HTML has no
#: pages), so they are checked separately rather than listed here.
REQUIRED_FIELDS = (
    "chunk_id",
    "text",
    "doc_code",
    "source_path",
    "retrieval_date",
    "tier",
    "provenance",
    "section_path",
    "context_header",
    "model_applicability",
    "firmware_applicability",
    "category",
    "verification_status",
    "token_estimate",
)

BOOL_FIELDS = (
    "cross_model",
    "hw_revision_specific",
    "speakable",
    "destructive",
    "safety_critical",
    "expectation_gap",
)

_LEADING_STEP = ("1", "2", "3", "4", "5", "6", "7", "8", "9")


def load_chunks(path: Path = CHUNKS_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"{path} not found -- run `python -m ingest.run` first."
        )
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _has_source(chunk: dict) -> bool:
    """`docs/04` item 5, read with `docs/06` §4.4's third provenance class.

    A crawler-captured URL is a source. An operator attestation -- named
    person, named date, recorded in the registry -- is a weaker source, and
    the registry has to show that difference rather than hide it, which is
    what `speakable_scope: prototype` does.
    """
    if chunk.get("source_url"):
        return True
    return (
        chunk.get("provenance") == md.PROVENANCE_OPERATOR_ATTESTED
        and bool(chunk.get("attested_by"))
        and bool(chunk.get("retrieval_date"))
    )


def check_chunks(chunks: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for chunk in chunks:
        cid = chunk.get("chunk_id") or "<no chunk_id>"

        for field in REQUIRED_FIELDS:
            if field not in chunk:
                errors.append(f"{cid}: missing metadata field {field!r}")
            elif chunk[field] in (None, "", [], {}):
                errors.append(f"{cid}: empty required field {field!r}")
        for field in BOOL_FIELDS:
            if not isinstance(chunk.get(field), bool):
                errors.append(f"{cid}: field {field!r} is not a boolean")

        if cid in seen_ids:
            errors.append(f"{cid}: duplicate chunk_id")
        seen_ids.add(cid)

        if not chunk.get("doc_code"):
            errors.append(f"{cid}: empty doc_code")
        elif chunk["doc_code"] not in md.SOURCES:
            errors.append(f"{cid}: doc_code {chunk['doc_code']!r} is not in the registry")

        if not _has_source(chunk):
            errors.append(
                f"{cid}: no source -- neither a source_url nor an operator "
                "attestation (docs/04 item 5)"
            )

        if not chunk.get("model_applicability") and not chunk.get("cross_model"):
            errors.append(
                f"{cid}: model_applicability is empty and the chunk is not "
                "marked cross_model (docs/06 §4.3)"
            )
        for model in chunk.get("model_applicability", []):
            if model not in md.ALL_MODELS:
                errors.append(f"{cid}: unknown model {model!r}")

        if chunk.get("tier") != md.TIER:
            errors.append(f"{cid}: tier is {chunk.get('tier')!r}, expected {md.TIER}")

        firmware = chunk.get("firmware_applicability") or {}
        if firmware.get("version") != "unknown":
            errors.append(
                f"{cid}: firmware_applicability.version is "
                f"{firmware.get('version')!r}; docs/06 §4.6 requires 'unknown' "
                "on every chunk"
            )

        found = md.contains_firmware_version(chunk.get("text", ""))
        if found:
            errors.append(
                f"{cid}: chunk text contains a firmware version string "
                f"{found!r} (docs/06 §4.6)"
            )

        status = chunk.get("verification_status")
        if status not in md.STATUS_RANK:
            errors.append(f"{cid}: unknown verification_status {status!r}")
        elif chunk.get("speakable") and status not in md.SPEAKABLE_STATUSES:
            errors.append(
                f"{cid}: speakable with verification_status={status} "
                "(docs/06 §4.5 item 3)"
            )

        for taxonomy_id in chunk.get("taxonomy_ids", []):
            if taxonomy_id.startswith("GAP-"):
                continue
            if taxonomy_id not in md.TAXONOMY_STATUS:
                errors.append(f"{cid}: unknown taxonomy id {taxonomy_id!r}")
            elif (
                md.TAXONOMY_STATUS[taxonomy_id] == md.REJECTED
                and chunk.get("speakable")
            ):
                errors.append(
                    f"{cid}: speakable chunk carries REJECTED entry "
                    f"{taxonomy_id} (docs/05; docs/06 §4.5)"
                )

    errors.extend(check_procedures_atomic(chunks))
    errors.extend(check_step_ids(chunks))
    return errors


def check_procedures_atomic(chunks: list[dict]) -> list[str]:
    """`docs/06` §4.2: a numbered step sequence is never split.

    Detected from the rendered text: if a chunk's last line is a numbered
    step and the next chunk in the same document opens with a numbered step
    that continues the count, a procedure was cut in half.
    """
    errors: list[str] = []
    for previous, current in zip(chunks, chunks[1:]):
        if previous.get("doc_code") != current.get("doc_code"):
            continue
        previous_lines = [l for l in previous.get("text", "").split("\n") if l.strip()]
        current_lines = [l for l in current.get("text", "").split("\n") if l.strip()]
        if not previous_lines or not current_lines:
            continue
        tail, head = previous_lines[-1].strip(), current_lines[0].strip()
        if not (tail[:1] in _LEADING_STEP and head[:1] in _LEADING_STEP):
            continue
        tail_number = _leading_number(tail)
        head_number = _leading_number(head)
        if tail_number is None or head_number is None:
            continue
        if head_number == tail_number + 1:
            errors.append(
                f"{current['chunk_id']}: numbered procedure split -- previous "
                f"chunk ends at step {tail_number}, this one opens at step "
                f"{head_number} (docs/06 §4.2)"
            )
    return errors


def _leading_number(line: str) -> int | None:
    digits = ""
    for char in line:
        if char.isdigit():
            digits += char
        else:
            break
    if not digits or len(digits) > 2:
        return None
    rest = line[len(digits) :]
    if rest[:1] not in (".", ")", ":", " ", "\t"):
        return None
    return int(digits)


def check_step_ids(chunks: list[dict]) -> list[str]:
    """Every `step_id` must exist in the canonical ontology (`docs/06` §3.6).

    The ontology lives in `eval/ontology.py` (Phase 0). If it cannot be
    imported the check is skipped rather than guessed at.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from eval.ontology import STEPS  # noqa: PLC0415
    except Exception:  # pragma: no cover - ontology is optional here
        return []
    errors = []
    for chunk in chunks:
        for step_id in chunk.get("step_ids", []):
            if step_id not in STEPS:
                errors.append(
                    f"{chunk['chunk_id']}: step_id {step_id!r} is not in the "
                    "canonical ontology (docs/06 §3.6)"
                )
    return errors


def coverage_gaps(chunks: list[dict]) -> list[tuple[str, str, str]]:
    """Entries `docs/05` cleared that no speakable chunk currently grounds.

    Returns (taxonomy_id, status, why). Only VERIFIED and CORRECTED entries
    are checked: UNVERIFIED and REJECTED entries are *expected* to have no
    speakable chunk, and finding one would be the error.
    """
    speakable_ids: set[str] = set()
    any_ids: set[str] = set()
    for chunk in chunks:
        for taxonomy_id in chunk.get("taxonomy_ids", []):
            any_ids.add(taxonomy_id)
            if chunk.get("speakable"):
                speakable_ids.add(taxonomy_id)

    gaps = []
    for taxonomy_id, status in md.TAXONOMY_STATUS.items():
        if status not in md.SPEAKABLE_STATUSES:
            continue
        if taxonomy_id in speakable_ids:
            continue
        why = (
            "chunks exist but none is speakable"
            if taxonomy_id in any_ids
            else "no chunk in the corpus matches this entry's evidence"
        )
        gaps.append((taxonomy_id, status, why))
    return gaps


def expected_absences(chunks: list[dict]) -> list[str]:
    """UNVERIFIED and REJECTED entries, confirmed to have no speakable chunk.

    `docs/05` says FW-03, APP-02 and APP-04 have no Tier-1 coverage and
    SD-02's premise does not exist. (PWR-02 was on that list until Milestone
    4.3 captured the overheating article; it is CORRECTED now.) This prints
    the confirmation, so the absence is visible as a deliberate outcome
    rather than an oversight.
    """
    speakable_ids = {
        t
        for chunk in chunks
        if chunk.get("speakable")
        for t in chunk.get("taxonomy_ids", [])
    }
    return [
        f"{t} ({md.TAXONOMY_STATUS[t]}) -- "
        + ("NO speakable chunk, as expected" if t not in speakable_ids else "LEAKED")
        for t, status in md.TAXONOMY_STATUS.items()
        if status not in md.SPEAKABLE_STATUSES
    ]


def main() -> int:
    chunks = load_chunks()
    print(f"validating {len(chunks)} chunks from {CHUNKS_PATH.relative_to(REPO_ROOT)}")
    if not SOURCES_PATH.exists():
        print(f"ERROR: {SOURCES_PATH} is missing -- run `python -m ingest.run`")
        return 1

    errors = check_chunks(chunks)
    gaps = coverage_gaps(chunks)

    print()
    speakable_entries = sum(
        1
        for t, s in md.TAXONOMY_STATUS.items()
        if s in md.SPEAKABLE_STATUSES
    )
    print(
        f"coverage of the {speakable_entries} VERIFIED / CORRECTED entries in "
        "docs/02 + docs/05"
    )
    covered = speakable_entries - len(gaps)
    print(
        f"  grounded by at least one speakable chunk: {covered}/{speakable_entries}"
    )
    if gaps:
        print("  COVERAGE GAPS (reported, not fatal):")
        for taxonomy_id, status, why in gaps:
            print(f"    {taxonomy_id:8} {status:10} {why}")
    else:
        print("  no coverage gaps")

    print()
    print("entries expected to have no speakable chunk (docs/05)")
    for line in expected_absences(chunks):
        print(f"  {line}")

    print()
    if errors:
        print(f"ERRORS: {len(errors)}")
        for error in errors:
            print(f"  {error}")
        return 1
    print("ERRORS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
