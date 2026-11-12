"""The Postgres + pgvector chunk store (`docs/06` §8.5 option B, `docs/07` D-12).

This module owns everything that touches the database: the schema, the
migration that loads `data/processed/chunks.jsonl` and `sources.json` into it,
the Titan embedding calls (`docs/07` D-11), and the two halves of the §4.6
hybrid search expressed as SQL. `agent/retrieval.py` owns the filter chain, the
fusion and the rerank, and never writes SQL.

**Why a database at all**, since `docs/06` §8.5 concedes an embedded store would
be faster: the source registry, the clearance flags, the ledgers, the
orchestration checkpoints and the traces all want to be in the same
transactional store as the chunks, and §4.4's rule — *no chunk without a
registry entry is indexed* — is naturally a foreign key. Here it is literally
one: `chunks.doc_code REFERENCES source_registry(doc_code)`.

Three constraints are enforced by the schema rather than by application code,
because a filter bug is a plausible event and a rejected `INSERT` is not:

* `chunks.tier = 1` — §4.5's physical separation, as a `CHECK`. Tier 2/3 cannot
  be loaded into this table at all.
* `NOT speakable OR verification_status IN ('VERIFIED','CORRECTED')` — §4.5's
  status gate. An `UNVERIFIED` or `REJECTED` entry cannot be marked speakable,
  so it can never be returned by a search that filters on `speakable`.
* `chunk_embeddings` is populated for speakable chunks only, so the dense half
  of the search has nothing else to find even if the `speakable` predicate were
  dropped.

**The embedding dimension is never hard-coded.** `docs/07` D-11 consequence 1
says the schema must not assume it, so the migration probes the model once,
creates `vector(n)` with whatever it got back, and records `(model_id, dim)` in
`embedding_model`. Retrieval reads the dimension from that row.

**Lexical tokenization lives here, not in `retrieval.py`,** because index time
and query time have to be the same code or BM25 is scoring two different
languages. `rove_english` is a Snowball-stemmed configuration with *no*
stopword dictionary, because the Postgres `english` configuration drops `off`,
`on`, `no` and `not` — all content words in a corpus about a camera that will
not turn off. The short stoplist in `_STOPWORDS` is applied in Python instead,
before the text ever reaches `to_tsvector`.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = _ROOT / "data" / "processed" / "chunks.jsonl"
SOURCES_PATH = _ROOT / "data" / "processed" / "sources.json"

#: Peer auth over the Unix socket; no password anywhere in the repo.
DEFAULT_DSN = "postgresql://ubuntu@/rove?host=/var/run/postgresql"
DSN = os.environ.get("ROVE_PG_DSN", DEFAULT_DSN)

#: `docs/07` D-11. Pinned: changing it means re-embedding the whole corpus and
#: re-running the eval set, so it is a decision, not a parameter.
EMBED_MODEL_ID = os.environ.get("ROVE_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBED_REGION = os.environ.get("ROVE_BEDROCK_REGION", "us-east-1")

#: BM25 parameters. Textbook defaults; nothing in a 161-chunk corpus justifies
#: tuning them, and a tuned constant nobody can re-derive is worse than a
#: default everybody recognises. Stored in `corpus_stats` so the numbers the
#: index was built with are readable from the database.
BM25_K1 = 1.5
BM25_B = 0.75

TS_CONFIG = "rove_english"

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Stopwords. Short list on purpose: "card", "off", "on" are content words in
#: this corpus and a general-purpose stoplist would eat them.
_STOPWORDS = frozenset(
    """a an and are as at be been but by do does for from had has have how i if
    in is it its just like me my no not of on or so that the their then there
    they this to too was what when where which will with you your""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def search_text(text: str, context_header: str = "") -> str:
    """What the lexical half actually indexes and matches against.

    Body plus the §4.2 rolling context header, tokenized and stoplisted here so
    `to_tsvector` sees exactly the tokens BM25 will score. Each surviving token
    is `[a-z0-9]+`, which the `simple` parser maps one-to-one onto a lexeme, so
    the document length below is the same number the ranking uses.
    """
    return " ".join(tokenize(f"{text} {context_header}"))


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------

