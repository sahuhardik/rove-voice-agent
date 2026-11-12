"""Stdlib unittest for the Phase 2b server.

    .venv/bin/python -m unittest server.test_server -v

Three things, because three things are what `docs/06` §9.1 asks Phase 2b to
show and the rest is already covered elsewhere:

1. **The mint is scoped the way §1.4.2 says.** A token expires after its TTL
   and is refused afterwards; a token minted for one room is refused on
   another. Both are asserted twice — once against `server/tokens.py` directly,
   where the rule is written, and once against a running server over HTTP,
   where the rule is actually enforced. A property that holds in the library
   and not at the endpoint is not a property this system has.
2. **A real peer connection.** A headless `aiortc` peer
   (`server/headless_peer.py`) offers, the server answers, ICE and DTLS come
   up, and the server reports frames it received on the data channel. No
   browser and no mock transport: the thing under test is a WebRTC session, so
   the test is one end of a WebRTC session.
3. **A typed turn reaches the real core.** `user.text` over `/ws`, and an agent
   transcript line comes back carrying a step id out of `eval.ontology` and an
   FSM state out of `agent.state` — neither of which exists anywhere in
   `server/`, which is what makes the assertion mean "the core answered" rather
   than "the server answered".

**Hermetic**: no AWS, no Bedrock, no network beyond loopback.

* The LLM is switched off (`use_llm=False`), so `agent.core.diagnose` runs on
  its rule-based floor. That is still the real core — `docs/07` D-06/D-07 treat
  the model as an advisor that may fail at any moment, so the floor is a
  supported path and not a stub.
* The microphone is a synthesised tone rather than Polly speech. These tests
  assert that *frames arrive*, not that Silero fires; `server/verify.py` is
  where the VAD is exercised against real speech, because a VAD that triggers
  on a sine wave has told you nothing.
* The greeting comes from the on-disk Polly cache when it is there. When it is
  not, `pipeline.py` traces `greeting.failed` and the session continues, so
  nothing here depends on it either way.

Imports are absolute against a forced `sys.path` entry, matching
`eval/test_harness.py`, so `discover -s server` works with no parent package.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import websockets  # noqa: E402

from agent.state import State  # noqa: E402
from eval import ontology  # noqa: E402
from server import headless_peer  # noqa: E402
from server import tokens as token_module  # noqa: E402
from server.config import TRANSPORT_SMALLWEBRTC, Settings  # noqa: E402
from server.verify import BackgroundServer, free_port  # noqa: E402

#: A fixed secret, so the expiry test can mint a stale token the server will
#: accept the signature of and reject the expiry of. `verify.py` does the same.
TEST_SECRET = "phase2b-test-secret-do-not-use-anywhere"

#: Loopback only. The documented bind is `0.0.0.0:8080` (`server/README.md`);
#: a test that took the documented port would collide with a running server.
TEST_HOST = "127.0.0.1"

_server: BackgroundServer | None = None
_trace_dir: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """One server for the whole module, on a free port, with no LLM."""
    global _server, _trace_dir
    _trace_dir = tempfile.TemporaryDirectory(prefix="rove-test-traces-")
    settings = dataclasses.replace(
        # `{}` rather than the ambient environment: a developer's exported
        # ROVE_* settings must not change what these tests assert.
        Settings.from_env({}),
        host=TEST_HOST,
        port=free_port(),
        # These are the **fallback transport's** tests and they say so out
        # loud. `/api/offer`, `/api/ice` and `server/tokens.py` are Phase 2b's
        # three surfaces; Phase 3 promoted the default to LiveKit (`docs/07`
        # D-02) and in that mode the first two refuse with 409 and the mint
        # issues a LiveKit JWT instead. Pinning the transport here is what
        # keeps D-02's "the fallback stays wired" a tested claim rather than a
        # comment — `server/test_livekit.py` and `server/verify_livekit.py`
        # are where the LiveKit path is exercised.
        transport=TRANSPORT_SMALLWEBRTC,
        token_secret=TEST_SECRET,
        token_secret_is_ephemeral=False,
        use_llm=False,
        trace_dir=Path(_trace_dir.name),
    )
    _server = BackgroundServer(settings).start()


def tearDownModule() -> None:
    global _server, _trace_dir
    if _server is not None:
        _server.stop()
        _server = None
    if _trace_dir is not None:
        _trace_dir.cleanup()
        _trace_dir = None


def base_url() -> str:
    assert _server is not None, "module fixture did not start"
    return _server.base_url


def ws_url() -> str:
    assert _server is not None, "module fixture did not start"
    return _server.ws_url


def tone_pcm(seconds: float, sample_rate: int = 16000, hz: float = 220.0) -> bytes:
    """A mono 16-bit PCM tone, amplitude-modulated so it is not a flat carrier.

    Enough to put real Opus frames on the wire, which is all the handshake test
    needs. Deliberately *not* speech: see this module's docstring.
    """
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    envelope = 0.5 * (1.0 - np.cos(2.0 * np.pi * 3.0 * t))
    samples = 0.3 * envelope * np.sin(2.0 * np.pi * hz * t)
    return (samples * 32767.0).astype("<i2").tobytes()


# --------------------------------------------------------------------------
# 1. The mint (§1.4.2)
# --------------------------------------------------------------------------


class TestTokenMint(unittest.TestCase):
    """Short-lived and single-room, in the library and at the endpoint."""

    ROOM = "room-test-aaaaaaaa"
    OTHER_ROOM = "room-test-bbbbbbbb"
    IDENTITY = "caller-test"

    # -- the rule, where it is written ------------------------------------

    def test_token_is_refused_once_its_ttl_has_elapsed(self) -> None:
        issued = 1_700_000_000.0
        ttl = 60
        token = token_module.mint(
            room=self.ROOM,
            identity=self.IDENTITY,
            secret=TEST_SECRET,
            ttl_seconds=ttl,
            now=issued,
        )

        claims = token_module.verify(
            token, secret=TEST_SECRET, room=self.ROOM, now=issued + 1
        )
        self.assertEqual(claims.ttl_seconds, ttl)
        self.assertEqual(claims.expires_at, int(issued) + ttl)

        # Still good one second before it lapses...
        token_module.verify(token, secret=TEST_SECRET, room=self.ROOM, now=issued + ttl - 1)
        # ...and refused from the moment it does. No grace window (§1.4.2).
        with self.assertRaises(token_module.TokenExpired):
            token_module.verify(token, secret=TEST_SECRET, room=self.ROOM, now=issued + ttl)
        with self.assertRaises(token_module.TokenExpired):
            token_module.verify(
                token, secret=TEST_SECRET, room=self.ROOM, now=issued + ttl + 3600
            )

    def test_token_minted_for_one_room_is_refused_on_another(self) -> None:
        token = token_module.mint(
            room=self.ROOM, identity=self.IDENTITY, secret=TEST_SECRET, ttl_seconds=300
        )
        self.assertEqual(
            token_module.verify(token, secret=TEST_SECRET, room=self.ROOM).room, self.ROOM
        )
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(token, secret=TEST_SECRET, room=self.OTHER_ROOM)
        # Single-identity is the same claim in the same signature.
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(
                token, secret=TEST_SECRET, room=self.ROOM, identity="caller-somebody-else"
            )

    def test_payload_carries_exactly_the_signed_claims_and_no_credential(self) -> None:
        """`server/tokens.py`'s docstring promises this file pins the claim set."""
        token = token_module.mint(
            room=self.ROOM, identity=self.IDENTITY, secret=TEST_SECRET
        )
        self.assertEqual(set(token_module.peek(token)), set(token_module.CLAIM_KEYS))

    def test_ttl_ceiling_is_enforced_at_the_mint(self) -> None:
        with self.assertRaises(ValueError):
            token_module.mint(
                room=self.ROOM,
                identity=self.IDENTITY,
                secret=TEST_SECRET,
                ttl_seconds=token_module.MAX_TTL_SECONDS + 1,
            )

    # -- the rule, where it is enforced -----------------------------------

    def test_server_refuses_an_expired_token_and_a_foreign_room(self) -> None:
        """The same two properties through HTTP, against the running server."""
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            first = http.post("/api/session").raise_for_status().json()
            second = http.post("/api/session").raise_for_status().json()
            self.assertNotEqual(first["room"], second["room"])
            self.assertLessEqual(first["ttl_seconds"], token_module.MAX_TTL_SECONDS)

            # Correctly signed for this room, but minted an hour ago: 401.
            stale = token_module.mint(
                room=first["room"],
                identity=first["identity"],
                secret=TEST_SECRET,
                ttl_seconds=60,
                now=time.time() - 3600,
            )
            expired = http.post(
                "/api/offer",
                json={"sdp": "", "type": "offer", "room": first["room"], "token": stale},
            )
            self.assertEqual(expired.status_code, 401, expired.text)

            # Valid and unexpired, but minted for the other room: 403.
            replayed = http.post(
                "/api/offer",
                json={
                    "sdp": "",
                    "type": "offer",
                    "room": second["room"],
                    "token": first["token"],
                },
            )
            self.assertEqual(replayed.status_code, 403, replayed.text)

            # And the same token on the room it *was* minted for gets past the
            # token check — it fails later, on the empty SDP, which is a 500
            # and not a 401/403. Without this the two assertions above would
            # also pass if every offer were refused.
            accepted = http.post(
                "/api/offer",
                json={
                    "sdp": "",
                    "type": "offer",
                    "room": first["room"],
                    "token": first["token"],
                },
            )
            self.assertNotIn(accepted.status_code, (401, 403), accepted.text)

            # Renewal needs an unexpired token for the room being renewed.
            renewed = http.post(
                f"/api/session/{first['room']}/token", json={"token": first["token"]}
            )
            self.assertEqual(renewed.status_code, 200, renewed.text)
            self.assertNotEqual(renewed.json()["token"], first["token"])

            stale_renewal = http.post(
                f"/api/session/{first['room']}/token", json={"token": stale}
            )
            self.assertEqual(stale_renewal.status_code, 401, stale_renewal.text)


