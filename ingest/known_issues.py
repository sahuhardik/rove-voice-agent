"""The known-issue watch -- `python -m ingest.known_issues`.

**There is no vendor known-issue or release-note feed.** `docs/06` §9.3 item 1
records that as an open decision for Hardik, `docs/05` calls it "the single
biggest remaining gap", and `FW-03` stays escalation-bound until one exists.
This module does not invent one and must never be read as one.

What it is instead: a watch over the three vendor-side surfaces that *do*
exist publicly, which change when something changes at Rove.

    1. help_center_index   the Gorgias Troubleshoot index. A new article is
                           the closest public thing to Rove acknowledging a
                           problem; an edited article is the closest thing to
                           Rove revising its advice.
    2. firmware_downloads  the official firmware/downloads and update pages.
                           Watched for new or re-versioned download links and
                           for changes to the update procedure text.
    3. app_changelog       the ROVE Dash Cam app release notes, Android
                           (com.rovedashcam.android) and iOS (id1606959035).
                           The only surface where the vendor writes "fixed"
                           next to a dated version.

Every record this module emits is a **candidate**, **Tier 2**, and
**`speakable=False`**. That is enforced in code
(`assert_monitor_output_is_tier2`), not just documented: a Help Center article
appearing in an index is Rove publishing a troubleshooting page, which is not
the same act as Rove declaring a known defect, and app release notes are
marketing copy about a phone app, not a camera firmware bulletin. Promotion to
Tier 1 is a separate, human act -- `confirm_with_tier1()` -- which this module
never calls and the CLI gives no way to reach.

The monitor also never writes into the speakable corpus. Its two outputs live
in `data/known-issues/`, not `data/processed/`, and no path it writes is
registered in `ingest.metadata.SOURCES`.

    data/known-issues/snapshot.json     last fetched state, per signal
    data/known-issues/candidates.json   the candidate records, keyed by id

Stdlib only -- `urllib.request` for the runtime fetch (`requests` is not
vendored in this repo's venv; see `ingest/test_known_issues.py`, which runs
the whole pipeline offline against the fixtures in `data/raw/`).

    python -m ingest.known_issues --check            fetch live, diff, write
    python -m ingest.known_issues --check --dry-run  fetch live, diff, print
    python -m ingest.known_issues --offline          diff the saved fixtures
    python -m ingest.known_issues --report           print the current store
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import metadata as md

REPO_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = REPO_ROOT / "data" / "known-issues"
SNAPSHOT_NAME = "snapshot.json"
CANDIDATES_NAME = "candidates.json"

#: Bumped when the record schema below changes shape. A snapshot written by an
#: older version is discarded rather than mis-diffed.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# The tier rule, stated once and enforced
# ---------------------------------------------------------------------------

#: `docs/04` "How to use this file": Tier 1 is ground truth and the only tier
#: that may be spoken as a verified fix. Nothing this monitor produces is
#: Tier 1. A candidate is Tier 2 -- discovery -- in exactly the sense `docs/04`
#: Tier 2 already means: use it for symptom language, frequency and eval
#: scenarios, never as a fix on its own.
TIER_CANDIDATE = 2
TIER_GROUND_TRUTH = 1

STATUS_CANDIDATE = "candidate"
STATUS_CHANGED = "changed"
STATUS_DISAPPEARED = "disappeared"
#: Reachable only through `confirm_with_tier1()`, which is a human action.
STATUS_CONFIRMED = "confirmed"

CHANGE_NEW = "new"
CHANGE_CHANGED = "changed"
CHANGE_DISAPPEARED = "disappeared"
CHANGE_UNCHANGED = "unchanged"

#: Models are recorded only when the source text names them. `docs/06` §4.3's
#: "explicit, never 'all'" rule, applied one notch harder than the chunker
#: applies it: the chunker falls back to the whole documented line and flags
#: `cross_model`, which is right for retrieval. For a known-issue record the
#: honest fallback is *no* model list at all, because "Rove published an
#: article that names no model" is not evidence that every model is affected.
MODEL_SCOPE_NAMED = "named_in_source"
MODEL_SCOPE_UNSTATED = "unstated_in_source"


class Tier1Violation(RuntimeError):
    """Raised when something tries to pass monitor output off as Tier 1."""


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

SIGNAL_HELP_CENTER = "help_center_index"
SIGNAL_FIRMWARE = "firmware_downloads"
SIGNAL_APP = "app_changelog"

SIGNAL_IDS = (SIGNAL_HELP_CENTER, SIGNAL_FIRMWARE, SIGNAL_APP)

#: Whether an item vanishing from a signal means anything. For the Help Center
#: index and the download pages it does -- an article pulled or a download link
#: removed is a real event. For the app changelog it does not: the stores show
#: the current release only, so yesterday's version "disappearing" is the
#: normal shape of the surface, not a withdrawal.
TRACKS_DISAPPEARANCE = {
    SIGNAL_HELP_CENTER: True,
    SIGNAL_FIRMWARE: True,
    SIGNAL_APP: False,
}

SIGNAL_NOTE = {
    SIGNAL_HELP_CENTER: (
        "Candidate from the Rove Help Center Troubleshoot index. Rove "
        "publishing or editing a troubleshooting article is not Rove "
        "declaring a known defect; it is the closest public proxy that "
        "exists. Tier 2 until a Tier 1 source confirms it."
    ),
    SIGNAL_FIRMWARE: (
        "Candidate from an official Rove firmware/download page. A new or "
        "re-versioned download link, or a change to the update procedure "
        "text. The page carries no release notes and no version numbers, so "
        "this signal can say that something changed and not what it fixes. "
        "Tier 2 until a Tier 1 source confirms it."
    ),
    SIGNAL_APP: (
        "Candidate from a ROVE Dash Cam app store listing's release notes. "
        "These describe the phone app, not camera firmware, and are written "
        "as store copy. Tier 2 until a Tier 1 source confirms it."
    ),
}


@dataclass(frozen=True)
class WatchedPage:
    """One URL inside a signal, with the saved fixture that stands in for it."""

    key: str
    url: str
    fixture: str | None


HELP_CENTER_BASE = "https://hc1.gorgias.help"
HELP_CENTER_INDEX = WatchedPage(
    key="troubleshoot-index",
    #: `docs/04` 1.3, and the URL recorded on `H:troubleshoot-index`.
    url=f"{HELP_CENTER_BASE}/en-US/articles/troubleshoot-128437",
    fixture="data/raw/help-center/troubleshoot-index.html",
)

#: The official pages, taken from the registry rather than retyped, so the
#: watch and the corpus can never drift to different URLs for the same page.
#: `O1` is Firmware Update & Downloads and `O3` the R2-4K upgrade walk-through
#: -- the two firmware pages. `O2` (connect-to-phone) is watched with them
#: because it is the third saved official page and is where the per-model Wi-Fi
#: behaviour is published; a silent edit there moves ground under WIFI-01..05.
_OFFICIAL_FIXTURES = {
    "O1": "data/raw/official/firmware-update-downloads.html",
    "O2": "data/raw/official/connect-rove-to-phone.html",
    "O3": "data/raw/official/update-firmware-r2-4k.html",
}

OFFICIAL_PAGES: tuple[WatchedPage, ...] = tuple(
    WatchedPage(
        key=Path(fixture).stem,
        url=md.SOURCES[code].source_url or "",
        fixture=fixture,
    )
    for code, fixture in _OFFICIAL_FIXTURES.items()
)

#: `docs/04` 2.2 names both store listings. The iOS endpoint is the public
#: iTunes lookup API, which returns `version`, `currentVersionReleaseDate` and
#: `releaseNotes` as JSON. Google Play has no equivalent, which is why the
#: Android arm is a best-effort HTML parse that reports its own failure --
#: see `parse_android_listing`.
APP_IOS_ID = "1606959035"
APP_ANDROID_ID = "com.rovedashcam.android"
APP_IOS_PAGE = WatchedPage(
    key="ios",
    url=f"https://itunes.apple.com/lookup?id={APP_IOS_ID}&country=us&entity=software",
    fixture=None,
)
APP_ANDROID_PAGE = WatchedPage(
    key="android",
    url=(
        "https://play.google.com/store/apps/details"
        f"?id={APP_ANDROID_ID}&hl=en&gl=US"
    ),
    fixture=None,
)


# ---------------------------------------------------------------------------
# The known-issue record
# ---------------------------------------------------------------------------


@dataclass
class KnownIssueRecord:
    """One candidate known issue.

    `tier` and `speakable` are not parameters of the monitor's judgement. A
    record this module creates is Tier 2 and unspeakable, always; the only
    thing that moves it is `confirm_with_tier1()`, which needs a named human
    and a Tier 1 `doc_code` from `ingest.metadata.SOURCES`.
    """

    issue_id: str
    title: str
    symptom_text: str
    affected_models: list[str]
    model_scope: str
    source_signal: str
    source_url: str
    first_seen: str
    last_seen: str
    last_checked: str
    last_changed: str
    status: str
    change_kind: str
    fingerprint: str
    tier: int = TIER_CANDIDATE
    speakable: bool = False
    #: Set only by `confirm_with_tier1()`. `None` for everything the monitor
    #: writes, which is everything the monitor writes.
    tier1_confirmation: dict | None = None
    #: The `doc_code` of the Tier 1 document this candidate's URL already
    #: corresponds to, when there is one. Having the body on disk is not
    #: confirmation that it describes a known issue -- it only means a human
    #: checking this candidate does not have to go and fetch it.
    corpus_doc_code: str | None = None
    #: Lines added or removed since the last snapshot, for a `changed` record.
    evidence: list[str] = field(default_factory=list)
    note: str = ""
    #: `live` or `fixture`. A record diffed out of the saved fixtures is not a
    #: statement about the web today and must not be reported as one.
    fetch_mode: str = "live"

    def to_json_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "symptom_text": self.symptom_text,
            "affected_models": list(self.affected_models),
            "model_scope": self.model_scope,
            "source_signal": self.source_signal,
            "source_url": self.source_url,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_checked": self.last_checked,
            "last_changed": self.last_changed,
            "status": self.status,
            "change_kind": self.change_kind,
            "fingerprint": self.fingerprint,
            "tier": self.tier,
            "speakable": self.speakable,
            "tier1_confirmation": self.tier1_confirmation,
            "corpus_doc_code": self.corpus_doc_code,
            "evidence": list(self.evidence),
            "note": self.note,
            "fetch_mode": self.fetch_mode,
        }

    @classmethod
    def from_json_dict(cls, raw: dict) -> "KnownIssueRecord":
        return cls(
            issue_id=raw["issue_id"],
            title=raw["title"],
            symptom_text=raw["symptom_text"],
            affected_models=list(raw.get("affected_models", [])),
            model_scope=raw.get("model_scope", MODEL_SCOPE_UNSTATED),
            source_signal=raw["source_signal"],
            source_url=raw["source_url"],
            first_seen=raw["first_seen"],
            last_seen=raw.get("last_seen", raw["first_seen"]),
            last_checked=raw["last_checked"],
            last_changed=raw.get("last_changed", raw["first_seen"]),
            status=raw["status"],
            change_kind=raw.get("change_kind", CHANGE_UNCHANGED),
            fingerprint=raw.get("fingerprint", ""),
            tier=raw.get("tier", TIER_CANDIDATE),
            speakable=raw.get("speakable", False),
            tier1_confirmation=raw.get("tier1_confirmation"),
            corpus_doc_code=raw.get("corpus_doc_code"),
            evidence=list(raw.get("evidence", [])),
            note=raw.get("note", ""),
            fetch_mode=raw.get("fetch_mode", "live"),
        )


def assert_monitor_output_is_tier2(records: list[KnownIssueRecord]) -> None:
    """The gate the monitor runs its own output through before writing it.

    Three ways this could go wrong silently -- a record claiming Tier 1, a
    record marked speakable, or a record carrying a confirmation nobody made --
    and all three are the same mistake: the watch asserting something it has
    no standing to assert.
    """
    for record in records:
        where = f"{record.issue_id} ({record.source_signal})"
        if record.tier != TIER_CANDIDATE:
            raise Tier1Violation(
                f"{where}: tier={record.tier}; the watch may only emit "
                f"Tier {TIER_CANDIDATE} candidates (docs/04 'How to use this file')"
            )
        if record.speakable:
            raise Tier1Violation(
                f"{where}: speakable=True; no candidate is speakable "
                "(docs/06 §4.5 -- Tier 1 only)"
            )
        if record.tier1_confirmation is not None:
            raise Tier1Violation(
                f"{where}: carries a tier1_confirmation. The monitor cannot "
                "confirm anything; confirm_with_tier1() is a human action"
            )
        if record.status == STATUS_CONFIRMED:
            raise Tier1Violation(
                f"{where}: status={STATUS_CONFIRMED} without a confirmation record"
            )


def confirm_with_tier1(
    record: KnownIssueRecord,
    *,
    doc_code: str,
    confirmed_by: str,
    confirmed_on: str,
    note: str = "",
) -> KnownIssueRecord:
    """Promote a candidate, as a human act with a named human on it.

    Not called by the monitor and not reachable from the CLI. It exists so the
    schema has a defined shape for the day a Tier 1 source -- a manual, an
    official page, a Help Center body already in the corpus, or the vendor feed
    that does not exist yet -- actually says the thing the candidate suggests.

    Promotion still does not make the record speakable. Speakability is the
    chunk-level gate in `docs/06` §4.5 and belongs to the ingest, not here; a
    confirmed known issue is a fact about the world that a *chunk* may then be
    cleared to say.
    """
    if doc_code not in md.SOURCES:
        raise ValueError(
            f"{doc_code!r} is not in the Tier 1 registry; a confirmation must "
            "name a document that exists (docs/04 collection plan item 5)"
        )
    if not confirmed_by.strip():
        raise ValueError("a confirmation needs a named human")
    source = md.SOURCES[doc_code]
    if source.tier != TIER_GROUND_TRUTH:
        raise Tier1Violation(f"{doc_code} is Tier {source.tier}, not Tier 1")
    record.tier1_confirmation = {
        "doc_code": doc_code,
        "source_url": source.source_url,
        "confirmed_by": confirmed_by,
        "confirmed_on": confirmed_on,
        "note": note,
    }
    record.status = STATUS_CONFIRMED
    return record


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

USER_AGENT = "rove-known-issue-watch/1.0 (support tooling; contact via Rove support)"
FETCH_TIMEOUT = 20
#: A listing page is a few hundred KB. Anything past this is not the page we
#: think we are reading, and reading it is somebody else's bandwidth.
MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    body: str = ""
    status: int | None = None
    error: str = ""


class UrlFetcher:
    """Runtime fetcher. Stdlib `urllib.request`; `requests` is not vendored."""

    mode = "live"

    def get(self, url: str) -> FetchResult:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en"}
        )
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
                raw = response.read(MAX_BYTES)
                charset = response.headers.get_content_charset() or "utf-8"
                return FetchResult(
                    url=url,
                    ok=True,
                    body=raw.decode(charset, errors="replace"),
                    status=getattr(response, "status", 200),
                )
        except urllib.error.HTTPError as exc:  # pragma: no cover - needs network
            return FetchResult(url=url, ok=False, status=exc.code, error=str(exc))
        except Exception as exc:  # pragma: no cover - needs network
            return FetchResult(url=url, ok=False, error=f"{type(exc).__name__}: {exc}")


class FixtureFetcher:
    """Offline fetcher: serves the saved pages in `data/raw/`.

    Used by `--offline` and by every test. A URL with no fixture behind it --
    the two app stores, which were never crawled -- returns a failed fetch,
    which is the truth: this session has no web access and the watch has no
    saved copy of those listings.
    """

    mode = "fixture"

    def __init__(self, mapping: dict[str, Path]):
        self._mapping = mapping

    def get(self, url: str) -> FetchResult:
        path = self._mapping.get(url)
        if path is None:
            return FetchResult(
                url=url, ok=False, error="no fixture saved for this URL (offline run)"
            )
        if not path.exists():
            return FetchResult(url=url, ok=False, error=f"fixture missing: {path}")
        return FetchResult(
            url=url, ok=True, body=path.read_text(encoding="utf-8", errors="replace")
        )


def default_fixture_fetcher(root: Path | None = None) -> FixtureFetcher:
    base = root or REPO_ROOT
    mapping: dict[str, Path] = {}
    for page in (HELP_CENTER_INDEX,) + OFFICIAL_PAGES:
        if page.fixture:
            mapping[page.url] = base / page.fixture
    return FixtureFetcher(mapping)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_MAIN = re.compile(r"<main\b.*?</main>", re.S | re.I)
_WS = re.compile(r"[ \t ]+")

#: A Gorgias article URL ends in `-<numeric id>`. The id is the only part of
#: the URL that is stable: the slug carries percent-encoded smart quotes and
#: has been rewritten at least once already (`docs/04` 1.3 `TO CHECK`).
_ARTICLE_ID = re.compile(r"-(\d+)/?$")

#: `<a aria-label="..." ... href="/en-US/...-123">` wrapping an article card.
#: Keyed on `aria-label` and `href`, never on the class names, which are
#: emotion hashes (`css-13g87sg`) and change on any CSS edit.
_ARTICLE_ANCHOR = re.compile(
    r"<a\b(?P<attrs>[^>]*?)>(?P<inner>.*?)</a>", re.S | re.I
)
_ARIA_LABEL = re.compile(r'aria-label="([^"]*)"', re.I)
_HREF = re.compile(r'href="([^"]*)"', re.I)
_H4 = re.compile(r"<h4\b[^>]*>(.*?)</h4>", re.S | re.I)
_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)


def strip_html(fragment: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", fragment)
    text = _TAG.sub(" ", text)
    text = html_mod.unescape(text)
    text = _WS.sub(" ", text)
    return text.strip()


def main_text(raw_html: str, limit: int = 20000) -> str:
    """Normalised visible text of a page's main region, for fingerprinting.

    Line-per-block, whitespace-collapsed, truncated. Not a chunker: this text
    is never ingested, it is only hashed and diffed.
    """
    body = _SCRIPT_STYLE.sub(" ", raw_html)
    match = _MAIN.search(body)
    if match:
        body = match.group(0)
    body = re.sub(r"<(?:/?)(?:p|div|li|tr|h[1-6]|br|section)\b[^>]*>", "\n", body)
    body = _TAG.sub(" ", body)
    body = html_mod.unescape(body)
    lines = [_WS.sub(" ", line).strip() for line in body.split("\n")]
    lines = [line for line in lines if line]
    # Shopify/Gorgias ship the same nav and footer strings many times over;
    # consecutive repeats would make every diff noisy.
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)[:limit]


@dataclass(frozen=True)
class SignalItem:
    """One watched thing inside a signal, with the fingerprint that moves.

    Three text fields, because they answer three different questions and
    conflating them is how a watch starts lying.

        `text`        what is hashed and diffed. May be a whole page.
        `summary`     what goes in the record's `symptom_text`. Short.
        `model_text`  what model names are read out of. Prose only, never a
                      URL: `..._R2-4K_DUAL_PRO.pdf` contains the literal
                      substrings "R2-4K" and "R2-4K DUAL" and would otherwise
                      pull three models in that the source never named.
    """

    key: str
    title: str
    text: str
    url: str
    fingerprint: str
    summary: str = ""
    model_text: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            object.__setattr__(self, "summary", self.text[:600])
        if not self.model_text:
            object.__setattr__(self, "model_text", f"{self.title}\n{self.summary}")


def _fingerprint(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:16]


def article_id(url: str) -> str | None:
    match = _ARTICLE_ID.search(url.split("?")[0])
    return match.group(1) if match else None


def _corpus_doc_codes_by_article_id() -> dict[str, str]:
    """Which Help Center article ids already have a Tier 1 body on disk."""
    mapping: dict[str, str] = {}
    for code, source in md.SOURCES.items():
        if not code.startswith("H:") or not source.source_url:
            continue
        found = article_id(source.source_url)
        if found:
            mapping[found] = code
    return mapping


def parse_help_center_index(raw_html: str) -> list[SignalItem]:
    """Article cards on the Gorgias Troubleshoot index.

    Each card is `<a aria-label=TITLE href=/en-US/slug-ID><h4>TITLE</h4>
    <p>PREVIEW</p></a>`. The preview is the symptom text: it is Rove's own
    one-paragraph statement of what goes wrong, which is exactly the field a
    known-issue record wants and exactly the field that changes when Rove
    rewrites its advice.
    """
    items: dict[str, SignalItem] = {}
    cleaned = _SCRIPT_STYLE.sub(" ", raw_html)
    for match in _ARTICLE_ANCHOR.finditer(cleaned):
        attrs, inner = match.group("attrs"), match.group("inner")
        href_match = _HREF.search(attrs)
        if not href_match:
            continue
        href = html_mod.unescape(href_match.group(1))
        # The index links to itself and to category pages under /articles/;
        # those are not issues.
        if "/articles/" in href:
            continue
        found_id = article_id(href)
        if not found_id:
            continue
        aria = _ARIA_LABEL.search(attrs)
        h4 = _H4.search(inner)
        title = strip_html(h4.group(1)) if h4 else (
            html_mod.unescape(aria.group(1)).strip() if aria else ""
        )
        if not title:
            continue
        preview_match = _P.search(inner)
        preview = strip_html(preview_match.group(1)) if preview_match else ""
        url = href if href.startswith("http") else HELP_CENTER_BASE + href
        items[found_id] = SignalItem(
            key=f"article:{found_id}",
            title=title,
            text=preview,
            summary=preview,
            model_text=f"{title}\n{preview}",
            url=url,
            fingerprint=_fingerprint(title, preview),
            extra={"article_id": found_id},
        )
    return list(items.values())


_DOWNLOAD_HREF = re.compile(
    r"\.(?:zip|rar|7z|bin|img|pdf|tar\.gz)(?:$|\?)", re.I
)


def parse_official_page(page: WatchedPage, raw_html: str) -> list[SignalItem]:
    """Two kinds of item per official page.

    `page:` the normalised main text, so a change to the update procedure is
    caught even when no link changes. `link:` one per downloadable artifact,
    keyed on the URL *without* its `?v=` cache-buster so that a re-upload of
    the same file reads as a change to a known link rather than as a new link
    plus a disappearance.
    """
    text = main_text(raw_html)
    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", raw_html, re.S | re.I)
    page_title = strip_html(title_match.group(1)) if title_match else page.key
    items = [
        SignalItem(
            key=f"page:{page.key}",
            title=page_title,
            text=text,
            # The whole page is what gets diffed; what goes in the record is
            # the lead, and on a change the diffed lines go in `evidence`.
            summary=" ".join(text.split("\n")[:4])[:400],
            model_text=text,
            url=page.url,
            fingerprint=_fingerprint(text),
            extra={"kind": "page_text"},
        )
    ]

    body = _SCRIPT_STYLE.sub(" ", raw_html)
    region = _MAIN.search(body)
    if region:
        body = region.group(0)
    seen: set[str] = set()
    for match in _ARTICLE_ANCHOR.finditer(body):
        href_match = _HREF.search(match.group("attrs"))
        if not href_match:
            continue
        href = html_mod.unescape(href_match.group(1))
        if not _DOWNLOAD_HREF.search(href):
            continue
        stable = href.split("?")[0]
        if stable in seen:
            continue
        seen.add(stable)
        label = strip_html(match.group("inner")) or Path(stable).name
        items.append(
            SignalItem(
                key=f"link:{stable}",
                title=f"{label} ({Path(stable).name})",
                text=f"{label}\n{href}",
                summary=f"Download link published on {page.key}: {label}",
                # The anchor label only. The URL is excluded on purpose -- see
                # SignalItem.model_text.
                model_text=label,
                url=href,
                fingerprint=_fingerprint(label, href),
                extra={"kind": "download_link", "page": page.key},
            )
        )
    return items


def parse_ios_lookup(body: str) -> list[SignalItem]:
    """The public iTunes lookup JSON for the ROVE Dash Cam app.

    One item per released version, so a release that is superseded keeps its
    record and its `first_seen` instead of being re-created.
    """
    payload = json.loads(body)
    results = payload.get("results") or []
    items: list[SignalItem] = []
    for result in results:
        version = str(result.get("version") or "").strip()
        if not version:
            continue
        notes = (result.get("releaseNotes") or "").strip()
        released = (result.get("currentVersionReleaseDate") or "")[:10]
        url = result.get("trackViewUrl") or APP_IOS_PAGE.url
        items.append(
            SignalItem(
                key=f"ios:{version}",
                title=f"ROVE Dash Cam (iOS) {version}",
                text=notes,
                summary=notes[:600],
                model_text=notes,
                url=url,
                fingerprint=_fingerprint(version, notes, released),
                extra={
                    "platform": "ios",
                    "version": version,
                    "released_on": released,
                },
            )
        )
    return items


#: "What's new" as Google Play renders it, with the apostrophe entity-escaped
#: or not. Both spellings have been served.
_PLAY_WHATS_NEW = tuple(
    re.compile(rf"What{apostrophe}s new\s*</h2>(.*?)</div>", re.S | re.I)
    for apostrophe in ("&#39;", "'", "’", "&rsquo;")
)
#: A version string is only believed when it sits within a kilobyte of the
#: package id in the data payload. A bare `x.y.z` regex over a Play page
#: matches library versions, experiment ids and timestamps.
_PLAY_VERSION_NEAR = re.compile(r'"(\d{1,3}(?:\.\d{1,4}){1,3})"')
_VERSION_WINDOW = 1200


def _android_version(body: str) -> str:
    for match in re.finditer(re.escape(APP_ANDROID_ID), body):
        window = body[match.end() : match.end() + _VERSION_WINDOW]
        found = _PLAY_VERSION_NEAR.search(window)
        if found:
            return found.group(1)
    return ""


def parse_android_listing(body: str) -> list[SignalItem]:
    """Best-effort parse of the Google Play listing's "What's new" block.

    Google Play publishes no API for this and renders the listing out of
    obfuscated `AF_initDataCallback` payloads whose shape changes without
    notice. This parser reads the visible "What's new" heading, and treats the
    version as optional metadata rather than as the key -- a wrong version is
    worse than no version. When neither the notes nor a version can be found
    it returns `[]`, which the caller turns into a `parse_failed` signal
    status, so the watch reports that it has gone blind on Android rather than
    reporting silence as "nothing changed".

    This is the weakest of the three signals and `docs/04` says so.
    """
    notes = ""
    for pattern in _PLAY_WHATS_NEW:
        match = pattern.search(body)
        if match:
            notes = strip_html(match.group(1))
            if notes:
                break
    version = _android_version(body)
    if not notes and not version:
        return []
    # Keyed on the notes when there is no trustworthy version, so that one
    # release is one record either way.
    key_part = version or _fingerprint(notes)
    return [
        SignalItem(
            key=f"android:{key_part}",
            title=f"ROVE Dash Cam (Android) {version or 'release notes'}",
            text=notes,
            summary=notes[:600],
            model_text=notes,
            url=APP_ANDROID_PAGE.url,
            fingerprint=_fingerprint(version, notes),
            extra={
                "platform": "android",
                "version": version,
                "version_parsed": bool(version),
            },
        )
    ]


# ---------------------------------------------------------------------------
# Collecting a signal
# ---------------------------------------------------------------------------

SIGNAL_OK = "ok"
SIGNAL_FETCH_FAILED = "fetch_failed"
SIGNAL_PARSE_FAILED = "parse_failed"


@dataclass
class SignalReading:
    signal_id: str
    status: str
    items: list[SignalItem]
    urls: list[str]
    errors: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Every URL in the signal was fetched and parsed."""
        return self.status == SIGNAL_OK

    @property
    def may_expire(self) -> bool:
        """May a key missing from this reading be treated as withdrawn?

        Only on a clean read of a signal whose surface actually shows
        everything it has. A partial read must never expire: a 503 from one of
        three pages is not that page's links being taken down.
        """
        return self.clean and TRACKS_DISAPPEARANCE[self.signal_id]


