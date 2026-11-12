"""Model fallback: a refused model (payment, access, throttling) must not take the agent down."""
import pytest
from botocore.exceptions import ClientError

from rove import bedrock


def err(code):
    return ClientError({"Error": {"Code": code, "Message": "INVALID_PAYMENT_INSTRUMENT"}}, "Converse")


def test_falls_back_when_primary_is_refused(monkeypatch):
    calls = []

    def fake(model, messages, **kw):
        calls.append(model)
        if model == "claude":
            raise err("AccessDeniedException")
        return {"output": {"message": {"content": [{"text": "ok"}]}}}
    monkeypatch.setattr(bedrock, "converse", fake)
    resp, used = bedrock.converse_with_fallback(["claude", "kimi"], [])
    assert used == "kimi" and calls == ["claude", "kimi"] and bedrock.text_of(resp) == "ok"


def test_refused_model_is_skipped_for_a_while(monkeypatch):
    monkeypatch.setattr(bedrock, "_refused_until", {})
    calls = []

    def fake(model, messages, **kw):
        calls.append(model)
        if model == "claude":
            raise err("AccessDeniedException")
        return {"output": {"message": {"content": [{"text": "ok"}]}}}
    monkeypatch.setattr(bedrock, "converse", fake)
    bedrock.converse_with_fallback(["claude", "kimi"], [])
    bedrock.converse_with_fallback(["claude", "kimi"], [])
    assert calls == ["claude", "kimi", "kimi"]  # second turn doesn't waste a call on claude


def test_real_request_errors_are_not_hidden(monkeypatch):
    monkeypatch.setattr(bedrock, "converse", lambda model, messages, **kw: (_ for _ in ()).throw(err("ValidationException")))
    with pytest.raises(ClientError):
        bedrock.converse_with_fallback(["claude", "kimi"], [])


def test_all_unavailable_raises(monkeypatch):
    monkeypatch.setattr(bedrock, "converse", lambda model, messages, **kw: (_ for _ in ()).throw(err("ThrottlingException")))
    with pytest.raises(ClientError):
        bedrock.converse_with_fallback(["a", "b"], [])
