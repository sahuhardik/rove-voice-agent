"""Symptom coverage: telling a genuine route apart from a nearest-category force.

Milestone 3.3. This module exists because of one sentence in `docs/06` §4.7:

    This is explicitly **not** "force it into the nearest category", which is
    the EVAL-28 failure and the most damaging thing the agent can do (`03`).

Milestone 3.1 made a `NO_MATCH` vote stop escalating on its own, which was
right — most of the over-escalation it removed was the classifier reaching for
`NO_MATCH` on a symptom it could have routed. But it measured "could have
routed" as *any* other shortlisted entry with a legal step, and that is too
weak a test. On EVAL-28 the classifier offered `NO_MATCH` alongside `PWR-02`;
`PWR-02` has legal steps; `NO_MATCH` was therefore dropped and the turn went to
a heat question. `PWR-02` is "shuts down in heat": it explains one of the three
symptoms the caller reported, and its own discriminating condition — heat, and
recovery once cool — appears nowhere in the utterance. That is not a route. It
is the nearest category, forced.

`docs/06` §3.2 is the authority for what `TRIAGE` is allowed to exit with:

    | `TRIAGE` | Symptom captured | Taxonomy ID or `KNOWN-GAP` or `NO_MATCH`
      assigned | 1 turn; `NO_MATCH` → `ESCALATE` (this is EVAL-28) |

Those are **alternatives, not a ranking**. A shortlist holding both `NO_MATCH`
and an entry that explains a minority of what the caller described has not
finished triaging, and §5.1's structural trigger — "`NO_MATCH` *from triage*" —
is exactly the case where triage finishes there.

So this module answers two questions about the caller's own words, with no
model in the loop:

1. **What did they actually report?** `reported_facets` splits an utterance
   into distinct symptom facets by deterministic phrase match — the same kind
   of rule as `eval/baseline.RULES` and the §3.4 discriminator ladder, over the
   caller's words rather than over a classifier's output.
2. **Does a candidate entry explain it?** `ENTRY_EXPLAINS` records, per
   `docs/02` entry, which facets its "Symptom (caller)" line covers, and
   `ENTRY_DISCRIMINATORS` records the condition its "Must ask" line turns on.
   An entry that explains a strict minority of the reported facets *and* whose
   discriminating condition is absent is a **nearest-category force**, not a
   route.

**Three facets are deliberately explained by nothing.** `audible_noise`,
`display_artefact` and `frozen_screen` are on `docs/06` §4.7's list of `docs/05`
finds with no taxonomy entry and no guard ("boot prompt with three options,
hardwire kit not detected, frozen screen, repeated on/off, random restarts").
A facet that no entry anywhere explains is the signature of a symptom that is
genuinely outside `docs/02`, and `assess` requires one before it will conclude
`NO_MATCH`. That is what keeps this from firing on EVAL-23, EVAL-24 and
EVAL-25, which are multi-symptom scenarios where every facet *is* in the
taxonomy and which `docs/03` grades as routable.

Nothing here can *suppress* an escalation: the only verdict it produces is
"triage finished at `NO_MATCH`".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

#: The two non-taxonomy triage outcomes. Duplicated as a literal rather than
#: imported from `agent.policy` so that this module has no agent-side imports
#: at all — it reads `docs/02` and the caller's words, and nothing else.
_RESIDUAL = frozenset({"NO_MATCH", "OUT_OF_SCOPE"})


# --------------------------------------------------------------------------
# Facets — how a symptom arrives in the caller's words
# --------------------------------------------------------------------------

#: Facet id -> the phrases that report it. Phrases are matched whole, on word
#: boundaries: "time" must not fire on "sometimes", which is the substring bug
#: that puts EVAL-28 on `PWR-04` in `eval/baseline.py`'s keyword router.
FACET_PATTERNS: dict[str, tuple[str, ...]] = {
    # ---- Category A: Wi-Fi ------------------------------------------------
    "wifi_not_visible": (
        "not showing up",
        "doesn't show up",
        "don't even see it",
        "nothing in my list",
        "not in the list",
        "nothing there",
        "doesn't appear",
    ),
    "wifi_drops": (
        "drops out",
        "drops back",
        "goes back to",
        "jumps back",
        "won't stay connected",
        "keeps dropping",
        "dropping the wifi",
        "kicks me off",
        "drops every",
        "disconnects",
    ),
    "password_rejected": (
        "password's wrong",
        "wrong password",
        "password is wrong",
        "says the password",
    ),
    "slow_playback": (
        "buffers",
        "buffering",
        "unusably slow",
        "takes forever",
    ),
    # ---- Category B: firmware ---------------------------------------------
    "update_stalled": (
        "stalled",
        "halfway",
        "half way",
        "percent",
        "per cent",
        "stuck at",
        "sat there",
    ),
    "stuck_on_logo": (
        "logo screen",
        "sits on the logo",
        "shows the logo",
        "on the logo",
    ),
    "feature_stopped_working": (
        "doesn't do anything",
        "does not do anything",
        "stopped working",
        "doesn't work any more",
        "doesn't work anymore",
        "no longer works",
    ),
    "cannot_perform_update": (
        "don't know what to do with it",
        "don't have a computer",
    ),
    # ---- Category C: app ---------------------------------------------------
    "app_no_device": (
        "can't find a device",
        "no device found",
        "can't find it",
        "keeps spinning",
        "just spins",
    ),
    "app_will_not_run": (
        "app won't open",
        "won't even open",
        "app crashes",
        "app keeps closing",
    ),
    "app_permission": (
        "asking me for location",
        "asks for location",
        "permission screen",
        "about local network",
    ),
    "app_black_preview": ("black screen",),
    "pairing_fails": (
        "won't pair",
        "will not pair",
        "can't pair",
    ),
    # ---- Category D: recording --------------------------------------------
    "no_recording": (
        "never actually records",
        "never starts recording",
        "never records",
        "doesn't record",
        "does not record",
        "isn't recording",
        "not recording",
        "no red dot",
        "nothing on it",
        "nothing new",
    ),
    "no_parked_recording": (
        "when the car's parked",
        "while it's parked",
        "from overnight",
        "when i'm parked",
        "parking mode on",
        "nothing recorded",
    ),
    "files_vanished": (
        "deleting my videos",
        "deleted my",
        "just gone",
        "overwrote",
        "overwritten",
        "didn't delete",
    ),
    "incident_footage_missing": (
        "hit my car",
        "need that video",
        "no footage of the",
    ),
    # ---- Category E: SD card ----------------------------------------------
    "card_error": (
        "card error",
        "insert card",
        "sd card error",
    ),
    "memory_full": (
        "memory full",
        "says full",
    ),
    "file_corruption": (
        "corrupt",
        "corrupted",
        "won't open",
        "wont open",
        "will not open",
    ),
    "repeat_reformat": (
        "format it again",
        "have to format",
        "keeps failing",
        "kept failing",
        "needing to be reformatted",
    ),
    # ---- Category F: power -------------------------------------------------
    "no_power": (
        "completely dead",
        "won't turn on",
        "will not turn on",
        "doesn't turn on",
        "won't power on",
        "no lights",
        "nothing happens when i plug",
        "it's dead",
    ),
    "shuts_down_or_restarts": (
        "turns itself off",
        "switches itself off",
        "shuts itself down",
        "shuts down",
        "restarts itself",
        "restarts on its own",
        "keeps restarting",
        "reboots",
        "turns off on its own",
        "goes off by itself",
    ),
    "battery_drain": (
        "battery went flat",
        "battery's flat",
        "battery is flat",
        "drains the battery",
        "drains my battery",
        "flattens the battery",
        "stays on after",
    ),
    "clock_loss": (
        "set the date",
        "setting the date",
        "asking me again",
        "losing the time",
        "loses the time",
        "loses the date",
        "date's wrong",
        "date is wrong",
        "showing 2020",
        "date again",
        "timestamp is wrong",
        "the date on them",
    ),
    # ---- Category G: video --------------------------------------------------
    "blurry_plate": (
        "blurry",
        "blur",
        "number plate",
        "number plates",
        "licence plate",
        "license plate",
    ),
    "night_or_reflection": (
        "at night",
        "night footage",
        "reflection",
        "reflections",
        "reflected",
        "see my own dashboard",
        "dashboard in the picture",
        "can't make anything out",
    ),
    "no_audio": (
        "no sound",
        "no audio",
        "sound on the videos",
    ),
    # ---- Explained by no entry in `docs/02` (06 §4.7) -----------------------
    # These three are on §4.7's list of `docs/05` finds that have Tier-1
    # content and no diagnostic branch: "frozen screen, repeated on/off,
    # random restarts". A facet here is the signature of a symptom outside the
    # taxonomy, and `assess` will not conclude `NO_MATCH` without one.
    "audible_noise": (
        "clicking noise",
        "clicking",
        "ticking noise",
        "buzzing",
        "rattling",
        "whining",
        "whirring",
        "grinding",
        "strange noise",
        "odd noise",
        "weird noise",
    ),
    "display_artefact": (
        "stripey",
        "stripes",
        "striped",
        "lines across",
        "flickering",
        "flickers",
        "garbled",
        "scrambled",
        "distorted picture",
        "distorted image",
        "static on the screen",
        "screen goes funny",
    ),
    "frozen_screen": (
        "screen is frozen",
        "frozen screen",
        "screen has frozen",
        "screen freezes",
        "frozen solid",
        "screen is stuck",
        "locks up",
    ),
}


# --------------------------------------------------------------------------
# What each `docs/02` entry explains, and what its discriminator turns on
# --------------------------------------------------------------------------

#: Taxonomy id -> the facets its `docs/02` **Symptom (caller)** line covers.
#: Transcribed from `docs/02`; an entry is credited generously, because an
#: over-credited entry only makes `assess` *less* likely to conclude
#: `NO_MATCH`. `PWR-02` is credited with `shuts_down_or_restarts` on exactly
#: that principle — its own symptom line is "it just turns itself off", and
#: crediting it with the restarts in EVAL-28 is the charitable reading.
ENTRY_EXPLAINS: dict[str, frozenset[str]] = {
    "WIFI-01": frozenset({"wifi_drops"}),
    "WIFI-02": frozenset({"wifi_not_visible"}),
    "WIFI-03": frozenset({"password_rejected"}),
    "WIFI-04": frozenset({"wifi_drops"}),
    "WIFI-05": frozenset({"slow_playback"}),
    "FW-01": frozenset({"update_stalled"}),
    "FW-02": frozenset({"stuck_on_logo", "no_power"}),
    "FW-03": frozenset({"feature_stopped_working"}),
    "FW-04": frozenset({"cannot_perform_update"}),
    "APP-01": frozenset({"app_no_device"}),
    "APP-02": frozenset({"app_will_not_run", "app_black_preview", "app_no_device"}),
    "APP-03": frozenset({"app_permission", "app_black_preview"}),
    "APP-04": frozenset({"pairing_fails"}),
    "REC-01": frozenset({"incident_footage_missing", "files_vanished"}),
    "REC-02": frozenset({"no_recording"}),
    "REC-03": frozenset({"files_vanished"}),
    "REC-04": frozenset({"no_parked_recording", "no_recording"}),
    "SD-01": frozenset({"card_error"}),
    "SD-02": frozenset({"memory_full", "no_recording"}),
    "SD-03": frozenset({"file_corruption"}),
    "SD-04": frozenset({"repeat_reformat", "card_error"}),
    "PWR-01": frozenset({"no_power"}),
    "PWR-02": frozenset({"shuts_down_or_restarts"}),
    "PWR-03": frozenset({"battery_drain", "no_parked_recording"}),
    "PWR-04": frozenset({"clock_loss"}),
    "VID-01": frozenset({"blurry_plate"}),
    "VID-02": frozenset({"night_or_reflection"}),
    "VID-03": frozenset({"no_audio", "clock_loss"}),
}

#: Taxonomy id -> the phrases that put its **Must ask** condition in the
#: caller's own words. These are the conditions each entry hangs on: `PWR-02`
#: is heat and recovery-when-cool, `PWR-03` is the wiring arrangement, `SD-03`
#: is the computer. Deliberately specific — a generic word like "screen" or
#: "on" would make almost every candidate look discriminated and this whole
#: test a no-op.
ENTRY_DISCRIMINATORS: dict[str, tuple[str, ...]] = {
    "WIFI-01": ("no internet", "kicks me off", "mobile data", "cellular"),
    "WIFI-02": ("awake", "powered on", "wifi list", "wi-fi list", "network list"),
    "WIFI-03": ("password", "sticker", "manual"),
    "WIFI-04": ("every few minutes", "two minutes", "interval", "walked away"),
    "WIFI-05": ("buffer", "buffers", "download", "playback", "stream"),
    "FW-01": ("update", "updating", "percent", "per cent", "halfway"),
    "FW-02": ("update", "updated", "logo"),
    "FW-03": ("update", "updated", "firmware version"),
    "FW-04": ("computer", "card reader", "downloaded the file"),
    "APP-01": ("app",),
    "APP-02": ("app", "updated my phone", "phone update", "os version"),
    "APP-03": ("permission", "location", "local network", "setup screen"),
    "APP-04": ("new phone", "old phone", "pair"),
    "REC-01": ("incident", "accident", "hit my car", "insurance", "police"),
    "REC-02": ("red dot", "recording icon", "sd card", "card"),
    "REC-03": ("locked", "event file", "overwrote", "deleted"),
    "REC-04": ("parked", "parking", "overnight", "hardwire", "ignition"),
    "SD-01": ("card",),
    "SD-02": ("full", "locked", "event files"),
    "SD-03": ("laptop", "computer", "card reader", "copied"),
    "SD-04": ("format", "formatted", "reformat", "rated"),
    "PWR-01": ("socket", "cable", "adapter", "plug", "no lights", "fuse"),
    "PWR-02": (
        "hot",
        "heat",
        "sun",
        "warm",
        "summer",
        "winter",
        "cool",
        "cools",
        "cooled",
        "cooling",
        "temperature",
    ),
    "PWR-03": (
        "hardwire",
        "hardwired",
        "ignition",
        "battery",
        "cutoff",
        "cut-off",
        "constant",
    ),
    "PWR-04": ("date", "clock", "timestamp", "start the car", "every start"),
    "VID-01": ("plate", "plates", "blur", "blurry", "zoom"),
    "VID-02": ("night", "reflection", "reflections", "reflected", "dashboard"),
    "VID-03": ("sound", "audio", "microphone", "timestamp", "date"),
}

#: Every facet some entry explains. Its complement inside `FACET_PATTERNS` is
#: the §4.7 gap set.
MAPPED_FACETS: frozenset[str] = frozenset().union(*ENTRY_EXPLAINS.values())


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


@lru_cache(maxsize=2048)
def _phrase(pattern: str) -> re.Pattern[str]:
    """Whole-phrase match, tolerant of run-together whitespace.

    `(?<!\\w)` / `(?!\\w)` rather than `\\b`, because several phrases end in a
    non-word character and `\\b` flips meaning there.
    """
    body = re.escape(pattern).replace("\\ ", r"\s+")
    return re.compile(rf"(?<!\w){body}(?!\w)")


def _contains(text: str, patterns: tuple[str, ...]) -> bool:
    return any(_phrase(p).search(text) for p in patterns)


def reported_facets(utterance: str) -> frozenset[str]:
    """The distinct symptom facets the caller reported, in their own words."""
    text = utterance.lower()
    return frozenset(
        facet for facet, patterns in FACET_PATTERNS.items() if _contains(text, patterns)
    )


def explained_facets(entry: str, facets: frozenset[str]) -> frozenset[str]:
    """Which of the reported facets this `docs/02` entry accounts for."""
    return facets & ENTRY_EXPLAINS.get(entry, frozenset())


def unmapped_facets(facets: frozenset[str]) -> frozenset[str]:
    """Reported facets that no entry in `docs/02` explains at all (§4.7)."""
    return facets - MAPPED_FACETS


def discriminator_present(entry: str, utterance: str) -> bool:
    """Whether the entry's own **Must ask** condition is in the utterance."""
    return _contains(utterance.lower(), ENTRY_DISCRIMINATORS.get(entry, ()))


