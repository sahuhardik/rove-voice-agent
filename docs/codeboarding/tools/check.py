#!/usr/bin/env python3
"""Verify docs/codeboarding against the repo. Exit 0 only if every check passes.

    .venv/bin/python docs/codeboarding/tools/check.py

No Mermaid parser (mermaid-cli, mermaid.js) is installed on the machine that
produced this output, so the Mermaid check here is a strict *structural* lint
of the subset of the language these files use, not a full parse. It catches the
failures that break rendering in practice: undeclared edge endpoints, unquoted
or unbalanced labels, bad node ids, dangling `click` targets, unclosed fences.
Run `npx @mermaid-js/mermaid-cli -i <file>` where a parser is available.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
ROOT = OUT.parent.parent

ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NODE_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\["([^"\n]*)"\]\s*$')
EDGE_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:--\s+"([^"\n]*)"\s+-->|-->|-\.->)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$'
)
CLICK_RE = re.compile(r'^\s*click\s+([A-Za-z_][A-Za-z0-9_]*)\s+href\s+"([^"\n]*)"\s+"([^"\n]*)"\s*$')
PATH_RE = re.compile(
    r"`((?:agent|server|eval|ingest|client|support|scripts|data|docs)/[A-Za-z0-9_./*-]+)`"
)
SOURCE_ROOTS = ("agent/", "server/", "eval/", "ingest/", "client/src/", "support/", "scripts/")
SOURCE_EXT = (".py", ".js", ".jsx", ".mjs", ".sh", ".html", ".css")


def tracked_sources() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    keep = set()
    for p in out:
        if not p.startswith(SOURCE_ROOTS) or not p.endswith(SOURCE_EXT):
            continue
        name = Path(p).name
        if name.startswith("test_") or name == "__init__.py" or "/testing-tls/" in p:
            continue
        keep.add(p)
    return keep


def find_symbol(path: Path, qualified: str) -> tuple[int, int] | None:
    """(start, end) line of a symbol, or None. .py via ast; others by text."""
    text = path.read_text()
    if path.suffix != ".py":
        short = qualified.split(".")[-1]
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(rf"\b{re.escape(short)}\b", line):
                return (i, i)
        return None
    tree = ast.parse(text)
    scope: list[ast.AST] = tree.body
    node = None
    for part in qualified.split("."):
        node = next(
            (n for n in scope
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part),
            None,
        )
        if node is None:
            return None
        scope = getattr(node, "body", [])
    return (node.lineno, node.end_lineno)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.checked: dict[str, int] = {}

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def count(self, key: str, n: int = 1) -> None:
        self.checked[key] = self.checked.get(key, 0) + n


def walk(components: list[dict]):
    for c in components:
        yield c
        yield from walk(c.get("components", []))


def check_analysis(rep: Report) -> tuple[list[dict], set[str]]:
    path = OUT / "analysis.json"
    if not path.exists():
        rep.err("analysis.json is missing")
        return [], set()
    data = json.loads(path.read_text())
    for key in ("metadata", "description", "components", "components_relations"):
        if key not in data:
            rep.err(f"analysis.json: missing top-level key {key!r}")
    comps = data.get("components", [])
    covered: set[str] = set()
    ids: set[str] = set()
    for c in walk(comps):
        for key in ("component_id", "name", "description", "key_entities", "file_methods"):
            if key not in c:
                rep.err(f"component {c.get('name')!r}: missing {key!r}")
        if c["component_id"] in ids:
            rep.err(f"duplicate component_id {c['component_id']}")
        ids.add(c["component_id"])
        if not c.get("description", "").strip():
            rep.err(f"component {c['name']!r}: empty description")
        rep.count("components")
        for fm in c.get("file_methods", []):
            rel = fm["file_path"]
            fp = ROOT / rel
            covered.add(rel)
            if not fp.is_file():
                rep.err(f"{c['name']}: file does not exist: {rel}")
                continue
            rep.count("files")
            for m in fm.get("methods", []):
                span = find_symbol(fp, m["qualified_name"])
                rep.count("symbols")
                if span is None:
                    rep.err(f"{c['name']}: {rel} has no symbol {m['qualified_name']}")
                elif fp.suffix == ".py" and (m["start_line"], m["end_line"]) != span:
                    rep.err(
                        f"{c['name']}: {rel}:{m['qualified_name']} lines "
                        f"{m['start_line']}-{m['end_line']} != actual {span[0]}-{span[1]}"
                    )
    names_by_level: dict[int, set[str]] = {}

    def check_relations(level_comps: list[dict], relations: list[dict], where: str) -> None:
        names = {c["name"] for c in level_comps}
        seen = set()
        for r in relations:
            for end in ("src_name", "dst_name"):
                if r[end] not in names:
                    rep.err(f"{where}: relation endpoint {r[end]!r} is not a component here")
            if not r.get("relation", "").strip():
                rep.err(f"{where}: relation {r['src_name']}->{r['dst_name']} has no label")
            if not r.get("evidence"):
                rep.err(f"{where}: relation {r['src_name']}->{r['dst_name']} cites no evidence")
            for ev in r.get("evidence", []):
                f, _, sym = ev.partition(":")
                if not (ROOT / f).is_file():
                    rep.err(f"{where}: evidence file missing: {ev}")
                elif sym and find_symbol(ROOT / f, sym) is None:
                    rep.err(f"{where}: evidence symbol missing: {ev}")
            key = (r["src_name"], r["dst_name"], r["relation"])
            if key in seen:
                rep.err(f"{where}: duplicate relation {key}")
            seen.add(key)
            rep.count("relations")
        names_by_level[len(names_by_level)] = names

    check_relations(comps, data.get("components_relations", []), "top level")
    for c in walk(comps):
        if c.get("components"):
            check_relations(c["components"], c.get("components_relations", []), c["name"])
    return comps, covered


def check_coverage(rep: Report, covered: set[str]) -> None:
    for p in sorted(tracked_sources() - covered):
        rep.err(f"source file not assigned to any component: {p}")
    rep.count("source files in repo", len(tracked_sources()))


def lint_mermaid(rep: Report, md: Path, block: list[str], start: int) -> None:
    where = f"{md.name}:{start}"
    if not block or not re.match(r"^(graph|flowchart) (LR|TD|TB|RL|BT)\s*$", block[0].strip()):
        rep.err(f"{where}: mermaid block must start with 'graph LR' / 'flowchart TD'")
        return
    declared: dict[str, str] = {}
    edges: list[tuple[int, str, str]] = []
    clicks: list[tuple[int, str, str]] = []
    for off, line in enumerate(block[1:], 1):
        if not line.strip() or line.strip().startswith("%%"):
            continue
        ln = f"{where}+{off}"
        if (m := NODE_RE.match(line)):
            if m[1] in declared:
                rep.err(f"{ln}: node {m[1]} declared twice")
            declared[m[1]] = m[2]
            if not m[2].strip():
                rep.err(f"{ln}: node {m[1]} has an empty label")
        elif (m := EDGE_RE.match(line)):
            edges.append((off, m[1], m[3]))
        elif (m := CLICK_RE.match(line)):
            clicks.append((off, m[1], m[2]))
        else:
            rep.err(f"{ln}: line is not a node, edge or click statement: {line.strip()[:70]}")
    for off, a, b in edges:
        for n in (a, b):
            if n not in declared:
                rep.err(f"{where}+{off}: edge endpoint {n} is not declared")
    for off, n, href in clicks:
        if n not in declared:
            rep.err(f"{where}+{off}: click target {n} is not declared")
        if not (md.parent / href).is_file():
            rep.err(f"{where}+{off}: click href {href} does not exist")
    for n in declared:
        if not ID_RE.match(n):
            rep.err(f"{where}: bad node id {n}")
    rep.count("mermaid edges", len(edges))
    rep.count("mermaid diagrams")


def check_markdown(rep: Report) -> None:
    files = sorted(OUT.glob("*.md"))
    if not (OUT / "README.md").exists() or not (OUT / "overview.md").exists():
        rep.err("README.md and overview.md are both required")
    for md in files:
        lines = md.read_text().splitlines()
        in_fence, fence_lang, buf, start = False, "", [], 0
        for i, line in enumerate(lines, 1):
            if line.startswith("```"):
                if not in_fence:
                    in_fence, fence_lang, buf, start = True, line[3:].strip(), [], i
                else:
                    if fence_lang == "mermaid":
                        lint_mermaid(rep, md, buf, start)
                    in_fence = False
            elif in_fence:
                buf.append(line)
        if in_fence:
            rep.err(f"{md.name}:{start}: unclosed code fence")
        text = md.read_text()
        for m in re.finditer(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", text):
            if not (md.parent / m[1]).is_file():
                rep.err(f"{md.name}: link target missing: {m[1]}")
        for m in PATH_RE.finditer(text):
            p = m[1].rstrip(".")
            if "*" in p:
                if not list(ROOT.glob(p)):
                    rep.err(f"{md.name}: glob matches nothing: {p}")
            elif not (ROOT / p).exists():
                rep.err(f"{md.name}: referenced path does not exist: {p}")
            rep.count("path references")
        rep.count("markdown files")


def main() -> int:
    rep = Report()
    _, covered = check_analysis(rep)
    check_coverage(rep, covered)
    check_markdown(rep)
    for k, v in sorted(rep.checked.items()):
        print(f"  checked {v:>4}  {k}")
    if rep.errors:
        print(f"\nFAIL: {len(rep.errors)} problem(s)")
        for e in rep.errors:
            print("  -", e)
        return 1
    print("\nOK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
