"""The metadata layer: registry, model vocabulary, evidence map, flags.

Everything in this module is *declared*, not inferred. Three rules govern it,
all three taken from the design record rather than invented here:

1. **Model applicability is explicit, never inferred** (`docs/06` §4.3:
   "explicit, never 'all'"). A manual's models come from the `docs/05` source
   table, which assigns each of `M1`..`M6` a model and a hardware revision. A
   shared page (official site, Help Center) gets the models whose names appear
   *in the chunk's own text*; if none appear, the chunk is marked
   `cross_model` and carries the full documented set, which is what
   `docs/06` §4.6 filters on when the device is `UNKNOWN`.

2. **Verification status comes from `docs/05`, per taxonomy entry** — the
   headline table, which Milestone 4.3 moved from 10/13/1/4 to **10 VERIFIED,
   14 CORRECTED, 1 REJECTED, 3 UNVERIFIED** when the Track C sources promoted
   `PWR-02`. A chunk inherits the status of the entries it is evidence for. A
   chunk that is evidence for no entry has not been through Step 1b and is
   `UNVERIFIED`.

3. **`speakable` is a gate, not a property** (`docs/06` §4.5). Tier 1, and
   `verification_status` in {VERIFIED, CORRECTED}, and a non-empty source.
   Nothing else is speakable. REJECTED and UNVERIFIED are not.

The provenance hole (`docs/06` §4.4) is handled, not hidden: see
`PROVENANCE_OPERATOR_ATTESTED` and `speakable_scope` below.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Every file in this package is Tier 1 (`docs/04` "How to use this file").
#: Tier 2 and Tier 3 are not ingested at all -- `docs/06` §4.5 item 1 requires
#: physical separation, and the cheapest physical separation is not having a
#: reader for them.
TIER = 1

#: `data/README.md` "Snapshot taken 2026-11-07", and every row of
#: `data/raw/DOWNLOAD_LOG.txt`.
RETRIEVAL_DATE = "2026-11-07"

PROVENANCE_CRAWLER = "crawler"
#: `docs/06` §4.4. Five manuals were uploaded by hand and have no source URL.
PROVENANCE_OPERATOR_ATTESTED = "operator_attested"

#: Who attested the five hand-uploaded manuals (`data/README.md`,
#: `docs/04` "Manuals added manually -- 2026-11-07").
ATTESTED_BY = "Hardik"

#: `docs/06` §4.4: operator-attested material is speakable "for the prototype
#: only", and the production gate in §9.1 Phase 4 does not pass without a
#: signed per-file record.
SCOPE_PRODUCTION = "production"
SCOPE_PROTOTYPE = "prototype"

VERIFIED = "VERIFIED"
CORRECTED = "CORRECTED"
UNVERIFIED = "UNVERIFIED"
REJECTED = "REJECTED"

#: Strongest first. A chunk that is evidence for several entries takes the
#: strongest status among them.
STATUS_RANK = {VERIFIED: 0, CORRECTED: 1, UNVERIFIED: 2, REJECTED: 3}

#: `docs/06` §4.5 item 3.
SPEAKABLE_STATUSES = frozenset({VERIFIED, CORRECTED})

#: `docs/06` §4.6: "the firmware facet is deliberately degenerate". One
#: version string exists in the whole corpus and it is the 2017 shipping build
#: of a discontinued revision, so every chunk says `unknown` and the facet
#: exists only so the schema does not need migrating when a real feed arrives.
FIRMWARE_APPLICABILITY = {"version": "unknown"}


# ---------------------------------------------------------------------------
# Models (docs/06 §4.3 vocabulary; docs/05 "The verified Rove dash cam line")
# ---------------------------------------------------------------------------

R2_4K_MINI_USB = "R2-4K_MINI_USB"
R2_4K_USB_C = "R2-4K_USB_C"
R2_4K_PRO = "R2-4K_PRO"
R2_4K_DUAL = "R2-4K_DUAL"
R2_4K_DUAL_PRO = "R2-4K_DUAL_PRO"
R3 = "R3"

#: The six documented models. R1 and R4 appear in no chunk, and `docs/06` §4.3
#: says that is correct: we have no manual for either.
ALL_MODELS: tuple[str, ...] = (
    R2_4K_MINI_USB,
    R2_4K_USB_C,
    R2_4K_PRO,
    R2_4K_DUAL,
    R2_4K_DUAL_PRO,
    R3,
)

#: Both R2-4K hardware revisions answer to the bare name "R2-4K". A shared
#: page that says "R2-4K" without qualifying the revision means both, and
#: `docs/05` is explicit that stopping at "an R2-4K" has not finished
#: identifying the device.
R2_4K_EITHER_REVISION = (R2_4K_MINI_USB, R2_4K_USB_C)

#: Ordered longest-name-first so that "R2-4K DUAL PRO" is not eaten by the
#: "R2-4K DUAL" pattern. Matched against the chunk's own body text only.
_MODEL_PATTERNS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"R2[\s_-]*4K[\s_-]*DUAL[\s_-]*PRO", re.I), (R2_4K_DUAL_PRO,)),
    (re.compile(r"R2[\s_-]*4K[\s_-]*DUAL", re.I), (R2_4K_DUAL,)),
    (re.compile(r"R2[\s_-]*4K[\s_-]*PRO", re.I), (R2_4K_PRO,)),
    (re.compile(r"R2[\s_-]*4K[\s_-]*MINI[\s_-]*USB", re.I), (R2_4K_MINI_USB,)),
    (re.compile(r"\bR2[\s_-]*4K\b", re.I), R2_4K_EITHER_REVISION),
    (re.compile(r"\bR3\b", re.I), (R3,)),
]

#: "mini-USB version" appearing anywhere pins the chunk to that revision --
#: `docs/05` notes the Help Center carries a dedicated mini-USB firmware
#: procedure.
_MINI_USB_RE = re.compile(r"mini[\s_-]*usb", re.I)


def models_named_in(text: str) -> tuple[list[str], bool]:
    """Return (models explicitly named in `text`, cross_model).

    Nothing is inferred: a model is in the list only because its name is
    written in the text. When no model is named the chunk applies to the whole
    documented line and is flagged `cross_model`, which is the only form
    `docs/06` §4.6 allows a retrieval to use when the device is UNKNOWN.
    """
    found: list[str] = []
    for pattern, models in _MODEL_PATTERNS:
        if pattern.search(text):
            for model in models:
                if model not in found:
                    found.append(model)
    if found and _MINI_USB_RE.search(text) and R2_4K_USB_C in found:
        # An explicit mini-USB qualification narrows the bare-name match.
        found = [m for m in found if m != R2_4K_USB_C]
    if not found:
        return list(ALL_MODELS), True
    ordered = [m for m in ALL_MODELS if m in found]
    return ordered, ordered == list(ALL_MODELS)


def models_spoken_in(utterance: str) -> list[str]:
    """Models a caller named in one sentence, longest name winning.

    `models_named_in` tags chunks, where "R2-4K DUAL PRO" legitimately also
    matches the shorter names inside it. A caller who says "R2-4K Pro" has named
    one camera, not three, so each matched span is blanked before the shorter
    patterns run. Nothing is inferred: no name written, no model returned, and
    a bare "R2-4K" stays both revisions rather than guessing one.
    """
    remaining = utterance
    found: list[str] = []
    for pattern, models in _MODEL_PATTERNS:
        if pattern.search(remaining):
            for model in models:
                if model not in found:
                    found.append(model)
            remaining = pattern.sub(" ", remaining)
    if _MINI_USB_RE.search(utterance) and R2_4K_USB_C in found:
        found = [m for m in found if m != R2_4K_USB_C]
    return [m for m in ALL_MODELS if m in found]


# ---------------------------------------------------------------------------
# The source registry (docs/06 §4.4; data/README.md; data/raw/DOWNLOAD_LOG.txt)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """One registry entry. Keyed by `doc_code`, exactly as `docs/05` codes it."""

    doc_code: str
    title: str
    path: str
    kind: str  # manual_text | official_html | help_center_html
    source_url: str | None
    provenance: str
    #: Models the *document* is about, when `docs/05` assigns them (manuals).
    #: Empty for shared pages, where applicability is read per chunk.
    models: tuple[str, ...] = ()
    hw_revision_specific: bool = False
    note: str = ""

    @property
    def retrieval_date(self) -> str:
        return RETRIEVAL_DATE

    @property
    def tier(self) -> int:
        return TIER

    @property
    def speakable_scope(self) -> str:
        """`docs/06` §4.4: operator-attested is prototype-only."""
        if self.provenance == PROVENANCE_OPERATOR_ATTESTED:
            return SCOPE_PROTOTYPE
        return SCOPE_PRODUCTION


_MANUAL_DIR = "data/text/manuals"
_OFFICIAL_DIR = "data/raw/official"
_HELP_DIR = "data/raw/help-center"

_OPERATOR_NOTE = (
    "Uploaded by hand on 2026-11-07; no source URL in DOWNLOAD_LOG.txt. "
    "provenance=operator_attested per docs/06 §4.4 -- speakable for the "
    "prototype only, and the §9.1 Phase 4 production gate does not pass "
    "until a signed per-file record exists."
)

#: The Tier-1 documents, in the order `docs/05` codes them. `docs/06` §4.1
#: describes the original 21 (6 manuals, 3 official pages, 12 Help Center
#: articles); Milestone 4.3 (Track C) adds a 7th manual and 6 more Help Center
#: articles, for **28**: 7 manuals, 3 official pages, 18 Help Center articles.
_SOURCE_LIST: list[Source] = [
    # ---- manuals ---------------------------------------------------------
    Source(
        "M1",
        "ROVE R2-4K User Manual (original mini-USB revision)",
        f"{_MANUAL_DIR}/dc3831.txt",
        "manual_text",
        None,
        PROVENANCE_OPERATOR_ATTESTED,
        models=(R2_4K_MINI_USB,),
        hw_revision_specific=True,
        note=_OPERATOR_NOTE,
    ),
    Source(
        "M2",
        "ROVE R2-4K User Manual (USB-C revision, supercapacitor)",
        f"{_MANUAL_DIR}/ROVE R2-4K User Manual.txt",
        "manual_text",
        None,
        PROVENANCE_OPERATOR_ATTESTED,
        models=(R2_4K_USB_C,),
        hw_revision_specific=True,
        note=_OPERATOR_NOTE,
    ),
    Source(
        "M3",
        "User Manual For New R2-4K (USB-C revision, later printing)",
        f"{_MANUAL_DIR}/User Manual For New R2-4K.txt",
        "manual_text",
        None,
        PROVENANCE_OPERATOR_ATTESTED,
        models=(R2_4K_USB_C,),
        hw_revision_specific=True,
        note=_OPERATOR_NOTE,
    ),
    Source(
        "M4",
        "ROVE R2-4K Dual Dash Cam Instruction Manual",
        f"{_MANUAL_DIR}/ROVE R2-4K Dual Dash Cam Instruction Manual.txt",
        "manual_text",
        None,
        PROVENANCE_OPERATOR_ATTESTED,
        models=(R2_4K_DUAL,),
        note=_OPERATOR_NOTE,
    ),
    Source(
        "M5",
        "ROVE R2-4K DUAL PRO manual (B0F9SX3JB9)",
        f"{_MANUAL_DIR}/B0F9SX3JB9.txt",
        "manual_text",
        None,
        PROVENANCE_OPERATOR_ATTESTED,
        models=(R2_4K_DUAL_PRO,),
        note=(
            _OPERATOR_NOTE
            + " The ASIN matches the failed manuals.plus fetch; whether it is "
            "the same document was never established (data/README.md)."
        ),
    ),
    Source(
        "M6",
        "ROVE R3 manual (condensed)",
        f"{_MANUAL_DIR}/r3-manual-website-files.txt",
        "manual_text",
        "https://cdn.prod.website-files.com/6724e2eaaa40b55848edd7ed/"
        "67b4fdf3c7d8bc594263f46b_bezog.pdf",
        PROVENANCE_CRAWLER,
        models=(R3,),
        note=(
            "The R3 manual as published on the Rove storefront: the PDF was "
            "printed from that page, so pages 1-2 extract empty and page 3 "
            "carries the whole manual as one unbroken run of prose with no "
            "heading. Two consequences, both handled in ingest/chunk.py. "
            "(1) section_path has nothing to draw on, so these chunks fall "
            "back to this registry title (see _section_path_for). "
            "(2) The extraction brought the storefront in with it. The age "
            "gate ('Are you at least 18 years old?'), the 'FREE 3 DAY "
            "SHIPPING ON ALL DASH CAMS' banner, the firmware/downloads page "
            "lead-in, the community/EMAIL US/QR-code furniture and the "
            "trailing SEO keyword list are stripped as non-manual boilerplate "
            "(_MANUAL_INLINE_NOISE, _is_seo_keyword_run). Manual content is "
            "untouched: the magnetic- and suction-mount steps, the Wi-Fi "
            "pairing steps and the troubleshooting guide all remain."
        ),
    ),
    Source(
        "M7",
        "ROVE R2-4K DUAL PRO User Manual (official, updated printing)",
        f"{_MANUAL_DIR}/ROVE-R2-4K-DUAL-PRO.txt",
        "manual_text",
        "https://cdn.shopify.com/s/files/1/2287/2433/files/"
        "ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf",
        PROVENANCE_CRAWLER,
        models=(R2_4K_DUAL_PRO,),
        note=(
            "Added in Milestone 4.3 (Track C). Rove's own 91-page DUAL PRO "
            "manual, fetched from the Shopify CDN, so it carries a real "
            "source URL and is provenance=crawler -- not operator_attested, "
            "and not prototype-scoped. It supersedes nothing: `M5` "
            "(B0F9SX3JB9) stays in the registry as the 12-page manuals.plus "
            "capture, but `M7` is the primary DUAL PRO source: it is Rove's "
            "own printing and it carries the troubleshooting table, the "
            "temperature guideline and the thermal-shutdown note that `M5` "
            "does not have. The fetch "
            "post-dates data/raw/DOWNLOAD_LOG.txt, which was not re-run; the "
            "URL above is recorded in docs/04 instead. Front and back matter "
            "(the Facebook community invite, the 'contact us before returning "
            "the item' page, the WATCH HOW TO VIDEOS page and the back-cover "
            "contact block) are stripped as non-manual furniture -- see "
            "_MANUAL_FURNITURE in ingest/chunk.py."
        ),
    ),
    # ---- official site ---------------------------------------------------
    Source(
        "O1",
        "Firmware Update & Downloads",
        f"{_OFFICIAL_DIR}/firmware-update-downloads.html",
        "official_html",
        "https://www.rovedashcam.com/pages/firmware-update-downloads",
        PROVENANCE_CRAWLER,
    ),
    Source(
        "O2",
        "How to Connect Your ROVE Dash Cam to Your Phone",
        f"{_OFFICIAL_DIR}/connect-rove-to-phone.html",
        "official_html",
        "https://www.rovedashcam.com/blogs/rove-dash_cam/"
        "connect-rove-dash-cam-to-phone-app",
        PROVENANCE_CRAWLER,
    ),
    Source(
        "O3",
        "How to UPGRADE FIRMWARE For Rove R2-4K Dashcam",
        f"{_OFFICIAL_DIR}/update-firmware-r2-4k.html",
        "official_html",
        "https://www.rovedashcam.com/pages/update-firmware-rove-r2-4k-dash-cam",
        PROVENANCE_CRAWLER,
    ),
]

#: (file stem, article title, URL) for the 18 Help Center articles. The first
#: 12 come from `data/README.md` and `data/raw/DOWNLOAD_LOG.txt`; the last 6
#: were captured in Milestone 4.3 (Track C), after the log was written, and
#: their URLs are the canonical ones embedded in the saved pages themselves.
_HELP_ARTICLES: list[tuple[str, str, str]] = [
    (
        "troubleshoot-index",
        "Help Center - Troubleshoot index",
        "https://hc1.gorgias.help/en-US/articles/troubleshoot-128437",
    ),
    (
        "wifi-not-connecting",
        "WiFi NOT Connecting",
        "https://hc1.gorgias.help/en-US/wifi-not-connecting-477922",
    ),
    (
        "wifi-connected-disconnected",
        'ROVE dash cam repeatedly saying "WiFi Is Connected - WiFi Is Disconnected"',
        "https://hc1.gorgias.help/en-US/rove-dash-cam-repeatedly-saying-"
        "%E2%80%9Cwifi-is-connected--wifi-is-disconnected%E2%80%9D-472820",
    ),
    (
        "missing-videos",
        "I have missing videos on my ROVE dash cam",
        "https://hc1.gorgias.help/en-US/i-have-missing-videos-on-my-rove-dash-cam-472877",
    ),
    (
        "camera-does-not-turn-on",
        "My Camera does NOT Turn ON",
        "https://hc1.gorgias.help/en-US/my-camera-does-not-turn-on-472872",
    ),
    (
        "r3-no-gps-live-speed",
        "R3: NO GPS Live Speed",
        "https://hc1.gorgias.help/en-US/r3--no-gps-live-speed-477968",
    ),
    (
        "no-audio-sound",
        "Why my video recording has no Audio/Sound",
        "https://hc1.gorgias.help/en-US/why-my-video-recording-has-no-audiosound-476108",
    ),
    (
        "memory-card-too-slow",
        'Receiving "Memory Card Too Slow" error',
        "https://hc1.gorgias.help/en-US/receiving-%E2%80%9Cmemory-card-too-slow"
        "%E2%80%9D-error-503340",
    ),
    (
        "camera-does-not-turn-off",
        "My Camera does NOT Turn OFF (Always stays ON)",
        "https://hc1.gorgias.help/en-US/my-camera-does-not-turn-off-"
        "(always-stays-on)-477921",
    ),
    (
        "wifi-name-not-showing",
        "ROVE WIFI name not showing on my phone",
        "https://hc1.gorgias.help/en-US/rove-wifi-name-not-showing-on-my-phone-2106568",
    ),
    (
        "sign-in-error-rove-app",
        "I am getting an error when I sign in to my ROVE app",
        "https://hc1.gorgias.help/en-US/"
        "i-am-getting-an-error-when-i-sign-in-to-my-rove-app-2041277",
    ),
    (
        "know-your-dashcam-how-to",
        "Help Center - Know your dashcam | How to",
        "https://hc1.gorgias.help/en-US/articles/"
        "know-your-dashcam-%7C-how-to-128439",
    ),
    # ---- added in Milestone 4.3 (Track C) ---------------------------------
    (
        "overheating",
        "Why Is My Dashcam Overheating — What Causes It and How Can I Prevent It?",
        "https://hc1.gorgias.help/en-US/why-is-my-dashcam-overheating-"
        "%E2%80%94-what-causes-it-and-how-can-i-prevent-it-2143477",
    ),
    (
        "licence-plate",
        "Why can't I read the license plate number clearly?",
        "https://hc1.gorgias.help/en-US/"
        "why-can%E2%80%99t-i-read-the-license-plate-number-clearly-6249872",
    ),
    (
        "blurry-video",
        "Why is my video blurry or out of focus?",
        "https://hc1.gorgias.help/en-US/why-is-my-video-blurry-or-out-of-focus-6265378",
    ),
    (
        "random-restarting",
        "My dashcam is randomly restarting - how to diagnose the issue",
        "https://hc1.gorgias.help/en-US/my-dashcam-is-randomly-restarting-"
        "%E2%80%93-how-to-diagnose-the-issue-2005853",
    ),
    (
        "repeatedly-on-off",
        "Dash Cam Repeatedly Turning ON and OFF",
        "https://hc1.gorgias.help/en-US/dash-cam-repeatedly-turning-on-and-off-6267097",
    ),
    (
        "frozen-screen",
        "Dash Cam Screen is Frozen",
        "https://hc1.gorgias.help/en-US/dash-cam-screen-is-frozen-6260254",
    ),
]

for _stem, _title, _url in _HELP_ARTICLES:
    _SOURCE_LIST.append(
        Source(
            f"H:{_stem}",
            _title,
            f"{_HELP_DIR}/{_stem}.html",
            "help_center_html",
            _url,
            PROVENANCE_CRAWLER,
        )
    )

SOURCES: dict[str, Source] = {s.doc_code: s for s in _SOURCE_LIST}


# ---------------------------------------------------------------------------
# Verification status per taxonomy entry (docs/05 headline counts)
# ---------------------------------------------------------------------------

#: Transcribed from the `docs/05` headline table. 28 entries, no exceptions.
#: `PWR-02` moved UNVERIFIED -> CORRECTED in Milestone 4.3: the Help Center
#: overheating body (`H:overheating`) now exists, and with it the thermal
#: shutdown the entry hypothesised and the temperature limits it marked
#: `Unknown`. See the `docs/05` PWR-02 row for what changed and what did not.
TAXONOMY_STATUS: dict[str, str] = {
    "WIFI-01": CORRECTED,
    "WIFI-02": CORRECTED,
    "WIFI-03": CORRECTED,
    "WIFI-04": CORRECTED,
    "WIFI-05": VERIFIED,
    "FW-01": VERIFIED,
    "FW-02": VERIFIED,
    "FW-03": UNVERIFIED,
    "FW-04": CORRECTED,
    "APP-01": CORRECTED,
    "APP-02": UNVERIFIED,
    "APP-03": VERIFIED,
    "APP-04": UNVERIFIED,
    "REC-01": VERIFIED,
    "REC-02": VERIFIED,
    "REC-03": CORRECTED,
    "REC-04": VERIFIED,
    "SD-01": CORRECTED,
    "SD-02": REJECTED,
    "SD-03": VERIFIED,
    "SD-04": CORRECTED,
    "PWR-01": CORRECTED,
    "PWR-02": CORRECTED,
    "PWR-03": CORRECTED,
    "PWR-04": CORRECTED,
    "VID-01": VERIFIED,
    "VID-02": CORRECTED,
    "VID-03": VERIFIED,
    # ---- Category H, added in Milestone 5.2 (docs/02; docs/05 §5.2) -------
    # Written *from* the corpus rather than verified against it afterwards,
    # so every one of these is sourced on arrival. The two CORRECTED rows
    # correct `docs/05` and `docs/06` §4.7, not a caller-facing fact:
    # GAP-REAR-CHANNEL because `docs/05` recorded two R3-only causes as
    # line-wide, and GAP-GPS because both documents state the R3 mount-GPS
    # mechanism as fact when the only corpus text for it is a storefront
    # product title (`docs/04` classes listings as unspeakable).
    "GAP-REAR-CHANNEL": CORRECTED,
    "GAP-GPS": CORRECTED,
    "GAP-MOUNTING": VERIFIED,
    "GAP-TIMELAPSE": VERIFIED,
    # The five guards. No ranked causes, no discriminating step -- but they
    # gate chunks exactly like an entry, so they carry a status like one.
    "GAP-BOOT-PROMPT": VERIFIED,
    "GAP-HWK-NOT-DETECTED": VERIFIED,
    "GAP-FROZEN-SCREEN": VERIFIED,
    "GAP-ON-OFF-CYCLING": VERIFIED,
    "GAP-RANDOM-RESTART": VERIFIED,
}

#: `docs/06` §4.3 marks these three safety-critical. `docs/02` calls FW-01
#: "High-risk entry: the wrong advice here destroys the device", FW-02
#: escalation-first, and REC-01 preserve-first.
#:
#: Milestone 5.2 adds two Category H ids under `docs/02` "Entries where the
#: first step is not diagnosis": GAP-REAR-CHANNEL, because the camera must be
#: powered OFF before the rear cable is touched and hot-plugging it is a
#: documented damage path, and GAP-HWK-NOT-DETECTED, because the only
#: published remedy is vehicle wiring and the hazard is the caller's car.
SAFETY_CRITICAL_IDS = frozenset(
    {
        "FW-01",
        "FW-02",
        "REC-01",
        "GAP-REAR-CHANNEL",
        "GAP-HWK-NOT-DETECTED",
    }
)

#: `docs/06` §4.3. These are frequently the device working as designed
#: (`docs/02` "Entries that are expectation gaps, not faults").
#:
#: Milestone 5.2 adds the three Category H ids that section names: the
#: parking-mode branch of GAP-TIMELAPSE, the GAP-BOOT-PROMPT dialog, and
#: GAP-MOUNTING -- where a windscreen flatter than ~20 degrees is a product
#: limitation Rove states outright, not a fault to keep troubleshooting.
EXPECTATION_GAP_IDS = frozenset(
    {
        "REC-03",
        "VID-01",
        "VID-02",
        "WIFI-05",
        "PWR-02",
        "GAP-TIMELAPSE",
        "GAP-BOOT-PROMPT",
        "GAP-MOUNTING",
    }
)

#: `docs/06` §4.3 category codes, plus GAP.
CATEGORY_OF_PREFIX = {
    "WIFI": "WIFI",
    "FW": "FW",
    "APP": "APP",
    "REC": "REC",
    "SD": "SD",
    "PWR": "PWR",
    "VID": "VID",
}


# ---------------------------------------------------------------------------
# The evidence map: docs/05's own citations, turned into matchers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRule:
    """One `docs/05` citation, expressed as something a chunk can match.

    `docs/05` cites evidence as "`M3` §LOOP RECORDING IMPORTANT (p.46)" or
    "`H:wifi-not-connecting`". A rule reproduces that: the documents the
    citation names, and a phrase or section pattern that identifies the part
    of the document it points at. A chunk is evidence for the entry when it
    comes from one of those documents *and* carries one of the phrases.

    Nothing matches on the strength of a document alone: a chunk about the
    package contents of the DUAL is not evidence for WIFI-05 merely because
    `docs/05` cites `M4` somewhere.
    """

    taxonomy_id: str
    doc_codes: tuple[str, ...]
    #: Any one of these, matched case-insensitively against the chunk text.
    phrases: tuple[str, ...]
    #: Optional extra requirement on the section heading path.
    section: str | None = None

    def matches(self, doc_code: str, text: str, section_path: str) -> bool:
        if doc_code not in self.doc_codes:
            return False
        if self.section and not re.search(self.section, section_path, re.I):
            return False
        return any(re.search(p, text, re.I) for p in self.phrases)


_MANUALS_R2 = ("M1", "M2", "M3")
_ALL_MANUALS = ("M1", "M2", "M3", "M4", "M5", "M6", "M7")

#: One block per `docs/05` per-issue row, for the 24 entries Step 1b marked
#: VERIFIED or CORRECTED. The three remaining UNVERIFIED entries (FW-03,
#: APP-02, APP-04) get no rule *on purpose*: `docs/05` searched the corpus and
#: recorded "no hit". Inventing a matcher for them would manufacture the
#: coverage the verification report says does not exist. SD-02 is REJECTED and
#: gets no rule for the same reason -- and `docs/06` §4.5 would strip
#: `speakable` from anything it matched anyway.
#:
#: Milestone 4.3 widened the `doc_codes` of existing rules to the Track C
#: sources, but **only where the new document actually carries the fact**: see
#: the `docs/05` per-issue table, which was re-checked against `M7` and the
#: six new Help Center bodies before any code was added here. `M7` is
#: deliberately *absent* from `FW-01` and `FW-02`: it documents no card-side
#: update at all, and its one "BLINKING RED LED" line means *recording*, not
#: *updating* -- exactly the confusion `docs/02` calls device-destroying.
#:
#: The three new Help Center articles with no taxonomy entry behind them
#: (`H:random-restarting`, `H:repeatedly-on-off`, `H:frozen-screen`) appear in
#: no rule. They are indexed, and they are UNVERIFIED and unspeakable, which
#: is the correct state for Tier 1 material that Step 1b has no entry to hang
#: a status on. Writing those entries is Phase 2 work (`docs/06` §9.1).
EVIDENCE: tuple[EvidenceRule, ...] = (
    # ---- Category A: Wi-Fi ------------------------------------------------
    EvidenceRule(
        "WIFI-01",
        (
            "O2",
            "H:wifi-connected-disconnected",
            "H:wifi-not-connecting",
            "M2",
            "M3",
            "M7",
        ),
        (
            r"no\s*internet",
            r"keep trying wi-?fi",
            r"always connect",
            r"don'?t ask again for this network",
            r"wifi is connected.{0,12}wifi is disconnected",
        ),
    ),
    EvidenceRule(
        "WIFI-02",
        (
            "O2",
            "H:wifi-not-connecting",
            "H:wifi-name-not-showing",
            "M2",
            "M3",
            "M6",
            "M7",
        ),
        (
            r"emergency lock",
            r"wifi mode",
            r"some phones don'?t show",
            r"can'?t see the rove network",
            r"name not showing",
            r"network name starts with",
            r"wifi icon",
        ),
    ),
    EvidenceRule(
        "WIFI-03",
        ("O2", "H:wifi-not-connecting", "H:know-your-dashcam-how-to") + _ALL_MANUALS,
        (
            r"12345678",
            r"wi-?fi password",
            r"change the wifi name and password",
            r"default password",
        ),
    ),
    EvidenceRule(
        "WIFI-04",
        (
            "O2",
            "H:wifi-not-connecting",
            "H:wifi-connected-disconnected",
            "M2",
            "M3",
            "M6",
            "M7",
        ),
        (
            r"10\s*met(er|re)s?",
            r"33\s*(ft|feet)",
            r"stay on at all times",
            r"always on",
            r"obstruction",
        ),
    ),
    EvidenceRule(
        "WIFI-05",
        ("O2", "M3", "M4", "M5", "M7"),
        (
            r"mb/s",
            r"how fast are downloads",
            r"dual band wifi\s*6",
            r"playback on pc",
            r"2\s*[x×]\s*faster",
        ),
    ),
    # ---- Category B: firmware ---------------------------------------------
    EvidenceRule(
        "FW-01",
        ("O1", "O3"),
        (
            r"don'?t disconnect the power",
            r"power does ?n'?t get disconnected",
            r"blinking red",
            r"flashing red",
            r"allow the update to complete",
            r"without interruption",
            r"go through its cycle",
        ),
    ),
    EvidenceRule(
        "FW-02",
        ("O1", "O3", "H:camera-does-not-turn-on", "M3", "M6"),
        (
            r"keep updating the firmware",
            r"format.{0,60}(card|memory card).{0,60}again",
            r"remove the memory card",
            r"hard reset",
            r"paper ?clip",
            r"turns on without the card",
            r"firmware update issue",
        ),
    ),
    EvidenceRule(
        "FW-04",
        ("O1", "O2", "O3", "M2", "M3", "M7"),
        (
            r"over[\s-]*the[\s-]*air",
            r"unzip",
            r"usb flash drive",
            r"firmware update.{0,80}(left )?menu",
            r"update your dash cam'?s firmware",
            r"manual firmware update",
        ),
    ),
    # ---- Category C: app ---------------------------------------------------
    EvidenceRule(
        "APP-01",
        ("O2", "H:wifi-not-connecting", "H:wifi-name-not-showing"),
        (
            r"retry connect",
            r"correct\s*rove dash cam model",
            r"model is selected",
            r"turn off your vpn",
            r"clear .{0,20}(the )?(storage data and )?cache",
        ),
    ),
    EvidenceRule(
        "APP-03",
        ("O2", "H:wifi-not-connecting", "H:sign-in-error-rove-app"),
        (
            r"allow location access",
            r"location.{0,60}auto-?connect",
            r"grant access or permissions",
            r"allow all permissions",
            r"necessary permissions",
        ),
    ),
    # ---- Category D: recording --------------------------------------------
    EvidenceRule(
        "REC-01",
        ("O2", "M1", "M2", "M3", "M7"),
        (
            r"oldest locked video",
            r"turn(ed)? (the camera )?off before you remove",
            r"do not insert/?remove",
            r"download any locked video",
            r"retrieve your footage",
        ),
    ),
    EvidenceRule(
        "REC-02",
        ("H:missing-videos", "M1", "M2", "M3", "M7"),
        (
            r"memory card error",
            r"please insert (micro)?sd",
            r"card full",
            r"red dot",
            r"every 30 seconds",
            r"not recording",
        ),
    ),
    EvidenceRule(
        "REC-03",
        ("M1", "M2", "M3", "M5", "M7"),
        (
            r"locks many videos",
            r"g-?sensor setting",
            r"emergency (video )?lock",
            r"you can'?t lock unlimited",
            r"(?s)loop recording.{0,400}(oldest|delete|overwrit)",
        ),
    ),
    EvidenceRule(
        "REC-04",
        ("M3", "M4", "M5", "M6", "M7", "H:troubleshoot-index"),
        (
            r"24[\s-]*(hr|hour)s?[\s-]*(auto[\s-]*)?parking",
            r"(?s)hardwire kit.{0,400}park",
            r"(?s)park.{0,400}hardwire kit",
            r"always hot",
            r"11\.8",
            r"hardwire kit not detected",
        ),
    ),
    # ---- Category E: SD card ----------------------------------------------
    EvidenceRule(
        "SD-01",
        ("M1", "M2", "M3", "M7", "H:memory-card-too-slow"),
        (
            r"memory card error",
            r"crooked",
            r"shutter sound",
            r"fake",
            r"gold contacts",
            r"memory card too slow",
        ),
    ),
    EvidenceRule(
        "SD-03",
        ("O2", "M1", "M2", "M3", "M7", "H:no-audio-sound", "H:licence-plate"),
        (
            r"\bvlc\b",
            r"windows media player",
            r"quicktime",
            r"different media player",
        ),
    ),
    EvidenceRule(
        "SD-04",
        ("O1", "M1", "M2", "M3", "M4", "M5", "M6", "M7",
         "H:know-your-dashcam-how-to", "H:memory-card-too-slow", "H:overheating"),
        (
            r"512\s*gb",
            r"\b1\s*tb\b",
            r"class\s*10",
            r"\bu3\b",
            r"high endurance",
            r"format .{0,40}(every|month|week)",
            r"should i format",
        ),
    ),
    # ---- Category F: power -------------------------------------------------
    EvidenceRule(
        "PWR-01",
        ("H:camera-does-not-turn-on", "M1", "M2", "M3", "M6", "M7"),
        (
            r"does ?n[o']?t turn on",
            r"110\s*v",
            r"wall outlet",
            r"reset button",
            r"different .{0,20}usb cable",
        ),
    ),
    # `docs/05` PWR-02 was UNVERIFIED because the overheating article's body
    # was not captured. Milestone 4.3 captured it, and it documents the
    # thermal cut-off the entry hypothesised plus four heat *causes* the entry
    # does not carry. The published temperature limits -- which `docs/02` says
    # are Unknown and must not be quoted -- turn out to have been in `M1`-`M3`
    # and `M7` all along, which is why this is CORRECTED and not VERIFIED:
    # the entry's recovery-on-cooling discriminator is still undocumented.
    EvidenceRule(
        "PWR-02",
        ("H:overheating", "M1", "M2", "M3", "M6", "M7"),
        (
            r"overheat",
            r"high[\s-]*temperature",
            r"temperature guideline",
            r"operating temperature",
            r"automatically shut down",
            r"gets hot",
            r"run slightly hot",
            r"greenhouse effect",
        ),
    ),
    EvidenceRule(
        "PWR-03",
        ("H:camera-does-not-turn-off", "M1", "M2", "M3", "M7"),
        (
            # Anchored on the camera as the subject. The bare phrase also
            # matches the ROTATE VIDEO / compass note -- "by turning off this
            # feature, it does NOT turn OFF the Driving Speed" -- in `M2`,
            # `M3` and `M7`, which has nothing to do with powering down.
            r"camera does ?n[o']?t turn off",
            r"always stays on",
            r"always hot",
            r"cigarette.{0,40}(outlet|socket|lighter)",
            r"auto power on/?\s*off",
            r"press and hold the power",
        ),
    ),
    EvidenceRule(
        "PWR-04",
        ("M1", "M2", "M3", "M6", "M7",
         "H:know-your-dashcam-how-to", "H:missing-videos"),
        (
            r"supercapacitor",
            r"time zone",
            r"\bgmt\b",
            r"date and time is not staying",
            r"250\s*mah",
        ),
    ),
    # ---- Category G: video --------------------------------------------------
    EvidenceRule(
        "VID-01",
        ("M2", "M3", "M4", "M5", "M7", "H:blurry-video", "H:licence-plate"),
        (
            r"fuzzy",
            r"protective (plastic )?film",
            r"lens screen protector",
            r"clarity priority",
            r"video iq",
            r"blurry",
            r"out of focus",
            r"(?s)lens.{0,80}(clean|dirt|grease)",
        ),
    ),
    EvidenceRule(
        "VID-02",
        ("M3", "M4", "M5", "M7", "H:know-your-dashcam-how-to", "H:blurry-video"),
        (
            r"\bcpl\b",
            r"glare",
            r"reflection",
            r"\bwdr\b",
        ),
    ),
    EvidenceRule(
        "VID-03",
        ("M2", "M3", "M6", "M7", "H:no-audio-sound"),
        (
            r"mute",
            r"record audio",
            r"microphone (on|off)",
            r"no audio",
            r"audio recording",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Category H: the four known gaps and the five guards (docs/02; docs/06 §4.7)
# ---------------------------------------------------------------------------

#: Milestone 5.2 (Phase 2 knowledge completion) replaced the old `GAP_RULES`.
#:
#: Until 5.2 these four ids were matched by **bare keywords against any
#: document** -- `\bgps\b` tagged the M1 table of contents, `rear camera`
#: tagged a package-contents list -- because there was no `docs/02` entry to
#: anchor them to and the only job was to make the `KNOWN-GAP` routing
#: outcome findable. `docs/02` Category H now carries four full entries and
#: five guards, each with its own `docs/05` status and its own citations, so
#: these become ordinary `EvidenceRule`s: scoped to the documents that
#: actually carry the fact, and matched on the phrase the entry quotes.
#:
#: The four entries and the five guards share the `GAP-` prefix on purpose.
#: `docs/06` §4.3 fixes the category vocabulary at
#: `WIFI | FW | APP | REC | SD | PWR | VID | GAP` and §4.7 routes this whole
#: set -- gaps and guards alike -- through one outcome, so a sixth category
#: code would be a schema change for no gain. What separates an entry from a
#: guard is `docs/02`, not the id: a guard has no ranked cause list and no
#: discriminating step, only a must / must-not.
#:
#: Statuses live in `TAXONOMY_STATUS` with the other 28. Two of the four are
#: CORRECTED rather than VERIFIED, and in both cases what was corrected is
#: one of **our own documents** -- see the `docs/05` Milestone 5.2 rows.
GAP_EVIDENCE: tuple[EvidenceRule, ...] = (
    # -- the four entries ---------------------------------------------------
    # Rear channel exists only on the dual and 3-channel bodies. M6 carries
    # the two named causes (and they are R3 causes -- the sticky-mount power
    # port is an R3 mount feature, which is the correction in `docs/05`);
    # M4/M5/M7 carry the install, the hot-plug damage note and the alignment
    # requirement. M1-M3 are single-channel and are deliberately absent.
    EvidenceRule(
        "GAP-REAR-CHANNEL",
        ("M4", "M5", "M6", "M7"),
        (
            r"rear camera (cable|connector|live|not|is not|at the rear)",
            r"rear cam(era)? port",
            r"switch the front and rear",
            r"rear camera live view",
            r"plug in the rear camera",
            r"connect the rear camera",
            r"install the rear camera",
            r"mount rear camera",
        ),
    ),
    # The GPS *settings* and the fix-state readouts, not every mention of the
    # word. `O1` is excluded on purpose: its only R3-mount-GPS text is a
    # storefront product title, which `docs/04` classes as listing material
    # and `docs/05` 5.2 rules unspeakable.
    EvidenceRule(
        "GAP-GPS",
        ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "H:r3-no-gps-live-speed"),
        (
            r"live speed",
            r"speed stamp",
            r"gps location stamp",
            r"gps info",
            r"gps indicator",
            r"gps not connected",
            r"gps signal lock",
            r"quad-?mode gps",
            r"no gps related data",
            r"no gaps between them",
            r"vehicle'?s gps antenna",
        ),
    ),
    # Mounting: the 20-degree constraint, the dot-matrix band, the lock
    # procedure, the electrostatic film and the defroster-line note.
    EvidenceRule(
        "GAP-MOUNTING",
        ("M3", "M2", "M4", "M5", "M6", "M7", "H:know-your-dashcam-how-to"),
        (
            r"20\s*°\s*slope",
            r"flat windshield",
            r"dot-?matrix",
            r"locking knob",
            r"electrostatic film",
            r"defroster lines",
            r"suction mount",
            r"sticky mount",
            r"magnetic mount",
        ),
    ),
    # Time-lapse: the setting, its options, and the two restart notes that
    # disagree across hardware revisions.
    EvidenceRule(
        "GAP-TIMELAPSE",
        ("M1", "M2", "M3", "M5", "M6", "M7", "H:troubleshoot-index"),
        (
            r"time[\s-]?lapse record",
            r"time[\s-]?lapse video",
            r"time[\s-]?lapse recording mode",
            r"frame/second",
            r"fast motion",
            r"time-?lapse 1fps",
        ),
    ),
    # -- the five guards ----------------------------------------------------
    # The three-option USB prompt. The dialog itself is printed in M1-M3;
    # the cause and the "storage device" explanation are in the Help Center.
    EvidenceRule(
        "GAP-BOOT-PROMPT",
        (
            "M1",
            "M2",
            "M3",
            "O2",
            "H:know-your-dashcam-how-to",
            "H:troubleshoot-index",
        ),
        (
            r"connect as usb flash drive",
            r"connect as pc/mac webcam",
            r"operate camera normally",
            r"connect to pc/mac",
            r"type-?c usb function",
            r"three options",
        ),
    ),
    # Hardwire kit not detected. The only published remedy is a wiring check,
    # which `01` §4 puts out of scope -- hence a guard, and hence the
    # never-wire-to-the-battery caution travelling with it.
    EvidenceRule(
        "GAP-HWK-NOT-DETECTED",
        ("M3", "M7", "H:troubleshoot-index", "H:know-your-dashcam-how-to"),
        (
            r"hardwire kit not detected",
            r"hwk connected",
            r"never connect the dash cam directly",
            r"(?s)hardwire kit.{0,200}fuse box",
            r"why do i need hardwire kit",
        ),
    ),
    EvidenceRule(
        "GAP-FROZEN-SCREEN",
        ("M4", "M6", "M7", "H:frozen-screen"),
        (
            r"frozen",
            r"freez(e|es|ing)",
            r"unresponsive",
            r"lagging or crashing",
            r"force restart",
        ),
    ),
    EvidenceRule(
        "GAP-ON-OFF-CYCLING",
        ("M7", "H:repeatedly-on-off"),
        (
            r"repeatedly turning on and off",
            r"turns on/?off frequently",
            r"keeps restarting",
            r"repeated restarting",
            r"cannot stay powered on",
        ),
    ),
    # The charger attribution `docs/05` records lives in the manuals, not in
    # the article; the article is broader (cable and card too). Both halves
    # are matched so the guard can cite whichever the caller's model has.
    EvidenceRule(
        "GAP-RANDOM-RESTART",
        ("M2", "M3", "M6", "M7", "H:random-restarting", "H:know-your-dashcam-how-to"),
        (
            r"randomly restarting",
            r"reboot randomly",
            r"frequently reboot",
            r"only use rove",
            r"non-?rove usb car charger",
            r"insufficient power",
            r"type-?c to type-?c cable",
        ),
    ),
)

#: The Category H ids, in `docs/02` order. Used for the entry/guard split in
#: reporting and to keep the two lists from drifting apart.
GAP_ENTRY_IDS = (
    "GAP-REAR-CHANNEL",
    "GAP-GPS",
    "GAP-MOUNTING",
    "GAP-TIMELAPSE",
)
GAP_GUARD_IDS = (
    "GAP-BOOT-PROMPT",
    "GAP-HWK-NOT-DETECTED",
    "GAP-FROZEN-SCREEN",
    "GAP-ON-OFF-CYCLING",
    "GAP-RANDOM-RESTART",
)

#: Every Category H id, entries then guards, in `docs/02` order.
GAP_IDS = GAP_ENTRY_IDS + GAP_GUARD_IDS


# ---------------------------------------------------------------------------
# Step ontology linkage (docs/06 §3.6; eval/ontology.py)
# ---------------------------------------------------------------------------

#: Chunk text -> canonical step id, for the steps whose *procedure* is written
#: down in the corpus. This is deliberately small and literal: a chunk earns a
#: `step_id` only when it documents how to carry that step out, which is what
#: makes a citation possible under `docs/06` §4.5 item 4.
STEP_EVIDENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("STEP.DEVICE.ENABLE_WIFI_ON_CAMERA", (r"emergency lock", r"wifi icon")),
    ("STEP.SETTINGS.SWITCH_WIFI_BAND_2_4", (r"wifi mode", r"5\s*ghz.{0,40}2\.4",)),
    ("STEP.PHONE.ACCEPT_NO_INTERNET_PROMPT",
     (r"keep trying wi-?fi", r"always connect", r"stay connected")),
    ("STEP.PHONE.FORGET_AND_REJOIN_NETWORK", (r"forget (this )?(wi-?fi|network)",)),
    ("STEP.PHONE.MOVE_CLOSER_TO_CAMERA", (r"10\s*met(er|re)s?", r"33\s*ft")),
    ("STEP.APP.RETRY_CONNECT_BUTTON", (r"retry connect",)),
    ("STEP.APP.REINSTALL", (r"re-?install", r"uninstall")),
    ("STEP.APP.CLEAR_CACHE", (r"clear .{0,20}cache",)),
    ("STEP.APP.CHECK_FIRMWARE_MENU", (r"firmware update.{0,40}menu", r"app menu")),
    ("STEP.CARD.FORMAT_IN_CAMERA",
     (r"format .{0,30}(in|on) (the )?camera", r"system settings\s*>\s*format")),
    ("STEP.DEVICE.RESTORE_DEFAULT_SETTINGS", (r"(restore|reset).{0,30}default settings",)),
    ("STEP.DEVICE.HARD_RESET_PINHOLE", (r"reset button", r"paper ?clip")),
    ("STEP.OBSERVE.PHOTO_MODE_SHUTTER_TEST", (r"shutter sound",)),
    ("STEP.OBSERVE.LISTEN_FOR_ANNOUNCEMENT",
     (r"every 30 seconds", r"voice guidance")),
    ("STEP.OBSERVE.TRY_DIFFERENT_PLAYER", (r"\bvlc\b", r"different media player")),
    ("STEP.SETTINGS.CHECK_LOOP_RECORDING", (r"loop recording",)),
    ("STEP.SETTINGS.CHECK_GSENSOR_SENSITIVITY", (r"g-?sensor setting",)),
    ("STEP.SETTINGS.CHECK_AUDIO_ENABLED", (r"record audio",)),
    ("STEP.SETTINGS.SET_DATE_TIME", (r"time zone", r"\bgmt\b")),
    ("STEP.PHYSICAL.CLEAN_LENS_AND_GLASS", (r"lens .{0,20}clean", r"clean .{0,20}lens")),
    ("STEP.POWER.TRY_DIFFERENT_CABLE", (r"different .{0,20}usb cable", r"another cable")),
    ("STEP.SETTINGS.ENABLE_PARKING_MODE", (r"parking (mode|monitor)",)),
)


# ---------------------------------------------------------------------------
# Destructive and firmware-version detection
# ---------------------------------------------------------------------------

#: `docs/06` §6.4 routes these through the destructive gate: cause, consent,
#: consequence stated aloud. The flag is on the chunk so the gate can fire
#: before the text is ever used to build a step.
_DESTRUCTIVE_RE = re.compile(
    r"\b(format(ting|ted|s)?\b"
    r"|erase[sd]?\b"
    r"|wipe[sd]?\b"
    r"|factory reset"
    r"|hard reset"
    r"|reset (it )?to the default"
    r"|restore .{0,20}default"
    r"|default settings"
    r"|delete all"
    r"|reset button)",
    re.I,
)

#: `docs/06` §4.6. Two shapes: a dotted version-looking token sitting near
#: firmware vocabulary, and the one real ROVE build string in the corpus
#: (`ROVE-R2-4K-06102017`, M1 p.51).
_FW_BUILD_RE = re.compile(r"ROVE[\s_-]*R\d[\s_-]*4K[\s_-]*\d{6,8}", re.I)
_FW_VOCAB_RE = re.compile(r"firmware|\bbuild\b|\bversion\b", re.I)
_DOTTED_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
#: Units that make a dotted number a measurement rather than a version. Kept
#: tight on purpose: a false redaction costs a fact, a missed one costs a
#: spoken firmware version, and §4.6 is unambiguous about which is worse.
_UNIT_AFTER_RE = re.compile(
    r"\s*(ghz|mhz|khz|hz|gb|tb|mb|kb|mbps|mb/s|v\b|volt|%|mm|cm|m\b|met(er|re)"
    r"|inch|in\b|\"|'|ft|feet|a\b|amp|mah|wh|k\b|fps|x\b|°|deg|sec|second|min"
    r"|hour|oz|ounce|lb|pound|gram|kg|g\b|million|billion)",
    re.I,
)
#: How far from a dotted number the firmware vocabulary has to be for the
#: number to be treated as a version (`docs/06` §4.6 "near firmware
#: vocabulary").
_FW_PROXIMITY = 80

REDACTION = "[firmware version redacted]"


def redact_firmware_versions(text: str) -> tuple[str, list[str]]:
    """Strip version-shaped tokens out of chunk text.

    `docs/06` §4.6: "no retrieval path, prompt, or template may emit a version
    string". The corpus contains exactly one real build string and a scatter
    of version-shaped numbers near firmware vocabulary. Removing them at
    ingest is stronger than filtering at output, because a chunk that does not
    contain a version cannot leak one.

    Returns the cleaned text and the list of what was removed, so the registry
    can show that something was taken out rather than quietly losing it.
    """
    removed: list[str] = []

    def _drop_build(match: re.Match[str]) -> str:
        removed.append(match.group(0))
        return REDACTION

    cleaned = _FW_BUILD_RE.sub(_drop_build, text)

    out: list[str] = []
    cursor = 0
    for match in _DOTTED_RE.finditer(cleaned):
        start, end = match.span()
        if _UNIT_AFTER_RE.match(cleaned, end):
            continue
        window = cleaned[max(0, start - _FW_PROXIMITY) : end + _FW_PROXIMITY]
        if not _FW_VOCAB_RE.search(window):
            continue
        out.append(cleaned[cursor:start])
        out.append(REDACTION)
        removed.append(match.group(0))
        cursor = end
    out.append(cleaned[cursor:])
    return "".join(out), removed


def contains_firmware_version(text: str) -> list[str]:
    """The validator's side of `redact_firmware_versions`. Empty list is a pass."""
    _, removed = redact_firmware_versions(text)
    return removed