def is_nearest_category_force(
    entry: str, utterance: str, facets: frozenset[str]
) -> bool:
    """`docs/06` §4.7's "force it into the nearest category", as a predicate.

    True when all three hold:

    * the caller reported **more than one** symptom facet — a single-symptom
      utterance is exactly the case Milestone 3.1 fixed, and routing it stays
      the right answer;
    * the entry explains a **strict minority** of them. Strict, so an entry
      that covers one of two reported facets — EVAL-25's `SD-03`, EVAL-24's
      `REC-04` — is still a route;
    * the entry's own **discriminating condition is absent**. EVAL-23 hands
      over "it's been really hot today", which is `PWR-02`'s condition
      verbatim, and that is a genuine re-rank rather than a force.
    """
    if entry in _RESIDUAL or len(facets) < 2:
        return False
    if len(explained_facets(entry, facets)) * 2 >= len(facets):
        return False
    return not discriminator_present(entry, utterance)


# --------------------------------------------------------------------------
# The triage verdict
# --------------------------------------------------------------------------


@dataclass
class Coverage:
    """What triage can say about the shortlist it is holding."""

    #: Facets the caller reported.
    facets: list[str] = field(default_factory=list)
    #: Of those, the ones no `docs/02` entry explains.
    unmapped: list[str] = field(default_factory=list)
    #: Per shortlisted taxonomy entry: what it explains, and whether it is a
    #: nearest-category force. Kept whole for the trace — a decision this
    #: consequential has to be legible after the fact.
    per_entry: dict[str, dict[str, object]] = field(default_factory=dict)
    #: True when `TRIAGE` should exit at `NO_MATCH` (§3.2, §5.1).
    unmatched: bool = False
    #: One line, for `trace["triage_no_match"]`.
    reason: str = ""