_lock = threading.Lock()
_conn: Any = None
_conn_failed = False


class StoreUnavailable(RuntimeError):
    """The database is not reachable. Callers fall back; they do not crash."""


def connect(dsn: str | None = None, *, fresh: bool = False) -> Any:
    """A cached autocommit connection, with `vector` registered on it.

    One connection, reused: the agent is single-threaded per turn and a pool
    would be ceremony. The failure is cached too — a machine without the store
    should pay one connection timeout per process, not one per retrieval.
    """
    global _conn, _conn_failed
    with _lock:
        if fresh or dsn is not None:
            return _open(dsn or DSN)
        if _conn is not None and not getattr(_conn, "closed", False):
            return _conn
        if _conn_failed:
            raise StoreUnavailable(f"no connection to {DSN}")
        try:
            _conn = _open(DSN)
        except Exception as exc:  # noqa: BLE001 — any driver error is the same answer
            _conn_failed = True
            raise StoreUnavailable(str(exc)) from exc
        return _conn


def _open(dsn: str) -> Any:
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    try:
        register_vector(conn)
    except Exception:  # noqa: BLE001 — extension missing; migrate() will say so
        pass
    return conn


def reset_connection() -> None:
    """Forget the cached connection *and* the cached failure (tests)."""
    global _conn, _conn_failed
    with _lock:
        if _conn is not None and not getattr(_conn, "closed", False):
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn = None
        _conn_failed = False


def is_available(dsn: str | None = None) -> bool:
    try:
        conn = connect(dsn)
        conn.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return False
    return True


def versions(dsn: str | None = None) -> dict[str, str]:
    """What is actually running — for the README, not for a code path."""
    conn = connect(dsn)
    pg = conn.execute("SELECT version()").fetchone()[0]
    row = conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    return {"postgres": pg, "pgvector": row[0] if row else "(not installed)"}


# --------------------------------------------------------------------------
# Embeddings (docs/07 D-11)
# --------------------------------------------------------------------------

_bedrock: Any = None
_embed_failed = False


def _client() -> Any:
    global _bedrock
    if _bedrock is None:
        import boto3
        from botocore.config import Config

        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=EMBED_REGION,
            config=Config(
                retries={"max_attempts": 4, "mode": "adaptive"},
                connect_timeout=5,
                read_timeout=15,
            ),
        )
    return _bedrock


class EmbeddingUnavailable(RuntimeError):
    """Titan could not be reached. The dense half degrades; BM25 carries."""


#: On-demand Bedrock throttles the whole-corpus embed. Botocore's own adaptive
#: retries are not enough for 122 back-to-back calls, so throttling gets its
#: own backoff ladder here. Anything else fails on the first try: a missing
#: credential is not going to resolve itself in eight seconds.
_THROTTLE_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0)


def embed(text: str, *, model_id: str | None = None) -> list[float]:
    """One Titan Embeddings v2 vector. The dimension is whatever it returns."""
    import time

    model = model_id or EMBED_MODEL_ID
    body = json.dumps({"inputText": text})
    last: Exception | None = None
    for delay in (0.0, *_THROTTLE_BACKOFF):
        if delay:
            time.sleep(delay)
        try:
            response = _client().invoke_model(
                modelId=model,
                body=body,
                accept="application/json",
                contentType="application/json",
            )
            payload = json.loads(response["body"].read())
            vector = payload["embedding"]
        except Exception as exc:  # noqa: BLE001 — credentials, access, network, shape
            last = exc
            if "Throttl" in type(exc).__name__ or "Throttl" in str(exc):
                continue
            raise EmbeddingUnavailable(f"{model}: {exc}") from exc
        if not vector:
            raise EmbeddingUnavailable(f"{model}: empty embedding")
        return [float(x) for x in vector]
    raise EmbeddingUnavailable(f"{model}: {last}")


