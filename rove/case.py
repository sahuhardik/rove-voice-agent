"""The case file: what the agent knows about this customer's problem.

The model updates it every turn; code reads it to enforce safety and to build
the handoff for a human. It is also what the UI shows.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LIST_FIELDS = ("tried", "hypotheses", "facts")


@dataclass
class Case:
    model: str = "unknown"                 # registry id, e.g. "R2-4K-USB-C", or "unknown"
    model_confidence: str = "unknown"      # confirmed | probable | unknown
    symptom: str = ""                      # the problem in the customer's words
    changed_recently: str = ""             # update, new card, new phone, install ...
    facts: list[str] = field(default_factory=list)       # everything the customer has told us
    tried: list[dict[str, str]] = field(default_factory=list)  # {"step": ..., "result": ...}
    hypotheses: list[str] = field(default_factory=list)  # ranked, most likely first
    next_test: str = ""                    # what the current question/step is meant to tell apart
    status: str = "open"                   # open | resolved | escalated | answered
    # Set by code, not the model:
    flags: list[str] = field(default_factory=list)
    footage_at_risk: bool = False
    driving: bool = False
    confirmed_destructive: bool = False
    awaiting_destructive_confirmation: bool = False
    turns: int = 0

    MODEL_WRITABLE = ("model", "model_confidence", "symptom", "changed_recently", "facts",
                      "tried", "hypotheses", "next_test", "status")

    def apply(self, update: dict[str, Any], known_models: set[str]) -> None:
        """Merge the model's update. Unknown keys and bad values are ignored."""
        for key, value in (update or {}).items():
            if key not in self.MODEL_WRITABLE or value is None:
                continue
            if key == "model":
                value = str(value).strip()
                if value not in known_models and value != "unknown":
                    continue
            if key == "model_confidence" and value not in ("confirmed", "probable", "unknown"):
                continue
            if key == "status" and value not in ("open", "resolved", "escalated", "answered"):
                continue
            if key == "facts":
                new = [str(v) for v in (value if isinstance(value, list) else [value]) if str(v).strip()]
                self.facts += [f for f in new if f not in self.facts]
                continue
            if key == "tried":
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if isinstance(item, dict) and item.get("step"):
                        entry = {"step": str(item["step"]), "result": str(item.get("result", "pending"))}
                        # Update the result of a step already listed, else add it.
                        for existing in self.tried:
                            if existing["step"].lower() == entry["step"].lower():
                                existing["result"] = entry["result"]
                                break
                        else:
                            self.tried.append(entry)
                continue
            if key == "hypotheses":
                if isinstance(value, list):
                    self.hypotheses = [str(v) for v in value][:4]
                continue
            setattr(self, key, str(value))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def handoff_summary(self) -> str:
        tried = "; ".join(f"{t['step']} → {t['result']}" for t in self.tried) or "nothing yet"
        return (
            f"Model: {self.model} ({self.model_confidence}). Problem: {self.symptom or 'not stated'}. "
            f"Changed recently: {self.changed_recently or 'nothing mentioned'}. Tried: {tried}. "
            f"Current thinking: {', '.join(self.hypotheses) or 'none yet'}. "
            f"Flags: {', '.join(self.flags) or 'none'}. Facts: {'; '.join(self.facts) or 'none'}."
        )
