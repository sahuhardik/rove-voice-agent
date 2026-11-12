"""Check a knowledge pack against its sources.

    python -m knowledge.factcheck            # all packs
    python -m knowledge.factcheck R3

Objective checks only, so a reviewer knows where to look:
* every number-bearing token in the pack (256GB, U3, 2.4GHz, 5 seconds, 12V ...)
  must appear in that pack's source text;
* no firmware version strings;
* every citation names a source that exists;
* the required sections are present.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLEAN, PACKS = HERE / "clean", HERE / "packs"

MODEL_SECTIONS = ["## How to recognise this model", "## Key facts", "## How-to procedures",
                  "## Troubleshooting playbook", "## Safety and data-loss warnings", "## Not covered by the sources"]
GENERAL_SECTIONS = ["## Troubleshooting articles", "## Safety and data-loss warnings"]

FIRMWARE_RE = re.compile(r"(?:firmware|version|\bfw\b)[^.\n]{0,20}\bv?\d+\.\d+(?:\.\d+)?\b|ROVE-R\d-[\w-]*\d{6,}", re.I)
#: A number with an optional unit glued or spaced on: "256GB", "2.4 GHz", "U3", "V30", "12V", "5 seconds".
NUMBER_RE = re.compile(r"\b(?:[UV]\d{1,2}|\d+(?:\.\d+)?\s?(?:GB|TB|MB|GHz|mAh|V|A|W|°[CF]|fps|P|K|mm|ft|feet|meters?|m|inch(?:es)?|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|%)?)\b", re.I)
CITE_RE = re.compile(r"\[(manual|help|official): ([^\]]+?)\]")
IGNORE_NUMBERS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"}  # list numbering, counts


@dataclass
class Report:
    name: str
    numbers_checked: int = 0
    unsupported_numbers: list[str] = field(default_factory=list)
    firmware_versions: list[str] = field(default_factory=list)
    bad_citations: list[str] = field(default_factory=list)
    citations: int = 0
    missing_sections: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.unsupported_numbers or self.firmware_versions or self.bad_citations or self.missing_sections)


UNIT_SYNONYMS = [
    (r"(\d)\s*-?\s*(?:feet|foot|ft)\b", r"\1ft"),
    (r"(\d)\s*-?\s*(?:minutes?|mins?)\b", r"\1min"),
    (r"(\d)\s*-?\s*(?:seconds?|secs?)\b", r"\1sec"),
    (r"(\d)\s*-?\s*(?:hours?|hrs?)\b", r"\1hr"),
    (r"(\d)\s*-?\s*(?:meters?|metres?)\b", r"\1m"),
    (r"(\d)\s*-?\s*(?:inch(?:es)?|\")", r"\1in"),
    (r"(\d)\s*-?\s*(?:days?)\b", r"\1day"),
]


def norm(s: str) -> str:
    """Lowercase, canonical units, no whitespace: "10 feet" and "10ft" both -> "10ft"."""
    s = s.lower()
    for pat, rep in UNIT_SYNONYMS:
        s = re.sub(pat, rep, s)
    # Glue a real unit to its number ("2.4 ghz" -> "2.4ghz"), but not an unrelated next word ("class 10 u3").
    s = re.sub(r"(\d)[\s-]+(?=(?:gb|tb|mb/s|mbps|mb|ghz|mah|fps|ft|min|sec|hr|day|in|m|v|a|p|k|°[cf])\b)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def sources_for(name: str) -> list[str]:
    if name in ("identify", "general"):
        return [p.stem for p in CLEAN.glob("*.txt")] if name == "identify" else ["general"]
    # Model packs may cite the Help Center for cross-model facts.
    return [name, "general"]


def check(name: str) -> Report:
    pack = (PACKS / f"{name}.md").read_text(encoding="utf-8")
    source = "\n".join((CLEAN / f"{s}.txt").read_text(encoding="utf-8") for s in sources_for(name))
    src_norm = norm(source)
    rep = Report(name)

    # The "not covered" section names facts the sources lack; numbers there are not claims.
    body = re.sub(r"## Not covered by the sources.*?(?=\n## |\Z)", "", pack, flags=re.S)
    body = re.sub(r"\[[^\]]*\]", "", body)  # citations are checked separately
    body = re.sub(r"^\s*\d+\.\s", "", body, flags=re.M)  # numbered-list markers
    body = re.sub(r"^#+ .*$", "", body, flags=re.M)  # headings restate the checklist
    seen = set()
    for m in NUMBER_RE.finditer(body):
        tok = m.group(0).strip()
        if tok in IGNORE_NUMBERS or tok in seen or not any(c.isdigit() for c in tok):
            continue
        seen.add(tok)
        rep.numbers_checked += 1
        n = norm(tok)
        digits = re.match(r"[uv]?\d+(?:\.\d+)?", n).group(0)
        unit = n[len(digits):]
        if unit:
            # With a unit, the number AND unit must appear together ("2.4ghz", "10ft").
            # Note src_norm has no spaces, so the unit must not run on into a longer word ("2m" in "2mp").
            supported = re.search(rf"(?<![\d.]){re.escape(n)}(?![a-z])", src_norm) is not None
        else:
            # A bare number: digits not glued to other digits ("265" in "H.265" counts).
            supported = re.search(rf"(?<!\d)(?<!\d\.){re.escape(digits)}(?![\d]|\.\d)", source.lower()) is not None
        if not supported:
            rep.unsupported_numbers.append(tok)

    rep.firmware_versions = [m.group(0) for m in FIRMWARE_RE.finditer(pack)]

    stems = {p.stem.lower() for p in (HERE.parents[0] / "data").rglob("*") if p.is_file()}
    for bracket in re.findall(r"\[((?:manual|help|official):[^\]]+)\]", pack):
        # One bracket may hold several: "[manual: a; help: b]" or "[manual: a manual: b]".
        for kind, ref in re.findall(r"(manual|help|official):\s*(.+?)(?=[;,]?\s*(?:manual|help|official):|$)", bracket):
            rep.citations += 1
            ref = ref.strip(" ;,")
            if ref.lower() not in stems:
                rep.bad_citations.append(f"{kind}: {ref}")
    rep.bad_citations = sorted(set(rep.bad_citations))

    required = [] if name == "identify" else GENERAL_SECTIONS if name == "general" else MODEL_SECTIONS
    rep.missing_sections = [s for s in required if s not in pack]
    return rep


def main(names: list[str]) -> list[Report]:
    names = names or sorted(p.stem for p in PACKS.glob("*.md"))
    reports = [check(n) for n in names]
    for r in reports:
        print(f"{r.name:16} {'OK  ' if r.ok else 'FAIL'} numbers={r.numbers_checked} "
              f"unsupported={r.unsupported_numbers} citations={r.citations} bad_cites={r.bad_citations} "
              f"firmware={r.firmware_versions} missing={r.missing_sections}")
    return reports


if __name__ == "__main__":
    sys.exit(0 if all(r.ok for r in main(sys.argv[1:])) else 1)