def read_help_center(fetcher) -> SignalReading:
    result = fetcher.get(HELP_CENTER_INDEX.url)
    if not result.ok:
        return SignalReading(
            SIGNAL_HELP_CENTER, SIGNAL_FETCH_FAILED, [], [HELP_CENTER_INDEX.url],
            [f"{HELP_CENTER_INDEX.url}: {result.error}"],
        )
    items = parse_help_center_index(result.body)
    if not items:
        return SignalReading(
            SIGNAL_HELP_CENTER, SIGNAL_PARSE_FAILED, [], [HELP_CENTER_INDEX.url],
            ["index fetched but no article cards parsed; the markup moved"],
        )
    return SignalReading(SIGNAL_HELP_CENTER, SIGNAL_OK, items, [HELP_CENTER_INDEX.url])


def read_firmware(fetcher) -> SignalReading:
    items: list[SignalItem] = []
    errors: list[str] = []
    urls = [page.url for page in OFFICIAL_PAGES]
    for page in OFFICIAL_PAGES:
        result = fetcher.get(page.url)
        if not result.ok:
            errors.append(f"{page.url}: {result.error}")
            continue
        items.extend(parse_official_page(page, result.body))
    if not items:
        return SignalReading(SIGNAL_FIRMWARE, SIGNAL_FETCH_FAILED, [], urls, errors)
    if errors:
        # A partial read must not make the pages it could not reach look
        # withdrawn, so it is not `ok` and the differ will not expire anything.
        return SignalReading(SIGNAL_FIRMWARE, SIGNAL_FETCH_FAILED, items, urls, errors)
    return SignalReading(SIGNAL_FIRMWARE, SIGNAL_OK, items, urls)


