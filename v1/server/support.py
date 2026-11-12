"""The support side: observer tokens, the console's surfaces, the §5.3 join.

`docs/07` D-17 names what is missing and who it blocks:

> **Same-session join** — *chosen*. … needs a live queue, an available human,
> and an agent-side console that can join a room — and **that console does not
> exist** (`06` §9.3 item 14).

This module is the server half of that console. It is scaffolding for
`docs/06` §9.1 Phase 4 — "live sessions with a human monitoring and able to
**join the room** at any moment (§5.3)" — and it deliberately stops short of
the pilot itself: no queue, no routing, no availability model, no live users.
What it provides is the thing those would need to exist on top of.

**The observer is not the caller, and the token says so.**
`server/tokens.py` now mints two disjoint scopes. The caller's token
(`join:room`, identity `caller-…`) reaches signalling, media, the control
socket and the trace. The observer's (`observe:room`, identity `observer-…`)
reaches the surfaces in this file and nothing else. Neither is usable where the
other is: `verify` defaults to the caller scope, so every pre-existing surface
refuses an observer token without being edited, and :func:`authorise_observer`
names its scope explicitly, so a caller token is refused here. `docs/06` §1.4.2
asks for short-lived, single-room, single-identity; an observer token is all
three *and* single-scope, and it is a fresh identity per admission rather than
a standing support credential.

**Minting one needs the support key.** A room id is not a secret — it travels
in URLs and in the trace — so possession of one must not be enough to watch the
session it names. `ROVE_SUPPORT_KEY` is the stand-in for the real answer, which
is whatever the support organisation already authenticates its people with.
§9.3 item 2 owns that, and the key is deliberately a single obvious seam rather
than a login system this project would be guessing at.

**The join, and what it changes.** §5.3:

> The agent announces the join, stops proposing steps, and drops to
> transcribing and recording the ledger. The human sees the §5.2 panel as they
> arrive.

So :func:`join` does three things and traces all three: it records a
:class:`~server.core_bridge.Participant`, it flips the session to
``AGENT_MODE_TRANSCRIBING``, and it tells both the caller's page and the
console. The flip is the load-bearing part and it lives in `core_bridge`, not
in `agent/`.

**Disclosure comes first.** §6.3's third bullet, and §5.3's last paragraph:

> A human joining the room can hear the user and read the transcript. That is a
> disclosure in its own right and the agent makes it **before the join, not
> after**.

:func:`join` refuses with 409 until :func:`disclose` has run. The two-step
shape is the point — a single "join" button that did both would make the
ordering a matter of implementation detail rather than something the code
insists on. §5.3's "it never announces a join that has not happened" is the
mirror rule and is why the announcement is worded as an intention and the
arrival is a second, separate message.

**What a human may do here, and what they may not.** The console socket accepts
a note and a ping. It does not accept `user.text`: a support human typing into
the caller's turn dispatcher would put words in the caller's mouth, and §7.2's
M10 is computed from a transcript whose caller lines are the caller's.
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from server import consent as consent_module
from server import tokens as token_module
from server import transcripts as transcript_store
from server.core_bridge import (
    AGENT_MODE_PROPOSING,
    AGENT_MODE_TRANSCRIBING,
    Participant,
    Session,
    TranscriptLine,
    fanout,
)
from server.handoff import build_handoff


def check_support_key(state: Any, key: str) -> None:
    """The one gate on minting an observer token.

    Constant-time, because a key that leaks its prefix to a timing loop is not
    a key. A 401 rather than a 403: this says "we do not know who you are",
    which is true — there is no support identity in this scaffolding beyond
    holding the key.
    """
    expected = state.settings.support_key
    if not expected:
        raise HTTPException(status_code=503, detail="no support key is configured")
    if not key or not hmac.compare_digest(str(key), expected):
        raise HTTPException(status_code=401, detail="support key required")


def authorise_observer(state: Any, token: str, room: str) -> Session:
    """Verify an **observer** token for this room, and return its session.

    Three checks, and all three have to pass: the scope claim is
    `observe:room`, the room claim is this room, and the identity claim is one
    this room actually issued. The third is what stops an observer token minted
    for one room from being replayed into another that happens to share a
    secret — the room check already covers that, and the identity check covers
    the case where it did not, which is the kind of redundancy a credential
    boundary earns.
    """
    if not token or not room:
        raise HTTPException(status_code=401, detail="token and room are required")
    session = state.sessions.get(room)
    if session is None:
        raise HTTPException(status_code=404, detail="no such room")
    try:
        claims = token_module.verify(
            token,
            secret=state.settings.token_secret,
            room=room,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
    except token_module.TokenExpired as exc:
        session.trace.event("observer.rejected", reason="expired", room=room)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except token_module.TokenError as exc:
        session.trace.event(
            "observer.rejected",
            reason=type(exc).__name__,
            room=room,
            presented_scope=token_module.peek(token).get("scope"),
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if claims.identity == session.identity:
        # Unreachable while the mint pairs scope with identity prefix; here
        # because "the observer is never the caller" is the property, and a
        # property worth stating is worth asserting.
        session.trace.event("observer.rejected", reason="identity_is_caller")
        raise HTTPException(status_code=403, detail="observer identity is the caller")
    if claims.identity not in session.observer_identities:
        session.trace.event(
            "observer.rejected", reason="unknown_identity", identity=claims.identity
        )
        raise HTTPException(
            status_code=403, detail="observer identity was not issued for this room"
        )
    return session


def room_summary(session: Session) -> dict[str, Any]:
    """One row of the console's room list. No transcript, no caller words.

    The picker exists to choose a room, so it carries what that choice is made
    on — how long, how many turns, whether it has escalated, whether a human is
    already in it — and nothing the §6.3 consent questions apply to.
    """
    return {
        "room": session.room,
        "session_id": session.session_id,
        "started_at": session.created_at,
        "duration_s": round(time.time() - session.created_at, 1),
        "turn": session.state.turn,
        "fsm_state": session.state.state.value,
        "category": session.state.problem.category,
        "taxonomy_id": session.state.problem.taxonomy_id,
        "escalated": session.state.escalation.triggered,
        "escalation_reason_code": session.state.escalation.reason_code,
        "hazard": bool(session.state.safety.hazard_flags),
        "footage_at_stake": session.state.safety.footage_at_stake,
        "agent_mode": session.agent_mode,
        "humans_present": [p.display_name or p.identity for p in session.humans_present],
        "consent": {
            "display": session.consent.display,
            "storage": session.consent.storage,
            "disclosed": session.consent.disclosed_at is not None,
        },
        "observers": len(session.observers),
        "caller_connected": bool(session.listeners),
    }


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def register_support_routes(app: FastAPI, state: Any) -> None:
    """Mount every support surface on the app `create_app` is building."""

    settings = state.settings

    # -- the observer mint (§1.4.2's shape, §5.3's purpose) ----------------

    @app.post("/api/support/observer")
    async def mint_observer(request: Request) -> dict[str, Any]:
        """Mint a short-lived **observer** token for one room.

        Never the caller token, and never a widened copy of it: a separate
        scope, a separate identity, its own TTL, and a separate mint whose only
        caller is a holder of the support key.
        """
        body = await request.json()
        check_support_key(state, body.get("key", ""))
        room = str(body.get("room", "")).strip()
        session = state.sessions.get(room)
        if session is None:
            raise HTTPException(status_code=404, detail="no such room")
        identity = token_module.new_observer_identity()
        token = token_module.mint(
            room=room,
            identity=identity,
            secret=settings.token_secret,
            ttl_seconds=settings.observer_ttl_seconds,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
        claims = token_module.verify(
            token,
            secret=settings.token_secret,
            room=room,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
        session.observer_identities.add(identity)
        session.trace.event(
            "observer.minted",
            observer_identity=identity,
            scope=token_module.SCOPE_OBSERVE_ROOM,
            jti=claims.jti,
            expires_at=claims.expires_at,
            ttl_seconds=claims.ttl_seconds,
        )
        return {
            "room": room,
            "identity": identity,
            "scope": token_module.SCOPE_OBSERVE_ROOM,
            "token": token,
            "expires_at": claims.expires_at,
            "ttl_seconds": claims.ttl_seconds,
            "session_id": session.session_id,
        }

    @app.get("/api/support/rooms")
    async def list_rooms(key: str = Query("")) -> dict[str, Any]:
        """Live rooms, for the console's picker. Support key, not a token."""
        check_support_key(state, key)
        rows = []
        for room in state.sessions.rooms():
            session = state.sessions.get(room)
            if session is not None:
                rows.append(room_summary(session))
        rows.sort(key=lambda row: row["started_at"], reverse=True)
        return {"rooms": rows, "count": len(rows)}

    # -- reading one session ------------------------------------------------

    @app.get("/api/support/room/{room}/handoff")
    async def handoff(room: str, token: str = Query("")) -> dict[str, Any]:
        """The §5.2 panel, rebuilt from `DiagnosticState` on every request.

        D-17: *"the handoff is not something sent somewhere — it is the panel
        the joining human sees, rendered from `DiagnosticState` at the moment
        they are admitted and live thereafter."* Live thereafter is why this is
        a GET the console polls rather than a snapshot taken at the join.
        """
        session = authorise_observer(state, token, room)
        return {
            "handoff": build_handoff(session),
            "snapshot": _observer_snapshot(session),
        }

    @app.get("/api/support/room/{room}/trace")
    async def observer_trace(
        room: str, token: str = Query(""), since_seq: int = Query(0)
    ) -> dict[str, Any]:
        session = authorise_observer(state, token, room)
        return {
            "summary": session.trace.summary(),
            "events": session.trace.events(since_seq=since_seq),
        }

    # -- the §5.3 join ------------------------------------------------------

    @app.post("/api/support/room/{room}/disclose")
    async def disclose(room: str, request: Request) -> dict[str, Any]:
        """The §6.3 second consent surface, made **before** the join.

        It is its own request because it is its own event: the caller is told
        that a human will be able to hear them and read the transcript, and
        that telling has to be able to happen — and be seen to have happened —
        while the join is still only an intention.
        """
        body = await request.json()
        session = authorise_observer(state, body.get("token", ""), room)
        text = (
            str(body.get("text") or "").strip()
            or consent_module.DEFAULT_ESCALATION_DISCLOSURE
        )
        session.consent.disclose_escalation(text=text)
        session.add_line(
            TranscriptLine(role="agent", text=text, modality="text", turn=session.state.turn)
        )
        session.trace.event(
            "escalation.disclosed", text=text, turn=session.state.turn
        )
        await fanout(
            session,
            {
                "type": "transcript",
                "line": {
                    "role": "agent",
                    "text": text,
                    "modality": "text",
                    "turn": session.state.turn,
                    "at": time.time(),
                },
            },
        )
        await fanout(session, {"type": "consent", "consent": session.consent.as_dict()})
        return {"ok": True, "consent": session.consent.as_dict()}

    @app.post("/api/support/room/{room}/join")
    async def join(room: str, request: Request) -> dict[str, Any]:
        """Admit the human to the room the caller is already in (§5.3, D-17).

        No transfer, no bridge, no second connection for the caller: the only
        thing that changes about the session is who else is in it — and, as a
        consequence of that, what the agent does with the next turn.
        """
        body = await request.json()
        token = body.get("token", "")
        session = authorise_observer(state, token, room)
        claims = token_module.verify(
            token,
            secret=settings.token_secret,
            room=room,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
        if not session.consent.escalation_disclosed:
            # §6.3: before the join, not after. A 409 rather than a 403 —
            # nothing is wrong with the credential, the session is not in a
            # state where this is allowed yet.
            raise HTTPException(
                status_code=409,
                detail=(
                    "§6.3: the caller has not been told a human can hear them "
                    "and read the transcript — disclose first"
                ),
            )
        existing = session.participant(claims.identity)
        if existing is not None and existing.present:
            return {
                "ok": True,
                "already_joined": True,
                "agent_mode": session.agent_mode,
                "participants": [p.as_dict() for p in session.participants],
            }
        participant = Participant(
            identity=claims.identity,
            display_name=str(body.get("display_name") or "").strip(),
            role="support",
        )
        session.participants.append(participant)
        previous = session.set_agent_mode(
            AGENT_MODE_TRANSCRIBING,
            reason="support human joined the room (§5.3)",
        )
        session.trace.event(
            "support.joined",
            observer_identity=participant.identity,
            display_name=participant.display_name,
            turn=session.state.turn,
            agent_mode=session.agent_mode,
            previous_agent_mode=previous,
        )
        # §5.3: "The agent announces the join." It announces the arrival, which
        # has now happened — never one that has not.
        announcement = (
            f"{participant.display_name or 'A member of the support team'} has "
            "joined and can see what we've covered. I'll stop suggesting steps "
            "and keep the notes."
        )
        session.add_line(
            TranscriptLine(
                role="agent", text=announcement, modality="text", turn=session.state.turn
            )
        )
        await fanout(
            session,
            {
                "type": "transcript",
                "line": {
                    "role": "agent",
                    "text": announcement,
                    "modality": "text",
                    "turn": session.state.turn,
                    "at": time.time(),
                },
            },
        )
        await fanout(
            session,
            {
                "type": "participants",
                "agent_mode": session.agent_mode,
                "participants": [p.as_dict() for p in session.participants],
            },
        )
        return {
            "ok": True,
            "already_joined": False,
            "agent_mode": session.agent_mode,
            "participants": [p.as_dict() for p in session.participants],
            "handoff": build_handoff(session),
        }

    @app.post("/api/support/room/{room}/leave")
    async def leave(room: str, request: Request) -> dict[str, Any]:
        """Leave the room. The agent does **not** resume by default.

        §5.3 says what the join does to the agent and says nothing about what a
        departure does, so the safe reading is that it does nothing: a caller
        who has been told a human is handling it should not find the agent
        proposing steps again because somebody closed a tab. Resuming is an
        explicit, traced act, which is what `resume_agent` is.
        """
        body = await request.json()
        token = body.get("token", "")
        session = authorise_observer(state, token, room)
        claims = token_module.verify(
            token,
            secret=settings.token_secret,
            room=room,
            scope=token_module.SCOPE_OBSERVE_ROOM,
        )
        participant = session.participant(claims.identity)
        if participant is not None and participant.present:
            participant.left_at = time.time()
            session.trace.event(
                "support.left",
                observer_identity=participant.identity,
                turn=session.state.turn,
            )
        resume = bool(body.get("resume_agent"))
        if resume and not session.humans_present:
            session.set_agent_mode(
                AGENT_MODE_PROPOSING,
                reason="support human handed the session back (§5.3)",
            )
        await fanout(
            session,
            {
                "type": "participants",
                "agent_mode": session.agent_mode,
                "participants": [p.as_dict() for p in session.participants],
            },
        )
        return {
            "ok": True,
            "agent_mode": session.agent_mode,
            "participants": [p.as_dict() for p in session.participants],
        }

    # -- §6.3 / §9.1 Phase 4: the pilot corpus ------------------------------

    @app.post("/api/support/room/{room}/collect")
    async def collect(room: str, request: Request) -> dict[str, Any]:
        """Write this session's transcript to the pilot corpus, if consented.

        Two failure modes and they are different HTTP answers, because they are
        different facts: 409 means §6.3 says no, and nothing was attempted;
        503 means consent exists and Postgres does not.
        """
        body = await request.json()
        session = authorise_observer(state, body.get("token", ""), room)
        try:
            receipt = transcript_store.collect(
                session,
                redact_identifiers=bool(body.get("redact", True)),
            )
        except transcript_store.ConsentRequired as exc:
            session.trace.event(
                "transcript.refused",
                reason="no storage consent (§6.3)",
                consent=session.consent.as_dict(),
            )
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except transcript_store.StoreUnavailable as exc:
            session.trace.event("transcript.store_unavailable", error=str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "receipt": receipt}

    # -- the console socket --------------------------------------------------

    @app.websocket("/ws/support")
    async def support_socket(
        socket: WebSocket, token: str = Query(""), room: str = Query("")
    ) -> None:
        """The console's live feed. Read-mostly, by construction.

        It joins `session.observers`, not `session.listeners`, so it receives
        the session feed and the turn dispatcher never sees it. The accepted
        message set is three items long and `user.text` is not one of them.
        """
        try:
            session = authorise_observer(state, token, room)
        except HTTPException as exc:
            await socket.accept()
            await socket.send_json({"type": "error", "detail": exc.detail})
            await socket.close(code=4403)
            return
        await socket.accept()
        session.observers.add(socket)
        session.trace.event("observer.connected", observers=len(session.observers))
        try:
            await socket.send_json(
                {
                    "type": "hello",
                    "snapshot": _observer_snapshot(session),
                    "handoff": build_handoff(session),
                }
            )
            while True:
                message = await socket.receive_json()
                await _handle_observer_message(state, session, socket, message)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            session.trace.event("observer.error", error=f"{type(exc).__name__}: {exc}")
        finally:
            session.observers.discard(socket)
            session.trace.event("observer.disconnected", observers=len(session.observers))


def _observer_snapshot(session: Session) -> dict[str, Any]:
    """What the console renders: the session, plus who is in the room.

    The transcript is here under §6.3's display rule, not its storage rule:
    a human who has been disclosed to the caller may read what has been said.
    Nothing in this snapshot is written anywhere.
    """
    from server.core_bridge import session_snapshot

    snapshot = session_snapshot(session)
    snapshot["observer_view"] = True
    snapshot["spoken_claims"] = [
        {
            "claim": claim.claim,
            "chunk_ids": list(claim.chunk_ids),
            "tier": claim.tier,
            "retrieval_date": claim.retrieval_date,
            "turn": claim.turn,
        }
        for claim in session.state.clearance.spoken_claims
    ]
    return snapshot


async def _handle_observer_message(
    state: Any, session: Session, socket: WebSocket, message: dict[str, Any]
) -> None:
    """One message from the console. Three are accepted; the rest are refused."""
    kind = message.get("type")

    if kind == "ping":
        await socket.send_json({"type": "pong", "t": time.time()})
        return

    if kind == "refresh":
        await socket.send_json(
            {
                "type": "hello",
                "snapshot": _observer_snapshot(session),
                "handoff": build_handoff(session),
            }
        )
        return

    if kind == "support.note":
        # A human's own note, into the trace and the console — not into the
        # transcript and not into `DiagnosticState`. §3.3's rule holds: if a
        # fact is not in `DiagnosticState` it does not exist for
        # decision-making, and a free-text note is exactly the kind of thing
        # that must not become an input to the policy layer.
        text = str(message.get("text") or "").strip()
        if not text:
            await socket.send_json({"type": "error", "detail": "empty note"})
            return
        session.trace.event("support.note", text=text, turn=session.state.turn)
        await fanout(
            session,
            {"type": "support.note", "text": text, "at": time.time()},
            caller=False,
        )
        return

    if kind == "user.text":
        # Refused explicitly rather than falling through to the generic error,
        # because *why* it is refused is the point. A support human typing here
        # would author a caller line, and §7.2's M10 is computed over a
        # transcript whose caller lines are the caller's.
        session.trace.event("observer.refused", kind=kind)
        await socket.send_json(
            {
                "type": "error",
                "detail": (
                    "an observer may not speak as the caller — join the room "
                    "and talk to them (§5.3)"
                ),
            }
        )
        return

    await socket.send_json(
        {"type": "error", "detail": f"unknown message type {kind!r}"}
    )