# ---------------------------------------------------------------------------
# The chunk record
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """One row of `data/processed/chunks.jsonl`. `docs/06` §4.3, in order."""

    chunk_id: str
    text: str
    doc_code: str
    source_path: str
    source_url: str | None
    retrieval_date: str
    tier: int
    provenance: str
    attested_by: str | None
    page_range: str | None
    section: str
    section_path: list[str]
    context_header: str
    overlap_sentence: str

    model_applicability: list[str]
    cross_model: bool
    hw_revision_specific: bool
    firmware_applicability: dict[str, str]

    category: str
    categories: list[str]
    taxonomy_ids: list[str]
    step_ids: list[str]

    verification_status: str
    speakable: bool
    speakable_scope: str
    speakable_reason: str
    destructive: bool
    safety_critical: bool
    expectation_gap: bool

    token_estimate: int
    redactions: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """Token-equivalent estimate. ~1.3 tokens per whitespace word for English
    prose; good enough to hold a budget to, and it needs no tokenizer."""
    words = len(text.split())
    return max(1, round(words * 1.3))


#: `docs/02`'s own order, used only to break ties deterministically.
CATEGORY_ORDER = ("WIFI", "FW", "APP", "REC", "SD", "PWR", "VID")


def categories_for(taxonomy_ids: list[str], gap_ids: list[str]) -> list[str]:
    """Every category a chunk carries evidence for, in `docs/02` order."""
    present = {
        t.split("-")[0] for t in taxonomy_ids if t.split("-")[0] in CATEGORY_OF_PREFIX
    }
    out = [c for c in CATEGORY_ORDER if c in present]
    if gap_ids:
        out.append("GAP")
    return out


