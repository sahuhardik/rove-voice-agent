"""Step 6: the web API, with a fake model and fake speech (no AWS needed)."""
import pytest
from fastapi.testclient import TestClient

from rove import agent as agent_mod
from server import app as app_mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    replies = iter([
        "<case>{\"model\": \"R3\", \"symptom\": \"stops recording\"}</case><say>What does your card say on it?</say><action>continue</action>",
        "<case>{\"facts\": [\"card is U1\"], \"hypotheses\": [\"card too slow\"]}</case><say>U1 is too slow. Do you have a U3 card?</say><action>continue</action>",
    ])
    real_init = agent_mod.Agent.__init__

    def fake_init(self, **kw):
        real_init(self, llm=lambda system, messages: next(replies))
    monkeypatch.setattr(agent_mod.Agent, "__init__", fake_init)
    monkeypatch.setattr(app_mod.speech, "synthesize", lambda text, fmt="mp3": b"ID3fake")

    async def fake_transcribe(pcm, sample_rate=16000):
        return "it says U1 on it"
    monkeypatch.setattr(app_mod.speech, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(app_mod, "SESSIONS_DIR", tmp_path)
    return TestClient(app_mod.create_app())


def test_page_and_health(client):
    assert client.get("/healthz").json()["ok"]
    assert "Rove Support" in client.get("/").text


def test_text_then_voice_turn_updates_case_and_saves(client, tmp_path):
    s = client.post("/api/sessions").json()
    assert s["greeting"] and s["audio"]
    r = client.post(f"/api/sessions/{s['id']}/message", json={"text": "my R3 stops recording"}).json()
    assert r["say"] == "What does your card say on it?" and r["case"]["model"] == "R3"
    v = client.post(f"/api/sessions/{s['id']}/voice", content=b"\x00\x01" * 16000).json()
    assert v["transcript"] == "it says U1 on it"
    assert v["case"]["facts"] == ["card is U1"] and v["case"]["hypotheses"] == ["card too slow"]
    saved = (tmp_path / f"{s['id']}.json").read_text(encoding="utf-8")
    assert "card too slow" in saved and '"via": "voice"' in saved


def test_errors_are_explained(client):
    assert client.post("/api/sessions/nope/message", json={"text": "hi"}).status_code == 404
    s = client.post("/api/sessions").json()
    assert client.post(f"/api/sessions/{s['id']}/message", json={"text": "  "}).status_code == 400
    assert client.post(f"/api/sessions/{s['id']}/voice", content=b"\x00" * 100).status_code == 400


def test_model_outage_gives_a_clear_503_and_keeps_the_session(client, monkeypatch):
    # Found live: when every Bedrock model was refused the app returned a bare 500.
    s = client.post("/api/sessions").json()
    calls = {"n": 0}
    real = agent_mod.Agent.respond

    def flaky(self, text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Access to Bedrock models is not allowed for this account")
        return real(self, text)
    monkeypatch.setattr(agent_mod.Agent, "respond", flaky)
    r = client.post(f"/api/sessions/{s['id']}/message", json={"text": "my R3 stops recording"})
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]
    ok = client.post(f"/api/sessions/{s['id']}/message", json={"text": "my R3 stops recording"})
    assert ok.status_code == 200 and ok.json()["case"]["model"] == "R3"  # same session, after recovery


def test_escalated_session_refuses_more_turns(client):
    s = client.post("/api/sessions").json()
    r = client.post(f"/api/sessions/{s['id']}/message", json={"text": "there's smoke coming out of it"}).json()
    assert r["action"] == "escalate" and r["closed"]
    assert client.post(f"/api/sessions/{s['id']}/message", json={"text": "hello?"}).status_code == 409
    assert "Flags: hazard" in client.get(f"/api/sessions/{s['id']}").json()["handoff"]


def test_livekit_token_endpoint(client, monkeypatch):
    import jwt as pyjwt  # PyJWT ships with livekit-api

    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 40)
    monkeypatch.setenv("LIVEKIT_PUBLIC_URL", "wss://example.test")
    body = client.get("/api/livekit/token?name=Sam").json()
    assert body["url"] == "wss://example.test" and body["room"].startswith("rove-")
    claims = pyjwt.decode(body["token"], "s" * 40, algorithms=["HS256"])
    assert claims["video"]["room"] == body["room"] and claims["video"]["roomJoin"] is True
    assert client.get("/api/livekit/token").json()["room"] != body["room"]  # one room per call


def test_live_page_is_default_and_classic_remains(client):
    assert "livekit-client" in client.get("/").text
    assert "hold-to-talk" in client.get("/classic").text
