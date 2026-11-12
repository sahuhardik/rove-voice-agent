"""Milestone 4.5 — the grounding measurement (`docs/06` §7.2, §9.1 Phase 1 exit).

`docs/06` §7.2 adds grounding rate to the metric table as *"proportion of
device-specific claims carrying at least one cleared Tier-1 chunk citation,
across both output surfaces. Target 100 %, enforced by the output guard,
measured from traces."* §9.1 Phase 1 exit names it directly: **grounding rate
100 %**.

That sentence hides two different claims, and this module refuses to blend
them:

1. **Structural grounding** — every device-specific span in a turn the output
   guard *let through* carries at least one `chunk_id`, and the cited id is a
   real chunk in the speakable store. This is machine-checkable, it is checked
   over every turn of Harness A and Harness B, and it is the number §7.5's
   alert ("grounding-rate drop below 100 %") would fire on.
2. **Semantic grounding** — the cited chunk actually *supports the claim as
   stated*. No regex can tell you that. §7.4 is explicit that an LLM judge
   ships only after it is validated against human labels at an agreed κ, and
   those labels do not exist yet, so this layer is **sampled and hand-graded**,
   its verdicts live in `grounding_semantic.json`, and the code in here only
   counts them.

A structural rate of 100 % with an unmeasured semantic rate is the failure mode
this split exists to prevent: a citation attached to a claim it does not
support turns `clearance.spoken_claims` (§4.4) into decoration, and it would
score full marks on layer 1.

**This module is an instrument. It does not touch what it measures.** It adds
no scoring to `eval/harness.py` or `eval/harness_b.py`, and it reimplements
nothing: span detection is `agent.core.device_specific_spans`, the version
regex is `agent.core.firmware_version_spans`, and the kept/dropped/rewritten
verdict is the real `agent.core.output_guard` — captured by wrapping the
module attribute for the duration of a run (`capture_guard`), which is the only
way to see the guard's *per-line* verdict from outside without changing
`agent/`. `TurnResult` carries the turn's citations as one merged list, and a
merged list cannot tell you that line 2 was uncited while line 1 was cited.

Two things the structural layer deliberately *can* fail on, so it is worth
saying what they are before reading a rate:

* **Safety lines are exempt from the citation rule inside the guard** ("unplug
  it and stop" is not a claim about the product — `agent/core.py`
  `output_guard`). They are *not* exempt here: a safety line that names a
  control or a capacity is still a device-specific claim the user hears, so it
  is counted and reported. A non-zero failing count made entirely of safety
  lines is a different finding from one made of step lines, and the report
  prints the line kind for exactly that reason.
* **A citation naming a chunk id that is not in the corpus** counts as uncited,
  not as cited. A dangling id is an audit trail that leads nowhere.
"""

from __future__ import annotations

import json
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from agent import core

#: Where the hand-graded semantic verdicts live. Written by a human reading the
#: chunk text against the claim (§7.4 item 1–2: human labels first, a judge only
#: after it is validated against them).
SEMANTIC_RECORD_PATH = Path(__file__).with_name("grounding_semantic.json")

#: `docs/06` §9.1 Phase 1 exit. Not a target — the exit condition.
GROUNDING_TARGET = 1.0

#: The sampled semantic layer: 20 cited claims, plus **every** structural
#: failure (a failing span is always read by hand, never sampled away).
SEMANTIC_SAMPLE_SIZE = 20
#: Fixed so the sample is reproducible from the same run of claims.
SEMANTIC_SAMPLE_SEED = 45  # Milestone 4.5

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
PARTIAL = "partial"
#: Only `supported` scores 1. `partial` — the chunk supports a weaker claim
#: than the one spoken — scores 0, because the measurement is whether the chunk
#: supports the claim *as stated*.
VERDICTS = (SUPPORTED, PARTIAL, UNSUPPORTED)