def embed_query(text: str) -> list[float] | None:
    """A cached query embedding, or `None` once Titan has failed.

    Cached because the §3.5 shortlist retrieves once per entry against the same
    utterance — up to four identical embeddings per turn otherwise. The failure
    is cached too: a run without credentials should not pay a Bedrock timeout
    on every retrieval, it should drop to the lexical half and say so.
    """
    global _embed_failed
    if _embed_failed:
        return None
    text = text.strip()
    if not text:
        return None
    hit = _query_cache.get(text)
    if hit is not None:
        return hit
    try:
        vector = embed(text)
    except EmbeddingUnavailable:
        _embed_failed = True
        return None
    if len(_query_cache) > 512:
        _query_cache.clear()
    _query_cache[text] = vector
    return vector


_query_cache: dict[str, list[float]] = {}


def reset_embedder() -> None:
    global _bedrock, _embed_failed
    _bedrock = None
    _embed_failed = False
    _query_cache.clear()


def embedding_model_info(dsn: str | None = None) -> dict[str, Any] | None:
    """`(model_id, dim, embedded)` as recorded by the migration."""
    conn = connect(dsn)
    row = conn.execute(
        "SELECT model_id, dim, n_embedded, embedded_on FROM embedding_model WHERE id = 1"
    ).fetchone()
    if not row:
        return None
    return {
        "model_id": row[0],
        "dim": row[1],
        "n_embedded": row[2],
        "embedded_on": row[3],
    }


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