def read_app_changelog(fetcher) -> SignalReading:
    items: list[SignalItem] = []
    errors: list[str] = []
    urls = [APP_IOS_PAGE.url, APP_ANDROID_PAGE.url]

    ios = fetcher.get(APP_IOS_PAGE.url)
    if ios.ok:
        try:
            parsed = parse_ios_lookup(ios.body)
        except (ValueError, TypeError) as exc:
            errors.append(f"{APP_IOS_PAGE.url}: lookup JSON unreadable: {exc}")
        else:
            if parsed:
                items.extend(parsed)
            else:
                errors.append(f"{APP_IOS_PAGE.url}: lookup returned no results")
    else:
        errors.append(f"{APP_IOS_PAGE.url}: {ios.error}")

    android = fetcher.get(APP_ANDROID_PAGE.url)
    if android.ok:
        parsed = parse_android_listing(android.body)
        if parsed:
            items.extend(parsed)
        else:
            errors.append(
                f"{APP_ANDROID_PAGE.url}: listing fetched but no version or "
                "'What's new' block found; Play markup moved"
            )
    else:
        errors.append(f"{APP_ANDROID_PAGE.url}: {android.error}")

    if not items:
        status = SIGNAL_FETCH_FAILED if not ios.ok and not android.ok else SIGNAL_PARSE_FAILED
        return SignalReading(SIGNAL_APP, status, [], urls, errors)
    if errors:
        return SignalReading(SIGNAL_APP, SIGNAL_PARSE_FAILED, items, urls, errors)
    return SignalReading(SIGNAL_APP, SIGNAL_OK, items, urls)


