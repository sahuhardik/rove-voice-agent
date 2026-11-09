"""A browser-shaped WebRTC peer with no browser in it.

The Phase 2b exit criterion in `docs/06` §9.1 is about a *real* peer
connection, and the only honest way to assert that in CI is to be a real peer:
`aiortc` on this side, `aiortc` (inside Pipecat's SmallWebRTC transport) on the
other, a genuine DTLS-SRTP session between them, Opus on the wire both ways.

This peer does exactly what `client/src/webrtc.js` does and nothing more:

1. open a data channel, add a microphone track, create an offer;
2. `POST /api/offer` with the join token, apply the answer;
3. push 20 ms PCM frames up at real-time pace;
4. read the frames that come back down, and the data-channel messages beside
   them.

The microphone is Polly speech rather than a tone or noise, because the thing
under test on the way up is **Silero VAD v5** (`docs/07` D-03), and a VAD that
fires on a sine wave has told you nothing. Synthesising the mic audio with the
same service the server greets with keeps the fixture honest and costs one
cached call.

What this file is **not**: a browser. It proves the transport, the VAD and the
return path. It cannot prove getUserMedia, echo cancellation, the browser's own
jitter buffer or `RTCPeerConnection.getStats()` — those need a human and a
browser, and `client/README.md` says which steps that takes.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack

#: 20 ms frames, as §1.4.2 and the Opus default both want.
FRAME_MS = 20


def _frame_samples(sample_rate: int) -> int:
    return int(sample_rate * FRAME_MS / 1000)


class PcmMicTrack(MediaStreamTrack):
    """A microphone that plays a fixed PCM buffer, then silence.

    Paced against the wall clock rather than emitted as fast as it is asked
    for: a VAD hangover is measured in milliseconds of audio time, so audio
    time has to be real time or the segment durations are fiction.
    """

    kind = "audio"

    def __init__(
        self,
        pcm: bytes,
        *,
        sample_rate: int = 16000,
        lead_silence_ms: int = 400,
        tail_silence_ms: int = 1500,
    ) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        lead = b"\x00\x00" * int(sample_rate * lead_silence_ms / 1000)
        tail = b"\x00\x00" * int(sample_rate * tail_silence_ms / 1000)
        self._pcm = lead + pcm + tail
        self._offset = 0
        self._samples_sent = 0
        self._started_at: float | None = None
        #: Set once the buffer has been fully handed to the encoder.
        self.exhausted = asyncio.Event()

    @property
    def speech_seconds(self) -> float:
        return len(self._pcm) / 2 / self.sample_rate

    async def recv(self) -> av.AudioFrame:
        count = _frame_samples(self.sample_rate)
        if self._started_at is None:
            self._started_at = time.time()
        due = self._started_at + self._samples_sent / self.sample_rate
        delay = due - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

        wanted = count * 2
        chunk = self._pcm[self._offset : self._offset + wanted]
        self._offset += len(chunk)
        if len(chunk) < wanted:
            if not self.exhausted.is_set():
                self.exhausted.set()
            chunk = chunk + b"\x00" * (wanted - len(chunk))

        frame = av.AudioFrame(format="s16", layout="mono", samples=count)
        frame.planes[0].update(chunk)
        frame.sample_rate = self.sample_rate
        frame.pts = self._samples_sent
        frame.time_base = Fraction(1, self.sample_rate)
        self._samples_sent += count
        return frame


@dataclass
class ReturnPath:
    """What came back down the peer connection."""

    frames: int = 0
    samples: int = 0
    sample_rate: int = 0
    peak_abs: int = 0
    #: Samples whose magnitude is above the silence floor. Audio arriving is
    #: not the same claim as *audible* audio arriving, so both are counted.
    loud_samples: int = 0
    first_audible_at: float | None = None

    #: A sample is audible at roughly -50 dBFS, well under speech and well over
    #: codec noise on a silent channel.
    threshold: int = 100

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def audible_seconds(self) -> float:
        return self.loud_samples / self.sample_rate if self.sample_rate else 0.0

    def feed(self, frame: av.AudioFrame) -> None:
        samples = frame.to_ndarray().astype(np.int32).reshape(-1)
        self.frames += 1
        self.samples += samples.size
        self.sample_rate = frame.sample_rate or self.sample_rate
        if samples.size:
            magnitude = np.abs(samples)
            self.peak_abs = max(self.peak_abs, int(magnitude.max()))
            loud = int((magnitude > self.threshold).sum())
            self.loud_samples += loud
            if loud and self.first_audible_at is None:
                self.first_audible_at = time.time()


@dataclass
class HeadlessPeer:
    """One headless session against a running server."""

    base_url: str
    room: str
    token: str
    sample_rate: int = 16000
    pc: RTCPeerConnection = field(default_factory=RTCPeerConnection)
    messages: list[dict[str, Any]] = field(default_factory=list)
    returned: ReturnPath = field(default_factory=ReturnPath)
    pc_id: str | None = None
    answer_sdp: str = ""
    connected_at: float | None = None
    offered_at: float | None = None
    _mic: PcmMicTrack | None = None
    _reader: asyncio.Task | None = None
    _channel: Any = None
    _data_open: asyncio.Event = field(default_factory=asyncio.Event)
    _connected: asyncio.Event = field(default_factory=asyncio.Event)

    # -- connecting -------------------------------------------------------

    async def connect(self, *, mic_pcm: bytes, http: Any, restart_pc: bool = False) -> None:
        """Offer, answer, and come up. `http` is an `httpx.AsyncClient`."""
        channel = self.pc.createDataChannel("rove")
        self._channel = channel

        @channel.on("open")
        def _open() -> None:
            self._data_open.set()

        @channel.on("message")
        def _message(raw: Any) -> None:
            try:
                self.messages.append(json.loads(raw))
            except (TypeError, ValueError):
                self.messages.append({"type": "raw", "data": str(raw)})

        self._mic = PcmMicTrack(mic_pcm, sample_rate=self.sample_rate)
        self.pc.addTrack(self._mic)

        @self.pc.on("track")
        def _on_track(track: MediaStreamTrack) -> None:
            if track.kind == "audio":
                self._reader = asyncio.create_task(self._drain(track))

        @self.pc.on("connectionstatechange")
        async def _on_state() -> None:
            if self.pc.connectionState == "connected":
                self.connected_at = time.time()
                self._connected.set()

        await self.pc.setLocalDescription(await self.pc.createOffer())
        self.offered_at = time.time()
        response = await http.post(
            f"{self.base_url}/api/offer",
            json={
                "sdp": self.pc.localDescription.sdp,
                "type": self.pc.localDescription.type,
                "room": self.room,
                "token": self.token,
                "pc_id": self.pc_id,
                "restart_pc": restart_pc,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        answer = response.json()
        self.pc_id = answer.get("pc_id")
        self.answer_sdp = answer["sdp"]
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )

    async def wait_connected(self, timeout: float = 25.0) -> float:
        """Seconds from offer to ICE/DTLS up."""
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        return round((self.connected_at or time.time()) - (self.offered_at or time.time()), 3)

    async def _drain(self, track: MediaStreamTrack) -> None:
        while True:
            try:
                frame = await track.recv()
            except Exception:  # noqa: BLE001 — the track ends with the session
                return
            self.returned.feed(frame)

    # -- speaking ---------------------------------------------------------

    async def speak(self, extra_seconds: float = 1.0) -> None:
        """Wait out the microphone buffer, plus the VAD's hangover."""
        assert self._mic is not None
        await asyncio.wait_for(
            self._mic.exhausted.wait(),
            timeout=self._mic.speech_seconds + 15.0,
        )
        await asyncio.sleep(extra_seconds)

    # -- reading what came back -------------------------------------------

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("type") == kind]

    @property
    def speech_segments(self) -> list[dict[str, Any]]:
        return self.of_type("speech.end")

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.pc.close()


async def open_session(http: Any, base_url: str) -> dict[str, Any]:
    """`POST /api/session` — the mint, as the browser calls it."""
    response = await http.post(f"{base_url}/api/session", timeout=15.0)
    response.raise_for_status()
    return response.json()