#: `%(dim)s` is substituted with the probed embedding dimension — D-11's
#: "the schema must not hard-code it", taken literally.
SCHEMA = """
DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS chunk_lexemes CASCADE;
DROP TABLE IF EXISTS lexeme_df CASCADE;
DROP TABLE IF EXISTS corpus_stats CASCADE;
DROP TABLE IF EXISTS embedding_model CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS source_registry CASCADE;
DROP TEXT SEARCH CONFIGURATION IF EXISTS {ts} CASCADE;
DROP TEXT SEARCH DICTIONARY IF EXISTS rove_en_stem CASCADE;

CREATE TEXT SEARCH DICTIONARY rove_en_stem (TEMPLATE = snowball, Language = english);
CREATE TEXT SEARCH CONFIGURATION {ts} (COPY = simple);
ALTER TEXT SEARCH CONFIGURATION {ts}
    ALTER MAPPING FOR asciiword, word, hword, hword_part, asciihword,
                      hword_asciipart, numword, numhword, hword_numpart
    WITH rove_en_stem;

-- docs/06 §4.4: the source registry, keyed by doc_code. Every chunk joins to
-- it; "no chunk without a registry entry is indexed" is the foreign key below.
CREATE TABLE source_registry (
    doc_code        text PRIMARY KEY,
    title           text NOT NULL,
    tier            int  NOT NULL CHECK (tier = 1),
    source_url      text,
    provenance      text NOT NULL,
    attested_by     text,
    retrieval_date  date NOT NULL,
    source_file     text NOT NULL,
    content_sha256  text NOT NULL,
    speakable_scope text,
    note            text
);

CREATE TABLE chunks (
    chunk_id             text PRIMARY KEY,
    doc_code             text NOT NULL REFERENCES source_registry(doc_code),
    text                 text NOT NULL,
    context_header       text NOT NULL DEFAULT '',
    overlap_sentence     text,
    source_path          text NOT NULL,
    source_url           text,
    retrieval_date       date NOT NULL,
    tier                 int  NOT NULL CHECK (tier = 1),
    page_range           text,
    section              text NOT NULL DEFAULT '',
    section_path         text,
    model_applicability  text[] NOT NULL,
    cross_model          boolean NOT NULL,
    hw_revision_specific boolean NOT NULL,
    firmware_applicability jsonb NOT NULL,
    category             text NOT NULL,
    categories           text[] NOT NULL,
    taxonomy_ids         text[] NOT NULL,
    step_ids             text[] NOT NULL,
    verification_status  text NOT NULL,
    speakable            boolean NOT NULL,
    speakable_reason     text,
    speakable_scope      text,
    destructive          boolean NOT NULL,
    safety_critical      boolean NOT NULL,
    expectation_gap      boolean NOT NULL,
    token_estimate       int,
    provenance           text,
    attested_by          text,
    redactions           jsonb,
    raw                  jsonb NOT NULL,
    search_text          text NOT NULL,
    doc_len              int  NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('{ts}', search_text)) STORED,

    -- docs/06 §4.5 item 3, as a constraint rather than a filter: an
    -- UNVERIFIED or REJECTED entry cannot be stored as speakable at all.
    CONSTRAINT speakable_requires_verified
        CHECK (NOT speakable OR verification_status IN ('VERIFIED', 'CORRECTED'))
);

CREATE INDEX chunks_tsv_idx     ON chunks USING gin (tsv);
CREATE INDEX chunks_models_idx  ON chunks USING gin (model_applicability);
CREATE INDEX chunks_speakable_idx ON chunks (speakable);

-- BM25 needs per-term frequencies and a document length. The lexemes are
-- unnested straight out of the generated tsvector, so the term vocabulary the
-- ranker sees is exactly the one the GIN index holds.
CREATE TABLE chunk_lexemes (
    chunk_id text NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    lexeme   text NOT NULL,
    tf       int  NOT NULL,
    PRIMARY KEY (chunk_id, lexeme)
);
CREATE INDEX chunk_lexemes_lexeme_idx ON chunk_lexemes (lexeme);

-- Document frequency over the *whole speakable corpus*, not over the
-- post-filter subset: idf is a property of the corpus, and recomputing it per
-- query over the handful of chunks that survive a UNKNOWN-model filter
-- produces unstable weights for no gain.
CREATE TABLE lexeme_df (
    lexeme text PRIMARY KEY,
    df     int  NOT NULL,
    idf    double precision NOT NULL
);

CREATE TABLE corpus_stats (
    id       int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    n_docs   int NOT NULL,
    avg_len  double precision NOT NULL,
    bm25_k1  double precision NOT NULL,
    bm25_b   double precision NOT NULL,
    built_on timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE embedding_model (
    id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    model_id    text NOT NULL,
    dim         int  NOT NULL,
    n_embedded  int  NOT NULL,
    embedded_on timestamptz NOT NULL DEFAULT now()
);

-- Speakable chunks only: the dense half has nothing else to find.
CREATE TABLE chunk_embeddings (
    chunk_id  text PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    model_id  text NOT NULL,
    embedding vector(%(dim)s) NOT NULL
);
"""


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def migrate(
    *,
    dsn: str | None = None,
    chunks_path: Path | None = None,
    sources_path: Path | None = None,
    embed_chunks: bool = True,
    progress: bool = True,
) -> dict[str, Any]:
    """Build the store from the on-disk corpus. Destructive and idempotent.

    Order matters: the dimension is probed *before* the schema is created,
    because the schema needs it.
    """
    from psycopg.types.json import Jsonb

    chunks_file = chunks_path or CHUNKS_PATH
    sources_file = sources_path or SOURCES_PATH
    rows = _read_jsonl(chunks_file)
    registry = json.loads(sources_file.read_text(encoding="utf-8"))

    dim = 0
    model_id = EMBED_MODEL_ID
    if embed_chunks:
        probe = embed("dimension probe")
        dim = len(probe)
        if progress:
            print(f"  embedding model {model_id}: dimension {dim} (probed, not assumed)")
    else:
        dim = 1  # schema still needs a width; nothing will be written into it

    conn = connect(dsn)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(SCHEMA.format(ts=TS_CONFIG) % {"dim": dim})

    for src in registry["sources"]:
        conn.execute(
            """INSERT INTO source_registry (doc_code, title, tier, source_url,
                   provenance, attested_by, retrieval_date, source_file,
                   content_sha256, speakable_scope, note)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                src["doc_code"],
                src["title"],
                int(src["tier"]),
                src.get("source_url"),
                src["provenance"],
                src.get("attested_by"),
                src["retrieval_date"],
                src["file"],
                src["content_sha256"],
                src.get("speakable_scope"),
                src.get("note"),
            ),
        )

    for row in rows:
        body = row["text"]
        header = row.get("context_header", "") or ""
        indexed = search_text(body, header)
        conn.execute(
            """INSERT INTO chunks (chunk_id, doc_code, text, context_header,
                   overlap_sentence, source_path, source_url, retrieval_date,
                   tier, page_range, section, section_path, model_applicability,
                   cross_model, hw_revision_specific, firmware_applicability,
                   category, categories, taxonomy_ids, step_ids,
                   verification_status, speakable, speakable_reason,
                   speakable_scope, destructive, safety_critical,
                   expectation_gap, token_estimate, provenance, attested_by,
                   redactions, raw, search_text, doc_len)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["chunk_id"],
                row["doc_code"],
                body,
                header,
                row.get("overlap_sentence"),
                row["source_path"],
                row.get("source_url"),
                row["retrieval_date"],
                int(row["tier"]),
                row.get("page_range"),
                row.get("section", "") or "",
                row.get("section_path"),
                list(row.get("model_applicability", [])),
                bool(row.get("cross_model", False)),
                bool(row.get("hw_revision_specific", False)),
                Jsonb(row.get("firmware_applicability", {})),
                row.get("category", "NONE"),
                list(row.get("categories", [])),
                list(row.get("taxonomy_ids", [])),
                list(row.get("step_ids", [])),
                row.get("verification_status", "UNVERIFIED"),
                bool(row.get("speakable", False)),
                row.get("speakable_reason"),
                row.get("speakable_scope"),
                bool(row.get("destructive", False)),
                bool(row.get("safety_critical", False)),
                bool(row.get("expectation_gap", False)),
                row.get("token_estimate"),
                row.get("provenance"),
                row.get("attested_by"),
                Jsonb(row.get("redactions", [])),
                Jsonb(row),
                indexed,
                len(tokenize(f"{body} {header}")),
            ),
        )

    conn.execute(
        """INSERT INTO chunk_lexemes (chunk_id, lexeme, tf)
           SELECT c.chunk_id, u.lexeme, COALESCE(array_length(u.positions, 1), 1)
           FROM chunks c, unnest(c.tsv) u"""
    )
    stats = conn.execute(
        "SELECT count(*), COALESCE(avg(doc_len), 0) FROM chunks WHERE speakable"
    ).fetchone()
    n_docs, avg_len = int(stats[0]) or 1, float(stats[1]) or 1.0
    conn.execute(
        """INSERT INTO lexeme_df (lexeme, df, idf)
           SELECT cl.lexeme, count(*)::int,
                  ln(1 + (%s - count(*) + 0.5) / (count(*) + 0.5))
           FROM chunk_lexemes cl JOIN chunks c USING (chunk_id)
           WHERE c.speakable GROUP BY cl.lexeme""",
        (n_docs,),
    )
    conn.execute(
        "INSERT INTO corpus_stats (n_docs, avg_len, bm25_k1, bm25_b) VALUES (%s,%s,%s,%s)",
        (n_docs, avg_len, BM25_K1, BM25_B),
    )

    n_embedded = 0
    if embed_chunks:
        import time

        speakable = [r for r in rows if r.get("speakable")]
        for i, row in enumerate(speakable, start=1):
            if i > 1:
                time.sleep(0.2)  # stay under the on-demand rate for 122 calls
            header = row.get("context_header", "") or ""
            vector = embed(f"{header}\n{row['text']}".strip())
            if len(vector) != dim:
                raise RuntimeError(
                    f"{row['chunk_id']}: dimension {len(vector)} != probed {dim}"
                )
            conn.execute(
                "INSERT INTO chunk_embeddings (chunk_id, model_id, embedding) "
                "VALUES (%s, %s, %s)",
                (row["chunk_id"], model_id, _vector_literal(vector)),
            )
            n_embedded += 1
            if progress and i % 25 == 0:
                print(f"  embedded {i}/{len(speakable)}")
        conn.execute(
            "INSERT INTO embedding_model (model_id, dim, n_embedded) VALUES (%s,%s,%s)",
            (model_id, dim, n_embedded),
        )
        # An index is not required at 122 rows — an exact scan is faster than
        # an approximate one here, and exact is also what the eval measures.
        # The index exists so the shape is the production shape.
        conn.execute(
            "CREATE INDEX chunk_embeddings_cos_idx ON chunk_embeddings "
            "USING hnsw (embedding vector_cosine_ops)"
        )

    return {
        "chunks": len(rows),
        "speakable": sum(1 for r in rows if r.get("speakable")),
        "sources": len(registry["sources"]),
        "embedded": n_embedded,
        "dim": dim if embed_chunks else None,
        "model_id": model_id,
        "n_docs": n_docs,
        "avg_len": avg_len,
    }


