"""Stdlib unittest for the Phase 4 scaffolding (`docs/06` §5.2, §5.3, §6.3).

    .venv/bin/python -m unittest server.test_support -v

`server/test_server.py` covers Phase 2b — the mint, a real peer connection, a
typed turn into the real core. This covers what Milestone 7.1 adds on top, and
it is organised around the four properties that, if any one of them were only
true by convention, would make the rest of this milestone unsafe to run a pilot
on:

1. **The observer is not the caller, in both directions.** An `observe:room`
   token cannot reach a caller surface and a `join:room` token cannot reach a
   support surface. Asserted twice, the way `test_server.py` asserts the room
   scope twice: once against `server/tokens.py`, where the rule is written, and
   once over HTTP against a running server, where it is enforced. A property
   that holds in the library and not at the endpoint is not a property this
   system has.
2. **Nothing is stored until a storage decision exists** (§6.3), and *display*
   and *storage* are decided separately. The ordering matters as much as the
   answer, so one test calls `collect` on an un-consented session pointed at a
   DSN that does not resolve and asserts the refusal is `ConsentRequired` and
   not `StoreUnavailable` — proof the gate ran before the connection.
3. **The join flips the agent** (§5.3). Not "the console shows a badge": the
   caller's next turn must reach the transcript and *not* reach
   `agent.core.diagnose`, and the ledger must not grow a step nobody spoke.
4. **The console builds and serves.** `node support/build.mjs`, then `/support`
   and its assets over HTTP from the same process.

**Hermetic, with one exception stated plainly.** No AWS, no Bedrock, no network
beyond loopback, and the LLM is off so `agent.core.diagnose` runs on its
rule-based floor. The exception is Postgres: the §9.1 Phase 4 corpus is a
Postgres corpus (`docs/07` D-12), so the write path is tested against a real
database when one is reachable and the end-to-end collection test skips when it
is not. The *gate* is tested either way, because the gate is the part that must
never depend on the database being there.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402
import websockets  # noqa: E402

from server import consent as consent_module  # noqa: E402
from server import tokens as token_module  # noqa: E402
from server import transcripts as transcript_store  # noqa: E402
from server.config import Settings  # noqa: E402
from server.core_bridge import (  # noqa: E402
    AGENT_MODE_PROPOSING,
    AGENT_MODE_TRANSCRIBING,
    SessionRegistry,
)
from server.verify import BackgroundServer, free_port  # noqa: E402

TEST_SECRET = "phase4-test-secret-do-not-use-anywhere"
TEST_SUPPORT_KEY = "phase4-test-support-key"
TEST_HOST = "127.0.0.1"

#: A DSN that cannot resolve, on purpose. Used to prove that the §6.3 consent
#: gate runs *before* anything opens a connection: if the gate were second,
#: this would surface as `StoreUnavailable` instead.
UNREACHABLE_DSN = "postgresql://nobody@203.0.113.1:5432/nothing?connect_timeout=1"

_server: BackgroundServer | None = None
_trace_dir: tempfile.TemporaryDirectory | None = None
_console_built = ""
_console_selftest = ""
_collected: list[str] = []


def _run_node(script: str) -> str:
    """Run one of the console's Node scripts; return its output or the failure."""
    try:
        result = subprocess.run(
            ["node", str(_REPO_ROOT / "support" / script)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"node unavailable: {exc}"
    if result.returncode != 0:
        return f"{script} failed ({result.returncode}): {result.stderr.strip()}"
    return result.stdout.strip()


def setUpModule() -> None:
    """Build the console, self-test it, then start one server for the module."""
    global _server, _trace_dir, _console_built, _console_selftest
    _console_built = _run_node("build.mjs")
    _console_selftest = (
        _run_node("selftest.mjs")
        if "failed" not in _console_built and "unavailable" not in _console_built
        else "skipped — the build did not produce a tree to test"
    )

    _trace_dir = tempfile.TemporaryDirectory(prefix="rove-test-support-")
    settings = dataclasses.replace(
        Settings.from_env({}),
        host=TEST_HOST,
        port=free_port(),
        token_secret=TEST_SECRET,
        token_secret_is_ephemeral=False,
        support_key=TEST_SUPPORT_KEY,
        support_key_is_ephemeral=False,
        use_llm=False,
        trace_dir=Path(_trace_dir.name),
    )
    _server = BackgroundServer(settings).start()


def tearDownModule() -> None:
    global _server, _trace_dir
    # The corpus is a real table; a test that writes to it tidies up after
    # itself rather than leaving rows a later reader would take for pilot data.
    for session_id in _collected:
        try:
            transcript_store.connect().execute(
                "DELETE FROM pilot_sessions WHERE session_id = %s", (session_id,)
            )
        except Exception:  # noqa: BLE001
            pass
    transcript_store.reset_connection()
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


def open_caller_session(http: httpx.Client) -> dict:
    return http.post("/api/session").raise_for_status().json()


def mint_observer(http: httpx.Client, room: str, key: str = TEST_SUPPORT_KEY):
    return http.post("/api/support/observer", json={"key": key, "room": room})


async def recv_until(socket, kinds: set[str], timeout: float = 90.0) -> dict:
    """Read until one of `kinds` arrives. An `error` fails the test loudly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(1.0, deadline - time.monotonic())
        message = json.loads(await asyncio.wait_for(socket.recv(), timeout=remaining))
        if message.get("type") in kinds:
            return message
        if message.get("type") == "error" and "error" not in kinds:
            raise AssertionError(f"server refused: {message.get('detail')}")
    raise AssertionError(f"none of {sorted(kinds)} arrived within {timeout}s")


# --------------------------------------------------------------------------
# 1. The observer is not the caller — in the library
# --------------------------------------------------------------------------


class TestObserverTokenScope(unittest.TestCase):
    """`docs/06` §5.3: a separate scope and a separate identity, not a widened
    copy of the caller's token."""

    ROOM = "room-support-aaaaaaaa"
    OTHER_ROOM = "room-support-bbbbbbbb"

    def caller_token(self, room: str | None = None) -> tuple[str, str]:
        identity = token_module.new_identity()
        return (
            token_module.mint(
                room=room or self.ROOM, identity=identity, secret=TEST_SECRET
            ),
            identity,
        )

    def observer_token(self, room: str | None = None) -> tuple[str, str]:
        identity = token_module.new_observer_identity()
        return (
            token_module.mint(
                room=room or self.ROOM,
                identity=identity,
                secret=TEST_SECRET,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            ),
            identity,
        )

    def test_the_two_scopes_and_their_identities_are_disjoint(self) -> None:
        self.assertNotEqual(token_module.SCOPE_JOIN_ROOM, token_module.SCOPE_OBSERVE_ROOM)
        caller = token_module.new_identity()
        observer = token_module.new_observer_identity()
        self.assertTrue(caller.startswith("caller-"))
        self.assertTrue(observer.startswith("observer-"))
        self.assertFalse(observer.startswith("caller-"))
        self.assertFalse(caller.startswith("observer-"))

    def test_an_observer_token_cannot_be_verified_as_the_caller(self) -> None:
        """The default `verify` asks "is this the caller?" — and it is not."""
        token, identity = self.observer_token()
        # The scope it *was* minted for passes.
        claims = token_module.verify(
            token,
            secret=TEST_SECRET,
            room=self.ROOM,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
        self.assertEqual(claims.scope, token_module.SCOPE_OBSERVE_ROOM)
        self.assertEqual(claims.identity, identity)

        # The caller scope — which is the default, and therefore what every
        # pre-existing call site asks — does not.
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(token, secret=TEST_SECRET, room=self.ROOM)
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(
                token,
                secret=TEST_SECRET,
                room=self.ROOM,
                scope=token_module.SCOPE_JOIN_ROOM,
            )

    def test_a_caller_token_cannot_be_verified_as_an_observer(self) -> None:
        token, identity = self.caller_token()
        self.assertEqual(
            token_module.verify(token, secret=TEST_SECRET, room=self.ROOM).identity,
            identity,
        )
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(
                token,
                secret=TEST_SECRET,
                room=self.ROOM,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            )

    def test_an_observer_token_is_still_single_room_and_short_lived(self) -> None:
        """§1.4.2's three properties hold for the fourth scope too."""
        token, _ = self.observer_token()
        with self.assertRaises(token_module.TokenScopeError):
            token_module.verify(
                token,
                secret=TEST_SECRET,
                room=self.OTHER_ROOM,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            )
        issued = 1_700_000_000.0
        stale = token_module.mint(
            room=self.ROOM,
            identity=token_module.new_observer_identity(),
            secret=TEST_SECRET,
            ttl_seconds=60,
            scope=token_module.SCOPE_OBSERVE_ROOM,
            now=issued,
        )
        with self.assertRaises(token_module.TokenExpired):
            token_module.verify(
                stale,
                secret=TEST_SECRET,
                room=self.ROOM,
                scope=token_module.SCOPE_OBSERVE_ROOM,
                now=issued + 60,
            )
        with self.assertRaises(ValueError):
            token_module.mint(
                room=self.ROOM,
                identity=token_module.new_observer_identity(),
                secret=TEST_SECRET,
                ttl_seconds=token_module.MAX_TTL_SECONDS + 1,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            )

    def test_the_mint_refuses_a_scope_and_identity_that_disagree(self) -> None:
        """A signed token that lied about itself would read as the caller at
        any call site that checked only one of the two claims."""
        with self.assertRaises(ValueError):
            token_module.mint(
                room=self.ROOM,
                identity=token_module.new_identity(),  # caller-…
                secret=TEST_SECRET,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            )
        with self.assertRaises(ValueError):
            token_module.mint(
                room=self.ROOM,
                identity=token_module.new_observer_identity(),  # observer-…
                secret=TEST_SECRET,
                scope=token_module.SCOPE_JOIN_ROOM,
            )
        with self.assertRaises(ValueError):
            token_module.mint(
                room=self.ROOM,
                identity="someone-else",
                secret=TEST_SECRET,
                scope=token_module.SCOPE_OBSERVE_ROOM,
            )


# --------------------------------------------------------------------------
# 2. The observer is not the caller — at the endpoints
# --------------------------------------------------------------------------


class TestObserverScopeOverHttp(unittest.TestCase):
    """The same property where it is enforced: both directions, every surface."""

    def test_the_observer_mint_needs_the_support_key(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            self.assertEqual(mint_observer(http, session["room"], "").status_code, 401)
            self.assertEqual(
                mint_observer(http, session["room"], "not-the-key").status_code, 401
            )
            self.assertEqual(
                mint_observer(http, "room-does-not-exist").status_code, 404
            )
            self.assertEqual(
                http.get("/api/support/rooms", params={"key": "wrong"}).status_code, 401
            )
            ok = mint_observer(http, session["room"])
            self.assertEqual(ok.status_code, 200, ok.text)

    def test_the_minted_observer_is_a_separate_scope_and_identity(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()

            self.assertEqual(observer["scope"], token_module.SCOPE_OBSERVE_ROOM)
            self.assertTrue(observer["identity"].startswith("observer-"))
            self.assertNotEqual(observer["identity"], session["identity"])
            self.assertNotEqual(observer["token"], session["token"])
            self.assertLessEqual(observer["ttl_seconds"], token_module.MAX_TTL_SECONDS)

            claims = token_module.peek(observer["token"])
            self.assertEqual(claims["scope"], token_module.SCOPE_OBSERVE_ROOM)
            self.assertEqual(claims["room"], session["room"])
            # Two mints in the same room are two identities: the room is the
            # unit of access, not the person (§5.3).
            second = mint_observer(http, session["room"]).raise_for_status().json()
            self.assertNotEqual(second["identity"], observer["identity"])

    def test_an_observer_token_is_refused_on_every_caller_surface(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            room, token = session["room"], observer["token"]

            trace = http.get(f"/api/trace/{room}", params={"token": token})
            self.assertEqual(trace.status_code, 403, trace.text)

            offer = http.post(
                "/api/offer", json={"sdp": "", "type": "offer", "room": room, "token": token}
            )
            self.assertEqual(offer.status_code, 403, offer.text)

            ice = http.post("/api/ice", json={"room": room, "token": token, "candidates": []})
            self.assertEqual(ice.status_code, 403, ice.text)

            renew = http.post(f"/api/session/{room}/token", json={"token": token})
            self.assertEqual(renew.status_code, 403, renew.text)

            # And the caller's own token still works on the same surface, so
            # the four assertions above are not passing because everything is
            # refused.
            self.assertEqual(
                http.get(f"/api/trace/{room}", params={"token": session["token"]}).status_code,
                200,
            )

    def test_a_caller_token_is_refused_on_every_support_surface(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            room, token = session["room"], session["token"]

            handoff = http.get(f"/api/support/room/{room}/handoff", params={"token": token})
            self.assertEqual(handoff.status_code, 403, handoff.text)

            trace = http.get(f"/api/support/room/{room}/trace", params={"token": token})
            self.assertEqual(trace.status_code, 403, trace.text)

            for path, body in (
                ("disclose", {"token": token}),
                ("join", {"token": token}),
                ("leave", {"token": token}),
                ("collect", {"token": token}),
            ):
                response = http.post(f"/api/support/room/{room}/{path}", json=body)
                self.assertEqual(response.status_code, 403, f"{path}: {response.text}")

            # The support key is not a token either: it authorises the mint and
            # only the mint. It is not even the right shape, which is what the
            # 403 says — there is no path by which holding the key alone opens
            # a session.
            keyed = http.get(
                f"/api/support/room/{room}/handoff", params={"token": TEST_SUPPORT_KEY}
            )
            self.assertEqual(keyed.status_code, 403, keyed.text)
            # And an empty token is refused before the room is even looked up.
            self.assertEqual(
                http.get(f"/api/support/room/{room}/handoff").status_code, 401
            )

    def test_an_observer_token_is_refused_on_another_rooms_support_surface(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            first = open_caller_session(http)
            second = open_caller_session(http)
            observer = mint_observer(http, first["room"]).raise_for_status().json()

            own = http.get(
                f"/api/support/room/{first['room']}/handoff",
                params={"token": observer["token"]},
            )
            self.assertEqual(own.status_code, 200, own.text)

            replayed = http.get(
                f"/api/support/room/{second['room']}/handoff",
                params={"token": observer["token"]},
            )
            self.assertEqual(replayed.status_code, 403, replayed.text)


class TestObserverSocketScope(unittest.IsolatedAsyncioTestCase):
    """The same boundary on the two WebSockets."""

    async def test_each_socket_refuses_the_other_sides_token(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
        room = session["room"]

        # A caller token on the console socket.
        async with websockets.connect(
            f"{ws_url()}/ws/support?room={room}&token={session['token']}", open_timeout=20
        ) as socket:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
            self.assertEqual(message["type"], "error", message)

        # An observer token on the caller's control socket.
        async with websockets.connect(
            f"{ws_url()}/ws?room={room}&token={observer['token']}", open_timeout=20
        ) as socket:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
            self.assertEqual(message["type"], "error", message)

        # And the right token on the right socket gets a snapshot.
        async with websockets.connect(
            f"{ws_url()}/ws/support?room={room}&token={observer['token']}", open_timeout=20
        ) as socket:
            hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=20))
            self.assertEqual(hello["type"], "hello", hello)
            self.assertTrue(hello["snapshot"]["observer_view"])
            self.assertIn("handoff", hello)

    async def test_the_console_feed_still_opens_after_a_human_has_joined(self) -> None:
        """A console that died on the join would die exactly when it is needed.

        `hello` carries the §5.2 panel, the panel carries the participants, and
        the socket sends it with `json.dumps` — so this is the one path where a
        payload FastAPI's encoder would have accepted takes the room's live feed
        down. The empty-participants case above cannot see it.
        """
        with httpx.Client(base_url=base_url(), timeout=30.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            room, otoken = session["room"], observer["token"]
            http.post(
                f"/api/support/room/{room}/disclose", json={"token": otoken}
            ).raise_for_status()
            http.post(
                f"/api/support/room/{room}/join",
                json={"token": otoken, "display_name": "Dana"},
            ).raise_for_status()

        async with websockets.connect(
            f"{ws_url()}/ws/support?room={room}&token={otoken}", open_timeout=20
        ) as socket:
            hello = await recv_until(socket, {"hello"}, timeout=20)

        self.assertEqual(
            [p["identity"] for p in hello["handoff"]["participants"]],
            [observer["identity"]],
        )
        self.assertEqual(
            [p["identity"] for p in hello["snapshot"]["participants"]],
            [observer["identity"]],
        )
        self.assertEqual(hello["handoff"]["agent_mode"], AGENT_MODE_TRANSCRIBING)

    async def test_an_observer_may_not_speak_as_the_caller(self) -> None:
        """§7.2's M10 is computed over a transcript whose caller lines are the
        caller's, so `user.text` is refused on the console socket by name."""
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()

        url = f"{ws_url()}/ws/support?room={session['room']}&token={observer['token']}"
        async with websockets.connect(url, open_timeout=20) as socket:
            await recv_until(socket, {"hello"}, timeout=20)
            await socket.send(json.dumps({"type": "user.text", "text": "it is broken"}))
            refusal = await recv_until(socket, {"error"}, timeout=20)
            self.assertIn("may not speak as the caller", refusal["detail"])

            # The note *is* accepted — it goes to the trace and the console,
            # not into the transcript and not into `DiagnosticState`.
            await socket.send(json.dumps({"type": "support.note", "text": "card looks old"}))
            note = await recv_until(socket, {"support.note"}, timeout=20)
            self.assertEqual(note["text"], "card looks old")

        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            snapshot = (
                http.get(
                    f"/api/support/room/{session['room']}/handoff",
                    params={"token": observer["token"]},
                )
                .raise_for_status()
                .json()["snapshot"]
            )
        self.assertEqual(
            [line for line in snapshot["transcript"] if line["role"] == "caller"],
            [],
            "an observer's note reached the transcript as a caller line",
        )


# --------------------------------------------------------------------------
# 3. Consent (§6.3)
# --------------------------------------------------------------------------


class TestConsentState(unittest.TestCase):
    """§6.3: the unsafe default is impossible, and the two decisions are two."""

    def test_nothing_may_be_stored_before_a_decision_exists(self) -> None:
        state = consent_module.ConsentState()
        self.assertFalse(state.may_store())
        self.assertFalse(state.may_record_audio())
        self.assertFalse(state.decided)
        # Undecided is not a third kind of yes, and no operator default turns
        # it into one.
        self.assertEqual(state.storage, consent_module.UNDECIDED)
        self.assertFalse(state.may_retain(consent_module.RETENTION_EVALUATION))
        # The operational class is not gated: §6.3 keeps the diagnostic state
        # record because the handoff needs it, declined or not.
        self.assertTrue(state.may_retain(consent_module.RETENTION_OPERATIONAL))

    def test_display_is_rendered_until_it_is_declined(self) -> None:
        """"The live transcript is rendered in the browser whether or not it is
        retained" — so display is refused only on an explicit decline."""
        state = consent_module.ConsentState()
        self.assertTrue(state.may_display())
        state.disclose(text="notice", spoken=True, shown=True)
        state.decide(consent_module.DISPLAY, consent_module.DECLINED)
        self.assertFalse(state.may_display())
        self.assertFalse(state.may_store())

    def test_display_and_storage_are_separate_decisions(self) -> None:
        state = consent_module.ConsentState()
        state.disclose(text="notice", spoken=True, shown=True)

        state.decide(consent_module.DISPLAY, consent_module.GRANTED, modality="click")
        self.assertTrue(state.may_display())
        self.assertEqual(state.storage, consent_module.UNDECIDED)
        self.assertFalse(state.may_store(), "granting display granted storage")
        self.assertFalse(state.decided)

        state.decide(consent_module.STORAGE, consent_module.GRANTED, modality="voice")
        self.assertTrue(state.may_store())
        self.assertTrue(state.decided)
        self.assertEqual(state.storage_modality, "voice")
        self.assertEqual(state.display_modality, "click")

        # And the reverse: declining storage leaves display alone.
        other = consent_module.ConsentState()
        other.disclose(text="notice", shown=True)
        other.decide(consent_module.STORAGE, consent_module.DECLINED)
        self.assertFalse(other.may_store())
        self.assertTrue(other.may_display())

    def test_a_decision_requires_a_disclosure_first(self) -> None:
        state = consent_module.ConsentState()
        with self.assertRaises(consent_module.ConsentError):
            state.decide(consent_module.STORAGE, consent_module.GRANTED)
        with self.assertRaises(consent_module.ConsentError):
            state.disclose(text="notice")  # neither spoken nor shown
        with self.assertRaises(consent_module.ConsentError):
            state.disclose(text="   ", shown=True)
        state.disclose(text=consent_module.DEFAULT_DISCLOSURE, spoken=True, shown=True)
        state.decide(consent_module.STORAGE, consent_module.GRANTED)
        self.assertTrue(state.may_store())

    def test_a_decision_must_be_granted_or_declined(self) -> None:
        state = consent_module.ConsentState()
        state.disclose(text="notice", shown=True)
        with self.assertRaises(consent_module.ConsentError):
            state.decide(consent_module.STORAGE, consent_module.UNDECIDED)
        with self.assertRaises(consent_module.ConsentError):
            state.decide("recording", consent_module.GRANTED)

    def test_the_handoff_line_says_what_is_actually_true(self) -> None:
        state = consent_module.ConsentState()
        self.assertEqual(state.as_handoff_line(), "recorded: n · consent: not-obtained")
        state.disclose(text="notice", shown=True)
        state.decide(consent_module.STORAGE, consent_module.DECLINED)
        self.assertEqual(state.as_handoff_line(), "recorded: n · consent: declined")
        state.decide(consent_module.STORAGE, consent_module.GRANTED)
        self.assertEqual(state.as_handoff_line(), "recorded: y · consent: obtained")


class TestConsentGatesTheCorpus(unittest.TestCase):
    """§6.3's gate, and the order it runs in."""

    def make_session(self):
        registry = SessionRegistry(trace_dir=None)
        session = registry.create()
        return session

    def test_an_unconsented_session_never_reaches_the_database(self) -> None:
        """`ConsentRequired`, not `StoreUnavailable`, against a dead DSN.

        If the gate ran after the connection, this DSN would time out first and
        the error would be the other one. "We did not write it" is a weaker
        claim than "we never tried", and this is the test that tells them apart.
        """
        session = self.make_session()
        with self.assertRaises(transcript_store.ConsentRequired):
            transcript_store.collect(session, dsn=UNREACHABLE_DSN)
        self.assertFalse(
            issubclass(transcript_store.ConsentRequired, transcript_store.StoreUnavailable),
            "collapsing the two would make a caller retry a refusal",
        )

    def test_display_consent_alone_does_not_open_the_corpus(self) -> None:
        session = self.make_session()
        session.consent.disclose(text=consent_module.DEFAULT_DISCLOSURE, shown=True)
        session.consent.decide(consent_module.DISPLAY, consent_module.GRANTED)
        with self.assertRaises(transcript_store.ConsentRequired):
            transcript_store.collect(session, dsn=UNREACHABLE_DSN)

    def test_a_declined_storage_decision_is_still_a_refusal(self) -> None:
        session = self.make_session()
        session.consent.disclose(text=consent_module.DEFAULT_DISCLOSURE, shown=True)
        session.consent.decide(consent_module.STORAGE, consent_module.DECLINED)
        with self.assertRaises(transcript_store.ConsentRequired):
            transcript_store.collect(session, dsn=UNREACHABLE_DSN)

    def test_redaction_removes_identifiers_and_keeps_the_corpus_content(self) -> None:
        """§6.3 data minimisation, and the limit on it.

        The corpus exists to hold real user language about cameras, so the
        serial rule has to leave `R2-4K`, `U3` and `V30` alone while taking the
        things that identify a person.
        """
        redacted = transcript_store.redact(
            {
                "lines": [
                    {"text": "email me at sam.doe@example.com or call +1 415 555 0123"},
                    {"text": "it's a Rove R2-4K with a SanDisk U3 V30 card"},
                    {"text": "the serial is A1B2C3D4E5F6G7"},
                ]
            }
        )
        joined = " ".join(line["text"] for line in redacted["lines"])
        self.assertNotIn("sam.doe@example.com", joined)
        self.assertNotIn("415 555 0123", joined)
        self.assertNotIn("A1B2C3D4E5F6G7", joined)
        self.assertIn("[EMAIL]", joined)
        self.assertIn("[PHONE]", joined)
        self.assertIn("[SERIAL]", joined)
        self.assertIn("R2-4K", joined)
        self.assertIn("U3", joined)
        self.assertIn("V30", joined)


class TestConsentOverTheWire(unittest.IsolatedAsyncioTestCase):
    """The same gate through the caller's socket and the console's endpoint."""

    async def test_collection_is_refused_until_storage_is_granted(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=30.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            room = session["room"]

            # §6.3's notice travels with the credential, so there is no version
            # of the page that has a session and does not have the words.
            self.assertIn("consent", session)
            self.assertTrue(session["consent"]["disclosure"].strip())
            self.assertFalse(session["consent"]["state"]["may_store"])

            refused = http.post(
                f"/api/support/room/{room}/collect", json={"token": observer["token"]}
            )
            self.assertEqual(refused.status_code, 409, refused.text)
            self.assertIn("consent", refused.text.lower())

        url = f"{ws_url()}/ws?room={room}&token={session['token']}"
        async with websockets.connect(url, open_timeout=20) as socket:
            await recv_until(socket, {"hello"}, timeout=20)

            # A decision before the disclosure is refused, on the wire too.
            await socket.send(
                json.dumps(
                    {"type": "consent.decision", "kind": "storage", "decision": "granted"}
                )
            )
            error = await recv_until(socket, {"error"}, timeout=20)
            self.assertIn("disclosure", error["detail"])

            await socket.send(
                json.dumps({"type": "consent.disclosed", "spoken": True, "shown": True})
            )
            state = (await recv_until(socket, {"consent"}, timeout=20))["consent"]
            self.assertTrue(state["disclosed"])
            self.assertTrue(state["disclosed_spoken"])
            self.assertTrue(state["disclosed_shown"])
            self.assertFalse(state["may_store"])

            # Display first — and storage must not move with it.
            await socket.send(
                json.dumps(
                    {
                        "type": "consent.decision",
                        "kind": "display",
                        "decision": "granted",
                        "modality": "click",
                    }
                )
            )
            state = (await recv_until(socket, {"consent"}, timeout=20))["consent"]
            self.assertTrue(state["may_display"])
            self.assertFalse(state["may_store"], "display consent granted storage")
            self.assertEqual(state["storage"], consent_module.UNDECIDED)

            # Say something, so there is a transcript to collect.
            await socket.send(
                json.dumps(
                    {
                        "type": "user.text",
                        "text": "my rove r2-4k keeps saying memory card error",
                        "modality": "typed",
                    }
                )
            )
            await recv_until(socket, {"turn.reply"})

            await socket.send(
                json.dumps(
                    {
                        "type": "consent.decision",
                        "kind": "storage",
                        "decision": "granted",
                        "modality": "click",
                    }
                )
            )
            state = (await recv_until(socket, {"consent"}, timeout=20))["consent"]
            self.assertTrue(state["may_store"])

        with httpx.Client(base_url=base_url(), timeout=60.0) as http:
            collected = http.post(
                f"/api/support/room/{room}/collect", json={"token": observer["token"]}
            )
            # Whatever happens now, it is not the consent refusal: the gate is
            # open. A 503 here means Postgres is absent, which is a fact about
            # this machine and not about the gate.
            self.assertNotEqual(collected.status_code, 409, collected.text)
            if collected.status_code == 503:
                self.skipTest(f"no Postgres for the pilot corpus: {collected.text}")
            self.assertEqual(collected.status_code, 200, collected.text)

            receipt = collected.json()["receipt"]
            _collected.append(receipt["session_id"])
            self.assertEqual(receipt["session_id"], session["session_id"])
            self.assertGreaterEqual(receipt["lines"], 2)
            self.assertTrue(receipt["redacted"])
            self.assertEqual(receipt["retention_class"], consent_module.RETENTION_EVALUATION)

            stored = transcript_store.fetch(receipt["session_id"])
            self.assertIsNotNone(stored, "the receipt claimed a write that is not there")
            self.assertEqual(stored["consent_storage"], consent_module.GRANTED)
            self.assertEqual(stored["room"], room)
            self.assertEqual(len(stored["lines"]), receipt["lines"])
            self.assertTrue(
                any("memory card error" in line["text"].lower() for line in stored["lines"])
            )

    async def test_declining_display_withholds_the_transcript_from_both_pages(self) -> None:
        """§6.3 keeps display and storage apart; this is the display one."""
        with httpx.Client(base_url=base_url(), timeout=30.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            room = session["room"]

        url = f"{ws_url()}/ws?room={room}&token={session['token']}"
        async with websockets.connect(url, open_timeout=20) as socket:
            await recv_until(socket, {"hello"}, timeout=20)
            await socket.send(json.dumps({"type": "consent.disclosed", "shown": True}))
            await recv_until(socket, {"consent"}, timeout=20)
            await socket.send(
                json.dumps(
                    {"type": "user.text", "text": "the screen is blank", "modality": "typed"}
                )
            )
            await recv_until(socket, {"turn.reply"})
            await socket.send(
                json.dumps(
                    {"type": "consent.decision", "kind": "display", "decision": "declined"}
                )
            )
            state = (await recv_until(socket, {"consent"}, timeout=20))["consent"]
            self.assertFalse(state["may_display"])

        with httpx.Client(base_url=base_url(), timeout=30.0) as http:
            snapshot = (
                http.get(
                    f"/api/support/room/{room}/handoff", params={"token": observer["token"]}
                )
                .raise_for_status()
                .json()["snapshot"]
            )
        self.assertFalse(snapshot["transcript_displayed"])
        self.assertEqual(snapshot["transcript"], [])


# --------------------------------------------------------------------------
# 4. The join flips the agent (§5.3)
# --------------------------------------------------------------------------


class TestAgentModeUnit(unittest.TestCase):
    """The flip itself, in `core_bridge`, where it lives."""

    def test_the_mode_starts_proposing_and_is_mirrored_into_the_state(self) -> None:
        session = SessionRegistry(trace_dir=None).create()
        self.assertEqual(session.agent_mode, AGENT_MODE_PROPOSING)

        previous = session.set_agent_mode(AGENT_MODE_TRANSCRIBING, reason="test")
        self.assertEqual(previous, AGENT_MODE_PROPOSING)
        self.assertEqual(session.agent_mode, AGENT_MODE_TRANSCRIBING)
        # Mirrored into `DiagnosticState.notes`, which the core never branches
        # on, so the mode travels with the state without `agent/` growing a
        # field about who is in the room.
        self.assertEqual(session.state.notes["agent_mode"], AGENT_MODE_TRANSCRIBING)

        with self.assertRaises(ValueError):
            session.set_agent_mode("listening", reason="not a mode")


class TestJoinFlipsTheAgent(unittest.IsolatedAsyncioTestCase):
    """§5.3: the agent announces the join, stops proposing steps, and drops to
    transcribing and recording the ledger."""

    async def test_the_join_stops_the_agent_proposing_and_keeps_transcribing(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=60.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            room, otoken = session["room"], observer["token"]

            url = f"{ws_url()}/ws?room={room}&token={session['token']}"
            async with websockets.connect(url, open_timeout=20) as socket:
                await recv_until(socket, {"hello"}, timeout=20)

                # -- before the join: the agent proposes ---------------------
                await socket.send(
                    json.dumps(
                        {
                            "type": "user.text",
                            "text": "my rove r2-4k will not connect to wi-fi",
                            "modality": "typed",
                        }
                    )
                )
                before = (await recv_until(socket, {"turn.reply"}))["reply"]
                self.assertFalse(before["suppressed"])
                self.assertEqual(before["agent_mode"], AGENT_MODE_PROPOSING)
                self.assertTrue(
                    before["step"] or before["escalate"],
                    "the agent proposed nothing before any human was in the room",
                )
                self.assertTrue(before["text"].strip())
                ledger_before = len(before["state"]["ledger"])
                turn_before = before["state"]["turn"]

                # -- §6.3: no join before the disclosure ---------------------
                premature = http.post(
                    f"/api/support/room/{room}/join",
                    json={"token": otoken, "display_name": "Dana"},
                )
                self.assertEqual(premature.status_code, 409, premature.text)
                self.assertIn("disclose", premature.text)

                disclosed = http.post(
                    f"/api/support/room/{room}/disclose", json={"token": otoken}
                )
                self.assertEqual(disclosed.status_code, 200, disclosed.text)
                self.assertTrue(disclosed.json()["consent"]["escalation_disclosed"])

                # -- the join ------------------------------------------------
                joined = http.post(
                    f"/api/support/room/{room}/join",
                    json={"token": otoken, "display_name": "Dana"},
                )
                self.assertEqual(joined.status_code, 200, joined.text)
                body = joined.json()
                self.assertFalse(body["already_joined"])
                self.assertEqual(body["agent_mode"], AGENT_MODE_TRANSCRIBING)
                self.assertEqual(
                    [p["identity"] for p in body["participants"] if p["present"]],
                    [observer["identity"]],
                )
                # D-17: the §5.2 panel arrives with the human, not after.
                self.assertIn("handoff", body)
                self.assertEqual(body["handoff"]["agent_mode"], AGENT_MODE_TRANSCRIBING)

                # Idempotent: a second join is not a second participant.
                again = http.post(
                    f"/api/support/room/{room}/join", json={"token": otoken}
                ).json()
                self.assertTrue(again["already_joined"])
                self.assertEqual(len(again["participants"]), 1)

                # -- after the join: transcribed, not diagnosed ---------------
                await socket.send(
                    json.dumps(
                        {
                            "type": "user.text",
                            "text": "it is still not connecting",
                            "modality": "typed",
                        }
                    )
                )
                after = (await recv_until(socket, {"turn.reply"}))["reply"]
                self.assertTrue(after["suppressed"], "the agent proposed a step anyway")
                self.assertEqual(after["agent_mode"], AGENT_MODE_TRANSCRIBING)
                self.assertIsNone(after["step"])
                self.assertEqual(after["text"], "")
                # The ledger did not grow a step nobody spoke: §3.5's no-repeat
                # accounting and §7.2's M4 are both computed from it.
                self.assertEqual(len(after["state"]["ledger"]), ledger_before)

            # The caller's words are still kept — §5.3 drops the agent to
            # "transcribing and recording the ledger", not to deafness.
            snapshot = (
                http.get(
                    f"/api/support/room/{room}/handoff", params={"token": otoken}
                )
                .raise_for_status()
                .json()
            )
            caller_lines = [
                line["text"] for line in snapshot["snapshot"]["transcript"]
                if line["role"] == "caller"
            ]
            self.assertIn("it is still not connecting", caller_lines)
            self.assertGreater(snapshot["snapshot"]["state"]["turn"], turn_before)
            self.assertEqual(snapshot["handoff"]["agent_mode"], AGENT_MODE_TRANSCRIBING)

            # The announcement happened, and it announced an arrival that had.
            agent_lines = " ".join(
                line["text"] for line in snapshot["snapshot"]["transcript"]
                if line["role"] == "agent"
            )
            self.assertIn("Dana", agent_lines)

            # -- the trace agrees ------------------------------------------
            events = http.get(
                f"/api/support/room/{room}/trace", params={"token": otoken}
            ).raise_for_status().json()["events"]
            types = {event["type"] for event in events}
            for expected in (
                "observer.minted",
                "escalation.disclosed",
                "support.joined",
                "agent.mode",
                "turn.not_proposed",
            ):
                self.assertIn(expected, types)

            # -- leaving does not resume the agent by itself ----------------
            left = http.post(
                f"/api/support/room/{room}/leave", json={"token": otoken}
            ).raise_for_status().json()
            self.assertEqual(left["agent_mode"], AGENT_MODE_TRANSCRIBING)

            resumed = http.post(
                f"/api/support/room/{room}/leave",
                json={"token": otoken, "resume_agent": True},
            ).raise_for_status().json()
            self.assertEqual(resumed["agent_mode"], AGENT_MODE_PROPOSING)


# --------------------------------------------------------------------------
# 5. The handoff payload (§5.2)
# --------------------------------------------------------------------------


class TestHandoffPayload(unittest.TestCase):
    """§5.2's layout, and the two things it forbids."""

    def test_the_panel_carries_the_sections_5_2_asks_for(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            session = open_caller_session(http)
            observer = mint_observer(http, session["room"]).raise_for_status().json()
            payload = (
                http.get(
                    f"/api/support/room/{session['room']}/handoff",
                    params={"token": observer["token"]},
                )
                .raise_for_status()
                .json()["handoff"]
            )

        for field in (
            "session_id",
            "started_at",
            "duration_s",
            "agent_version",
            "corpus_snapshot_date",
            "user_said",
            "symptom_summary",
            "category",
            "taxonomy_id",
            "device",
            "context",
            "already_tried",
            "hypothesis",
            "authority",
            "escalation",
            "agent_mode",
        ):
            self.assertIn(field, payload)

        # "firmware — never agent-stated": the source travels with the value.
        self.assertIn("source", payload["device"]["firmware"])
        self.assertEqual(payload["device"]["firmware"]["source"], "not obtained")

        # §5.2's "recording + consent status" row, and the pointer that only
        # points when there is something to point at.
        self.assertIn("recording_and_consent", payload["escalation"])
        self.assertIn("not retained", payload["escalation"]["transcript_pointer"])

    def test_the_payload_withholds_a_fault_declaration_and_a_policy_statement(self) -> None:
        """`01` §4 — the agent may suspect, a human decides. `03` EVAL-29 — no
        warranty or returns statement, ever."""
        from server.handoff import build_handoff

        session = SessionRegistry(trace_dir=None).create()
        state = session.state
        state.escalation.reason = (
            "the card is faulty and it is covered under warranty, so it needs replacing"
        )
        payload = build_handoff(session)

        rendered = payload["escalation"]["reason"]
        self.assertNotIn("is faulty", rendered)
        self.assertNotIn("warranty", rendered.lower())
        self.assertNotIn("needs replacing", rendered)
        self.assertIn("[withheld", rendered)
        # Listed rather than silently dropped: a human reading the panel can
        # see that something was taken out, and why.
        self.assertTrue(payload["withheld"])
        reasons = " ".join(entry["reason"] for entry in payload["withheld"])
        self.assertIn("a human decides", reasons)
        self.assertIn("EVAL-29", reasons)

    def test_suspicion_is_not_withheld(self) -> None:
        """The rules catch the declarative form, not the suspicion `01` §4
        explicitly permits — a gate that ate "card at end of life" would make
        the panel useless."""
        from server.handoff import build_handoff

        session = SessionRegistry(trace_dir=None).create()
        session.state.escalation.reason = (
            "card at end of life — consistent with a failing card, slot not ruled out"
        )
        payload = build_handoff(session)
        self.assertEqual(payload["withheld"], [])
        self.assertIn("card at end of life", payload["escalation"]["reason"])

    def test_the_payload_survives_plain_json_once_a_human_is_in_the_room(self) -> None:
        """`json.dumps`, not FastAPI's encoder — the panel has two other readers.

        The console socket sends this with Starlette's `send_json`, which is
        `json.dumps` and stops dead on a dataclass; `transcripts.collect` files
        it with `json.dumps(default=str)`, which does not stop and instead
        writes a Python `repr` into a `jsonb` column. FastAPI's encoder copes
        with both, so the HTTP surfaces would have hidden it — which is why
        this asserts against the stricter of the three readers, and does so
        with a participant present, since an empty list serialises fine either
        way and that is exactly the state every other test here leaves it in.
        """
        from server.core_bridge import Participant
        from server.handoff import build_handoff

        session = SessionRegistry(trace_dir=None).create()
        session.participants.append(
            Participant(identity="observer-abc", display_name="Dana")
        )
        payload = build_handoff(session)

        round_tripped = json.loads(json.dumps(payload))
        self.assertEqual(
            round_tripped["participants"],
            [
                {
                    "identity": "observer-abc",
                    "display_name": "Dana",
                    "role": "support",
                    "joined_at": session.participants[0].joined_at,
                    "left_at": None,
                    "present": True,
                }
            ],
        )


# --------------------------------------------------------------------------
# 6. The console builds and serves
# --------------------------------------------------------------------------


class TestConsoleBuildsAndServes(unittest.TestCase):
    """`docs/07` D-17: "that console does not exist" (§9.3 item 14). It does now."""

    def test_the_modules_parse_the_ids_bind_and_the_panels_escape(self) -> None:
        """`support/selftest.mjs`, which the other tests here cannot replace.

        They assert that `/support/assets/main.js` is *served* — which a file
        with a syntax error does perfectly well — and they cannot see that a
        renamed id has turned the §6.3 disclosure button into a no-op, or that
        a panel rendered a stranger's typed words as markup.
        """
        self.assertNotIn("failed", _console_selftest, _console_selftest)
        self.assertNotIn("unavailable", _console_selftest, _console_selftest)
        self.assertNotIn("skipped", _console_selftest, _console_selftest)
        self.assertIn("panels escaped", _console_selftest, _console_selftest)
        self.assertIn("all declared in index.html", _console_selftest, _console_selftest)

    def test_the_build_produced_the_tree_the_server_serves(self) -> None:
        self.assertNotIn("failed", _console_built, _console_built)
        self.assertNotIn("unavailable", _console_built, _console_built)
        dist = _REPO_ROOT / "support" / "dist"
        self.assertTrue(dist.is_dir(), f"{dist} was not built")
        for name in ("index.html", "assets/main.js", "assets/console.css",
                     "assets/panels.js", "assets/api.js", "assets/socket.js"):
            self.assertTrue((dist / name).is_file(), f"missing {name}")

    def test_the_console_is_served_from_the_same_process(self) -> None:
        with httpx.Client(base_url=base_url(), timeout=15.0) as http:
            self.assertTrue(http.get("/healthz").raise_for_status().json()["console"])

            page = http.get("/support")
            self.assertEqual(page.status_code, 200, page.text)
            self.assertIn("text/html", page.headers["content-type"])
            self.assertIn("support console", page.text)
            # The placeholders were substituted, not shipped.
            self.assertNotIn("__BASE__", page.text)
            self.assertNotIn("__BUILD__", page.text)
            self.assertIn("/support/assets/main.js", page.text)
            # An internal tool, and the correct number of search engines that
            # have seen a stranger's session is zero.
            self.assertIn("noindex", page.text)

            for asset, needle in (
                ("main.js", "SupportSocket"),
                ("panels.js", "export function handoffPanel"),
                ("api.js", "export async function mintObserver"),
                ("socket.js", "export class SupportSocket"),
                ("console.css", ".panel"),
            ):
                response = http.get(f"/support/assets/{asset}")
                self.assertEqual(response.status_code, 200, asset)
                self.assertIn(needle, response.text, asset)

    def test_the_console_holds_no_credential_and_no_caller_turn_control(self) -> None:
        """§1.4.2's rule, read for the console: the page holds a short-lived
        room token and nothing else — no AWS credential, no standing key."""
        # Comments are stripped first — line and block both. These modules
        # *discuss* `user.text` and `localStorage` at length, because why each
        # one is absent is the point. What must not be there is the code.
        import re

        code = "\n".join(
            re.sub(
                r"^\s*//.*$",
                "",
                re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S),
                flags=re.M,
            )
            for path in sorted((_REPO_ROOT / "support" / "src").glob("*.js"))
        )
        self.assertNotIn("localStorage", code)
        self.assertNotIn("sessionStorage", code)
        self.assertNotIn("AWS_", code)
        self.assertNotIn("user.text", code)


if __name__ == "__main__":
    unittest.main()
