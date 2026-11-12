"""Step 7: voice helpers and the LiveKit worker adapter (no AWS or LiveKit server needed)."""
import asyncio
from types import SimpleNamespace

import pytest

from rove import speech


@pytest.mark.parametrize("heard,expected", [
    ("Hi, my roar 3 keeps restarting", "Hi, my Rove R3 keeps restarting"),
    ("it's a rove are three", "it's a Rove R3"),
    ("my are two four k won't connect", "my R2-4K won't connect"),
    ("the dual bro has no wifi", "the Dual Pro has no wifi"),
    ("the card says you one", "the card says U1"),
    ("I want to go to the store", "I want to go to the store"),  # nothing to fix
    ("you want me to restart it?", "you want me to restart it?"),
])
def test_transcript_normaliser(heard, expected):
    assert speech.normalize_transcript(heard) == expected


def test_worker_routes_speech_through_the_same_agent(monkeypatch):
    from livekit.agents import llm

    from voice import livekit_worker as w

    replies = iter(["<case>{\"model\": \"R3\"}</case><say>Does it come back on when it cools down?</say><action>continue</action>"])
    real_init = w.Agent.__init__
    monkeypatch.setattr(w.Agent, "__init__", lambda self, **kw: real_init(self, llm=lambda s, m: next(replies)))

    agent = w.RoveVoiceAgent.__new__(w.RoveVoiceAgent)
    agent.brain = w.Agent()
    monkeypatch.setattr(w.RoveVoiceAgent, "session", property(lambda self: SimpleNamespace(room_io=None)), raising=False)

    ctx = llm.ChatContext.empty()
    ctx.add_message(role="assistant", content="Hi, this is Rove support.")
    ctx.add_message(role="user", content="my roar 3 restarts when it's hot")
    out = asyncio.run(agent.llm_node(ctx, [], None))
    assert out == "Does it come back on when it cools down?"
    assert agent.brain.case.model == "R3"  # normaliser fixed "roar 3" before the agent saw it


def test_session_has_an_llm_so_livekit_calls_llm_node():
    # Regression: without an LLM on the session, LiveKit 1.3 never calls llm_node
    # and spoken turns are silently dropped (found in the live room test).
    from livekit.agents import llm

    from voice import livekit_worker as w
    assert isinstance(w.DiagnosticLLM(), llm.LLM)
    import inspect
    assert "llm=DiagnosticLLM()" in inspect.getsource(w.entrypoint)


def test_worker_hard_stop_and_closed_session(monkeypatch):
    from livekit.agents import llm

    from voice import livekit_worker as w

    agent = w.RoveVoiceAgent.__new__(w.RoveVoiceAgent)
    agent.brain = w.Agent(llm=lambda s, m: "")
    monkeypatch.setattr(w.RoveVoiceAgent, "session", property(lambda self: SimpleNamespace(room_io=None)), raising=False)
    ctx = llm.ChatContext.empty()
    ctx.add_message(role="user", content="there's smoke coming out of the camera")
    assert "Unplug" in asyncio.run(agent.llm_node(ctx, [], None))
    ctx.add_message(role="user", content="hello?")
    assert "taking over" in asyncio.run(agent.llm_node(ctx, [], None))