# --------------------------------------------------------------------------
# Capturing the guard
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TurnLabel:
    """Which turn of which run a captured guard verdict belongs to."""

    harness: str  # "A" | "B"
    scenario_id: str
    branch: str | None = None
    turn: int = 1

    def __str__(self) -> str:
        where = f"{self.scenario_id}"
        if self.branch:
            where += f"/{self.branch}"
        return f"{self.harness}:{where} turn {self.turn}"


@dataclass(frozen=True)
class CapturedLine:
    text: str
    kind: str
    chunk_ids: tuple[str, ...]


@dataclass
class CapturedTurn:
    """One `output_guard` call, as it happened."""

    label: TurnLabel
    kept: list[CapturedLine] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    rewritten: list[tuple[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.kept).strip()


class GuardRecorder:
    """Every guard verdict of a run, labelled by turn.

    Unlabelled calls are still recorded, under a `?` label, rather than
    dropped: a guard call the instrument did not expect is a finding about the
    instrument and should be visible, not swallowed.
    """

    def __init__(self) -> None:
        self.turns: list[CapturedTurn] = []
        self._label: TurnLabel | None = None

    @contextmanager
    def labelled(self, label: TurnLabel) -> Iterator[None]:
        previous = self._label
        self._label = label
        try:
            yield
        finally:
            self._label = previous

    def record(self, report: Any) -> None:
        label = self._label or TurnLabel(harness="?", scenario_id="?", turn=0)
        self.turns.append(
            CapturedTurn(
                label=label,
                kept=[
                    CapturedLine(
                        text=line.text,
                        kind=line.kind,
                        chunk_ids=tuple(line.chunk_ids),
                    )
                    for line in report.kept
                ],
                dropped=[(line.text, reason) for line, reason in report.dropped],
                rewritten=[(line.text, reason) for line, reason in report.rewritten],
            )
        )


@contextmanager
def capture_guard(recorder: GuardRecorder | None = None) -> Iterator[GuardRecorder]:
    """Record every `agent.core.output_guard` verdict inside the block.

    The real guard runs and its real report is returned — this wraps, it does
    not replace. `agent/core.py` is not edited: `_compose_turn` looks the guard
    up as a module global on every call, so swapping the attribute for the
    duration of a measurement run is enough to see each line's verdict, and the
    attribute is restored on the way out even if the run raises.
    """
    recorder = recorder if recorder is not None else GuardRecorder()
    real_guard = core.output_guard

    def wrapper(lines: Sequence[Any]) -> Any:
        report = real_guard(lines)
        recorder.record(report)
        return report

    core.output_guard = wrapper  # type: ignore[assignment]
    try:
        yield recorder
    finally:
        core.output_guard = real_guard  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Layer 1 — structural
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimSpan:
    """One device-specific span in one line the guard let through."""

    label: TurnLabel
    line_index: int
    kind: str
    span: str
    line_text: str
    chunk_ids: tuple[str, ...]
    cited: bool
    reason: str = ""

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        """Identity of the *claim*, independent of which turn said it."""
        return (self.line_text, self.chunk_ids)


def known_chunk_ids(chunks_path: str | None = None) -> frozenset[str]:
    """Every chunk id the corpus actually has, for the dangling-citation rule."""
    from agent import retrieval

    return frozenset(c.chunk_id for c in retrieval.load_chunks(chunks_path))


def scan_turn(turn: CapturedTurn, known: frozenset[str] | None = None) -> list[ClaimSpan]:
    """Every device-specific span in every line the guard kept.

    Span detection is `agent.core.device_specific_spans` — the guard's own
    detector, so the measurement cannot disagree with the thing it measures
    about what a device-specific claim *is*.
    """
    spans: list[ClaimSpan] = []
    for index, line in enumerate(turn.kept):
        found = core.device_specific_spans(line.text)
        if not found:
            continue
        live = [cid for cid in line.chunk_ids if known is None or cid in known]
        dangling = [cid for cid in line.chunk_ids if known is not None and cid not in known]
        if live:
            cited, reason = True, ""
        elif dangling:
            cited = False
            reason = (
                "cites " + ", ".join(repr(c) for c in dangling) + ", which is not a "
                "chunk in the corpus"
            )
        else:
            cited, reason = False, "no chunk id on the line"
        for span in found:
            spans.append(
                ClaimSpan(
                    label=turn.label,
                    line_index=index,
                    kind=line.kind,
                    span=span,
                    line_text=line.text,
                    chunk_ids=tuple(line.chunk_ids),
                    cited=cited,
                    reason=reason,
                )
            )
    return spans


#: The `span` of a claim record whose unit is the whole line, not a substring.
WHOLE_LINE = "<whole line>"


def cited_lines(
    turns: Sequence[CapturedTurn], known: frozenset[str] | None = None
) -> list[ClaimSpan]:
    """Every kept line carrying a citation, as a claim record.

    The two layers do not share a unit, and pretending they do would be the
    blend this module exists to avoid:

    * **Structural** counts *spans*, because the guard's rule is written in
      spans — `device_specific_spans` is what decides whether a line needed a
      citation at all.
    * **Semantic** counts *lines*, because what a human grades against a chunk
      is a sentence. It also has to: on this corpus the span pool is tiny
      (see `eval/README.md`), so a sample drawn from spans alone would grade two
      claims and call it a rate.

    Every line here is one the agent spoke **and** attached a chunk id to, so
    "does the chunk support it as stated" is a fair question about all of them,
    pattern match or not.
    """
    out: list[ClaimSpan] = []
    for turn in turns:
        for index, line in enumerate(turn.kept):
            if not line.chunk_ids:
                continue
            live = [cid for cid in line.chunk_ids if known is None or cid in known]
            out.append(
                ClaimSpan(
                    label=turn.label,
                    line_index=index,
                    kind=line.kind,
                    span=WHOLE_LINE,
                    line_text=line.text,
                    chunk_ids=tuple(line.chunk_ids),
                    cited=bool(live),
                    reason="" if live else "every cited id is outside the corpus",
                )
            )
    return out


def version_leaks(turn: CapturedTurn) -> list[tuple[int, str]]:
    """Firmware-version-shaped tokens the guard let through (§4.6).

    Should always be empty — the guard drops those lines — which is exactly why
    it is worth asserting on a real run rather than trusting.
    """
    out: list[tuple[int, str]] = []
    for index, line in enumerate(turn.kept):
        for token in core.firmware_version_spans(line.text):
            out.append((index, token))
    return out


def turn_score(spans: Sequence[ClaimSpan]) -> int:
    """1 if every device-specific span in this turn is cited, else 0.

    All-or-nothing per turn, deliberately: a turn is what the user hears, and
    one uncited device claim in it is an ungrounded turn no matter how many
    cited ones sit beside it.
    """
    return 0 if any(not span.cited for span in spans) else 1


@dataclass
class StructuralReport:
    harness: str
    commit: str
    turns: list[CapturedTurn] = field(default_factory=list)
    spans: list[ClaimSpan] = field(default_factory=list)
    leaks: list[tuple[TurnLabel, int, str]] = field(default_factory=list)

    @property
    def failing(self) -> list[ClaimSpan]:
        return [s for s in self.spans if not s.cited]

    @property
    def span_rate(self) -> float | None:
        """Cited spans / all spans. `None` when the run made no claims at all —
        reporting 1.0 there would be a lie dressed as a pass."""
        if not self.spans:
            return None
        return sum(1 for s in self.spans if s.cited) / len(self.spans)

    @property
    def turn_rate(self) -> float | None:
        """Turns scoring 1 / turns carrying at least one device-specific span."""
        grouped = self.by_turn()
        if not grouped:
            return None
        return sum(turn_score(v) for v in grouped.values()) / len(grouped)

    def by_turn(self) -> dict[str, list[ClaimSpan]]:
        grouped: dict[str, list[ClaimSpan]] = {}
        for span in self.spans:
            grouped.setdefault(str(span.label), []).append(span)
        return grouped

    @property
    def cited_spans(self) -> list[ClaimSpan]:
        return [s for s in self.spans if s.cited]


def structural_report(
    harness: str,
    turns: Sequence[CapturedTurn],
    known: frozenset[str] | None = None,
    *,
    commit: str = "",
) -> StructuralReport:
    report = StructuralReport(harness=harness, commit=commit, turns=list(turns))
    for turn in turns:
        report.spans.extend(scan_turn(turn, known))
        for index, token in version_leaks(turn):
            report.leaks.append((turn.label, index, token))
    return report


# --------------------------------------------------------------------------
# Running the harnesses under the recorder
# --------------------------------------------------------------------------


class LabelledAgent:
    """Harness A's `Agent`, with every guard call labelled by scenario.

    Delegates `propose` untouched. The harness cannot tell the difference, which
    is the requirement: the measurement may not change what is measured.
    """

    def __init__(self, agent: Any, recorder: GuardRecorder) -> None:
        self._agent = agent
        self._recorder = recorder
        self.name = agent.name

    def propose(self, state: Any) -> Any:
        label = TurnLabel(harness="A", scenario_id=state.session_id, turn=1)
        with self._recorder.labelled(label):
            return self._agent.propose(state)


class LabelledSession:
    """Harness B's `Session`, with every guard call labelled by turn."""

    def __init__(self, session: Any, recorder: GuardRecorder, scenario_id: str,
                 branch: str) -> None:
        self._session = session
        self._recorder = recorder
        self._scenario_id = scenario_id
        self._branch = branch
        self._turn = 0

    def turn(self, utterance: str) -> Any:
        self._turn += 1
        label = TurnLabel(
            harness="B",
            scenario_id=self._scenario_id,
            branch=self._branch,
            turn=self._turn,
        )
        with self._recorder.labelled(label):
            return self._session.turn(utterance)

    def record_attempt(self, entry: Any) -> None:
        self._session.record_attempt(entry)


class LabelledDriver:
    """Harness B's `Driver`, wrapping each session it opens."""

    def __init__(self, driver: Any, recorder: GuardRecorder) -> None:
        self._driver = driver
        self._recorder = recorder
        self.name = driver.name

    def open(self, scenario: Any, session_key: str) -> LabelledSession:
        branch = session_key.rsplit("::", 1)[-1]
        return LabelledSession(
            self._driver.open(scenario, session_key),
            self._recorder,
            scenario.id,
            branch,
        )


def run_harness_a(
    *, llm: Any | None = None, chunks_path: str | None = None, scenarios: Any = None
) -> tuple[Any, list[CapturedTurn]]:
    """Harness A over the core, capturing every guard verdict."""
    from eval import harness

    agent = harness.build_agent("core", llm=llm, chunks_path=chunks_path)
    recorder = GuardRecorder()
    with capture_guard(recorder):
        report = harness.run_harness(LabelledAgent(agent, recorder), scenarios)
    return report, recorder.turns


def run_harness_b(
    *, llm: Any | None = None, chunks_path: str | None = None, scenarios: Any = None
) -> tuple[Any, list[CapturedTurn]]:
    """Harness B — 8 scenarios × 2 branches — capturing every guard verdict."""
    from eval import harness, harness_b

    driver = harness_b.build_driver("core", llm=llm, chunks_path=chunks_path)
    recorder = GuardRecorder()
    scenarios = scenarios if scenarios is not None else harness.load_scenarios()
    with capture_guard(recorder):
        report = harness_b.run_harness_b(LabelledDriver(driver, recorder), scenarios)
    return report, recorder.turns


# --------------------------------------------------------------------------
# Layer 2 — semantic, sampled, hand-graded
# --------------------------------------------------------------------------


def distinct_claims(spans: Sequence[ClaimSpan]) -> list[ClaimSpan]:
    """One representative per (line text, citation set).

    The same composed line recurs across scenarios with the same citations.
    Sampling instances would spend the hand-grading budget re-reading one claim;
    sampling distinct claims spends it on distinct evidence. The instance count
    is reported alongside, so the sample's coverage is never overstated.
    """
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[ClaimSpan] = []
    for span in spans:
        if span.key in seen:
            continue
        seen.add(span.key)
        out.append(span)
    return out


def sample_claims(
    spans: Sequence[ClaimSpan],
    size: int = SEMANTIC_SAMPLE_SIZE,
    seed: int = SEMANTIC_SAMPLE_SEED,
) -> list[ClaimSpan]:
    """A reproducible random sample of distinct cited claims."""
    pool = distinct_claims([s for s in spans if s.cited])
    pool = sorted(pool, key=lambda s: (s.line_text, s.chunk_ids))
    if len(pool) <= size:
        return pool
    return sorted(
        random.Random(seed).sample(pool, size),
        key=lambda s: (s.line_text, s.chunk_ids),
    )


@dataclass(frozen=True)
class SemanticVerdict:
    """One hand-graded claim: does the cited chunk support it *as stated*?"""

    claim: str
    chunk_ids: tuple[str, ...]
    verdict: str
    note: str
    origin: str  # "sampled-cited" | "structural-failure"

    @property
    def score(self) -> int:
        return 1 if self.verdict == SUPPORTED else 0


class SemanticRecordError(AssertionError):
    """The hand-graded record is not a record this module can count."""


def load_semantic_record(path: str | Path | None = None) -> list[SemanticVerdict]:
    """Load the hand-graded verdicts, validating hard.

    A malformed grading record has to fail loudly: a verdict vocabulary that
    drifted, or an entry with no note, would quietly change a published rate.
    """
    path = Path(path) if path is not None else SEMANTIC_RECORD_PATH
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SemanticRecordError(f"no hand-graded record at {path}") from exc
    except json.JSONDecodeError as exc:
        raise SemanticRecordError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict) or "verdicts" not in raw:
        raise SemanticRecordError(f"{path} has no top-level 'verdicts' key")

    out: list[SemanticVerdict] = []
    for entry in raw["verdicts"]:
        missing = {"claim", "chunk_ids", "verdict", "note", "origin"} - set(entry)
        if missing:
            raise SemanticRecordError(
                f"{path}: a verdict is missing {sorted(missing)}"
            )
        if entry["verdict"] not in VERDICTS:
            raise SemanticRecordError(
                f"{path}: verdict {entry['verdict']!r} is not one of {list(VERDICTS)}"
            )
        if not str(entry["note"]).strip():
            raise SemanticRecordError(
                f"{path}: the verdict on {entry['claim'][:40]!r} has an empty note — "
                "an ungrounded grade is not a grade"
            )
        if entry["origin"] not in ("sampled-cited", "structural-failure"):
            raise SemanticRecordError(
                f"{path}: origin {entry['origin']!r} is not one of "
                "'sampled-cited' / 'structural-failure'"
            )
        out.append(
            SemanticVerdict(
                claim=entry["claim"],
                chunk_ids=tuple(entry["chunk_ids"]),
                verdict=entry["verdict"],
                note=entry["note"],
                origin=entry["origin"],
            )
        )
    if not out:
        raise SemanticRecordError(f"{path} grades nothing")
    return out


