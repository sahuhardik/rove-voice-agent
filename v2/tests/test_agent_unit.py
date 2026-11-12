"""Step 4a: the agent's plumbing, with a scripted fake model (no AWS needed)."""
from v2.rove import knowledge
from v2.rove.agent import Agent, parse
from v2.rove.case import Case


def fake(*replies):
    calls = []

    def llm(system, messages):
        calls.append((system, messages))
        return replies[min(len(calls) - 1, len(replies) - 1)]
    llm.calls = calls
    return llm


def turn(case_json="{}", say="OK.", action="continue"):
    return f"<case>{case_json}</case>\n<say>{say}</say>\n<action>{action}</action>"


def test_parse_reads_all_three_parts():
    update, say, action = parse(turn('{"model": "R3", "facts": ["card is U1"]}', "Is it **hot**?", "continue"))
    assert update == {"model": "R3", "facts": ["card is U1"]}
    assert say == "Is it hot?"  # markdown removed for speech
    assert action == "continue"


def test_parse_survives_a_model_that_ignores_the_format():
    _, say, action = parse("Sure, let's check the card first.")
    assert say == "Sure, let's check the card first." and action == "continue"


def test_case_apply_merges_and_validates():
    c = Case()
    ids = knowledge.model_ids()
    c.apply({"model": "R3", "facts": ["U1 card"], "tried": [{"step": "format in camera", "result": "no change"}]}, ids)
    c.apply({"model": "NOT-A-MODEL", "facts": ["U1 card", "256GB"], "tried": [{"step": "Format in camera", "result": "helped"}],
             "status": "bogus", "flags": ["hacked"]}, ids)
    assert c.model == "R3"
    assert c.facts == ["U1 card", "256GB"]
    assert c.tried == [{"step": "format in camera", "result": "helped"}]
    assert c.status == "open" and c.flags == []  # flags are code-owned


def test_model_named_by_customer_loads_its_pack():
    llm = fake(turn())
    a = Agent(llm=llm)
    a.respond("my R2-4K Dual Pro keeps disconnecting")
    assert a.case.model == "R2-4K-DUAL-PRO"
    assert "ROVE R2-4K DUAL PRO" in llm.calls[0][0].upper()


def test_alias_longest_match_wins():
    assert knowledge.model_from_text("it's the dual pro") == "R2-4K-DUAL-PRO"
    assert knowledge.model_from_text("the r2 dual") == "R2-4K-DUAL"
    assert knowledge.model_from_text("my phone is new") is None


def test_hazard_is_answered_without_the_model():
    llm = fake(turn())
    a = Agent(llm=llm)
    r = a.respond("there's smoke coming out of it")
    assert r.action == "escalate" and "Unplug" in r.say and not llm.calls
    assert a.case.status == "escalated" and a.closed


def test_request_for_human_escalates():
    a = Agent(llm=fake(turn()))
    assert a.respond("can I talk to a real person").action == "escalate"


def test_unsafe_draft_is_rewritten():
    llm = fake(turn(say="Go to Settings and Format the card."), turn(say="Formatting erases all videos. Is there anything you need to keep?",
                                                                     action="ask_destructive_confirmation"))
    a = Agent(llm=llm)
    r = a.respond("card error on my R3")
    assert len(llm.calls) == 2 and "previous draft was blocked" in llm.calls[1][1][-1]["content"][0]["text"]
    assert r.action == "ask_destructive_confirmation" and a.case.awaiting_destructive_confirmation


def test_persistently_unsafe_model_gets_safe_fallback():
    a = Agent(llm=fake(turn(say="Format the card now.")))
    r = a.respond("card error")
    assert "is it OK to go ahead?" in r.say and r.action == "ask_destructive_confirmation"


def test_fallback_question_is_answered_by_yes_without_looping():
    # Live loop (EVAL-02): the fallback must be a question where "yes" is the go-ahead.
    llm = fake(turn(say="Format the card now."), turn(say="Format the card now."),
               turn(say="Press the menu button, go to System Settings, then select Format."))
    a = Agent(llm=llm)
    a.respond("card error on my R3")
    r = a.respond("yes, go ahead")
    assert r.say.startswith("Press the menu button") and "OK to go ahead" not in r.say


def test_yes_confirms_one_destructive_step():
    llm = fake(turn(say="That erases everything on the card. OK to go ahead?", action="ask_destructive_confirmation"),
               turn(say="Go to Settings, then Format, and confirm."),
               turn(say="Did that fix it?"))
    a = Agent(llm=llm)
    a.respond("card error on my R3")
    r = a.respond("yes go ahead")
    assert r.say.startswith("Go to Settings")  # allowed: confirmed
    assert not a.case.confirmed_destructive  # used up
    a.respond("done")
    assert not a.case.confirmed_destructive


def test_footage_mode_is_sticky_and_blocks_writes():
    llm = fake(turn(say="Take a photo to test the card."), turn(say="Unplug the camera and remove the card so nothing records over it."))
    a = Agent(llm=llm)
    r = a.respond("I had an accident and can't find the video")
    assert a.case.footage_at_risk and "Unplug" in r.say
    assert "footage_at_risk" in llm.calls[0][1][-1]["content"][0]["text"]


def test_menu_paths_are_speakable():
    _, say, _ = parse(turn(say="Go to Settings > Phone > WiFi Calling."))
    assert say == "Go to Settings, then Phone, then WiFi Calling."


def test_backstop_hazard_is_advisory_not_a_hard_stop(monkeypatch):
    from v2.rove import safety
    llm = fake(turn(say="Does it come back on once it cools down?"))
    a = Agent(llm=llm)
    a.use_backstop = True
    monkeypatch.setattr(a, "_backstop", lambda text: safety.Screen(hazards=["model_flagged"]))
    r = a.respond("it gets really hot and restarts")
    assert r.action == "continue" and a.case.status == "open"
    assert "physical damage" in llm.calls[-1][1][-1]["content"][0]["text"]


def test_backstop_cannot_escalate_on_its_own(monkeypatch):
    from v2.rove import safety
    a = Agent(llm=fake(turn(say="Is your phone on the camera's Wi-Fi?")))
    a.use_backstop = True
    monkeypatch.setattr(a, "_backstop", lambda text: safety.Screen(wants_human=True))
    r = a.respond("the app won't find the camera")
    assert r.action == "continue" and not a.closed


def test_invented_brand_triggers_rewrite():
    llm = fake(turn(say="Samsung cards are the ones to use."), turn(say="Rove recommends a Class 10 U3 card. What does yours say on it?"))
    a = Agent(llm=llm)
    r = a.respond("my R3 stops recording")
    assert len(llm.calls) == 2 and "Samsung" not in r.say


def test_required_escalation_is_enforced_by_code():
    llm = fake(turn(say="Does it behave any differently with the card taken out?"))
    a = Agent(llm=llm)
    r = a.respond("I did the update yesterday and now it just sits on the logo screen")
    assert r.action == "escalate" and a.closed
    assert r.say.startswith("Does it behave any differently") and "person at Rove" in r.say
    assert any("escalation enforced" in n for n in r.safety_notes)


def test_history_alternates_roles():
    a = Agent(llm=fake(turn(say="Which model is it?")))
    a.respond("hello")
    a.respond("not sure")
    roles = [m["role"] for m in a.history]
    assert roles == ["user", "assistant", "user", "assistant"]