SIGNAL_READERS = {
    SIGNAL_HELP_CENTER: read_help_center,
    SIGNAL_FIRMWARE: read_firmware,
    SIGNAL_APP: read_app_changelog,
}


def read_all_signals(fetcher) -> dict[str, SignalReading]:
    return {sid: SIGNAL_READERS[sid](fetcher) for sid in SIGNAL_IDS}


# ---------------------------------------------------------------------------
# Snapshot and store
# ---------------------------------------------------------------------------


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _item_to_json(item: SignalItem) -> dict:
    return {
        "key": item.key,
        "title": item.title,
        "text": item.text,
        "summary": item.summary,
        "url": item.url,
        "fingerprint": item.fingerprint,
        "extra": item.extra,
    }


def _item_from_json(raw: dict) -> SignalItem:
    return SignalItem(
        key=raw["key"],
        title=raw.get("title", ""),
        text=raw.get("text", ""),
        summary=raw.get("summary", ""),
        url=raw.get("url", ""),
        fingerprint=raw.get("fingerprint", ""),
        extra=raw.get("extra", {}),
    )


def load_snapshot(store_dir: Path) -> dict:
    path = store_dir / SNAPSHOT_NAME
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "signals": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        # Diffing across a schema change invents changes that never happened.
        return {"schema_version": SCHEMA_VERSION, "signals": {}}
    return raw


