"""The §5.2 handoff payload, rendered from `DiagnosticState` (`docs/06` §5.2).

§5.2 and `docs/07` D-17 both make the same point, and it is the reason this
module produces a dict rather than sending a message anywhere:

> Because the human joins the same session (§5.3), the payload is **not a
> message sent somewhere — it is the panel the joining human sees**, rendered
> from `DiagnosticState` at the moment they are admitted, and live thereafter.

So this is a projection, like `core_bridge.project_state` is a projection, and
it is rebuilt on every request. There is no handoff record to keep in sync with
the session, because the session *is* the record. The same shape serves the
ticket and callback cases unchanged, which is the other half of D-17's claim.

**The target it is written against**: *the human never asks the user a question
the agent already asked.* Everything in the §5.2 layout earns its place against
that sentence — the ledger in order, the answers with their readings, the
hypothesis with what is and is not ruled out, and `verbatim_symptom` carried
word for word because "a paraphrase loses the detail that turned out to matter".

**Two things §5.2 forbids the payload from containing**, and which are enforced
here rather than hoped for (:func:`_withhold`):

1. a declaration that the hardware is faulty — `01` §4: the agent may
   *suspect*, a human decides;
2. any warranty, returns-window or policy statement — `03` EVAL-29: all
   `Unknown` and none of it ours to state.

Both scan the free text the payload carries out of the core (hypotheses,
rationales, summaries). What is removed is listed in ``withheld`` rather than
silently dropped, because a human reading the panel should be able to see that
something was taken out and why.

**What this module reads and does not own.** `agent/` is untouched: every field
here comes off `DiagnosticState`, `eval.ontology` or the corpus manifest. The
citation resolver reads `data/processed/chunks.jsonl` and `sources.json` for
*metadata only* — chunk id, doc code, page range, tier, retrieval date — which
is exactly the row §5.2 asks for under "WHAT WAS SAID, AND ON WHAT AUTHORITY".
Chunk bodies are not loaded and not rendered: the panel is an audit trail, not
a second reader for the corpus.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from agent.state import DiagnosticState
from eval import ontology
from server import consent as consent_module

_REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = _REPO_ROOT / "data" / "processed" / "chunks.jsonl"
SOURCES_PATH = _REPO_ROOT / "data" / "processed" / "sources.json"

#: What the agent is. Not a semver: the thing a human reading a handoff six
#: weeks later needs is "which build said this", and the milestone branch plus
#: the corpus date answers that better than a number nobody bumps.
AGENT_VERSION = "rove-agent/phase4-scaffolding"

# --------------------------------------------------------------------------
# §5.2's two prohibitions
# --------------------------------------------------------------------------

#: A declaration that the hardware is faulty. Note what is *not* here: "card at
#: end of life", "suspect the card slot", "consistent with a failing card" —
#: `01` §4 permits suspicion and these patterns are written to let it through.
#: What they catch is the declarative form, which is the human's to make.
_FAULT_DECLARATION = re.compile(
    r"\b("
    r"(?:is|are|was|were)\s+(?:definitely\s+|clearly\s+|certainly\s+)?"
    r"(?:faulty|defective|broken|dead|failed)"
    r"|hardware\s+(?:is\s+)?(?:faulty|defective|failure|fault)\b"
    r"|needs?\s+(?:to\s+be\s+)?replac(?:ed|ing)"
    r"|the\s+(?:camera|unit|device)\s+has\s+failed"
    r")",
    re.IGNORECASE,
)

#: Warranty, returns and policy. `03` EVAL-29: all `Unknown`, and none of it
#: ours to state — including in a payload a human will read as ours.
_POLICY_STATEMENT = re.compile(
    r"\b(warrant(?:y|ies|ed)|return(?:s|ed)?\s+window|returns\s+polic\w*|rma\b"
    r"|refund\w*|replacement\s+polic\w*|covered\s+under)\b",
    re.IGNORECASE,
)

#: Why a span was withheld, by the rule that caught it.
_FAULT_REASON = (
    "§5.2: the agent may suspect, a human decides — a fault declaration is "
    "not the agent's to make (01 §4)"
)
_POLICY_REASON = (
    "§5.2: no warranty, returns-window or policy statement — all Unknown and "
    "none of it ours to state (03 EVAL-29)"
)

#: What replaces a withheld span. Visible on purpose: a reader should see that
#: something was taken out.
REDACTION_MARKER = "[withheld — §5.2]"


def _withhold(text: str, *, where: str, withheld: list[dict[str, str]]) -> str:
    """Strip the two forbidden kinds of statement, recording what went."""
    if not text:
        return text
    out = text
    for pattern, reason in ((_FAULT_DECLARATION, _FAULT_REASON), (_POLICY_STATEMENT, _POLICY_REASON)):
        for match in pattern.finditer(text):
            withheld.append({"field": where, "span": match.group(0), "reason": reason})
        out = pattern.sub(REDACTION_MARKER, out)
    return out


# --------------------------------------------------------------------------
# Citations (§5.2 "WHAT WAS SAID, AND ON WHAT AUTHORITY")
# --------------------------------------------------------------------------


class _CorpusManifest:
    """chunk_id → the metadata row §5.2 wants beside a spoken claim.

    Loaded once per process and held, because the panel is rebuilt on every
    poll and re-reading a 161-chunk manifest per poll would be silly. Absent
    files are not an error: a server running without the processed corpus
    still renders the panel, with `UNRESOLVED` where the row would be, which
    is more honest than an empty citations list that reads like "no claims".
    """

    def __init__(self) -> None:
        self._chunks: dict[str, dict[str, Any]] | None = None
        self._docs: dict[str, dict[str, Any]] = {}
        self._corpus_date = ""

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._chunks is not None:
            return self._chunks
        chunks: dict[str, dict[str, Any]] = {}
        try:
            with CHUNKS_PATH.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    # Metadata only. The body is deliberately not kept.
                    chunks[row["chunk_id"]] = {
                        "doc_code": row.get("doc_code", ""),
                        "page_range": row.get("page_range", ""),
                        "section": row.get("section", ""),
                        "tier": row.get("tier"),
                        "retrieval_date": row.get("retrieval_date", ""),
                        "verification_status": row.get("verification_status", ""),
                        "speakable": bool(row.get("speakable")),
                        "provenance": row.get("provenance", ""),
                    }
        except (OSError, ValueError, KeyError):
            chunks = {}
        try:
            manifest = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
            self._corpus_date = str(manifest.get("retrieval_date", ""))
            for source in manifest.get("sources", []):
                self._docs[source.get("doc_code", "")] = {
                    "title": source.get("title", ""),
                    "provenance": source.get("provenance", ""),
                    "source_url": source.get("source_url"),
                    "attested_by": source.get("attested_by"),
                }
        except (OSError, ValueError):
            pass
        self._chunks = chunks
        return chunks

    @property
    def corpus_snapshot_date(self) -> str:
        self._load()
        return self._corpus_date or "unknown"

    def cite(self, chunk_id: str) -> dict[str, Any]:
        """One citation row: the chunk, the document it came from, its tier."""
        chunks = self._load()
        row = chunks.get(chunk_id)
        if row is None:
            return {
                "chunk_id": chunk_id,
                "doc_code": "",
                "title": "UNRESOLVED — not in this corpus snapshot",
                "page": "",
                "tier": None,
                "retrieval_date": "",
                "verification_status": "",
                "resolved": False,
            }
        doc = self._docs.get(row["doc_code"], {})
        return {
            "chunk_id": chunk_id,
            "doc_code": row["doc_code"],
            "title": doc.get("title", ""),
            "page": row["page_range"],
            "section": row["section"],
            "tier": row["tier"],
            "retrieval_date": row["retrieval_date"],
            "verification_status": row["verification_status"],
            "speakable": row["speakable"],
            "provenance": row["provenance"] or doc.get("provenance", ""),
            "source_url": doc.get("source_url"),
            "resolved": True,
        }


MANIFEST = _CorpusManifest()


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------


def _device_block(state: DiagnosticState, withheld: list[dict[str, str]]) -> dict[str, Any]:
    """§5.2 DEVICE — model, confidence *and why*, firmware, card, power.

    "firmware — user read '…' | not obtained ← never agent-stated" is the row
    §5.2 annotates most sharply, so the source of the value travels with it
    rather than being implied by its presence.
    """
    device = state.device
    why = [
        f"{signal.signal}={signal.value!r}"
        for signal in device.evidence
        if getattr(signal, "applied", False)
    ] or [f"{signal.signal}={signal.value!r}" for signal in device.evidence]
    firmware_known = device.firmware_version not in ("", "unknown", None)
    return {
        "model": device.reported_model,
        "hw_revision": device.hw_revision,
        "confidence": device.confidence,
        "why": "; ".join(why) or "no model signal yet",
        "candidates": list(device.candidates),
        "firmware": {
            "value": device.firmware_version if firmware_known else "",
            # §5.2: never agent-stated. If it is here, the caller read it out.
            "source": "user read" if firmware_known else "not obtained",
        },
        "card": dict(device.card),
        "power": dict(device.power),
    }


def _ledger_block(state: DiagnosticState) -> list[dict[str, Any]]:
    """§5.2 ALREADY TRIED — "the ledger, in order", numbered as §5.2 numbers it."""
    rows = []
    for index, attempt in enumerate(state.ledger.attempted, start=1):
        step = ontology.STEPS.get(attempt.step_id)
        rows.append(
            {
                "n": index,
                "step_id": attempt.step_id,
                "family": attempt.step_family,
                "description": step.description if step else "",
                "count": attempt.count,
                "source": attempt.source,
                "outcome": attempt.outcome,
                "turn": attempt.turn,
                "verbatim": attempt.verbatim,
                "destructive": bool(step.destructive) if step else False,
                "blocking": attempt.blocking,
            }
        )
    return rows


def _answers_block(state: DiagnosticState) -> list[dict[str, Any]]:
    """What we were told, so the human does not ask it again (§3.3, §5.2)."""
    rows = []
    for answer in state.answers.values():
        step = ontology.STEPS.get(answer.step_id)
        rows.append(
            {
                "step_id": answer.step_id,
                "question": step.description if step else "",
                "reading": answer.reading,
                "verbatim": answer.verbatim,
                "turn": answer.turn,
                "source": answer.source,
                "modality": answer.modality,
            }
        )
    rows.sort(key=lambda row: row["turn"])
    return rows


def _hypothesis_block(
    state: DiagnosticState, withheld: list[dict[str, str]]
) -> dict[str, Any]:
    """§5.2 AGENT'S HYPOTHESIS — top, ruled out *and why*, and not ruled out."""
    top = state.problem.top_hypothesis
    ruled_out = [
        {
            "cause_id": entry.cause_id,
            "text": _withhold(entry.text, where="ruled_out.text", withheld=withheld),
            "reason": _withhold(entry.reason, where="ruled_out.reason", withheld=withheld),
            "turn": entry.turn,
        }
        for entry in state.problem.ruled_out
    ]
    eliminated = {entry.cause_id for entry in state.problem.ruled_out}
    not_ruled_out = [
        {
            "cause_id": hypothesis.cause_id,
            "text": _withhold(
                hypothesis.text, where="hypothesis.text", withheld=withheld
            ),
            "confidence": hypothesis.confidence,
            "rank": hypothesis.rank,
            "turns_held": hypothesis.turns_held,
        }
        for hypothesis in state.problem.hypothesis_stack
        if hypothesis.cause_id not in eliminated
        and (top is None or hypothesis.cause_id != top.cause_id)
    ]
    return {
        "top": (
            {
                "cause_id": top.cause_id,
                "text": _withhold(top.text, where="hypothesis.top", withheld=withheld),
                "confidence": top.confidence,
                "turns_held": top.turns_held,
                "chunk_ids": list(top.chunk_ids),
            }
            if top is not None
            else None
        ),
        "ruled_out": ruled_out,
        "not_ruled_out": not_ruled_out,
    }


