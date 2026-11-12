"""Live end-to-end test of the LiveKit voice path: a headless caller in a real room.

    # terminal 1: livekit-server --dev
    # terminal 2: python -m v2.voice.livekit_worker dev
    python -m v2.tests.live_livekit_call

The caller joins a room the way the browser does, waits for the agent's
greeting, speaks customer lines as real-time audio, records the agent's spoken
replies, transcribes them to check what was said, and collects the case-file
updates the worker publishes on the data channel.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

import numpy as np
from livekit import api, rtc

from v2.rove import speech

URL = os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
SR = 16000
LINES = ["Hi, my Rove R3 dash cam keeps restarting on its own when it's sunny outside."]


def rms(pcm: np.ndarray) -> float:
    return float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if len(pcm) else 0.0


async def main() -> int:
    room_name = f"test-{uuid.uuid4().hex[:6]}"
    token = (api.AccessToken(KEY, SECRET).with_identity("caller").with_name("Test caller")
             .with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt())
    room = rtc.Room()
    heard = bytearray()          # agent audio at 16 kHz mono
    last_voice = [0.0]
    cases: list[dict] = []

    async def record(track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=SR, num_channels=1)
        async for ev in stream:
            data = np.frombuffer(ev.frame.data, dtype=np.int16)
            heard.extend(data.tobytes())
            if rms(data) > 300:
                last_voice[0] = time.time()

    @room.on("track_subscribed")
    def _on_track(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.ensure_future(record(track))

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket):
        if packet.topic == "rove.case":
            cases.append(json.loads(packet.data))

    await room.connect(URL, token)
    print(f"joined {room_name}")
    source = rtc.AudioSource(SR, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    async def wait_for_agent_speech(timeout: float) -> bytes:
        start, mark = time.time(), len(heard)
        while time.time() - start < timeout:
            await asyncio.sleep(0.2)
            spoke = last_voice[0] > start
            if spoke and time.time() - last_voice[0] > 1.5:  # finished talking
                break
        return bytes(heard[mark:])

    async def speak(text: str) -> None:
        pcm = np.frombuffer(speech.synthesize(text, fmt="pcm"), dtype=np.int16)
        pcm = np.concatenate([pcm, np.zeros(SR * 2, dtype=np.int16)])  # trailing silence ends the turn
        step = SR // 100  # 10 ms frames, real-time pace
        for i in range(0, len(pcm) - step, step):
            frame = rtc.AudioFrame(pcm[i:i + step].tobytes(), SR, 1, step)
            await source.capture_frame(frame)

    ok = True
    greeting = await wait_for_agent_speech(30)
    g_text = await speech.transcribe_pcm(greeting) if greeting else ""
    print(f"agent greeting (transcribed): {g_text!r}")
    ok &= "rove" in g_text.lower()

    for line in LINES:
        print(f"\ncaller says : {line}")
        t0 = time.time()
        speak_task = asyncio.create_task(speak(line))
        await speak_task
        spoke_at = time.time()
        reply = await wait_for_agent_speech(60)
        r_text = await speech.transcribe_pcm(reply) if reply else ""
        first_voice = last_voice[0]
        print(f"agent said  : {r_text!r}")
        print(f"timing      : speaking took {spoke_at - t0:.1f}s, agent finished {time.time() - spoke_at:.1f}s after caller stopped")
        ok &= len(r_text.split()) >= 5

    await asyncio.sleep(1)
    print(f"\ncase updates on data channel: {len(cases)}; last model = {cases[-1]['case']['model'] if cases else None}")
    ok &= bool(cases) and cases[-1]["case"]["model"] == "R3"
    await room.disconnect()
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
