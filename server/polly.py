"""Amazon Polly, Neural engine (`docs/07` D-10) — whole and incremental.

Polly is **pinned** rather than conditional: it is a managed service governed
by IAM, not by Bedrock model access, so constraint **C-2** does not gate it and
no approval is waiting on anyone.

Two surfaces, and the split is `docs/06` §2.2 line 7.

:func:`synthesize_pcm` is one `synthesize_speech` call for one complete
utterance, cached on disk. Phase 2b used it for the greeting and it is still
what the Pipecat fallback (`server/pipeline.py`) uses.

:func:`synthesize_incremental` is the Phase 3 path, and it exists because line 7
is explicit about what it is measuring:

> **TTS time-to-first-audio** — 70 ms best case, 120 ms target median, 320 ms at
> p95. *Requires streaming synthesis that emits on a partial clause, not on a
> complete sentence.*

Whole-utterance synthesis cannot hit that for any reply longer than a sentence,
because the wait before first audio scales with the whole reply. So the reply is
cut at clause boundaries (:class:`ClauseBuffer`), the first clause is
synthesised and played the moment it comes back, and the rest are synthesised
one ahead of playout. Time-to-first-audio then scales with the **first clause**
instead of with the reply, which is the whole of the win.

What it costs, said plainly: one Polly request per clause instead of one per
reply, and a prosodic seam at each cut — Polly gives a clause synthesised alone
a falling intonation it would not have had mid-sentence. The cut therefore
prefers real punctuation, which is a prosodic break anyway. §2.2 line 7 accepts
that trade by asking for partial-clause emission in the first place.

**Where the text comes from.** :func:`synthesize_incremental` takes an iterable
*or* an async iterable of text fragments, so a true token stream can be piped
straight into it. Today the reply arrives whole — `agent.core.diagnose` is
synchronous and `agent/` is not this milestone's to change — so the stream is a
one-element iterable and the incremental behaviour starts at the clause
splitter. The seam is here, ready, and `server/README.md` says so rather than
claiming a token stream that does not exist.

PCM, 16 kHz, mono, 16-bit little-endian — the format both transports take, so
nothing resamples on the way out.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterable


class PollyUnavailable(RuntimeError):
    """Synthesis failed. The session continues without the greeting."""


def cache_key(text: str, voice: str, engine: str, sample_rate: int) -> str:
    digest = hashlib.sha256(
        "|".join([text, voice, engine, str(sample_rate)]).encode("utf-8")
    ).hexdigest()
    return f"{voice}-{engine}-{sample_rate}-{digest[:16]}.pcm"


def synthesize_pcm(
    text: str,
    *,
    voice: str = "Amy",
    engine: str = "neural",
    sample_rate: int = 16000,
    cache_dir: Path | None = None,
    client: Any | None = None,
) -> bytes:
    """Synthesise `text` to raw PCM, caching the result.

    Args:
        text: What to say.
        voice: A Polly voice id that supports `engine`.
        engine: `neural` per D-10. Standard would also work and is not what we
            chose.
        sample_rate: 8000 or 16000 for PCM output.
        cache_dir: Where to keep the bytes. `None` disables caching.
        client: A boto3 Polly client, for tests. Built on demand otherwise.

    Raises:
        PollyUnavailable: Credentials, permissions or the service itself.
    """
    path: Path | None = None
    if cache_dir is not None:
        path = cache_dir / cache_key(text, voice, engine, sample_rate)
        if path.exists():
            return path.read_bytes()
    try:
        if client is None:
            import boto3  # imported here so an import of this module costs nothing

            client = boto3.client("polly")
        response = client.synthesize_speech(
            Text=text,
            Engine=engine,
            VoiceId=voice,
            OutputFormat="pcm",
            SampleRate=str(sample_rate),
        )
        audio = response["AudioStream"].read()
    except Exception as exc:  # noqa: BLE001 — botocore raises a wide family
        raise PollyUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if not audio:
        raise PollyUnavailable("Polly returned no audio")
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
        except OSError:
            pass
    return audio


def duration_ms(pcm: bytes, sample_rate: int) -> int:
    """How long a mono 16-bit PCM buffer plays for."""
    return int(1000 * len(pcm) / 2 / sample_rate)


# --------------------------------------------------------------------------
# Clause splitting (docs/06 §2.2 line 7: "emits on a partial clause")
# --------------------------------------------------------------------------

#: The first chunk is the one §2.2 line 7 is measuring, so it is allowed to be
#: short — but not so short that Polly has no prosody to work with and the
#: request overhead dominates the audio it returns. Two or three words is a
#: tone, not a clause.
FIRST_CHUNK_MIN_CHARS = 24

#: Every chunk after the first. Longer, because once audio is playing the
#: remaining synthesis is hidden behind it and the only thing left to optimise
#: is seam count.
CHUNK_MIN_CHARS = 70

#: A hard ceiling, so a reply with no punctuation in it still streams. Cut at a
#: word boundary rather than mid-word.
CHUNK_MAX_CHARS = 220

#: Where a clause may be cut. Sentence enders first, then the softer marks.
#: Each requires trailing whitespace, so `2.4 GHz`, `R2-4K` and `12345678`
#: survive intact — the §3.4 confusables are exactly the strings a naive
#: full-stop split would mangle.
_CUT = re.compile(r"(?<=[.!?])\s+|(?<=[;:])\s+|(?<=,)\s+|(?<=—)\s*|\s+-\s+")


class ClauseBuffer:
    """Text in, speakable chunks out, as soon as each one is whole.

    Stateful on purpose: it is fed fragments in arrival order and yields a
    chunk the moment the text so far contains a cut point far enough in. The
    first chunk is held to :data:`FIRST_CHUNK_MIN_CHARS` and every one after it
    to :data:`CHUNK_MIN_CHARS`, which is how "emit early, then stop churning"
    is expressed without a second policy knob.
    """

    def __init__(
        self,
        *,
        first_min_chars: int = FIRST_CHUNK_MIN_CHARS,
        min_chars: int = CHUNK_MIN_CHARS,
        max_chars: int = CHUNK_MAX_CHARS,
    ) -> None:
        self.first_min_chars = first_min_chars
        self.min_chars = min_chars
        self.max_chars = max_chars
        self._pending = ""
        self._emitted = 0

    @property
    def minimum(self) -> int:
        return self.first_min_chars if self._emitted == 0 else self.min_chars

    def push(self, fragment: str) -> list[str]:
        """Add text. Returns every chunk that is now complete, in order."""
        self._pending += fragment or ""
        out: list[str] = []
        while True:
            piece = self._take()
            if piece is None:
                return out
            out.append(piece)

    def flush(self) -> list[str]:
        """Whatever is left, as one final chunk. Idempotent."""
        remainder = self._pending.strip()
        self._pending = ""
        if not remainder:
            return []
        self._emitted += 1
        return [remainder]

    # -- one cut ----------------------------------------------------------

    def _take(self) -> str | None:
        minimum = self.minimum
        for match in _CUT.finditer(self._pending):
            head = self._pending[: match.start()].strip()
            if len(head) >= minimum:
                self._pending = self._pending[match.end() :]
                self._emitted += 1
                return head
        if len(self._pending) >= self.max_chars:
            # No punctuation to lean on. Cut at the last word boundary inside
            # the ceiling, because a chunk that splits a word is audible.
            window = self._pending[: self.max_chars]
            cut = window.rfind(" ")
            if cut < minimum:
                cut = self.max_chars
            head = self._pending[:cut].strip()
            self._pending = self._pending[cut:].lstrip()
            if head:
                self._emitted += 1
                return head
        return None


def split_clauses(text: str, **kwargs: Any) -> list[str]:
    """:class:`ClauseBuffer` over a complete string. The common case."""
    buffer = ClauseBuffer(**kwargs)
    return buffer.push(text or "") + buffer.flush()


# --------------------------------------------------------------------------
# Incremental synthesis (docs/06 §2.1, §2.2 line 7)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Clip:
    """One synthesised chunk, in the order it must be played."""

    index: int
    text: str
    pcm: bytes
    #: How long Polly took on *this* chunk. The first clip's number is §2.2
    #: line 7; the sum is what whole-utterance synthesis would have charged
    #: before a single sample was audible.
    synthesis_ms: float
    sample_rate: int

    @property
    def duration_ms(self) -> int:
        return duration_ms(self.pcm, self.sample_rate)


def _one(fragment: str) -> list[str]:
    """A pre-split fragment, as a chunk list. Empty strings are not chunks."""
    text = (fragment or "").strip()
    return [text] if text else []


async def _fragments(source: Any) -> AsyncIterator[str]:
    """Normalise an iterable or an async iterable of text into one shape."""
    if hasattr(source, "__aiter__"):
        async for fragment in source:
            yield fragment
        return
    for fragment in source:
        yield fragment


async def synthesize_incremental(
    source: Iterable[str] | AsyncIterator[str] | str,
    *,
    voice: str = "Amy",
    engine: str = "neural",
    sample_rate: int = 16000,
    cache_dir: Path | None = None,
    client: Any | None = None,
    lookahead: int = 1,
    split: bool = True,
    buffer: ClauseBuffer | None = None,
) -> AsyncIterator[Clip]:
    """Clause-by-clause synthesis, yielding each clip the moment it is ready.

    Args:
        source: The reply text — a string, an iterable of fragments, or an
            async iterable of them (a token stream, when there is one).
        lookahead: How many chunks may be synthesised *ahead* of the one being
            yielded. 1 keeps the next clause warm behind the one playing,
            which is enough to hide synthesis under playout for any clause
            longer than its own synthesis time, and bounds the spend when the
            caller barges in and the rest of the reply is thrown away.
        split: Whether to run the clause splitter over `source`. `False` means
            the caller has already split it and each fragment is one chunk —
            which is what `server/livekit_agent.py` does, because it needs the
            chunk list up front to say which clause was playing when the
            caller cut in (§2.1's `sub_step_index`).

    Raises:
        PollyUnavailable: Propagated from the **first** chunk only. A failure
            part way through is not raised, because audio is already playing
            and tearing the utterance down is worse than ending it short; the
            generator simply stops.
    """
    if isinstance(source, str):
        source = [source]
    clauses = buffer or ClauseBuffer()
    kwargs: dict[str, Any] = {
        "voice": voice,
        "engine": engine,
        "sample_rate": sample_rate,
        "cache_dir": cache_dir,
        "client": client,
    }
    gate = asyncio.Semaphore(max(1, lookahead + 1))
    tasks: list[asyncio.Task] = []
    index = 0

    async def synthesise(position: int, text: str) -> Clip:
        async with gate:
            started = time.perf_counter()
            pcm = await asyncio.to_thread(synthesize_pcm, text, **kwargs)
            return Clip(
                index=position,
                text=text,
                pcm=pcm,
                synthesis_ms=round((time.perf_counter() - started) * 1000, 1),
                sample_rate=sample_rate,
            )

    yielded = 0
    try:
        async for fragment in _fragments(source):
            ready = clauses.push(fragment) if split else _one(fragment)
            for text in ready:
                tasks.append(asyncio.create_task(synthesise(index, text)))
                index += 1
            # Hand over everything already finished before asking the source
            # for more text, so the first clause reaches the room without
            # waiting on a token stream that may still be mid-sentence.
            while tasks and tasks[0].done():
                try:
                    clip = await tasks.pop(0)
                except PollyUnavailable:
                    if yielded == 0:
                        raise
                    return
                yielded += 1
                yield clip
        for text in clauses.flush() if split else []:
            tasks.append(asyncio.create_task(synthesise(index, text)))
            index += 1
        while tasks:
            try:
                clip = await tasks.pop(0)
            except PollyUnavailable:
                if yielded == 0:
                    raise
                return
            yielded += 1
            yield clip
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
