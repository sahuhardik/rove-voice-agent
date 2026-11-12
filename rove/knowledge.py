"""Loads the knowledge packs and decides which ones the agent reads."""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge"
PACKS = KNOWLEDGE / "packs"


@functools.lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads((KNOWLEDGE / "registry.json").read_text(encoding="utf-8"))["models"]


def model_ids() -> set[str]:
    return set(registry())


@functools.lru_cache(maxsize=None)
def pack(name: str) -> str:
    return (PACKS / f"{name}.md").read_text(encoding="utf-8")


def model_from_text(text: str) -> str | None:
    """A model id if the customer named one unambiguously, longest alias first ("dual pro" before "dual")."""
    t = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    best: tuple[int, str] | None = None
    for model, info in registry().items():
        for alias in info["aliases"] + [model.lower().replace("-", " ")]:
            a = " " + re.sub(r"[^a-z0-9]+", " ", alias.lower()).strip() + " "
            if a in t and (best is None or len(a) > best[0]):
                best = (len(a), model)
    return best[1] if best else None


def catalogue() -> str:
    return "\n".join(f"- {mid}: {info['display_name']}" for mid, info in registry().items())


def context_for(model: str) -> str:
    """What the agent reads this turn: the ID guide and general pack always; the model's pack once known."""
    parts = [pack("identify"), pack("general")]
    if model in registry():
        parts.append(pack(model))
        note = registry()[model].get("source_note")
        if note:
            parts.append(f"(Note on this model's pack: {note})")
    return "\n\n---\n\n".join(parts)


_STOP = set("the a an and or is it my i to of in on for with that this was be at not no yes but have has had do does did can you your me just so what when how why are camera dash cam dashcam rove".split())


def _sections(md: str, level: str) -> list[tuple[str, str]]:
    parts = re.split(rf"(?m)^({level} .*)$", md)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def compact_context(model: str, said: str, per_section: int = 1600, playbook: int = 3, howto: int = 2) -> str:
    """A small slice of the knowledge for slow (local) models: identification, key facts, and the
    playbook / how-to sections that best match what the customer has said. ~2k tokens."""
    if model not in registry():
        return pack("identify")
    md = pack(model)
    words = {w for w in re.findall(r"[a-z0-9]+", said.lower()) if w not in _STOP and len(w) > 2}

    def score(title: str, body: str) -> int:
        t = set(re.findall(r"[a-z0-9]+", title.lower()))
        b = set(re.findall(r"[a-z0-9]+", body.lower()))
        return 3 * len(words & t) + len(words & b)

    head = md.split("## How-to procedures", 1)[0]
    howtos = _sections(md.split("## How-to procedures", 1)[1].split("## Troubleshooting playbook", 1)[0], "###") if "## How-to procedures" in md else []
    plays = _sections(md.split("## Troubleshooting playbook", 1)[1], "###") if "## Troubleshooting playbook" in md else []
    pick = lambda items, n: [t + b[:per_section] for t, b in sorted(items, key=lambda x: -score(*x))[:n] if score(t, b)]
    out = [head.strip()[:3500], "## Most relevant troubleshooting", *pick(plays, playbook), "## Most relevant how-to", *pick(howtos, howto)]
    note = registry()[model].get("source_note")
    if note:
        out.append(f"(Note on this model's pack: {note})")
    out.append("Support contact: help@rovedashcam.com")
    return "\n\n".join(out)
