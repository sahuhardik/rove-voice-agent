"""Hybrid retrieval over the Postgres + pgvector store (`docs/06` §4.6).

§4.6 in five lines, and this module is those five lines:

```
model_filter     = CONFIRMED → this model | PROBABLE → every live candidate | UNKNOWN → cross-model
category_filter  = triaged category ∪ cross-cutting
status_filter    = speakable == true          (tier is implicit — separate store)

hits = hybrid_search(query, filters = ALL of the above, k = 8)
     = 0.5 · BM25(query + taxonomy_id + step vocabulary)
     + 0.5 · dense(query)
hits = rerank(hits)[:3]
```

**Filter first, then search. Never semantic-only.** That ordering is a safety
control, not relevance tuning. The card ceiling is 512 GB on R2-4K / PRO / R3
and up to 1 TB on DUAL / DUAL PRO (`docs/05` SD-04); an unfiltered search for
"how big a card can I use" returns both, and either answer is wrong for half
the line. Same for the reset button (the R3 has none), the Wi-Fi control, the
band, and computer connectivity (the DUAL PRO has none). So the model filter is
not applied to a result list — it is the `WHERE` clause of the pool query in
`agent/store.py`, and nothing outside that pool is ever scored, ranked or
returned. A filter applied after search is a filter that a ranking bug can
skip; this one cannot be skipped, because the rows never exist.

The filter chain, in order:

1. **Tier 1 and speakable only.** §4.5's physical separation is a `CHECK
   (tier = 1)` in the schema plus a second `CHECK` forbidding `speakable` on an
   `UNVERIFIED` or `REJECTED` entry — so the four unevidenced entries (`FW-03`,
   `APP-02`, `APP-04`, `PWR-02`) and the rejected premise of `SD-02` have no
   speakable chunk that could be returned, and could not be given one without
   the database refusing the row.
2. **Model**, the three §4.6 branches. `UNKNOWN` is expensive on purpose: of
   161 chunks, 16 are cross-model. At `UNKNOWN` there is very little the agent
   is entitled to assert, and the honest consequence is that it asks rather
   than tells.
3. **Category / taxonomy**, as a soft filter: applied when it leaves something
   to search, dropped when it does not, so a thin category never returns an
   empty hand where a cross-cutting chunk would have helped.

Then the two halves, both computed over that pool and nothing else:

* **BM25** over the `tsvector` lexemes, in Postgres (`store.bm25_scores`). Not
  `ts_rank_cd` — §4.6 says BM25, and `ts_rank_cd` is a different ranker.
* **Dense**, cosine over pgvector (`1 - (embedding <=> query)`), with Titan
  Embeddings v2 (`docs/07` D-11) on both sides.

Each half is min-max normalised **over the surviving pool** before the 0.5/0.5
sum, because a raw BM25 score and a cosine similarity are not on the same
scale and adding them unscaled would make the weights decorative. Normalising
over the pool rather than over a global constant keeps the weighting meaningful
when a `CONFIRMED` filter leaves nine chunks.

**What the reranker is, stated plainly:** a metadata reranker over the k = 8 —
taxonomy-id match, category match, safety-critical — not a cross-encoder. A
cross-encoder would need a model `docs/06` §0 has not cleared (C-2) and §8.3
has not recorded, so it is deferred rather than improvised. The boosts are the
same three the lexical-only milestone used, kept because they were reviewed,
and applied at the rerank stage because that is where §4.6 puts them.

**Degradation.** The store is the source of record. If Postgres is unreachable
the module falls back to the on-disk `chunks.jsonl` with an in-process BM25 and
no dense half; if Titan is unreachable the dense half drops and BM25 carries
alone. Both are visible in the funnel — `store jsonl` or `dense scored 0` — so
a run can never quietly report hybrid numbers it did not produce.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from agent import store
from agent.state import CONFIRMED, PROBABLE, UNKNOWN
from ingest.metadata import ALL_MODELS

#: Index-time and query-time tokenization are the same function on purpose;
#: it lives with the indexer in `store.py`. Re-exported because it was part of
#: this module's surface before the store existed.
from agent.store import BM25_B, BM25_K1, tokenize  # noqa: F401

CHUNKS_PATH = store.CHUNKS_PATH

#: §4.6: `hybrid_search(..., k = 8)` then `rerank(hits)[:3]`.
HYBRID_K = 8

#: §4.6's weights. Equal halves, as specified.
BM25_WEIGHT = 0.5
DENSE_WEIGHT = 0.5

#: Multiplicative boosts applied by the reranker. Kept small and explicit so a
#: surprising ranking is readable from the trace (`docs/06` §7.5).
TAXONOMY_BOOST = 1.6
CATEGORY_BOOST = 1.25
SAFETY_CRITICAL_BOOST = 1.1


@dataclass(frozen=True)
class Chunk:
    """One chunk, with the fields retrieval actually reads."""

    chunk_id: str
    text: str
    doc_code: str
    source_path: str
    source_url: str | None
    retrieval_date: str
    tier: int
    page_range: str | None
    section: str
    context_header: str
    model_applicability: tuple[str, ...]
    cross_model: bool
    category: str
    categories: tuple[str, ...]
    taxonomy_ids: tuple[str, ...]
    step_ids: tuple[str, ...]
    verification_status: str
    speakable: bool
    destructive: bool
    safety_critical: bool
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def citation(self) -> str:
        """How a chunk is named in a trace or a handoff: id, doc, pages."""
        page = f" {self.page_range}" if self.page_range else ""
        return f"{self.chunk_id} ({self.doc_code}{page})"


def _as_chunk(row: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        text=row["text"],
        doc_code=row["doc_code"],
        source_path=row["source_path"],
        source_url=row.get("source_url"),
        retrieval_date=str(row.get("retrieval_date", "")),
        tier=int(row["tier"]),
        page_range=row.get("page_range"),
        section=row.get("section", "") or "",
        context_header=row.get("context_header", "") or "",
        model_applicability=tuple(row.get("model_applicability") or ()),
        cross_model=bool(row.get("cross_model", False)),
        category=row.get("category", "NONE"),
        categories=tuple(row.get("categories") or ()),
        taxonomy_ids=tuple(row.get("taxonomy_ids") or ()),
        step_ids=tuple(row.get("step_ids") or ()),
        verification_status=row.get("verification_status", "UNVERIFIED"),
        speakable=bool(row.get("speakable", False)),
        destructive=bool(row.get("destructive", False)),
        safety_critical=bool(row.get("safety_critical", False)),
        raw=row.get("raw") if isinstance(row.get("raw"), dict) else row,
    )


def _check_tier(chunks: Sequence[Chunk], where: str) -> None:
    """§4.5 gets its strength from Tier 2/3 being physically absent from this
    path. The assertion is deliberately fatal."""
    for chunk in chunks:
        if chunk.tier != 1:
            raise ValueError(
                f"{where}: {chunk.chunk_id} is tier {chunk.tier}; only Tier 1 may "
                "reach the speakable path (06 §4.5)"
            )


# --------------------------------------------------------------------------
# Model filtering (docs/06 §4.6)
# --------------------------------------------------------------------------


def _with_revision(model: str, hw_revision: str) -> str:
    if model != "R2-4K":
        return model
    if hw_revision == "mini_usb":
        return "R2-4K_MINI_USB"
    if hw_revision == "usb_c":
        return "R2-4K_USB_C"
    return model


def model_filter(
    chunks: Sequence[Chunk],
    *,
    confidence: str,
    model: str = "unknown",
    hw_revision: str = "unknown",
    candidates: Sequence[str] = (),
) -> list[Chunk]:
    """The §4.6 model gate, as three distinct branches.

    `hw_revision` participates only through the model vocabulary, which already
    encodes the split (`R2-4K_MINI_USB` vs `R2-4K_USB_C`) — a revision is not a
    separate facet to intersect, it is part of the model id.

    This is the in-process twin of `store.model_predicate`. The two are held to
    the same answer by `agent/test_retrieval.py`, which runs every branch
    through both and asserts the surviving sets are identical — the one place
    where a SQL rewrite could quietly diverge from the rule.
    """
    if confidence == CONFIRMED and model != "unknown":
        wanted = _with_revision(model, hw_revision)
        return [c for c in chunks if wanted in c.model_applicability or c.cross_model]
    if confidence == PROBABLE:
        live = tuple(candidates) or tuple(ALL_MODELS)
        return [
            c
            for c in chunks
            if c.cross_model or all(m in c.model_applicability for m in live)
        ]
    # UNKNOWN: cross-model only. model_applicability ⊇ all 6 documented models.
    return [c for c in chunks if c.cross_model]


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


class Backend(Protocol):
    """What retrieval needs from a store. Two implementations ship; the tests
    add a third, so the fusion and the rerank are exercised without a network."""

    name: str

    def chunks(self) -> tuple[Chunk, ...]: ...

    def pool(
        self,
        *,
        confidence: str,
        model: str,
        hw_revision: str,
        candidates: Sequence[str],
    ) -> list[Chunk]: ...

    def lexical(self, query: str, ids: Sequence[str]) -> dict[str, float]: ...

    def dense(self, query: str, ids: Sequence[str]) -> dict[str, float] | None: ...


class PostgresBackend:
    """`docs/06` §8.5 option B. The filter is SQL; both halves are SQL."""

    name = "postgres"

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    @property
    def _cached(self) -> tuple[Chunk, ...]:
        return _postgres_chunks(self.dsn)

    def chunks(self) -> tuple[Chunk, ...]:
        return self._cached

    def pool(
        self,
        *,
        confidence: str,
        model: str,
        hw_revision: str,
        candidates: Sequence[str],
    ) -> list[Chunk]:
        wanted = _with_revision(model, hw_revision) if model != "unknown" else None
        live = tuple(candidates) or tuple(ALL_MODELS)
        ids = store.pool_ids(
            confidence=confidence, wanted=wanted, live=live, dsn=self.dsn
        )
        index = {c.chunk_id: c for c in self._cached}
        return [index[i] for i in ids if i in index]

    def lexical(self, query: str, ids: Sequence[str]) -> dict[str, float]:
        lexemes = store.query_lexemes(query, dsn=self.dsn)
        return store.bm25_scores(lexemes, ids, dsn=self.dsn)

    def dense(self, query: str, ids: Sequence[str]) -> dict[str, float] | None:
        vector = store.embed_query(query)
        if vector is None:
            return None
        return store.dense_scores(vector, ids, dsn=self.dsn)


class JsonlBackend:
    """The fallback: `chunks.jsonl`, stdlib BM25, no dense half.

    This exists so the unit suite and the `--no-llm` path still run on a
    machine with no database — and so a store outage degrades the agent to the
    lexical half rather than to nothing. It is not the architecture; §8.5
    chose Postgres, and `retrieve` says which one it used in the funnel.
    """

    name = "jsonl"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path else str(CHUNKS_PATH)

    def chunks(self) -> tuple[Chunk, ...]:
        return _jsonl_chunks(self.path)

    def pool(
        self,
        *,
        confidence: str,
        model: str,
        hw_revision: str,
        candidates: Sequence[str],
    ) -> list[Chunk]:
        speakable = [c for c in self.chunks() if c.speakable]
        return model_filter(
            speakable,
            confidence=confidence,
            model=model,
            hw_revision=hw_revision,
            candidates=candidates,
        )

    def lexical(self, query: str, ids: Sequence[str]) -> dict[str, float]:
        corpus = _jsonl_corpus(self.path)
        index = {c.chunk_id: c for c in self.chunks()}
        tokens = tokenize(query)
        out: dict[str, float] = {}
        for chunk_id in ids:
            chunk = index.get(chunk_id)
            if chunk is None:
                continue
            score = _bm25(tokens, chunk, corpus)
            if score:
                out[chunk_id] = score
        return out

    def dense(self, query: str, ids: Sequence[str]) -> dict[str, float] | None:
        return None


@lru_cache(maxsize=2)
def _postgres_chunks(dsn: str | None) -> tuple[Chunk, ...]:
    chunks = tuple(_as_chunk(row) for row in store.fetch_chunk_rows(dsn))
    _check_tier(chunks, "postgres chunks")
    return chunks


@lru_cache(maxsize=4)
def _jsonl_chunks(path: str) -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                chunks.append(_as_chunk(json.loads(line)))
    _check_tier(chunks, path)
    return tuple(chunks)


@dataclass(frozen=True)
class Corpus:
    """Document-frequency statistics over the whole speakable corpus.

    Computed over everything speakable, not over the post-filter subset: idf is
    a property of the corpus, and recomputing it per query over the chunks that
    survive a filter produces unstable weights for no gain. The *filter*
    decides what may be returned; the statistics decide how to rank it. The
    Postgres half does the same thing in `lexeme_df`.
    """

    doc_freq: dict[str, int]
    n_docs: int
    avg_len: float


@lru_cache(maxsize=4)
def _jsonl_corpus(path: str) -> Corpus:
    doc_freq: dict[str, int] = {}
    total_len = 0
    speakable = [c for c in _jsonl_chunks(path) if c.speakable]
    for chunk in speakable:
        tokens = tokenize(chunk.text + " " + chunk.context_header)
        total_len += len(tokens)
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1
    n = len(speakable) or 1
    return Corpus(doc_freq=doc_freq, n_docs=n, avg_len=(total_len / n) or 1.0)


def _bm25(query_tokens: Sequence[str], chunk: Chunk, corpus: Corpus) -> float:
    tokens = tokenize(chunk.text + " " + chunk.context_header)
    if not tokens:
        return 0.0
    length = len(tokens)
    freqs: dict[str, int] = {}
    for token in tokens:
        freqs[token] = freqs.get(token, 0) + 1
    score = 0.0
    for term in query_tokens:
        tf = freqs.get(term, 0)
        if not tf:
            continue
        df = corpus.doc_freq.get(term, 0)
        idf = math.log(1 + (corpus.n_docs - df + 0.5) / (df + 0.5))
        denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * length / corpus.avg_len)
        score += idf * (tf * (BM25_K1 + 1)) / denom
    return score


_default_backend: Backend | None = None


def default_backend() -> Backend:
    """Postgres if it answers, the file if it does not. Decided once."""
    global _default_backend
    if _default_backend is None:
        _default_backend = (
            PostgresBackend() if store.is_available() else JsonlBackend()
        )
    return _default_backend


def reset_backend() -> None:
    """Drop the cached backend and its caches (tests, and after a migration)."""
    global _default_backend
    _default_backend = None
    _postgres_chunks.cache_clear()
    _jsonl_chunks.cache_clear()
    _jsonl_corpus.cache_clear()
    store.reset_connection()


def _backend_for(path: str | None) -> Backend:
    if path is None or str(Path(path)) == str(CHUNKS_PATH):
        return default_backend()
    return JsonlBackend(path)


# --------------------------------------------------------------------------
# Corpus access (unchanged surface)
# --------------------------------------------------------------------------


def load_chunks(path: str | None = None) -> tuple[Chunk, ...]:
    """Every chunk, Tier 1 only — anything else is a bug and raises."""
    return _backend_for(path).chunks()


def speakable_chunks(path: str | None = None) -> tuple[Chunk, ...]:
    return tuple(c for c in load_chunks(path) if c.speakable)


def chunks_by_id(ids: Iterable[str], path: str | None = None) -> list[Chunk]:
    index = {c.chunk_id: c for c in load_chunks(path)}
    return [index[i] for i in ids if i in index]


# --------------------------------------------------------------------------
# Fusion and rerank
# --------------------------------------------------------------------------


def normalize(scores: dict[str, float], ids: Sequence[str]) -> dict[str, float]:
    """Min-max over the surviving pool, so the 0.5/0.5 weights mean something.

    A missing id scores 0: BM25 omits a chunk that shares no lexeme with the
    query, and that is a real zero rather than an unknown. If every chunk ties,
    the half carries no information — all 1.0 if the tie is above zero, all 0.0
    if the whole half is empty — and the other half decides the ranking.
    """
    if not ids:
        return {}
    values = [scores.get(i, 0.0) for i in ids]
    lo, hi = min(values), max(values)
    if hi <= lo:
        return {i: (0.0 if hi <= 0.0 else 1.0) for i in ids}
    span = hi - lo
    return {i: (scores.get(i, 0.0) - lo) / span for i in ids}


@dataclass
class Hit:
    chunk: Chunk
    score: float
    why: str
    bm25: float = 0.0
    dense: float = 0.0

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id


@dataclass
class RetrievalResult:
    hits: list[Hit] = field(default_factory=list)
    #: Every stage with the count that survived it — the §7.5 trace
    #: requirement applied to retrieval rather than to the policy filter.
    funnel: list[tuple[str, int]] = field(default_factory=list)

    @property
    def chunk_ids(self) -> list[str]:
        return [h.chunk_id for h in self.hits]

    @property
    def step_ids(self) -> list[str]:
        """Steps named by the retrieved chunks.

        `docs/06` §3.5 opens with `candidates = steps_for(taxonomy_id) ∪
        steps_from(cleared_chunks)`. This is the second half of that union, and
        every one of these still goes through the full filter chain.
        """
        out: list[str] = []
        for hit in self.hits:
            for step_id in hit.chunk.step_ids:
                if step_id not in out:
                    out.append(step_id)
        return out


def rerank(
    hits: Sequence[Hit], *, category: str | None = None, taxonomy_id: str | None = None
) -> list[Hit]:
    """§4.6's `rerank(hits)` — a metadata reranker, not a cross-encoder.

    Three signals the fused score cannot see: the chunk was written for exactly
    this taxonomy entry, it is in the triaged category, or it is one of the
    safety-critical procedures (`FW-01`, `FW-02`, `REC-01`) where surfacing the
    whole thing matters more than a fractional relevance gain. Ties break on
    `chunk_id`, so the order is reproducible run to run.
    """
    out: list[Hit] = []
    for hit in hits:
        score = hit.score
        reasons = [hit.why]
        if taxonomy_id and taxonomy_id in hit.chunk.taxonomy_ids:
            score *= TAXONOMY_BOOST
            reasons.append(f"taxonomy {taxonomy_id}")
        if category and category in hit.chunk.categories:
            score *= CATEGORY_BOOST
            reasons.append(f"category {category}")
        if hit.chunk.safety_critical:
            score *= SAFETY_CRITICAL_BOOST
            reasons.append("safety-critical")
        out.append(
            Hit(
                chunk=hit.chunk,
                score=score,
                why="; ".join(r for r in reasons if r),
                bm25=hit.bm25,
                dense=hit.dense,
            )
        )
    out.sort(key=lambda h: (-h.score, h.chunk_id))
    return out


# --------------------------------------------------------------------------
# The retrieval entry point
# --------------------------------------------------------------------------


def retrieve(
    query: str,
    *,
    confidence: str = UNKNOWN,
    model: str = "unknown",
    hw_revision: str = "unknown",
    candidates: Sequence[str] = (),
    category: str | None = None,
    taxonomy_id: str | None = None,
    k: int = 3,
    path: str | None = None,
    backend: Backend | None = None,
    hybrid_k: int = HYBRID_K,
) -> RetrievalResult:
    """Filter, then search, then rerank, then take the top `k` (§4.6).

    `k` is the post-rerank cut and defaults to §4.6's 3; `hybrid_k` is §4.6's
    `k = 8`, the candidate set the reranker sees.
    """
    result = RetrievalResult()
    chosen = backend or _backend_for(path)

    pool = chosen.pool(
        confidence=confidence,
        model=model,
        hw_revision=hw_revision,
        candidates=candidates,
    )
    result.funnel.append((f"store {chosen.name}", len(chosen.chunks())))
    result.funnel.append((f"tier-1 speakable + model ({confidence})", len(pool)))

    # Category is a soft filter: applied only when it leaves something to
    # search. A hard category filter on a thin category returns nothing, and
    # nothing retrieved means nothing citable, which means the output guard
    # drops a claim the corpus could in fact have supported.
    if category:
        narrowed = [c for c in pool if category in c.categories or c.category == category]
        if narrowed:
            pool = narrowed
        result.funnel.append((f"category ({category})", len(pool)))

    if not pool:
        return result

    ids = [c.chunk_id for c in pool]
    index = {c.chunk_id: c for c in pool}

    # BM25 gets §4.6's expanded input: query + taxonomy id + step vocabulary.
    # The dense half gets the caller's own words — §4.6 says `dense(query)`,
    # and the expansion terms are manual-side vocabulary that would pull the
    # embedding toward the manual's phrasing rather than the caller's.
    lexical_raw = chosen.lexical(_expand_query(query, category, taxonomy_id), ids)
    dense_raw = chosen.dense(query, ids)
    result.funnel.append(("bm25 scored", len(lexical_raw)))
    result.funnel.append(("dense scored", len(dense_raw or {})))

    lexical = normalize(lexical_raw, ids)
    if dense_raw:
        dense = normalize(dense_raw, ids)
        weights = (BM25_WEIGHT, DENSE_WEIGHT)
    else:
        # No dense half available: BM25 carries alone rather than being halved
        # against a column of zeroes, which would only rescale every score.
        dense = {i: 0.0 for i in ids}
        weights = (1.0, 0.0)

    fused: list[Hit] = []
    for chunk_id in ids:
        bm = lexical.get(chunk_id, 0.0)
        dn = dense.get(chunk_id, 0.0)
        score = weights[0] * bm + weights[1] * dn
        if score <= 0:
            continue
        fused.append(
            Hit(
                chunk=index[chunk_id],
                score=score,
                why=f"bm25={bm:.2f}·{weights[0]:g} dense={dn:.2f}·{weights[1]:g}",
                bm25=lexical_raw.get(chunk_id, 0.0),
                dense=(dense_raw or {}).get(chunk_id, 0.0),
            )
        )

    fused.sort(key=lambda h: (-h.score, h.chunk_id))
    candidates_8 = fused[:hybrid_k]
    result.funnel.append((f"hybrid k={hybrid_k}", len(candidates_8)))

    reranked = rerank(candidates_8, category=category, taxonomy_id=taxonomy_id)
    result.hits = reranked[:k]
    result.funnel.append((f"rerank top-{k}", len(result.hits)))
    return result


def _expand_query(query: str, category: str | None, taxonomy_id: str | None) -> str:
    """Query + taxonomy id + step vocabulary (`docs/06` §4.6's BM25 input)."""
    parts = [query]
    if taxonomy_id:
        parts.append(taxonomy_id)
        parts.append(_TAXONOMY_VOCABULARY.get(taxonomy_id, ""))
    if category:
        parts.append(_CATEGORY_VOCABULARY.get(category, ""))
    return " ".join(p for p in parts if p)


#: A handful of words per category that the caller is unlikely to say but the
#: manual certainly does. This is the cheap half of what a dense retriever
#: does for free, and it is written out rather than embedded so that a
#: surprising lexical hit can be traced to a word somebody chose. It stays now
#: that the dense half exists: it feeds BM25 only, where it is a precision aid
#: on a corpus small enough to enumerate.
_CATEGORY_VOCABULARY: dict[str, str] = {
    "WIFI": "wifi wi-fi network ssid connect connection password hotspot band ghz",
    "FW": "firmware update upgrade version flash led restart",
    "APP": "app application phone smartphone connect permission account pair",
    "REC": "record recording loop video clip event lock parking footage",
    "SD": "memory card microsd format storage capacity class speed file",
    "PWR": "power supply cable socket battery supercapacitor voltage hardwire temperature",
    "VID": "video image lens resolution exposure wdr audio microphone timestamp",
}

_TAXONOMY_VOCABULARY: dict[str, str] = {
    "WIFI-01": "no internet prompt keep trying always connect cellular",
    "WIFI-02": "network not showing emergency lock wifi on 2.4 5 ghz band",
    "WIFI-03": "password wrong default 12345678 forget network",
    "WIFI-04": "drops disconnect range metres feet always on",
    "WIFI-05": "slow download stream playback speed",
    "FW-01": "update stalled progress blinking red led do not disconnect power",
    "FW-02": "will not boot logo stuck remove card reset button",
    "FW-03": "stopped working after update setting reset regression",
    "FW-04": "update path app menu card reader usb flash drive",
    "APP-01": "no device found retry connect live video model selected vpn",
    "APP-02": "phone os update app version permissions reinstall",
    "APP-03": "permission location allow nearby devices setup screen",
    "APP-04": "new phone pair account register sign in",
    "REC-01": "incident footage overwritten locked event preserve power off remove card",
    "REC-02": "not recording red dot timer memory card error insert card announcement",
    "REC-03": "deleted overwrote loop oldest locked g-sensor event allocation",
    "REC-04": "parking mode hardwire kit ignition socket cutoff voltage",
    "SD-01": "card error insert card format photo mode shutter class u3 counterfeit",
    "SD-02": "card full loop recording off 4gb stopped recording",
    "SD-03": "corrupt file will not open vlc player abrupt power",
    "SD-04": "card failing endurance capacity maximum format every weeks",
    "PWR-01": "does not turn on wall outlet cable reset button power button",
    "PWR-02": "hot overheating temperature operating range shut down",
    "PWR-03": "does not turn off always hot socket usb port hold power 2 seconds",
    "PWR-04": "date time not holding supercapacitor battery gps time zone gmt",
    "VID-01": "blurry plate protective film lens clean resolution cpl",
    "VID-02": "reflection glare dashboard night cpl filter wdr exposure",
    "VID-03": "no audio microphone mute up button record audio timestamp",
}
