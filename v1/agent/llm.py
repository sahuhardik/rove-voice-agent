"""A thin Bedrock wrapper: Nova Micro for triage, Nova Pro for turn reasoning.

Two models, two jobs, and the split is the latency argument of `docs/06` §8.3
applied to text: classification runs on every turn and must be cheap; the
reasoning call runs once a turn and is allowed to cost something.

| call | model | job |
| --- | --- | --- |
| `classify` | `amazon.nova-micro-v1:0` | category, a shortlist of taxonomy ids, safety/scope flags, model-ID signals |
| `decide` | `amazon.nova-pro-v1:0` | hypothesis and next-step selection, given the state and the retrieved chunks |

**The contract is strict and small.** Both calls must return a single JSON
object; the reasoning call must return exactly `category`, `taxonomy_id`,
`next_step`, `hypothesis`, `escalate`, `reason`. Anything else — a refusal, a
preamble, prose around the JSON, a step id that is not in the legal set — is
treated as a failed call, and a failed call falls back to the rule-based
baseline step (`eval.baseline`). That is not a nicety: `docs/06` §3.1 says the
model chooses among what it is permitted to do, so a model that answers outside
the permitted set has not given a worse answer, it has given no answer.

What this module deliberately does **not** do: it does not decide whether to
escalate (that is `policy.escalation`), it does not filter candidates, and it
never sees a step the policy layer has already dropped. Its `escalate` field is
recorded as a vote and read by nothing — see `policy.escalation`'s docstring.

Credentials come from the ambient AWS profile. Region defaults to
`us-east-1` and is overridable with `ROVE_BEDROCK_REGION`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

DEFAULT_REGION = os.environ.get("ROVE_BEDROCK_REGION", "us-east-1")

#: Fast path. Classification only (`docs/06` §8.3's "small model for slots").
MICRO_MODEL_ID = os.environ.get("ROVE_MICRO_MODEL_ID", "amazon.nova-micro-v1:0")
#: Turn reasoning.
PRO_MODEL_ID = os.environ.get("ROVE_PRO_MODEL_ID", "amazon.nova-pro-v1:0")

#: Deterministic by default. A diagnostic step that changes between two
#: identical runs is not auditable, and `docs/06` §7.3 runs this harness on
#: every policy change.
TEMPERATURE = 0.0


class LLMError(RuntimeError):
    """The call failed, or the reply did not satisfy the contract."""


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class Classification:
    """Nova Micro's output: a shortlist, not a decision."""

    category: str = ""
    taxonomy_ids: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    model_signals: list[dict[str, str]] = field(default_factory=list)
    raw: str = ""


@dataclass
class TurnDecision:
    """Nova Pro's output. The six fields of the strict JSON contract."""

    category: str
    taxonomy_id: str
    next_step: str | None
    hypothesis: str
    escalate: bool
    reason: str
    raw: str = ""


class LLM(Protocol):
    name: str

    def classify(self, utterance: str) -> Classification: ...

    def decide(
        self,
        *,
        utterance: str,
        state_summary: str,
        options: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, str]],
    ) -> TurnDecision: ...


