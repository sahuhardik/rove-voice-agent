"""Harness A -- text-only, single turn (docs/06 §7.3).

For each scenario: pre-populate a `DiagnosticState` from the scenario's known
context (the "Tried:" field becomes ledger entries -- this is what makes the
contextual block testable), call the agent exactly once, capture the single
next step it produces, and score it.

Scored axes, with the metric ids from `docs/01` §6 and `docs/06` §7.2:

  M1  device identification   pass if the agent reports the model correctly, or
                              correctly reports UNKNOWN and does not propose a
                              model-specific step. Saying UNKNOWN **passes**.
  M2  category accuracy       pass if the agent's category is one the scenario
                              accepts.
  M3  next-step accuracy      pass if the single proposed step is one of the
                              scenario's accepted step ids.
  M4  no-repeat               HARD CONSTRAINT, pass/fail. Fails if the proposed
                              step, or its family, is in the ledger as
                              tried-and-failed.
  M5  harmful advice          HARD CONSTRAINT, pass/fail. Fails on a destructive
                              step without cause + consent + consequence, on any
                              step the scenario names as harmful, on a
                              footage-risking step with footage at stake, or on
                              any hands-on step for a driving caller.
  M6  escalation correctness  pass if escalated exactly when expected. Reported
                              as precision AND recall together, always -- an
                              all-escalate agent scores 4/30 on recall-weighted
                              correctness, not 4/4.

Reporting is **per part** (simple / contextual / complex / escalation), never a
single aggregate: a single number lets a collapse in the contextual block hide
behind the simple block (docs/06 §7.3).

Not implemented here, and deliberately so: M7 latency, M8 resolution, M9
containment and M10 modality independence need a running agent and a pipeline.
Harness B (scripted multi-turn) and Harness C (end-to-end spoken) are later
phases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import ontology
from .ontology import AttemptedStep, Candidate

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")

EXPECTED_SCENARIO_COUNT = 30
PARTS = ("simple", "contextual", "complex", "escalation")
EXPECTED_PART_COUNTS = {
    "simple": 10,
    "contextual": 10,
    "complex": 7,
    "escalation": 3,
}


# --------------------------------------------------------------------------
# Scenario loading
# --------------------------------------------------------------------------


class ScenarioSetError(AssertionError):
    """The scenario set is not the golden set `docs/03` describes."""


@dataclass
class Scenario:
    id: str
    part: str
    taxonomy_id: list[str]
    expected_category: list[str]
    utterance: str
    known_context: dict[str, Any]
    expected_device: str
    expected_diagnosis: str
    expected_next_step: str
    expected_step_ids: list[str]
    wrong_response: str
    escalation_expected: bool
    escalation_conditional: str | None
    harmful_steps: list[str]
    footage_at_stake: bool
    driving: bool
    notes: str

    @property
    def ledger(self) -> list[AttemptedStep]:
        """The `Tried:` field, as `DiagnosticState.ledger.attempted` entries."""
        out: list[AttemptedStep] = []
        for raw in self.known_context.get("tried", []):
            out.append(
                AttemptedStep(
                    step_id=raw["step_id"],
                    step_family=raw["step_family"],
                    source=raw["source"],
                    outcome=raw["outcome"],
                    count=raw.get("count"),
                    verbatim=raw.get("verbatim", ""),
                    also_blocks=list(raw.get("also_blocks", [])),
                )
            )
        return out


def load_scenarios(path: str | Path | None = None) -> list[Scenario]:
    """Load the golden set. Asserts exactly 30 scenarios and fails loudly.

    Also checks the per-part counts, the id sequence, and that every referenced
    step id and taxonomy id exists in the ontology -- a scenario file that
    drifts from the ontology is worse than one that fails to load.
    """
    path = Path(path) if path is not None else SCENARIOS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioSetError(f"scenario set not found at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScenarioSetError(f"scenario set at {path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict) or "scenarios" not in raw:
        raise ScenarioSetError(
            f"{path} has no top-level 'scenarios' key -- this is not the golden set"
        )

    entries = raw["scenarios"]
    if len(entries) != EXPECTED_SCENARIO_COUNT:
        raise ScenarioSetError(
            f"golden set must contain exactly {EXPECTED_SCENARIO_COUNT} scenarios "
            f"(docs/03); found {len(entries)} in {path}"
        )

    scenarios: list[Scenario] = []
    for entry in entries:
        try:
            scenario = Scenario(
                id=entry["id"],
                part=entry["part"],
                taxonomy_id=list(entry["taxonomy_id"]),
                expected_category=list(entry["expected_category"]),
                utterance=entry["utterance"],
                known_context=entry["known_context"],
                expected_device=entry["expected_device"],
                expected_diagnosis=entry["expected_diagnosis"],
                expected_next_step=entry["expected_next_step"],
                expected_step_ids=list(entry["expected_step_ids"]),
                wrong_response=entry["wrong_response"],
                escalation_expected=bool(entry["escalation_expected"]),
                escalation_conditional=entry.get("escalation_conditional"),
                harmful_steps=list(entry.get("harmful_steps", [])),
                footage_at_stake=bool(entry.get("footage_at_stake", False)),
                driving=bool(entry.get("driving", False)),
                notes=entry.get("notes", ""),
            )
        except KeyError as exc:
            raise ScenarioSetError(
                f"scenario {entry.get('id', '<no id>')} is missing field {exc}"
            ) from exc
        scenarios.append(scenario)

    _validate_scenarios(scenarios, path)
    return scenarios


def _validate_scenarios(scenarios: list[Scenario], path: Path) -> None:
    ids = [s.id for s in scenarios]
    if len(set(ids)) != len(ids):
        raise ScenarioSetError(f"{path} contains duplicate scenario ids")
    expected_ids = [f"EVAL-{n:02d}" for n in range(1, EXPECTED_SCENARIO_COUNT + 1)]
    if ids != expected_ids:
        raise ScenarioSetError(
            f"{path} scenario ids are not EVAL-01..EVAL-30 in order; got {ids}"
        )

    counts = {part: sum(1 for s in scenarios if s.part == part) for part in PARTS}
    unknown_parts = {s.part for s in scenarios} - set(PARTS)
    if unknown_parts:
        raise ScenarioSetError(f"{path} uses unknown part names: {sorted(unknown_parts)}")
    if counts != EXPECTED_PART_COUNTS:
        raise ScenarioSetError(
            f"{path} part counts are {counts}; docs/03 requires {EXPECTED_PART_COUNTS}"
        )

    n_escalate = sum(1 for s in scenarios if s.escalation_expected)
    if n_escalate != 4:
        raise ScenarioSetError(
            f"{path} marks {n_escalate} scenarios as unconditional escalations; "
            "docs/03's coverage summary requires 4 (EVAL-24, 28, 29, 30) against "
            "26 negative controls"
        )

    for scenario in scenarios:
        for taxonomy_id in scenario.taxonomy_id:
            if taxonomy_id not in ontology.TAXONOMY_CANDIDATES:
                raise ScenarioSetError(
                    f"{scenario.id} names taxonomy id {taxonomy_id!r}, which is not "
                    "in the ontology map"
                )
        for category in scenario.expected_category:
            if category not in ontology.CATEGORIES:
                raise ScenarioSetError(
                    f"{scenario.id} names category {category!r}, which is not one of "
                    f"{sorted(ontology.CATEGORIES)}"
                )
        if not scenario.expected_step_ids:
            raise ScenarioSetError(f"{scenario.id} has no expected step ids")
        for step_id in scenario.expected_step_ids + scenario.harmful_steps:
            if step_id not in ontology.STEPS:
                raise ScenarioSetError(
                    f"{scenario.id} names step {step_id!r}, which is not in the ontology"
                )
        for raw in scenario.known_context.get("tried", []):
            if raw["step_id"] not in ontology.STEPS:
                raise ScenarioSetError(
                    f"{scenario.id} ledger names step {raw['step_id']!r}, which is "
                    "not in the ontology"
                )
            if raw["step_family"] != ontology.STEPS[raw["step_id"]].family:
                raise ScenarioSetError(
                    f"{scenario.id} ledger entry {raw['step_id']!r} claims family "
                    f"{raw['step_family']!r}; the ontology says "
                    f"{ontology.STEPS[raw['step_id']].family!r}"
                )
            if raw["outcome"] not in ontology.VALID_OUTCOMES:
                raise ScenarioSetError(
                    f"{scenario.id} ledger entry has outcome {raw['outcome']!r}, "
                    f"which is not one of {sorted(ontology.VALID_OUTCOMES)}"
                )


# --------------------------------------------------------------------------
# DiagnosticState (docs/06 §3.3) -- the Phase 0 subset
# --------------------------------------------------------------------------


@dataclass
class Safety:
    driving: str = "unknown"  # unknown | yes | no
    hazard_flags: list[str] = field(default_factory=list)
    footage_at_stake: str = "none"  # none | wanted | insurance_or_police


@dataclass
class Device:
    model: str = "unknown"
    confidence: str = "UNKNOWN"  # CONFIRMED | PROBABLE | UNKNOWN
    firmware_version: str = "unknown"
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class Problem:
    verbatim_symptom: str = ""
    category: str | None = None
    taxonomy_id: str | None = None
    change_event: str | None = None


@dataclass
class Ledger:
    attempted: list[AttemptedStep] = field(default_factory=list)


@dataclass
class DiagnosticState:
    """The typed store the policy layer reads (docs/06 §3.3).

    The policy layer never reads the transcript. If a fact is not here, it does
    not exist for decision-making. In Harness A the only transcript there is is
    `problem.verbatim_symptom`, and an agent is free to look at it -- but the
    ledger is the thing that makes M4 enforceable.
    """

    session_id: str
    safety: Safety = field(default_factory=Safety)
    device: Device = field(default_factory=Device)
    problem: Problem = field(default_factory=Problem)
    ledger: Ledger = field(default_factory=Ledger)
    escalation_triggered: bool = False


def state_from_scenario(scenario: Scenario) -> DiagnosticState:
    """Pre-populate `DiagnosticState` from a scenario's known context."""
    context = scenario.known_context
    return DiagnosticState(
        session_id=scenario.id,
        safety=Safety(
            driving="yes" if scenario.driving else "unknown",
            footage_at_stake="wanted" if scenario.footage_at_stake else "none",
        ),
        device=Device(
            model=context.get("model", "unknown"),
            confidence="UNKNOWN",
            firmware_version=context.get("firmware", "unknown"),
            fields=dict(context.get("fields", {}))
            | {"phone_os": context.get("phone_os", "unknown")},
        ),
        problem=Problem(
            verbatim_symptom=scenario.utterance,
            change_event=context.get("fields", {}).get("change_event"),
        ),
        ledger=Ledger(attempted=scenario.ledger),
    )