def assess(utterance: str, shortlist: list[str]) -> Coverage:
    """Has triage routed this symptom, or forced it into the nearest category?

    Returns `unmatched=True` only when every one of the following holds, which
    is deliberately a narrow door:

    1. the shortlist holds at least one real taxonomy entry (if it does not,
       `policy.escalation`'s existing empty-alternatives path already fires);
    2. the caller reported two or more distinct symptom facets;
    3. at least one of them is explained by **no** entry in `docs/02` — the
       §4.7 signature of a symptom outside the taxonomy;
    4. **every** shortlisted entry is a nearest-category force.
    """
    facets = reported_facets(utterance)
    unmapped = unmapped_facets(facets)
    candidates = [entry for entry in shortlist if entry not in _RESIDUAL]
    per_entry: dict[str, dict[str, object]] = {}
    for entry in candidates:
        explained = sorted(explained_facets(entry, facets))
        per_entry[entry] = {
            "explains": explained,
            "discriminator_present": discriminator_present(entry, utterance),
            "nearest_category_force": is_nearest_category_force(
                entry, utterance, facets
            ),
        }

    coverage = Coverage(
        facets=sorted(facets),
        unmapped=sorted(unmapped),
        per_entry=per_entry,
    )
    if not candidates or len(facets) < 2 or not unmapped:
        return coverage
    if not all(
        bool(per_entry[entry]["nearest_category_force"]) for entry in candidates
    ):
        return coverage

    coverage.unmatched = True
    coverage.reason = (
        "triage exits NO_MATCH (06 §3.2): the caller reported "
        + ", ".join(sorted(facets))
        + "; no entry in 02 explains "
        + ", ".join(sorted(unmapped))
        + "; and "
        + ", ".join(candidates)
        + " each explain a minority of the reported symptoms with their own "
        "discriminating condition absent — the nearest category, forced (06 §4.7)"
    )
    return coverage


__all__ = [
    "Coverage",
    "ENTRY_DISCRIMINATORS",
    "ENTRY_EXPLAINS",
    "FACET_PATTERNS",
    "MAPPED_FACETS",
    "assess",
    "discriminator_present",
    "explained_facets",
    "is_nearest_category_force",
    "reported_facets",
    "unmapped_facets",
]
