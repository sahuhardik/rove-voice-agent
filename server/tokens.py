"""The session token mint (`docs/06` §1.4.2, `docs/07` D-14).

§1.4.2 states the rule the browser side of this system lives under:

> The browser never holds a long-lived credential, and it never holds an AWS
> credential at all. The React app authenticates to our backend; the backend
> mints a **short-lived, single-room, single-identity token** (minutes, not
> hours) and returns it; the browser uses it to join exactly one room.

Three properties, and each one is enforced by construction rather than by
convention, because a scope that is only enforced at the call site is a scope
that one forgotten call site removes:

1. **Short-lived.** `mint` takes a TTL in seconds, defaults to five minutes and
   refuses anything over :data:`MAX_TTL_SECONDS`. The expiry is on the payload
   and the payload is signed, so it cannot be widened after the fact. A token
   authorises *the join*, not the session: a ten-minute call outlives its own
   token, and a re-join after a network drop mints a new one (§1.4.2,
   "reconnection is expected, not exceptional").
2. **Single-room.** The room is a signed claim, and :func:`verify` **requires
   the caller to name the room it is verifying for**. There is no way to ask
   "is this token valid?" in the abstract, which is what keeps a token minted
   for one room from being replayed into another.
3. **Single-identity.** Same shape: one `identity` claim, and the room the
   token names is the only room that identity may join with it.

The token is an HMAC-SHA256 payload, not a JWT: there is no algorithm field to
confuse, no `none` algorithm to strip, and no library to keep current. The
secret stays on the server; what crosses to the browser is a signature over
public claims. Nothing in the payload is an AWS credential, and
`server/test_server.py` asserts that the payload carries exactly the seven
claims below and nothing else.

**The fourth property, added in Milestone 7.1: single-scope.** §5.3 admits a
*second participant* to the room the caller is already in, and that participant
is not the caller. Two scopes exist and they are disjoint:

* :data:`SCOPE_JOIN_ROOM` — the caller. Signalling, media, the control socket,
  the trace. This is what `POST /api/session` mints and the only thing the
  browser ever holds.
* :data:`SCOPE_OBSERVE_ROOM` — the support human (`docs/06` §5.3, `docs/07`
  D-17). Read the session and operate the join control; **never** offer SDP,
  never send a caller turn.

`scope` was always a signed claim and was always checked; what changes is that
it is now a *parameter* of :func:`verify` rather than a constant, and it
**defaults to the caller scope**. That default is the safety property: every
call site that existed before this milestone keeps asking exactly the question
it was asking — "is this the caller?" — so an observer token cannot reach one
by being forgotten about. The observer path has to name its scope out loud.

Identity carries the same split and is checked alongside it:
:func:`new_identity` issues ``caller-…`` and :func:`new_observer_identity`
issues ``observer-…``, and the two are never the same string. So a token lifted
from one side fails the scope check *and* the identity check at the other.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

#: Payload format version. Bumped if a claim's meaning ever changes, so an
#: old token fails closed rather than being read under new rules.
TOKEN_VERSION = 1

#: The caller's scope. A token is permission to join one room *as the caller*,
#: not an API credential — nothing else in the system accepts one.
SCOPE_JOIN_ROOM = "join:room"

#: The support human's scope (`docs/06` §5.3, `docs/07` D-17). Strictly less
#: than :data:`SCOPE_JOIN_ROOM` and not a subset of it: it reaches the support
#: surfaces and nothing the caller's token reaches. A token of this scope
#: cannot offer SDP, cannot open the caller's control socket and cannot send a
#: caller turn — all three refuse it on the scope claim before they look at
#: anything else.
SCOPE_OBSERVE_ROOM = "observe:room"

#: Every scope this mint will issue. Anything else is a typo, and a typo that
#: reached `mint` would be signed.
SCOPES = frozenset({SCOPE_JOIN_ROOM, SCOPE_OBSERVE_ROOM})

#: Identity prefixes, one per scope. Pinned here rather than at the call sites
#: so that "an observer token cannot act as the caller" is one comparison in
#: one file: a mint that pairs the wrong prefix with the wrong scope raises.
IDENTITY_PREFIX = {
    SCOPE_JOIN_ROOM: "caller-",
    SCOPE_OBSERVE_ROOM: "observer-",
}

#: "Minutes, not hours" (§1.4.2), read as: five minutes by default.
DEFAULT_TTL_SECONDS = 300

#: And never more than fifteen, whatever the caller asks for. The ceiling is
#: here rather than in the config so that a mis-set environment variable cannot
#: quietly turn a join token into a session-length credential.
MAX_TTL_SECONDS = 900

#: Claims on the wire. `server/test_server.py` pins this set exactly.
CLAIM_KEYS = frozenset({"v", "scope", "room", "identity", "iat", "exp", "jti"})


class TokenError(ValueError):
    """Base class: the token is not usable for what was asked of it."""


class TokenMalformed(TokenError):
    """Not a token at all — wrong shape, bad base64, or unreadable payload."""


class TokenSignatureError(TokenError):
    """The signature does not match the payload under this secret."""


class TokenExpired(TokenError):
    """Minted correctly, presented too late."""


class TokenScopeError(TokenError):
    """Minted for a different room, identity or purpose."""


@dataclass(frozen=True)
class Claims:
    """What a verified token says. All seven fields are signed."""

    room: str
    identity: str
    issued_at: int
    expires_at: int
    jti: str
    version: int = TOKEN_VERSION
    scope: str = SCOPE_JOIN_ROOM

    @property
    def ttl_seconds(self) -> int:
        return self.expires_at - self.issued_at

    def seconds_remaining(self, now: float | None = None) -> int:
        return int(self.expires_at - (time.time() if now is None else now))

    def as_payload(self) -> dict[str, Any]:
        return {
            "v": self.version,
            "scope": self.scope,
            "room": self.room,
            "identity": self.identity,
            "iat": self.issued_at,
            "exp": self.expires_at,
            "jti": self.jti,
        }


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:  # noqa: BLE001 — any decode failure is malformed
        raise TokenMalformed(f"undecodable token segment: {exc}") from exc


def _sign(payload: bytes, secret: str) -> str:
    return _b64e(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest())


def _check_room(room: str) -> str:
    """One room, named plainly.

    A room id with a comma, a wildcard or whitespace in it is the shape a
    multi-room token would take, so it is refused at the mint rather than
    being left for a comparison somewhere else to get right.
    """
    room = str(room)
    if not room or room.strip() != room:
        raise ValueError("room must be a non-empty id with no surrounding space")
    if any(ch in room for ch in ",* \t\n"):
        raise ValueError(f"room must name exactly one room, got {room!r}")
    return room


def _check_identity(identity: str) -> str:
    identity = str(identity)
    if not identity or identity.strip() != identity:
        raise ValueError("identity must be a non-empty id with no surrounding space")
    if any(ch in identity for ch in ",* \t\n"):
        raise ValueError(f"identity must name exactly one identity, got {identity!r}")
    return identity


def _check_scope(scope: str, identity: str) -> str:
    """One known scope, and an identity whose prefix belongs to it.

    The pairing is checked at the mint because a token is immutable once
    signed: an `observe:room` token carrying a `caller-…` identity would read
    as the caller at any call site that checked only one of the two claims.
    """
    scope = str(scope)
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; known: {sorted(SCOPES)}")
    prefix = IDENTITY_PREFIX[scope]
    if not identity.startswith(prefix):
        raise ValueError(
            f"scope {scope!r} requires an identity starting {prefix!r}, "
            f"got {identity!r}"
        )
    for other_scope, other_prefix in IDENTITY_PREFIX.items():
        if other_scope != scope and identity.startswith(other_prefix):
            raise ValueError(
                f"identity {identity!r} belongs to scope {other_scope!r}, "
                f"not {scope!r}"
            )
    return scope


def mint(
    *,
    room: str,
    identity: str,
    secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    scope: str = SCOPE_JOIN_ROOM,
    now: float | None = None,
) -> str:
    """Mint a token for exactly one room, one identity and one scope.

    Args:
        room: The one room this token admits its holder to.
        identity: The one participant identity it admits them as. Its prefix
            must match `scope` (see :data:`IDENTITY_PREFIX`).
        secret: The server-side signing secret. Never leaves this process.
        ttl_seconds: Lifetime, capped at :data:`MAX_TTL_SECONDS`.
        scope: :data:`SCOPE_JOIN_ROOM` (the caller) or
            :data:`SCOPE_OBSERVE_ROOM` (the support human, §5.3).
        now: Issue time, for tests. Defaults to the wall clock.

    Raises:
        ValueError: On an empty secret, a non-single room or identity, an
            unknown scope, an identity whose prefix belongs to another scope,
            or a TTL outside ``0 < ttl <= MAX_TTL_SECONDS``.
    """
    if not secret:
        raise ValueError("refusing to mint with an empty signing secret")
    room = _check_room(room)
    identity = _check_identity(identity)
    scope = _check_scope(scope, identity)
    ttl = int(ttl_seconds)
    if ttl <= 0:
        raise ValueError(f"ttl_seconds must be positive, got {ttl}")
    if ttl > MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl_seconds {ttl} exceeds the {MAX_TTL_SECONDS}s ceiling — §1.4.2 "
            "says minutes, not hours"
        )
    issued = int(now if now is not None else time.time())
    claims = Claims(
        room=room,
        identity=identity,
        issued_at=issued,
        expires_at=issued + ttl,
        jti=secrets.token_urlsafe(9),
        scope=scope,
    )
    payload = json.dumps(
        claims.as_payload(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"{_b64e(payload)}.{_sign(payload, secret)}"


def verify(
    token: str,
    *,
    secret: str,
    room: str,
    identity: str | None = None,
    scope: str = SCOPE_JOIN_ROOM,
    now: float | None = None,
    leeway_seconds: int = 0,
) -> Claims:
    """Verify a token **for one named room and one named scope**.

    The `room` argument is required on purpose. Verification without a room to
    check against would answer a question nobody should be asking — a join
    token is only ever presented alongside the room it is being used on, so
    that room is always in hand at the call site.

    `scope` **defaults to the caller's scope** for the same reason. Every
    surface that existed before the support console asks "is this the caller?",
    and it should keep asking exactly that without being edited — a default of
    "any scope" would have silently widened all of them the moment a second
    scope existed.

    Args:
        token: The token as the holder presented it.
        secret: The signing secret.
        room: The room the holder is trying to act on.
        identity: Optionally, the identity they claim to be.
        scope: The scope this call site requires. Defaults to
            :data:`SCOPE_JOIN_ROOM`.
        now: Verification time, for tests.
        leeway_seconds: Clock skew allowance. Zero by default.

    Raises:
        TokenMalformed, TokenSignatureError, TokenExpired, TokenScopeError.
    """
    if not secret:
        raise ValueError("refusing to verify with an empty signing secret")
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; known: {sorted(SCOPES)}")
    if not isinstance(token, str) or token.count(".") != 1:
        raise TokenMalformed("token must be one payload and one signature")
    encoded_payload, signature = token.split(".")
    if not encoded_payload or not signature:
        raise TokenMalformed("token has an empty segment")
    payload = _b64d(encoded_payload)
    # Signature first: nothing in the payload is trusted enough to read until
    # it is known to be ours.
    if not hmac.compare_digest(_sign(payload, secret), signature):
        raise TokenSignatureError("signature does not match payload")
    try:
        data = json.loads(payload)
    except Exception as exc:  # noqa: BLE001
        raise TokenMalformed(f"payload is not JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != set(CLAIM_KEYS):
        raise TokenMalformed(f"payload claims are not {sorted(CLAIM_KEYS)}")
    if data["v"] != TOKEN_VERSION:
        raise TokenScopeError(f"token version {data['v']!r} is not {TOKEN_VERSION}")
    if data["scope"] != scope:
        raise TokenScopeError(f"token scope {data['scope']!r} is not {scope!r}")
    if data["room"] != room:
        raise TokenScopeError("token was minted for a different room")
    if identity is not None and data["identity"] != identity:
        raise TokenScopeError("token was minted for a different identity")
    # Belt and braces: the mint pairs scope with identity prefix, so a token
    # that disagrees with itself was not minted here.
    if not str(data["identity"]).startswith(IDENTITY_PREFIX[scope]):
        raise TokenScopeError(
            f"identity {data['identity']!r} does not belong to scope {scope!r}"
        )
    stamp = time.time() if now is None else now
    if float(data["exp"]) <= stamp - leeway_seconds:
        raise TokenExpired(
            f"token expired at {data['exp']}, {int(stamp - data['exp'])}s ago"
        )
    if float(data["iat"]) > stamp + leeway_seconds + 1:
        raise TokenScopeError("token is issued in the future")
    return Claims(
        room=data["room"],
        identity=data["identity"],
        issued_at=int(data["iat"]),
        expires_at=int(data["exp"]),
        jti=data["jti"],
        version=int(data["v"]),
        scope=data["scope"],
    )


def peek(token: str) -> dict[str, Any]:
    """Read a token's claims **without** verifying it — trace and logs only.

    Never use this to decide anything. It exists so that a rejected join can be
    traced with the room it was aimed at.
    """
    try:
        payload = _b64d(token.split(".")[0])
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class MintedSession:
    """What `POST /api/session` hands back to the browser.

    One envelope for both transports (`docs/07` D-02), because the browser's
    *question* is the same either way — which room, as whom, with what
    credential, and where to point it. Only `transport` and `livekit_url`
    differ, and the page branches on `transport` rather than being built for
    one of them. That is what keeps D-02's flip back to Pipecat a restart.
    """

    room: str
    identity: str
    token: str
    expires_at: int
    ttl_seconds: int
    ice_servers: list[dict[str, Any]] = field(default_factory=list)
    #: `livekit` or `smallwebrtc` — see `server/config.py`.
    transport: str = "smallwebrtc"
    #: Where the media server is, in LiveKit mode. Not a secret: the token is
    #: the credential, and sending the URL keeps the page free of build-time
    #: configuration.
    livekit_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "identity": self.identity,
            "token": self.token,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
            "ice_servers": self.ice_servers,
            "transport": self.transport,
            "livekit_url": self.livekit_url,
        }


def new_room_id() -> str:
    """One room per session (§1.4.2)."""
    return "room-" + secrets.token_urlsafe(9)


def new_identity() -> str:
    """One identity per session. The caller, not the agent."""
    return IDENTITY_PREFIX[SCOPE_JOIN_ROOM] + secrets.token_urlsafe(6)


def new_observer_identity() -> str:
    """One identity per support human admitted to a room (§5.3).

    A fresh id per admission, not a stable support-agent id: the room is the
    unit of access here, so two sessions handled by the same human carry two
    identities and neither token is usable on the other's room.
    """
    return IDENTITY_PREFIX[SCOPE_OBSERVE_ROOM] + secrets.token_urlsafe(6)