def semantic_rate(verdicts: Sequence[SemanticVerdict], origin: str | None = None) -> float | None:
    """Supported / graded, over the sample. `None` when nothing was graded."""
    scope = [v for v in verdicts if origin is None or v.origin == origin]
    if not scope:
        return None
    return sum(v.score for v in scope) / len(scope)


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:.1f}%"


def dump_turns(turns: Sequence[CapturedTurn]) -> dict[str, Any]:
    """Every captured turn, as JSON-able records.

    `docs/06` §7.5 wants the guard verdict on a turn to be a trace record
    rather than something reconstructed later, and the semantic layer is graded
    by a human reading these lines against the chunk text — which is a slow job
    that should not require re-running the harness against Bedrock each time.
    """
    return {
        "turns": [
            {
                "harness": turn.label.harness,
                "scenario_id": turn.label.scenario_id,
                "branch": turn.label.branch,
                "turn": turn.label.turn,
                "kept": [
                    {"text": line.text, "kind": line.kind,
                     "chunk_ids": list(line.chunk_ids)}
                    for line in turn.kept
                ],
                "dropped": [{"text": t, "reason": r} for t, r in turn.dropped],
                "rewritten": [{"text": t, "reason": r} for t, r in turn.rewritten],
            }
            for turn in turns
        ]
    }


