"""Tier-1 ingestion for the Rove voice support agent.

Milestone 2. Turns the 21 Tier-1 documents on disk into chunks carrying the
full metadata schema of `docs/06-architecture.md` §4.3, plus a source registry
(§4.4).

Stdlib only. No network. No AWS. Nothing here reads anything that is not
already under `data/`.

Modules:
    metadata  the source registry, the model vocabulary, the docs/05 evidence
              map, and every rule that turns a span of text into a metadata
              record.
    chunk     the parsers (stdlib `html.parser` for HTML, page-aware plain
              text for the extracted manuals) and the chunk packer.
    run       `python -m ingest.run`  -> data/processed/{chunks.jsonl,sources.json}
    validate  `python -m ingest.validate`
"""

__all__ = ["chunk", "metadata"]
