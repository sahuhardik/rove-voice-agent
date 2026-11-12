"""`python -m ingest.run` -- chunk the Tier-1 corpus and write the registry.

Writes two files, both of which are committed:

    data/processed/chunks.jsonl    one chunk per line, docs/06 §4.3 schema
    data/processed/sources.json    one entry per source document, docs/06 §4.4

and prints counts per document and per model, which is the cheapest way to see
that a corpus change did what it was supposed to.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import metadata as md
from .chunk import REPO_ROOT, chunk_corpus

OUT_DIR = REPO_ROOT / "data" / "processed"
CHUNKS_PATH = OUT_DIR / "chunks.jsonl"
SOURCES_PATH = OUT_DIR / "sources.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_registry(chunks: list[md.Chunk]) -> dict:
    """The source registry of `docs/06` §4.4, keyed by `doc_code`.

    Holds source URL, retrieval date, tier, provenance, content hash and the
    licence note, so that "where did the agent get that from" is a lookup.
    """
    per_doc = Counter(c.doc_code for c in chunks)
    speakable = Counter(c.doc_code for c in chunks if c.speakable)

    entries = []
    for source in md.SOURCES.values():
        path = REPO_ROOT / source.path
        entries.append(
            {
                "doc_code": source.doc_code,
                "title": source.title,
                "tier": source.tier,
                "source_url": source.source_url,
                "provenance": source.provenance,
                "attested_by": (
                    md.ATTESTED_BY
                    if source.provenance == md.PROVENANCE_OPERATOR_ATTESTED
                    else None
                ),
                "retrieval_date": source.retrieval_date,
                "file": source.path,
                "content_sha256": _sha256(path),
                "chunk_count": per_doc.get(source.doc_code, 0),
                "speakable_chunk_count": speakable.get(source.doc_code, 0),
                "speakable_scope": source.speakable_scope,
                "models": list(source.models),
                "note": source.note,
            }
        )
    return {
        "generated_by": "python -m ingest.run",
        "retrieval_date": md.RETRIEVAL_DATE,
        "tier": md.TIER,
        "licence_note": (
            "Rove content is used for support in this assessment. Do not "
            "republish manuals verbatim in the app UI; use short grounded "
            "excerpts with source attribution (docs/04 'Gaps / risks')."
        ),
        "provenance_hole": (
            "5 of the 7 manuals (M1-M5) were uploaded by hand on 2026-11-07 "
            "and carry no source URL. They are provenance=operator_attested "
            "and speakable for the prototype only; the docs/06 §9.1 Phase 4 "
            "production gate does not pass until a signed per-file record "
            "exists (docs/06 §4.4)."
        ),
        "sources": entries,
    }


def write_outputs(chunks: list[md.Chunk]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_json_dict(), ensure_ascii=False) + "\n")
    SOURCES_PATH.write_text(
        json.dumps(build_registry(chunks), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _report(chunks: list[md.Chunk]) -> None:
    per_doc = Counter(c.doc_code for c in chunks)
    speakable = Counter(c.doc_code for c in chunks if c.speakable)
    tokens = [c.token_estimate for c in chunks]

    print(f"chunks: {len(chunks)}")
    print(
        "tokens: min {} / median {} / max {} (budget 300-800; a procedure may "
        "exceed it, docs/06 §4.2)".format(
            min(tokens), sorted(tokens)[len(tokens) // 2], max(tokens)
        )
    )
    print()
    print("per document")
    print(f"  {'doc':28} {'chunks':>6} {'speakable':>9}  source")
    for source in md.SOURCES.values():
        code = source.doc_code
        origin = (
            source.source_url
            if source.source_url
            else f"{md.PROVENANCE_OPERATOR_ATTESTED} ({md.ATTESTED_BY})"
        )
        print(
            f"  {code:28} {per_doc.get(code, 0):>6} {speakable.get(code, 0):>9}  "
            f"{origin[:72]}"
        )

    print()
    print("per model (a chunk counts once per model it applies to)")
    per_model: Counter[str] = Counter()
    cross = 0
    for chunk in chunks:
        if chunk.cross_model:
            cross += 1
        for model in chunk.model_applicability:
            per_model[model] += 1
    for model in md.ALL_MODELS:
        print(f"  {model:20} {per_model.get(model, 0):>5}")
    print(f"  {'(cross-model)':20} {cross:>5}")

    print()
    print("per verification status")
    for status, count in Counter(c.verification_status for c in chunks).most_common():
        print(f"  {status:12} {count:>5}")
    print(f"  {'speakable':12} {sum(1 for c in chunks if c.speakable):>5}")

    print()
    print("per category")
    for category, count in Counter(c.category for c in chunks).most_common():
        print(f"  {category:12} {count:>5}")

    redacted = sum(len(c.redactions) for c in chunks)
    if redacted:
        print()
        print(
            f"firmware version strings redacted: {redacted} "
            "(docs/06 §4.6 -- no chunk may carry a version)"
        )


def main() -> int:
    chunks = chunk_corpus()
    write_outputs(chunks)
    _report(chunks)
    print()
    print(f"wrote {CHUNKS_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {SOURCES_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
