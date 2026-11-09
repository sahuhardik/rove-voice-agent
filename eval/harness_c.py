"""Harness C -- end-to-end spoken, through the real transport (docs/06 §7.3).

    Synthesised speech over the real pipeline, with added road noise [...]
    Two rules that are easy to get wrong and that invalidate the results
    silently when you do: the audio is injected **at real-time pace in 20 ms
    frames** (§1.4.2), and it goes **through an actual WebRTC peer
    connection** -- a headless browser or a native WebRTC client -- not
    spliced in behind the transport.

Both rules are kept by *not having a way to break them*. The microphone is
`server/livekit_peer.HeadlessParticipant`, the same stand-in
`server/verify_livekit.py` uses: it joins a real room on a real media server
with a real minted credential and pushes 20 ms `rtc.AudioFrame`s through
`AudioSource.capture_frame`, which blocks until the source has room. The SDK's
queue is the clock. There is no "inject" entry point into the agent anywhere in
this module -- the only way audio reaches the recogniser is by being sent.

What only this harness can measure (§7.3)
-----------------------------------------

* **The ASR-degradation pass `03` demands.** `03` says of itself: *"No ASR
  degradation yet... every utterance here is a clean transcript."* §7.3 names
  the corruptions to inject -- `R2`↔`R3`, `4K`↔"forty", `SD`↔`SB`, clipped
  turns, mis-segmented turns, barge-in mid-instruction -- and states the target
  in a way that is easy to get backwards:

  > The measurable target here is **not** "still gets it right" -- it is "does
  > not act on a mis-heard model", i.e. M1's `UNKNOWN`-handling branch fires.

  So :func:`corruption_verdict` scores exactly that and nothing else: the
  reported model is `unknown`, and the step proposed is not one
  `eval/ontology.py` marks `model_specific`. That is `eval/harness.py`'s own M1
  rule, read rather than re-implemented, so the two harnesses cannot disagree
  about what M1 means.

* **M7 and turn-taking**, which `03` correctly says the text set does not test.
  M7 is read off the `latency.turn` records `server/latency.py` writes -- the
  same instrumentation the trace and the ladder read, so the harness cannot be
  reporting one latency while the session acted on another. Harness C does not
  compute M7 itself; it drives turns and reads the instrument.

**M10, and why the typed leg replays the heard text.** §7.2 defines M10 as the
same answer "replayed through the *other* modality", with the next step
required to be **identical**. The value replayed is therefore the transcript
the voice leg actually produced, typed verbatim into a second session with a
fresh `DiagnosticState` -- same value, two modalities. Replaying `03`'s written
sentence instead would fold ASR error into the modality number and measure two
things at once: whether Transcribe heard the words (reported separately here as
`asr_exact`) and whether the FSM branched on modality (which is the only thing
M10 is about, and the only thing §1.4.1 forbids).

What this harness does **not** do, stated rather than implied
-------------------------------------------------------------

* **It does not pre-populate the ledger.** Harness A turns `03`'s `Tried:`
  field into `DiagnosticState.ledger` entries before the turn. There is no API
  on a live session that could do that, and inventing one would be a test
  surface the product does not have. The utterances carry what was tried *in
  words* ("I've forgotten the network and put the password back in"), so the
  agent has to build the ledger from speech. That is a harder test and a
  different one: **M4 figures from Harness C are not comparable with Harness
  A's** and are not reported as if they were.
* **It does not score M2/M3/M5/M6.** Those are Harness A and B's, over a
  pre-populated state, and a second set of numbers from a different starting
  state would be two scores for one metric. The branch each case took is in the
  record so a reader can see it; it is not dressed as a score.
* **It does not measure §2.2 lines 1 and 9.** No browser has been on this link.
  The peer's own view of the loopback leg is reported as `loopback_ms` under
  its own name, which is what `server/latency.py` says Harness C may do with
  it, and never as a browser number.
* **It does not vary accent or speaker colouration.** §7.3 asks for road noise,
  laptop-speaker colouration and accent variation; this module injects the
  first and says so. One Polly voice, one synthesis path: colouration and
  accent are **not covered** by this run, and no number here should be read as
  evidence about either.

The one thing done to every fixture, and the finding behind it
--------------------------------------------------------------

Polly leaves roughly 600 ms of silence at a full stop. §2.3's shortest
hangover is 600 ms. The first run of this harness therefore measured something
nobody intended: on `EVAL-02` the endpointer closed the turn **after the first
sentence**, the core ran on half an utterance, and everything the caller said
between that endpoint and the end of the spoken reply — 16.5 s of it — was
discarded as echo when `_speak` moved the recogniser cursor past it. The reply
was to "It's got a message on it saying card error" and "The card's in there
though, I just checked" never reached a turn.

That is a real property of the pipeline and it is reported as a finding rather
than tuned away. But a harness whose every case is accidentally a
mis-segmentation case cannot measure anything else, and could not tell its own
deliberate mis-segmentation case apart from the rest. So :func:`compress_silences`
caps every silence *inside* a fixture at :data:`MAX_INTERNAL_SILENCE_MS`, on
every pass equally, before any other degradation is applied. Phrase gaps
survive; the full-stop pause that would close the turn does not. The
mis-segmented corruption case then re-inserts a gap deliberately, and the gap
it inserts is the only one in that fixture.
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import httpx
import numpy as np
import websockets

from server import livekit_peer, polly
from server import latency as latency_module
from server.config import Settings

from . import ontology
from .harness import Scenario, load_scenarios

# --------------------------------------------------------------------------
# The three passes
# --------------------------------------------------------------------------

CLEAN = "clean"
NOISE = "noise"
CORRUPTION = "corruption"
PASSES: tuple[str, ...] = (CLEAN, NOISE, CORRUPTION)

#: Signal-to-noise ratio for the noise pass, in dB over the *speech* of the
#: fixture (the lead-in and tail silence are excluded from the speech RMS, or
#: every fixture would get a different effective SNR depending on how much of
#: it was silence). 15 dB is a car at speed with a close microphone: clearly
#: audible road noise, not a destroyed signal. One stated level rather than a
#: sweep -- a sweep is a different experiment and would multiply the runtime of
#: a real-time-paced harness by its length.
NOISE_SNR_DB = 15.0

#: Which scenarios the noise pass runs over. Every third one of `03`'s thirty,
#: which lands on all four parts (simple ×3, contextual ×3, complex ×3,
#: escalation ×1) without anyone choosing which scenarios are convenient.
#: **Why a subset:** the pass is about the front end -- VAD segmentation and
#: the recogniser under degradation -- and every case costs its own wall-clock
#: seconds because the audio is paced in real time. Ten cases exercise the
#: front end on four parts; thirty would cost three times the minutes to
#: exercise the same front end.
NOISE_IDS: tuple[str, ...] = tuple(f"EVAL-{n:02d}" for n in range(3, 31, 3))

#: `02`/`03` never name a model in an utterance, so a corruption case has to
#: put one there: the caller states the model, in the confusable surface form
#: `01` §2 names. Every case records what it did to the fixture in
#: :attr:`Case.construction`, because a corrupted fixture is not `03`'s
#: sentence and a report that implied it was would be lying by omission.
CLIP_FRACTION = 0.30

#: A gap longer than the longest §2.3 hangover, placed mid-sentence: the
#: endpointer closes the turn where the caller had not finished, which is what
#: "mis-segmented turn" means on this pipeline.
GAP_MS = 1400

#: The longest silence a fixture may contain before the degradations are
#: applied. Comfortably under §2.3's 600 ms hangover floor and comfortably
#: above a phrase gap — see the module docstring for the measurement that made
#: this necessary and for what it costs in fidelity.
MAX_INTERNAL_SILENCE_MS = 250


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One spoken run: what the microphone says, and what was done to it."""

    case_id: str
    pass_name: str
    scenario_id: str
    part: str
    #: What the microphone says, in order. More than one entry only where the
    #: case is about turn-taking -- the barge-in case, whose second utterance
    #: is spoken over the agent's reply to the first.
    utterances: tuple[str, ...]
    #: Why this fixture is not `03`'s sentence verbatim. Empty on the clean
    #: pass, where it is.
    construction: str = ""
    #: The §7.3 corruption this case injects, or "" on clean and noise.
    corruption: str = ""
    #: What the caller actually owns, where the case states a model at all.
    #: Never used as an expectation -- the point of the pass is that the agent
    #: must not resolve *any* model from a spoken name.
    true_model: str = ""
    noise_snr_db: float | None = None
    clip_fraction: float = 0.0
    gap_after_word: int = 0
    #: Speak the second utterance over the agent's reply to the first.
    barge_in: bool = False

    @property
    def degraded(self) -> bool:
        return bool(
            self.noise_snr_db or self.clip_fraction or self.gap_after_word or self.barge_in
        )