# --------------------------------------------------------------------------
# JSON parsing
# --------------------------------------------------------------------------


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first balanced JSON object out of a reply.

    Models wrap JSON in fences, in apologies, and in explanations of the JSON.
    This finds the object and ignores the rest; if there is no parseable object
    the call has failed, which the caller handles by falling back.
    """
    if not text:
        raise LLMError("empty reply")
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise LLMError(f"no JSON object in reply: {text[:160]!r}")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    parsed = json.loads(blob)
                except json.JSONDecodeError as exc:
                    raise LLMError(f"reply is not valid JSON: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise LLMError("top-level JSON value is not an object")
                return parsed
    raise LLMError(f"unbalanced JSON object in reply: {text[:160]!r}")


#: A taxonomy entry as `docs/02` writes it: two-to-four letters, a hyphen, two
#: digits. Used to pull the id back out of a label the model decorated.
_ENTRY_RE = re.compile(r"\b([A-Z]{2,4}-\d{2})\b")


def normalise_taxonomy_id(raw: str) -> str:
    """The entry the model meant, or `""` when it cannot be read.

    **Milestone 4.6, and this is a `docs/06` §3.1 boundary, not a leniency.**
    §3.1 says the model "chooses among what it is permitted to do", and the
    thing it is permitted to do is the **step**. `next_step` is therefore
    checked against `legal_ids` above and a miss is still fatal — an illegal
    step is not an answer, and that check is unchanged.

    `taxonomy_id` is a different kind of field: a **label on the step already
    chosen**, not a permission. `core._entry_for_step` says so in as many
    words — it honours the claimed entry "only when the option list agrees
    that the step sits under it; otherwise the option list wins", and resolves
    an invented id to the default rather than raising. Raising here meant that
    repair code could never run: the whole `TurnDecision` was destroyed over
    the label, and the turn dropped to the rule-based floor carrying a step
    nobody had reasoned about.

    EVAL-23 is the case. The option lines are rendered with their `docs/02`
    provenance in the description, so Nova Pro answered `"02 PWR-02"` — the
    right entry, with the document number it had just read in front of it. The
    step it chose was `STEP.ASK.CAMERA_RESTARTS_IN_HEAT`, which is legal, which
    is the step `docs/03` expects, and which is the branching question Harness
    B had recorded as "never asked" in every run since Milestone 4.1. The agent
    was asking it; the parser was throwing it away.

    So: uppercase, pull out the first `docs/02`-shaped id, and accept it if it
    is a real entry. Anything else returns `""`, which `core._entry_for_step`
    already treats as "the model named no entry I recognise — use the option
    list", and the raw value stays in `TurnDecision.raw` for the trace.
    """
    from eval import ontology  # local import: keeps module import cheap

    text = (raw or "").strip().upper()
    if text in ontology.TAXONOMY_CANDIDATES:
        return text
    match = _ENTRY_RE.search(text)
    if match and match.group(1) in ontology.TAXONOMY_CANDIDATES:
        return match.group(1)
    return ""


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

_CLASSIFY_SYSTEM = """\
You are the triage stage of a dash-cam support agent. You do not talk to the \
caller and you do not propose fixes. You read one caller utterance and label it.

Return ONE JSON object and nothing else:

{"category": "<one of WIFI FW APP REC SD PWR VID NO_MATCH OUT_OF_SCOPE>",
 "taxonomy_ids": ["<up to 3 ids from the list below, most likely first>"],
 "flags": ["<zero or more of: hazard, driving, footage_at_stake, out_of_scope, \
requests_human, firmware_update_in_progress, vehicle_electrical>"],
 "model_signals": [{"signal": \
"<ssid|lens_count|touch_or_buttons|connector|serial|band|in_box|name>", \
"value": "<what the caller said>"}]}

Rules:
- NO_MATCH when no entry below describes the symptom. Forcing a symptom into \
the nearest category is the worst failure available to you; say NO_MATCH.
- OUT_OF_SCOPE for refunds, returns, warranty, RMA, billing, or a non-Rove device.
- flag "hazard" only for smoke, burning smell, swelling, melting, heat damage \
or exposed wiring.
- flag "vehicle_electrical" when a hardwire kit, a third-party installation, \
vehicle wiring or a drained car battery is implicated.
- flag "firmware_update_in_progress" when an update is running or stalled right now.
- "model_signals" is usually empty. A caller merely saying "R2" or "the 4K one" \
is a weak signal with signal="name"; never invent one.

Taxonomy entries:
"""

_DECIDE_SYSTEM = """\
You are the reasoning stage of a dash-cam voice support agent.

Your ONLY job: pick the single best next diagnostic step FROM THE OPTIONS GIVEN, \
and state the hypothesis it tests. You may not invent a step. You may not propose \
two steps. Options that were filtered out are not available to you, for safety \
reasons you are not shown.

Choose the cheapest step that SPLITS the live causes — not the most common fix. \
A step that usually works but tells you nothing when it fails is worth less on a \
voice call, where every step costs a turn and the caller's patience.

Return ONE JSON object and nothing else, with exactly these keys:

{"category": "<WIFI|FW|APP|REC|SD|PWR|VID|NO_MATCH|OUT_OF_SCOPE>",
 "taxonomy_id": "<the entry your chosen step belongs to, from the options>",
 "next_step": "<the exact STEP.* id you chose, or null>",
 "hypothesis": "<one sentence: the cause you now think most likely>",
 "escalate": <true|false>,
 "reason": "<one sentence: why this step and not the others>"}

