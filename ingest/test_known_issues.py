"""Stdlib unittest for the known-issue watch. Runs entirely offline.

    .venv/bin/python -m unittest ingest.test_known_issues
    .venv/bin/python -m unittest ingest.test_known_issues -v

The monitor fetches at runtime; these tests never do. The Help Center and
official-page signals are driven from the real saved pages in `data/raw/`, and
the two app-store signals -- which were never crawled, so there is no saved
page for them -- are driven from small hand-written payloads defined in this
file and labelled as such. None of them is vendor data and none is written
into `data/`.

What is worth testing here is not that the parsers parse. It is the three
ways this thing could quietly become dishonest:

    1. **It claims Tier 1.** The whole premise is that no vendor feed exists
       (`docs/06` §9.3 item 1), so every record is a Tier 2 candidate and
       nothing is speakable. Tested as an invariant over a real run, and
       against three forged records.
    2. **It invents change.** A failed fetch read as "every article was
       withdrawn" would manufacture twenty-two events out of one 503.
    3. **It invents scope.** A record saying "affects all six models" because
       its source named none, or because the model name was in a CDN filename
       rather than in anything Rove wrote.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ingest import known_issues as ki  # noqa: E402
from ingest import metadata as md  # noqa: E402

RAW = _REPO_ROOT / "data" / "raw"
INDEX_FIXTURE = RAW / "help-center" / "troubleshoot-index.html"
FIRMWARE_FIXTURE = RAW / "official" / "firmware-update-downloads.html"


# ---------------------------------------------------------------------------
# Hand-written app-store payloads.
#
# NOT vendor data and NOT a crawl. The two store listings were never fetched
# into `data/raw/`, so there is nothing saved to drive these parsers from.
# These stand in for the *shape* of the two responses so the parsing, keying
# and failure behaviour can be tested; the version numbers and the wording are
# invented and must never be quoted as Rove's.
# ---------------------------------------------------------------------------

FAKE_IOS_LOOKUP = json.dumps(
    {
        "resultCount": 1,
        "results": [
            {
                "trackId": 1606959035,
                "trackName": "ROVE Dash Cam",
                "version": "6.2.0",
                "currentVersionReleaseDate": "2026-10-30T12:00:00Z",
                "releaseNotes": "Fixed a connection drop on iOS 18.\nSpeed improvements.",
                "trackViewUrl": "https://apps.apple.com/us/app/rove-dash-cam/id1606959035",
            }
        ],
    }
)

FAKE_IOS_LOOKUP_NEXT = json.dumps(
    {
        "resultCount": 1,
        "results": [
            {
                "trackId": 1606959035,
                "trackName": "ROVE Dash Cam",
                "version": "6.3.0",
                "currentVersionReleaseDate": "2026-11-20T12:00:00Z",
                "releaseNotes": "Fixed firmware update failing on R3.",
                "trackViewUrl": "https://apps.apple.com/us/app/rove-dash-cam/id1606959035",
            }
        ],
    }
)

FAKE_PLAY_HTML = (
    "<html><body>"
    '<div data-id="com.rovedashcam.android">["com.rovedashcam.android",null,'
    '[["6.2.0"]]]</div>'
    "<h2>What&#39;s new</h2><div><span>Fixed WiFi disconnect on Android 14."
    "<br>Download speed improvements.</span></div>"
    "</body></html>"
)

#: The listing as Play serves it when the markup has moved: no "What's new"
#: heading, and the only `x.y.z` on the page is a library version nowhere near
#: the package id.
FAKE_PLAY_HTML_OPAQUE = (
    "<html><body><script>var lib='1.2.3';</script>"
    "<div>" + ("padding " * 400) + "com.rovedashcam.android</div>"
    "</body></html>"
)


class DictFetcher:
    """Serves whatever strings the test hands it, keyed by URL."""

    mode = "fixture"

    def __init__(self, bodies: dict[str, str], fail: set[str] | None = None):
        self._bodies = bodies
        self._fail = fail or set()

    def get(self, url: str) -> ki.FetchResult:
        if url in self._fail:
            return ki.FetchResult(url=url, ok=False, status=503, error="503 upstream")
        if url not in self._bodies:
            return ki.FetchResult(url=url, ok=False, error="no fixture for this URL")
        return ki.FetchResult(url=url, ok=True, body=self._bodies[url])


def _all_bodies(index_html: str | None = None) -> dict[str, str]:
    """Every URL the watch fetches, served from the saved pages plus the
    hand-written store payloads. A complete, clean read."""
    bodies = {
        ki.HELP_CENTER_INDEX.url: index_html
        if index_html is not None
        else INDEX_FIXTURE.read_text(encoding="utf-8"),
        ki.APP_IOS_PAGE.url: FAKE_IOS_LOOKUP,
        ki.APP_ANDROID_PAGE.url: FAKE_PLAY_HTML,
    }
    for page in ki.OFFICIAL_PAGES:
        bodies[page.url] = (_REPO_ROOT / page.fixture).read_text(encoding="utf-8")
    return bodies


# ---------------------------------------------------------------------------
# 1. The Help Center index signal
# ---------------------------------------------------------------------------


class HelpCenterIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = ki.parse_help_center_index(
            INDEX_FIXTURE.read_text(encoding="utf-8")
        )

    def test_parses_every_article_card(self) -> None:
        self.assertGreaterEqual(len(self.items), 20, "index fixture holds 20+ articles")
        for item in self.items:
            with self.subTest(item.key):
                self.assertTrue(item.title.strip(), "an article card with no title")
                self.assertTrue(
                    item.url.startswith("https://hc1.gorgias.help/en-US/"),
                    f"relative href not absolutised: {item.url}",
                )
                self.assertTrue(item.key.startswith("article:"))
                self.assertTrue(item.extra["article_id"].isdigit())

    def test_keyed_on_article_id_not_slug(self) -> None:
        """The slug carries percent-encoded smart quotes and has been
        rewritten once already (`docs/04` 1.3 `TO CHECK`). Keying on it would
        turn a slug tidy-up into a withdrawal plus a new issue."""
        for item in self.items:
            self.assertEqual(item.key, f"article:{item.extra['article_id']}")

    def test_index_self_link_is_not_an_issue(self) -> None:
        """`/en-US/articles/troubleshoot-128437` is the index linking to
        itself. It is a category page, not a problem anyone has."""
        ids = {item.extra["article_id"] for item in self.items}
        self.assertNotIn("128437", ids)

    def test_symptom_text_is_roves_own_preview(self) -> None:
        turn_on = next(i for i in self.items if i.extra["article_id"] == "472872")
        self.assertEqual(turn_on.title, "My Camera does NOT Turn ON")
        self.assertIn("powering on", turn_on.text)

    def test_articles_already_in_the_corpus_are_cross_referenced(self) -> None:
        """A candidate whose body is already on disk as Tier 1 says so. It is
        not confirmation -- having the article does not make it a known issue
        -- it just means whoever triages the candidate need not go fetch it."""
        mapping = ki._corpus_doc_codes_by_article_id()
        self.assertEqual(mapping.get("472872"), "H:camera-does-not-turn-on")
        self.assertEqual(mapping.get("477922"), "H:wifi-not-connecting")
        matched = [i for i in self.items if i.extra["article_id"] in mapping]
        self.assertGreaterEqual(
            len(matched), 10, "most indexed articles should match a saved body"
        )


# ---------------------------------------------------------------------------
# 2. The firmware / official-page signal
# ---------------------------------------------------------------------------


class FirmwarePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        page = next(p for p in ki.OFFICIAL_PAGES if p.key == "firmware-update-downloads")
        cls.page = page
        cls.items = ki.parse_official_page(
            page, FIRMWARE_FIXTURE.read_text(encoding="utf-8")
        )

    def test_emits_one_page_item_and_the_download_links(self) -> None:
        pages = [i for i in self.items if i.key.startswith("page:")]
        links = [i for i in self.items if i.key.startswith("link:")]
        self.assertEqual(len(pages), 1)
        self.assertGreaterEqual(len(links), 10)
        self.assertIn("Firmware", pages[0].text)
        self.assertIn("Format Memory Card", pages[0].text)

    def test_cache_buster_is_stripped_from_the_key_but_not_the_fingerprint(self) -> None:
        """Shopify re-uploads append `?v=<epoch>`. If the key carried it, a
        re-upload would read as the old file disappearing and a new one
        appearing; the file changing is what actually happened."""
        dual_pro = next(
            i for i in self.items
            if i.key.endswith("ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf")
        )
        self.assertNotIn("?v=", dual_pro.key)
        self.assertIn("?v=1787084395", dual_pro.url)

        bumped = ki.parse_official_page(
            self.page,
            FIRMWARE_FIXTURE.read_text(encoding="utf-8").replace(
                "v=1787084395", "v=1799999999"
            ),
        )
        after = next(i for i in bumped if i.key == dual_pro.key)
        self.assertEqual(after.key, dual_pro.key, "same artifact, same key")
        self.assertNotEqual(after.fingerprint, dual_pro.fingerprint, "and a change")

    def test_models_come_from_the_label_never_from_the_cdn_path(self) -> None:
        """The mini-USB hardwire kit is the case that separates the two.

        Its label says "Hardwire Kit for R2-4K (Mini-USB Version)", which
        names one hardware revision. Its filename is `R2-4K_HWK_UM.pdf`,
        which says only "R2-4K" and so matches *both* revisions. Reading
        models out of the URL would widen a one-revision document to two.
        """
        hwk = next(i for i in self.items if i.key.endswith("R2-4K_HWK_UM.pdf"))
        self.assertIn("Mini-USB", hwk.model_text)
        self.assertNotIn("cdn.shopify.com", hwk.model_text)
        from_label, scope = ki._models_for(hwk.model_text)
        self.assertEqual(from_label, [md.R2_4K_MINI_USB])
        self.assertEqual(scope, ki.MODEL_SCOPE_NAMED)

        # The case that shows why the separation is kept: a generic link
        # label with a model name in the filename. Rove named no model here;
        # a build engineer named a file.
        synthetic = ki.parse_official_page(
            self.page,
            '<html><main><a href="https://cdn.shopify.com/s/files/'
            'ROVE-R3-Firmware.zip">Download the latest firmware</a>'
            "</main></html>",
        )
        link = next(i for i in synthetic if i.key.startswith("link:"))
        self.assertEqual(ki._models_for(link.model_text), ([], ki.MODEL_SCOPE_UNSTATED))
        self.assertEqual(ki._models_for(link.url), ([md.R3], ki.MODEL_SCOPE_NAMED))

    def test_a_longer_model_name_is_not_also_the_shorter_ones(self) -> None:
        """"R2-4K DUAL PRO" names one product. It contains the substrings
        "R2-4K" and "R2-4K DUAL", and the shared `md.models_named_in` returns
        all four on that basis -- right for a retrieval filter, wrong for a
        record that claims which models are affected."""
        dual_pro = next(
            i for i in self.items
            if i.key.endswith("ROVE_R2-4K_DUAL_PRO_User_Manual_Updated.pdf")
        )
        models, scope = ki._models_for(dual_pro.model_text)
        self.assertEqual(models, [md.R2_4K_DUAL_PRO])
        self.assertEqual(scope, ki.MODEL_SCOPE_NAMED)

        widened, _ = md.models_named_in(dual_pro.model_text)
        self.assertEqual(len(widened), 4, "the shared helper is the wider one")

    def test_the_local_matcher_agrees_with_the_shared_one_on_a_single_name(self) -> None:
        """The two rules must not drift apart on the simple cases. Where only
        one model is named, the span-exclusive matcher and `md` agree."""
        for text, expected in (
            ("ROVE R3", [md.R3]),
            ("R2-4K PRO", [md.R2_4K_PRO]),
            ("R2-4K DUAL", [md.R2_4K_DUAL]),
        ):
            with self.subTest(text):
                mine, scope = ki._models_for(text)
                theirs, _ = md.models_named_in(text)
                self.assertEqual(scope, ki.MODEL_SCOPE_NAMED)
                self.assertEqual(mine, expected)
                self.assertEqual(theirs[-1], expected[-1])

    def test_the_page_publishes_no_firmware_binary(self) -> None:
        """A fact about the 2026-11-07 capture, and the reason `docs/04` says
        this signal can report that something changed and not what it fixes.

        The Firmware Update & Downloads page -- the page named in `docs/04`
        1.1 as the firmware source -- links manuals, the GPS Player and the
        two app stores. It links no firmware image at all. The watch therefore
        cannot see a firmware release on this page unless Rove starts
        publishing one.
        """
        binaries = [
            i for i in self.items
            if i.key.startswith("link:")
            and i.url.lower().split("?")[0].endswith((".zip", ".bin", ".rar", ".img"))
        ]
        self.assertEqual(
            binaries, [], "fixture captured 2026-11-07 held no firmware image"
        )


# ---------------------------------------------------------------------------
# 3. The app-changelog signal
# ---------------------------------------------------------------------------


class AppChangelogTest(unittest.TestCase):
    def test_ios_lookup_yields_one_item_per_version(self) -> None:
        items = ki.parse_ios_lookup(FAKE_IOS_LOOKUP)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].key, "ios:6.2.0")
        self.assertIn("connection drop", items[0].text)
        self.assertEqual(items[0].extra["released_on"], "2026-10-30")

    def test_android_reads_whats_new_and_the_version(self) -> None:
        items = ki.parse_android_listing(FAKE_PLAY_HTML)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].key, "android:6.2.0")
        self.assertTrue(items[0].extra["version_parsed"])
        self.assertIn("WiFi disconnect", items[0].text)

    def test_android_returns_nothing_rather_than_a_guessed_version(self) -> None:
        """Play has no API and the payload shape moves. A stray `1.2.3` in a
        script tag is not a release. Returning nothing is what lets the caller
        say "blind on Android" instead of "nothing changed on Android"."""
        self.assertEqual(ki.parse_android_listing(FAKE_PLAY_HTML_OPAQUE), [])

    def test_a_blind_android_arm_does_not_discard_a_good_ios_read(self) -> None:
        fetcher = DictFetcher(
            {
                ki.APP_IOS_PAGE.url: FAKE_IOS_LOOKUP,
                ki.APP_ANDROID_PAGE.url: FAKE_PLAY_HTML_OPAQUE,
            }
        )
        reading = ki.read_app_changelog(fetcher)
        self.assertEqual(reading.status, ki.SIGNAL_PARSE_FAILED)
        self.assertFalse(reading.clean)
        self.assertEqual([i.key for i in reading.items], ["ios:6.2.0"])
        self.assertTrue(any("Play markup moved" in e for e in reading.errors))

    def test_a_superseded_release_is_not_a_withdrawal(self) -> None:
        """The stores show the current version only. 6.2.0 scrolling off the
        listing when 6.3.0 ships is the shape of the surface, not Rove pulling
        a release."""
        self.assertFalse(ki.TRACKS_DISAPPEARANCE[ki.SIGNAL_APP])
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(DictFetcher(_all_bodies()), store, checked_on="2026-11-08")
            bodies = _all_bodies()
            bodies[ki.APP_IOS_PAGE.url] = FAKE_IOS_LOOKUP_NEXT
            run = ki.run_watch(DictFetcher(bodies), store, checked_on="2026-11-20")
            self.assertEqual([r.issue_id for r in run.new], ["KI-APP-ios-6-3-0"])
            self.assertEqual(run.disappeared, [])
            kept = ki.load_candidates(store)["KI-APP-ios-6-2-0"]
            self.assertEqual(kept.status, ki.STATUS_CANDIDATE)
            self.assertEqual(kept.first_seen, "2026-11-08")


# ---------------------------------------------------------------------------
# 4. The tier rule
# ---------------------------------------------------------------------------


class TierRuleTest(unittest.TestCase):
    def test_every_record_from_a_real_run_is_an_unspeakable_tier_2_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = ki.run_watch(
                DictFetcher(_all_bodies()), Path(tmp), checked_on="2026-11-08"
            )
            records = list(ki.load_candidates(Path(tmp)).values())
        self.assertGreater(len(records), 30)
        self.assertEqual(len(run.new), len(records))
        for record in records:
            with self.subTest(record.issue_id):
                self.assertEqual(record.tier, 2)
                self.assertFalse(record.speakable)
                self.assertIsNone(record.tier1_confirmation)
                self.assertEqual(record.status, ki.STATUS_CANDIDATE)
                self.assertIn("Tier 2 until a Tier 1 source confirms", record.note)

    def test_the_written_store_says_no_vendor_feed_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(DictFetcher(_all_bodies()), store, checked_on="2026-11-08")
            payload = json.loads(
                (store / ki.CANDIDATES_NAME).read_text(encoding="utf-8")
            )
        self.assertEqual(payload["tier"], 2)
        self.assertFalse(payload["speakable"])
        self.assertIn("no known-issue or release-note feed", payload["no_vendor_feed"])
        self.assertIn("FW-03 stays escalation-bound", payload["no_vendor_feed"])

    def test_forged_records_are_rejected_before_they_are_written(self) -> None:
        def record(**overrides) -> ki.KnownIssueRecord:
            base = dict(
                issue_id="KI-HC-1",
                title="t",
                symptom_text="s",
                affected_models=[],
                model_scope=ki.MODEL_SCOPE_UNSTATED,
                source_signal=ki.SIGNAL_HELP_CENTER,
                source_url="https://example.invalid",
                first_seen="2026-11-08",
                last_seen="2026-11-08",
                last_checked="2026-11-08",
                last_changed="2026-11-08",
                status=ki.STATUS_CANDIDATE,
                change_kind=ki.CHANGE_NEW,
                fingerprint="abc",
            )
            base.update(overrides)
            return ki.KnownIssueRecord(**base)

        ki.assert_monitor_output_is_tier2([record()])  # the honest one passes

        for label, forged in (
            ("claims Tier 1", record(tier=1)),
            ("claims speakable", record(speakable=True)),
            ("claims a confirmation", record(tier1_confirmation={"doc_code": "O1"})),
            ("claims confirmed status", record(status=ki.STATUS_CONFIRMED)),
        ):
            with self.subTest(label):
                with self.assertRaises(ki.Tier1Violation):
                    ki.assert_monitor_output_is_tier2([forged])

    def test_promotion_needs_a_real_tier_1_document_and_a_named_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(DictFetcher(_all_bodies()), store, checked_on="2026-11-08")
            record = ki.load_candidates(store)["KI-HC-472872"]

        with self.assertRaises(ValueError):
            ki.confirm_with_tier1(
                record,
                doc_code="NOT-A-DOC",
                confirmed_by="Hardik",
                confirmed_on="2026-11-09",
            )
        with self.assertRaises(ValueError):
            ki.confirm_with_tier1(
                record,
                doc_code="H:camera-does-not-turn-on",
                confirmed_by="   ",
                confirmed_on="2026-11-09",
            )

        promoted = ki.confirm_with_tier1(
            record,
            doc_code="H:camera-does-not-turn-on",
            confirmed_by="Hardik",
            confirmed_on="2026-11-09",
        )
        self.assertEqual(promoted.status, ki.STATUS_CONFIRMED)
        self.assertEqual(promoted.tier1_confirmation["confirmed_by"], "Hardik")
        self.assertFalse(
            promoted.speakable,
            "confirming a known issue is not the chunk-level speakable gate "
            "of docs/06 §4.5",
        )

    def test_the_watch_writes_nothing_into_the_speakable_corpus(self) -> None:
        """Two separate guarantees. The store is not under `data/processed/`,
        and no file the watch writes is registered as an ingestable source --
        so `python -m ingest.run` cannot pick a candidate up and chunk it."""
        processed = _REPO_ROOT / "data" / "processed"
        self.assertNotEqual(ki.STORE_DIR, processed)
        self.assertNotIn(processed, ki.STORE_DIR.parents)

        store_rel = ki.STORE_DIR.relative_to(_REPO_ROOT).as_posix()
        for code, source in md.SOURCES.items():
            self.assertFalse(
                source.path.startswith(store_rel),
                f"{code} points into the known-issue store",
            )

    def test_candidates_are_tier_2_in_the_sense_docs_04_already_means(self) -> None:
        self.assertEqual(ki.TIER_CANDIDATE, 2)
        self.assertNotEqual(ki.TIER_CANDIDATE, md.TIER)
        self.assertEqual(md.TIER, ki.TIER_GROUND_TRUTH)


# ---------------------------------------------------------------------------
# 5. The diff
# ---------------------------------------------------------------------------


class DiffTest(unittest.TestCase):
    def test_a_second_identical_run_reports_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            first = ki.run_watch(
                DictFetcher(_all_bodies()), store, checked_on="2026-11-08"
            )
            second = ki.run_watch(
                DictFetcher(_all_bodies()), store, checked_on="2026-12-01"
            )
            self.assertEqual(second.new, [])
            self.assertEqual(second.changed, [])
            self.assertEqual(second.disappeared, [])
            self.assertEqual(second.unchanged, len(first.new))

            record = ki.load_candidates(store)["KI-HC-472872"]
            self.assertEqual(record.first_seen, "2026-11-08", "first_seen is history")
            self.assertEqual(record.last_checked, "2026-12-01")
            self.assertEqual(record.last_changed, "2026-11-08")

    def test_an_edited_article_is_one_changed_record_with_the_diff_on_it(self) -> None:
        original = INDEX_FIXTURE.read_text(encoding="utf-8")
        edited = original.replace(
            "Follow these step-by-step options to identify what&#x27;s preventing",
            "KNOWN ISSUE: after the latest firmware update, some cameras will not",
            1,
        )
        self.assertNotEqual(original, edited, "the edit must actually apply")

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(DictFetcher(_all_bodies()), store, checked_on="2026-11-08")
            run = ki.run_watch(
                DictFetcher(_all_bodies(edited)), store, checked_on="2026-12-01"
            )

            self.assertEqual([r.issue_id for r in run.changed], ["KI-HC-472872"])
            self.assertEqual(run.new, [])
            self.assertEqual(run.disappeared, [])

            changed = run.changed[0]
            self.assertEqual(changed.status, ki.STATUS_CHANGED)
            self.assertEqual(changed.first_seen, "2026-11-08")
            self.assertEqual(changed.last_changed, "2026-12-01")
            self.assertIn("KNOWN ISSUE", changed.symptom_text)
            self.assertTrue(
                any("KNOWN ISSUE" in line for line in changed.evidence),
                f"the added line should be on the record: {changed.evidence}",
            )
            self.assertEqual(changed.tier, 2, "a change is still only a candidate")

    def test_a_pulled_article_is_recorded_as_disappeared(self) -> None:
        original = INDEX_FIXTURE.read_text(encoding="utf-8")
        start = original.index('<a aria-label="My Camera does NOT Turn ON"')
        end = original.index("</a>", start) + len("</a>")
        pulled = original[:start] + original[end:]

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            first = ki.run_watch(
                DictFetcher(_all_bodies()), store, checked_on="2026-11-08"
            )
            run = ki.run_watch(
                DictFetcher(_all_bodies(pulled)), store, checked_on="2026-12-01"
            )

            self.assertEqual([r.issue_id for r in run.disappeared], ["KI-HC-472872"])
            self.assertEqual(run.new, [])
            self.assertEqual(run.unchanged, len(first.new) - 1)

            gone = ki.load_candidates(store)["KI-HC-472872"]
            self.assertEqual(gone.status, ki.STATUS_DISAPPEARED)
            self.assertEqual(gone.first_seen, "2026-11-08")

    def test_a_failed_fetch_withdraws_nothing(self) -> None:
        """The one that matters most. Gorgias returning 503 is not twenty-one
        articles being pulled, and a watch that reported it as twenty-one
        events would be worse than no watch."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            first = ki.run_watch(
                DictFetcher(_all_bodies()), store, checked_on="2026-11-08"
            )
            hc_count = len([r for r in first.new if r.source_signal == ki.SIGNAL_HELP_CENTER])
            self.assertGreaterEqual(hc_count, 20)

            run = ki.run_watch(
                DictFetcher(_all_bodies(), fail={ki.HELP_CENTER_INDEX.url}),
                store,
                checked_on="2026-12-01",
            )

            self.assertEqual(run.disappeared, [], "a 503 is not a withdrawal")
            self.assertEqual(run.new, [])
            self.assertIn(ki.SIGNAL_HELP_CENTER, run.degraded_signals)
            self.assertEqual(
                run.readings[ki.SIGNAL_HELP_CENTER].status, ki.SIGNAL_FETCH_FAILED
            )

            for record in ki.load_candidates(store).values():
                if record.source_signal == ki.SIGNAL_HELP_CENTER:
                    self.assertEqual(record.status, ki.STATUS_CANDIDATE)

            snapshot = ki.load_snapshot(store)
            carried = snapshot["signals"][ki.SIGNAL_HELP_CENTER]
            self.assertEqual(len(carried["items"]), hc_count, "history carried forward")
            self.assertEqual(carried["status"], ki.SIGNAL_FETCH_FAILED)

    def test_a_partial_page_failure_keeps_the_pages_it_could_not_read(self) -> None:
        """Firmware is three pages. One failing must not expire the other
        two's links, and must not drop the failed page's items from the
        snapshot -- that would make them read as new on the next clean run."""
        o3 = next(p for p in ki.OFFICIAL_PAGES if p.key == "update-firmware-r2-4k")
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(DictFetcher(_all_bodies()), store, checked_on="2026-11-08")
            before = len(
                ki.load_snapshot(store)["signals"][ki.SIGNAL_FIRMWARE]["items"]
            )

            degraded = ki.run_watch(
                DictFetcher(_all_bodies(), fail={o3.url}),
                store,
                checked_on="2026-12-01",
            )
            self.assertEqual(degraded.disappeared, [])
            self.assertIn(ki.SIGNAL_FIRMWARE, degraded.degraded_signals)
            self.assertEqual(
                len(ki.load_snapshot(store)["signals"][ki.SIGNAL_FIRMWARE]["items"]),
                before,
            )

            recovered = ki.run_watch(
                DictFetcher(_all_bodies()), store, checked_on="2026-12-02"
            )
            self.assertEqual(recovered.new, [], "recovery must not look like news")
            self.assertEqual(recovered.changed, [])

    def test_a_snapshot_from_an_older_schema_is_discarded_not_diffed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            store.mkdir(exist_ok=True)
            (store / ki.SNAPSHOT_NAME).write_text(
                json.dumps({"schema_version": 0, "signals": {"x": {}}}),
                encoding="utf-8",
            )
            self.assertEqual(ki.load_snapshot(store)["signals"], {})


