"""Milestone 3 — the Phase 1 text-only diagnostic core (`docs/06` §9.1).

Five modules, in dependency order:

| module | what it owns |
| --- | --- |
| `state.py` | the typed `DiagnosticState`: 13 FSM states, the attempted-step ledger, the hypothesis and ruled-out lists, model identification with CONFIRMED / PROBABLE / UNKNOWN |
| `retrieval.py` | in-process retrieval over `data/processed/chunks.jsonl` — model-first metadata filtering, Tier-1 speakable only, stdlib BM25, top 3 with chunk ids |
| `policy.py` | the `docs/06` §3.5 next-step policy: no-repeat with family-level blocking, the destructive gate, the FW-01 interlock, the §6 safety stops |
| `llm.py` | a thin `boto3` Bedrock wrapper: Nova Micro for classification, Nova Pro for turn reasoning, strict JSON, rule-based fallback |
| `core.py` | the text-only diagnostic turn: utterance + state → response text, updated state, citations, through the output guard |

Dependencies: Python stdlib plus `boto3`. No voice, no Postgres, no pgvector —
those are `docs/06` §9.1 Phases 2b/3 and §8.5 respectively.

This package reads `eval.ontology` (the canonical step ontology and the
taxonomy → candidate-step map, Milestone 1) and `ingest.metadata` (the
`docs/05` verification statuses and the model vocabulary, Milestone 2) rather
than restating either. A second copy of the ontology would be a second thing to
drift.
"""

__all__ = ["state", "retrieval", "policy", "llm", "core"]