@dataclass(frozen=True)
class CorruptionSpec:
    """One of §7.3's named corruptions, bound to a scenario."""

    name: str
    scenario_id: str
    note: str
    #: Spoken ahead of `03`'s own sentence, so the caller's words are still in
    #: the fixture and the turn still has a symptom in it.
    prefix: str = ""
    true_model: str = ""
    clip_fraction: float = 0.0
    gap_after_word: int = 0
    #: Spoken over the agent's reply to the first utterance.
    interrupt_with: str = ""


#: §7.3's list, each bound to the scenario it sits most naturally on.
CORRUPTIONS: tuple[CorruptionSpec, ...] = (
    CorruptionSpec(
        name="r2_heard_as_r3",
        scenario_id="EVAL-03",
        prefix="My camera is the Rove R3.",
        true_model="R2-4K",
        note=(
            "§7.3 `R2`↔`R3`, forward. The caller owns an R2-4K and the fixture "
            "says R3; the recogniser is handed the confusable surface rather "
            "than being asked to produce it on demand."
        ),
    ),
    CorruptionSpec(
        name="r3_heard_as_r2",
        scenario_id="EVAL-13",
        prefix="Mine is the are two, four K one.",
        true_model="R3",
        note=(
            "§7.3 `R2`↔`R3`, reverse, in §3.4's own spelling of the confusion "
            "(\"are two\" / \"R2\"). The caller owns an R3."
        ),
    ),
    CorruptionSpec(
        name="4k_heard_as_forty",
        scenario_id="EVAL-04",
        prefix="It's the Rove R2 forty K.",
        true_model="R2-4K",
        note="§7.3 `4K`↔\"forty\": the model number said as a quantity.",
    ),
    CorruptionSpec(
        name="sd_heard_as_sb",
        scenario_id="EVAL-02",
        prefix="The SB card in it is the one that came with the camera.",
        note=(
            "§7.3 `SD`↔`SB`. Not a model name -- the thing mis-heard is the "
            "card, and the question is whether a mis-heard card word turns "
            "into a card-specific instruction."
        ),
    ),
    CorruptionSpec(
        name="clipped_turn",
        scenario_id="EVAL-05",
        clip_fraction=CLIP_FRACTION,
        note=(
            "§7.3 clipped turn: the last 30 % of the audio is cut mid-word, as "
            "a caller whose connection dropped the tail of their sentence."
        ),
    ),
    CorruptionSpec(
        name="missegmented_turn",
        scenario_id="EVAL-01",
        gap_after_word=9,
        note=(
            f"§7.3 mis-segmented turn: a {GAP_MS} ms gap mid-sentence, longer "
            "than the longest §2.3 hangover, so the endpointer closes a turn "
            "the caller had not finished."
        ),
    ),
    CorruptionSpec(
        name="barge_in_mid_reply",
        scenario_id="EVAL-10",
        interrupt_with="Sorry — hang on. It's the Rove are two, four K.",
        true_model="R2-4K",
        note=(
            "§7.3 barge-in mid-instruction: the caller cuts across the agent's "
            "reply with a spoken model name. Two things are under test at once "
            "-- that §2.1's barge-in fires, and that the model claim it "
            "carries still produces UNKNOWN."
        ),
    ),
)


def build_cases(
    scenarios: Sequence[Scenario] | None = None,
    passes: Sequence[str] = PASSES,
    ids: Sequence[str] | None = None,
) -> list[Case]:
    """Every case of every requested pass, in a stable order."""
    scenarios = list(scenarios if scenarios is not None else load_scenarios())
    by_id = {s.id: s for s in scenarios}
    wanted = set(ids) if ids else None
    cases: list[Case] = []

    if CLEAN in passes:
        for scenario in scenarios:
            if wanted and scenario.id not in wanted:
                continue
            cases.append(
                Case(
                    case_id=f"{CLEAN}:{scenario.id}",
                    pass_name=CLEAN,
                    scenario_id=scenario.id,
                    part=scenario.part,
                    utterances=(scenario.utterance,),
                    construction="docs/03's utterance, spoken verbatim",
                )
            )

    if NOISE in passes:
        for scenario_id in NOISE_IDS:
            if wanted and scenario_id not in wanted:
                continue
            scenario = by_id[scenario_id]
            cases.append(
                Case(
                    case_id=f"{NOISE}:{scenario.id}",
                    pass_name=NOISE,
                    scenario_id=scenario.id,
                    part=scenario.part,
                    utterances=(scenario.utterance,),
                    construction=(
                        f"docs/03's utterance with road noise mixed in at "
                        f"{NOISE_SNR_DB:.0f} dB SNR over the speech"
                    ),
                    noise_snr_db=NOISE_SNR_DB,
                )
            )

    if CORRUPTION in passes:
        for spec in CORRUPTIONS:
            if wanted and spec.scenario_id not in wanted:
                continue
            scenario = by_id[spec.scenario_id]
            spoken = (
                f"{spec.prefix} {scenario.utterance}".strip()
                if spec.prefix
                else scenario.utterance
            )
            utterances = (spoken,)
            if spec.interrupt_with:
                utterances = (spoken, spec.interrupt_with)
            construction = spec.note
            if spec.prefix:
                construction += f' Fixture prepends: "{spec.prefix}"'
            cases.append(
                Case(
                    case_id=f"{CORRUPTION}:{spec.name}",
                    pass_name=CORRUPTION,
                    scenario_id=scenario.id,
                    part=scenario.part,
                    utterances=utterances,
                    construction=construction,
                    corruption=spec.name,
                    true_model=spec.true_model,
                    clip_fraction=spec.clip_fraction,
                    gap_after_word=spec.gap_after_word,
                    barge_in=bool(spec.interrupt_with),
                )
            )
    return cases


