"""Verify the Phase 2b server from outside itself.

    .venv/bin/python -m server.verify            # start a server, verify it, stop it
    .venv/bin/python -m server.verify --url http://host:8080 --secret <s>

Four things, in the order that makes a failure readable — each one only runs if
the one before it held:

1. **The process serves.** `/healthz` over a real socket on the bound port.
2. **The mint is what §1.4.2 says it is.** Short-lived (a TTL inside the
   ceiling, an expiry in the near future), single-room (a token minted for one
   room is refused on another), single-identity, unforgeable (a flipped byte is
   refused), and expiring (a token minted in the past is refused *now*, which
   needs the signing secret and so only runs when we have it).
3. **The transport carries audio both ways.** A headless `aiortc` peer
   (`server/headless_peer.py`) offers, connects, speaks Polly-synthesised
   audio up the link, and the server reports Silero VAD v5 speech segments on
   the data channel while Polly's greeting arrives back on the return path.
4. **The click-or-type path reaches the real core.** A typed turn over the
   control socket comes back with a step and a diagnostic state, produced by
   `agent.core.diagnose` and not by anything in `server/`.

The exit code is 0 only if every check passed. `--json` prints the report as
one object, which is what `server/README.md` tells you to paste into a
milestone note.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
import websockets

from server import headless_peer, polly
from server import tokens as token_module
from server.app import create_app
from server.config import TRANSPORT_SMALLWEBRTC, Settings

#: What the headless peer says into the microphone. A sentence rather than a
#: word: §2.3's hangover only means anything over speech with pauses in it.
MIC_LINE = (
    "Hello, this is a headless test peer speaking into the microphone. "
    "The camera stopped recording after the last firmware update."
)


# --------------------------------------------------------------------------
# Running the server in-process
# --------------------------------------------------------------------------


class BackgroundServer:
    """`uvicorn` on its own thread, bound for real on `settings.host`.

    A thread rather than a subprocess so the verification and the tests can
    assert on exit codes and tracebacks directly; a real bound socket rather
    than ASGI-in-memory because ASGI transport cannot carry a peer connection
    and the peer connection is the thing being verified.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app = create_app(settings)
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=settings.host,
                port=settings.port,
                log_level="warning",
                access_log=False,
                ssl_certfile=settings.tls_certfile or None,
                ssl_keyfile=settings.tls_keyfile or None,
            )
        )
        self._thread = threading.Thread(target=self._server.run, name="rove-web", daemon=True)

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.settings.host in ("0.0.0.0", "::") else self.settings.host
        return f"{self.settings.scheme}://{host}:{self.settings.port}"

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http", "ws", 1)

    def start(self, timeout: float = 30.0) -> "BackgroundServer":
        self._thread.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._server.started:
                return self
            if not self._thread.is_alive():
                raise RuntimeError("server thread died during startup")
            time.sleep(0.05)
        raise TimeoutError(f"server did not bind {self.settings.host}:{self.settings.port}")

    def stop(self, timeout: float = 15.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)

    def __enter__(self) -> "BackgroundServer":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


