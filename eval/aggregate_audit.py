"""Aggregate the independent audit files into rates.

    python -m eval.aggregate_audit <dir containing audit_*.jsonl>

Reads, from that directory:
  audit_replies_N.jsonl   claims and reply-level flags for the agent's real replies
  audit_pack_X.jsonl      claims and omissions for the knowledge packs
and prints verdict rates, severity, where wrong claims came from, and the worst offenders.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

VERDICTS = ["SUPPORTED", "PARTIAL", "UNSUPPORTED", "CONTRADICTED", "WRONG_MODEL", "BAD_CITATION"]


def load(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append({**json.loads(line), "_file": p.name})
            except json.JSONDecodeError:
                print(f"  skipped unreadable line {p.name}:{i}", file=sys.stderr)
    return rows


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


def report_claims(title: str, claims: list[dict]) -> None:
    n = len(claims)
    c = Counter(r.get("verdict") for r in claims)
    bad = [r for r in claims if r.get("verdict") != "SUPPORTED"]
    print(f"\n=== {title}: {n} claims audited")
    for v in VERDICTS:
        if c.get(v):
            print(f"  {v:13} {pct(c[v], n)}")
    # "Wrong" = would mislead on a point of fact; PARTIAL is mostly-right-but-embellished.
    wrong = c.get("UNSUPPORTED", 0) + c.get("CONTRADICTED", 0) + c.get("WRONG_MODEL", 0)
    print(f"  fully supported {pct(c.get('SUPPORTED', 0), n)}   |   unsupported+contradicted+wrong-model {pct(wrong, n)}"
          f"   |   partial {pct(c.get('PARTIAL', 0), n)}")
    sev = Counter(r.get("severity") for r in bad)
    print(f"  severity of the {len(bad)} non-supported: " + ", ".join(f"{k}={v}" for k, v in sev.most_common()))
    src = Counter(r.get("where_from") for r in bad if r.get("where_from"))
    if src:
        print("  where they came from: " + ", ".join(f"{k}={v}" for k, v in src.most_common()))


def main(d: Path) -> None:
    replies = load(sorted(d.glob("audit_replies_*.jsonl")))
    packs = load(sorted(d.glob("audit_pack_*.jsonl")))

    claims = [r for r in replies if r.get("type") == "claim"]
    flags = [r for r in replies if r.get("type") == "reply"]
    print(f"files: {sorted({r['_file'] for r in replies})}")
    report_claims("AGENT REPLIES (all)", claims)
    for sc_group, label in [("EVAL-0", "simple (01-09)"), ("EVAL-1", "contextual (10-19)"), ("EVAL-2", "complex+escalation (20-29)")]:
        sub = [r for r in claims if str(r.get("scenario", "")).startswith(sc_group)]
        if sub:
            s = Counter(r["verdict"] for r in sub)
            print(f"    {label}: supported {pct(s['SUPPORTED'], len(sub))}")

    if flags:
        sound_no = [r for r in flags if r.get("instruction_sound") == "NO"]
        applicable = [r for r in flags if r.get("instruction_sound") in ("YES", "NO")]
        ign = [r for r in flags if r.get("ignores_customer") == "YES"]
        unk = [r for r in flags if r.get("model_assumed") == "unknown"]
        print(f"\n  replies audited: {len(flags)}")
        print(f"  instructions not backed by the docs for that situation/model: {pct(len(sound_no), len(applicable))} of replies that give a step")
        print(f"  replies that ask for something the customer already said/did: {pct(len(ign), len(flags))}")
        print(f"  replies given while the camera model was still unknown: {pct(len(unk), len(flags))}")
        per_reply: dict[tuple, list[dict]] = {}
        for r in claims:
            per_reply.setdefault((r["scenario"], r["turn"]), []).append(r)
        clean_replies = sum(all(x["verdict"] == "SUPPORTED" for x in v) for v in per_reply.values())
        print(f"  replies whose every product claim is fully supported: {pct(clean_replies, len(per_reply))} (of {len(per_reply)} replies that make product claims)")
        harmful = [r for r in claims if r.get("severity") == "HARMFUL"]
        print(f"  HARMFUL-rated claims: {len(harmful)}")
        for r in harmful[:6]:
            print(f"    - {r['scenario']} T{r['turn']}: {r['claim'][:150]}")

    pc = [r for r in packs if r.get("type") == "claim"]
    if pc:
        report_claims("KNOWLEDGE PACKS (all)", pc)
        for pack in sorted({r["pack"] for r in pc}):
            sub = [r for r in pc if r["pack"] == pack]
            s = Counter(r["verdict"] for r in sub)
            print(f"    {pack:16} n={len(sub):3}  supported {pct(s['SUPPORTED'], len(sub))}  "
                  f"unsupp/contra/wrongmodel {s['UNSUPPORTED'] + s['CONTRADICTED'] + s['WRONG_MODEL']}  partial {s['PARTIAL']}")
        om = [r for r in packs if r.get("type") == "omission"]
        if om:
            print(f"  'Not covered' items that the sources actually cover: {pct(sum(bool(r.get('actually_covered')) for r in om), len(om))}")
        worst = [r for r in pc if r.get("verdict") in ("CONTRADICTED", "WRONG_MODEL") or r.get("severity") == "HARMFUL"]
        for r in worst[:8]:
            print(f"    - [{r['pack']}] {r['verdict']}/{r.get('severity')}: {r['claim'][:140]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))
