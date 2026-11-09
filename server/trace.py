"""The session trace (`docs/06` §7.5, §9.1 Phase 2b exit).

Phase 2b's exit criterion ends "**and reports RTT/jitter/loss into the
trace**", so the trace is a deliverable here rather than an afterthought. One
JSONL file per session, one object per line, appended as events happen:

    data/traces/phase2b/<session-id>.jsonl

Both ends of the peer connection report. The server samples `aiortc`'s RTCP
view every few seconds (`net.server_stats`); the browser samples its own
`RTCPeerConnection.getStats()` and posts it over the control socket
(`net.client_stats`). They are kept as separate event types on purpose — they
are two measurements of one link, not one measurement, and a disagreement
between them is information.

**What is deliberately not here.** No audio is written, ever: `docs/06` §6.3
puts recording behind a consent flow that Phase 2b does not have. The trace
holds event shapes and numbers — levels in dBFS, segment durations, RTT — and
the caller's typed words, which they typed into our own page.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path
from typing import Any

#: In-memory tail length. The file is the record; this is what the debug
#: endpoint and the verification script read without re-parsing it.
MAX_EVENTS_HELD = 5000


class Trace:
    """One session's event log: a file, a tail in memory, and a summary."""

    def __init__(
        self,
        *,
        session_id: str,
        room: str,
        identity: str,
        directory: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.room = room
        self.identity = identity
        self.started_at = time.time()
        self.path: Path | None = None
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._seq = 0
        #: Set by the app so that an event reaches the open page as well as the
        #: file. Called inline, from whichever thread wrote the event, so it
        #: must do nothing but hand the record off.
        self.subscriber: Any = None
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / f"{session_id}.jsonl"

    # -- writing ---------------------------------------------------------

    def event(self, type: str, **fields: Any) -> dict[str, Any]:
        """Append one event. Returns it, so a caller can forward it to the UI."""
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "t": round(time.time(), 6),
                "elapsed_s": round(time.time() - self.started_at, 3),
                "session_id": self.session_id,
                "room": self.room,
                "identity": self.identity,
                "type": type,
            }
            record.update(fields)
            self._events.append(record)
            if len(self._events) > MAX_EVENTS_HELD:
                del self._events[: len(self._events) - MAX_EVENTS_HELD]
            if self.path is not None:
                try:
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, default=str) + "\n")
                except OSError:
                    # A trace that cannot be written must not take the session
                    # down with it; the in-memory tail still serves the UI.
                    pass
        if self.subscriber is not None:
            try:
                self.subscriber(record)
            except Exception:  # noqa: BLE001 — a dead page is not a dead session
                pass
        return record

    # -- reading ---------------------------------------------------------

    def events(self, *, since_seq: int = 0, types: tuple[str, ...] | None = None) -> list[dict]:
        with self._lock:
            out = [e for e in self._events if e["seq"] > since_seq]
        if types:
            out = [e for e in out if e["type"] in types]
        return out

    def summary(self) -> dict[str, Any]:
        """Session-level numbers, including the §9.1 RTT/jitter/loss lines."""
        with self._lock:
            events = list(self._events)
        counts: dict[str, int] = {}
        for event in events:
            counts[event["type"]] = counts.get(event["type"], 0) + 1
        return {
            "session_id": self.session_id,
            "room": self.room,
            "identity": self.identity,
            "started_at": self.started_at,
            "duration_s": round(time.time() - self.started_at, 3),
            "event_counts": counts,
            "connects": counts.get("webrtc.connected", 0),
            "disconnects": counts.get("webrtc.disconnected", 0),
            "rejoins": max(counts.get("webrtc.connected", 0) - 1, 0),
            "speech_segments": counts.get("vad.speech_end", 0),
            "typed_turns": counts.get("turn.user", 0),
            "network": {
                "server": _network_stats(events, "net.server_stats"),
                "client": _network_stats(events, "net.client_stats"),
            },
            # `docs/06` §7.2: "Report median, p95, and the component breakdown
            # — a single number hides which of lines 2/6/7 moved." Rebuilt from
            # the `latency.turn` events rather than read off a live object, so
            # a trace file on disk carries the same summary as the process did.
            "latency": _latency_summary(events),
            "ladder": _ladder_summary(events),
            "trace_path": str(self.path) if self.path else None,
        }


def _latency_summary(events: list[dict]) -> dict[str, Any] | None:
    """§2.2's nine lines over the session (`server/latency.py`).

    Imported inside the function rather than at module scope: `server/
    latency.py` imports `agent/`, and `Trace` is constructed by anything that
    opens a session — including the hermetic tests, which must not be made to
    pull the diagnostic core in behind a log file.
    """
    from server import latency as latency_module

    return latency_module.summarise(events)


def _ladder_summary(events: list[dict]) -> dict[str, Any]:
    """§2.4's tier changes, from the `latency.ladder` events."""
    changes = [e for e in events if e["type"] == "latency.ladder"]
    return {
        "changes": len(changes),
        "fired": sum(1 for e in changes if e.get("direction") == "fired"),
        "recovered": sum(1 for e in changes if e.get("direction") == "recovered"),
        "max_tier": max((int(e.get("tier") or 0) for e in changes), default=0),
        "final_tier": int(changes[-1].get("tier") or 0) if changes else 0,
        "events": [
            {
                "direction": e.get("direction"),
                "tier": e.get("tier"),
                "previous_tier": e.get("previous_tier"),
                "reason": e.get("reason"),
                "p95_ms": e.get("p95_ms"),
            }
            for e in changes
        ],
    }


def _distribution(values: list[float]) -> dict[str, float] | None:
    numbers = [float(v) for v in values if v is not None]
    if not numbers:
        return None
    numbers.sort()
    index = min(len(numbers) - 1, int(round(0.95 * (len(numbers) - 1))))
    return {
        "n": len(numbers),
        "min": round(numbers[0], 3),
        "median": round(statistics.median(numbers), 3),
        "p95": round(numbers[index], 3),
        "max": round(numbers[-1], 3),
    }


def _network_stats(events: list[dict], event_type: str) -> dict[str, Any]:
    """RTT/jitter/loss, as a distribution rather than a last reading.

    Loss is reported as the final cumulative counters rather than as a
    distribution: `packetsLost` only ever climbs, so its median says nothing.
    """
    samples = [e for e in events if e["type"] == event_type]
    if not samples:
        return {"samples": 0}
    last = samples[-1]
    received = last.get("packets_received")
    lost = last.get("packets_lost")
    loss_pct = None
    if isinstance(received, (int, float)) and isinstance(lost, (int, float)):
        total = received + lost
        if total > 0:
            loss_pct = round(100.0 * lost / total, 4)
    return {
        "samples": len(samples),
        "rtt_ms": _distribution([e.get("rtt_ms") for e in samples]),
        "jitter_ms": _distribution([e.get("jitter_ms") for e in samples]),
        "packets_received": received,
        "packets_lost": lost,
        "loss_pct": loss_pct,
        "playout_delay_ms": _distribution([e.get("playout_delay_ms") for e in samples]),
    }
