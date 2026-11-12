"""Join a LiveKit room over the secure (wss via /lk relay) URL, headless.

    scripts/serve_https_testing.sh &           # TESTING-ONLY self-signed cert
    SSL_CERT_FILE=server/testing-tls/TESTING-ONLY-ca.pem \
      .venv/bin/python -m server.verify_wss https://127.0.0.1:8443

Mints through the HTTPS page's own `/api/session`, asserts the browser would be
handed `wss://<host>/lk`, then joins with `server/livekit_peer.py` and waits
for the agent worker and its voice track. Does not start or stop livekit-server.
TESTING ONLY: certificate verification of the mint call is off; the media-side
TLS check is made trusting the test cert through SSL_CERT_FILE.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from server import livekit_peer


async def main(base: str) -> int:
    async with httpx.AsyncClient(verify=False, timeout=15) as client:  # noqa: S501 testing cert
        reply = await client.post(f"{base}/api/session")
        reply.raise_for_status()
        session = reply.json()
    url = session["livekit_url"]
    print(f"minted livekit_url = {url}")
    if not url.startswith("wss://") or not url.endswith("/lk"):
        print("FAIL: not a wss relay URL")
        return 1
    peer = livekit_peer.HeadlessParticipant(
        url=url,
        token=session["token"],
        sample_rate=int(session.get("audio_sample_rate", 16000)),
        identity=session["identity"],
    )
    await peer.connect()
    print(f"PASS joined room over wss in {peer.connected_at}s")
    joined = await peer.wait_for_agent(timeout=45.0)
    print(f"{'PASS' if joined else 'FAIL'} agent joined: {peer.agent_identity or 'nobody'}")
    track = joined and await peer.wait_for_agent_track(timeout=30.0)
    print(f"{'PASS' if track else 'FAIL'} agent voice track subscribed")
    await peer.room.disconnect()
    return 0 if joined and track else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://127.0.0.1:8443")))