def _vector_literal(vector: Sequence[float]) -> str:
    """pgvector accepts its own text literal, which avoids needing the adapter
    registered on whichever connection happens to be in hand."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


# --------------------------------------------------------------------------
# Reads: the two halves of the §4.6 hybrid search
# --------------------------------------------------------------------------

CHUNK_COLUMNS = """chunk_id, text, doc_code, source_path, source_url,
    retrieval_date::text, tier, page_range, section, context_header,
    model_applicability, cross_model, category, categories, taxonomy_ids,
    step_ids, verification_status, speakable, destructive, safety_critical,
    raw"""

_CHUNK_FIELDS = (
    "chunk_id text doc_code source_path source_url retrieval_date tier page_range "
    "section context_header model_applicability cross_model category categories "
    "taxonomy_ids step_ids verification_status speakable destructive safety_critical raw"
).split()


def fetch_chunk_rows(dsn: str | None = None) -> list[dict[str, Any]]:
    """Every chunk, as dicts. Ordered by `chunk_id` so a corpus-wide iteration
    is reproducible across processes."""
    conn = connect(dsn)
    rows = conn.execute(f"SELECT {CHUNK_COLUMNS} FROM chunks ORDER BY chunk_id").fetchall()
    return [dict(zip(_CHUNK_FIELDS, row)) for row in rows]


def model_predicate(
    *, confidence: str, wanted: str | None, live: Sequence[str]
) -> tuple[str, dict[str, Any]]:
    """§4.6's three model branches as a SQL predicate.

    This is the half of the safety control that has to happen *before* search:
    it goes into the `WHERE` of the pool query, so a wrong-model chunk is never
    scored, never ranked and never available to be returned — not filtered out
    afterwards, where a bug could skip the filter.
    """
    if confidence == "CONFIRMED" and wanted and wanted != "unknown":
        return "(%(wanted)s = ANY(model_applicability) OR cross_model)", {"wanted": wanted}
    if confidence == "PROBABLE":
        return "(cross_model OR model_applicability @> %(live)s)", {"live": list(live)}
    return "cross_model", {}


def pool_ids(
    *,
    confidence: str,
    wanted: str | None = None,
    live: Sequence[str] = (),
    dsn: str | None = None,
) -> list[str]:
    """The §4.5 + §4.6 filter, in SQL, before anything is searched."""
    predicate, params = model_predicate(confidence=confidence, wanted=wanted, live=live)
    conn = connect(dsn)
    rows = conn.execute(
        f"SELECT chunk_id FROM chunks WHERE speakable AND tier = 1 AND {predicate} "
        "ORDER BY chunk_id",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def query_lexemes(query: str, dsn: str | None = None) -> list[str]:
    """The query's lexemes, produced by the same configuration as the index."""
    text = " ".join(tokenize(query))
    if not text:
        return []
    conn = connect(dsn)
    rows = conn.execute(
        f"SELECT lexeme FROM unnest(to_tsvector('{TS_CONFIG}', %s))", (text,)
    ).fetchall()
    return [r[0] for r in rows]