# --------------------------------------------------------------------------
# The microphone fixture, and what is done to it
# --------------------------------------------------------------------------

#: Below this the speech is a gap between words rather than a word, and
#: counting it in the speech RMS would quietly raise the SNR of a fixture that
#: happened to pause a lot.
_SPEECH_FLOOR = 300


def _pcm_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float64)


def _float_to_pcm(samples: np.ndarray) -> bytes:
    return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()


def speech_rms(samples: np.ndarray) -> float:
    """RMS over the parts of the buffer that are actually speech."""
    voiced = samples[np.abs(samples) > _SPEECH_FLOOR]
    if voiced.size == 0:
        voiced = samples
    return float(np.sqrt(np.mean(np.square(voiced)))) if voiced.size else 0.0


def road_noise(count: int, sample_rate: int, *, seed: int) -> np.ndarray:
    """Cabin noise: a tilted broadband floor plus an engine order.

    Shaped in the frequency domain rather than with a recursive filter --
    vectorised, exactly reproducible from `seed`, and easier to say what it is:
    white noise whose magnitude is rolled off above 160 Hz at roughly
    6 dB/octave (tyre and wind noise, which is where cabin noise lives), with a
    narrow engine order at 85 Hz and its second harmonic on top. Unit RMS out;
    the caller scales it to the SNR it wants.
    """
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(count)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(count, 1.0 / sample_rate)
    tilt = 1.0 / np.sqrt(1.0 + (freqs / 160.0) ** 2)
    noise = np.fft.irfft(spectrum * tilt, n=count)

    t = np.arange(count) / float(sample_rate)
    # A touch of wobble, so the order is not a pure tone a notch filter would
    # remove and no real engine ever produced.
    wobble = 1.0 + 0.02 * np.sin(2 * math.pi * 0.7 * t)
    engine = np.sin(2 * math.pi * 85.0 * t * wobble) + 0.4 * np.sin(
        2 * math.pi * 170.0 * t * wobble
    )
    mixed = noise / (np.std(noise) or 1.0) + 0.35 * engine
    return mixed / (np.sqrt(np.mean(np.square(mixed))) or 1.0)


def mix_noise(pcm: bytes, *, sample_rate: int, snr_db: float, seed: int) -> bytes:
    """Road noise under the whole fixture, at `snr_db` over its speech."""
    samples = _pcm_to_float(pcm)
    if samples.size == 0:
        return pcm
    target = speech_rms(samples) * (10.0 ** (-snr_db / 20.0))
    noise = road_noise(samples.size, sample_rate, seed=seed) * target
    return _float_to_pcm(samples + noise)


def compress_silences(
    pcm: bytes, *, sample_rate: int, max_ms: int = MAX_INTERNAL_SILENCE_MS
) -> bytes:
    """Cap every silent run in the buffer at `max_ms`, leading and trailing too.

    Frame-wise on the same 20 ms grid the transport uses, so the result is
    still a whole number of frames and the pacing is unchanged. A frame counts
    as silence when nothing in it clears the speech floor — which is a
    deliberately crude test, and the right one here: the VAD on the other end
    is making a decision of the same shape.
    """
    frame = sample_rate * livekit_peer.FRAME_MS // 1000
    samples = np.frombuffer(pcm, dtype="<i2")
    usable = samples.size - samples.size % frame
    if usable <= 0:
        return pcm
    frames = samples[:usable].reshape(-1, frame)
    quiet = np.max(np.abs(frames.astype(np.int32)), axis=1) <= _SPEECH_FLOOR
    budget = max(1, int(max_ms / livekit_peer.FRAME_MS))

    keep = np.ones(frames.shape[0], dtype=bool)
    run = 0
    for index, is_quiet in enumerate(quiet):
        run = run + 1 if is_quiet else 0
        if run > budget:
            keep[index] = False
    return frames[keep].tobytes() + samples[usable:].tobytes()


def clip_tail(pcm: bytes, *, sample_rate: int, fraction: float) -> bytes:
    """Cut `fraction` off the end, at a 20 ms frame boundary."""
    frame_bytes = sample_rate * 2 * livekit_peer.FRAME_MS // 1000
    keep = int(len(pcm) * (1.0 - fraction))
    keep -= keep % frame_bytes
    return pcm[: max(frame_bytes, keep)]


def _seed_for(case_id: str) -> int:
    """A stable seed per case, so a noise run is reproducible by name.

    Derived from the bytes of the id rather than from `hash()`, which is salted
    per process: a fixture that was different noise on every run would make a
    failure unrepeatable, and an unrepeatable failure is not evidence.
    """
    return int.from_bytes(case_id.encode("utf-8")[:8].ljust(8, b"\0"), "big") % (2**31)


def synthesize_case(
    case: Case, index: int, settings: Settings, *, sample_rate: int
) -> tuple[bytes, str]:
    """The PCM for utterance `index` of `case`, and the text it says.

    One Polly call per fragment, cached on disk by `server/polly.py`, so a
    re-run of the same case costs no synthesis. The mis-segmented case is the
    only one that is two calls: the gap has to fall on a word boundary, and the
    only way to know where a word boundary is without a forced aligner is to
    synthesise the two halves separately and join them with silence.
    """
    text = case.utterances[index]
    fragments = [text]
    if case.gap_after_word and index == 0:
        words = text.split()
        cut = min(case.gap_after_word, max(1, len(words) - 1))
        fragments = [" ".join(words[:cut]), " ".join(words[cut:])]

    def speak(fragment: str) -> bytes:
        # Conditioned the moment it comes back, before anything else touches
        # it: the degradations below are meant to be the only difference
        # between a clean fixture and a degraded one.
        return compress_silences(
            polly.synthesize_pcm(
                fragment,
                voice=settings.polly_voice,
                engine=settings.polly_engine,
                sample_rate=sample_rate,
                cache_dir=settings.polly_cache_dir,
            ),
            sample_rate=sample_rate,
        )

    pcm = speak(fragments[0])
    for fragment in fragments[1:]:
        pcm += b"\x00\x00" * int(sample_rate * GAP_MS / 1000) + speak(fragment)

    if case.clip_fraction and index == 0:
        pcm = clip_tail(pcm, sample_rate=sample_rate, fraction=case.clip_fraction)
    if case.noise_snr_db:
        pcm = mix_noise(
            pcm,
            sample_rate=sample_rate,
            snr_db=case.noise_snr_db,
            seed=_seed_for(f"{case.case_id}:{index}"),
        )
    return pcm, text


