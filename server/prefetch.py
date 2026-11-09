"""Speculative prefetch on ASR partials (`docs/06` §2.1, §2.2 line 5).

§2.1 draws it into the pipeline and says exactly what it is for:

> SPECULATIVE PREFETCH fires at ~60% confidence on a category-bearing partial
> ("card error", "won't connect", "won't turn on"): runs the metadata-filtered
> retrieval for the 2–3 most likely taxonomy IDs and warms the LLM prompt
> prefix. **Discarded silently if the final transcript disagrees.** Cost:
> wasted retrieval. Benefit: the whole RAG hop leaves the critical path.

§2.2 line 5 is the budget line it is spending against — *"RAG retrieval **not
hidden by prefetch**: 0 ms best case, 30 ms median, 240 ms at p95. **0 on a
prefetch hit.**"*

Three things make this safe to bolt onto a diagnostic system rather than a
chatbot, and all three are structural:

1. **It never writes anything.** A prefetch produces a `RetrievalResult` and a
   `Classification` and puts them in a cache. It does not touch
   `DiagnosticState`, does not advance the FSM, does not enter the ledger and
   cannot propose a step. A speculative turn that *ran* would be a no-repeat
   violation waiting to happen (§3.5); a speculative *lookup* cannot be.
2. **It is only ever a cache warm.** The turn runs the real retrieval and the
   real classification afterwards, unconditionally, through the same
   `agent.core.diagnose` a typed turn goes through. What a hit buys is that
   those calls find their work already done — the Titan query embedding in
   `agent/store.py`'s `_query_cache`, and the Nova Micro classification in
   :class:`MemoLLM` below. Nothing branches on whether the prefetch hit, so a
   wrong guess costs tokens and never a decision. §7.2's M10 stays measurable
   because the branch taken does not depend on it.
3. **It yields to the turn.** `agent/store.py` keeps *one* connection and says
   why — *"the agent is single-threaded per turn and a pool would be
   ceremony"*. A speculative retrieval on a worker thread would race the turn's
   on that connection. :data:`CORE_LOCK` serialises them: the turn takes it
   blocking, the prefetch takes it **non-blocking and gives up**, so
   speculation can never make a real turn wait for speculation. (It can make
   one wait for a prefetch already in flight — that is §2.1's "cost: wasted
   retrieval", paid once, and it is bounded by a single retrieval.)

**What "the final transcript disagrees" means.** Two kinds of agreement are
worth different amounts, so both are recorded:

* **exact** — the final transcript is character-identical to the partial the
  prefetch fired on. The classification memo and the embedding cache both hit,
  and the whole RAG hop really does leave the critical path. This is the common
  case with Transcribe's `partial_results_stability=high`, where the last
  stabilised partial before the endpoint usually *is* the final.
* **shortlist** — the final differs in wording but triages to the same
  taxonomy entry. The embedding memo misses (it is keyed on text) but the
  retrieval pool, the corpus statistics and the connection are warm, and the
  prefetched hits are still the right ones to have looked at.

Anything else is a **miss**, and a miss is discarded in one statement:
:meth:`SpeculativePrefetch.claim` drops the entry whatever the answer, so there
is no path on which a stale speculation survives into a later turn.

Nothing in `agent/` or `eval/` is modified by any of this. The only thing this
module imports from them is `eval.baseline.match_taxonomy` — the same pure
rule-based router `agent/core.py` uses as its triage floor — because the
cheapest honest way to ask "is this partial category-bearing?" is to ask the
thing that will be asked for real a second later.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agent import retrieval
from eval import baseline, ontology

#: Serialises anything that touches `agent/store.py`'s single shared
#: connection. See item 3 of the module docstring. The turn takes it blocking
#: (`server/core_bridge.py`); the prefetch takes it with `blocking=False`.
CORE_LOCK = threading.Lock()

#: §2.1: "fires at ~60% confidence on a category-bearing partial". Transcribe
#: scores partials per item; `server/transcribe.py` averages them.
MIN_CONFIDENCE = 0.6

#: Below this, a partial is a fragment rather than a symptom. "my camera" is
#: category-bearing by keyword and worth nothing to retrieve on.
MIN_WORDS = 4

#: How many taxonomy entries a prefetch is allowed to retrieve for. §2.1 says
#: "the 2–3 most likely taxonomy IDs"; three, and never the whole shortlist,
#: because the cost of a miss is the thing being bounded here.
MAX_ENTRIES = 3

#: Entries that name nothing to retrieve for. `OUT_OF_SCOPE` and `NO_MATCH` are
#: triage *outcomes*, not categories, and retrieving on them warms nothing.
_NOT_AN_ENTRY = frozenset({"NO_MATCH", "OUT_OF_SCOPE", "KNOWN-GAP"})


# --------------------------------------------------------------------------
# The memoising LLM (docs/06 §2.1: "warms the LLM prompt prefix")
# --------------------------------------------------------------------------


class MemoLLM:
    """An `agent.llm.LLM` that remembers what it was asked to classify.

    `classify(utterance)` is a pure function of the utterance — it takes no
    state, reads no ledger and returns a category, a taxonomy shortlist and
    flags. That is precisely the property §2.1 needs: it is "the LLM call the
    partial already determines", and running it early on a partial that turns
    out to be the final transcript removes a whole Nova Micro round trip from
    §2.2 line 6.

    `decide(...)` is **not** memoised and must not be: it is a function of the
    legal candidate set, which is a function of the ledger, the model
    clearance and the destructive gate. A cache there would be a cache of a
    policy decision, and `docs/06` §1.3 says policy clearance is recomputed per
    turn. So this wrapper is one memo, on one pure call, and a pass-through for
    everything else.

    Installed by `server/app.py` around the real `BedrockLLM`, which is the
    documented injection point — `agent.core.diagnose` takes `llm=` and
    `server/` is what passes it. Nothing in `agent/` is changed to make this
    work.
    """

    def __init__(self, inner: Any, *, max_entries: int = 64) -> None:
        self.inner = inner
        self.max_entries = max_entries
        self._memo: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", "llm")

    def classify(self, utterance: str) -> Any:
        key = (utterance or "").strip()
        with self._lock:
            cached = self._memo.get(key)
        if cached is not None:
            with self._lock:
                self.hits += 1
            return cached
        result = self.inner.classify(utterance)
        with self._lock:
            self.misses += 1
            if len(self._memo) >= self.max_entries:
                self._memo.clear()
            self._memo[key] = result
        return result

    def decide(self, **kwargs: Any) -> Any:
        return self.inner.decide(**kwargs)

    def __getattr__(self, name: str) -> Any:
        # `last_error` and anything else the core reads off the handle for the
        # trace. Delegated rather than copied, so a field added to `BedrockLLM`
        # does not silently read as absent through the wrapper.
        return getattr(self.inner, name)


# --------------------------------------------------------------------------
# One speculation
# --------------------------------------------------------------------------


@dataclass
class Speculation:
    """One prefetch: what it was fired on, and what it found."""

    key: str
    fired_at: float
    confidence: float
    entries: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    retrieval_ms: float = 0.0
    classify_ms: float = 0.0
    classified: bool = False
    done: bool = False
    skipped: str = ""

    @property
    def work_ms(self) -> float:
        return round(self.retrieval_ms + self.classify_ms, 1)


@dataclass
class Outcome:
    """What claiming a speculation against the final transcript was worth."""

    hit: bool
    kind: str  # exact | shortlist | miss | none
    key: str = ""
    final: str = ""
    entries: list[str] = field(default_factory=list)
    final_entry: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    #: Retrieval + classification that was already done when the endpoint
    #: fired. On a hit this is work §2.2 lines 5 and 6 do not have to pay for.
    prefetched_ms: float = 0.0
    lead_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "hit": self.hit,
            "kind": self.kind,
            "partial": self.key,
            "final": self.final,
            "entries": list(self.entries),
            "final_entry": self.final_entry,
            "chunk_ids": list(self.chunk_ids),
            "prefetched_ms": self.prefetched_ms,
            "lead_ms": self.lead_ms,
        }


@dataclass
class PrefetchStats:
    considered: int = 0
    fired: int = 0
    hits: int = 0
    exact_hits: int = 0
    shortlist_hits: int = 0
    misses: int = 0
    yielded_to_turn: int = 0
    wasted_ms: float = 0.0
    saved_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        return round(self.hits / self.fired, 4) if self.fired else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "fired": self.fired,
            "hits": self.hits,
            "exact_hits": self.exact_hits,
            "shortlist_hits": self.shortlist_hits,
            "misses": self.misses,
            "yielded_to_turn": self.yielded_to_turn,
            "hit_rate": self.hit_rate,
            "saved_ms": round(self.saved_ms, 1),
            "wasted_ms": round(self.wasted_ms, 1),
        }


# --------------------------------------------------------------------------
# Is this partial worth speculating on?
# --------------------------------------------------------------------------


def shortlist_for(text: str, *, llm: Any | None = None) -> list[str]:
    """The 2–3 most likely taxonomy entries for a string (§2.1).

    The rule-based router first, because it is free, deterministic and is the
    same floor `agent/core.py`'s `TRIAGE` falls back to. The classifier is
    asked only when there is one, and its answer goes *in front* — mirroring
    `step_triage`, which extends the shortlist with the classification and then
    appends the rule entry.
    """
    entries: list[str] = []
    if llm is not None:
        try:
            classification = llm.classify(text)
        except Exception:  # noqa: BLE001 — a speculative call may always fail
            classification = None
        if classification is not None:
            entries.extend(
                e for e in getattr(classification, "taxonomy_ids", []) or [] if e
            )
    rule_entry = baseline.match_taxonomy(text)
    if rule_entry and rule_entry not in entries:
        entries.append(rule_entry)
    return [e for e in entries if e not in _NOT_AN_ENTRY][:MAX_ENTRIES]


def category_bearing(text: str) -> bool:
    """§2.1's trigger: does this partial name a problem yet?

    Asked of `eval.baseline.match_taxonomy`, which is the rule-based router the
    core itself falls back to — so a partial this says yes to is a partial the
    turn will triage somewhere, and a partial it says no to is one a prefetch
    would have nothing to filter on.
    """
    stripped = (text or "").strip()
    if len(stripped.split()) < MIN_WORDS:
        return False
    return baseline.match_taxonomy(stripped) not in _NOT_AN_ENTRY


# --------------------------------------------------------------------------
# The prefetcher
# --------------------------------------------------------------------------


class SpeculativePrefetch:
    """One session's speculation, fired from partials and claimed at the endpoint.

    Deliberately not an `asyncio` object: it is driven from
    `server/livekit_agent.py`'s partial callback, which Transcribe's reader
    calls, and the work it does is blocking (a Bedrock round trip and a
    database query). `submit` is whatever the caller wants it to be — a thread
    pool in the server, a direct call in a test.
    """

    def __init__(
        self,
        *,
        state: Any,
        llm: Any | None = None,
        chunks_path: str | None = None,
        trace: Callable[..., Any] | None = None,
        submit: Callable[[Callable[[], None]], Any] | None = None,
        enabled: bool = True,
    ) -> None:
        self.state = state
        self.llm = llm
        self.chunks_path = chunks_path
        self._trace = trace or (lambda *a, **k: None)
        self._submit = submit or (lambda fn: fn())
        self.enabled = enabled
        self.stats = PrefetchStats()
        self._lock = threading.Lock()
        self._live: Speculation | None = None
        self._armed_at = 0.0

    # -- the turn boundary -------------------------------------------------

    def arm(self, now: float | None = None) -> None:
        """A new caller turn is starting. Anything left over is stale."""
        with self._lock:
            self._live = None
            self._armed_at = time.time() if now is None else now

    # -- firing ------------------------------------------------------------

    def consider(self, text: str, *, confidence: float | None, is_partial: bool = True) -> bool:
        """One ASR hypothesis. Returns whether it started a speculation.

        §2.1 fires "at ~60% confidence on a category-bearing partial". Both
        halves are conditions and both are checked here rather than inside the
        worker, so a partial that does not qualify costs a regex and a dict
        lookup on the recogniser's own callback.
        """
        if not self.enabled:
            return False
        key = (text or "").strip()
        if not key:
            return False
        self.stats.considered += 1
        score = MIN_CONFIDENCE if confidence is None else float(confidence)
        if score < MIN_CONFIDENCE:
            return False
        if not category_bearing(key):
            return False
        with self._lock:
            live = self._live
            if live is not None and (live.key == key or key.startswith(live.key)):
                # The same hypothesis, or it grew: the speculation in flight is
                # still the best guess we have. Re-firing on every partial
                # would spend a Bedrock call per 200 ms of speech, which is the
                # cost §2.1 bounds rather than the benefit it describes.
                if live.key == key:
                    return False
                if not live.done:
                    return False
            speculation = Speculation(key=key, fired_at=time.time(), confidence=score)
            self._live = speculation
            self.stats.fired += 1
        self._trace(
            "prefetch.fired",
            partial=key,
            confidence=round(score, 4),
            words=len(key.split()),
        )
        self._submit(lambda: self._run(speculation))
        return True

    def _run(self, speculation: Speculation) -> None:
        """The speculative work itself, on whatever thread `submit` chose."""
        try:
            started = time.perf_counter()
            if self.llm is not None:
                try:
                    self.llm.classify(speculation.key)
                    speculation.classified = True
                except Exception:  # noqa: BLE001 — a speculation may fail freely
                    speculation.classified = False
            speculation.classify_ms = round((time.perf_counter() - started) * 1000, 1)

            entries = shortlist_for(speculation.key, llm=self.llm)
            speculation.entries = entries
            if not entries:
                speculation.skipped = "no taxonomy entry"
                return

            # Item 3 of the module docstring: speculation yields to the turn,
            # and never the other way round.
            if not CORE_LOCK.acquire(blocking=False):
                speculation.skipped = "a real turn holds the store"
                self.stats.yielded_to_turn += 1
                self._trace("prefetch.yielded", partial=speculation.key)
                return
            try:
                started = time.perf_counter()
                device = getattr(self.state, "device", None)
                for entry in entries:
                    result = retrieval.retrieve(
                        speculation.key,
                        confidence=getattr(device, "confidence", "unknown"),
                        model=getattr(device, "model", "unknown"),
                        hw_revision=getattr(device, "hw_revision", "unknown"),
                        candidates=list(getattr(device, "candidates", ()) or ()),
                        category=ontology.category_of(entry),
                        taxonomy_id=entry,
                        path=self.chunks_path,
                    )
                    for chunk_id in result.chunk_ids:
                        if chunk_id not in speculation.chunk_ids:
                            speculation.chunk_ids.append(chunk_id)
                speculation.retrieval_ms = round((time.perf_counter() - started) * 1000, 1)
            finally:
                CORE_LOCK.release()
        except Exception as exc:  # noqa: BLE001 — speculation never fails a turn
            speculation.skipped = f"{type(exc).__name__}: {exc}"
        finally:
            speculation.done = True

    # -- claiming ----------------------------------------------------------

    def claim(self, final: str) -> Outcome:
        """Settle the speculation against the final transcript, and drop it.

        Called once per turn, at the endpoint. The entry is cleared whatever
        the verdict — §2.1's "discarded silently if the final transcript
        disagrees", made unconditional so there is no path on which a stale
        speculation survives into a later turn.
        """
        final = (final or "").strip()
        with self._lock:
            speculation, self._live = self._live, None
        if speculation is None:
            return Outcome(hit=False, kind="none", final=final)

        final_entries = shortlist_for(final, llm=None)
        final_entry = final_entries[0] if final_entries else ""
        lead_ms = round(1000.0 * max(0.0, time.time() - speculation.fired_at), 1)

        if speculation.key == final:
            kind = "exact"
        elif final_entry and final_entry in speculation.entries:
            kind = "shortlist"
        else:
            kind = "miss"

        outcome = Outcome(
            hit=kind != "miss",
            kind=kind,
            key=speculation.key,
            final=final,
            entries=list(speculation.entries),
            final_entry=final_entry,
            chunk_ids=list(speculation.chunk_ids),
            prefetched_ms=speculation.work_ms,
            lead_ms=lead_ms,
        )
        if outcome.hit:
            self.stats.hits += 1
            self.stats.saved_ms += speculation.work_ms
            if kind == "exact":
                self.stats.exact_hits += 1
            else:
                self.stats.shortlist_hits += 1
            self._trace("prefetch.hit", **outcome.as_dict())
        else:
            self.stats.misses += 1
            self.stats.wasted_ms += speculation.work_ms
            self._trace("prefetch.discarded", **outcome.as_dict())
        return outcome