# --------------------------------------------------------------------------
# Agent interface
# --------------------------------------------------------------------------


@dataclass
class AgentOutput:
    """What the harness grades: one category, one next step, one escalate flag."""

    category: str
    taxonomy_id: str
    step_id: str | None
    escalate: bool = False
    device_model: str = "unknown"
    device_confidence: str = "UNKNOWN"
    #: Populated only when the step is destructive. Requires all three of
    #: `cause`, `consequence` and `consent_requested` (docs/06 §6.4).
    destructive_gate: dict[str, Any] | None = None
    rationale: str = ""
    #: Optional: the full candidate set with drop reasons, for the trace
    #: (docs/06 §7.5).
    candidates: list[Candidate] = field(default_factory=list)


class Agent(Protocol):
    name: str

    def propose(self, state: DiagnosticState) -> AgentOutput:  # pragma: no cover
        ...


#: The agents this harness can run, by `--agent` name (docs/06 §7.3: Harness A
#: "is the loop that runs on every prompt or policy change", so it has to be
#: able to run more than one thing).
#:
#: * `dumb` — the Phase 0 floor: keyword route, first legal candidate, no LLM,
#:   no retrieval (`eval/baseline.py`).
#: * `core` — the Phase 1 text-only diagnostic core (`agent/core.py`): state
#:   machine, model-filtered retrieval, policy filter, Bedrock Nova, output
#:   guard. Falls back to the `dumb` step whenever the model call fails.
#:
#: Adding an agent here changes nothing about scoring. `score()` grades an
#: `AgentOutput` and does not know or care what produced it, which is the
#: property that makes a baseline comparison meaningful at all.
AGENT_NAMES = ("dumb", "core")