# --------------------------------------------------------------------------
# 2. A real peer connection
# --------------------------------------------------------------------------


class TestHeadlessPeerHandshake(unittest.IsolatedAsyncioTestCase):
    """Offer, answer, connect, and frames arriving at the server."""

    async def test_peer_connects_and_the_server_receives_audio_frames(self) -> None:
        async with httpx.AsyncClient() as http:
            session = await headless_peer.open_session(http, base_url())
            peer = headless_peer.HeadlessPeer(
                base_url=base_url(),
                room=session["room"],
                token=session["token"],
                sample_rate=int(session["audio_sample_rate"]),
            )
            try:
                await peer.connect(
                    mic_pcm=tone_pcm(1.0, int(session["audio_sample_rate"])), http=http
                )

                # The answer is a real SDP answer, not an acknowledgement.
                self.assertTrue(peer.answer_sdp.startswith("v=0"), peer.answer_sdp[:80])
                self.assertIn("m=audio", peer.answer_sdp)
                self.assertTrue(peer.pc_id, "server returned no pc_id")

                setup_s = await peer.wait_connected(timeout=30.0)
                self.assertEqual(peer.pc.connectionState, "connected")
                self.assertGreaterEqual(setup_s, 0.0)

                await peer.speak(extra_seconds=1.0)

                # Frames counted by `SpeechReporter` on the server, reported
                # back over the WebRTC data channel. The count is the server's,
                # not ours — this is the server saying what it received.
                levels = peer.of_type("audio.level")
                self.assertTrue(levels, "no audio.level came back over the data channel")
                self.assertGreaterEqual(levels[-1]["frames"], 1)
                self.assertEqual(levels[-1]["sample_rate"], session["audio_sample_rate"])

                # And the server's own trace agrees about the handshake.
                trace = await http.get(
                    f"{base_url()}/api/trace/{session['room']}",
                    params={"token": session["token"]},
                    timeout=15.0,
                )
                trace.raise_for_status()
                types = {event["type"] for event in trace.json()["events"]}
                self.assertIn("webrtc.offer", types)
                self.assertIn("webrtc.answer", types)
                self.assertIn("webrtc.connected", types)
            finally:
                await peer.close()