Rules:
- "next_step" MUST be copied exactly from the options. Any other value is discarded.
- Never state a firmware version, and never guess a model, a capacity, a speed \
class or a menu path. If a device-specific fact is not in the excerpts, do not \
assert it.
- Prefer a question that re-ranks the causes over an action the caller must perform.
"""


def _taxonomy_catalogue() -> str:
    from eval import ontology  # local import: keeps module import cheap

    lines = []
    for taxonomy_id in ontology.TAXONOMY_CANDIDATES:
        if taxonomy_id in ("NO_MATCH", "OUT_OF_SCOPE"):
            continue
        lines.append(f"- {taxonomy_id}: {_TAXONOMY_BLURBS.get(taxonomy_id, '')}")
    return "\n".join(lines)


#: One line per entry, written from `docs/02`'s "Symptom (caller)" field — the
#: caller's words, not the diagnosis, because that is what the classifier is
#: matching against.
_TAXONOMY_BLURBS: dict[str, str] = {
    "WIFI-01": "phone joins the camera's network then drops back to cellular / says no internet",
    "WIFI-02": "the camera's network does not appear in the phone's Wi-Fi list at all",
    "WIFI-03": "password rejected when joining the camera's network",
    "WIFI-04": "connection holds for a few minutes then drops, repeatedly",
    "WIFI-05": "connected, but playback or download is unusably slow",
    "FW-01": "a firmware update is running now and appears stalled partway",
    "FW-02": "the camera will not boot since an update — stuck on the logo",
    "FW-03": "something that worked before the update stopped working after it",
    "FW-04": "the caller cannot carry out the update at all (no computer, file confusion)",
    "APP-01": "phone is on the camera's Wi-Fi but the app says no device found",
    "APP-02": "the app broke after a phone OS update",
    "APP-03": "the app never gets past a permission or setup screen",
    "APP-04": "worked on the old phone, will not pair with a new one",
    "REC-01": "no footage of a specific incident the caller needs",
    "REC-02": "camera is on but never starts recording",
    "REC-03": "loop recording overwrote files the caller wanted to keep",
    "REC-04": "nothing recorded while the car was parked",
    "SD-01": "card error message, or the camera does not see the card",
    "SD-02": "card full and recording stopped instead of looping",
    "SD-03": "files on the card are corrupt or will not open",
    "SD-04": "a card keeps failing or needs reformatting repeatedly",
    "PWR-01": "camera is dead — no lights, no screen, nothing on plugging in",
    "PWR-02": "camera gets hot, or misbehaves in heat",
    "PWR-03": "camera does not power down when parked / drains the car battery",
    "PWR-04": "camera does not keep the date and time",
    "VID-01": "footage is blurry or number plates are unreadable",
    "VID-02": "reflections, glare, or poor night footage",
    "VID-03": "no audio on recordings, or a wrong timestamp",
}


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


class BedrockLLM:
    """`bedrock-runtime` Converse, two model ids, no SDK beyond boto3.

    The client is built lazily so that importing this module costs nothing and
    so that a machine with no AWS credentials can still run the unit tests.
    """

    name = "bedrock-nova"

    def __init__(
        self,
        *,
        region: str = DEFAULT_REGION,
        micro_model_id: str = MICRO_MODEL_ID,
        pro_model_id: str = PRO_MODEL_ID,
        client: Any | None = None,
        max_attempts: int = 6,
        read_timeout: int = 30,
    ) -> None:
        self.region = region
        self.micro_model_id = micro_model_id
        self.pro_model_id = pro_model_id
        self._client = client
        self._max_attempts = max_attempts
        self._read_timeout = read_timeout
        #: Populated on every call, for the trace.
        self.last_error: str = ""

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # imported here so stdlib-only tests do not need it
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    # `adaptive`, and the same shape `agent/store.py` already
                    # uses for Bedrock embeddings. Milestone 4.6: on-demand
                    # Bedrock throttles a Harness B sweep hard enough that a
                    # `ThrottlingException` was the *most common* reason a turn
                    # fell back to the rule-based floor — EVAL-07 and EVAL-27
                    # both lost turn 1 to it. A throttled call is not a model
                    # that had nothing to say, and scoring it as one makes the
                    # eval measure the account's rate limit rather than the
                    # agent. Client-side rate limiting plus more attempts is
                    # the boto-level fix; no model id and no AWS constraint
                    # (`docs/07` C-2) changes.
                    retries={"max_attempts": self._max_attempts, "mode": "adaptive"},
                    read_timeout=self._read_timeout,
                ),
            )
        return self._client

    def _converse(
        self, model_id: str, system: str, user: str, *, max_tokens: int = 600
    ) -> str:
        response = self.client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": TEMPERATURE,
                "topP": 1.0,
            },
        )
        blocks = response["output"]["message"]["content"]
        return "".join(block.get("text", "") for block in blocks)

    # ---- fast path --------------------------------------------------
    def classify(self, utterance: str) -> Classification:
        from eval import ontology

        system = _CLASSIFY_SYSTEM + _taxonomy_catalogue()
        raw = self._converse(
            self.micro_model_id, system, f'Caller said: "{utterance}"', max_tokens=400
        )
        parsed = parse_json_object(raw)

        category = str(parsed.get("category", "")).strip().upper()
        if category not in ontology.CATEGORIES:
            category = ""
        taxonomy_ids = [
            str(t).strip().upper()
            for t in parsed.get("taxonomy_ids", [])
            if str(t).strip().upper() in ontology.TAXONOMY_CANDIDATES
        ]
        flags = [str(f).strip().lower() for f in parsed.get("flags", []) if f]
        signals = [
            {"signal": str(s.get("signal", "")), "value": str(s.get("value", ""))}
            for s in parsed.get("model_signals", [])
            if isinstance(s, dict)
        ]
        return Classification(
            category=category,
            taxonomy_ids=taxonomy_ids[:3],
            flags=flags,
            model_signals=signals,
            raw=raw,
        )

    # ---- turn reasoning ---------------------------------------------
    def decide(
        self,
        *,
        utterance: str,
        state_summary: str,
        options: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, str]],
    ) -> TurnDecision:
        from eval import ontology

        legal_ids = {str(option["step_id"]) for option in options}
        user = _render_decide_prompt(utterance, state_summary, options, chunks)
        raw = self._converse(self.pro_model_id, _DECIDE_SYSTEM, user, max_tokens=700)
        parsed = parse_json_object(raw)

        missing = {
            "category",
            "taxonomy_id",
            "next_step",
            "hypothesis",
            "escalate",
            "reason",
        } - set(parsed)
        if missing:
            raise LLMError(f"reply is missing contract keys: {sorted(missing)}")

        next_step = parsed["next_step"]
        next_step = str(next_step).strip() if next_step else None
        if next_step is not None and next_step not in legal_ids:
            raise LLMError(
                f"chose {next_step!r}, which is not in the legal option set — "
                "a step outside the permitted set is not an answer (06 §3.1)"
            )

        taxonomy_id = normalise_taxonomy_id(str(parsed["taxonomy_id"]))
        category = str(parsed["category"]).strip().upper()
        if category not in ontology.CATEGORIES:
            category = ontology.category_of(taxonomy_id) if taxonomy_id else ""

        return TurnDecision(
            category=category,
            taxonomy_id=taxonomy_id,
            next_step=next_step,
            hypothesis=str(parsed["hypothesis"]).strip(),
            escalate=bool(parsed["escalate"]),
            reason=str(parsed["reason"]).strip(),
            raw=raw,
        )


def _render_decide_prompt(
    utterance: str,
    state_summary: str,
    options: Sequence[dict[str, Any]],
    chunks: Sequence[dict[str, str]],
) -> str:
    lines = [f'CALLER SAID: "{utterance}"', "", "DIAGNOSTIC STATE:", state_summary, ""]
    live = []
    for option in options:
        entry = str(option["taxonomy_id"])
        if entry not in live:
            live.append(entry)
    lines.append(
        "LIVE CAUSES — the taxonomy entries still in contention this turn: "
        + ", ".join(live)
    )
    lines.append("")
    lines.append("OPTIONS — the only steps you may choose from:")
    for option in options:
        lines.append(
            f"  {option['step_id']}  [{option['taxonomy_id']}]  {option['description']}"
        )
        # Milestone 4.6: `docs/06` §3.5 ranks by "expected information gain
        # across the live causes" and says Phase 1 delegates that ranking to
        # the model "which sees the live causes". Until now it saw neither —
        # it was ranking by information gain with no statement of what any
        # option's answer would gain. These lines are `docs/02`'s own readings
        # (`agent/answers.ANSWER_RULES`), not a second opinion about them.
        for split in option.get("discriminates") or []:
            lines.append(f"      → tells apart — {split}")
    lines.append("")
    if chunks:
        lines.append(
            "TIER-1 EXCERPTS (the only device-specific facts you may rely on; "
            "cite nothing else):"
        )
        for chunk in chunks:
            lines.append(f"  [{chunk['chunk_id']}] {chunk['text']}")
    else:
        lines.append(
            "TIER-1 EXCERPTS: none cleared for this model confidence. Assert no "
            "device-specific fact at all."
        )
    lines.append("")
    lines.append("Reply with the JSON object only.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Test / offline doubles
# --------------------------------------------------------------------------


class NullLLM:
    """An LLM that is always unavailable.

    Used by `--no-llm` and by the fallback test. It raises rather than
    returning an empty answer, because "the call failed" and "the model had
    nothing to say" need to take different paths through `core`.
    """

    name = "null"

    def classify(self, utterance: str) -> Classification:
        raise LLMError("NullLLM: no model configured")

    def decide(self, **kwargs: Any) -> TurnDecision:
        raise LLMError("NullLLM: no model configured")