def load_turns(payload: dict[str, Any]) -> list[CapturedTurn]:
    """The inverse of `dump_turns`, so a dump can be re-scanned offline."""
    return [
        CapturedTurn(
            label=TurnLabel(
                harness=row["harness"],
                scenario_id=row["scenario_id"],
                branch=row.get("branch"),
                turn=row.get("turn", 1),
            ),
            kept=[
                CapturedLine(
                    text=line["text"],
                    kind=line["kind"],
                    chunk_ids=tuple(line["chunk_ids"]),
                )
                for line in row["kept"]
            ],
            dropped=[(d["text"], d["reason"]) for d in row.get("dropped", [])],
            rewritten=[(d["text"], d["reason"]) for d in row.get("rewritten", [])],
        )
        for row in payload["turns"]
    ]


def format_structural(report: StructuralReport) -> str:
    lines: list[str] = []
    lines.append(
        f"Harness {report.harness} — structural grounding"
        + (f" @ {report.commit}" if report.commit else "")
    )
    grouped = report.by_turn()
    lines.append(
        f"  guard calls: {len(report.turns)}   "
        f"turns carrying a device-specific claim: {len(grouped)}"
    )
    lines.append(
        f"  device-specific spans: {len(report.spans)}   "
        f"cited: {len(report.cited_spans)}   uncited: {len(report.failing)}"
    )
    lines.append(
        f"  STRUCTURAL GROUNDING RATE (spans): {_pct(report.span_rate)}"
        f"   (turns: {_pct(report.turn_rate)})"
    )
    lines.append(
        f"  distinct cited claims: {len(distinct_claims(report.cited_spans))}"
    )
    dropped = sum(len(t.dropped) for t in report.turns)
    rewritten = sum(len(t.rewritten) for t in report.turns)
    lines.append(f"  guard dropped {dropped} line(s), rewrote {rewritten}")
    lines.append(f"  firmware-version tokens let through: {len(report.leaks)}")
    lines.append("")
    if report.failing:
        lines.append("  Failing spans — every one, with scenario, turn and text:")
        for span in report.failing:
            lines.append(
                f"    [{span.label}] kind={span.kind} span={span.span!r} "
                f"({span.reason})"
            )
            lines.append(f"      line: {span.line_text}")
    else:
        lines.append("  No failing spans: every device-specific claim the guard let")
        lines.append("  through carried a citation the guard accepted.")
    return "\n".join(lines)


