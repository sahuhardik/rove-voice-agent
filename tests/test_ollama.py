"""The local-model path returns a Converse-shaped response."""
import io
import json

from rove import bedrock


def test_ollama_route(monkeypatch):
    seen = {}

    def fake(req, timeout=0):
        seen["body"] = json.loads(req.data)
        return io.BytesIO(json.dumps({"message": {"content": "hello"}, "prompt_eval_count": 7, "eval_count": 2}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    r = bedrock.converse("ollama:qwen3:8b", [{"role": "user", "content": [{"text": "hi"}]}], system="be brief", max_tokens=50)
    assert bedrock.text_of(r) == "hello"
    assert seen["body"]["model"] == "qwen3:8b" and seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert r["usage"]["inputTokens"] == 7


def test_compact_context_is_small_and_relevant():
    from rove import knowledge
    c = knowledge.compact_context("R3", "my card says memory card error")
    full = knowledge.context_for("R3")
    assert len(c) < 14000 < len(full)
    assert "Memory card" in c and "help@rovedashcam.com" in c
    assert knowledge.compact_context("unknown", "hi") == knowledge.pack("identify")