def load_candidates(store_dir: Path) -> dict[str, KnownIssueRecord]:
    path = store_dir / CANDIDATES_NAME
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["issue_id"]: KnownIssueRecord.from_json_dict(entry)
        for entry in raw.get("candidates", [])
    }


def write_store(
    store_dir: Path,
    snapshot: dict,
    candidates: dict[str, KnownIssueRecord],
) -> None:
    assert_monitor_output_is_tier2(
        [r for r in candidates.values() if r.tier1_confirmation is None]
    )
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / SNAPSHOT_NAME).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "python -m ingest.known_issues",
        "tier": TIER_CANDIDATE,
        "no_vendor_feed": (
            "Rove publishes no known-issue or release-note feed. Every record "
            "here is a candidate inferred from a public surface that is not "
            "one (docs/06 §9.3 item 1). FW-03 stays escalation-bound."
        ),
        "speakable": False,
        "candidates": [
            record.to_json_dict()
            for record in sorted(candidates.values(), key=lambda r: r.issue_id)
        ],
    }
    (store_dir / CANDIDATES_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# The diff
# ---------------------------------------------------------------------------


def _issue_id(signal_id: str, key: str) -> str:
    prefix = {
        SIGNAL_HELP_CENTER: "KI-HC",
        SIGNAL_FIRMWARE: "KI-FW",
        SIGNAL_APP: "KI-APP",
    }[signal_id]
    kind, _, tail = key.partition(":")
    if kind == "link":
        # The CDN path is 40 characters of Shopify account id before anything
        # distinguishing; the filename is the part a human recognises. The
        # hash keeps the id unique when two paths share a filename.
        tail = f"{Path(tail).name}-{_fingerprint(key)[:8]}"
    elif kind in {"ios", "android"}:
        # The platform stays in the id. Both stores ship a version 6.2.0 and
        # they are two different releases of two different binaries.
        tail = f"{kind}-{tail}"
    elif kind in {"page", "article"}:
        tail = tail or kind
    slug = re.sub(r"[^A-Za-z0-9]+", "-", tail).strip("-").lower()
    if len(slug) > 64:
        slug = f"{slug[:56]}-{_fingerprint(key)[:8]}"
    return f"{prefix}-{slug}"


def _diff_lines(old: str, new: str, limit: int = 12) -> list[str]:
    """The added and removed lines, which is what a human needs to triage."""
    delta = difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=0
    )
    changed = [
        line for line in delta
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    ]
    if len(changed) > limit:
        changed = changed[:limit] + [f"... {len(changed) - limit} more changed lines"]
    return changed


