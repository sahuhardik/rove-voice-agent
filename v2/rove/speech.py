"""Speech in and out on AWS: Transcribe streaming (speech -> text) and Polly (text -> speech)."""
from __future__ import annotations

import asyncio
import functools
import re

import boto3

from . import config

SAMPLE_RATE = 16_000
#: Words Transcribe should expect; improves model names and card markings.
HINT_PHRASES = ["Rove", "R2-4K", "R3", "Dual Pro", "dash cam", "SD card", "U3", "U1", "Wi-Fi", "firmware"]


#: Common speech-to-text mishearings of Rove product names (seen in testing: "Rove R3" -> "roar 3").
_NUM = r"(?:3|three)"
_FIXES = [
    (rf"\b(?:rove|roar|road|rover|row|rob)\s*(?:r|are|our|or)?\s*{_NUM}\b", "Rove R3"),
    (r"\b(?:roar|row|rob)\b(?=\s+(?:dash|cam|camera|r2|r3|dual|pro))", "Rove"),
    (r"\b(?:r|are|our)\s*(?:2|two|to|too)\s*[-\s]?\s*(?:4|four|for)\s*k\b", "R2-4K"),
    (rf"\b(?:r|are|our)\s*{_NUM}\b(?=\s+(?:dash|cam|camera|keeps|is|isn|won|doesn|has))", "R3"),
    (r"\bdual\s*(?:pro|bro|pr)\b", "Dual Pro"),
]
#: Card speed classes, only when the sentence is about a card ("you one" is otherwise ordinary speech).
_CARD_CONTEXT = re.compile(r"\b(card|class|says|rated|speed|label|marking|printed)\b", re.I)
_CARD_FIXES = [(r"\b(?:you|u)\s*(?:1|one)\b", "U1"), (r"\b(?:you|u)\s*(?:3|three)\b", "U3")]


def normalize_transcript(text: str) -> str:
    """Fix the product names speech recognition gets wrong, before the agent reads them."""
    for pat, rep in _FIXES:
        text = re.sub(pat, rep, text, flags=re.I)
    if _CARD_CONTEXT.search(text):
        for pat, rep in _CARD_FIXES:
            text = re.sub(pat, rep, text, flags=re.I)
    return text


async def transcribe_pcm(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe 16-bit mono PCM with Amazon Transcribe streaming. Returns the final text."""
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler

    client = TranscribeStreamingClient(region=config.REGION)
    stream = await client.start_stream_transcription(
        language_code="en-US", media_sample_rate_hz=sample_rate, media_encoding="pcm")
    finals: list[str] = []

    class Handler(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, event):
            for result in event.transcript.results:
                if not result.is_partial and result.alternatives:
                    finals.append(result.alternatives[0].transcript)

    async def feed():
        chunk = sample_rate * 2 // 10  # 100 ms of audio per event
        for i in range(0, len(pcm), chunk):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + chunk])
            await asyncio.sleep(0)  # no real-time pacing needed for a finished recording
        await stream.input_stream.end_stream()

    await asyncio.gather(feed(), Handler(stream.output_stream).handle_events())
    return normalize_transcript(" ".join(finals).strip())


@functools.lru_cache(maxsize=1)
def _polly():
    return boto3.client("polly", region_name=config.REGION)


def synthesize(text: str, fmt: str = "mp3") -> bytes:
    """Speech for a reply. fmt: "mp3" for browsers, "pcm" (16 kHz, 16-bit mono) for pipelines."""
    kwargs = {"Text": text, "VoiceId": config.POLLY_VOICE, "Engine": config.POLLY_ENGINE,
              "OutputFormat": fmt}
    if fmt == "pcm":
        kwargs["SampleRate"] = str(SAMPLE_RATE)
    return _polly().synthesize_speech(**kwargs)["AudioStream"].read()
