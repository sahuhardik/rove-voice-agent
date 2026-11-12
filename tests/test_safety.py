"""Tests for step 3: the safety layer."""
import pytest

from rove import safety


@pytest.mark.parametrize("text,hazard", [
    ("there's smoke coming out of the camera", "smoke"),
    ("it smells like burning plastic", "burning_smell"),
    ("the battery looks swollen", "swelling"),
    ("the case has melted a bit", "heat_damage"),
    ("I saw sparks from the cable", "exposed_wiring"),
    ("it's too hot to touch", "too_hot_to_touch"),
])
def test_hazards_detected(text, hazard):
    assert hazard in safety.screen(text).hazards


@pytest.mark.parametrize("text", [
    "I had an accident yesterday and I can't find the video on the card",   # missed by the old system
    "someone rear-ended me and I need the footage for insurance",
    "the police want the clip",
    "I can't find the recording from the crash",
    "hit and run in the car park last night",
])
def test_footage_at_risk_detected(text):
    assert safety.screen(text).footage_at_risk


@pytest.mark.parametrize("text", [
    "can I speak to a real person", "put me through to someone", "I want to talk to a human",
    "transfer me to a person please",
])
def test_wants_human(text):
    assert safety.screen(text).wants_human


@pytest.mark.parametrize("text,flag", [
    ("I'm driving right now, can you help", "driving"),
    ("I want a refund", "out_of_scope"),
    ("the update is stuck at 50%", "firmware_in_progress"),
    ("since the installer hardwired it my car battery is dead every morning", "vehicle_electrical"),
    ("I had it hardwired in by a guy locally and my car battery went flat twice", "vehicle_electrical"),
    ("I did the update yesterday and now it just sits on the logo screen", "bricked_after_update"),
    ("after the firmware update it won't turn on", "bricked_after_update"),
])
def test_other_flags(text, flag):
    assert flag in safety.screen(text).flags


@pytest.mark.parametrize("text", [
    "my camera keeps stopping recording after ten minutes",
    "the wifi keeps disconnecting",
    "how do I turn on parking mode",
    "the video is blurry at night",
    "it restarts on its own when it's hot outside",  # heat is a symptom, not a hazard
])
def test_ordinary_problems_raise_no_flags(text):
    assert safety.screen(text).flags == []


# ---- reviewing replies ----------------------------------------------------

def _review(reply, **kw):
    args = dict(confirmed_destructive=False, footage_at_risk=False, driving=False) | kw
    return safety.review(reply, **args)


def test_blocks_firmware_version():
    assert not _review("Please update to firmware version 2.3.1 first.").ok
    assert _review("Please update to the latest firmware from Rove's firmware page.").ok


def test_blocks_unconfirmed_format_but_allows_after_confirmation():
    reply = "Go to Settings, then Format, and press OK."
    assert not _review(reply).ok
    assert _review(reply, confirmed_destructive=True).ok


def test_asking_about_a_format_is_not_instructing_one():
    assert _review("Have you tried formatting the card in the camera before?").ok
    assert _review("Don't format the card yet, we need to keep that footage.").ok
    # The live false-positive: acknowledging the customer's own format.
    assert _review("Got it, formatting didn't help. What brand and speed class is your card?").ok
    assert _review("Since you already formatted it, that rules out a corrupted file system.").ok


@pytest.mark.parametrize("reply", [
    "Format the card now.",
    "Please format the card in the camera.",
    "Press the menu button, go to System Settings, then select Format.",
    "You should reset the camera to defaults.",
    "Let's format the card and see if it holds.",
    "Next, restore defaults from the system menu.",
])
def test_destructive_instructions_are_caught(reply):
    assert "destructive" in _review(reply).kinds


@pytest.mark.parametrize("reply", [
    "Now delete the ROVE app from your phone and reinstall it from the App Store.",
    "Delete the app and reinstall it, then allow all permissions.",
])
def test_reinstalling_the_app_is_not_an_erase(reply):
    # Live false positive (EVAL-26): the app holds no footage.
    assert "destructive" not in _review(reply).kinds


def test_deleting_files_is_still_an_erase():
    assert "destructive" in _review("Delete the old files from the card to make room.").kinds


def test_grounding_flags_invented_brands_and_specs():
    knowledge = "Use a Class 10 U3 card up to 512GB. Wi-Fi is 2.4GHz."
    rev = _review("Samsung cards are recommended, and it needs a V30 card at 5GHz.", grounding=knowledge)
    assert set(rev.ungrounded) == {"samsung", "V30", "5GHz"}
    assert _review("You need a Class 10 U3 card, up to 512 GB.", grounding=knowledge).ok
    # The customer's own words count as grounding.
    assert _review("A 256GB SanDisk U1 card is too slow.", grounding=knowledge + " my 256 gig sandisk 256GB says U1").ok


def test_brand_advice_follows_the_customers_model():
    from rove import knowledge
    reply = "I'd recommend a genuine Samsung Class 10 U3 card."
    # The original R2-4K manual recommends Samsung ...
    assert safety.contradicted_brands(reply, knowledge.pack("R2-4K")) == []
    # ... the R2-4K PRO manual says not to use it.
    assert safety.contradicted_brands(reply, knowledge.pack("R2-4K-PRO")) == ["samsung"]
    # Warning the customer off it is fine.
    assert safety.contradicted_brands("Avoid Samsung cards for this camera.", knowledge.pack("R2-4K-PRO")) == []


def test_spelled_out_units_are_checked():
    rev = _review("U1 is about 10 megabytes per second, but you need 30.", grounding="U1 U3 class 10")
    assert "10 megabytes per second" in rev.ungrounded


def test_spelled_out_numbers_are_checked():
    assert safety.words_to_digits("wait forty-five minutes or ten seconds") == "wait 45 minutes or 10 seconds"
    rev = _review("If it hits forty-five minutes with no movement, call us.", grounding="the update takes about 10 minutes")
    assert "45 minutes" in rev.ungrounded
    assert _review("Give it ten minutes.", grounding="the update takes about 10 minutes").ok


def test_long_replies_are_flagged_and_trimmed():
    long = " ".join(["This is a sentence about the card."] * 12) + " What does your card say?"
    rev = _review(long)
    assert "length" in rev.kinds
    text, _ = safety.fallback(long, rev)
    assert len(text.split()) < 30 and text.endswith("?")


def test_fallback_keeps_the_grounded_part():
    rev = _review("U1 cards are too slow. Samsung is the brand to buy. Do you have a U3 card?", grounding="U1 U3")
    text, action = safety.fallback("U1 cards are too slow. Samsung is the brand to buy. Do you have a U3 card?", rev)
    assert text == "U1 cards are too slow. Do you have a U3 card?" and action == "continue"


def test_footage_mode_blocks_writes_and_erases():
    assert not _review("Take a photo and tell me if you hear the shutter.", footage_at_risk=True).ok
    assert not _review("Format the card in the camera.", footage_at_risk=True, confirmed_destructive=True).ok
    assert _review("Unplug the camera and take the card out so nothing records over it.", footage_at_risk=True).ok


def test_driving_mode_blocks_hands_on_steps():
    assert not _review("Press and hold the power button for five seconds.", driving=True).ok
    assert _review("Once you've parked somewhere safe, let me know and we'll carry on.", driving=True).ok
