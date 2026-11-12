"""The LiveKit access-token mint (`docs/06` §1.4.2, `docs/07` D-02).

Phase 2b minted a token of our own design (`server/tokens.py`) because the
peer connection lived in our process and nothing else had to read it. Phase 3
promotes the transport to LiveKit (D-02), and the credential has to be one the
**media server** accepts — a LiveKit access token, which is a JWT signed with
the API secret.

§1.4.2's three properties are unchanged, and they are what this module
enforces rather than assumes:

1. **Short-lived.** A TTL in minutes, capped at
   :data:`~server.tokens.MAX_TTL_SECONDS` — the same ceiling as the Phase 2b
   mint, imported rather than restated so the two cannot drift apart.
2. **Single-room.** The `video` grant names exactly one room, and
   :func:`verify` requires the caller to say which room it is verifying *for*.
   There is no way to ask "is this token valid?" in the abstract.
3. **Single-identity.** `sub` is one participant identity, and LiveKit refuses
   a second connection on the same identity in the same room.

Two grants are deliberately **not** issued: `roomCreate` and `roomAdmin`. A
browser that could create rooms could create rooms it was not minted for, and
the mint is the only thing standing between a page and the media server.
`canPublishData` is granted because §2.3's typing signal and §1.4's level meter
ride the data channel.

The exception hierarchy mirrors `server/tokens.py` exactly, so `server/app.py`
handles a rejected LiveKit token and a rejected Phase 2b token with the same
code and produces the same HTTP status and the same trace event.

**What this mint does not issue: the agent worker's own credential.** The
worker registers with the media server once, on the API key pair, and the
server hands it a per-job token when it dispatches it into a room
(`server/livekit_agent.py`). So everything minted here is a *browser-side*
credential — the caller today, and the human support seat that joins the same
room at `docs/06` §5.3 tomorrow, which is one more `mint()` call with a
different `identity` and no new mechanism at all. That is the whole of D-02's
argument for LiveKit, visible in the size of the change it implies.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from server.tokens import (  # noqa: F401 — re-exported on purpose, see module docstring
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    MintedSession,
    TokenError,
    TokenExpired,
    TokenMalformed,
    TokenScopeError,
    TokenSignatureError,
    new_identity,
    new_room_id,
)

#: LiveKit's `--dev` mode hard-codes this pair. It is published in LiveKit's
#: own documentation, which is exactly why `README.md` says in as many words
#: that it is a local-loop credential and never a deployed one.
DEV_API_KEY = "devkey"
DEV_API_SECRET = "secret"


@dataclass(frozen=True)
class Claims:
    """What a verified LiveKit token says. Same shape as `server/tokens.py`."""

    room: str
    identity: str
    issued_at: int
    expires_at: int
    jti: str
    video_grant: dict[str, Any] = field(default_factory=dict)

    @property
    def ttl_seconds(self) -> int:
        return self.expires_at - self.issued_at

    def seconds_remaining(self, now: float | None = None) -> int:
        return int(self.expires_at - (time.time() if now is None else now))


def mint(
    *,
    room: str,
    identity: str,
    api_key: str,
    api_secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    name: str = "",
    now: float | None = None,
) -> str:
    """Mint a LiveKit join token for exactly one room and one identity.

    Args:
        room: The one room this token admits its holder to.
        identity: The one participant identity it admits them as.
        api_key: The LiveKit API key the media server knows us by.
        api_secret: The signing secret. Never leaves this process.
        ttl_seconds: Lifetime, capped at :data:`MAX_TTL_SECONDS`.
        name: Display name. Cosmetic; LiveKit shows it to other participants.
        now: Issue time, for tests.

    Raises:
        ValueError: On an empty key or secret, a non-single room or identity,
            or a TTL outside ``0 < ttl <= MAX_TTL_SECONDS``.
    """
    if not api_key or not api_secret:
        raise ValueError("refusing to mint without a LiveKit API key and secret")
    room = _one(room, "room")
    identity = _one(identity, "identity")
    ttl = int(ttl_seconds)
    if ttl <= 0:
        raise ValueError(f"ttl_seconds must be positive, got {ttl}")
    if ttl > MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl_seconds {ttl} exceeds the {MAX_TTL_SECONDS}s ceiling — §1.4.2 "
            "says minutes, not hours"
        )

    import jwt  # PyJWT, a livekit-api dependency

    issued = int(now if now is not None else time.time())
    grant = {
        "roomJoin": True,
        "room": room,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
        "canUpdateOwnMetadata": True,
        # No roomCreate, no roomAdmin, no roomList: see the module docstring.
    }
    payload: dict[str, Any] = {
        "iss": api_key,
        "sub": identity,
        "jti": secrets.token_urlsafe(9),
        "nbf": issued,
        "iat": issued,
        "exp": issued + ttl,
        "video": grant,
    }
    if name:
        payload["name"] = name
    return jwt.encode(payload, api_secret, algorithm="HS256")


def verify(
    token: str,
    *,
    api_key: str,
    api_secret: str,
    room: str,
    identity: str | None = None,
    now: float | None = None,
    leeway_seconds: int = 0,
) -> Claims:
    """Verify a LiveKit token **for one named room**, returning its claims.

    `room` is required for the same reason `server/tokens.py` requires it: a
    join token is only ever presented alongside the room it is being used on,
    so that room is always in hand at the call site, and verifying without one
    answers a question nobody should be asking.

    The algorithm is pinned to HS256. PyJWT would otherwise accept whatever the
    header asks for, and a token that chooses its own algorithm is a token that
    can choose `none`.

    Raises:
        TokenMalformed, TokenSignatureError, TokenExpired, TokenScopeError.
    """
    if not api_secret:
        raise ValueError("refusing to verify with an empty signing secret")
    if not isinstance(token, str) or not token:
        raise TokenMalformed("token must be a non-empty string")

    import jwt

    try:
        payload = jwt.decode(
            token,
            api_secret,
            algorithms=["HS256"],
            issuer=api_key or None,
            leeway=leeway_seconds,
            options={"require": ["exp", "sub", "iss"], "verify_iss": bool(api_key)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired(f"token expired: {exc}") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenScopeError(f"token was minted by a different API key: {exc}") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenSignatureError("signature does not match payload") from exc
    except jwt.DecodeError as exc:
        raise TokenMalformed(f"undecodable token: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenScopeError(str(exc)) from exc

    grant = payload.get("video")
    if not isinstance(grant, dict):
        raise TokenScopeError("token carries no video grant")
    if not grant.get("roomJoin"):
        raise TokenScopeError("token does not grant roomJoin")
    if grant.get("room") != room:
        raise TokenScopeError("token was minted for a different room")
    if identity is not None and payload.get("sub") != identity:
        raise TokenScopeError("token was minted for a different identity")
    # The mint never issues these; a token that has them is not one of ours.
    for forbidden in ("roomCreate", "roomAdmin", "roomList"):
        if grant.get(forbidden):
            raise TokenScopeError(f"token carries an unexpected {forbidden} grant")

    stamp = time.time() if now is None else now
    expires_at = int(payload["exp"])
    if expires_at <= stamp - leeway_seconds:
        raise TokenExpired(f"token expired at {expires_at}, {int(stamp - expires_at)}s ago")
    issued_at = int(payload.get("iat") or payload.get("nbf") or expires_at - DEFAULT_TTL_SECONDS)
    if issued_at > stamp + leeway_seconds + 1:
        raise TokenScopeError("token is issued in the future")
    return Claims(
        room=room,
        identity=str(payload.get("sub") or ""),
        issued_at=issued_at,
        expires_at=expires_at,
        jti=str(payload.get("jti") or ""),
        video_grant=grant,
    )


def peek(token: str) -> dict[str, Any]:
    """Read a token's claims **without** verifying it — trace and logs only.

    Never use this to decide anything. It exists so that a rejected join can be
    traced with the room it was aimed at.
    """
    try:
        import jwt

        payload = jwt.decode(token, options={"verify_signature": False})
        grant = payload.get("video") or {}
        return {
            "room": grant.get("room"),
            "identity": payload.get("sub"),
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
            "jti": payload.get("jti"),
            "iss": payload.get("iss"),
        }
    except Exception:  # noqa: BLE001
        return {}


def _one(value: str, label: str) -> str:
    """One room, one identity, named plainly — same rule as `server/tokens.py`."""
    value = str(value)
    if not value or value.strip() != value:
        raise ValueError(f"{label} must be a non-empty id with no surrounding space")
    if any(ch in value for ch in ",* \t\n"):
        raise ValueError(f"{label} must name exactly one {label}, got {value!r}")
    return value
