"""Canonical step ontology and the taxonomy-ID -> candidate-step map.

Two things live here, and the distinction between them matters:

1. **The canonical ontology from `docs/06` §3.6.** Five families and their
   `STEP.*` ids, transcribed verbatim. These are marked `source="06 §3.6"`.
   They are the ids the architecture document commits to.

2. **Phase 0 extensions.** `docs/06` §3.6 is illustrative -- it shows the
   *shape* of the ontology with a worked sample, not the whole of it. The 28
   taxonomy entries in `docs/02` propose next steps that the sample does not
   cover (asking for a card's speed rating, asking how the camera is powered
   with the ignition off, and so on). Those steps are added here with
   `source="extension (02)"` so that nobody mistakes them for text that exists
   in the architecture document. Every extension is traceable to a specific
   `docs/02` entry via `TAXONOMY_CANDIDATES` below.

Why canonical ids at all (`docs/06` §3.6): the no-repeat rule M4 is only
enforceable if "what the user already tried" and "what the agent is about to
propose" are the same kind of object. Free-text matching fails on exactly the
cases `docs/03` Part 2 is built to catch.

**`FAMILY.OBSERVE` is exempt from the no-repeat block** (`docs/06` §3.6):
asking someone to read the screen again, after something has changed, is not
repetition. `FAMILY.ASK` -- a Phase 0 extension -- carries the same exemption
on the same reasoning: a question is not a step.

**Family-level blocking.** `docs/06` §3.5 drops a candidate if its
`step_family` is in the ledger's failed families, not merely if its `step_id`
is. That is the mechanism EVAL-12 tests: having formatted in the camera and
failed, a computer-side format is a *different step in the same family* and is
equally blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Families
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    id: str
    description: str
    source: str
    destructive: bool = False
    no_repeat_exempt: bool = False


_FAMILY_LIST: list[Family] = [
    # ---- the five families named in docs/06 §3.6 -------------------------
    Family(
        id="FAMILY.DESTRUCTIVE.ERASE_CARD",
        description="Anything that erases the memory card.",
        source="06 §3.6",
        destructive=True,
    ),
    Family(
        id="FAMILY.DESTRUCTIVE.RESET_DEVICE",
        description="Anything that discards the camera's own configuration.",
        source="06 §3.6",
        destructive=True,
    ),
    Family(
        id="FAMILY.POWER_CYCLE",
        description="Removing and restoring power to the camera.",
        source="06 §3.6",
    ),
    Family(
        id="FAMILY.APP_STATE",
        description="Changing the state of the phone app without touching the camera.",
        source="06 §3.6",
    ),
    Family(
        id="FAMILY.OBSERVE",
        description=(
            "Look, listen, read out. Never destructive, never blocked by no-repeat "
            "(06 §3.6)."
        ),
        source="06 §3.6",
        no_repeat_exempt=True,
    ),
    # ---- Phase 0 extensions ---------------------------------------------
    Family(
        id="FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE",
        description=(
            "Reverting firmware. Never agent-initiated under any circumstances "
            "(06 §3.5, 01 §5). Present in the ontology so the safety filter has "
            "something to name; never a candidate."
        ),
        source="extension (06 §3.5)",
        destructive=True,
    ),
    Family(
        id="FAMILY.ASK",
        description=(
            "Pure information gathering: a question whose answer re-ranks the cause "
            "list. Exempt from no-repeat on the same reasoning as FAMILY.OBSERVE."
        ),
        source="extension (02)",
        no_repeat_exempt=True,
    ),
    Family(
        id="FAMILY.SETTINGS_CHANGE",
        description="Reading or changing a camera setting. Non-destructive.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.DATE_TIME",
        description=(
            "Setting the clock. Split out of FAMILY.SETTINGS_CHANGE because EVAL-20 "
            "needs the whole family blocked once the caller has set the date "
            "repeatedly without it holding."
        ),
        source="extension (02)",
    ),
    Family(
        id="FAMILY.CARD_HANDLING",
        description="Physically handling the card. Non-destructive to its contents.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.PHYSICAL",
        description="Cleaning, checking, or adjusting the camera and its mounting.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.DEVICE_CONTROL",
        description="Non-destructive controls on the camera body or its menus.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.PHONE_NETWORK",
        description="Phone-side network actions. Nothing is done to the camera.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.POWER_HARDWARE",
        description="Swapping or testing cables, adapters, and sockets.",
        source="extension (02)",
    ),
    Family(
        id="FAMILY.SAFETY",
        description=(
            "Steps whose purpose is to stop something bad happening: hold the "
            "caller's hand off the plug, preserve the card before diagnosing."
        ),
        source="extension (02)",
    ),
    Family(
        id="FAMILY.ESCALATE",
        description="Hand the call to a human.",
        source="extension (02)",
    ),
]

FAMILIES: dict[str, Family] = {f.id: f for f in _FAMILY_LIST}


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    id: str
    family: str
    description: str
    source: str
    #: True if carrying this out destroys data or configuration. Routed through
    #: the destructive gate (06 §6.4) -- cause + consent + consequence.
    destructive: bool = False
    #: True if the step is only valid for some models. Proposing one of these
    #: while `device.confidence == UNKNOWN` is an M1 failure (06 §3.4).
    model_specific: bool = False
    #: True if carrying it out can lose footage the caller may need (REC-01).
    risks_footage: bool = False
    #: True if the caller has to touch the camera or the phone. Blocked by the
    #: driving gate (06 §6.2).
    needs_hands: bool = True

    @property
    def no_repeat_exempt(self) -> bool:
        return FAMILIES[self.family].no_repeat_exempt


_STEP_LIST: list[Step] = [
    # ======================================================================
    # docs/06 §3.6, verbatim
    # ======================================================================
    Step(
        "STEP.CARD.FORMAT_IN_CAMERA",
        "FAMILY.DESTRUCTIVE.ERASE_CARD",
        "Format the memory card using the camera's own format function.",
        "06 §3.6",
        destructive=True,
        risks_footage=True,
    ),
    Step(
        "STEP.CARD.FORMAT_ON_COMPUTER",
        "FAMILY.DESTRUCTIVE.ERASE_CARD",
        "Format the card on a computer. Different step, SAME family (EVAL-12).",
        "06 §3.6",
        destructive=True,
        risks_footage=True,
    ),
    Step(
        "STEP.DEVICE.RESTORE_DEFAULT_SETTINGS",
        "FAMILY.DESTRUCTIVE.RESET_DEVICE",
        "Restore the camera to its default settings.",
        "06 §3.6",
        destructive=True,
    ),
    Step(
        "STEP.DEVICE.HARD_RESET_PINHOLE",
        "FAMILY.DESTRUCTIVE.RESET_DEVICE",
        "Press the recessed reset button with a paper clip. R2-4K family only; "
        "the R3 has no reset button.",
        "06 §3.6",
        destructive=True,
        model_specific=True,
    ),
    Step(
        "STEP.DEVICE.POWER_CYCLE",
        "FAMILY.POWER_CYCLE",
        "Switch the camera off and on again.",
        "06 §3.6",
    ),
    Step(
        "STEP.DEVICE.UNPLUG_REPLUG",
        "FAMILY.POWER_CYCLE",
        "Pull the power lead out and put it back in.",
        "06 §3.6",
    ),
    Step(
        "STEP.APP.FORCE_CLOSE_REOPEN",
        "FAMILY.APP_STATE",
        "Fully close the app -- swipe it away, not just go to the home screen -- "
        "and reopen it.",
        "06 §3.6",
    ),
    Step(
        "STEP.APP.RETRY_CONNECT_BUTTON",
        "FAMILY.APP_STATE",
        "Tap 'Retry Connect to Dash Cam' on the app's Live Video screen. The "
        "Tier-1 correct first move (05 APP-01).",
        "06 §3.6",
    ),
    Step(
        "STEP.APP.CLEAR_CACHE",
        "FAMILY.APP_STATE",
        "Clear the app's cache.",
        "06 §3.6",
    ),
    Step(
        "STEP.APP.REINSTALL",
        "FAMILY.APP_STATE",
        "Uninstall and reinstall the app, then allow all permissions.",
        "06 §3.6",
    ),
    Step(
        "STEP.OBSERVE.READ_SCREEN_VERBATIM",
        "FAMILY.OBSERVE",
        "Read out everything on the camera's screen, word for word.",
        "06 §3.6",
    ),
    Step(
        "STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT",
        "FAMILY.OBSERVE",
        "Listen for the 30-second 'not recording' failsafe announcement "
        "(05 REC-02).",
        "06 §3.6",
        needs_hands=False,
    ),
    Step(
        "STEP.OBSERVE.READ_SSID",
        "FAMILY.OBSERVE",
        "Read out (or type) the network name shown on the camera's screen.",
        "06 §3.6",
    ),
    Step(
        "STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST",
        "FAMILY.OBSERVE",
        "Switch to photo mode and press OK; the shutter sound splits card from "
        "slot on one action (05 SD-01).",
        "06 §3.6",
    ),
    # ======================================================================
    # Phase 0 extensions, each traceable to a docs/02 entry
    # ======================================================================
    # ---- FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE ---------------------------
    Step(
        "STEP.FW.DOWNGRADE",
        "FAMILY.DESTRUCTIVE.FIRMWARE_DOWNGRADE",
        "Revert the camera to an earlier firmware build. Never agent-initiated "
        "(02 FW-02, 06 §3.5).",
        "extension (06 §3.5)",
        destructive=True,
    ),
    # ---- FAMILY.OBSERVE extensions ---------------------------------------
    Step(
        "STEP.OBSERVE.CONFIRM_CAMERA_AWAKE",
        "FAMILY.OBSERVE",
        "Confirm the camera is powered on and awake right now, and say what its "
        "screen is showing (02 WIFI-02).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.READ_PASSWORD_CHARACTERWISE",
        "FAMILY.OBSERVE",
        "Read the password aloud character by character, stating upper or lower "
        "case for each (02 WIFI-03).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.CHECK_LENS_FILM_AND_CLEANLINESS",
        "FAMILY.OBSERVE",
        "Check the lens for a clear plastic film still stuck on it, and whether "
        "lens and glass are clean (02 VID-01).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.CHECK_UPDATE_INDICATOR",
        "FAMILY.OBSERVE",
        "Watch for a full minute and say whether any light or indicator is still "
        "changing (02 FW-01).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.OBSERVE.WAIT_FOR_INDICATOR",
        "FAMILY.OBSERVE",
        "Wait, without unplugging, and watch (02 FW-01). Recorded as an attempt "
        "when the caller has already waited.",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR",
        "FAMILY.OBSERVE",
        "Power down, take the card out, power on once, and report whether the "
        "camera behaves any differently (02 FW-02).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.TRY_DIFFERENT_PLAYER",
        "FAMILY.OBSERVE",
        "Open one failing file in a different media player (02 SD-03).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.CHECK_MUTE_INDICATOR",
        "FAMILY.OBSERVE",
        "Check whether the screen shows a muted or crossed-out microphone "
        "indicator (02 VID-03).",
        "extension (02)",
    ),
    Step(
        "STEP.OBSERVE.CHECK_CARD_ON_COMPUTER",
        "FAMILY.OBSERVE",
        "Put the card in a computer and look at what is on it (02 REC-02 / SD-03).",
        "extension (02)",
    ),
    # ---- FAMILY.ASK -------------------------------------------------------
    Step(
        "STEP.ASK.PHONE_OS_AND_VERSION",
        "FAMILY.ASK",
        "Ask whether the phone is an iPhone or Android, and roughly which OS "
        "version (02 WIFI-01).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.OTHER_DEVICE_ON_SOCKET",
        "FAMILY.ASK",
        "Ask whether any other device works from that same socket in the car "
        "(02 PWR-01).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.WERE_CLIPS_LOCKED",
        "FAMILY.ASK",
        "Ask whether the missing clips had been locked or marked as events, or "
        "were ordinary recordings (02 REC-03).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.SPLIT_SYMPTOMS_AUDIO_FIRST",
        "FAMILY.ASK",
        "State that the audio and the timestamp are two separate things, take "
        "audio first, and ask whether audio recording is currently enabled "
        "(02 VID-03).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.LOCKED_FILE_VOLUME",
        "FAMILY.ASK",
        "Ask roughly how many clips are locked or marked as events -- whether the "
        "caller has been saving clips deliberately (02 SD-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.CARD_SPECS_AND_RATING",
        "FAMILY.ASK",
        "Ask for the card's brand, capacity, speed and endurance markings, and "
        "roughly how long it has been in use (02 SD-01 / SD-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.APP_PERMISSIONS_GRANTED",
        "FAMILY.ASK",
        "Ask which permissions the app was granted -- specifically local network "
        "or nearby-devices access -- and what the caller answered (02 APP-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.WHICH_PERMISSION_PROMPT",
        "FAMILY.ASK",
        "Ask which permission prompt is on screen and what the caller answered "
        "(02 APP-03).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.PARKED_POWER_SOURCE",
        "FAMILY.ASK",
        "Ask how the camera is powered with the ignition off -- hardwire kit, "
        "battery pack, or the cigarette-lighter socket (02 REC-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.DROP_IDLE_OR_ACTIVE",
        "FAMILY.ASK",
        "Ask whether the drop happens even while actively using the app, or only "
        "when the phone has been idle on the connection (02 WIFI-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.DASHBOARD_REFLECTIVE_OBJECTS",
        "FAMILY.ASK",
        "Ask whether there is anything light-coloured or shiny on top of the "
        "dashboard (02 VID-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.INTERIOR_VISIBLE_IN_FOOTAGE",
        "FAMILY.ASK",
        "Ask whether the caller can see their own dashboard or car interior in "
        "the footage (02 VID-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
        "FAMILY.ASK",
        "Ask how old the camera is and whether it has ever held the date before "
        "(02 PWR-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.CAMERA_RESTARTS_IN_HEAT",
        "FAMILY.ASK",
        "Ask whether the camera also switches itself off or restarts on hot days, "
        "or whether only the Wi-Fi drops (02 PWR-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.RECOVERS_WHEN_COOL",
        "FAMILY.ASK",
        "Ask whether the camera comes back on by itself once the car has cooled "
        "down (02 PWR-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.HARDWIRE_KIT_AND_CUTOFF",
        "FAMILY.ASK",
        "Ask whether the camera is on a hardwire kit and, if so, whether a "
        "low-voltage cutoff was set or mentioned (02 PWR-03).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.POWERED_SIGN_WHEN_PARKED",
        "FAMILY.ASK",
        "Ask whether the camera shows any sign of being powered when the caller "
        "comes back to a parked car (02 PWR-03 + REC-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.SHUTDOWN_ABRUPT_OR_GRACEFUL",
        "FAMILY.ASK",
        "Ask whether the camera loses power abruptly when the ignition goes off, "
        "or shuts down gracefully with a message or a countdown (02 SD-03 + "
        "PWR-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.CARD_FROZEN_IN_TIME",
        "FAMILY.ASK",
        "Ask whether the oldest files on the card are still there, or whether the "
        "card appears frozen at a point in time (02 REC-02 + SD-01).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.COPIED_OR_PLAYED_FROM_CARD",
        "FAMILY.ASK",
        "Ask whether the files were copied off the card first, or are being played "
        "directly from it (02 SD-03).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.CARD_PRESENT",
        "FAMILY.ASK",
        "Ask whether there is a card in the camera right now (02 REC-02).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.STREAM_OR_DOWNLOAD",
        "FAMILY.ASK",
        "Ask whether the caller is playing the video in the app or downloading it "
        "to the phone first (02 WIFI-05).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.COMPUTER_AND_CARD_READER",
        "FAMILY.ASK",
        "Ask whether the caller has a computer and a card reader, or whether the "
        "phone is their only device (02 FW-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.APP_ACCOUNT_REGISTERED",
        "FAMILY.ASK",
        "Ask whether a ROVE app account has been created and verified on the new "
        "phone (02 APP-04).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ASK.PHYSICAL_TRAUMA_HISTORY",
        "FAMILY.ASK",
        "Ask whether the camera has ever been dropped, soaked, or exposed to "
        "extreme heat -- the one question that makes an unmatched-symptom handoff "
        "useful (03 EVAL-28).",
        "extension (02)",
        needs_hands=False,
    ),
    # ---- FAMILY.SETTINGS_CHANGE -------------------------------------------
    Step(
        "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        "FAMILY.SETTINGS_CHANGE",
        "Check whether the relevant setting is still switched on -- the update may "
        "have reset it (02 FW-03).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.CHECK_LOOP_RECORDING",
        "FAMILY.SETTINGS_CHANGE",
        "Check Video Mode settings > Loop Recording and report whether it reads "
        "OFF or a duration (02 SD-02).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.CHECK_GSENSOR_SENSITIVITY",
        "FAMILY.SETTINGS_CHANGE",
        "Check the G-sensor sensitivity setting (02 REC-03).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.CHECK_RESOLUTION",
        "FAMILY.SETTINGS_CHANGE",
        "Check whether the resolution setting is at the camera's maximum "
        "(02 VID-01).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.CHECK_EXPOSURE_WDR",
        "FAMILY.SETTINGS_CHANGE",
        "Check the exposure / WDR-type settings (02 VID-02).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.CHECK_AUDIO_ENABLED",
        "FAMILY.SETTINGS_CHANGE",
        "Check whether audio recording is enabled (02 VID-03).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.ENABLE_PARKING_MODE",
        "FAMILY.SETTINGS_CHANGE",
        "Switch parking mode on in the camera's settings (02 REC-04).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.SWITCH_WIFI_BAND_2_4",
        "FAMILY.SETTINGS_CHANGE",
        "Change WiFi Mode from 5 GHz to 2.4 GHz in System Settings. DUAL, DUAL "
        "PRO and R3 only -- the R2-4K has nothing to switch (02 WIFI-02).",
        "extension (02)",
        model_specific=True,
    ),
    # ---- FAMILY.DATE_TIME --------------------------------------------------
    Step(
        "STEP.SETTINGS.SET_DATE_TIME",
        "FAMILY.DATE_TIME",
        "Set the date and time (02 PWR-04).",
        "extension (02)",
    ),
    Step(
        "STEP.SETTINGS.SET_DATE_TIME_AND_RETEST",
        "FAMILY.DATE_TIME",
        "Set the date, leave the camera on power for about an hour, restart it and "
        "check (02 PWR-04).",
        "extension (02)",
    ),
    # ---- FAMILY.CARD_HANDLING ---------------------------------------------
    Step(
        "STEP.CARD.RESEAT",
        "FAMILY.CARD_HANDLING",
        "Power off, remove and firmly reseat the card, and power back on "
        "(02 SD-01).",
        "extension (02)",
    ),
    Step(
        "STEP.CARD.REPLACE_CARD",
        "FAMILY.CARD_HANDLING",
        "Swap to a different card and observe over the next week (02 SD-04).",
        "extension (02)",
    ),
    # ---- FAMILY.PHYSICAL ---------------------------------------------------
    Step(
        "STEP.PHYSICAL.CLEAN_LENS_AND_GLASS",
        "FAMILY.PHYSICAL",
        "Clean the lens and the windscreen glass in front of it (02 VID-01 / "
        "VID-02).",
        "extension (02)",
    ),
    # ---- FAMILY.DEVICE_CONTROL --------------------------------------------
    Step(
        "STEP.DEVICE.ENABLE_WIFI_ON_CAMERA",
        "FAMILY.DEVICE_CONTROL",
        "Switch Wi-Fi on at the camera using the model-specific control "
        "(02 WIFI-02). Model-specific: Emergency Lock held 2 s on R2-4K/PRO, "
        "touch menu on R3.",
        "extension (02)",
        model_specific=True,
    ),
    # ---- FAMILY.PHONE_NETWORK ---------------------------------------------
    Step(
        "STEP.PHONE.FORGET_AND_REJOIN_NETWORK",
        "FAMILY.PHONE_NETWORK",
        "Have the phone forget the saved network and join it again (02 WIFI-03).",
        "extension (02)",
    ),
    Step(
        "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
        "FAMILY.PHONE_NETWORK",
        "Stand beside the camera, within range, and retry (02 WIFI-04).",
        "extension (02)",
    ),
    Step(
        "STEP.PHONE.ACCEPT_NO_INTERNET_PROMPT",
        "FAMILY.PHONE_NETWORK",
        "Re-connect and, when the phone offers to stay on a network with no "
        "internet, accept and keep it (02 WIFI-01).",
        "extension (02)",
    ),
    Step(
        "STEP.PHONE.DISABLE_WIFI_OLD_PHONE",
        "FAMILY.PHONE_NETWORK",
        "Turn Wi-Fi off entirely on the old phone, then try the new one "
        "(02 APP-04).",
        "extension (02)",
    ),
    Step(
        "STEP.PHONE.DOWNLOAD_SHORT_CLIP",
        "FAMILY.PHONE_NETWORK",
        "Download one short clip rather than playing it, and report whether it "
        "completes and roughly how long it takes (02 WIFI-05).",
        "extension (02)",
    ),
    Step(
        "STEP.PHONE.RESTART",
        "FAMILY.PHONE_NETWORK",
        "Restart the phone (02 APP-02, listed as a wrong response in 03 EVAL-14).",
        "extension (02)",
    ),
    # ---- FAMILY.APP_STATE extensions --------------------------------------
    Step(
        "STEP.APP.UNINSTALL_OLD_PHONE",
        "FAMILY.APP_STATE",
        "Uninstall the app from the old phone (02 APP-04).",
        "extension (02)",
    ),
    Step(
        "STEP.APP.CHECK_STORE_VERSION",
        "FAMILY.APP_STATE",
        "Check the app store listing: does it offer Update, or only Open "
        "(02 APP-02)?",
        "extension (02)",
    ),
    Step(
        "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",
        "FAMILY.APP_STATE",
        "Explain in one sentence why the app needs the permission -- it talks to "
        "the camera directly over its own Wi-Fi, not over the internet -- then ask "
        "whether they are willing to grant it (02 APP-03).",
        "extension (02)",
    ),
    Step(
        "STEP.APP.CHECK_FIRMWARE_MENU",
        "FAMILY.APP_STATE",
        "Open the app's left menu and look for 'Firmware Update' (02 FW-04).",
        "extension (02)",
    ),
    # ---- FAMILY.POWER_HARDWARE --------------------------------------------
    Step(
        "STEP.POWER.TRY_DIFFERENT_CABLE",
        "FAMILY.POWER_HARDWARE",
        "Try a different cable or car adapter (02 PWR-01).",
        "extension (02)",
    ),
    # ---- FAMILY.SAFETY ------------------------------------------------------
    Step(
        "STEP.SAFETY.HOLD_DO_NOT_UNPLUG",
        "FAMILY.SAFETY",
        "Tell the caller explicitly not to unplug anything yet -- a cut during a "
        "write is what creates a brick (02 FW-01).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.SAFETY.PRESERVE_CARD_POWER_OFF",
        "FAMILY.SAFETY",
        "Before any diagnosis: power the camera down, remove the card, set it "
        "aside untouched (02 REC-01).",
        "extension (02)",
    ),
    # ---- FAMILY.ESCALATE ----------------------------------------------------
    Step(
        "STEP.ESCALATE.HANDOFF",
        "FAMILY.ESCALATE",
        "Hand to a human engineer with the handoff payload (06 §5.2).",
        "extension (02)",
        needs_hands=False,
    ),
    Step(
        "STEP.ESCALATE.OUT_OF_SCOPE_TRANSFER",
        "FAMILY.ESCALATE",
        "Say plainly that this is handled by a person, and transfer -- without "
        "demanding a troubleshooting session as the price of the handoff "
        "(03 EVAL-29).",
        "extension (02)",
        needs_hands=False,
    ),
]

STEPS: dict[str, Step] = {s.id: s for s in _STEP_LIST}


# --------------------------------------------------------------------------
# Taxonomy-ID -> candidate-step map (docs/02)
# --------------------------------------------------------------------------

#: One entry per taxonomy ID in `docs/02`, plus the two non-taxonomy outcomes.
#:
#: **Ordering.** Each `docs/02` entry carries two next-step fields: the original
#: `Next step` and the later `Most plausible next step` (which Step 1b marked
#: VERIFIED / CORRECTED / REJECTED / UNVERIFIED). Where the two disagree, the
#: original `Next step` is listed first, because `docs/03` -- the eval set this
#: harness grades against -- was written against it. The corrected step follows
#: immediately. The disagreements are real and are listed in `eval/README.md`;
#: they are Phase 0 findings, not bugs in this file.
TAXONOMY_CANDIDATES: dict[str, list[str]] = {
    # ---- Category A: Wi-Fi connectivity -----------------------------------
    "WIFI-01": [
        "STEP.ASK.PHONE_OS_AND_VERSION",
        "STEP.PHONE.ACCEPT_NO_INTERNET_PROMPT",
        "STEP.OBSERVE.READ_SSID",
    ],
    "WIFI-02": [
        "STEP.OBSERVE.CONFIRM_CAMERA_AWAKE",
        "STEP.OBSERVE.READ_SCREEN_VERBATIM",
        "STEP.DEVICE.ENABLE_WIFI_ON_CAMERA",
        "STEP.SETTINGS.SWITCH_WIFI_BAND_2_4",
    ],
    "WIFI-03": [
        "STEP.OBSERVE.READ_PASSWORD_CHARACTERWISE",
        "STEP.PHONE.FORGET_AND_REJOIN_NETWORK",
    ],
    "WIFI-04": [
        "STEP.ASK.DROP_IDLE_OR_ACTIVE",
        "STEP.PHONE.MOVE_CLOSER_TO_CAMERA",
        "STEP.ASK.PHONE_OS_AND_VERSION",
    ],
    "WIFI-05": [
        "STEP.ASK.STREAM_OR_DOWNLOAD",
        "STEP.PHONE.DOWNLOAD_SHORT_CLIP",
    ],
    # ---- Category B: Firmware ---------------------------------------------
    "FW-01": [
        "STEP.SAFETY.HOLD_DO_NOT_UNPLUG",
        "STEP.OBSERVE.CHECK_UPDATE_INDICATOR",
    ],
    "FW-02": [
        "STEP.ESCALATE.HANDOFF",
        "STEP.OBSERVE.CARD_REMOVED_BEHAVIOUR",
    ],
    "FW-03": [
        "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        "STEP.ESCALATE.HANDOFF",
    ],
    "FW-04": [
        "STEP.ASK.COMPUTER_AND_CARD_READER",
        "STEP.APP.CHECK_FIRMWARE_MENU",
    ],
    # ---- Category C: Mobile app pairing -----------------------------------
    "APP-01": [
        "STEP.APP.FORCE_CLOSE_REOPEN",
        "STEP.APP.RETRY_CONNECT_BUTTON",
        "STEP.ASK.APP_PERMISSIONS_GRANTED",
        "STEP.APP.CLEAR_CACHE",
        "STEP.APP.REINSTALL",
    ],
    "APP-02": [
        "STEP.ASK.APP_PERMISSIONS_GRANTED",
        "STEP.APP.CHECK_STORE_VERSION",
        "STEP.APP.REINSTALL",
    ],
    "APP-03": [
        "STEP.APP.EXPLAIN_AND_REQUEST_PERMISSION",
        "STEP.ASK.WHICH_PERMISSION_PROMPT",
    ],
    "APP-04": [
        "STEP.PHONE.DISABLE_WIFI_OLD_PHONE",
        "STEP.ASK.APP_ACCOUNT_REGISTERED",
    ],
    # ---- Category D: Not recording / loop recording -----------------------
    "REC-01": [
        "STEP.SAFETY.PRESERVE_CARD_POWER_OFF",
        "STEP.ESCALATE.HANDOFF",
    ],
    "REC-02": [
        "STEP.OBSERVE.READ_SCREEN_VERBATIM",
        "STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT",
        "STEP.ASK.CARD_PRESENT",
        # Milestone 4.6. The step's own description files it under "02 REC-02 +
        # SD-01" and it was in neither list, so no entry could offer it and the
        # policy layer could not propose it from anywhere: an unreachable step,
        # not a filtered one. Appended rather than inserted so the first legal
        # candidate — what `eval/baseline.py` and the LLM-unavailable floor
        # both take — is unchanged.
        "STEP.ASK.CARD_FROZEN_IN_TIME",
    ],
    "REC-03": [
        "STEP.ASK.WERE_CLIPS_LOCKED",
        "STEP.SETTINGS.CHECK_GSENSOR_SENSITIVITY",
    ],
    "REC-04": [
        "STEP.ASK.PARKED_POWER_SOURCE",
        "STEP.SETTINGS.CHECK_SETTING_SURVIVED_UPDATE",
        "STEP.SETTINGS.ENABLE_PARKING_MODE",
    ],
    # ---- Category E: SD card / storage ------------------------------------
    "SD-01": [
        "STEP.CARD.RESEAT",
        "STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST",
        "STEP.ASK.CARD_SPECS_AND_RATING",
        "STEP.CARD.FORMAT_IN_CAMERA",
        # A candidate the filter must *drop*, not one to propose: a
        # computer-formatted card is SD-01 cause 1 (02 §E), and once an
        # in-camera format has failed this is the same destructive family
        # (03 EVAL-12 "wrong response", 07 §free-text row). It has to be in
        # the candidate set for the family block to have anything to bite on.
        "STEP.CARD.FORMAT_ON_COMPUTER",
        # The other half of the same Milestone 4.6 wiring hole — see REC-02.
        # `docs/03` EVAL-27 makes this the expected next step and `docs/02`
        # files it under both entries; it has to be reachable from both.
        "STEP.ASK.CARD_FROZEN_IN_TIME",
    ],
    "SD-02": [
        "STEP.ASK.LOCKED_FILE_VOLUME",
        "STEP.SETTINGS.CHECK_LOOP_RECORDING",
    ],
    "SD-03": [
        "STEP.OBSERVE.TRY_DIFFERENT_PLAYER",
        "STEP.ASK.COPIED_OR_PLAYED_FROM_CARD",
        "STEP.ASK.SHUTDOWN_ABRUPT_OR_GRACEFUL",
    ],
    "SD-04": [
        "STEP.CARD.REPLACE_CARD",
        "STEP.ASK.CARD_SPECS_AND_RATING",
    ],
    # ---- Category F: Power / overheating ----------------------------------
    "PWR-01": [
        "STEP.ASK.OTHER_DEVICE_ON_SOCKET",
        "STEP.POWER.TRY_DIFFERENT_CABLE",
    ],
    "PWR-02": [
        "STEP.ASK.RECOVERS_WHEN_COOL",
        "STEP.ASK.CAMERA_RESTARTS_IN_HEAT",
    ],
    "PWR-03": [
        "STEP.ASK.HARDWIRE_KIT_AND_CUTOFF",
        "STEP.ASK.POWERED_SIGN_WHEN_PARKED",
    ],
    "PWR-04": [
        "STEP.SETTINGS.SET_DATE_TIME_AND_RETEST",
        "STEP.ASK.CAMERA_AGE_AND_DATE_HISTORY",
    ],
    # ---- Category G: Video quality / settings -----------------------------
    "VID-01": [
        "STEP.OBSERVE.CHECK_LENS_FILM_AND_CLEANLINESS",
        "STEP.PHYSICAL.CLEAN_LENS_AND_GLASS",
        "STEP.SETTINGS.CHECK_RESOLUTION",
    ],
    "VID-02": [
        "STEP.ASK.INTERIOR_VISIBLE_IN_FOOTAGE",
        "STEP.ASK.DASHBOARD_REFLECTIVE_OBJECTS",
        "STEP.SETTINGS.CHECK_EXPOSURE_WDR",
    ],
    "VID-03": [
        "STEP.ASK.SPLIT_SYMPTOMS_AUDIO_FIRST",
        "STEP.SETTINGS.CHECK_AUDIO_ENABLED",
        "STEP.OBSERVE.CHECK_MUTE_INDICATOR",
    ],
    # ---- Not a taxonomy entry ---------------------------------------------
    # 02 has no entry for these; 03 EVAL-28/29 require them.
    "NO_MATCH": [
        "STEP.ESCALATE.HANDOFF",
        "STEP.ASK.PHYSICAL_TRAUMA_HISTORY",
    ],
    "OUT_OF_SCOPE": [
        "STEP.ESCALATE.OUT_OF_SCOPE_TRANSFER",
    ],
}

#: The seven categories of `docs/02`, plus the two non-diagnostic outcomes that
#: `DiagnosticState.problem.category` allows (06 §3.3).
CATEGORIES: dict[str, str] = {
    "WIFI": "Wi-Fi connectivity",
    "FW": "Firmware update / compatibility",
    "APP": "Mobile app pairing",
    "REC": "Not recording / loop recording",
    "SD": "SD card / storage",
    "PWR": "Power / overheating",
    "VID": "Video quality / settings",
    "NO_MATCH": "No matching taxonomy entry",
    "OUT_OF_SCOPE": "Out of scope (billing, RMA, warranty, returns, non-Rove)",
}


def category_of(taxonomy_id: str) -> str:
    """Map a taxonomy ID to its category code."""
    if taxonomy_id in ("NO_MATCH", "OUT_OF_SCOPE"):
        return taxonomy_id
    prefix = taxonomy_id.split("-")[0]
    if prefix not in CATEGORIES:
        raise KeyError(f"unknown taxonomy id: {taxonomy_id!r}")
    return prefix


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

#: Outcomes that mark a step as tried-and-not-helpful, and therefore blocking
#: (06 §3.5). `unclear` blocks too, deliberately: 06 §3.6 treats an ambiguous
#: mapping as attempted, because re-proposing a step the user may already have
#: done is the exact behaviour 01 M4 forbids.
BLOCKING_OUTCOMES = frozenset({"no_change", "worse", "unclear"})

VALID_OUTCOMES = frozenset(
    {"success", "no_change", "worse", "not_attempted", "unclear"}
)


@dataclass
class AttemptedStep:
    """One entry in `DiagnosticState.ledger.attempted` (06 §3.3)."""

    step_id: str
    step_family: str
    source: str  # user_volunteered | agent_proposed
    outcome: str
    count: int | None = None
    turn: int | None = None
    verbatim: str = ""
    #: Extra step ids or family ids this attempt also blocks. Populated only
    #: where `docs/03` itself names the extra step under M4 -- e.g. EVAL-11
    #: cites a power cycle as an M4 violation after two camera resets.
    also_blocks: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.outcome in BLOCKING_OUTCOMES

    @property
    def information_only(self) -> bool:
        """Whether this entry's product was information rather than a change.

        `FAMILY.ASK` and `FAMILY.OBSERVE` are the two families `docs/06` §3.6
        exempts from no-repeat, and the reason it gives is that a question is
        not a step: its product is information. That makes them the wrong thing
        to count against `docs/02`'s cross-cutting trigger 1, **"Two next-steps
        attempted, symptom unchanged"** -- a question that was put and answered
        left the symptom unchanged because it was never going to change it, and
        the answer is the gain. See
        `agent.state.Ledger.agent_proposed_failures`.

        This is deliberately *not* a relaxation of `blocking`: an answered
        question still blocks itself under `blocked_ids` and under the
        asked-and-answered filter, exactly as before. The two properties read
        the same entry for two different questions.
        """
        family = FAMILIES.get(self.step_family)
        return bool(family is not None and family.no_repeat_exempt)


def blocked_ids(ledger: list[AttemptedStep]) -> set[str]:
    """Every step id and family id blocked by a ledger (06 §3.5 NO-REPEAT)."""
    blocked: set[str] = set()
    for entry in ledger:
        if not entry.blocking:
            continue
        blocked.add(entry.step_id)
        blocked.add(entry.step_family)
        blocked.update(entry.also_blocks)
    return blocked


# --------------------------------------------------------------------------
# The policy filter (06 §3.5), minus the parts Phase 0 has no inputs for
# --------------------------------------------------------------------------


@dataclass
class Candidate:
    step_id: str
    kept: bool
    drop_reason: str | None = None


def legal_candidates(
    taxonomy_id: str,
    ledger: list[AttemptedStep],
    *,
    allow_destructive: bool = False,
    model_known: bool = False,
    driving: bool = False,
    footage_at_stake: bool = False,
) -> list[Candidate]:
    """Run the `docs/06` §3.5 filter chain over a taxonomy entry's candidates.

    Returns every candidate with a kept/dropped verdict and a drop reason, so a
    no-repeat breach is debuggable in one look (06 §7.5). Source clearance and
    discriminating-power ranking are Phase 1 concerns and are not implemented:
    candidates stay in the order `TAXONOMY_CANDIDATES` lists them.
    """
    blocked = blocked_ids(ledger)
    out: list[Candidate] = []
    for step_id in TAXONOMY_CANDIDATES.get(taxonomy_id, []):
        step = STEPS[step_id]
        reason: str | None = None
        if not step.no_repeat_exempt and (
            step_id in blocked or step.family in blocked
        ):
            reason = "no-repeat: in ledger as tried-and-failed, or same family"
        elif step.destructive and not allow_destructive:
            reason = "destructive: requires the gate (cause + consent + consequence)"
        elif step.model_specific and not model_known:
            reason = "model clearance: step is model-specific, model is UNKNOWN"
        elif driving and step.needs_hands:
            reason = "safety: driving gate active and the step needs hands"
        elif footage_at_stake and step.risks_footage:
            reason = "safety: footage at stake and the step risks it"
        out.append(Candidate(step_id, kept=reason is None, drop_reason=reason))
    return out


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------


class OntologyError(AssertionError):
    """The ontology is internally inconsistent."""


def validate() -> None:
    """Fail loudly if the ontology or the map is inconsistent."""
    for step in STEPS.values():
        if step.family not in FAMILIES:
            raise OntologyError(
                f"step {step.id!r} names family {step.family!r}, which does not exist"
            )
        if FAMILIES[step.family].destructive and not step.destructive:
            raise OntologyError(
                f"step {step.id!r} is in destructive family {step.family!r} "
                "but is not marked destructive"
            )
    for taxonomy_id, step_ids in TAXONOMY_CANDIDATES.items():
        category_of(taxonomy_id)  # raises on an unknown prefix
        if not step_ids:
            raise OntologyError(f"{taxonomy_id!r} has no candidate steps")
        if len(set(step_ids)) != len(step_ids):
            raise OntologyError(f"{taxonomy_id!r} lists a duplicate candidate")
        for step_id in step_ids:
            if step_id not in STEPS:
                raise OntologyError(
                    f"{taxonomy_id!r} names step {step_id!r}, which is not in the "
                    "ontology"
                )


validate()