def _authority_block(state: DiagnosticState) -> list[dict[str, Any]]:
    """§5.2 — "spoken claims + chunk_ids + doc_code + page + tier + retrieval date"."""
    rows = []
    for claim in state.clearance.spoken_claims:
        rows.append(
            {
                "claim": claim.claim,
                "turn": claim.turn,
                "tier": claim.tier,
                "retrieval_date": claim.retrieval_date,
                "citations": [MANIFEST.cite(chunk_id) for chunk_id in claim.chunk_ids],
                # A spoken claim with no chunk behind it is the thing §4.5's
                # output guard exists to prevent, so it is surfaced rather
                # than rendered as an empty list.
                "uncited": not claim.chunk_ids,
            }
        )
    return rows


def _gates_block(state: DiagnosticState) -> list[dict[str, Any]]:
    """Every destructive-step gate decision (§6.4). Structured, not inferred."""
    return [gate.as_harness_gate() for gate in state.gates]


def build_handoff(
    session: Any,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """The §5.2 panel for one live session.

    Args:
        session: A `server.core_bridge.Session`.
        now: Clock, for tests.

    Returns:
        The payload, in §5.2's order, plus `withheld` listing anything the two
        §5.2 prohibitions removed.
    """
    stamp = time.time() if now is None else now
    state: DiagnosticState = session.state
    withheld: list[dict[str, str]] = []
    consent_state = session.consent

    symptom = state.problem.verbatim_symptom
    first_caller_line = next(
        (line for line in session.transcript if line.role == "caller"), None
    )

    payload = {
        # -- header --------------------------------------------------------
        "session_id": session.session_id,
        "room": session.room,
        "started_at": session.created_at,
        "duration_s": round(stamp - session.created_at, 1),
        "agent_version": AGENT_VERSION,
        "corpus_snapshot_date": MANIFEST.corpus_snapshot_date,
        "turn": state.turn,
        "fsm_state": state.state.value,
        # §5.3: the agent stops proposing steps once a human is in the room.
        "agent_mode": session.agent_mode,
        # Projected, not the `Participant` objects themselves. Every consumer of
        # this payload serialises it: the console socket with `json.dumps` (which
        # a dataclass stops dead), the corpus with `json.dumps(default=str)`
        # (which would file a Python `repr` where the rows belong), and FastAPI's
        # encoder (which copes, and so would have hidden both).
        "participants": [participant.as_dict() for participant in session.participants],
        # -- the caller's own words ----------------------------------------
        "user_said": {
            # Word for word. §5.2: "a paraphrase loses the detail that turned
            # out to matter". Not passed through `_withhold`: this is the
            # caller speaking, not the agent, and editing it would defeat the
            # field's only purpose.
            "verbatim": symptom or (first_caller_line.text if first_caller_line else ""),
            "turn": 1,
            "modality": first_caller_line.modality if first_caller_line else "",
        },
        "symptom_summary": _withhold(
            state.problem.top_hypothesis.text if state.problem.top_hypothesis else symptom,
            where="symptom_summary",
            withheld=withheld,
        ),
        "category": state.problem.category or "",
        "taxonomy_id": state.problem.taxonomy_id or ("KNOWN_GAP" if state.problem.known_gap else "NO_MATCH"),
        "taxonomy_status": state.entry_status,
        "known_gap": state.problem.known_gap or "",
        # -- the §5.2 blocks ------------------------------------------------
        "device": _device_block(state, withheld),
        "context": {
            "change_event": state.problem.change_event or "",
            "environment": state.safety.driving,
            "footage_at_stake": state.safety.footage_at_stake,
            "firmware_update_in_progress": state.firmware_update_in_progress,
        },
        "already_tried": _ledger_block(state),
        "already_answered": _answers_block(state),
        "hypothesis": _hypothesis_block(state, withheld),
        "authority": _authority_block(state),
        "gates": _gates_block(state),
        "escalation": {
            "triggered": state.escalation.triggered,
            "reason_code": state.escalation.reason_code,
            "reason": _withhold(
                state.escalation.reason, where="escalation.reason", withheld=withheld
            ),
            "at_turn": state.escalation.at_turn,
            "safety_flags": {
                "hazard": list(state.safety.hazard_flags),
                "footage": state.safety.footage_at_stake,
                "driving": state.safety.driving,
            },
            # §5.2's "recording + consent status" row, and the pointer it says
            # is subject to the §6.3 retention policy — so it is only a pointer
            # when there is something to point at.
            "recording_and_consent": consent_state.as_handoff_line(),
            "consent": consent_state.as_dict(),
            "transcript_pointer": (
                f"pilot_sessions/{session.session_id}"
                if consent_state.may_retain(consent_module.RETENTION_EVALUATION)
                else "not retained (§6.3 — no storage consent)"
            ),
        },
        "withheld": withheld,
    }
    return payload
