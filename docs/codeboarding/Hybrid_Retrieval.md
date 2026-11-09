# Hybrid Retrieval

[Back to the overview](overview.md) · component 5

```mermaid
graph LR
    Filter_Fuse_and_Rerank["Filter, Fuse and Rerank"]
    Retrieval_Backends["Retrieval Backends"]
    Postgres_and_pgvector_Store["Postgres and pgvector Store"]
    Filter_Fuse_and_Rerank -- "asks the backend for a pool, lexical scores and dense scores" --> Retrieval_Backends
    Retrieval_Backends -- "PostgresBackend calls the store's SQL halves" --> Postgres_and_pgvector_Store
```

## Details

Filter first, then search. `retrieval.retrieve` applies model, category and speakable filters, fuses BM25 and dense scores, reranks and returns the top three Tier-1 chunks. The chunk store is Postgres plus pgvector (Titan embeddings); a JSONL backend takes over when Postgres does not answer.

### Relations

| From | To | Relation | Evidence |
|---|---|---|---|
| Filter, Fuse and Rerank | Retrieval Backends | asks the backend for a pool, lexical scores and dense scores | `agent/retrieval.py:retrieve` |
| Retrieval Backends | Postgres and pgvector Store | PostgresBackend calls the store's SQL halves | `agent/retrieval.py:PostgresBackend` |

### Filter, Fuse and Rerank

The retrieval chain over a `Backend`: model filter (confirmed / probable / unknown), fusion of lexical and dense scores, rerank, top 3 with chunk ids.

**Related Classes/Methods**:

- [`agent/retrieval.py`:`retrieve`](../../agent/retrieval.py#L565-L655)

**Source Files:**

- [`agent/retrieval.py`](../../agent/retrieval.py)
  - `retrieve` ([L565-L655](../../agent/retrieval.py#L565-L655)) - function
  - `rerank` ([L523-L557](../../agent/retrieval.py#L523-L557)) - function
  - `model_filter` ([L189-L219](../../agent/retrieval.py#L189-L219)) - function
  - `Chunk` ([L105-L134](../../agent/retrieval.py#L105-L134)) - class
  - `RetrievalResult` ([L497-L520](../../agent/retrieval.py#L497-L520)) - class
  - `Hit` ([L484-L493](../../agent/retrieval.py#L484-L493)) - class

### Retrieval Backends

`PostgresBackend` runs the filter and both halves of the search as SQL; `JsonlBackend` serves `data/processed/chunks.jsonl` with stdlib BM25; `default_backend` picks one once.

**Related Classes/Methods**:

- [`agent/retrieval.py`:`Backend`](../../agent/retrieval.py#L227-L246)

**Source Files:**

- [`agent/retrieval.py`](../../agent/retrieval.py)
  - `Backend` ([L227-L246](../../agent/retrieval.py#L227-L246)) - class
  - `PostgresBackend` ([L249-L288](../../agent/retrieval.py#L249-L288)) - class
  - `JsonlBackend` ([L291-L340](../../agent/retrieval.py#L291-L340)) - class
  - `default_backend` ([L415-L422](../../agent/retrieval.py#L415-L422)) - function

### Postgres and pgvector Store

Schema (`source_registry`, `chunks`, `chunk_lexemes`, `lexeme_df`, `corpus_stats`, `embedding_model`, `chunk_embeddings`), the migration that loads the corpus, Titan embedding calls, and the SQL halves of the hybrid search.

**Related Classes/Methods**:

- [`agent/store.py`:`connect`](../../agent/store.py#L112-L132)

**Source Files:**

- [`agent/store.py`](../../agent/store.py)
  - `connect` ([L112-L132](../../agent/store.py#L112-L132)) - function
  - `migrate` ([L449-L623](../../agent/store.py#L449-L623)) - function
  - `embed` ([L216-L243](../../agent/store.py#L216-L243)) - function
  - `embed_query` ([L246-L271](../../agent/store.py#L246-L271)) - function
  - `bm25_scores` ([L717-L734](../../agent/store.py#L717-L734)) - function
  - `dense_scores` ([L737-L749](../../agent/store.py#L737-L749)) - function
  - `fetch_chunk_rows` ([L649-L654](../../agent/store.py#L649-L654)) - function
  - `model_predicate` ([L657-L671](../../agent/store.py#L657-L671)) - function
