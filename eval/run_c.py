"""Run Harness C (`docs/06` §7.3) — end-to-end spoken, through a real room.

    .venv/bin/python -m eval.run_c                     # all three passes
    .venv/bin/python -m eval.run_c --pass clean
    .venv/bin/python -m eval.run_c --pass corruption --json
    .venv/bin/python -m eval.run_c --scenarios EVAL-01,EVAL-02 --no-m10
    .venv/bin/python -m eval.run_c --out data/traces/phase3-harness-c/run.jsonl

Unlike `eval/run.py` and `eval/run_b.py`, this one **brings a system up**: a
`livekit-server --dev` media server and the FastAPI process, both on free
ports, exactly as `server/verify_livekit.py` does. That is not convenience — it
is §7.3's second rule. The audio has to go through a real peer connection, so
there has to be something on the other end of one, and a harness that let you
point it at "no server" would be a harness with a way to not do that.

**It needs AWS** (Polly for the microphone fixture and the agent's voice,
Transcribe for the recogniser, Bedrock for the core) and the `livekit-server`
binary. It runs in **real time by construction** and takes minutes rather than
seconds; `--limit` and `--scenarios` exist for working on the harness itself,
not for producing a headline number from four cases.

Results are written to a JSONL file as each case finishes, so a run that dies
at case 25 has 24 cases on disk rather than nothing, and `--resume` picks up
from what is already there.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

from eval import harness_c
from server import livekit_dev, livekit_tokens
from server.config import REPO_ROOT, Settings
from server.verify import BackgroundServer, free_port

#: Where a run lands by default. Beside the Phase 3 traces, because the traces
#: of the sessions it drove are the evidence for every number it prints.
DEFAULT_OUT = REPO_ROOT / "data" / "traces" / "phase3-harness-c"

#: A short greeting, for the same reason `server/verify_livekit.py` has one:
#: the default greeting is eight seconds of playout per case that the harness
#: then waits out, and thirty cases of it is twenty minutes of dead air. The
#: greeting a user gets is unchanged; this is the harness's own.
HARNESS_GREETING = "I can hear you. Tell me what the camera is doing."


def _load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            record = json.loads(line)
            out[record["case_id"]] = record
    return out


async def _run(
    cases: list[harness_c.Case],
    *,
    base_url: str,
    ws_url: str,
    settings: Settings,
    measure_m10: bool,
    out_path: Path,
) -> list[harness_c.CaseResult]:
    handle = out_path.open("a", encoding="utf-8")

    def write(result: harness_c.CaseResult) -> None:
        handle.write(json.dumps(result.as_dict(), sort_keys=True) + "\n")
        handle.flush()

    try:
        return await harness_c.run_harness_c(
            cases,
            base_url=base_url,
            ws_url=ws_url,
            settings=settings,
            measure_m10=measure_m10,
            on_result=write,
        )
    finally:
        handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness C — end-to-end spoken.")
    parser.add_argument(
        "--pass",
        dest="passes",
        default="all",
        help=f"comma-separated: {', '.join(harness_c.PASSES)}, or all",
    )
    parser.add_argument("--scenarios", default="", help="comma-separated EVAL ids")
    parser.add_argument("--limit", type=int, default=0, help="first N cases only")
    parser.add_argument("--no-m10", action="store_true", help="skip the typed M10 leg")
    parser.add_argument("--no-llm", action="store_true", help="core on its rule-based floor")
    parser.add_argument("--binary", default="", help=f"default: {livekit_dev.DEFAULT_BINARY}")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--livekit-port", type=int, default=0)
    parser.add_argument("--out", default="", help=f"results JSONL (default under {DEFAULT_OUT})")
    parser.add_argument("--resume", action="store_true", help="skip cases already in --out")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)

    passes = (
        harness_c.PASSES
        if args.passes == "all"
        else tuple(p.strip() for p in args.passes.split(",") if p.strip())
    )
    unknown = [p for p in passes if p not in harness_c.PASSES]
    if unknown:
        parser.error(f"unknown pass(es) {unknown}; expected {list(harness_c.PASSES)}")
    ids = tuple(s.strip() for s in args.scenarios.split(",") if s.strip()) or None

    cases = harness_c.build_cases(passes=passes, ids=ids)
    out_path = Path(args.out) if args.out else DEFAULT_OUT / "results.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done: dict[str, dict[str, Any]] = {}
    if args.resume:
        done = _load_existing(out_path)
        cases = [c for c in cases if c.case_id not in done]
    if args.limit:
        cases = cases[: args.limit]

    binary = livekit_dev.find_binary(args.binary or None)
    if binary is None:
        print(
            f"livekit-server not found (expected {livekit_dev.DEFAULT_BINARY} or on PATH)",
            file=sys.stderr,
        )
        return 2

    media: livekit_dev.DevServer | None = None
    api: BackgroundServer | None = None
    results: list[harness_c.CaseResult] = []
    started = time.time()
    try:
        media = livekit_dev.start_dev_server(
            binary=binary,
            port=args.livekit_port or free_port(),
            log_path=DEFAULT_OUT / "livekit-server.log",
        )
        settings = dataclasses.replace(
            Settings.from_env(),
            port=args.port or free_port(),
            transport="livekit",
            livekit_url=media.ws_url,
            livekit_api_key=livekit_tokens.DEV_API_KEY,
            livekit_api_secret=livekit_tokens.DEV_API_SECRET,
            livekit_keys_are_dev=True,
            greeting_text=HARNESS_GREETING,
            use_llm=not args.no_llm,
            use_transcribe=True,
            trace_dir=DEFAULT_OUT / "traces",
        )
        api = BackgroundServer(settings).start()
        print(
            f"Harness C — {len(cases)} case(s) over pass(es) {', '.join(passes)}"
            + (f", resuming past {len(done)}" if done else ""),
            flush=True,
        )
        print(f"  media {media.ws_url}   api {api.base_url}   out {out_path}", flush=True)
        print(
            "  real-time pace: a case costs roughly as long as it takes to say it.\n",
            flush=True,
        )
        results = asyncio.run(
            _run(
                cases,
                base_url=api.base_url,
                ws_url=api.ws_url,
                settings=settings,
                measure_m10=not args.no_m10,
                out_path=out_path,
            )
        )
    except KeyboardInterrupt:
        print("\ninterrupted — results so far are in " + str(out_path), flush=True)
    finally:
        if api is not None:
            with contextlib.suppress(Exception):
                api.stop()
        if media is not None:
            with contextlib.suppress(Exception):
                media.stop()

    # Everything on disk, including what earlier runs left there, so the
    # report is about the whole pass rather than about this invocation.
    all_results = [
        _result_from(record) for record in _load_existing(out_path).values()
    ]
    order = {case.case_id: i for i, case in enumerate(harness_c.build_cases())}
    all_results.sort(key=lambda r: order.get(r.case_id, 10_000))

    if args.json:
        print(
            json.dumps(
                {
                    "summary": harness_c.summarise(all_results),
                    "cases": [r.as_dict() for r in all_results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print()
        print(harness_c.format_report_c(all_results))
        print(f"\n  {len(results)} case(s) this run in {time.time() - started:.0f}s; "
              f"{len(all_results)} on disk at {out_path}")
    failures = sum(1 for r in all_results if r.error)
    return 1 if failures else 0


def _result_from(record: dict[str, Any]) -> harness_c.CaseResult:
    """Rebuild a `CaseResult` from its JSONL line.

    The report is rendered from the file rather than from memory so that
    `--resume` and a plain re-print give exactly the same numbers.
    """
    result = harness_c.CaseResult(
        case_id=record["case_id"],
        pass_name=record["pass"],
        scenario_id=record["scenario_id"],
        part=record.get("part", ""),
        corruption=record.get("corruption", ""),
        construction=record.get("construction", ""),
        true_model=record.get("true_model", ""),
        spoken=list(record.get("spoken") or []),
        fixture_ms=list(record.get("fixture_ms") or []),
        device_model=(record.get("device") or {}).get("model", ""),
        device_confidence=(record.get("device") or {}).get("confidence", ""),
        peer_m7_ms=record.get("peer_m7_ms"),
        loopback_ms=record.get("loopback_ms"),
        barge_in=dict(record.get("barge_in") or {}),
        error=record.get("error", ""),
        seconds=float(record.get("seconds") or 0.0),
    )
    m10 = record.get("m10") or {}
    result.typed_text = m10.get("typed_text", "")
    result.typed_step_id = m10.get("typed_step_id")
    result.typed_category = m10.get("typed_category", "")
    result.typed_escalate = m10.get("typed_escalate")
    result.typed_device_model = m10.get("typed_device_model", "")
    for turn in record.get("turns") or []:
        result.turns.append(
            harness_c.TurnRecord(
                turn=int(turn.get("turn") or 0),
                heard=turn.get("heard", ""),
                normalised=turn.get("normalised", ""),
                confidence=turn.get("confidence"),
                asr_candidates=list(turn.get("asr_candidates") or []),
                step_id=turn.get("step_id"),
                taxonomy_id=turn.get("taxonomy_id", ""),
                category=turn.get("category", ""),
                escalate=bool(turn.get("escalate")),
                fsm_state=turn.get("fsm_state", ""),
                m7_server_ms=turn.get("m7_server_ms"),
                first_audible=turn.get("first_audible", "reply"),
                latency_lines=dict(turn.get("lines") or {}),
                ladder_tier=int(turn.get("ladder_tier") or 0),
            )
        )
    return result


if __name__ == "__main__":
    sys.exit(main())