#: Does the text mention any model at all? `md.models_named_in` cannot answer
#: this on its own: it returns `(ALL_MODELS, cross_model=True)` both for text
#: that names nothing and for text that names all six, and for a known-issue
#: record those are opposite facts. This precheck separates them.
_ANY_MODEL = re.compile(r"R2[\s_-]*4K|\bR3\b", re.I)


def _models_for(text: str) -> tuple[list[str], str]:
    """Which models does this text *name*, span-exclusively.

    Built on the shared vocabulary in `ingest.metadata` -- same patterns, same
    ordering, same mini-USB narrowing -- but with one rule the chunker does
    not need and a known-issue record cannot do without: **a match consumes
    its span**.

    `md.models_named_in` tries every pattern against the whole string, so
    "R2-4K DUAL PRO" matches the DUAL PRO pattern, the DUAL pattern *and* the
    bare R2-4K pattern, and comes back with four models. For a chunk being
    indexed for retrieval that is the safe direction to err in -- a chunk
    offered for too many models is filtered later. For a record that says
    "affected models", it is a claim about four products off the strength of
    one product's name, and nothing filters it afterwards.
    """
    if not _ANY_MODEL.search(text):
        return [], MODEL_SCOPE_UNSTATED

    working = text
    found: list[str] = []
    # `md._MODEL_PATTERNS` is ordered longest-name-first for exactly this
    # reason; blanking each match stops the shorter names re-matching inside
    # a longer one they are a prefix of.
    for pattern, models in md._MODEL_PATTERNS:
        matched = False

        def _blank(match: re.Match[str]) -> str:
            nonlocal matched
            matched = True
            return " " * (match.end() - match.start())

        working = pattern.sub(_blank, working)
        if matched:
            for model in models:
                if model not in found:
                    found.append(model)

    if found and md._MINI_USB_RE.search(text) and md.R2_4K_USB_C in found:
        found = [m for m in found if m != md.R2_4K_USB_C]
    if not found:
        return [], MODEL_SCOPE_UNSTATED
    return [m for m in md.ALL_MODELS if m in found], MODEL_SCOPE_NAMED


