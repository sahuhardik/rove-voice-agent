"""Live end-to-end voice test against a running server (needs AWS).

    python -m tests.live_voice_roundtrip http://127.0.0.1:8000

A customer's words are synthesised by Polly as 16 kHz PCM (what the browser
sends), posted to /voice, transcribed by Transcribe, answered by the agent, and
the reply comes back with Polly audio. Checks each hop.
"""
import base64
import re
import sys
import time

import httpx

from rove import speech

LINES = [
    "Hi, my Rove R3 keeps restarting on its own when it's sunny.",
    "Yes, it comes back on after it cools down.",
]


def words(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", t.lower()))


def main(base: str) -> int:
    ok = True
    with httpx.Client(base_url=base, timeout=120) as c:
        s = c.post("/api/sessions").json()
        greet_audio = base64.b64decode(s["audio"] or "")
        print(f"greeting: {s['greeting']!r} audio={len(greet_audio)} bytes")
        ok &= len(greet_audio) > 1000
        for line in LINES:
            pcm = speech.synthesize(line, fmt="pcm")
            t0 = time.time()
            r = c.post(f"/api/sessions/{s['id']}/voice", content=pcm).json()
            dt = time.time() - t0
            overlap = len(words(line) & words(r["transcript"])) / len(words(line))
            audio = base64.b64decode(r["audio"] or "")
            print(f"\nsaid      : {line}\nheard     : {r['transcript']}  (word overlap {overlap:.0%})"
                  f"\nagent     : {r['say']}\nreply mp3 : {len(audio)} bytes   round trip {dt:.1f}s   model={r['case']['model']}")
            ok &= overlap >= 0.8 and len(audio) > 1000 and bool(r["say"])
        ok &= r["case"]["model"] == "R3"
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
