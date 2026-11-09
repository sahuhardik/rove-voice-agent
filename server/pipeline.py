"""The media path: a Pipecat SmallWebRTC peer connection in this process.

`docs/06` §8.1.1 picks this shape for the spike and says why:

> **Pipecat is not discarded — it is the Phase 3 spike and the fallback.**
> SmallWebRTC gets a real browser conversation running in a single Python
> process with nothing to operate.

The pipeline is four processors and no more:

    transport.input()  →  VADProcessor(Silero v5)  →  SpeechReporter  →  transport.output()

* **`transport.input()`** holds the `aiortc` peer connection and turns inbound
  Opus into 20 ms PCM frames (§1.4.2: "audio is fed to the pipeline at
  real-time pace, in 20 ms frames").
* **`VADProcessor`** runs **Silero VAD v5** in-process on CPU (`docs/07`
  D-03). Pipecat ships the ONNX weights; nothing is downloaded and no Bedrock
  endpoint is touched, which is the reading of **C-2** that D-03 records as
  needing one sentence of confirmation from Hardik.
* **`SpeechReporter`** is ours: it turns the VAD's start/stop events into
  speech segments and the inbound frames into an audio level, and sends both
  to the browser over the WebRTC **data channel**, where the UI meter and the
  "I can hear you" line come from. It also writes them to the trace.
* **`transport.output()`** plays the Polly greeting back down the same peer
  connection.

**What is deliberately missing**, because `docs/06` §9.1 puts it in Phase 3:
no Transcribe streaming, no LLM in the audio path, no incremental Polly, no
barge-in, and no endpointing beyond the VAD's own hangover. The speech segments
are reported, not acted on.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from server import polly
from server.config import Settings
from server.core_bridge import Session

#: How often the audio level goes to the browser. Eight a second is enough for
#: a meter to look live and little enough to stay out of the way of media.
LEVEL_HZ = 8.0

#: Silence floor for the dBFS conversion.
MIN_DBFS = -90.0

#: The RTP clock for Opus, and the divisor the jitter numbers below need.
#:
#: `aiortc` reports `jitter` as an **int in RTP timestamp units** (see
#: `aiortc/stats.py`: `jitter: int`, filled from the interarrival-jitter
#: estimator in `rtcrtpreceiver.py`), whereas the browser's `getStats()`
#: reports it in **seconds**, per the W3C stats spec. The two have to be
#: converted differently to land in the same unit, and the trace compares them
#: directly — so getting this wrong does not produce a wrong number, it
#: produces a wrong comparison. `roundTripTime` *is* seconds on both sides.
#:
#: 48 kHz is unconditional here because this pipeline is audio-only and
#: WebRTC Opus is always 48 kHz-clocked, whatever rate the pipeline runs at
#: internally.
OPUS_CLOCK_HZ = 48000


def _jitter_ms(raw: Any) -> float:
    """RTP-clock jitter units → milliseconds."""
    return round(1000.0 * float(raw or 0) / OPUS_CLOCK_HZ, 3)


def _dbfs(samples: np.ndarray) -> float:
    """RMS of int16 samples, in dBFS. Full scale is 0."""
    if samples.size == 0:
        return MIN_DBFS
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 1.0:
        return MIN_DBFS
    return max(MIN_DBFS, round(20.0 * float(np.log10(rms / 32768.0)), 2))


class SpeechReporter(FrameProcessor):
    """Report speech segments and audio levels to the browser and the trace.

    The report goes over the **data channel** rather than the control socket on
    purpose: it is a property of the media path, it is produced by the media
    path, and sending it any other way would leave the data channel untested.
    """

    def __init__(self, *, session: Session, level_hz: float = LEVEL_HZ, **kwargs: Any):
        super().__init__(**kwargs)
        self._session = session
        self._level_period = 1.0 / max(level_hz, 0.1)
        self._last_level_at = 0.0
        self._peak_dbfs = MIN_DBFS
        self._frames_in = 0
        self._samples_in = 0
        self._speech_started_at: float | None = None
        self._segments = 0
        self._sample_rate = 16000

    @property
    def frames_received(self) -> int:
        return self._frames_in

    async def _send(self, message: dict[str, Any]) -> None:
        await self.push_frame(
            OutputTransportMessageUrgentFrame(message=message), FrameDirection.DOWNSTREAM
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            await self._on_audio(frame)
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._on_speech_started(frame)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            await self._on_speech_stopped(frame)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._session.trace.event(
                "media.stopped",
                frames_received=self._frames_in,
                audio_seconds=round(self._samples_in / self._sample_rate, 2),
                speech_segments=self._segments,
            )

    async def _on_audio(self, frame: InputAudioRawFrame) -> None:
        self._frames_in += 1
        self._sample_rate = frame.sample_rate or self._sample_rate
        samples = np.frombuffer(frame.audio, dtype=np.int16)
        self._samples_in += samples.size
        level = _dbfs(samples)
        self._peak_dbfs = max(self._peak_dbfs, level)
        now = time.time()
        if now - self._last_level_at < self._level_period:
            return
        self._last_level_at = now
        await self._send(
            {
                "type": "audio.level",
                "dbfs": level,
                "peak_dbfs": self._peak_dbfs,
                "frames": self._frames_in,
                "sample_rate": frame.sample_rate,
                "speaking": self._speech_started_at is not None,
            }
        )
        self._peak_dbfs = MIN_DBFS
        if self._frames_in % 250 == 0:  # ~5 s of 20 ms frames
            self._session.trace.event(
                "media.audio_in",
                frames=self._frames_in,
                seconds=round(self._samples_in / max(frame.sample_rate, 1), 2),
                dbfs=level,
            )

    async def _on_speech_started(self, frame: VADUserStartedSpeakingFrame) -> None:
        self._speech_started_at = time.time()
        self._session.trace.event(
            "vad.speech_start",
            vad="silero-v5",
            start_secs=frame.start_secs,
            frames_received=self._frames_in,
        )
        await self._send(
            {
                "type": "speech.start",
                "at": self._speech_started_at,
                "vad": "silero-v5",
                "start_secs": frame.start_secs,
            }
        )

    async def _on_speech_stopped(self, frame: VADUserStoppedSpeakingFrame) -> None:
        ended = time.time()
        started = self._speech_started_at or ended
        # The hangover is part of the detection, not of the speech: §2.3 is
        # about exactly this number, so the segment is reported without it and
        # the hangover is reported beside it.
        duration_ms = max(0, int(1000 * (ended - started) - 1000 * frame.stop_secs))
        self._speech_started_at = None
        self._segments += 1
        self._session.trace.event(
            "vad.speech_end",
            vad="silero-v5",
            duration_ms=duration_ms,
            stop_secs=frame.stop_secs,
            segment=self._segments,
        )
        await self._send(
            {
                "type": "speech.end",
                "at": ended,
                "duration_ms": duration_ms,
                "stop_secs": frame.stop_secs,
                "segment": self._segments,
            }
        )


class MediaSession:
    """One peer connection, its pipeline, and the tasks that watch it."""

    def __init__(self, *, session: Session, connection: Any, settings: Settings) -> None:
        self.session = session
        self.connection = connection
        self.settings = settings
        self.started_at = time.time()
        self.greeting_ms: int | None = None
        self._runner: WorkerRunner | None = None
        self._worker: PipelineWorker | None = None
        self._run_task: asyncio.Task | None = None
        self._stats_task: asyncio.Task | None = None
        self._reporter: SpeechReporter | None = None
        self._stopping = False

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        settings = self.settings
        transport = SmallWebRTCTransport(
            webrtc_connection=self.connection,
            params=TransportParams(
                audio_in_enabled=True,
                audio_in_sample_rate=settings.audio_sample_rate,
                audio_in_passthrough=True,
                audio_out_enabled=True,
                audio_out_sample_rate=settings.audio_sample_rate,
            ),
        )
        self._transport = transport
        self._reporter = SpeechReporter(session=self.session)
        vad = VADProcessor(
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=settings.audio_sample_rate,
                params=VADParams(
                    confidence=settings.vad_confidence,
                    start_secs=settings.vad_start_secs,
                    stop_secs=settings.vad_stop_secs,
                ),
            )
        )
        pipeline = Pipeline([transport.input(), vad, self._reporter, transport.output()])
        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=settings.audio_sample_rate,
                audio_out_sample_rate=settings.audio_sample_rate,
            ),
            # A duplex session that holds for ten minutes (§9.1 Phase 2b exit)
            # with nobody speaking is **not** an idle pipeline, and Pipecat's
            # default would cancel it at five minutes. The browser's own
            # disconnect is what ends a session here.
            idle_timeout_secs=None,
            enable_turn_tracking=False,
            check_dangling_tasks=False,
        )

        @transport.event_handler("on_client_connected")
        async def _on_connected(_transport, client):  # noqa: ANN001
            self.session.trace.event(
                "webrtc.connected",
                pc_id=getattr(client, "pc_id", None),
                elapsed_since_offer_s=round(time.time() - self.started_at, 3),
            )
            await self._speak_greeting()

        @transport.event_handler("on_client_disconnected")
        async def _on_disconnected(_transport, client):  # noqa: ANN001
            self.session.trace.event(
                "webrtc.disconnected",
                pc_id=getattr(client, "pc_id", None),
                held_for_s=round(time.time() - self.started_at, 3),
                frames_received=self._reporter.frames_received if self._reporter else 0,
            )
            await self.stop()

        self._runner = WorkerRunner(handle_sigint=False, check_dangling_tasks=False)
        self._run_task = asyncio.create_task(self._run())
        self._stats_task = asyncio.create_task(self._sample_stats())

    async def _run(self) -> None:
        assert self._runner is not None and self._worker is not None
        try:
            await self._runner.run(self._worker)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.session.trace.event("media.error", error=f"{type(exc).__name__}: {exc}")
        finally:
            if self.session.media is self:
                self.session.media = None

    async def stop(self) -> None:
        """End the pipeline.

        Called from the transport's own disconnect handler as well as from the
        outside, so it must not cancel the task it may itself be running on:
        cancelling the worker is what makes the runner return, and the run task
        then finishes on its own.
        """
        if self._stopping:
            return
        self._stopping = True
        if self._stats_task is not None and self._stats_task is not asyncio.current_task():
            self._stats_task.cancel()
            self._stats_task = None
        if self._worker is not None:
            try:
                await self._worker.cancel(reason="peer disconnected")
            except Exception:  # noqa: BLE001
                pass
        if (
            self._run_task is not None
            and self._run_task is not asyncio.current_task()
            and not self._run_task.done()
        ):
            try:
                await asyncio.wait_for(asyncio.shield(self._run_task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._run_task.cancel()
        if self.session.media is self:
            self.session.media = None

    # -- the greeting ----------------------------------------------------

    async def _speak_greeting(self) -> None:
        """One Polly Neural sentence, played down the peer connection.

        Synthesis is a blocking boto3 call, so it runs on a thread: `docs/07`
        D-14's "async throughout, no blocking calls on the media path".
        """
        settings = self.settings
        try:
            audio = await asyncio.to_thread(
                polly.synthesize_pcm,
                settings.greeting_text,
                voice=settings.polly_voice,
                engine=settings.polly_engine,
                sample_rate=settings.audio_sample_rate,
                cache_dir=settings.polly_cache_dir,
            )
        except polly.PollyUnavailable as exc:
            self.session.trace.event("greeting.failed", error=str(exc))
            return
        self.greeting_ms = polly.duration_ms(audio, settings.audio_sample_rate)
        assert self._worker is not None
        await self._worker.queue_frame(
            OutputAudioRawFrame(
                audio=audio,
                sample_rate=settings.audio_sample_rate,
                num_channels=1,
            )
        )
        self.session.trace.event(
            "greeting.played",
            engine=settings.polly_engine,
            voice=settings.polly_voice,
            duration_ms=self.greeting_ms,
            bytes=len(audio),
        )

    # -- RTT / jitter / loss, from this end ------------------------------

    async def _sample_stats(self) -> None:
        """Sample `aiortc`'s RTCP view into the trace (§9.1 Phase 2b exit).

        `roundTripTime` here comes from the peer's RTCP receiver reports, so it
        is a measurement of the live link rather than of an application-level
        ping. The browser's own `getStats()` arrives separately as
        `net.client_stats`; the two are kept apart deliberately.
        """
        period = self.settings.stats_period_secs
        while True:
            await asyncio.sleep(period)
            try:
                stats = await self.connection.pc.getStats()
            except Exception:  # noqa: BLE001 — connection going away
                return
            sample: dict[str, Any] = {}
            for report in stats.values():
                kind = getattr(report, "type", "")
                if kind == "inbound-rtp":
                    sample["jitter_ms"] = _jitter_ms(getattr(report, "jitter", 0))
                    sample["packets_received"] = int(getattr(report, "packetsReceived", 0))
                    sample["packets_lost"] = int(getattr(report, "packetsLost", 0))
                    sample["bytes_received"] = int(getattr(report, "bytesReceived", 0))
                elif kind == "remote-inbound-rtp":
                    # `roundTripTime` is seconds here and seconds in the
                    # browser, so this one multiplication is the same on both
                    # sides. It is the peer's RTCP view of the round trip, not
                    # an application ping.
                    rtt = getattr(report, "roundTripTime", None)
                    if rtt is not None:
                        sample["rtt_ms"] = round(1000 * float(rtt), 3)
                    sample["remote_jitter_ms"] = _jitter_ms(getattr(report, "jitter", 0))
                    sample["remote_packets_lost"] = int(getattr(report, "packetsLost", 0))
                    fraction_lost = getattr(report, "fractionLost", None)
                    if fraction_lost is not None:
                        sample["remote_fraction_lost"] = round(float(fraction_lost), 5)
                elif kind == "outbound-rtp":
                    sample["packets_sent"] = int(getattr(report, "packetsSent", 0))
                    sample["bytes_sent"] = int(getattr(report, "bytesSent", 0))
            if sample:
                self.session.trace.event("net.server_stats", source="aiortc", **sample)


async def attach_media(
    *, session: Session, connection: Any, settings: Settings
) -> MediaSession:
    """Build and start the pipeline for a newly offered peer connection."""
    if session.media is not None:
        await session.media.stop()
    media = MediaSession(session=session, connection=connection, settings=settings)
    session.media = media
    await media.start()
    return media