# --------------------------------------------------------------------------
# What came back
# --------------------------------------------------------------------------


class AudibleReturnPath(livekit_peer.ReturnPath):
    """`ReturnPath` that also remembers *when* audible audio arrived.

    `server/livekit_peer.py` counts audible samples; the peer-side half of M7
    needs the clock reading of the first audible frame after a mark, so this
    subclass keeps one timestamp and a mark. Subclassed rather than edited:
    Harness C is new files, and the peer is shared with `verify_livekit`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.audible_at: list[float] = []

    def feed(self, frame: Any) -> None:
        before = self.audible_samples
        super().feed(frame)
        if self.audible_samples > before:
            self.audible_at.append(time.time())

    def first_audible_after(self, mark: float) -> float | None:
        for at in self.audible_at:
            if at >= mark:
                return at
        return None


@dataclass
class TurnRecord:
    """One turn the fixture produced, as the trace recorded it."""

    turn: int
    heard: str = ""
    normalised: str = ""
    confidence: float | None = None
    asr_candidates: list[dict[str, Any]] = field(default_factory=list)
    step_id: str | None = None
    taxonomy_id: str = ""
    category: str = ""
    escalate: bool = False
    fsm_state: str = ""
    m7_server_ms: float | None = None
    first_audible: str = "reply"
    latency_lines: dict[str, Any] = field(default_factory=dict)
    ladder_tier: int = 0

    @property
    def branch(self) -> tuple[str | None, str, bool]:
        return (self.step_id, self.category, self.escalate)


@dataclass
class CaseResult:
    case_id: str
    pass_name: str
    scenario_id: str
    part: str
    corruption: str = ""
    construction: str = ""
    true_model: str = ""
    spoken: list[str] = field(default_factory=list)
    fixture_ms: list[int] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)
    device_model: str = ""
    device_confidence: str = ""
    #: The peer's own view of end-of-push → first audible frame back, and what
    #: it adds over the server's number. Never a browser number (§2.2 1 and 9).
    peer_m7_ms: float | None = None
    loopback_ms: float | None = None
    barge_in: dict[str, Any] = field(default_factory=dict)
    #: The M10 leg: every heard turn, typed into one second, fresh session.
    #: :attr:`typed_text` is the last of :attr:`typed_replay` -- the one whose
    #: reply is compared -- and the rest is the state it was asked in.
    typed_replay: list[str] = field(default_factory=list)
    typed_text: str = ""
    typed_step_id: str | None = None
    typed_category: str = ""
    typed_escalate: bool | None = None
    typed_device_model: str = ""
    error: str = ""
    #: Attempts the case took; >1 means a room was abandoned and remade. See
    #: :data:`MAX_CASE_ATTEMPTS`.
    attempts: int = 1
    seconds: float = 0.0

    # -- derived -----------------------------------------------------------

    @property
    def final(self) -> TurnRecord | None:
        """The last turn the core actually answered.

        A transcript the agent heard and never replied to is in
        :attr:`turns` with `turn == -1`; it is part of what was heard and it is
        not a branch, so it cannot be the case's branch unless it is all there
        is.
        """
        answered = [t for t in self.turns if t.turn >= 0]
        if answered:
            return answered[-1]
        return self.turns[-1] if self.turns else None

    @property
    def heard(self) -> str:
        return " ".join(t.normalised or t.heard for t in self.turns).strip()

    @property
    def asr_exact(self) -> bool:
        """Did the recogniser return the sentence the fixture said?

        Reported beside M10 and never folded into it: a mis-heard word is an
        ASR fact, and M10 is a modality fact.
        """
        return _comparable(self.heard) == _comparable(" ".join(self.spoken))

    @property
    def m7_values(self) -> list[float]:
        return [
            t.m7_server_ms
            for t in self.turns
            if t.m7_server_ms is not None and t.first_audible == "reply"
        ]

    @property
    def m10_match(self) -> bool | None:
        """`None` when there was nothing to compare -- not a pass."""
        final = self.final
        if final is None or self.typed_escalate is None:
            return None
        return (
            final.step_id == self.typed_step_id
            and final.category == self.typed_category
            and final.escalate == bool(self.typed_escalate)
        )

    @property
    def m10_detail(self) -> str:
        final = self.final
        if final is None or self.typed_escalate is None:
            return "no comparable turn"
        if self.m10_match:
            return "identical next step"
        parts = []
        if final.step_id != self.typed_step_id:
            parts.append(f"step {final.step_id} vs {self.typed_step_id}")
        if final.category != self.typed_category:
            parts.append(f"category {final.category} vs {self.typed_category}")
        if final.escalate != bool(self.typed_escalate):
            parts.append(f"escalate {final.escalate} vs {self.typed_escalate}")
        return "; ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "pass": self.pass_name,
            "scenario_id": self.scenario_id,
            "part": self.part,
            "corruption": self.corruption,
            "construction": self.construction,
            "true_model": self.true_model,
            "spoken": list(self.spoken),
            "fixture_ms": list(self.fixture_ms),
            "heard": self.heard,
            "asr_exact": self.asr_exact,
            "device": {"model": self.device_model, "confidence": self.device_confidence},
            "turns": [
                {
                    "turn": t.turn,
                    "heard": t.heard,
                    "normalised": t.normalised,
                    "confidence": t.confidence,
                    "asr_candidates": t.asr_candidates,
                    "step_id": t.step_id,
                    "taxonomy_id": t.taxonomy_id,
                    "category": t.category,
                    "escalate": t.escalate,
                    "fsm_state": t.fsm_state,
                    "m7_server_ms": t.m7_server_ms,
                    "first_audible": t.first_audible,
                    "ladder_tier": t.ladder_tier,
                    "lines": t.latency_lines,
                }
                for t in self.turns
            ],
            "peer_m7_ms": self.peer_m7_ms,
            "loopback_ms": self.loopback_ms,
            "barge_in": self.barge_in,
            "m10": {
                "typed_replay": list(self.typed_replay),
                "typed_text": self.typed_text,
                "typed_step_id": self.typed_step_id,
                "typed_category": self.typed_category,
                "typed_escalate": self.typed_escalate,
                "typed_device_model": self.typed_device_model,
                "match": self.m10_match,
                "detail": self.m10_detail,
            },
            "corruption_verdict": (
                corruption_verdict(self) if self.pass_name == CORRUPTION else None
            ),
            "error": self.error,
            "attempts": self.attempts,
            "seconds": round(self.seconds, 1),
        }


def _comparable(text: str) -> str:
    keep = [c.lower() for c in text if c.isalnum() or c.isspace()]
    return " ".join("".join(keep).split())


# --------------------------------------------------------------------------
# §7.3's corruption criterion
# --------------------------------------------------------------------------


def corruption_verdict(result: CaseResult) -> dict[str, Any]:
    """"Does not act on a mis-heard model", scored as §7.3 states it.

    Two conditions, both of them `eval/harness.py`'s M1 rule rather than a
    second opinion about it:

    1. the model the agent is willing to *report* is `unknown` -- `03` and
       §7.2 are explicit that correctly saying UNKNOWN **passes**;
    2. no step marked `model_specific` in `eval/ontology.py` was proposed on
       any turn of the case. That is the half that catches an agent which says
       `unknown` out loud and then tells the caller to hold the reset button a
       model without one does not have.

    Nothing here asks whether the agent "still got it right". §7.3 says that is
    not the target, and scoring it would make a harness that rewards guessing
    through a corrupted transcript.
    """
    model_specific = [
        t.step_id
        for t in result.turns
        if t.step_id and getattr(ontology.STEPS.get(t.step_id), "model_specific", False)
    ]
    reported_unknown = (result.device_model or "unknown").lower() == "unknown"
    reasons: list[str] = []
    if not reported_unknown:
        reasons.append(
            f"reported model {result.device_model!r} at confidence "
            f"{result.device_confidence} from a mis-heard spoken name"
        )
    if model_specific:
        reasons.append(f"proposed model-specific step(s) {', '.join(model_specific)}")
    if not result.turns:
        reasons.append("the fixture produced no turn at all")
    return {
        "pass": not reasons and bool(result.turns),
        "reported_model": result.device_model,
        "confidence": result.device_confidence,
        "model_specific_steps": model_specific,
        "detail": "; ".join(reasons) or "UNKNOWN branch held; no model-specific step",
    }


# --------------------------------------------------------------------------
# Driving one case
# --------------------------------------------------------------------------


async def _trace_events(
    http: httpx.AsyncClient, base_url: str, session: dict[str, Any]
) -> list[dict[str, Any]]:
    response = await http.get(
        f"{base_url}/api/trace/{session['room']}", params={"token": session["token"]}
    )
    response.raise_for_status()
    return response.json()["events"]


async def _wait_for_trace(
    http: httpx.AsyncClient,
    base_url: str,
    session: dict[str, Any],
    *,
    kind: str,
    count: int,
    timeout: float,
) -> list[dict[str, Any]]:
    deadline = time.time() + timeout
    events: list[dict[str, Any]] = []
    while time.time() < deadline:
        events = await _trace_events(http, base_url, session)
        if sum(1 for e in events if e["type"] == kind) >= count:
            return events
        await asyncio.sleep(0.4)
    return events


async def _wait_for_speech(
    peer: livekit_peer.HeadlessParticipant, state: str, *, since: int, timeout: float
) -> dict[str, Any] | None:
    """The next `agent.speech` in `state` after the mark, or `None`."""
    deadline = time.time() + timeout
    seen = since
    while time.time() < deadline:
        for message in peer.messages[seen:]:
            if message.get("type") == "agent.speech" and message.get("state") == state:
                return message
            if message.get("type") == "agent.speech" and message.get("state") == "failed":
                return None
        seen = len(peer.messages)
        await asyncio.sleep(0.05)
    return None


async def snapshot(ws_url: str, session: dict[str, Any]) -> dict[str, Any]:
    """The session as the page would render it: `DiagnosticState`, projected.

    The control socket's `hello` carries it, which is the only surface in the
    product that exposes `device.confidence` -- and `device.confidence` is half
    of §7.3's corruption criterion. Opened once, after the turn, and closed.
    """
    url = f"{ws_url}/ws?room={session['room']}&token={session['token']}"
    async with websockets.connect(url, open_timeout=20, max_size=4 * 1024 * 1024) as socket:
        hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
        return (hello.get("snapshot") or {}) if hello.get("type") == "hello" else {}


async def typed_leg(
    http: httpx.AsyncClient,
    base_url: str,
    ws_url: str,
    texts: str | Sequence[str],
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """§7.2's M10: the same value, through the other modality.

    A **fresh session**, because M10 compares the next step produced from the
    same state, and replaying into the session that just answered would be
    comparing turn 2 with turn 1. No peer joins it: a typed turn needs the
    control socket and the core, and nothing else -- which is itself §1.4.1
    item 2 holding (*"a click, a typed string and a transcribed utterance are
    the same event"*).

    **Every** turn the voice leg produced is replayed, in order, into that one
    session, and the reply compared is the reply to the last of them. Milestone
    6.4: replaying only the final transcript is what made
    `corruption:missegmented_turn` read as an M10 divergence. The endpointer
    split that fixture into two turns, so the voice leg answered its second
    transcript *with the first one already in the record* -- `WIFI-01` pinned,
    `STEP.ASK.PHONE_OS_AND_VERSION` in the ledger, and triage skipped. The
    typed leg answered the same sentence cold. Two different states, one of
    them two turns in and the other none, compared as though the only
    difference were modality. The docstring already said "the same state"; now
    the code does it.
    """
    if isinstance(texts, str):
        texts = [texts]
    replay = [t for t in (text.strip() for text in texts) if t]
    if not replay:
        raise RuntimeError("nothing was heard, so there is nothing to retype")
    session = await livekit_peer.open_session(http, base_url)
    url = f"{ws_url}/ws?room={session['room']}&token={session['token']}"
    reply: dict[str, Any] | None = None
    async with websockets.connect(url, open_timeout=20, max_size=4 * 1024 * 1024) as socket:
        await asyncio.wait_for(socket.recv(), timeout=20)  # hello
        for text in replay:
            await socket.send(
                json.dumps({"type": "user.text", "text": text, "modality": "typed"})
            )
            reply = None
            deadline = time.time() + timeout
            while time.time() < deadline:
                message = json.loads(
                    await asyncio.wait_for(
                        socket.recv(), timeout=max(1.0, deadline - time.time())
                    )
                )
                if message.get("type") == "turn.reply":
                    reply = message["reply"]
                    break
                if message.get("type") == "error":
                    raise RuntimeError(str(message.get("detail")))
            if reply is None:
                raise TimeoutError("typed leg produced no reply")
    assert reply is not None
    return reply


def _branch_of(reply: dict[str, Any]) -> dict[str, Any]:
    """The three fields M10 compares, out of one `turn.reply` payload."""
    return {
        "step_id": (reply.get("step") or {}).get("step_id"),
        "category": str(reply.get("category") or ""),
        "escalate": bool(reply.get("escalate")),
        "device_model": str(((reply.get("state") or {}).get("device") or {}).get("model") or ""),
    }


#: How long to wait for the worker's job to join the room before giving up on
#: an attempt. Milestone 6.4: `clean:EVAL-10` of the 6.3 run spent its 60 s here
#: and was written off.
#:
#: It is *not* a cold-start cost, and the timeout alone would not have saved it.
#: `server/livekit_agent.py` runs with `job_executor_type = THREAD` and
#: `num_idle_processes = 0`, so every job does pay for an executor to be made
#: on demand -- but a thread, not a process, and `data/traces/phase3-harness-c`
#: shows all 46 other cases paying exactly that and joining well inside 60 s,
#: each one announcing itself in `all.console.log` with the proc pool's *"no
#: warmed process available for job"*. EVAL-10 never printed that line, and its
#: trace (`room-6QUyGMOLU4Rr-9cce49c3.jsonl`) stops at `session.minted`: the
#: worker was never handed a job at all. The failure is in dispatch, upstream of
#: the pool, so warming the pool would not touch it and this module does not
#: claim otherwise. A longer wait is cheap insurance against the slow tail; the
#: thing that actually recovers a lost dispatch is :data:`MAX_CASE_ATTEMPTS`,
#: because a retry asks for a *new room*, and a new room is a new dispatch.
AGENT_JOIN_TIMEOUT_S = 90.0

#: Attempts per case when the *room* fails, not the agent. A case whose worker
#: never arrives produced no turn, so it is in no denominator: M10 loses a
#: comparison and the corruption pass loses a verdict, silently. One retry on a
#: fresh room turns an infrastructure flake into a measured case, and
#: `attempts` in the record says it happened.
MAX_CASE_ATTEMPTS = 2

#: Errors worth a second room. Anything else -- a bad fixture, a missing model
#: -- would fail the same way twice.
_RETRYABLE_ERRORS = (
    "the agent worker never joined the room",
    "the agent never finished its greeting",
)


async def run_case(
    case: Case,
    *,
    http: httpx.AsyncClient,
    base_url: str,
    ws_url: str,
    settings: Settings,
    measure_m10: bool = True,
    verbose: bool = True,
) -> CaseResult:
    """One case, retried once if the room -- not the agent -- let it down.

    The attempt itself is :func:`run_case_once`. This wrapper exists for two
    things the 6.3 run showed were missing: a case that failed before its
    first turn printed *nothing* and recorded `seconds: 0.0`, because both the
    stamp and the line came after an early `return`; and it was dropped from
    every denominator with no second try.
    """
    started = time.time()
    result: CaseResult | None = None
    for attempt in range(1, MAX_CASE_ATTEMPTS + 1):
        result = await run_case_once(
            case,
            http=http,
            base_url=base_url,
            ws_url=ws_url,
            settings=settings,
            measure_m10=measure_m10,
        )
        result.attempts = attempt
        if result.error not in _RETRYABLE_ERRORS or attempt == MAX_CASE_ATTEMPTS:
            break
        if verbose:
            print(
                f"  {case.case_id:<32}retrying on a fresh room — {result.error}",
                flush=True,
            )
    assert result is not None
    result.seconds = time.time() - started
    if verbose:
        print(_one_line(result), flush=True)
    return result


async def run_case_once(
    case: Case,
    *,
    http: httpx.AsyncClient,
    base_url: str,
    ws_url: str,
    settings: Settings,
    measure_m10: bool = True,
) -> CaseResult:
    """One attempt: join, speak, read the instrument, replay through typing."""
    result = CaseResult(
        case_id=case.case_id,
        pass_name=case.pass_name,
        scenario_id=case.scenario_id,
        part=case.part,
        corruption=case.corruption,
        construction=case.construction,
        true_model=case.true_model,
    )
    sample_rate = int(settings.audio_sample_rate)
    fixtures: list[bytes] = []
    for index in range(len(case.utterances)):
        pcm, text = await asyncio.to_thread(
            synthesize_case, case, index, settings, sample_rate=sample_rate
        )
        fixtures.append(pcm)
        result.spoken.append(text)
        result.fixture_ms.append(polly.duration_ms(pcm, sample_rate))

    session = await livekit_peer.open_session(http, base_url)
    peer = livekit_peer.HeadlessParticipant(
        url=session["livekit_url"],
        token=session["token"],
        sample_rate=sample_rate,
        identity=session["identity"],
    )
    peer.returned = AudibleReturnPath()
    try:
        await peer.connect()
        if not await peer.wait_for_agent(timeout=AGENT_JOIN_TIMEOUT_S):
            result.error = "the agent worker never joined the room"
            return result
        await peer.wait_for_agent_track(timeout=30.0)
        await peer.publish_microphone()

        # The greeting is dead air for this harness: wait it out rather than
        # talk over it, except in the case that is *about* talking over
        # something, which talks over the reply instead.
        if await _wait_for_speech(peer, "end", since=0, timeout=90.0) is None:
            result.error = "the agent never finished its greeting"
            return result

        expected_turns = 0
        for index, pcm in enumerate(fixtures):
            if index and case.barge_in:
                # Speak across the agent's reply to the previous utterance.
                mark = len(peer.messages)
                reply_started = await _wait_for_speech(
                    peer, "start", since=mark, timeout=120.0
                )
                if reply_started is None:
                    result.error = "no reply to barge in on"
                    return result
                await asyncio.sleep(0.6)  # far enough in that there is audio to cut
                before = len(peer.messages)
                await peer.speak(pcm, lead_silence_ms=0)
                flush = await peer.wait_for_message("agent.flush", timeout=5.0, since=before)
                result.barge_in = {
                    "flush_received": flush is not None,
                    "queued_ms": (flush or {}).get("queued_ms"),
                    "reason": (flush or {}).get("reason"),
                }
            else:
                await peer.speak(pcm, lead_silence_ms=300)
            # Past the longest §2.3 hangover, pushed frame by frame: silence
            # that is not transmitted is a gap in the stream, which the VAD
            # reads differently.
            await peer.hold_silence(3.0)
            expected_turns += 2 if (case.gap_after_word and index == 0) else 1

        push_ended = time.time()

        events = await _wait_for_trace(
            http, base_url, session, kind="latency.turn", count=1, timeout=180.0
        )
        # A mis-segmented fixture produces more than one turn; give the second
        # one its chance before reading, but do not require it -- "the gap
        # split the turn" and "it did not" are both findings.
        if expected_turns > 1:
            events = await _wait_for_trace(
                http,
                base_url,
                session,
                kind="latency.turn",
                count=expected_turns,
                timeout=90.0,
            )
        result.turns = _turns_from(events)
        result.barge_in.update(_barge_in_from(events))

        peer_first = peer.returned.first_audible_after(push_ended)
        if peer_first is not None:
            result.peer_m7_ms = round((peer_first - push_ended) * 1000.0, 1)
            server_m7 = result.m7_values[-1] if result.m7_values else None
            if server_m7 is not None:
                result.loopback_ms = round(result.peer_m7_ms - server_m7, 1)

        state = (await snapshot(ws_url, session)).get("state") or {}
        device = state.get("device") or {}
        result.device_model = str(device.get("model") or "")
        result.device_confidence = str(device.get("confidence") or "")
    except Exception as exc:  # noqa: BLE001 — a failed case is a reported case
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        await peer.close()

    final = result.final
    if measure_m10 and final is not None and not result.error:
        # Everything the agent heard up to and including the turn whose branch
        # M10 compares -- not just that turn. See :func:`typed_leg`.
        spoken_to = result.turns.index(final)
        result.typed_replay = [
            heard
            for heard in (
                (t.normalised or t.heard).strip() for t in result.turns[: spoken_to + 1]
            )
            if heard
        ]
        result.typed_text = result.typed_replay[-1] if result.typed_replay else ""
        try:
            if not result.typed_replay:
                raise RuntimeError("nothing was heard, so there is nothing to retype")
            branch = _branch_of(
                await typed_leg(http, base_url, ws_url, result.typed_replay)
            )
            result.typed_step_id = branch["step_id"]
            result.typed_category = branch["category"]
            result.typed_escalate = branch["escalate"]
            result.typed_device_model = branch["device_model"]
        except Exception as exc:  # noqa: BLE001
            result.error = (result.error + "; " if result.error else "") + (
                f"M10 leg: {type(exc).__name__}: {exc}"
            )

    return result


def _turns_from(events: Sequence[dict[str, Any]]) -> list[TurnRecord]:
    """Pair up `turn.voice`, `turn.reply` and `latency.turn` into turns.

    `turn.voice` is written by the agent worker before the core has run, so it
    carries no turn number — `agent.core.begin_turn` has not bumped the counter
    yet. It is therefore matched **by order**: a `turn.voice` belongs to the
    next voice `turn.reply` in the file, which is the same pairing a reader
    does by eye. `latency.turn` and `turn.reply` both carry the number and are
    matched on it.
    """
    turns: dict[int, TurnRecord] = {}
    pending: dict[str, Any] | None = None
    orphans: list[TurnRecord] = []

    def at(number: int) -> TurnRecord:
        return turns.setdefault(number, TurnRecord(turn=number))

    def fill(record: TurnRecord, voice: dict[str, Any]) -> None:
        record.heard = str(voice.get("verbatim") or "")
        record.normalised = str(voice.get("normalised") or "")
        record.confidence = voice.get("confidence")
        record.asr_candidates = list(voice.get("asr_candidates") or [])

    for event in events:
        kind = event["type"]
        if kind == "turn.voice":
            if pending is not None:
                # A transcript that never became a reply: kept, not dropped,
                # because "the agent heard this and answered nothing" is a
                # finding and a silent omission would hide it.
                orphan = TurnRecord(turn=-1)
                fill(orphan, pending)
                orphans.append(orphan)
            pending = event
        elif kind == "turn.reply" and event.get("modality") == "voice":
            record = at(int(event.get("turn") or 0))
            if pending is not None:
                fill(record, pending)
                pending = None
            record.step_id = event.get("step_id")
            record.taxonomy_id = str(event.get("taxonomy_id") or "")
            record.category = str(event.get("category") or "")
            record.escalate = bool(event.get("escalate"))
            record.fsm_state = str(event.get("fsm_state") or "")
        elif kind == "latency.turn" and event.get("modality") == "voice":
            record = at(int(event.get("turn") or 0))
            record.m7_server_ms = event.get("m7_server_ms")
            record.first_audible = str(event.get("first_audible") or "reply")
            record.ladder_tier = int(event.get("ladder_tier") or 0)
            record.latency_lines = {
                f"line{line['line']}": line.get("ms") for line in event.get("lines") or []
            }
    if pending is not None:
        orphan = TurnRecord(turn=-1)
        fill(orphan, pending)
        orphans.append(orphan)
    return [turns[k] for k in sorted(turns)] + orphans


def _barge_in_from(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    detected = [e for e in events if e["type"] == "barge_in.detected"]
    if not detected:
        return {"detected": False}
    return {
        "detected": True,
        "count": len(detected),
        "flushed_ms": detected[-1].get("flushed_ms"),
        "held_frames": detected[-1].get("held_frames"),
    }


#: How a case's M10 verdict prints in one character.
_M10_MARK = {True: "=", False: "≠", None: "·"}


def _one_line(result: CaseResult) -> str:
    """One line per case, printed as it finishes.

    A real-time-paced harness takes minutes; a run that printed nothing until
    the end would be indistinguishable from a hung one.
    """
    final = result.final
    m7 = result.m7_values
    step = "—"
    if final is not None:
        step = final.step_id or ("escalate" if final.escalate else "<no step>")
    return (
        f"  {result.case_id:<32}"
        f"{step:<42}"
        f"m7={(f'{m7[-1]:.0f}' if m7 else '—'):>7} ms  "
        f"model={(result.device_model or '—'):<9} "
        f"m10={_M10_MARK[result.m10_match]}  "
        f"{result.seconds:>5.1f}s"
        + (f"  ERROR: {result.error}" if result.error else "")
    )


# --------------------------------------------------------------------------
# Running a list of cases
# --------------------------------------------------------------------------


async def run_harness_c(
    cases: Sequence[Case],
    *,
    base_url: str,
    ws_url: str,
    settings: Settings,
    measure_m10: bool = True,
    on_result: Any = None,
    verbose: bool = True,
) -> list[CaseResult]:
    """Every case, **one at a time**.

    Serial on purpose. The numbers this harness exists to produce are latency
    numbers, and two sessions sharing a CPU, a Bedrock client and a Polly
    client would be measuring contention. It costs wall-clock minutes, which is
    the price of a real-time-paced harness and is paid rather than optimised
    away.
    """
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=60.0) as http:
        for case in cases:
            result = await run_case(
                case,
                http=http,
                base_url=base_url,
                ws_url=ws_url,
                settings=settings,
                measure_m10=measure_m10,
                verbose=verbose,
            )
            results.append(result)
            if on_result is not None:
                on_result(result)
    return results


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def _distribution(values: Iterable[float]) -> dict[str, Any] | None:
    numbers = [float(v) for v in values if v is not None]
    if not numbers:
        return None
    ordered = sorted(numbers)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "n": len(numbers),
        "min": round(min(numbers), 1),
        "median": round(statistics.median(numbers), 1),
        "p95": round(ordered[index], 1),
        "max": round(max(numbers), 1),
    }


def summarise(results: Sequence[CaseResult]) -> dict[str, Any]:
    """M7, M10, the corruption verdicts and the ASR fidelity, per pass."""
    per_pass: dict[str, Any] = {}
    for name in PASSES:
        subset = [r for r in results if r.pass_name == name]
        if not subset:
            continue
        m10 = [r.m10_match for r in subset if r.m10_match is not None]
        per_pass[name] = {
            "cases": len(subset),
            "errors": sum(1 for r in subset if r.error),
            "turns": sum(len(r.turns) for r in subset),
            "m7_server_ms": _distribution(v for r in subset for v in r.m7_values),
            "peer_m7_ms": _distribution(r.peer_m7_ms for r in subset),
            "loopback_ms": _distribution(r.loopback_ms for r in subset),
            "m10_compared": len(m10),
            "m10_matches": sum(1 for m in m10 if m),
            "asr_exact": sum(1 for r in subset if r.asr_exact),
        }
    all_m10 = [r.m10_match for r in results if r.m10_match is not None]
    corruption = [r for r in results if r.pass_name == CORRUPTION]
    verdicts = {r.corruption: corruption_verdict(r) for r in corruption}
    return {
        "cases": len(results),
        "per_pass": per_pass,
        "m7_server_ms": _distribution(v for r in results for v in r.m7_values),
        "m7_ceiling_ms": latency_module.M7_CEILING_MS,
        "m7_target_median_ms": latency_module.MEASURABLE_TARGET_MEDIAN_MS,
        "m10_compared": len(all_m10),
        "m10_matches": sum(1 for m in all_m10 if m),
        "corruption": {
            "cases": len(corruption),
            "passes": sum(1 for v in verdicts.values() if v["pass"]),
            "verdicts": verdicts,
        },
        "browser_lines_1_and_9": latency_module.UNMEASURED,
    }


def format_report_c(results: Sequence[CaseResult]) -> str:
    """The per-pass, per-case report §7.3 asks for. No single aggregate."""
    summary = summarise(results)
    lines: list[str] = []
    lines.append(
        f"Harness C — end-to-end spoken, through a real room "
        f"({summary['cases']} cases, "
        f"{sum(len(r.turns) for r in results)} spoken turns)"
    )
    lines.append(
        "  20 ms frames at real-time pace, through server/livekit_peer.py into a "
        "live LiveKit room."
    )
    lines.append("")

    for name in PASSES:
        subset = [r for r in results if r.pass_name == name]
        if not subset:
            continue
        stats = summary["per_pass"][name]
        lines.append(f"── {name} pass — {stats['cases']} case(s) " + "─" * 46)
        header = (
            f"{'case':<22}{'heard':<6}{'next step':<40}"
            f"{'model':<10}{'M7 ms':>8}{'M10':>5}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for r in subset:
            final = r.final
            m7 = r.m7_values
            lines.append(
                f"{r.case_id.split(':', 1)[1]:<22}"
                f"{('exact' if r.asr_exact else 'drift'):<6}"
                f"{(final.step_id if final and final.step_id else ('escalate' if final and final.escalate else '—')):<40}"
                f"{(r.device_model or '—'):<10}"
                f"{(f'{m7[-1]:.0f}' if m7 else '—'):>8}"
                f"{({True: 'yes', False: 'NO', None: '—'}[r.m10_match]):>5}"
            )
            if r.error:
                lines.append(f"{'':<22}  ↳ error: {r.error}")
            if r.m10_match is False:
                lines.append(f"{'':<22}  ↳ M10: {r.m10_detail}")
        lines.append("")
        m7 = stats["m7_server_ms"]
        if m7:
            lines.append(
                f"  M7 (end of speech → first audible, server side): median "
                f"{m7['median']:.0f} ms, p95 {m7['p95']:.0f} ms, n={m7['n']}"
            )
        loop = stats["loopback_ms"]
        if loop:
            lines.append(
                f"  loopback leg the peer adds on top: median {loop['median']:.0f} ms "
                f"(n={loop['n']}) — NOT §2.2 lines 1 and 9"
            )
        lines.append(
            f"  M10: {stats['m10_matches']}/{stats['m10_compared']} identical; "
            f"ASR returned the fixture verbatim in {stats['asr_exact']}/{stats['cases']}"
        )
        lines.append("")

    # ---- M7, the headline §9.1 asks for ---------------------------------
    m7 = summary["m7_server_ms"]
    lines.append("M7 — `01`'s metric, over every spoken reply turn of every pass")
    if m7:
        lines.append(
            f"  median {m7['median']:.0f} ms, p95 {m7['p95']:.0f} ms, "
            f"min {m7['min']:.0f}, max {m7['max']:.0f}, n={m7['n']}"
        )
        lines.append(
            f"  §2.2 lines 2–8 target median {summary['m7_target_median_ms']:.0f} ms; "
            f"`01` M7 ceiling {summary['m7_ceiling_ms']:.0f} ms at the median"
        )
        verdict_target = "AT OR UNDER" if m7["median"] <= summary["m7_target_median_ms"] else "OVER"
        verdict_ceiling = "NOT BREACHED" if m7["median"] <= summary["m7_ceiling_ms"] else "BREACHED"
        lines.append(f"  → {verdict_target} the §2.2 target median")
        lines.append(f"  → the 1.2 s median line is {verdict_ceiling}")
    else:
        lines.append("  no turn produced an M7 reading")
    lines.append(
        "  §2.2 lines 1 and 9 are UNMEASURED and are not in this number: it is "
        "end of speech"
    )
    lines.append(
        "  to first sample pushed into the room, which is as much of M7 as a "
        "process without"
    )
    lines.append("  a browser on the other end can honestly see.")
    lines.append("")

    # ---- M10 -------------------------------------------------------------
    lines.append("M10 — modality independence (§7.2: the next step must be identical)")
    lines.append(
        f"  {summary['m10_matches']}/{summary['m10_compared']} cases: the "
        "transcript typed into a fresh session"
    )
    lines.append("  produced the same step, category and escalation as the spoken turn.")
    divergent = [r for r in results if r.m10_match is False]
    for r in divergent:
        lines.append(f"  [DIVERGENCE] {r.case_id}: {r.m10_detail}")
    if not divergent:
        lines.append("  No divergence. Target is 100 % and a divergence is a defect, not a score.")
    lines.append("")

    # ---- the corruption pass --------------------------------------------
    corruption = [r for r in results if r.pass_name == CORRUPTION]
    if corruption:
        lines.append(
            "ASR-corruption pass — §7.3's criterion: a mis-heard model produces "
            "UNKNOWN,"
        )
        lines.append("not a wrong branch. Per case:")
        for r in corruption:
            verdict = corruption_verdict(r)
            lines.append(
                f"  [{'PASS' if verdict['pass'] else 'FAIL'}] {r.corruption:<20} "
                f"({r.scenario_id}) model={verdict['reported_model'] or '—'} "
                f"confidence={verdict['confidence'] or '—'}"
            )
            lines.append(f"           heard: \"{r.heard[:110]}\"")
            lines.append(f"           {verdict['detail']}")
            if r.barge_in:
                lines.append(f"           barge-in: {json.dumps(r.barge_in, sort_keys=True)}")
        passes = summary["corruption"]["passes"]
        lines.append(f"  {passes}/{len(corruption)} cases held the UNKNOWN branch.")
        lines.append("")

    lines.append(
        "Reported per pass and per case, never as one aggregate (§7.3). The "
        "ledger is not"
    )
    lines.append(
        "pre-populated here, so M4 from this harness is not comparable with "
        "Harness A's and"
    )
    lines.append("is not reported.")
    return "\n".join(lines)


__all__ = [
    "CLEAN",
    "CORRUPTION",
    "CORRUPTIONS",
    "Case",
    "CaseResult",
    "CorruptionSpec",
    "GAP_MS",
    "NOISE",
    "NOISE_IDS",
    "NOISE_SNR_DB",
    "PASSES",
    "TurnRecord",
    "build_cases",
    "clip_tail",
    "corruption_verdict",
    "format_report_c",
    "mix_noise",
    "road_noise",
    "run_case",
    "run_harness_c",
    "summarise",
    "synthesize_case",
    "typed_leg",
]
