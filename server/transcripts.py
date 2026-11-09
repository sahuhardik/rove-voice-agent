"""Consented transcripts, written to the pilot corpus (`docs/06` §6.3, §9.1).

Phase 4 is "collect real transcripts (consent permitting — §6.3) and **replace
`03`'s written utterances with real user language**". This module is the write
path for that corpus and nothing else: it does not run a pilot, it does not
schedule anything, and it never writes on its own — a session is collected when
something asks for it, and only then.

**Postgres, same DSN pattern as `agent/store.py`.** `docs/07` D-12 already put
the chunks, the source registry and the ledgers in one transactional store and
said why: "the source registry, the clearance flags, the ledgers, the
orchestration checkpoints and the traces all want to be in the same
transactional store as the chunks". A pilot transcript is in that list. So this
reads the same `ROVE_PG_DSN`, defaults to the same peer-auth socket, caches its
connection failure the same way, and raises :class:`StoreUnavailable` rather
than crashing a session when the database is not there — a support console that
cannot reach Postgres is still a working console.

**The gate, and where it sits.** §6.3's first bullet is the requirement:

> Recording is off until a consent decision exists for the session. … No
> consent decision → no audio written to disk.

:func:`collect` asks :meth:`ConsentState.may_store` **before it opens a
connection**. That ordering is the design, not an optimisation: an
un-consented session does not reach the network, so there is no window in which
a DSN typo, a retry or a half-finished transaction could leave part of it
somewhere. `server/test_support.py` pins it by calling `collect` on an
un-consented session with no database running at all and asserting the error is
:class:`ConsentRequired` rather than :class:`StoreUnavailable`.

The same rule is then stated a second time, in the schema, as
``CHECK (consent_storage = 'granted')`` — the same technique `agent/store.py`
uses for §4.5's tier and status rules, and for the same reason: *"a filter bug
is a plausible event and a rejected INSERT is not"*. Two independent statements
of one rule, in the language of two different layers.

**Redaction** (§6.3 data minimisation): "Serial numbers, and any contact
details taken for a callback, are identifiers: they go into the handoff payload,
and are redacted by default from the evaluation corpus". The pilot corpus *is*
the evaluation corpus, so :func:`redact` runs over everything stored here by
default — the transcript lines and the copy of the handoff payload alike. The
live handoff panel a human reads is built fresh from `DiagnosticState` and is
not touched by any of this.

**What is not stored, ever.** Audio. §6.3 puts the recording tap at the WebRTC
edge and Phase 3 owns it; this milestone writes text and leaves
:meth:`ConsentState.may_record_audio` as the predicate that tap will ask.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from server import consent as consent_module

#: Peer auth over the Unix socket; no password anywhere in the repo. The same
#: default and the same environment variable as `agent/store.py`, so one DSN
#: configures the whole system.
DEFAULT_DSN = "postgresql://ubuntu@/rove?host=/var/run/postgresql"
DSN = os.environ.get("ROVE_PG_DSN", DEFAULT_DSN)


class StoreUnavailable(RuntimeError):
    """The database is not reachable. Callers report it; they do not crash."""


class ConsentRequired(RuntimeError):
    """§6.3: there is no storage consent for this session, so nothing is written.

    Deliberately **not** a subclass of :class:`StoreUnavailable`. "We may not"
    and "we could not" are different answers and a caller that collapsed them
    would retry the first one.
    """


# --------------------------------------------------------------------------
# Connection — the `agent/store.py` shape
# --------------------------------------------------------------------------

_lock = threading.Lock()
_conn: Any = None
_conn_failed = False


def connect(dsn: str | None = None, *, fresh: bool = False) -> Any:
    """A cached autocommit connection. The failure is cached too."""
    global _conn, _conn_failed
    with _lock:
        if fresh or dsn is not None:
            return _open(dsn or DSN)
        if _conn is not None and not getattr(_conn, "closed", False):
            return _conn
        if _conn_failed:
            raise StoreUnavailable(f"no connection to {DSN}")
        try:
            _conn = _open(DSN)
        except Exception as exc:  # noqa: BLE001 — any driver error is the same answer
            _conn_failed = True
            raise StoreUnavailable(str(exc)) from exc
        return _conn


def _open(dsn: str) -> Any:
    try:
        import psycopg
    except Exception as exc:  # noqa: BLE001 — driver absent is unavailability
        raise StoreUnavailable(f"psycopg is not installed: {exc}") from exc
    try:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except Exception as exc:  # noqa: BLE001
        raise StoreUnavailable(f"{dsn}: {exc}") from exc


def reset_connection() -> None:
    """Forget the cached connection *and* the cached failure (tests)."""
    global _conn, _conn_failed
    with _lock:
        if _conn is not None and not getattr(_conn, "closed", False):
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn = None
        _conn_failed = False


def is_available(dsn: str | None = None) -> bool:
    try:
        connect(dsn).execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return False
    return True


# --------------------------------------------------------------------------
# Redaction (§6.3 data minimisation)
# --------------------------------------------------------------------------

#: Contact details taken for a callback, and serial numbers. The serial
#: pattern is deliberately narrow — a long unbroken run of letters *and*
#: digits — because this corpus is full of model names (`R2-4K`), card
#: markings (`U3`, `V30`) and step ids, and a greedy identifier rule would eat
#: the content the corpus exists to hold.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (
        re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"),
        "[PHONE]",
    ),
    (
        re.compile(
            r"(?<![\w-])(?=[A-Za-z0-9]{10,})(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])"
            r"[A-Za-z0-9]{10,}(?![\w-])"
        ),
        "[SERIAL]",
    ),
    (
        re.compile(r"(?i)\bserial(?:\s+number)?\s*(?:is|:)?\s*([A-Za-z0-9-]{6,})"),
        "serial [SERIAL]",
    ),
)


def redact(value: Any) -> Any:
    """Replace identifiers in a string, or recursively through a structure."""
    if isinstance(value, str):
        out = value
        for pattern, replacement in _PATTERNS:
            out = pattern.sub(replacement, out)
        return out
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

#: `IF NOT EXISTS` rather than the `DROP … CASCADE` migration `agent/store.py`
#: runs: that one rebuilds a corpus from a file that is the source of truth,
#: and this one holds the only copy of something a caller consented to once.
SCHEMA = """
CREATE TABLE IF NOT EXISTS pilot_sessions (
    session_id            text PRIMARY KEY,
    room                  text NOT NULL,
    started_at            timestamptz NOT NULL,
    collected_at          timestamptz NOT NULL DEFAULT now(),
    duration_s            double precision,
    turns                 integer NOT NULL DEFAULT 0,

    -- docs/06 §6.3, stated a second time in the language of the schema.
    -- `granted` is the only value this table will hold: an un-consented
    -- session cannot be inserted even by code that forgot to ask.
    consent_storage       text NOT NULL CHECK (consent_storage = 'granted'),
    consent_display       text NOT NULL,
    consent_disclosed_at  timestamptz NOT NULL,
    consent_modality      text NOT NULL,
    consent_jurisdiction  text NOT NULL,

    -- §6.3 "two retention classes": this table is the *evaluation* class and
    -- carries its own clock, which §9.3 item 4 owns the value of.
    retention_class       text NOT NULL DEFAULT 'evaluation',
    retention_until       timestamptz,

    agent_mode            text NOT NULL,
    escalated             boolean NOT NULL DEFAULT false,
    escalation_reason_code text,
    fsm_state             text,
    taxonomy_id           text,
    taxonomy_status       text,
    category              text,
    model                 text,
    model_confidence      text,

    agent_version         text,
    corpus_snapshot_date  text,
    redacted              boolean NOT NULL DEFAULT true,
    -- The §5.2 panel as it stood at collection. Operational-class content,
    -- copied here so a corpus row is readable without the live session.
    handoff               jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_transcript_lines (
    session_id  text NOT NULL REFERENCES pilot_sessions(session_id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    role        text NOT NULL CHECK (role IN ('caller', 'agent', 'support')),
    turn        integer,
    modality    text,
    confidence  double precision,
    said_at     timestamptz,
    text        text NOT NULL,
    PRIMARY KEY (session_id, seq)
);

CREATE INDEX IF NOT EXISTS pilot_lines_session
    ON pilot_transcript_lines (session_id, seq);
"""


def ensure_schema(dsn: str | None = None) -> None:
    """Create the two tables if they are not there. Idempotent."""
    connect(dsn).execute(SCHEMA)


# --------------------------------------------------------------------------
# The write path
# --------------------------------------------------------------------------


def _stamp(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def check_consent(session: Any) -> None:
    """The §6.3 gate, on its own so it can be asked without writing.

    Raises:
        ConsentRequired: When no storage decision exists, or it is a decline.
    """
    state: consent_module.ConsentState = session.consent
    if not state.may_store():
        raise ConsentRequired(
            f"session {session.session_id}: storage consent is "
            f"{state.storage!r} — §6.3 stores nothing until it is "
            f"{consent_module.GRANTED!r}"
        )


def collect(
    session: Any,
    *,
    dsn: str | None = None,
    redact_identifiers: bool = True,
    handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one consented session to the pilot corpus.

    The consent check is first, and it is first on purpose: an un-consented
    session must not open a connection, because "we did not write it" is a
    weaker claim than "we never tried".

    Args:
        session: A `server.core_bridge.Session`.
        dsn: Override the DSN (tests, or a second corpus).
        redact_identifiers: §6.3 data minimisation. Default on.
        handoff: The §5.2 payload to file alongside. Built if not supplied.

    Returns:
        A receipt: the session id, the line count and what was gated.

    Raises:
        ConsentRequired: No storage consent (§6.3). Nothing was attempted.
        StoreUnavailable: Consent exists, the database does not.
    """
    check_consent(session)

    from server.handoff import build_handoff  # deferred: handoff imports agent/

    payload = handoff if handoff is not None else build_handoff(session)
    lines = [line.as_dict() for line in session.transcript]
    if redact_identifiers:
        lines = redact(lines)
        payload = redact(payload)

    consent_state: consent_module.ConsentState = session.consent
    state = session.state

    ensure_schema(dsn)
    conn = connect(dsn)
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO pilot_sessions (
                session_id, room, started_at, duration_s, turns,
                consent_storage, consent_display, consent_disclosed_at,
                consent_modality, consent_jurisdiction,
                agent_mode, escalated, escalation_reason_code, fsm_state,
                taxonomy_id, taxonomy_status, category, model,
                model_confidence, agent_version, corpus_snapshot_date,
                redacted, handoff
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (session_id) DO UPDATE SET
                collected_at = now(),
                duration_s   = EXCLUDED.duration_s,
                turns        = EXCLUDED.turns,
                agent_mode   = EXCLUDED.agent_mode,
                escalated    = EXCLUDED.escalated,
                escalation_reason_code = EXCLUDED.escalation_reason_code,
                fsm_state    = EXCLUDED.fsm_state,
                handoff      = EXCLUDED.handoff
            """,
            (
                session.session_id,
                session.room,
                _stamp(session.created_at),
                round(payload.get("duration_s") or 0.0, 3),
                state.turn,
                consent_state.storage,
                consent_state.display,
                _stamp(consent_state.disclosed_at),
                consent_state.storage_modality,
                consent_state.jurisdiction,
                session.agent_mode,
                bool(state.escalation.triggered),
                state.escalation.reason_code or None,
                state.state.value,
                state.problem.taxonomy_id,
                state.entry_status,
                state.problem.category,
                state.device.reported_model,
                state.device.confidence,
                payload.get("agent_version"),
                payload.get("corpus_snapshot_date"),
                bool(redact_identifiers),
                json.dumps(payload, default=str),
            ),
        )
        # Replace rather than append: a session can be collected again after
        # more turns, and a corpus row that held two overlapping copies of one
        # conversation would be worse than useless for `03`'s purpose.
        conn.execute(
            "DELETE FROM pilot_transcript_lines WHERE session_id = %s",
            (session.session_id,),
        )
        for seq, line in enumerate(lines, start=1):
            conn.execute(
                """
                INSERT INTO pilot_transcript_lines
                    (session_id, seq, role, turn, modality, confidence, said_at, text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session.session_id,
                    seq,
                    line["role"],
                    line.get("turn"),
                    line.get("modality"),
                    line.get("confidence"),
                    _stamp(line.get("at")),
                    line["text"],
                ),
            )

    receipt = {
        "session_id": session.session_id,
        "room": session.room,
        "lines": len(lines),
        "turns": state.turn,
        "redacted": bool(redact_identifiers),
        "retention_class": consent_module.RETENTION_EVALUATION,
        "audio": "none — §6.3 recording tap is Phase 3's and writes nothing here",
        "collected_at": time_now_iso(),
    }
    session.trace.event("transcript.collected", **receipt)
    return receipt


def time_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def fetch(session_id: str, *, dsn: str | None = None) -> dict[str, Any] | None:
    """Read one collected session back. For checking a write, not for serving."""
    conn = connect(dsn)
    row = conn.execute(
        """
        SELECT session_id, room, turns, consent_storage, consent_display,
               redacted, handoff
        FROM pilot_sessions WHERE session_id = %s
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return None
    lines = conn.execute(
        "SELECT seq, role, turn, modality, text FROM pilot_transcript_lines "
        "WHERE session_id = %s ORDER BY seq",
        (session_id,),
    ).fetchall()
    return {
        "session_id": row[0],
        "room": row[1],
        "turns": row[2],
        "consent_storage": row[3],
        "consent_display": row[4],
        "redacted": row[5],
        "handoff": row[6],
        "lines": [
            {"seq": r[0], "role": r[1], "turn": r[2], "modality": r[3], "text": r[4]}
            for r in lines
        ],
    }