# ---------------------------------------------------------------------------
# 6. Model scope
# ---------------------------------------------------------------------------


class ModelScopeTest(unittest.TestCase):
    def test_naming_no_model_and_naming_every_model_are_different_facts(self) -> None:
        """`md.models_named_in` reports both as `(ALL_MODELS, cross=True)`,
        which is right for a retrieval filter and wrong for a known-issue
        record: "Rove named no model" is not evidence that all six are hit."""
        none_named, none_scope = ki._models_for(
            "Your dash cam keeps saying WiFi Is Connected"
        )
        self.assertEqual(none_named, [])
        self.assertEqual(none_scope, ki.MODEL_SCOPE_UNSTATED)

        all_named, all_scope = ki._models_for(
            "Affects R2-4K, R2-4K PRO, R2-4K DUAL, R2-4K DUAL PRO and R3"
        )
        self.assertEqual(all_scope, ki.MODEL_SCOPE_NAMED)
        self.assertEqual(len(all_named), len(md.ALL_MODELS))

    def test_records_carry_the_scope_they_were_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ki.run_watch(
                DictFetcher(_all_bodies()), Path(tmp), checked_on="2026-11-08"
            )
            records = ki.load_candidates(Path(tmp)).values()
        for record in records:
            with self.subTest(record.issue_id):
                if record.model_scope == ki.MODEL_SCOPE_UNSTATED:
                    self.assertEqual(record.affected_models, [])
                else:
                    self.assertTrue(record.affected_models)
                    for model in record.affected_models:
                        self.assertIn(model, md.ALL_MODELS)