def format_semantic(verdicts: Sequence[SemanticVerdict]) -> str:
    lines: list[str] = []
    sampled = [v for v in verdicts if v.origin == "sampled-cited"]
    failures = [v for v in verdicts if v.origin == "structural-failure"]
    lines.append("Semantic grounding — sampled, hand-graded (06 §7.4: no judge yet)")
    lines.append(
        f"  sampled cited claims: {len(sampled)}   "
        f"supported: {sum(v.score for v in sampled)}"
    )
    lines.append(
        f"  SAMPLED SEMANTIC RATE: {_pct(semantic_rate(verdicts, 'sampled-cited'))}"
    )
    if failures:
        lines.append(
            f"  structural failures also read by hand: {len(failures)}   "
            f"supported by a cited chunk: {sum(v.score for v in failures)}"
        )
    lines.append("")
    bad = [v for v in verdicts if v.score == 0]
    if bad:
        lines.append("  Not supported as stated:")
        for v in bad:
            lines.append(f"    [{v.verdict}] {v.claim}")
            lines.append(f"      cites: {', '.join(v.chunk_ids) or '<nothing>'}")
            lines.append(f"      {v.note}")
    else:
        lines.append("  Every graded claim is supported by its cited chunk as stated.")
    return "\n".join(lines)
