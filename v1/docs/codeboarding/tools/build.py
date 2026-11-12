#!/usr/bin/env python3
"""Render docs/codeboarding from components.py.

    .venv/bin/python docs/codeboarding/tools/build.py

Writes analysis.json, overview.md and one <Component_Name>.md per top-level
component. README.md is hand-written and is not touched. Line numbers are
resolved from the code, never typed. Deterministic: same repo, same output
(the timestamp is the HEAD commit's date).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402  (reuses find_symbol so build and check cannot disagree)
import components  # noqa: E402

OUT, ROOT = check.OUT, check.ROOT
REPO_LINK = "../../"  # docs/codeboarding/ -> repo root


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def node_key(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def node_type(path: str, qualified: str, line: int) -> str:
    if not path.endswith(".py"):
        return "reference"
    text = (ROOT / path).read_text().splitlines()[line - 1].lstrip()
    if text.startswith("class "):
        return "class"
    return "method" if "." in qualified else "function"


def resolve_files(files: list[tuple[str, list[str]]]) -> list[dict]:
    """Merge duplicate paths, resolve every symbol to its real line span."""
    merged: dict[str, list[str]] = {}
    for path, symbols in files:
        merged.setdefault(path, [])
        merged[path].extend(s for s in symbols if s not in merged[path])
    out = []
    for path, symbols in merged.items():
        methods = []
        for sym in symbols:
            span = check.find_symbol(ROOT / path, sym)
            if span is None:
                raise SystemExit(f"build: {path} has no symbol {sym}")
            methods.append({
                "qualified_name": sym,
                "start_line": span[0],
                "end_line": span[1],
                "node_type": node_type(path, sym, span[0]),
            })
        out.append({"file_path": path, "methods": methods})
    return out


def key_entities(file_methods: list[dict], limit: int = 3) -> list[dict]:
    ents = []
    for fm in file_methods:
        if fm["methods"]:
            m = fm["methods"][0]
            ents.append({
                "qualified_name": m["qualified_name"],
                "reference_file": fm["file_path"],
                "reference_start_line": m["start_line"],
                "reference_end_line": m["end_line"],
            })
    return ents[:limit]


def relation_json(rel: tuple, ids: dict[str, str]) -> dict:
    src, dst, label, evidence = rel
    return {
        "relation": label,
        "src_name": src,
        "dst_name": dst,
        "src_id": ids[src],
        "dst_id": ids[dst],
        "is_static": False,
        "evidence": evidence,
    }


def build_model() -> list[dict]:
    top: list[dict] = []
    for i, comp in enumerate(components.COMPONENTS, 1):
        subs, sub_ids = [], {}
        for j, sub in enumerate(comp["subs"], 1):
            fm = resolve_files(sub["files"])
            sub_ids[sub["name"]] = f"{i}.{j}"
            subs.append({
                "component_id": f"{i}.{j}",
                "name": sub["name"],
                "description": sub["description"],
                "key_entities": key_entities(fm),
                "file_methods": fm,
                "can_expand": False,
                "components": [],
                "components_relations": [],
            })
        all_files = [f for s in comp["subs"] for f in s["files"]]
        fm = resolve_files(all_files)
        top.append({
            "component_id": str(i),
            "name": comp["name"],
            "description": comp["description"],
            "key_entities": key_entities(fm),
            "file_methods": fm,
            "can_expand": True,
            "components": subs,
            "components_relations": [relation_json(r, sub_ids) for r in comp["sub_relations"]],
        })
    return top


def mermaid(comps: list[dict], relations: list[dict], link: bool) -> str:
    lines = ["```mermaid", "graph LR"]
    for c in comps:
        lines.append(f'    {node_key(c["name"])}["{c["name"]}"]')
    for r in relations:
        lines.append(f'    {node_key(r["src_name"])} -- "{r["relation"]}" --> {node_key(r["dst_name"])}')
    if link:
        for c in comps:
            k = node_key(c["name"])
            lines.append(f'    click {k} href "{k}.md" "Details"')
    lines.append("```")
    return "\n".join(lines)


def details(c: dict) -> str:
    out = [f"### {c['name']}", "", c["description"], ""]
    if c["key_entities"]:
        out += ["**Related Classes/Methods**:", ""]
        for e in c["key_entities"]:
            f, a, b = e["reference_file"], e["reference_start_line"], e["reference_end_line"]
            out.append(f"- [`{f}`:`{e['qualified_name']}`]({REPO_LINK}{f}#L{a}-L{b})")
        out.append("")
    out += ["**Source Files:**", ""]
    for fm in c["file_methods"]:
        out.append(f"- [`{fm['file_path']}`]({REPO_LINK}{fm['file_path']})")
        for m in fm["methods"]:
            out.append(
                f"  - `{m['qualified_name']}` "
                f"([L{m['start_line']}-L{m['end_line']}]({REPO_LINK}{fm['file_path']}#L{m['start_line']}-L{m['end_line']}))"
                f" - {m['node_type']}"
            )
    out.append("")
    return "\n".join(out)


def relation_table(relations: list[dict]) -> str:
    rows = ["| From | To | Relation | Evidence |", "|---|---|---|---|"]
    for r in relations:
        ev = "<br>".join(f"`{e}`" for e in r["evidence"])
        rows.append(f"| {r['src_name']} | {r['dst_name']} | {r['relation']} | {ev} |")
    return "\n".join(rows)


def main() -> None:
    comps = build_model()
    ids = {c["name"]: c["component_id"] for c in comps}
    relations = [relation_json(r, ids) for r in components.RELATIONS]
    head = git("rev-parse", "HEAD")
    analysis = {
        "metadata": {
            "generated_at": git("log", "-1", "--format=%cI"),
            "repo_name": "rove-voice-agent",
            "source_commit": head,
            "depth_level": 2,
            "generator": "hand-authored in CodeBoarding analysis.json shape; NOT produced by the CodeBoarding engine",
            "engine_run": False,
            "engine_version_consulted": "codeboarding 0.15.3 (/home/ubuntu/codeboarding-upstream)",
            "description_step": "written by Claude Sonnet 5.5 from reading the code; see README.md",
            "relation_semantics": "is_static is false on every relation: they are cited imports and calls (see 'evidence'), not CFG analysis",
        },
        "description": components.DESCRIPTION,
        "components": comps,
        "components_relations": relations,
    }
    (OUT / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")

    overview = [
        "# Rove architecture (CodeBoarding format)",
        "",
        "> Hand-authored in CodeBoarding's output format, not produced by the engine. "
        "[README.md](README.md) says why and what was cross-checked against docs 06 and 08.",
        "",
        mermaid(comps, relations, link=True),
        "",
        "## Details",
        "",
        components.DESCRIPTION,
        "",
        "### Relations",
        "",
        relation_table(relations),
        "",
    ]
    overview += [details(c) + f"[Expand: nested diagram]({node_key(c['name'])}.md)\n" for c in comps]
    (OUT / "overview.md").write_text("\n".join(overview))

    for c in comps:
        page = [
            f"# {c['name']}",
            "",
            f"[Back to the overview](overview.md) · component {c['component_id']}",
            "",
            mermaid(c["components"], c["components_relations"], link=False),
            "",
            "## Details",
            "",
            c["description"],
            "",
            "### Relations",
            "",
            relation_table(c["components_relations"]),
            "",
        ]
        page += [details(s) for s in c["components"]]
        (OUT / f"{node_key(c['name'])}.md").write_text("\n".join(page))
    print(f"wrote analysis.json, overview.md and {len(comps)} component pages")


if __name__ == "__main__":
    main()
