"""A browser-shaped LiveKit participant with no browser in it.

`server/headless_peer.py` is this file's Phase 2b sibling: it offers SDP at
`/api/offer` because that is what the Pipecat fallback expects. Phase 3's
browser does something different and simpler — it takes the minted token
straight to the media server and joins a room (`docs/06` §1.4.2) — so the
headless stand-in has to do that instead, and this is it.

It does exactly what `client/src/livekit.js` does and nothing more:

1. `room.connect(url, token)` with the credential `POST /api/session` minted;
2. publish one microphone track and push 20 ms PCM frames up **at real-time
   pace** — §1.4.2 is explicit that "injected audio is paced", because a VAD
   hangover measured against audio replayed faster than real time is fiction;
3. subscribe to the agent's track and count what comes back;
4. read the `rove` data topic beside it — levels, speech segments, ASR
   partials, endpoint decisions.

The microphone is Polly speech rather than a tone, for the same reason it is in
Phase 2b: **Silero VAD v5** (`docs/07` D-03) and **Amazon Transcribe** (D-05)
are the things under test on the way up, and neither tells you anything about a
sine wave. One cached synthesis call buys a fixture with real formants, real
pauses and real words in it — which is also the only way `turn.voice` can be
asserted to contain anything.

What this is **not**: a browser. It proves the room join, the media path, the
VAD, the recogniser, the endpointer and the return path. It cannot prove
`getUserMedia`, acoustic echo cancellation, the browser's jitter buffer or
`RTCPeerConnection.getStats()` — those need a human and a browser, and
`client/README.md` says which steps that takes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from livekit import rtc

#: 20 ms frames (`docs/06` §1.4.2).
FRAME_MS = 20

#: Anything quieter than this in a returned frame is the gap between words
#: rather than speech. Matches `server/headless_peer.py` so the two headless
#: paths report the same number for the same audio.
AUDIBLE_PEAK = 300


@dataclass
class ReturnPath:
    """What the agent said back, as the peer actually received it."""

    frames: int = 0
    samples: int = 0
    audible_samples: int = 0
    peak_abs: int = 0
    sample_rate: int = 0
    first_frame_at: float | None = None

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def audible_seconds(self) -> float:
        return self.audible_samples / self.sample_rate if self.sample_rate else 0.0

    def feed(self, frame: rtc.AudioFrame) -> None:
        samples = np.frombuffer(bytes(frame.data), dtype="<i2")
        if samples.size == 0:
            return
        if self.first_frame_at is None:
            self.first_frame_at = time.time()
        self.frames += 1
        self.sample_rate = frame.sample_rate
        self.samples += frame.samples_per_channel
        magnitude = np.abs(samples.astype(np.int32))
        peak = int(magnitude.max())
        self.peak_abs = max(self.peak_abs, peak)
        if peak >= AUDIBLE_PEAK:
            self.audible_samples += frame.samples_per_channel


class HeadlessParticipant:
    """One caller, joined to one room, with a PCM buffer for a microphone."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        sample_rate: int = 16000,
        identity: str = "",
    ) -> None:
        self.url = url
        self.token = token
        self.sample_rate = sample_rate
        self.identity = identity
        self.room = rtc.Room()
        self.messages: list[dict[str, Any]] = []
        self.returned = ReturnPath()
        self.agent_identity = ""
        self.connected_at = 0.0
        self._source: rtc.AudioSource | None = None
        self._tasks: set[asyncio.Task] = set()
        self._agent_joined = asyncio.Event()
        self._agent_track = asyncio.Event()

    # -- joining -----------------------------------------------------------

    async def connect(self, *, timeout: float = 30.0) -> None:
        room = self.room

        @room.on("data_received")
        def _data(packet: rtc.DataPacket) -> None:
            with contextlib.suppress(ValueError, TypeError):
                message = json.loads(bytes(packet.data))
                if isinstance(message, dict):
                    self.messages.append(message)

        @room.on("participant_connected")
        def _joined(participant: rtc.RemoteParticipant) -> None:
            self.agent_identity = participant.identity
            self._agent_joined.set()

        @room.on("track_subscribed")
        def _subscribed(
            track: rtc.Track, _publication: Any, participant: rtc.RemoteParticipant
        ) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self.agent_identity = self.agent_identity or participant.identity
                self._agent_track.set()
                self._spawn(self._drain(track), name="lk-peer-drain")

        started = time.perf_counter()
        await asyncio.wait_for(room.connect(self.url, self.token), timeout=timeout)
        self.connected_at = round(time.perf_counter() - started, 3)
        # A participant that was already in the room when we arrived: the
        # worker may well have been dispatched before our `connect` returned.
        for participant in room.remote_participants.values():
            self.agent_identity = participant.identity
            self._agent_joined.set()
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._agent_track.set()
                    self._spawn(self._drain(publication.track), name="lk-peer-drain")

    async def publish_microphone(self) -> None:
        self._source = rtc.AudioSource(self.sample_rate, 1)
        track = rtc.LocalAudioTrack.create_audio_track("caller-mic", self._source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

    async def wait_for_agent(self, timeout: float = 30.0) -> bool:
        """Block until the agent worker's job has joined this room."""
        try:
            await asyncio.wait_for(self._agent_joined.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def wait_for_agent_track(self, timeout: float = 30.0) -> bool:
        try:
            await asyncio.wait_for(self._agent_track.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    # -- speaking ----------------------------------------------------------

    async def speak(
        self,
        pcm: bytes,
        *,
        lead_silence_ms: int = 300,
        tail_silence_ms: int = 0,
    ) -> float:
        """Push one utterance up the link, paced against the wall clock.

        `capture_frame` blocks until the source has room, which is what makes
        the pacing real rather than asserted: the SDK's queue is the clock.
        Returns the audio duration pushed, in seconds.
        """
        if self._source is None:
            raise RuntimeError("publish_microphone() first")
        lead = b"\x00\x00" * int(self.sample_rate * lead_silence_ms / 1000)
        tail = b"\x00\x00" * int(self.sample_rate * tail_silence_ms / 1000)
        buffer = lead + pcm + tail
        frame_bytes = self.sample_rate * 2 * FRAME_MS // 1000
        samples = frame_bytes // 2
        for offset in range(0, len(buffer), frame_bytes):
            chunk = buffer[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            await self._source.capture_frame(
                rtc.AudioFrame(
                    data=chunk,
                    sample_rate=self.sample_rate,
                    num_channels=1,
                    samples_per_channel=samples,
                )
            )
        return len(buffer) / 2 / self.sample_rate

    async def hold_silence(self, seconds: float) -> None:
        """Keep the uplink alive with silence, at real-time pace.

        The endpointer's hangover is measured in milliseconds of *silence*, and
        silence that is never transmitted is not silence — it is a gap in the
        stream, which the VAD reads differently. So the pause after an
        utterance is pushed frame by frame exactly as the speech was.
        """
        if self._source is None:
            raise RuntimeError("publish_microphone() first")
        frame_bytes = self.sample_rate * 2 * FRAME_MS // 1000
        silence = b"\x00" * frame_bytes
        for _ in range(int(seconds * 1000 / FRAME_MS)):
            await self._source.capture_frame(
                rtc.AudioFrame(
                    data=silence,
                    sample_rate=self.sample_rate,
                    num_channels=1,
                    samples_per_channel=frame_bytes // 2,
                )
            )

    def note_typing(self) -> None:
        """§2.3's typing suppressor, over the data channel the page uses."""
        self._spawn(
            self.room.local_participant.publish_data(
                json.dumps({"type": "user.typing"}).encode("utf-8"),
                reliable=True,
                topic="rove",
            ),
            name="lk-peer-typing",
        )

    # -- reading -----------------------------------------------------------

    async def _drain(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=self.sample_rate, num_channels=1)
        try:
            async for event in stream:
                self.returned.feed(event.frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the track ends with the call
            pass
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("type") == kind]

    @property
    def speech_segments(self) -> list[dict[str, Any]]:
        return self.of_type("speech.end")

    async def wait_for_message(
        self, kind: str, timeout: float = 20.0, *, since: int = 0
    ) -> dict[str, Any] | None:
        """Wait for one data-channel message of `kind`, or give up.

        Messages **already received** count. The endpoint decisions this is
        used for are sent the instant they are taken — `endpoint.armed` lands
        between the greeting ending and the caller noticing, and
        `endpoint.fired` lands in the middle of the silence the caller is still
        pushing — so a wait that only looked at what arrived *after* it started
        would report "no endpoint.armed" about a session that had one. Pass
        `since` to wait for the next one past a mark the caller took itself.
        """
        deadline = time.time() + timeout
        seen = max(0, since)
        while time.time() < deadline:
            for message in self.messages[seen:]:
                if message.get("type") == kind:
                    return message
            seen = len(self.messages)
            await asyncio.sleep(0.05)
        return None

    # -- leaving -----------------------------------------------------------

    def _spawn(self, coro: Any, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        with contextlib.suppress(Exception):
            await self.room.disconnect()


async def open_session(http: Any, base_url: str) -> dict[str, Any]:
    """`POST /api/session` — the one credential the browser ever holds."""
    response = await http.post(f"{base_url}/api/session", timeout=30.0)
    response.raise_for_status()
    return response.json()
