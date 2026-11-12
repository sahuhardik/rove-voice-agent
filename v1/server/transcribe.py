"""Streaming Amazon Transcribe, with biasing (`docs/06` §8.2, `docs/07` D-05).

D-05 pins Transcribe Streaming and says why: it satisfies **C-2** outright —
IAM permissions, **not** a Bedrock model-access request — and it emits true
streaming partials, which `docs/06` §2.1's speculative prefetch depends on.
What D-05 explicitly leaves unmeasured is the thing this module has to get
right:

> **What is explicitly unmeasured.** Biasing behaviour on *our* confusables.

So biasing here is two layers, and keeping them apart is the design:

**Layer 1 — the service's own custom vocabulary.** §3.4 gives the list:
`ROVE`, `R2-4K`, `R3`, `DUAL`, `DUAL PRO`, `Emergency Lock`, `microSD`,
`hardwire`, `supercapacitor`, the four SSID prefixes and `12345678`. Transcribe
takes this as a `CreateVocabulary` phrase list, with one constraint that
matters and is **not** obvious: for `en-US` a phrase may contain only letters,
apostrophes, full stops and hyphens — **no digits**. `R2-4K` is therefore
unsayable as a phrase and is carried as `R-two-four-K`, with the digit form
restored by layer 2. (A table-format vocabulary in S3 could carry a `DisplayAs`
column and do the restoration service-side; it costs a bucket, and the mapping
has to exist in our process anyway for the alias work below, so it buys
nothing here. That is a judgement, recorded rather than hidden.)

**Layer 2 — the alias table, which is ours.** §3.4, verbatim:

> Post-ASR, a phonetic alias table maps the known confusions ("are two" / "R
> too" / "R2" → `R2?`, "forty" / "4K" → `4K?`, "do all" / "dual" → `DUAL?`)
> into *candidate* tokens carrying their own uncertainty — **never into
> resolved values**.

:func:`alias_candidates` is that table and it returns :class:`AsrCandidate`
objects, every one of them flagged `resolved=False`. Nothing in this module
writes a model into `DiagnosticState`; §3.4 resolves model identity by feature,
and the note that outranks the vendor choice stands:

> *No ASR will reliably separate "R2" from "R3" over road noise.*

Measured on this corpus with Polly-synthesised speech, both of those layers
behave exactly as D-05 predicted: the vocabulary fixes `duel` → `Dual` and
`Wi Fi` → `Wi-Fi`, and it does **not** fix `Rover 24K` → `Rove R2-4K`. The
alias table turns that residue into candidates instead of into a wrong branch.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# --------------------------------------------------------------------------
# Layer 1: the biasing vocabulary (docs/06 §3.4)
# --------------------------------------------------------------------------

#: `en-US` custom-vocabulary phrases may hold only `a-z A-Z ' . -`. Multi-word
#: phrases are joined with hyphens. Digits are rejected by `CreateVocabulary`,
#: which is why the model names appear spelled out here and are restored by
#: :func:`normalise`.
BIASING_PHRASES: tuple[str, ...] = (
    # §3.4's list, in its order.
    "Rove",
    "R-two-four-K",
    "R-three",
    "Dual",
    "Dual-Pro",
    "Emergency-Lock",
    "micro-S-D",
    "hardwire",
    "supercapacitor",
    # The four SSID prefixes (`05` SSID table).
    "Rove-R-two-four-K",
    "Rove-R-two-four-K-Dual",
    "Rove-R-two-four-K-Dual-Pro",
    "Rove-R-three",
    # The published Wi-Fi password, spelled: digits cannot be a phrase.
    "one-two-three-four-five-six-seven-eight",
    # Wi-Fi vocabulary the sessions actually run on.
    "Wi-Fi",
    "S-S-I-D",
    "hotspot",
    "dual-band",
    "gigahertz",
    "W-P-A",
    "network-name",
    "access-point",
    "dashcam",
    "firmware",
    "loop-recording",
    "parking-mode",
    "G-sensor",
    "supercap",
)

#: What `ensure_vocabulary` calls the vocabulary in the account.
DEFAULT_VOCABULARY_NAME = "rove-support-en-us"

#: Transcribe's own streaming parameters. Stabilised partials are what §2.1's
#: speculative prefetch would read, and `high` is the setting that makes a
#: partial worth reading at all.
LANGUAGE_CODE = "en-US"
MEDIA_ENCODING = "pcm"
PARTIAL_STABILITY = "high"


class TranscribeUnavailable(RuntimeError):
    """Streaming ASR is not available. The session continues typed-only."""


def ensure_vocabulary(
    name: str = DEFAULT_VOCABULARY_NAME,
    *,
    phrases: tuple[str, ...] = BIASING_PHRASES,
    region: str | None = None,
    client: Any | None = None,
    timeout_s: float = 180.0,
    poll_s: float = 3.0,
) -> str:
    """Create or update the biasing vocabulary, and wait for it to be `READY`.

    Idempotent, and deliberately **non-fatal**: a caller that cannot create a
    vocabulary still gets a working recogniser, just an unbiased one, and the
    trace records which it got. Biasing is a quality lever, not a guarantee —
    §3.4's guards are the guarantee.

    Returns:
        The vocabulary name if it is `READY`, or `""` if it is not usable.
    """
    try:
        if client is None:
            import boto3

            client = boto3.client("transcribe", region_name=region) if region else boto3.client("transcribe")
        try:
            client.create_vocabulary(
                VocabularyName=name, LanguageCode=LANGUAGE_CODE, Phrases=list(phrases)
            )
        except Exception as exc:  # noqa: BLE001 — already exists is the common case
            if "ConflictException" not in type(exc).__name__ and "already" not in str(exc).lower():
                raise
            state = client.get_vocabulary(VocabularyName=name)["VocabularyState"]
            if state == "READY":
                return name
            if state == "FAILED":
                client.update_vocabulary(
                    VocabularyName=name, LanguageCode=LANGUAGE_CODE, Phrases=list(phrases)
                )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            info = client.get_vocabulary(VocabularyName=name)
            if info["VocabularyState"] == "READY":
                return name
            if info["VocabularyState"] == "FAILED":
                return ""
            time.sleep(poll_s)
        return ""
    except Exception:  # noqa: BLE001 — no credentials, no permission, no service
        return ""


# --------------------------------------------------------------------------
# Layer 2: the alias table (docs/06 §3.4)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AsrCandidate:
    """A token the recogniser *may* have heard, and never a resolved value.

    §3.4: candidates carry "their own uncertainty — never into resolved
    values". `resolved` is `False` on every instance this module makes, and it
    exists as a field so that a future typed-SSID path (§1.4.1, confidence 1.0)
    can produce the same shape with it set.
    """

    token: str
    surface: str
    confidence: float
    reason: str
    resolved: bool = False


#: Written out, the §3.4 confusions plus the ones `01` §2 names. Each entry is
#: (pattern, candidate token, confidence, why). Confidence is **about the
#: mapping**, not about the model: 0.5 means "this is one weak signal", which
#: is exactly §3.4's standing for a spoken model name.
_ALIASES: tuple[tuple[re.Pattern[str], str, float, str], ...] = (
    (re.compile(r"\b(?:are|r)\s*(?:two|too|to|2)\b", re.I), "R2?", 0.5, "R2/are-two"),
    (re.compile(r"\b(?:are|r)\s*(?:three|tree|3)\b", re.I), "R3?", 0.5, "R3/are-three"),
    (re.compile(r"\brover\s*(?:two|2)?\b", re.I), "ROVE?", 0.4, "Rove/Rover"),
    (re.compile(r"\br\s*-?\s*two\s*-?\s*four\s*-?\s*k\b", re.I), "R2-4K?", 0.6, "biased phrase"),
    (re.compile(r"\br\s*-?\s*three\b", re.I), "R3?", 0.6, "biased phrase"),
    (re.compile(r"\b(?:forty|fourty|4\s*k|forte)\b", re.I), "4K?", 0.5, "4K/forty"),
    (re.compile(r"\b(?:dual|duel|do\s*all|doo\s*al|jewel)\b", re.I), "DUAL?", 0.5, "DUAL/duel"),
    (re.compile(r"\bdual\s*pro\b|\bduel\s*pro\b", re.I), "DUAL PRO?", 0.5, "DUAL PRO"),
    (re.compile(r"\b(?:sd|s\s*d|es\s*dee|sb|s\s*b)\b", re.I), "SD?", 0.4, "SD/SB"),
    (re.compile(r"\bmicro\s*-?\s*s\s*-?\s*d\b", re.I), "microSD?", 0.6, "biased phrase"),
    (re.compile(r"\b(?:r\s*s\s*two|rs\s*2)\b", re.I), "RS2?", 0.5, "borescope guard (§3.4)"),
    (re.compile(r"\b(?:r\s*s\s*four|rs\s*4)\b", re.I), "RS4?", 0.5, "borescope guard (§3.4)"),
)

#: Display normalisations: what layer 1 could not spell, restored. These change
#: the *surface string the user reads on screen* (§1.4), not any decision.
_NORMALISERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwi\s+fi\b", re.I), "Wi-Fi"),
    (re.compile(r"\bwifi\b", re.I), "Wi-Fi"),
    (re.compile(r"\br\s*-?\s*two\s*-?\s*four\s*-?\s*k\b", re.I), "R2-4K"),
    (re.compile(r"\br\s*-\s*three\b", re.I), "R3"),
    (re.compile(r"\bmicro\s*-\s*s\s*-\s*d\b", re.I), "microSD"),
    (re.compile(r"\bs\s*-\s*s\s*-\s*i\s*-\s*d\b", re.I), "SSID"),
    (re.compile(r"\bdual\s*-\s*pro\b", re.I), "DUAL PRO"),
    (re.compile(r"\bemergency\s*-\s*lock\b", re.I), "Emergency Lock"),
    (re.compile(r"\bone\s*-?\s*two\s*-?\s*three\s*-?\s*four\s*-?\s*five\s*-?\s*six\s*-?\s*seven\s*-?\s*eight\b", re.I), "12345678"),
    (re.compile(r"\bg\s*-\s*sensor\b", re.I), "G-sensor"),
    (re.compile(r"\bw\s*-\s*p\s*-\s*a\b", re.I), "WPA"),
    (re.compile(r"\b(\d)\s+point\s+(\d)\s*(?:gigahertz|ghz)\b", re.I), r"\1.\2 GHz"),
    (re.compile(r"\b(\d)\s*(?:gigahertz|ghz)\b", re.I), r"\1 GHz"),
)

#: Spelled-out digit runs: "one two three four five six seven eight" is how a
#: user reads the Wi-Fi password, and §4.5 wants it speakable *and* legible.
_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _collapse_digit_runs(text: str, minimum: int = 4) -> str:
    """Join runs of spoken digits into the string the user is reading out."""
    tokens = re.split(r"(\W+)", text)
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if len(run) >= minimum:
            out.append("".join(_DIGIT_WORDS[w.lower()] for w in run))
        else:
            out.extend(run)
        run.clear()

    for token in tokens:
        if token.lower() in _DIGIT_WORDS:
            run.append(token)
        elif token.strip() == "" and run:
            continue  # keep the run alive across the separator
        else:
            flush()
            out.append(token)
    flush()
    return "".join(out)


def normalise(transcript: str) -> str:
    """The transcript as the §1.4 panel should render it.

    Display only. The core is handed this string because §1.4.1 requires the
    same `value` whatever modality produced it, and a user who *typed*
    `Wi-Fi` would not have typed `wi fi` — normalising here is what keeps the
    two modalities comparable, which is what M10 measures.
    """
    text = (transcript or "").strip()
    if not text:
        return ""
    text = _collapse_digit_runs(text)
    for pattern, replacement in _NORMALISERS:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def alias_candidates(transcript: str) -> list[AsrCandidate]:
    """§3.4's phonetic alias table: confusions → *candidates*, never values.

    Every candidate is `resolved=False` and carries a confidence well under
    1.0, because §3.4 is explicit that "a user saying 'R2' is treated as **one
    weak signal**, never as identification". The FSM reads these as signals;
    nothing here writes a model.
    """
    text = (transcript or "")
    if not text.strip():
        return []
    found: dict[str, AsrCandidate] = {}
    for pattern, token, confidence, reason in _ALIASES:
        match = pattern.search(text)
        if match is None:
            continue
        existing = found.get(token)
        if existing is None or existing.confidence < confidence:
            found[token] = AsrCandidate(
                token=token,
                surface=match.group(0),
                confidence=confidence,
                reason=reason,
            )
    return sorted(found.values(), key=lambda c: (-c.confidence, c.token))


# --------------------------------------------------------------------------
# The streaming session
# --------------------------------------------------------------------------


def _ignore(_partial: "Partial") -> None:
    """Default partial sink: the stream still records them on itself."""


def _mean_confidence(alternative: Any) -> float | None:
    """Mean confidence over the *pronounced* items in one alternative.

    Punctuation items carry no useful score and are left out. Returns `None`
    when nothing was scored, which is honest rather than optimistic: a turn
    whose confidence we do not know must not be recorded as a confident one.
    """
    items = getattr(alternative, "items", None) or []
    scores = [
        float(item.confidence)
        for item in items
        if getattr(item, "confidence", None) is not None
        and getattr(item, "item_type", "pronunciation") != "punctuation"
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


#: What a transcript is worth as evidence when the service tells us nothing.
#: §1.4.1 puts typed input at 1.0 and says ASR is lower for the fields §3.4
#: calls confusable; a mid-scale default keeps an unscored turn from claiming
#: either certainty or uselessness.
DEFAULT_ASR_CONFIDENCE = 0.6


@dataclass
class Partial:
    """One hypothesis from the recogniser."""

    text: str
    is_partial: bool
    at: float = field(default_factory=time.time)
    result_id: str = ""
    #: Mean per-item confidence over the pronunciations in this result, or
    #: `None` when the service did not score it (which partials never are).
    #: §1.4.1 wants `{value, modality, confidence}` on every answer, and this
    #: is where the voice channel's third field actually comes from rather
    #: than being invented at the dispatcher.
    confidence: float | None = None


class TranscribeStream:
    """One Transcribe streaming session, fed 20 ms PCM frames.

    The shape is deliberately not a Pipecat/LiveKit STT plugin: `docs/06`
    §8.1.1 warns that the framework's plugin layer "will occasionally need to
    be reached around; we must keep the §2.2 component timings visible through
    it, which is a requirement to verify, not assume". Owning the stream is how
    §2.2 line 3 — *ASR final flush after endpoint* — stays measurable.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        region: str | None = None,
        vocabulary_name: str = "",
        on_partial: Callable[[Partial], None] | None = None,
        client: Any | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.region = region
        self.vocabulary_name = vocabulary_name
        self.on_partial: Callable[[Partial], None] = on_partial or _ignore
        self._client = client
        self._stream: Any = None
        self._pump: asyncio.Task | None = None
        self._started_at = 0.0
        self.partials: list[Partial] = []
        self.finals: list[Partial] = []
        self.bytes_sent = 0
        self.first_partial_latency_ms: float | None = None
        self.error: str = ""

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Open the stream. Raises :class:`TranscribeUnavailable` if it cannot."""
        try:
            from amazon_transcribe.client import TranscribeStreamingClient

            client = self._client
            if client is None:
                import boto3

                region = self.region or boto3.session.Session().region_name or "us-east-1"
                client = TranscribeStreamingClient(region=region)
            kwargs: dict[str, Any] = {}
            if self.vocabulary_name:
                kwargs["vocabulary_name"] = self.vocabulary_name
            self._stream = await client.start_stream_transcription(
                language_code=LANGUAGE_CODE,
                media_sample_rate_hz=self.sample_rate,
                media_encoding=MEDIA_ENCODING,
                enable_partial_results_stabilization=True,
                partial_results_stability=PARTIAL_STABILITY,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — credentials, region, service
            self.error = f"{type(exc).__name__}: {exc}"
            raise TranscribeUnavailable(self.error) from exc
        self._started_at = time.time()
        self._pump = asyncio.create_task(self._read(), name="transcribe-read")

    async def send(self, pcm: bytes) -> None:
        """Push one chunk of 16-bit mono PCM at the stream's sample rate."""
        if self._stream is None or not pcm:
            return
        self.bytes_sent += len(pcm)
        try:
            await self._stream.input_stream.send_audio_event(audio_chunk=pcm)
        except Exception as exc:  # noqa: BLE001 — the stream closed under us
            self.error = self.error or f"{type(exc).__name__}: {exc}"

    async def close(self, *, drain_timeout: float = 5.0) -> None:
        """End the audio, then wait for the final results §2.2 line 3 counts."""
        if self._stream is not None:
            try:
                await self._stream.input_stream.end_stream()
            except Exception:  # noqa: BLE001
                pass
        if self._pump is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._pump), timeout=drain_timeout)
            except (TimeoutError, asyncio.CancelledError):
                self._pump.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._stream = None

    # -- reading ----------------------------------------------------------

    async def _read(self) -> None:
        assert self._stream is not None
        try:
            async for event in self._stream.output_stream:
                results = getattr(getattr(event, "transcript", None), "results", None)
                if not results:
                    continue
                for result in results:
                    alternatives = getattr(result, "alternatives", None) or []
                    if not alternatives:
                        continue
                    text = alternatives[0].transcript or ""
                    if not text:
                        continue
                    partial = Partial(
                        text=text,
                        is_partial=bool(result.is_partial),
                        result_id=getattr(result, "result_id", "") or "",
                        confidence=_mean_confidence(alternatives[0]),
                    )
                    if partial.is_partial:
                        self.partials.append(partial)
                        if self.first_partial_latency_ms is None and self._started_at:
                            self.first_partial_latency_ms = round(
                                1000.0 * (partial.at - self._started_at), 1
                            )
                    else:
                        self.finals.append(partial)
                    self.on_partial(partial)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the stream ends with the turn
            self.error = self.error or f"{type(exc).__name__}: {exc}"

    # -- what the turn heard ----------------------------------------------

    @property
    def latest(self) -> str:
        """The best hypothesis so far: finals joined, plus the live partial."""
        return self.text_since(0)

    @property
    def final_transcript(self) -> str:
        return " ".join(p.text.strip() for p in self.finals if p.text.strip()).strip()

    # -- turn boundaries --------------------------------------------------
    #
    # One stream lasts the whole session rather than one per turn. Opening a
    # stream costs a TLS handshake and an HTTP/2 upgrade, and paying that at
    # the start of every turn would clip the first word of it — which is the
    # §3.4 failure the whole design is trying to avoid. So the turn boundary
    # is ours (`server/endpointing.py` decides it) and the stream is cut with
    # a cursor rather than with a reconnection.

    def cursor(self) -> int:
        """A mark in the final-results list: "the turn starts here"."""
        return len(self.finals)

    def text_since(self, cursor: int) -> str:
        """Everything heard since `cursor`, live partial included."""
        finals = self.finals[cursor:]
        parts = [p.text for p in finals]
        if self.partials and (not finals or self.partials[-1].at > finals[-1].at):
            parts.append(self.partials[-1].text)
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    def confidence_since(self, cursor: int) -> float:
        """What the recogniser thought of everything heard since `cursor`.

        Weighted by nothing: §3.4 treats a spoken model name as "one weak
        signal" whatever the score, so this number goes into the evidence
        record and the trace, never into a branch. Falls back to
        :data:`DEFAULT_ASR_CONFIDENCE` when the service scored nothing.
        """
        scores = [p.confidence for p in self.finals[cursor:] if p.confidence is not None]
        if not scores:
            return DEFAULT_ASR_CONFIDENCE
        return round(sum(scores) / len(scores), 4)

    async def await_final(self, cursor: int, *, timeout: float = 1.0) -> float:
        """Wait for a final result past `cursor`. Returns the wait, in ms.

        This is **§2.2 line 3** — "ASR final flush after endpoint", budgeted at
        80 ms median and 200 ms at p95. Streaming ASR has already transcribed
        the audio; what is outstanding at the endpoint is finalisation and
        punctuation. Measuring it needs the wait to be a separate, timed thing
        rather than something hidden inside a plugin, which is why the stream
        is ours (see the class docstring).
        """
        started = time.perf_counter()
        deadline = started + timeout
        while time.perf_counter() < deadline:
            if len(self.finals) > cursor:
                break
            await asyncio.sleep(0.01)
        return round((time.perf_counter() - started) * 1000, 1)