def category_for(taxonomy_ids: list[str], gap_ids: list[str]) -> str:
    """The chunk's primary category (`docs/06` §4.3: the `category_filter` key).

    A Help Center article legitimately covers several categories at once, so
    the primary one is the category most of its evidence belongs to, with
    `docs/02`'s own ordering as the tie-break. The full set is kept in
    `categories` -- `docs/06` §4.6 unions the category filter with
    cross-cutting material anyway, so nothing is lost by naming one.
    """
    counts: dict[str, int] = {}
    for taxonomy_id in taxonomy_ids:
        prefix = taxonomy_id.split("-")[0]
        if prefix in CATEGORY_OF_PREFIX:
            counts[prefix] = counts.get(prefix, 0) + 1
    if counts:
        best = max(counts.values())
        for category in CATEGORY_ORDER:
            if counts.get(category) == best:
                return category
    if gap_ids:
        return "GAP"
    return "NONE"


def status_for(taxonomy_ids: list[str]) -> str:
    """Strongest status among the entries a chunk is evidence for.

    A chunk backing no Step 1b entry is UNVERIFIED: not wrong, unevidenced --
    the distinction `docs/05` draws in "How to read the outcomes" -- and
    `docs/06` §4.5 keeps it out of the speakable store either way.
    """
    if not taxonomy_ids:
        return UNVERIFIED
    return min(
        (TAXONOMY_STATUS[t] for t in taxonomy_ids if t in TAXONOMY_STATUS),
        key=lambda s: STATUS_RANK[s],
        default=UNVERIFIED,
    )