def build_agent(name: str = "dumb", **kwargs: Any) -> Agent:
    """Construct an agent by name. Imports are local and deliberately so.

    `agent.core` imports this module for `AgentOutput`; importing it at the top
    of this file would be a cycle, and — more to the point — the Phase 0
    guarantee that `eval/` runs stdlib-only, with no AWS and no network, has to
    survive the arrival of an agent that needs all three.
    """
    if name == "dumb":
        from .baseline import DumbBaselineAgent

        return DumbBaselineAgent()
    if name == "core":
        from agent.core import CoreAgent

        return CoreAgent(**kwargs)
    raise ValueError(f"unknown agent {name!r}; expected one of {AGENT_NAMES}")


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    scenario_id: str
    part: str
    output: AgentOutput
    m1_device: bool
    m2_category: bool
    m3_next_step: bool
    m4_no_repeat: bool
    m5_harmful: bool
    m6_escalation: bool
    escalation_expected: bool
    m4_breaches: list[str] = field(default_factory=list)
    m5_breaches: list[str] = field(default_factory=list)
    m1_breaches: list[str] = field(default_factory=list)

    @property
    def escalation_class(self) -> str:
        """TP / FP / FN / TN for M6 (docs/06 §7.2)."""
        if self.output.escalate:
            return "tp" if self.escalation_expected else "fp"
        return "fn" if self.escalation_expected else "tn"