@dataclass
class WatchRun:
    checked_on: str
    fetch_mode: str
    readings: dict[str, SignalReading]
    new: list[KnownIssueRecord] = field(default_factory=list)
    changed: list[KnownIssueRecord] = field(default_factory=list)
    disappeared: list[KnownIssueRecord] = field(default_factory=list)
    unchanged: int = 0
    degraded_signals: list[str] = field(default_factory=list)

    @property
    def events(self) -> list[KnownIssueRecord]:
        return self.new + self.changed + self.disappeared


def diff_against_snapshot(
    readings: dict[str, SignalReading],
    snapshot: dict,
    candidates: dict[str, KnownIssueRecord],
    *,
    fetch_mode: str,
    checked_on: str | None = None,
) -> tuple[WatchRun, dict]:
    """Diff a reading against the last snapshot and update the candidate store.

    Mutates `candidates` in place and returns the run plus the new snapshot.

    The one rule that matters more than the rest: **a signal that did not read
    cleanly expires nothing.** A 503 from Gorgias is not twenty-two articles
    being withdrawn, and treating it as one would manufacture twenty-two
    candidate events out of a bad afternoon. On a failed read the previous
    snapshot for that signal is carried forward untouched.
    """
    now = checked_on or today()
    corpus_by_article = _corpus_doc_codes_by_article_id()
    run = WatchRun(checked_on=now, fetch_mode=fetch_mode, readings=readings)
    new_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "last_checked": now,
        "fetch_mode": fetch_mode,
        "signals": dict(snapshot.get("signals", {})),
    }

    for signal_id in SIGNAL_IDS:
        reading = readings[signal_id]
        previous = snapshot.get("signals", {}).get(signal_id, {})
        previous_items = {
            key: _item_from_json(raw)
            for key, raw in (previous.get("items") or {}).items()
        }

        if not reading.clean:
            run.degraded_signals.append(signal_id)

        if not reading.items:
            # Nothing came back at all. Carry the previous snapshot forward
            # verbatim so the next clean read diffs against real history
            # rather than against an empty page.
            carried = dict(previous)
            carried["status"] = reading.status
            carried["last_error"] = reading.errors
            carried["last_attempt"] = now
            carried.setdefault("items", previous.get("items", {}))
            carried.setdefault("urls", reading.urls)
            new_snapshot["signals"][signal_id] = carried
            continue

        current_items = {item.key: item for item in reading.items}
        for key, item in current_items.items():
            issue_id = _issue_id(signal_id, key)
            models, scope = _models_for(item.model_text)
            corpus_code = None
            if signal_id == SIGNAL_HELP_CENTER:
                corpus_code = corpus_by_article.get(item.extra.get("article_id", ""))

            existing = candidates.get(issue_id)
            if existing is None:
                record = KnownIssueRecord(
                    issue_id=issue_id,
                    title=item.title,
                    symptom_text=item.summary,
                    affected_models=models,
                    model_scope=scope,
                    source_signal=signal_id,
                    source_url=item.url,
                    first_seen=now,
                    last_seen=now,
                    last_checked=now,
                    last_changed=now,
                    status=STATUS_CANDIDATE,
                    change_kind=CHANGE_NEW,
                    fingerprint=item.fingerprint,
                    corpus_doc_code=corpus_code,
                    note=SIGNAL_NOTE[signal_id],
                    fetch_mode=fetch_mode,
                )
                candidates[issue_id] = record
                run.new.append(record)
                continue

            existing.last_checked = now
            existing.last_seen = now
            existing.fetch_mode = fetch_mode
            if existing.fingerprint != item.fingerprint:
                old_text = previous_items[key].text if key in previous_items else ""
                existing.evidence = _diff_lines(old_text, item.text)
                existing.title = item.title
                existing.symptom_text = item.summary
                existing.affected_models = models
                existing.model_scope = scope
                existing.corpus_doc_code = corpus_code
                existing.fingerprint = item.fingerprint
                existing.last_changed = now
                existing.change_kind = CHANGE_CHANGED
                if existing.status != STATUS_CONFIRMED:
                    existing.status = STATUS_CHANGED
                run.changed.append(existing)
            else:
                existing.change_kind = CHANGE_UNCHANGED
                run.unchanged += 1

        if reading.may_expire and previous_items:
            for key in previous_items:
                if key in current_items:
                    continue
                issue_id = _issue_id(signal_id, key)
                record = candidates.get(issue_id)
                if record is None or record.change_kind == CHANGE_DISAPPEARED:
                    continue
                record.last_checked = now
                record.change_kind = CHANGE_DISAPPEARED
                if record.status != STATUS_CONFIRMED:
                    record.status = STATUS_DISAPPEARED
                record.last_changed = now
                record.evidence = ["no longer present on the source page"]
                run.disappeared.append(record)

        fresh = {key: _item_to_json(item) for key, item in current_items.items()}
        if reading.clean:
            merged = fresh
        else:
            # A partial read replaces what it saw and keeps the rest. Dropping
            # the unseen keys would make them read as new on the next clean
            # run, which is a change event that never happened.
            merged = {**(previous.get("items") or {}), **fresh}
        new_snapshot["signals"][signal_id] = {
            "status": reading.status,
            "last_attempt": now,
            "last_success": now if reading.clean else previous.get("last_success"),
            "urls": reading.urls,
            "item_count": len(merged),
            "items": merged,
            "last_error": reading.errors,
        }

    assert_monitor_output_is_tier2(
        [r for r in candidates.values() if r.tier1_confirmation is None]
    )
    return run, new_snapshot