def build_metadata(
    *,
    source: Source,
    text: str,
    section_path: list[str],
    page_range: str | None,
    chunk_id: str,
    context_header: str,
    overlap_sentence: str,
) -> Chunk:
    """Apply every rule in this module to one span of text."""
    joined_sections = " > ".join(section_path)
    haystack = f"{joined_sections}\n{text}"

    taxonomy_ids = sorted(
        {
            rule.taxonomy_id
            for rule in EVIDENCE
            if rule.matches(source.doc_code, haystack, joined_sections)
        }
    )
    # Category H matches through the same `EvidenceRule` machinery as A-G,
    # and since Milestone 5.2 it counts towards the chunk's status the same
    # way. Before 5.2 these ids were bare keywords that deliberately did
    # *not* affect `verification_status`, because `docs/02` had no entry to
    # hang a status on; it does now, so a chunk that grounds GAP-MOUNTING is
    # as speakable as one that grounds SD-01, and for the same reason.
    gap_ids = sorted(
        {
            rule.taxonomy_id
            for rule in GAP_EVIDENCE
            if rule.matches(source.doc_code, haystack, joined_sections)
        }
    )

    if source.models:
        models = list(source.models)
        cross_model = False
    else:
        models, cross_model = models_named_in(haystack)

    hw_revision_specific = source.hw_revision_specific or bool(
        _MINI_USB_RE.search(haystack)
    )

    all_ids = taxonomy_ids + gap_ids
    status = status_for(all_ids)
    has_source = bool(source.source_url) or source.provenance == (
        PROVENANCE_OPERATOR_ATTESTED
    )

    if status not in SPEAKABLE_STATUSES:
        speakable = False
        reason = (
            f"verification_status={status} (docs/06 §4.5 item 3)"
            if all_ids
            else "no docs/05 Step 1b entry maps to this chunk"
        )
    elif not has_source:
        speakable = False
        reason = "no source URL and no operator attestation (docs/04 item 5)"
    else:
        speakable = True
        reason = (
            f"Tier 1, {status}, "
            + (
                "operator_attested -- prototype only (docs/06 §4.4)"
                if source.provenance == PROVENANCE_OPERATOR_ATTESTED
                else "crawler-captured source URL"
            )
        )

    step_ids = sorted(
        {
            step_id
            for step_id, patterns in STEP_EVIDENCE
            if any(re.search(p, haystack, re.I) for p in patterns)
        }
    )

    return Chunk(
        chunk_id=chunk_id,
        text=text,
        doc_code=source.doc_code,
        source_path=source.path,
        source_url=source.source_url,
        retrieval_date=source.retrieval_date,
        tier=source.tier,
        provenance=source.provenance,
        attested_by=(
            ATTESTED_BY
            if source.provenance == PROVENANCE_OPERATOR_ATTESTED
            else None
        ),
        page_range=page_range,
        section=section_path[-1] if section_path else "",
        section_path=list(section_path),
        context_header=context_header,
        overlap_sentence=overlap_sentence,
        model_applicability=models,
        cross_model=cross_model,
        hw_revision_specific=hw_revision_specific,
        firmware_applicability=dict(FIRMWARE_APPLICABILITY),
        category=category_for(taxonomy_ids, gap_ids),
        categories=categories_for(taxonomy_ids, gap_ids),
        taxonomy_ids=all_ids,
        step_ids=step_ids,
        verification_status=status,
        speakable=speakable,
        speakable_scope=source.speakable_scope,
        speakable_reason=reason,
        destructive=bool(_DESTRUCTIVE_RE.search(text)),
        safety_critical=bool(set(all_ids) & SAFETY_CRITICAL_IDS),
        expectation_gap=bool(set(all_ids) & EXPECTATION_GAP_IDS),
        token_estimate=estimate_tokens(text),
    )