BM25_SQL = """
SELECT cl.chunk_id,
       SUM(d.idf * (cl.tf * (s.bm25_k1 + 1))
           / (cl.tf + s.bm25_k1 * (1 - s.bm25_b + s.bm25_b * c.doc_len / s.avg_len)))
FROM chunk_lexemes cl
JOIN chunks c USING (chunk_id)
JOIN lexeme_df d USING (lexeme)
CROSS JOIN corpus_stats s
WHERE cl.chunk_id = ANY(%(ids)s) AND cl.lexeme = ANY(%(lexemes)s)
GROUP BY cl.chunk_id
"""


def bm25_scores(
    lexemes: Sequence[str], ids: Sequence[str], dsn: str | None = None
) -> dict[str, float]:
    """Okapi BM25 over the `tsvector` lexemes, computed in Postgres.

    `ts_rank_cd` is deliberately not used: it is a different ranker with
    different semantics, and §4.6 says BM25. The term frequencies come from the
    generated `tsv`, the document frequencies from `lexeme_df`, and `k1`/`b`
    from `corpus_stats` — so the formula and its constants are both inspectable
    in the database rather than only in this file.
    """
    if not lexemes or not ids:
        return {}
    conn = connect(dsn)
    rows = conn.execute(
        BM25_SQL, {"ids": list(ids), "lexemes": list(lexemes)}
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def dense_scores(
    vector: Sequence[float], ids: Sequence[str], dsn: str | None = None
) -> dict[str, float]:
    """Cosine similarity from pgvector: `1 - (embedding <=> query)`."""
    if not ids or not vector:
        return {}
    conn = connect(dsn)
    rows = conn.execute(
        "SELECT chunk_id, 1 - (embedding <=> %(q)s::vector) "
        "FROM chunk_embeddings WHERE chunk_id = ANY(%(ids)s)",
        {"q": _vector_literal(vector), "ids": list(ids)},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def counts(dsn: str | None = None) -> dict[str, int]:
    conn = connect(dsn)
    out = {}
    for name in ("source_registry", "chunks", "chunk_embeddings", "chunk_lexemes"):
        out[name] = int(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
    out["speakable"] = int(
        conn.execute("SELECT count(*) FROM chunks WHERE speakable").fetchone()[0]
    )
    return out


# --------------------------------------------------------------------------


def _main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Rove chunk store (docs/06 §8.5)")
    parser.add_argument("--migrate", action="store_true", help="rebuild from the corpus")
    parser.add_argument(
        "--no-embed", action="store_true", help="schema + BM25 only, no Bedrock calls"
    )
    parser.add_argument("--verify", action="store_true", help="report what is in the store")
    args = parser.parse_args(list(argv) if argv is not None else None)

    info = versions()
    print(f"postgres : {info['postgres'].split(' on ')[0]}")
    print(f"pgvector : {info['pgvector']}")

    if args.migrate:
        print(f"migrating from {CHUNKS_PATH}")
        summary = migrate(embed_chunks=not args.no_embed)
        print(
            f"  {summary['sources']} sources, {summary['chunks']} chunks "
            f"({summary['speakable']} speakable), {summary['embedded']} embedded "
            f"at dim {summary['dim']}"
        )
        print(f"  BM25 corpus: n_docs={summary['n_docs']} avg_len={summary['avg_len']:.1f}")

    if args.verify or args.migrate:
        print(f"counts   : {counts()}")
        print(f"embedding: {embedding_model_info()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
