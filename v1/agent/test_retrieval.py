"""Stdlib unittest for the hybrid retrieval layer (`docs/06` §4.6).

    .venv/bin/python -m unittest agent.test_retrieval
    .venv/bin/python -m unittest agent.test_retrieval -v

Two halves, deliberately:

* **No network, no database.** The fusion, the k = 8 cut, the rerank and the
  dense-unavailable degradation are tested against a hand-built backend with
  canned scores, so the arithmetic §4.6 specifies is asserted on a machine with
  neither Postgres nor AWS. These are the tests that must never be skipped.
* **Against the real store.** The safety properties — model-filter-before-
  search, speakable-only, the schema's own `CHECK` constraints — are asserted
  against Postgres + pgvector, because that is where they are actually
  enforced and a mock would only assert that the mock agrees with itself.
  Skipped, loudly, when the store is not reachable.

The headline property, stated once: **a chunk the model filter excluded is
never returned, even when the query is that chunk's own text.** It is not
filtered out of a result list — it is never in the pool that gets scored, so
there is no ranking path by which it could come back.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent import retrieval, store  # noqa: E402
from agent.state import CONFIRMED, PROBABLE, UNKNOWN  # noqa: E402
from ingest.metadata import ALL_MODELS  # noqa: E402


def _chunk(
    chunk_id: str,
    *,
    text: str = "body text",
    models: tuple[str, ...] = ALL_MODELS,
    cross_model: bool = True,
    category: str = "WIFI",
    taxonomy_ids: tuple[str, ...] = (),
    speakable: bool = True,
    safety_critical: bool = False,
    step_ids: tuple[str, ...] = (),
) -> retrieval.Chunk:
    return retrieval.Chunk(
        chunk_id=chunk_id,
        text=text,
        doc_code="M1",
        source_path="data/text/manuals/x.txt",
        source_url=None,
        retrieval_date="2026-11-07",
        tier=1,
        page_range=None,
        section="S",
        context_header="",
        model_applicability=models,
        cross_model=cross_model,
        category=category,
        categories=(category,),
        taxonomy_ids=taxonomy_ids,
        step_ids=step_ids,
        verification_status="VERIFIED",
        speakable=speakable,
        destructive=False,
        safety_critical=safety_critical,
        raw={},
    )


class FakeBackend:
    """A backend with canned halves, so the §4.6 arithmetic is testable alone."""

    name = "fake"

    def __init__(self, chunks, lexical, dense):
        self._chunks = tuple(chunks)
        self._lexical = lexical
        self._dense = dense
        self.lexical_queries: list[str] = []
        self.dense_queries: list[str] = []

    def chunks(self):
        return self._chunks

    def pool(self, *, confidence, model, hw_revision, candidates):
        speakable = [c for c in self._chunks if c.speakable]
        return retrieval.model_filter(
            speakable,
            confidence=confidence,
            model=model,
            hw_revision=hw_revision,
            candidates=candidates,
        )

    def lexical(self, query, ids):
        self.lexical_queries.append(query)
        return {i: self._lexical[i] for i in ids if i in self._lexical}

    def dense(self, query, ids):
        self.dense_queries.append(query)
        if self._dense is None:
            return None
        return {i: self._dense[i] for i in ids if i in self._dense}


# --------------------------------------------------------------------------
# 1. The arithmetic: fusion, k = 8, rerank. No network, no database.
# --------------------------------------------------------------------------


class HybridFusion(unittest.TestCase):
    """0.5 · BM25 + 0.5 · dense, over a min-max normalised pool."""

    def test_the_two_halves_are_weighted_equally(self):
        # A is the lexical winner, C the dense winner, B middling on both.
        # Normalised: A = (1.0, 0.0), B = (0.5, 0.5), C = (0.0, 1.0) — all three
        # fuse to 0.5, and only the tie-break on chunk_id separates them. That
        # is the point: neither half can outvote the other.
        chunks = [_chunk(c) for c in ("A", "B", "C")]
        backend = FakeBackend(
            chunks,
            lexical={"A": 10.0, "B": 5.0, "C": 0.0},
            dense={"A": 0.0, "B": 0.5, "C": 1.0},
        )
        result = retrieval.retrieve("q", backend=backend, confidence=UNKNOWN)
        self.assertEqual([h.score for h in result.hits], [0.5, 0.5, 0.5])
        self.assertEqual(result.chunk_ids, ["A", "B", "C"])

    def test_a_weak_lexical_match_can_win_on_the_dense_half(self):
        # The gap the lexical-only milestone recorded: "it keeps cutting out"
        # barely overlaps the manual's "disconnect". C is a distant second on
        # BM25 and first by a distance on the dense half, and the equal weights
        # hand it the top spot — a ranking BM25 alone could not produce.
        #
        # Note the ceiling this arithmetic has, because it is a property of
        # §4.6's equal weights and not an accident: a chunk with *no* lexical
        # overlap sits at the pool floor, normalises to 0.0, and so fuses to at
        # most 0.5 — exactly what the lexical leader gets from its own half. It
        # can tie for first but not take it. What the dense half does for such
        # a chunk is get it into the k = 8 candidate set at all; BM25 alone
        # scores it 0 and it is dropped before the reranker ever sees it.
        chunks = [_chunk(c) for c in ("A", "B", "C")]
        backend = FakeBackend(
            chunks,
            lexical={"A": 10.0, "B": 0.0, "C": 4.0},
            dense={"A": 0.30, "B": 0.10, "C": 0.90},
        )
        result = retrieval.retrieve("it keeps cutting out", backend=backend)
        self.assertEqual(result.chunk_ids[0], "C")
        self.assertGreater(result.hits[0].score, result.hits[1].score)

    def test_the_dense_half_gets_the_callers_words_and_bm25_gets_the_expansion(self):
        chunks = [_chunk("A", taxonomy_ids=("WIFI-02",))]
        backend = FakeBackend(chunks, lexical={"A": 1.0}, dense={"A": 0.5})
        retrieval.retrieve(
            "nothing in the wifi list",
            backend=backend,
            category="WIFI",
            taxonomy_id="WIFI-02",
        )
        self.assertIn("WIFI-02", backend.lexical_queries[0])
        self.assertIn("emergency lock", backend.lexical_queries[0])
        self.assertEqual(backend.dense_queries, ["nothing in the wifi list"])

    def test_bm25_carries_alone_when_the_dense_half_is_unavailable(self):
        # C is the pool floor, normalises to 0.0 and is dropped with it; what
        # survives is BM25's own ordering, A behind B.
        chunks = [_chunk(c) for c in ("A", "B", "C")]
        backend = FakeBackend(chunks, lexical={"A": 5.0, "B": 9.0, "C": 1.0}, dense=None)
        result = retrieval.retrieve("q", backend=backend)
        self.assertEqual(result.chunk_ids, ["B", "A"])
        self.assertIn(("dense scored", 0), result.funnel)
        # Weighted 1.0, not 0.5: halving every score against a column of zeroes
        # would only rescale the ranking, and would hide the degradation.
        self.assertEqual(result.hits[0].score, 1.0)

    def test_normalize_handles_an_all_tied_half(self):
        self.assertEqual(
            retrieval.normalize({"a": 0.0, "b": 0.0}, ["a", "b"]), {"a": 0.0, "b": 0.0}
        )
        self.assertEqual(
            retrieval.normalize({"a": 3.0, "b": 3.0}, ["a", "b"]), {"a": 1.0, "b": 1.0}
        )
        self.assertEqual(retrieval.normalize({"a": 2.0}, ["a", "b"]), {"a": 1.0, "b": 0.0})


class HybridTopK(unittest.TestCase):
    """`hits = hybrid_search(..., k = 8)`; `hits = rerank(hits)[:3]`."""

    def _ten(self, **overrides):
        # Ten chunks, fused scores strictly decreasing by construction.
        chunks = [_chunk(f"C{i:02d}", **overrides.get(f"C{i:02d}", {})) for i in range(10)]
        lexical = {f"C{i:02d}": float(10 - i) for i in range(10)}
        dense = {f"C{i:02d}": float(10 - i) / 10 for i in range(10)}
        return chunks, lexical, dense

    def test_returns_three_and_only_three(self):
        chunks, lexical, dense = self._ten()
        result = retrieval.retrieve("q", backend=FakeBackend(chunks, lexical, dense))
        self.assertEqual(len(result.hits), 3)
        self.assertEqual(result.chunk_ids, ["C00", "C01", "C02"])
        self.assertIn(("hybrid k=8", 8), result.funnel)
        self.assertIn(("rerank top-3", 3), result.funnel)

    def test_the_rerank_reorders_the_eight(self):
        # C03 is fourth on fused score — 6/9 against C00's 1.0 — and carries
        # the triaged taxonomy id. 0.667 × 1.6 = 1.067 clears C00's unboosted
        # 1.0, so "written for exactly this taxonomy entry" outweighs a fused
        # gap of that size and C03 takes the top spot it did not have.
        chunks, lexical, dense = self._ten(C03={"taxonomy_ids": ("WIFI-02",)})
        backend = FakeBackend(chunks, lexical, dense)
        plain = retrieval.retrieve("q", backend=backend)
        boosted = retrieval.retrieve("q", backend=backend, taxonomy_id="WIFI-02")
        self.assertEqual(plain.chunk_ids, ["C00", "C01", "C02"])
        self.assertEqual(boosted.chunk_ids, ["C03", "C00", "C01"])
        self.assertIn("taxonomy WIFI-02", boosted.hits[0].why)

    def test_the_rerank_only_sees_the_eight(self):
        # C09 is last on fused score and would win on boosts alone. It is not
        # in the k = 8 candidate set, so the reranker never gets the chance —
        # §4.6 reranks `hits`, not the pool.
        chunks, lexical, dense = self._ten(
            C09={"taxonomy_ids": ("WIFI-02",), "safety_critical": True}
        )
        result = retrieval.retrieve(
            "q",
            backend=FakeBackend(chunks, lexical, dense),
            taxonomy_id="WIFI-02",
            category="WIFI",
        )
        self.assertNotIn("C09", result.chunk_ids)

    def test_k_and_hybrid_k_are_both_honoured(self):
        chunks, lexical, dense = self._ten()
        result = retrieval.retrieve(
            "q", backend=FakeBackend(chunks, lexical, dense), k=5, hybrid_k=6
        )
        self.assertEqual(len(result.hits), 5)
        self.assertIn(("hybrid k=6", 6), result.funnel)


class ModelFilterIsBeforeSearch(unittest.TestCase):
    """The safety control, on canned scores: a perfect text match loses to it."""

    def test_a_perfect_match_for_the_wrong_model_is_never_returned(self):
        # DUAL-only chunk, top of both halves by a mile. The caller's camera is
        # a confirmed R3. SD-04's card ceiling is exactly this case: 1 TB is
        # true for the DUAL and wrong for the R3.
        dual = _chunk("DUAL-ONLY", models=("R2-4K_DUAL",), cross_model=False)
        r3 = _chunk("R3-ONLY", models=("R3",), cross_model=False)
        backend = FakeBackend(
            [dual, r3],
            lexical={"DUAL-ONLY": 99.0, "R3-ONLY": 0.1},
            dense={"DUAL-ONLY": 0.99, "R3-ONLY": 0.01},
        )
        unfiltered = retrieval.retrieve(
            "q", backend=backend, confidence=CONFIRMED, model="R2-4K_DUAL"
        )
        self.assertEqual(unfiltered.chunk_ids[0], "DUAL-ONLY")

        filtered = retrieval.retrieve("q", backend=backend, confidence=CONFIRMED, model="R3")
        self.assertEqual(filtered.chunk_ids, ["R3-ONLY"])
        self.assertNotIn("DUAL-ONLY", filtered.chunk_ids)

    def test_unknown_confidence_sees_cross_model_chunks_only(self):
        specific = _chunk("SPECIFIC", models=("R3",), cross_model=False)
        shared = _chunk("SHARED", models=ALL_MODELS, cross_model=True)
        backend = FakeBackend(
            [specific, shared],
            lexical={"SPECIFIC": 99.0, "SHARED": 0.1},
            dense={"SPECIFIC": 0.99, "SHARED": 0.01},
        )
        result = retrieval.retrieve("q", backend=backend, confidence=UNKNOWN)
        self.assertEqual(result.chunk_ids, ["SHARED"])

    def test_probable_needs_every_live_candidate_covered(self):
        both = _chunk(
            "BOTH", models=("R2-4K_MINI_USB", "R2-4K_USB_C"), cross_model=False
        )
        one = _chunk("ONE", models=("R2-4K_USB_C",), cross_model=False)
        backend = FakeBackend(
            [both, one], lexical={"BOTH": 1.0, "ONE": 99.0}, dense={"BOTH": 0.5, "ONE": 0.9}
        )
        result = retrieval.retrieve(
            "q",
            backend=backend,
            confidence=PROBABLE,
            candidates=("R2-4K_MINI_USB", "R2-4K_USB_C"),
        )
        self.assertEqual(result.chunk_ids, ["BOTH"])

    def test_a_non_speakable_chunk_is_never_returned(self):
        blocked = _chunk("UNVERIFIED-ONE", speakable=False)
        allowed = _chunk("VERIFIED-ONE")
        backend = FakeBackend(
            [blocked, allowed],
            lexical={"UNVERIFIED-ONE": 99.0, "VERIFIED-ONE": 0.1},
            dense={"UNVERIFIED-ONE": 0.99, "VERIFIED-ONE": 0.01},
        )
        result = retrieval.retrieve("q", backend=backend)
        self.assertEqual(result.chunk_ids, ["VERIFIED-ONE"])


# --------------------------------------------------------------------------
# 2. Against the real Postgres + pgvector store.
# --------------------------------------------------------------------------


def _store_ready() -> bool:
    try:
        return store.is_available() and store.counts()["chunk_embeddings"] > 0
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_store_ready(), "Postgres + pgvector store not migrated")
class TheStore(unittest.TestCase):
    """What the database enforces, asserted where it is enforced."""

    def test_the_corpus_is_loaded_with_a_registry_row_behind_every_chunk(self):
        counts = store.counts()
        self.assertEqual(counts["chunks"], 213)
        self.assertEqual(counts["speakable"], 159)
        self.assertEqual(counts["source_registry"], 28)
        # §4.4: "no chunk without a registry entry is indexed", as a foreign key
        orphans = store.connect().execute(
            "SELECT count(*) FROM chunks c "
            "LEFT JOIN source_registry s USING (doc_code) WHERE s.doc_code IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0)

    def test_every_speakable_chunk_is_embedded_and_nothing_else_is(self):
        rows = store.connect().execute(
            "SELECT (SELECT count(*) FROM chunk_embeddings e JOIN chunks c "
            "        USING (chunk_id) WHERE NOT c.speakable), "
            "       (SELECT count(*) FROM chunks c WHERE c.speakable AND NOT EXISTS "
            "        (SELECT 1 FROM chunk_embeddings e WHERE e.chunk_id = c.chunk_id))"
        ).fetchone()
        self.assertEqual(tuple(rows), (0, 0))

    def test_the_embedding_dimension_is_recorded_not_assumed(self):
        info = store.embedding_model_info()
        self.assertEqual(info["model_id"], "amazon.titan-embed-text-v2:0")
        self.assertGreater(info["dim"], 0)
        actual = store.connect().execute(
            "SELECT vector_dims(embedding) FROM chunk_embeddings LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(actual, info["dim"])

    def test_the_schema_refuses_a_speakable_unverified_chunk(self):
        # §4.5 item 3 as a constraint: the four UNVERIFIED entries and the
        # rejected premise of SD-02 cannot be given a speakable chunk at all.
        import psycopg

        conn = store.connect()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO chunks (chunk_id, doc_code, text, source_path, "
                    "retrieval_date, tier, model_applicability, cross_model, "
                    "hw_revision_specific, firmware_applicability, category, "
                    "categories, taxonomy_ids, step_ids, verification_status, "
                    "speakable, destructive, safety_critical, expectation_gap, "
                    "raw, search_text, doc_len) VALUES "
                    "('T#1','M1','t','p','2026-11-07',1,'{}',false,false,'{}','FW',"
                    "'{}','{}','{}','UNVERIFIED',true,false,false,false,'{}','t',1)"
                )

    def test_the_schema_refuses_a_tier_2_chunk(self):
        import psycopg

        conn = store.connect()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO chunks (chunk_id, doc_code, text, source_path, "
                    "retrieval_date, tier, model_applicability, cross_model, "
                    "hw_revision_specific, firmware_applicability, category, "
                    "categories, taxonomy_ids, step_ids, verification_status, "
                    "speakable, destructive, safety_critical, expectation_gap, "
                    "raw, search_text, doc_len) VALUES "
                    "('T#2','M1','t','p','2026-11-07',2,'{}',false,false,'{}','FW',"
                    "'{}','{}','{}','VERIFIED',false,false,false,false,'{}','t',1)"
                )

    def test_the_sql_model_filter_matches_the_python_one(self):
        # The one place a SQL rewrite could quietly diverge from §4.6.
        pg = retrieval.PostgresBackend()
        jsonl = retrieval.JsonlBackend()
        cases = [
            (CONFIRMED, "R3", "unknown", ()),
            (CONFIRMED, "R2-4K", "mini_usb", ()),
            (CONFIRMED, "R2-4K", "usb_c", ()),
            (CONFIRMED, "R2-4K_DUAL_PRO", "unknown", ()),
            (PROBABLE, "unknown", "unknown", ("R2-4K_MINI_USB", "R2-4K_USB_C")),
            (PROBABLE, "unknown", "unknown", ()),
            (UNKNOWN, "unknown", "unknown", ()),
        ]
        for confidence, model, revision, candidates in cases:
            with self.subTest(confidence=confidence, model=model, revision=revision):
                kwargs = dict(
                    confidence=confidence,
                    model=model,
                    hw_revision=revision,
                    candidates=candidates,
                )
                self.assertEqual(
                    sorted(c.chunk_id for c in pg.pool(**kwargs)),
                    sorted(c.chunk_id for c in jsonl.pool(**kwargs)),
                )


@unittest.skipUnless(_store_ready(), "Postgres + pgvector store not migrated")
class AgainstTheRealCorpus(unittest.TestCase):
    """End to end on the 213 real chunks, through the default backend."""

    @classmethod
    def setUpClass(cls):
        cls.backend = retrieval.PostgresBackend()
        speakable = [c for c in cls.backend.chunks() if c.speakable]
        # A chunk that belongs to exactly one model and is not cross-model —
        # the kind SD-04 warns about, chosen from the corpus rather than named,
        # so this test does not rot when the corpus is re-chunked.
        cls.exclusive = next(
            c
            for c in speakable
            if len(c.model_applicability) == 1 and not c.cross_model
        )
        cls.owner = cls.exclusive.model_applicability[0]
        cls.other = next(
            m
            for m in ALL_MODELS
            if m != cls.owner
            and any(
                m in c.model_applicability and cls.owner not in c.model_applicability
                for c in speakable
            )
        )
        # The chunk's own words: as perfect a lexical match as exists.
        cls.query = " ".join(cls.exclusive.text.split()[:40])

    def test_bm25_ranks_the_exclusive_chunk_first_for_its_own_text(self):
        """The premise of the next test: without the filter, it wins."""
        ids = [c.chunk_id for c in self.backend.chunks() if c.speakable]
        scores = self.backend.lexical(self.query, ids)
        best = max(scores, key=lambda i: scores[i])
        self.assertEqual(best, self.exclusive.chunk_id)

    def test_the_wrong_model_top_hit_is_corrected_by_the_filter(self):
        # The test above establishes that BM25 alone ranks this chunk first for
        # its own words. The *hybrid* score need not agree, and here it does
        # not: the chunk's own text is a firmware-update passage inside a Wi-Fi
        # article, and the dedicated firmware chunks are closer to it on the
        # dense half than it is to itself on the lexical one. So what is
        # asserted is the property the model filter actually owns, which is
        # independent of rank: for its own model the chunk is in the candidate
        # set and available to be returned; for any other model it is in no
        # candidate set, at any k.
        confirmed_owner = retrieval.retrieve(
            self.query, confidence=CONFIRMED, model=self.owner, backend=self.backend, k=8
        )
        self.assertIn(self.exclusive.chunk_id, confirmed_owner.chunk_ids)

        confirmed_other = retrieval.retrieve(
            self.query, confidence=CONFIRMED, model=self.other, backend=self.backend, k=8
        )
        self.assertNotIn(self.exclusive.chunk_id, confirmed_other.chunk_ids)
        self.assertTrue(confirmed_other.hits, "the other model should still retrieve")

    def test_the_excluded_chunk_is_not_even_in_the_pool(self):
        """Not 'filtered out of the results' — never scored in the first place."""
        pool = store.pool_ids(confidence=CONFIRMED, wanted=self.other)
        self.assertNotIn(self.exclusive.chunk_id, pool)
        self.assertIn(self.exclusive.chunk_id, store.pool_ids(
            confidence=CONFIRMED, wanted=self.owner
        ))

    def test_unverified_entries_have_no_speakable_chunk_and_never_surface(self):
        unspeakable = {
            c.chunk_id for c in self.backend.chunks() if not c.speakable
        }
        self.assertTrue(unspeakable)
        for chunk in self.backend.chunks():
            if chunk.verification_status in ("UNVERIFIED", "REJECTED"):
                self.assertFalse(chunk.speakable, chunk.chunk_id)

        queries = [
            "it got really hot and shut itself down",
            "everything broke after the firmware update",
            "I got a new phone and need to pair it again",
            "the app version is out of date",
        ]
        for query in queries:
            for confidence, model in (
                (UNKNOWN, "unknown"),
                (CONFIRMED, "R3"),
                (CONFIRMED, "R2-4K_DUAL"),
            ):
                with self.subTest(query=query, confidence=confidence):
                    result = retrieval.retrieve(
                        query,
                        confidence=confidence,
                        model=model,
                        backend=self.backend,
                    )
                    self.assertFalse(unspeakable.intersection(result.chunk_ids))

    def test_the_hybrid_path_actually_ran_both_halves(self):
        result = retrieval.retrieve(
            "my wifi network is not showing up on my phone",
            confidence=CONFIRMED,
            model="R3",
            category="WIFI",
            taxonomy_id="WIFI-02",
            backend=self.backend,
        )
        funnel = dict(result.funnel)
        self.assertEqual(funnel["store postgres"], 213)
        self.assertGreater(funnel["bm25 scored"], 0)
        self.assertGreater(funnel["dense scored"], 0)
        self.assertEqual(len(result.hits), 3)
        for hit in result.hits:
            self.assertGreater(hit.dense, 0.0, "cosine should be populated")

    def test_results_are_reproducible(self):
        args = dict(
            confidence=CONFIRMED, model="R2-4K", hw_revision="usb_c", category="SD"
        )
        first = retrieval.retrieve("my card keeps erroring", backend=self.backend, **args)
        second = retrieval.retrieve("my card keeps erroring", backend=self.backend, **args)
        self.assertEqual(first.chunk_ids, second.chunk_ids)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