@dataclass
class Report:
    checks: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def fact(self, name: str, value: Any) -> None:
        self.facts[name] = value

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def render(self) -> str:
        lines = []
        for item in self.checks:
            mark = "PASS" if item["ok"] else "FAIL"
            lines.append(f"  [{mark}] {item['check']}" + (f" — {item['detail']}" if item["detail"] else ""))
        lines.append("")
        for key, value in self.facts.items():
            lines.append(f"  {key:34s} {value}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


async def verify_mint(http: httpx.AsyncClient, base_url: str, secret: str, report: Report) -> dict:
    """§1.4.2: short-lived, single-room, single-identity, and ours."""
    first = await headless_peer.open_session(http, base_url)
    second = await headless_peer.open_session(http, base_url)

    report.check(
        "mint returns a token, a room and an identity",
        bool(first.get("token") and first.get("room") and first.get("identity")),
    )
    ttl = int(first.get("ttl_seconds", 0))
    report.check(
        "token is short-lived",
        0 < ttl <= token_module.MAX_TTL_SECONDS,
        f"ttl={ttl}s, ceiling={token_module.MAX_TTL_SECONDS}s",
    )
    remaining = int(first.get("expires_at", 0)) - int(time.time())
    report.check(
        "token expiry is in the near future",
        0 < remaining <= ttl + 2,
        f"{remaining}s remaining",
    )
    claims = token_module.peek(first["token"])
    report.check(
        "token carries exactly the seven signed claims and no credential",
        set(claims) == set(token_module.CLAIM_KEYS),
        ",".join(sorted(claims)),
    )
    report.check(
        "rooms are distinct per session",
        first["room"] != second["room"] and first["identity"] != second["identity"],
    )

    # Single-room: the whole point of §1.4.2's scope.
    replay = await http.post(
        f"{base_url}/api/offer",
        json={"sdp": "", "type": "offer", "room": second["room"], "token": first["token"]},
    )
    report.check(
        "a token minted for one room is refused on another",
        replay.status_code == 403,
        f"HTTP {replay.status_code}",
    )

    tampered = first["token"][:-2] + ("aa" if not first["token"].endswith("aa") else "bb")
    forged = await http.post(
        f"{base_url}/api/offer",
        json={"sdp": "", "type": "offer", "room": first["room"], "token": tampered},
    )
    report.check(
        "a tampered signature is refused",
        forged.status_code == 403,
        f"HTTP {forged.status_code}",
    )

    missing = await http.post(
        f"{base_url}/api/offer",
        json={"sdp": "", "type": "offer", "room": first["room"], "token": ""},
    )
    report.check(
        "a room id with no token buys nothing",
        missing.status_code == 401,
        f"HTTP {missing.status_code}",
    )

    if secret:
        stale = token_module.mint(
            room=first["room"],
            identity=first["identity"],
            secret=secret,
            ttl_seconds=60,
            now=time.time() - 3600,
        )
        expired = await http.post(
            f"{base_url}/api/offer",
            json={"sdp": "", "type": "offer", "room": first["room"], "token": stale},
        )
        report.check(
            "a correctly signed but expired token is refused",
            expired.status_code == 401,
            f"HTTP {expired.status_code}",
        )
    else:
        report.fact("expiry check", "skipped — signing secret not known to this process")

    return first


async def verify_media(
    http: httpx.AsyncClient, base_url: str, session: dict, report: Report
) -> headless_peer.HeadlessPeer:
    """The handshake, the VAD and the return path, with no browser involved."""
    sample_rate = int(session.get("audio_sample_rate", 16000))
    try:
        mic_pcm = await asyncio.to_thread(
            polly.synthesize_pcm, MIC_LINE, sample_rate=sample_rate, cache_dir=None
        )
    except polly.PollyUnavailable as exc:
        report.check("microphone fixture synthesised", False, str(exc))
        raise

    peer = headless_peer.HeadlessPeer(
        base_url=base_url,
        room=session["room"],
        token=session["token"],
        sample_rate=sample_rate,
    )
    await peer.connect(mic_pcm=mic_pcm, http=http)
    report.check("server answered the SDP offer", bool(peer.answer_sdp))
    setup_s = await peer.wait_connected()
    report.check("peer connection reached `connected`", True, f"{setup_s}s from offer")
    report.fact("ice/dtls setup", f"{setup_s} s")

    await peer.speak(extra_seconds=2.0)
    # The server samples its RTCP view on a timer; give it one period.
    await asyncio.sleep(1.5)

    levels = peer.of_type("audio.level")
    segments = peer.speech_segments
    report.check(
        "audio frames arrived at the server",
        bool(levels) and levels[-1].get("frames", 0) > 50,
        f"{levels[-1].get('frames') if levels else 0} frames of 20 ms",
    )
    report.check(
        "Silero VAD v5 reported at least one speech segment",
        len(segments) >= 1,
        f"{len(segments)} segment(s): "
        + ", ".join(f"{s.get('duration_ms')}ms" for s in segments),
    )
    report.check(
        "Polly greeting played back on the return path",
        peer.returned.audible_seconds > 0.5,
        f"{peer.returned.frames} frames, {peer.returned.audible_seconds:.2f}s audible, "
        f"peak {peer.returned.peak_abs}",
    )
    report.fact("data-channel messages", len(peer.messages))
    report.fact("audio in (server saw)", f"{levels[-1].get('frames') if levels else 0} frames")
    report.fact(
        "audio out (peer heard)",
        f"{peer.returned.seconds:.2f}s total, {peer.returned.audible_seconds:.2f}s audible "
        f"at {peer.returned.sample_rate} Hz",
    )
    return peer


async def verify_trace(
    http: httpx.AsyncClient, base_url: str, session: dict, report: Report
) -> dict:
    response = await http.get(
        f"{base_url}/api/trace/{session['room']}", params={"token": session["token"]}
    )
    response.raise_for_status()
    body = response.json()
    summary = body["summary"]
    types = {event["type"] for event in body["events"]}
    report.check("trace recorded the connect", "webrtc.connected" in types)
    report.check("trace recorded the greeting", "greeting.played" in types)
    report.check("trace recorded VAD segments", summary["speech_segments"] >= 1)
    server_net = summary["network"]["server"]
    report.check(
        "trace recorded RTT/jitter/loss from the server end",
        server_net.get("samples", 0) >= 1,
        f"{server_net.get('samples')} sample(s)",
    )
    report.fact("server-side network", json.dumps(server_net.get("rtt_ms") or {}, sort_keys=True))
    report.fact("server-side jitter", json.dumps(server_net.get("jitter_ms") or {}, sort_keys=True))
    report.fact("server-side loss", f"{server_net.get('loss_pct')}%")
    report.fact("trace file", summary.get("trace_path"))
    return summary


async def verify_typed_turn(ws_url: str, session: dict, report: Report) -> dict | None:
    """§1.4.1: a typed string is a turn, and it reaches the real core."""
    url = f"{ws_url}/ws?room={session['room']}&token={session['token']}"
    reply: dict | None = None
    async with websockets.connect(url, open_timeout=20) as socket:
        hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
        report.check("control socket accepted the join token", hello.get("type") == "hello")
        started = time.perf_counter()
        await socket.send(
            json.dumps(
                {
                    "type": "user.text",
                    "text": "my rove r2-4k stopped recording after the firmware update",
                    "modality": "typed",
                }
            )
        )
        deadline = time.time() + 120
        while time.time() < deadline:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=120))
            if message.get("type") == "turn.reply":
                reply = message["reply"]
                break
            if message.get("type") == "error":
                report.check("typed turn answered", False, str(message.get("detail")))
                return None
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    if reply is None:
        report.check("typed turn answered", False, "no turn.reply within 120s")
        return None
    report.check("typed turn answered with words", bool(reply.get("text")))
    report.check(
        "reply carries a current step or an escalation",
        bool(reply.get("step")) or bool(reply.get("escalate")),
        (reply.get("step") or {}).get("step_id") or "escalated",
    )
    report.check(
        "reply carries the diagnostic state",
        bool(reply.get("state", {}).get("fsm_state")),
        reply["state"]["fsm_state"],
    )
    report.fact("typed turn round trip", f"{elapsed_ms} ms (wall, over the socket)")
    report.fact("reply", (reply.get("text") or "")[:120])
    return reply


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def run(base_url: str, ws_url: str, secret: str, report: Report) -> None:
    async with httpx.AsyncClient() as http:
        health = await http.get(f"{base_url}/healthz", timeout=15.0)
        report.check("server answers /healthz", health.status_code == 200, base_url)
        report.fact("health", json.dumps(health.json(), sort_keys=True))

        session = await verify_mint(http, base_url, secret, report)
        peer = await verify_media(http, base_url, session, report)
        try:
            await verify_trace(http, base_url, session, report)
            await verify_typed_turn(ws_url, session, report)
        finally:
            await peer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="verify a server already running here")
    parser.add_argument("--secret", default="", help="its ROVE_TOKEN_SECRET, for the expiry check")
    parser.add_argument("--port", type=int, default=0, help="port to bind when starting one")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    report = Report()
    started_here: BackgroundServer | None = None
    try:
        if args.url:
            base_url = args.url.rstrip("/")
            ws_url = base_url.replace("http", "ws", 1)
            secret = args.secret
        else:
            secret = "verify-" + str(int(time.time()))
            # This verifier is the SmallWebRTC fallback's verifier. The
            # process default is the LiveKit transport (D-02), and in that
            # mode /api/offer is not a surface at all — the token checks below
            # would fail against the transport gate instead of the token.
            settings = dataclasses.replace(
                Settings.from_env(),
                transport=TRANSPORT_SMALLWEBRTC,
                port=args.port or free_port(),
                token_secret=secret,
                token_secret_is_ephemeral=False,
            )
            started_here = BackgroundServer(settings).start()
            base_url, ws_url = started_here.base_url, started_here.ws_url
            print(f"started a server on {settings.host}:{settings.port}", flush=True)

        asyncio.run(run(base_url, ws_url, secret, report))
    except Exception as exc:  # noqa: BLE001 — a crash is a failed verification
        report.check("verification completed", False, f"{type(exc).__name__}: {exc}")
    finally:
        if started_here is not None:
            started_here.stop()

    if args.json:
        print(json.dumps({"ok": report.ok, "checks": report.checks, "facts": report.facts}, indent=2))
    else:
        print("\nPhase 2b server verification\n")
        print(report.render())
        print("\n" + ("ALL CHECKS PASSED" if report.ok else "FAILED") + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