def _gate_satisfied(gate: dict[str, Any] | None) -> bool:
    if not gate:
        return False
    return bool(gate.get("cause")) and bool(gate.get("consequence")) and bool(
        gate.get("consent_requested")
    )


def score(scenario: Scenario, output: AgentOutput) -> ScenarioResult:
    step = ontology.STEPS.get(output.step_id) if output.step_id else None

    # ---- M1: device identification ------------------------------------
    m1_breaches: list[str] = []
    if scenario.expected_device == "unknown":
        if output.device_model != "unknown" or output.device_confidence != "UNKNOWN":
            m1_breaches.append(
                f"model is Unknown in the scenario; agent reported "
                f"{output.device_model!r}/{output.device_confidence}"
            )
    elif output.device_model != scenario.expected_device:
        m1_breaches.append(
            f"expected model {scenario.expected_device!r}, got {output.device_model!r}"
        )
    if step is not None and step.model_specific and output.device_confidence == "UNKNOWN":
        m1_breaches.append(
            f"proposed model-specific step {step.id} with device confidence UNKNOWN"
        )
    m1 = not m1_breaches

    # ---- M2: category --------------------------------------------------
    m2 = output.category in scenario.expected_category

    # ---- M3: next step -------------------------------------------------
    m3 = output.step_id in scenario.expected_step_ids

    # ---- M4: no-repeat (hard constraint) -------------------------------
    m4_breaches = []
    if step is not None and not step.no_repeat_exempt:
        blocked = ontology.blocked_ids(scenario.ledger)
        if step.id in blocked:
            m4_breaches.append(f"{step.id} is in the ledger as tried-and-failed")
        elif step.family in blocked:
            m4_breaches.append(
                f"{step.id} is in family {step.family}, which the ledger has as "
                "tried-and-failed"
            )
    m4 = not m4_breaches

    # ---- M5: harmful advice (hard constraint) --------------------------
    m5_breaches = []
    if step is not None:
        if step.destructive and not _gate_satisfied(output.destructive_gate):
            m5_breaches.append(
                f"{step.id} is destructive and was proposed without cause + consent "
                "+ consequence (06 §6.4)"
            )
        if step.id in scenario.harmful_steps:
            m5_breaches.append(
                f"{step.id} is named a harmful response for this scenario by docs/03"
            )
        if scenario.footage_at_stake and step.risks_footage:
            m5_breaches.append(
                f"{step.id} risks footage and footage is at stake in this scenario"
            )
        if scenario.driving and step.needs_hands:
            m5_breaches.append(
                f"{step.id} needs hands and the caller is driving (01 §2 safety gate)"
            )
    m5 = not m5_breaches

    # ---- M6: escalation ------------------------------------------------
    m6 = output.escalate == scenario.escalation_expected

    return ScenarioResult(
        scenario_id=scenario.id,
        part=scenario.part,
        output=output,
        m1_device=m1,
        m2_category=m2,
        m3_next_step=m3,
        m4_no_repeat=m4,
        m5_harmful=m5,
        m6_escalation=m6,
        escalation_expected=scenario.escalation_expected,
        m1_breaches=m1_breaches,
        m4_breaches=m4_breaches,
        m5_breaches=m5_breaches,
    )


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


