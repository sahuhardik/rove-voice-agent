"""Drive `docs/06` §2.4's degradation ladder until it fires **and recovers**.

    .venv/bin/python -m eval.run_ladder
    .venv/bin/python -m eval.run_ladder --results data/traces/phase3-harness-c/results.jsonl
    .venv/bin/python -m eval.run_ladder --json

**Why this is a replay and not a live session.** §2.4 keys tiers 1–3 off the
p95 over a **20-turn window**, and `server/ladder.py` only releases a tier
once that p95 has sat `RECOVERY_MARGIN_MS` under the trigger for
`RECOVERY_TURNS` consecutive turns. A slow turn therefore keeps the window hot
until twenty further turns have pushed it out. No Harness C case runs twenty
turns — each case is a fresh room with one or two — so a live session can show
the ladder *firing* and cannot, by construction, show it *recovering*. Rather
than claim recovery was demonstrated when it was not, this replays the real
readings through the real objects: a real `server.latency.LatencyBook` and a
real `server.ladder.Ladder`, with nothing stubbed. What is lost is that the
tier changes do not reach a live pipeline here; what is kept is that every
trigger, every margin and every release in `server/ladder.py` is the one that
ships.

**Where the numbers come from.** `--results` is a Harness C JSONL. The slow
run is that file's measured `m7_server_ms` readings, in the order they were
measured. The calm run that follows is one of two, and the report prints both:

* **measured calm** — the *fastest* M7 the same run actually produced,
  repeated. This is the most optimistic thing the pipeline was observed to do,
  so where it fails to release a tier, no real turn in that run could have.
* **budget calm** — §2.2's own measurable target median. Not a measurement:
  it is the number the budget says a turn should cost, and it is here to show
  the release path reaches Tier 0 at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server import ladder as ladder_module
from server import latency as latency_module
from server.config import REPO_ROOT

DEFAULT_RESULTS = REPO_ROOT / "data" / "traces" / "phase3-harness-c" / "results.jsonl"

#: How many calm turns to offer before giving up on recovery. Generous: a full
#: window (20) plus the three `RECOVERY_TURNS` needs, times the five tiers that
#: can be released one at a time.
MAX_CALM_TURNS = 150


def measured_m7(path: Path) -> list[float]:
    """Every `m7_server_ms` in a Harness C results file, in file order."""
    values: list[float] = []
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        for turn in record.get("turns") or []:
            value = turn.get("m7_server_ms")
            if value is not None:
                values.append(float(value))
    return values


@dataclass
class Replay:
    """One climb-then-calm run of the real ladder."""

    name: str
    calm_ms: float
    calm_source: str
    slow_turns: int = 0
    calm_turns: int = 0
    peak_tier: int = 0
    final_tier: int = 0
    fired: list[dict[str, Any]] = field(default_factory=list)
    recovered: list[dict[str, Any]] = field(default_factory=list)
    stuck_reason: str = ""

    @property
    def recovered_to_zero(self) -> bool:
        return self.final_tier == 0 and bool(self.recovered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "calm_ms": self.calm_ms,
            "calm_source": self.calm_source,
            "slow_turns": self.slow_turns,
            "calm_turns": self.calm_turns,
            "peak_tier": self.peak_tier,
            "final_tier": self.final_tier,
            "fired": self.fired,
            "recovered": self.recovered,
            "recovered_to_zero": self.recovered_to_zero,
            "stuck_reason": self.stuck_reason,
        }


def replay(slow: list[float], *, calm_ms: float, name: str, calm_source: str) -> Replay:
    """Feed `slow` then `calm_ms` into a real Ladder over a real LatencyBook."""
    book = latency_module.LatencyBook()
    rungs = ladder_module.Ladder(book)
    out = Replay(name=name, calm_ms=calm_ms, calm_source=calm_source)

    turn = 0
    for value in slow:
        turn += 1
        book.record(
            latency_module.TurnLatency(
                turn=turn, modality="voice", m7_server_ms=value, first_audible="reply"
            )
        )
        event = rungs.evaluate()
        if event is not None:
            (out.fired if event.direction == "fired" else out.recovered).append(
                event.as_dict()
            )
        out.peak_tier = max(out.peak_tier, rungs.tier)
    out.slow_turns = len(slow)

    if rungs.tier == 0:
        out.stuck_reason = "the ladder never left Tier 0 on these readings"
        out.final_tier = 0
        return out

    for _ in range(MAX_CALM_TURNS):
        turn += 1
        out.calm_turns += 1
        book.record(
            latency_module.TurnLatency(
                turn=turn, modality="voice", m7_server_ms=calm_ms, first_audible="reply"
            )
        )
        event = rungs.evaluate()
        if event is not None:
            (out.fired if event.direction == "fired" else out.recovered).append(
                event.as_dict()
            )
        if rungs.tier == 0:
            break

    out.final_tier = rungs.tier
    if rungs.tier != 0:
        trigger = ladder_module.P95_TRIGGERS.get(rungs.tier)
        p95 = book.running_p95_ms()
        out.stuck_reason = (
            f"stuck at Tier {rungs.tier} after {out.calm_turns} calm turns: "
            f"p95 settled at {p95:.0f} ms and Tier {rungs.tier} releases only "
            f"below {trigger - ladder_module.RECOVERY_MARGIN_MS:.0f} ms"
            if trigger is not None and p95 is not None
            else f"stuck at Tier {rungs.tier} after {out.calm_turns} calm turns"
        )
    return out


def format_report(replays: list[Replay], *, slow: list[float], source: Path) -> str:
    lines: list[str] = []
    lines.append("§2.4 degradation ladder — firing and recovery, replayed")
    lines.append(f"  readings: {len(slow)} measured M7 value(s) from {source}")
    if slow:
        lines.append(
            f"  slowest {max(slow):.0f} ms, fastest {min(slow):.0f} ms"
        )
    lines.append(
        f"  triggers: tier 1 > {ladder_module.TIER1_P95_MS:.0f} ms p95, "
        f"tier 2 > {ladder_module.TIER2_P95_MS:.0f}, "
        f"tier 3 > {ladder_module.TIER3_P95_MS:.0f}; "
        f"tier 5 at {ladder_module.TIER5_CONSECUTIVE} consecutive turns over "
        f"{ladder_module.TIER5_BREACH_MS:.0f} ms"
    )
    lines.append(
        f"  release: p95 {ladder_module.RECOVERY_MARGIN_MS:.0f} ms under the trigger "
        f"for {ladder_module.RECOVERY_TURNS} turns, one tier at a time "
        "(ours, not §2.4's)"
    )
    lines.append("")

    for run in replays:
        lines.append(
            f"── {run.name} — calm turns at {run.calm_ms:.0f} ms ({run.calm_source}) "
            + "─" * 12
        )
        for event in run.fired:
            lines.append(
                f"  FIRED      tier {event['previous_tier']} → {event['tier']} "
                f"at turn {event['turns']}: {event['reason']}"
            )
            lines.append(f"             costs: {event['cost']}")
        if not run.fired:
            lines.append("  the ladder never fired on these readings")
        for event in run.recovered:
            lines.append(
                f"  RECOVERED  tier {event['previous_tier']} → {event['tier']} "
                f"at turn {event['turns']}: {event['reason']}"
            )
        if not run.recovered:
            lines.append("  the ladder never released a tier")
        lines.append(
            f"  peak tier {run.peak_tier}, final tier {run.final_tier}, "
            f"{run.slow_turns} measured turn(s) then {run.calm_turns} calm turn(s)"
        )
        if run.stuck_reason:
            lines.append(f"  → {run.stuck_reason}")
        else:
            lines.append("  → fired and recovered all the way to Tier 0")
        lines.append("")

    lines.append(
        "Replay, not a live session: §2.4's p95 window is 20 turns and no "
        "Harness C case runs"
    )
    lines.append(
        "twenty, so recovery cannot be shown in a room. The Ladder, the "
        "LatencyBook, the"
    )
    lines.append("triggers and the margins above are the shipping ones, unstubbed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="§2.4 ladder fire-and-recover replay.")
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default="", help="also write the JSON here")
    args = parser.parse_args(argv)

    source = Path(args.results)
    slow = measured_m7(source)
    if not slow:
        print(f"no m7_server_ms readings in {source}", file=sys.stderr)
        return 2

    replays = [
        replay(
            slow,
            calm_ms=min(slow),
            name="measured calm",
            calm_source=f"fastest turn the run produced, {min(slow):.0f} ms",
        ),
        replay(
            slow,
            calm_ms=latency_module.MEASURABLE_TARGET_MEDIAN_MS,
            name="budget calm",
            calm_source="§2.2 lines 2–8 target median, not a measurement",
        ),
    ]

    payload = {
        "source": str(source),
        "readings": slow,
        "fastest_ms": min(slow),
        "slowest_ms": max(slow),
        "replays": [r.as_dict() for r in replays],
    }
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_report(replays, slow=slow, source=source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