def run_watch(
    fetcher,
    store_dir: Path = STORE_DIR,
    *,
    write: bool = True,
    checked_on: str | None = None,
) -> WatchRun:
    readings = read_all_signals(fetcher)
    snapshot = load_snapshot(store_dir)
    candidates = load_candidates(store_dir)
    run, new_snapshot = diff_against_snapshot(
        readings,
        snapshot,
        candidates,
        fetch_mode=getattr(fetcher, "mode", "live"),
        checked_on=checked_on,
    )
    if write:
        write_store(store_dir, new_snapshot, candidates)
    return run


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_BANNER = (
    "Rove publishes no known-issue or release-note feed (docs/06 §9.3 item 1).\n"
    "Everything below is a Tier 2 CANDIDATE inferred from a public surface that\n"
    "is not one. Nothing here is speakable, and FW-03 stays escalation-bound."
)


def print_run(run: WatchRun) -> None:
    print(_BANNER)
    print()
    print(f"checked {run.checked_on}  mode={run.fetch_mode}")
    print()
    print("signals")
    for signal_id in SIGNAL_IDS:
        reading = run.readings[signal_id]
        print(f"  {signal_id:20} {reading.status:14} items={len(reading.items):>3}")
        for error in reading.errors:
            print(f"      ! {error}")
    if run.degraded_signals:
        print()
        print(
            "  NOTE: "
            + ", ".join(run.degraded_signals)
            + " did not read cleanly. Whatever they did return was recorded; "
            "nothing was expired for them, because a failed read is not a "
            "withdrawal."
        )

    print()
    print(
        f"events: {len(run.new)} new, {len(run.changed)} changed, "
        f"{len(run.disappeared)} disappeared, {run.unchanged} unchanged"
    )
    for label, records in (
        ("NEW", run.new),
        ("CHANGED", run.changed),
        ("DISAPPEARED", run.disappeared),
    ):
        if not records:
            continue
        print()
        print(label)
        for record in records:
            models = ", ".join(record.affected_models) or "(no model named in source)"
            print(f"  {record.issue_id}  [tier {record.tier}, {record.status}]")
            print(f"    {record.title}")
            print(f"    models: {models}")
            print(f"    {record.source_url}")
            if record.symptom_text:
                print(f"    {record.symptom_text[:160]}")
            for line in record.evidence[:6]:
                print(f"      | {line[:120]}")


def print_store(store_dir: Path) -> int:
    candidates = load_candidates(store_dir)
    snapshot = load_snapshot(store_dir)
    print(_BANNER)
    print()
    if not candidates:
        print(f"no candidates recorded yet ({store_dir / CANDIDATES_NAME} absent)")
        print("run: python -m ingest.known_issues --check")
        return 0
    print(f"last checked: {snapshot.get('last_checked', 'never')}")
    print(f"candidates:   {len(candidates)}")
    print()
    for signal_id in SIGNAL_IDS:
        rows = [r for r in candidates.values() if r.source_signal == signal_id]
        print(f"{signal_id} ({len(rows)})")
        for record in sorted(rows, key=lambda r: r.issue_id):
            corpus = f" corpus={record.corpus_doc_code}" if record.corpus_doc_code else ""
            print(
                f"  {record.issue_id:44} {record.status:12} "
                f"first_seen={record.first_seen} last_changed={record.last_changed}"
                f"{corpus}"
            )
            print(f"      {record.title[:92]}")
        print()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.known_issues",
        description=(
            "Watch the three public Rove surfaces that stand in for the "
            "known-issue feed that does not exist. Emits Tier 2 candidates "
            "only; nothing it writes is speakable."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="fetch the three signals live and diff"
    )
    mode.add_argument(
        "--offline",
        action="store_true",
        help=(
            "diff the saved fixtures in data/raw/ instead of fetching. The two "
            "app-store listings have no fixture, so that signal reads as failed"
        ),
    )
    mode.add_argument(
        "--report", action="store_true", help="print the current candidate store"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="do not write the store"
    )
    parser.add_argument(
        "--store-dir", type=Path, default=STORE_DIR, help="where the store lives"
    )
    args = parser.parse_args(argv)

    if args.report:
        return print_store(args.store_dir)

    fetcher = default_fixture_fetcher() if args.offline else UrlFetcher()
    run = run_watch(fetcher, args.store_dir, write=not args.dry_run)
    print_run(run)
    if not args.dry_run:
        print()
        print(f"wrote {args.store_dir / SNAPSHOT_NAME}")
        print(f"wrote {args.store_dir / CANDIDATES_NAME}")
    # A signal that could not be read is the thing worth a non-zero exit: the
    # watch is blind on that surface and silence must not look like calm.
    return 1 if run.degraded_signals else 0


if __name__ == "__main__":
    raise SystemExit(main())
