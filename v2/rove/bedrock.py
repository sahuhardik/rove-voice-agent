"""Thin wrapper over the Bedrock Converse API."""
from __future__ import annotations

import functools
import json
import re
import time
from typing import Any

import boto3
from botocore.config import Config

from . import config


@functools.lru_cache(maxsize=1)
def client():
    return boto3.client(
        "bedrock-runtime",
        region_name=config.REGION,
        config=Config(read_timeout=900, retries={"max_attempts": 4, "mode": "adaptive"}),
    )


def converse(
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> dict[str, Any]:
    """One Converse call. Returns the raw response (output.message, stopReason, usage).

    Model ids starting with "ollama:" (e.g. "ollama:qwen3:8b") run on a local Ollama server.
    """
    if model.startswith("ollama:"):
        return _ollama(model[7:], messages, system, max_tokens, temperature)
    kwargs: dict[str, Any] = {
        "modelId": model,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if temperature is not None:
        kwargs["inferenceConfig"]["temperature"] = temperature
    if system:
        kwargs["system"] = [{"text": system}] if isinstance(system, str) else system
    if tools:
        kwargs["toolConfig"] = {"tools": tools}
    for attempt in range(3):
        try:
            return client().converse(**kwargs)
        except client().exceptions.ThrottlingException:
            time.sleep(2 * (attempt + 1))
    return client().converse(**kwargs)


def _ollama(model, messages, system, max_tokens, temperature):
    import urllib.request

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system if isinstance(system, str) else "".join(b.get("text", "") for b in system)})
    for m in messages:
        msgs.append({"role": m["role"], "content": "".join(b.get("text", "") for b in m["content"])})
    body = {"model": model, "messages": msgs, "stream": False, "think": False, "keep_alive": "30m",
            "options": {"num_predict": max_tokens, "num_ctx": config.OLLAMA_NUM_CTX,
                        **({"temperature": temperature} if temperature is not None else {})}}
    req = urllib.request.Request(config.OLLAMA_URL + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    return {"output": {"message": {"role": "assistant", "content": [{"text": d["message"]["content"]}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": d.get("prompt_eval_count", 0), "outputTokens": d.get("eval_count", 0)},
            "metrics": {"latencyMs": int(d.get("total_duration", 0) / 1e6)}}


#: Errors that mean "this model won't serve us right now", not "the request is wrong".
UNAVAILABLE = ("AccessDeniedException", "ResourceNotFoundException", "ThrottlingException",
               "ServiceUnavailableException", "ModelNotReadyException")

log = __import__("logging").getLogger("rove.bedrock")


def converse_with_fallback(models: list[str], messages: list[dict[str, Any]], **kwargs: Any) -> tuple[dict[str, Any], str]:
    """Try each model in order; return (response, model_used). Re-raise if all are unavailable."""
    from botocore.exceptions import ClientError

    last: Exception | None = None
    candidates = list(dict.fromkeys(m for m in models if m))
    # Skip models refused in the last few minutes, unless nothing else is left.
    live = [m for m in candidates if _refused_until.get(m, 0) < time.time()] or candidates
    for model in live:
        try:
            resp = converse(model, messages, **kwargs)
            _refused_until.pop(model, None)
            return resp, model
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in UNAVAILABLE:
                raise
            log.warning("model %s unavailable (%s); trying the next one", model, str(e)[:160])
            _refused_until[model] = time.time() + RETRY_REFUSED_AFTER_S
            last = e
    raise last  # type: ignore[misc]


#: How long to stop trying a model that refused us (e.g. a billing problem).
RETRY_REFUSED_AFTER_S = 300
_refused_until: dict[str, float] = {}


def text_of(response: dict[str, Any]) -> str:
    return "".join(b.get("text", "") for b in response["output"]["message"]["content"])


def ask(model: str, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
    resp = converse(model, [{"role": "user", "content": [{"text": prompt}]}], system=system, max_tokens=max_tokens)
    return text_of(resp)


def parse_json(text: str) -> Any:
    """First JSON object or array in a model reply (tolerates ```json fences)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    start = min([i for i in (body.find("{"), body.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    return json.JSONDecoder().raw_decode(body[start:])[0]