# --------------------------------------------------------------------------
# 3. A typed turn, through /ws, into the real core
# --------------------------------------------------------------------------


class TestTypedTurn(unittest.IsolatedAsyncioTestCase):
    """§1.4.1: a typed string is a turn, and it reaches `agent.core`."""

    TURN_TIMEOUT_S = 120.0

    async def test_typed_turn_comes_back_as_an_agent_transcript_line(self) -> None:
        async with httpx.AsyncClient() as http:
            session = await headless_peer.open_session(http, base_url())

        url = f"{ws_url()}/ws?room={session['room']}&token={session['token']}"
        agent_line: dict | None = None
        reply: dict | None = None

        async with websockets.connect(url, open_timeout=20) as socket:
            hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
            self.assertEqual(hello.get("type"), "hello", hello)
            self.assertEqual(hello["snapshot"]["room"], session["room"])

            await socket.send(
                json.dumps(
                    {
                        "type": "user.text",
                        "text": "my rove r2-4k will not connect to wi-fi",
                        "modality": "typed",
                    }
                )
            )

            deadline = time.monotonic() + self.TURN_TIMEOUT_S
            while time.monotonic() < deadline and (agent_line is None or reply is None):
                remaining = max(1.0, deadline - time.monotonic())
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=remaining))
                kind = message.get("type")
                if kind == "error":
                    self.fail(f"server refused the typed turn: {message.get('detail')}")
                elif kind == "transcript" and message["line"]["role"] == "agent":
                    agent_line = message["line"]
                elif kind == "turn.reply":
                    reply = message["reply"]

        self.assertIsNotNone(agent_line, "no agent transcript line within the timeout")
        self.assertTrue(agent_line["text"].strip(), "the agent said nothing")
        self.assertEqual(agent_line["turn"], 1)

        self.assertIsNotNone(reply, "no turn.reply within the timeout")
        self.assertEqual(reply["text"], agent_line["text"])
        self.assertEqual(reply["modality"], "typed")

        # The answer came from the core, not from anything in `server/`: the
        # FSM state is one of `agent.state.State`, and the step — when there is
        # one — is a real id out of `eval.ontology`, which `server/` has no
        # copy of.
        self.assertIn(reply["state"]["fsm_state"], {s.value for s in State})
        self.assertTrue(
            reply["step"] or reply["escalate"],
            "the reply proposed no step and did not escalate",
        )
        if reply["step"]:
            self.assertIn(reply["step"]["step_id"], ontology.STEPS)
            self.assertTrue(reply["step"]["spoken"].strip())


if __name__ == "__main__":
    unittest.main()