# ---------------------------------------------------------------------------
# 7. The offline entry point
# ---------------------------------------------------------------------------


class OfflineCliTest(unittest.TestCase):
    def test_offline_mode_reads_the_saved_pages_and_reports_the_app_gap(self) -> None:
        """`--offline` is honest about what it is: the two store listings were
        never crawled, so that signal reads as failed rather than as quiet."""
        fetcher = ki.default_fixture_fetcher()
        self.assertEqual(fetcher.mode, "fixture")
        readings = ki.read_all_signals(fetcher)
        self.assertTrue(readings[ki.SIGNAL_HELP_CENTER].clean)
        self.assertTrue(readings[ki.SIGNAL_FIRMWARE].clean)
        self.assertEqual(readings[ki.SIGNAL_APP].status, ki.SIGNAL_FETCH_FAILED)
        self.assertEqual(readings[ki.SIGNAL_APP].items, [])

    def test_a_fixture_run_is_labelled_as_one(self) -> None:
        """A record diffed out of a 2026-11-07 capture is not a statement
        about the web today, and must not be filed as one."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            ki.run_watch(ki.default_fixture_fetcher(), store, checked_on="2026-11-08")
            for record in ki.load_candidates(store).values():
                self.assertEqual(record.fetch_mode, "fixture")
            self.assertEqual(ki.load_snapshot(store)["fetch_mode"], "fixture")

    def test_the_cli_exits_non_zero_when_a_signal_is_blind(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(out):
                code = ki.main(["--offline", "--store-dir", tmp])
        self.assertEqual(code, 1, "app_changelog has no fixture, so the run is blind")
        self.assertIn("no known-issue or release-note feed", out.getvalue())
        self.assertIn("FW-03 stays escalation-bound", out.getvalue())

    def test_report_on_an_empty_store_says_so_instead_of_failing(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(out):
                self.assertEqual(ki.main(["--report", "--store-dir", tmp]), 0)
        self.assertIn("no candidates recorded yet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