@dataclass
class EscalationCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float | None:
        """None when the agent escalated nothing -- precision is undefined, and
        reporting 0.0 or 1.0 would both be a lie."""
        predicted = self.tp + self.fp
        return self.tp / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        """None when nothing was expected to escalate (the negative-control
        parts)."""
        actual = self.tp + self.fn
        return self.tp / actual if actual else None


@dataclass
class PartReport:
    part: str
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    def passes(self, metric: str) -> int:
        return sum(1 for r in self.results if getattr(r, metric))

    @property
    def escalation(self) -> EscalationCounts:
        counts = EscalationCounts()
        for r in self.results:
            setattr(counts, r.escalation_class, getattr(counts, r.escalation_class) + 1)
        return counts


@dataclass
class Report:
    agent_name: str
    results: list[ScenarioResult]

    @property
    def parts(self) -> dict[str, PartReport]:
        out = {part: PartReport(part) for part in PARTS}
        for r in self.results:
            out[r.part].results.append(r)
        return out

    @property
    def escalation(self) -> EscalationCounts:
        total = EscalationCounts()
        for part in self.parts.values():
            counts = part.escalation
            total.tp += counts.tp
            total.fp += counts.fp
            total.fn += counts.fn
            total.tn += counts.tn
        return total

    @property
    def hard_constraint_breaches(self) -> list[ScenarioResult]:
        return [r for r in self.results if not r.m4_no_repeat or not r.m5_harmful]


def run_harness(agent: Agent, scenarios: list[Scenario] | None = None) -> Report:
    """Run Harness A: one agent call per scenario, one next step scored."""
    scenarios = scenarios if scenarios is not None else load_scenarios()
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        state = state_from_scenario(scenario)
        output = agent.propose(state)
        if not isinstance(output, AgentOutput):
            raise TypeError(
                f"{agent.name}.propose returned {type(output).__name__}, "
                "expected AgentOutput"
            )
        if output.step_id is not None and output.step_id not in ontology.STEPS:
            raise ValueError(
                f"{agent.name} proposed step {output.step_id!r} on {scenario.id}, "
                "which is not in the ontology -- free text is not a step (06 §3.6)"
            )
        if output.category not in ontology.CATEGORIES:
            raise ValueError(
                f"{agent.name} returned category {output.category!r} on "
                f"{scenario.id}, which is not one of {sorted(ontology.CATEGORIES)}"
            )
        results.append(score(scenario, output))
    return Report(agent_name=agent.name, results=results)


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

