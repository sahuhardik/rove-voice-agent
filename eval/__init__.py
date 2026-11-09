"""Phase 0 evaluation harness for the Rove voice troubleshooting agent.

Scope (docs/06 §9.1, Phase 0): Harness A (docs/06 §7.3), the canonical step
ontology (docs/06 §3.6), the taxonomy-ID -> candidate-step map (docs/02), and a
deliberately dumb rule-based baseline to establish a floor score.

Stdlib only. No third-party dependencies, no AWS, no network. No application
code lives in this package -- it exists to measure one, and is deliberately
runnable before any agent exists.
"""

__all__ = ["ontology", "harness", "baseline", "scenarios"]
