"""Measure what speculative prefetch (`docs/06` §2.1) is actually worth.

    .venv/bin/python -m eval.run_prefetch
    .venv/bin/python -m eval.run_prefetch --json
    .venv/bin/python -m eval.run_prefetch --no-llm      # rule router only

§2.1 says the prefetch fires "at ~60 % confidence on a category-bearing
partial" and that a hit removes retrieval and the classification round trip
from §2.2 lines 5 and 6. `server/prefetch.py` implements that and counts
itself; what was missing was a number for *how often it hits on our own
sentences*, which is the only thing that says whether the mechanism earns the
Bedrock calls it spends.

**The corpus is Harness B's.** Every sentence a Harness B run speaks: the
eight scenarios' opening utterances from `docs/03`, every branch reply in
`eval/harness_b.py`'s scripts, and the two off-script replies. These are
caller sentences rather than agent ones, which is what the recogniser would
be transcribing.

**What is modelled and what is real.** Harness B is a typed harness — there is
no audio in it and therefore no recogniser, so there is no recording of what
Transcribe's partials would have been. This drives the real
`SpeculativePrefetch` with a *prefix stream*: the utterance revealed one word
at a time from `prefetch.MIN_WORDS` onwards, which is roughly how a streaming
recogniser grows a hypothesis but is not a transcript of one. Everything
downstream of that is real — the real `category_bearing` trigger, the real
Nova Micro classification, the real hybrid retrieval over the real chunk
store, and the real `claim` against the final transcript. The timings in
`saved_ms` and `wasted_ms` are measured, not modelled.

**Each speculation is allowed to finish before the turn claims it.** In the
server the endpoint can arrive while a speculation is still in flight, and an
unfinished speculation claims as a miss. Waiting here separates the two
questions §2.1 raises — *did the guess agree with the final transcript* (this
number) from *did it finish in time* (a function of how long the caller kept
talking, which this corpus cannot say). So the hit rate below is the ceiling
the mechanism can reach, and the report says so rather than implying it is
what a live session sees.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from server import prefetch as prefetch_module
from server.config import Settings

from .harness import load_scenarios
from .harness_b import (
    HARNESS_B_IDS,
    OFF_SCRIPT_ACTION,
    OFF_SCRIPT_QUESTION,
    SCRIPTS,
)


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Utterance:
    """One caller sentence a Harness B run speaks, and where it came from."""

    source: str
    text: str


def harness_b_utterances() -> list[Utterance]:
    """Everything the caller says across a Harness B run, in a stable order."""
    by_id = {s.id: s for s in load_scenarios()}
    out: list[Utterance] = []
    for scenario_id in HARNESS_B_IDS:
        out.append(Utterance(f"{scenario_id}:opening", by_id[scenario_id].utterance))
        for branch in SCRIPTS[scenario_id].branches:
            out.append(Utterance(f"{scenario_id}:{branch.name}", branch.reply))
    out.append(Utterance("off-script:question", OFF_SCRIPT_QUESTION[0]))
    out.append(Utterance("off-script:action", OFF_SCRIPT_ACTION[0]))
    return out


def partial_stream(text: str) -> list[str]:
    """The prefix stream a streaming recogniser would roughly produce.

    From `prefetch.MIN_WORDS` words onwards, one word at a time, ending on the
    whole sentence. Below `MIN_WORDS` the prefetcher declines by construction,
    so emitting them would only inflate `considered`.
    """
    words = text.split()
    if len(words) < prefetch_module.MIN_WORDS:
        return [text] if text.strip() else []
    return [" ".join(words[:n]) for n in range(prefetch_module.MIN_WORDS, len(words) + 1)]


# --------------------------------------------------------------------------
# One utterance
# --------------------------------------------------------------------------


@dataclass
class UtteranceResult:
    source: str
    text: str
    partials: int = 0
    fired: int = 0
    kind: str = "none"
    hit: bool = False
    partial_fired_on: str = ""
    entries: list[str] = field(default_factory=list)
    final_entry: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    prefetched_ms: float = 0.0
    lead_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "text": self.text,
            "partials": self.partials,
            "fired": self.fired,
            "kind": self.kind,
            "hit": self.hit,
            "partial_fired_on": self.partial_fired_on,
            "entries": list(self.entries),
            "final_entry": self.final_entry,
            "chunks": len(self.chunk_ids),
            "prefetched_ms": self.prefetched_ms,
            "lead_ms": self.lead_ms,
        }


class _State:
    """The slice of `DiagnosticState` the prefetcher reads.

    An unresolved device, which is what a caller's first turns look like and
    what §1.3 says the retrieval filter must assume until proven otherwise.
    """

    device = None


def measure(
    utterances: list[Utterance],
    *,
    llm: Any | None,
    chunks_path: str | None,
    verbose: bool = True,
) -> tuple[list[UtteranceResult], prefetch_module.PrefetchStats]:
    """Drive the real prefetcher over the corpus, one turn per utterance."""
    pending: list[Any] = []

    def submit(work: Any) -> None:
        # Run inline and remember it, so `wait` below is a no-op that still
        # documents the ordering the server gets from its thread pool.
        work()
        pending.append(work)

    speculator = prefetch_module.SpeculativePrefetch(
        state=_State(),
        llm=llm,
        chunks_path=chunks_path,
        submit=submit,
    )

    results: list[UtteranceResult] = []
    for utterance in utterances:
        speculator.arm()
        before_fired = speculator.stats.fired
        result = UtteranceResult(source=utterance.source, text=utterance.text)
        stream = partial_stream(utterance.text)
        result.partials = len(stream)
        for index, partial in enumerate(stream):
            is_final = index == len(stream) - 1
            if speculator.consider(
                partial,
                # §2.1's trigger is "~60 % confidence". The corpus carries no
                # recogniser confidence, so every partial is offered at the
                # threshold itself: the weakest hypothesis §2.1 would still
                # fire on, rather than a flattering one.
                confidence=prefetch_module.MIN_CONFIDENCE,
                is_partial=not is_final,
            ):
                result.partial_fired_on = partial
        result.fired = speculator.stats.fired - before_fired

        outcome = speculator.claim(utterance.text)
        result.kind = outcome.kind
        result.hit = outcome.hit
        result.entries = list(outcome.entries)
        result.final_entry = outcome.final_entry
        result.chunk_ids = list(outcome.chunk_ids)
        result.prefetched_ms = outcome.prefetched_ms
        result.lead_ms = outcome.lead_ms
        results.append(result)
        if verbose:
            print(
                f"  {result.source:<28}{result.kind:<11}"
                f"fired={result.fired:<3}"
                f"{result.prefetched_ms:>8.1f} ms  "
                f"{result.final_entry or '—'}",
                flush=True,
            )
    return results, speculator.stats


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def format_report(
    results: list[UtteranceResult],
    stats: prefetch_module.PrefetchStats,
    *,
    llm_name: str,
) -> str:
    lines: list[str] = []
    lines.append(
        f"Speculative prefetch (§2.1) over the Harness B corpus — "
        f"{len(results)} caller utterance(s)"
    )
    lines.append(f"  classifier: {llm_name}")
    lines.append(
        f"  partials modelled as word-by-word prefixes from "
        f"{prefetch_module.MIN_WORDS} words, offered at "
        f"{prefetch_module.MIN_CONFIDENCE:.2f} confidence"
    )
    lines.append("")

    header = f"{'utterance':<28}{'verdict':<11}{'fired':<7}{'work ms':>9}  taxonomy entry"
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        lines.append(
            f"{r.source:<28}{r.kind:<11}{r.fired:<7}{r.prefetched_ms:>9.1f}  "
            f"{r.final_entry or '—'}"
        )
    lines.append("")

    worked = [r.prefetched_ms for r in results if r.fired]
    lines.append("Totals")
    lines.append(
        f"  considered {stats.considered} partial(s); fired {stats.fired}; "
        f"hits {stats.hits} ({stats.exact_hits} exact, "
        f"{stats.shortlist_hits} shortlist); misses {stats.misses}"
    )
    lines.append(f"  hit rate {stats.hit_rate:.1%} of speculations fired")
    fired_utterances = sum(1 for r in results if r.fired)
    hit_utterances = sum(1 for r in results if r.hit)
    lines.append(
        f"  per utterance: {fired_utterances}/{len(results)} fired at all, "
        f"{hit_utterances}/{len(results)} ended in a hit"
    )
    lines.append(
        f"  saved {stats.saved_ms:.1f} ms of §2.2 lines 5+6 work; "
        f"wasted {stats.wasted_ms:.1f} ms"
    )
    if worked:
        lines.append(
            f"  per speculation: median {statistics.median(worked):.1f} ms of "
            f"retrieval + classification, max {max(worked):.1f} ms"
        )
    if stats.hits:
        lines.append(
            f"  mean saving on a hit: {stats.saved_ms / stats.hits:.1f} ms off the turn"
        )
    lines.append(f"  yielded to a live turn {stats.yielded_to_turn} time(s)")
    lines.append("")
    lines.append(
        "Ceiling, not a live reading: every speculation was allowed to finish "
        "before the"
    )
    lines.append(
        "turn claimed it. In a session an endpoint that arrives mid-speculation "
        "claims as a"
    )
    lines.append(
        "miss, so a live hit rate is this number times the fraction of "
        "speculations that beat"
    )
    lines.append("the endpoint — which depends on how long the caller kept talking.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch hit rate over Harness B.")
    parser.add_argument("--no-llm", action="store_true", help="rule-based router only")
    parser.add_argument("--json", action="store_true", help="print as JSON")
    parser.add_argument("--out", default="", help="also write the JSON here")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    llm: Any | None = None
    llm_name = "none (eval.baseline rule router only)"
    if not args.no_llm:
        try:
            from agent import llm as llm_module

            llm = prefetch_module.MemoLLM(llm_module.BedrockLLM())
            llm_name = f"{llm.name} behind prefetch.MemoLLM"
        except Exception as exc:  # noqa: BLE001 — no AWS is a reportable state
            print(f"no classifier ({type(exc).__name__}: {exc}); rule router only",
                  file=sys.stderr)

    utterances = harness_b_utterances()
    started = time.time()
    if not args.json:
        print(f"Prefetch probe — {len(utterances)} utterance(s), classifier {llm_name}\n")
    results, stats = measure(
        utterances,
        llm=llm,
        chunks_path=settings.chunks_path,
        verbose=not args.json,
    )

    payload = {
        "corpus": "harness-b",
        "utterances": len(utterances),
        "classifier": llm_name,
        "min_words": prefetch_module.MIN_WORDS,
        "min_confidence": prefetch_module.MIN_CONFIDENCE,
        "stats": stats.as_dict(),
        "cases": [r.as_dict() for r in results],
        "seconds": round(time.time() - started, 1),
    }
    if args.out:
        from pathlib import Path

        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print()
        print(format_report(results, stats, llm_name=llm_name))
        print(f"\n  {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