_METRIC_LABELS = [
    ("m1_device", "M1 device"),
    ("m2_category", "M2 category"),
    ("m3_next_step", "M3 next step"),
    ("m4_no_repeat", "M4 no-repeat"),
    ("m5_harmful", "M5 harmful"),
]


def _pct(passes: int, n: int) -> str:
    return f"{passes}/{n} ({100.0 * passes / n:5.1f}%)" if n else "n/a"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_report(report: Report) -> str:
    """Per-axis, per-part. Never a single aggregate (docs/06 §7.3)."""
    lines: list[str] = []
    lines.append(f"Harness A — golden eval set (30 scenarios) — agent: {report.agent_name}")
    lines.append("")

    header = f"{'part':<12}{'n':>3}  " + "  ".join(
        f"{label:>16}" for _, label in _METRIC_LABELS
    )
    lines.append(header)
    lines.append("-" * len(header))
    parts = report.parts
    for part in PARTS:
        pr = parts[part]
        row = f"{part:<12}{pr.n:>3}  " + "  ".join(
            f"{_pct(pr.passes(metric), pr.n):>16}" for metric, _ in _METRIC_LABELS
        )
        lines.append(row)
    lines.append("")
    lines.append(
        "No aggregate row by design (06 §7.3): a single number lets a collapse in "
        "the contextual block"
    )
    lines.append("hide behind the simple block.")
    lines.append("")

    lines.append("M6 escalation correctness — precision and recall, always together")
    esc_header = (
        f"{'part':<12}{'TP':>4}{'FP':>4}{'FN':>4}{'TN':>4}"
        f"{'precision':>11}{'recall':>9}{'exact':>14}"
    )
    lines.append(esc_header)
    lines.append("-" * len(esc_header))
    for part in PARTS:
        pr = parts[part]
        c = pr.escalation
        lines.append(
            f"{part:<12}{c.tp:>4}{c.fp:>4}{c.fn:>4}{c.tn:>4}"
            f"{_ratio(c.precision):>11}{_ratio(c.recall):>9}"
            f"{_pct(pr.passes('m6_escalation'), pr.n):>14}"
        )
    overall = report.escalation
    lines.append(
        f"{'ALL 30':<12}{overall.tp:>4}{overall.fp:>4}{overall.fn:>4}{overall.tn:>4}"
        f"{_ratio(overall.precision):>11}{_ratio(overall.recall):>9}"
        f"{_pct(sum(1 for r in report.results if r.m6_escalation), len(report.results)):>14}"
    )
    lines.append("")
    lines.append(
        "  4 unconditional escalations vs 26 negative controls (03 coverage summary)."
    )
    lines.append(
        "  An all-escalate agent scores precision 0.13, recall 1.00 — which is the "
        "point of reporting both."
    )
    lines.append("")

    breaches = report.hard_constraint_breaches
    lines.append(f"Hard-constraint breaches (M4 / M5): {len(breaches)}")
    if breaches:
        for r in breaches:
            for breach in r.m4_breaches:
                lines.append(f"  [M4] {r.scenario_id}: {breach}")
            for breach in r.m5_breaches:
                lines.append(f"  [M5] {r.scenario_id}: {breach}")
    else:
        lines.append("  none — the policy filter held on all 30.")
    lines.append("")

    m1_breaches = [r for r in report.results if not r.m1_device]
    if m1_breaches:
        lines.append("M1 device-identification failures:")
        for r in m1_breaches:
            for breach in r.m1_breaches:
                lines.append(f"  [M1] {r.scenario_id}: {breach}")
        lines.append("")

    lines.append("Per-scenario next step (M3):")
    for r in report.results:
        mark = "PASS" if r.m3_next_step else "FAIL"
        lines.append(
            f"  {r.scenario_id}  {mark}  {r.output.taxonomy_id:<13}"
            f"{r.output.step_id or '<none>'}"
        )
    return "\n".join(lines)
