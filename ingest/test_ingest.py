"""Stdlib unittest for the Tier-1 ingestion.

    .venv/bin/python -m unittest ingest.test_ingest
    .venv/bin/python -m unittest ingest.test_ingest -v

These rules are worth a test because breaking any of them is silent: the
chunker would still produce chunks, the validator would still exit 0, and the
damage would only show up as a wrong answer spoken to a caller.

    1. A numbered procedure is never split across two chunks (`docs/06` §4.2).
    2. An `operator_attested` manual chunk carries the attestation, the
       prototype scope and the `unknown` firmware default (§4.3, §4.4, §4.6).
    3. The validator rejects a chunk with no source (`docs/04` item 5).
    4. The validator rejects a chunk whose `section_path` is empty -- a
       required field that is present but empty is still missing (§4.3).
    5. Non-manual boilerplate is stripped and manual content is not. Asserted
       twice over, for `M6`'s storefront and for `M7`'s printed cover and
       contact pages, because the two halves fail in opposite directions.
    6. The Milestone 4.3 sources are registered as what they are: `M7` has a
       real source URL, so it is `crawler` and production-scoped, not
       `operator_attested`; and the three new Help Center articles with no
       `docs/02` entry behind them stay UNVERIFIED and unspeakable.

Imports are absolute, with the repo root forced onto `sys.path`, so the file
works under both `python -m unittest ingest.test_ingest` and
`unittest discover -s ingest`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ingest import metadata as md  # noqa: E402
from ingest import validate  # noqa: E402
from ingest.chunk import (  # noqa: E402
    TARGET_MAX,
    Block,
    PARA,
    STEP,
    build_pieces,
    chunk_source,
    pack,
    parse_manual,
)

#: A chunk record as the validator expects to find it, used as the baseline
#: that each failure case breaks exactly one field of. Built from a real
#: chunk so the test cannot drift away from the schema the ingest emits.
def _reference_chunk() -> dict:
    chunks = chunk_source(md.SOURCES["M1"])
    for chunk in chunks:
        if chunk.speakable:
            return chunk.to_json_dict()
    raise AssertionError("M1 produced no speakable chunk to build a case from")


class ProcedureAtomicity(unittest.TestCase):
    """`docs/06` §4.2: a numbered procedure is atomic, budget or no budget."""

    def test_long_procedure_is_not_split(self) -> None:
        # Eight steps, each long enough that the run alone blows the 800-token
        # budget. The packer must still emit it as one chunk.
        padding = "connect the cable and wait for the camera to settle " * 12
        blocks = [Block(PARA, "Update the firmware from the card:")]
        blocks += [
            Block(STEP, f"{number}. Step {number}: {padding}")
            for number in range(1, 9)
        ]

        pieces = build_pieces(blocks)
        chunks = pack(pieces)

        self.assertEqual(len(chunks), 1, "an atomic procedure was split")
        text = chunks[0].pieces[0].text
        for number in range(1, 9):
            self.assertIn(f"{number}. Step {number}", text)
        self.assertGreater(
            chunks[0].tokens,
            TARGET_MAX,
            "the test procedure is not actually over budget, so it proves "
            "nothing about atomicity",
        )

    def test_corpus_has_no_split_procedure(self) -> None:
        # The same rule, checked the way the validator checks it, over the
        # real corpus rather than a constructed case.
        chunks = [c.to_json_dict() for c in chunk_source(md.SOURCES["M2"])]
        self.assertEqual(validate.check_procedures_atomic(chunks), [])


class ManualChunkMetadata(unittest.TestCase):
    """Defaults on a chunk from an `operator_attested` manual (M1)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = md.SOURCES["M1"]
        cls.chunks = chunk_source(cls.source)

    def test_source_is_operator_attested(self) -> None:
        self.assertEqual(self.source.provenance, md.PROVENANCE_OPERATOR_ATTESTED)
        self.assertIsNone(self.source.source_url)

    def test_defaults(self) -> None:
        self.assertTrue(self.chunks, "M1 produced no chunks")
        for chunk in self.chunks:
            with self.subTest(chunk=chunk.chunk_id):
                self.assertEqual(chunk.tier, md.TIER)
                self.assertEqual(chunk.retrieval_date, md.RETRIEVAL_DATE)
                self.assertEqual(chunk.provenance, md.PROVENANCE_OPERATOR_ATTESTED)
                # No URL, so the attestation is the whole of the provenance.
                self.assertEqual(chunk.attested_by, md.ATTESTED_BY)
                self.assertEqual(chunk.speakable_scope, md.SCOPE_PROTOTYPE)
                # §4.6: never a version, on any chunk, ever.
                self.assertEqual(chunk.firmware_applicability, {"version": "unknown"})
                # §4.3: applicability is explicit, never "all".
                self.assertEqual(chunk.model_applicability, [md.R2_4K_MINI_USB])
                self.assertFalse(chunk.cross_model)
                # M1 is the mini-USB revision: a hardware-revision document.
                self.assertTrue(chunk.hw_revision_specific)
                self.assertTrue(chunk.section_path)
                self.assertEqual(chunk.section, chunk.section_path[-1])
                self.assertTrue(chunk.context_header)
                self.assertGreater(chunk.token_estimate, 0)
                self.assertIn(chunk.verification_status, md.STATUS_RANK)
                if chunk.speakable:
                    self.assertIn(chunk.verification_status, md.SPEAKABLE_STATUSES)

    def test_unverified_chunk_is_not_speakable(self) -> None:
        for chunk in self.chunks:
            if chunk.verification_status not in md.SPEAKABLE_STATUSES:
                with self.subTest(chunk=chunk.chunk_id):
                    self.assertFalse(chunk.speakable)


class ValidatorCatchesBadChunks(unittest.TestCase):
    """The validator has to fail on the two cases it exists to fail on."""

    def setUp(self) -> None:
        self.chunk = _reference_chunk()

    def test_reference_chunk_passes(self) -> None:
        self.assertEqual(validate.check_chunks([self.chunk]), [])

    def test_empty_source_is_an_error(self) -> None:
        # No URL and no attestation: nothing says where the text came from.
        self.chunk["source_url"] = None
        self.chunk["provenance"] = md.PROVENANCE_CRAWLER
        self.chunk["attested_by"] = None

        errors = validate.check_chunks([self.chunk])

        self.assertTrue(errors, "a chunk with no source passed validation")
        self.assertTrue(
            any("no source" in error for error in errors),
            f"expected a 'no source' error, got {errors}",
        )

    def test_missing_attestation_is_an_error(self) -> None:
        # operator_attested is a source only while the attestation is there.
        self.chunk["source_url"] = None
        self.chunk["attested_by"] = None

        errors = validate.check_chunks([self.chunk])

        self.assertTrue(
            any("no source" in error for error in errors),
            f"expected a 'no source' error, got {errors}",
        )

    def test_empty_section_path_is_an_error(self) -> None:
        self.chunk["section_path"] = []

        errors = validate.check_chunks([self.chunk])

        self.assertTrue(
            any("empty required field 'section_path'" in error for error in errors),
            f"expected an empty-section_path error, got {errors}",
        )

    def test_missing_section_path_is_an_error(self) -> None:
        del self.chunk["section_path"]

        errors = validate.check_chunks([self.chunk])

        self.assertTrue(
            any("missing metadata field 'section_path'" in error for error in errors),
            f"expected a missing-section_path error, got {errors}",
        )


class M6StorefrontBoilerplate(unittest.TestCase):
    """M6 extracts with the storefront attached; the chunker takes it off.

    The regression this guards is one-sided: the boilerplate must go and the
    manual content must stay. Dropping the mounting steps would be the worse
    of the two failures, so both are asserted.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = md.SOURCES["M6"]
        cls.chunks = chunk_source(cls.source)
        cls.text = "\n".join(c.text for c in cls.chunks)

    def test_raw_extraction_really_does_contain_the_boilerplate(self) -> None:
        raw = (_REPO_ROOT / self.source.path).read_text(encoding="utf-8")
        self.assertIn("Are you at least 18 years old?", raw)
        self.assertIn("FREE 3 DAY SHIPPING ON ALL DASH CAMS", raw)

    def test_boilerplate_is_stripped(self) -> None:
        for phrase in (
            "Are you at least 18 years old",
            "Come back when you're older",
            "FREE 3 DAY SHIPPING",
            "Below, you'll find all the latest firmware",
            "Join our ROVE Dash Cam Community",
            "Scan the QR Code to Email or Text Us",
            "WATCH HOW TO VIDEOS",
            "Rove dash cam coupon code",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.casefold(), self.text.casefold())

    def test_manual_content_is_kept(self) -> None:
        for phrase in (
            "magnetic mount",  # the page-3 mounting steps are real content
            "electrostatic film",
            "12345678",  # the R3 Wi-Fi default password
            "Class 10",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.casefold(), self.text.casefold())

    def test_section_path_falls_back_to_the_document_title(self) -> None:
        # Page 3 of M6 carries no heading at all, which is what produced the
        # empty required field the validator used to fail on.
        blocks = parse_manual(_REPO_ROOT / self.source.path)
        self.assertFalse(
            [b for b in blocks if b.kind == "heading"],
            "M6 now has headings; this test's premise no longer holds",
        )
        for chunk in self.chunks:
            with self.subTest(chunk=chunk.chunk_id):
                self.assertEqual(chunk.section_path, [self.source.title])

    def test_m6_chunks_pass_validation(self) -> None:
        errors = validate.check_chunks([c.to_json_dict() for c in self.chunks])
        self.assertEqual(errors, [])


class M7PrintedFurniture(unittest.TestCase):
    """`M7` arrives with Rove's own cover and contact pages attached.

    Same one-sided regression as `M6StorefrontBoilerplate`, and the same two
    assertions, because the failure modes are opposite in cost: leaving the
    furniture in put a Facebook invite and a returns notice into a *speakable*
    chunk, and taking too much out would lose the troubleshooting table, the
    temperature guideline and the thermal-shutdown note -- which are the whole
    reason this manual was added (`docs/05` PWR-02).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = md.SOURCES["M7"]
        cls.chunks = chunk_source(cls.source)
        cls.text = "\n".join(c.text for c in cls.chunks)

    def test_raw_extraction_really_does_contain_the_furniture(self) -> None:
        raw = (_REPO_ROOT / self.source.path).read_text(encoding="utf-8")
        self.assertIn("Join the vibrant ROVE Dash", raw)
        self.assertIn("CONTACT US BEFORE RETURNING THE ITEM", raw)
        self.assertIn("Introduction .....", raw)

    def test_furniture_is_stripped(self) -> None:
        for phrase in (
            "Wanna meet",
            "other ROVERS",
            "Join the vibrant ROVE Dash Cam Community",
            "Community on Facebook",
            "CONTACT US BEFORE RETURNING THE ITEM",
            "WE WILL HELP YOU RESOLVE ANY ISSUES ASAP",
            "Item NOT as described",
            "Any issues what so ever",
            "Scan to visit the link",
            "Scan the QR Code",
            "License Plates. Smallest Details.",
            "www.rovedashcam.com/pages/videos",
            "1-844-ROVE-CAM",
            "7 Days a Week",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.casefold(), self.text.casefold())

    def test_table_of_contents_is_stripped(self) -> None:
        # Dot leaders are the signature; 36 of those lines were most of what
        # the first chunk used to contain.
        self.assertNotRegex(self.text, r"\.{4,}")
        self.assertNotIn(
            "pairing your r2-4k dual pro with your smart phone using wifi 43",
            self.text.casefold(),
        )

    def test_manual_content_is_kept(self) -> None:
        for phrase in (
            # The thermal-shutdown note -- the reason PWR-02 moved.
            "automatically shut down",
            "greenhouse effect",
            "Operating Temperature",
            "Camera gets HOT",
            # The troubleshooting table.
            "Video is fuzzy",
            "Camera does not turn ON",
            "GOLD CONTACTS",
            # Ordinary manual facts.
            "Clarity Priority",
            "12345678",
            "24-HR AUTO PARKING",
            "Loop Recording",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.casefold(), self.text.casefold())

    def test_words_that_look_like_furniture_but_are_not(self) -> None:
        # `FREE` and `STOP` are deliberately absent from _MANUAL_FURNITURE.
        # These two lines are why; a later widening of the rule breaks here
        # rather than silently in the corpus.
        self.assertIn("stop", self.text.casefold())  # the GPS player control
        self.assertIn("feel free to", self.text.casefold())

    def test_m7_chunks_pass_validation(self) -> None:
        errors = validate.check_chunks([c.to_json_dict() for c in self.chunks])
        self.assertEqual(errors, [])


class TrackCRegistry(unittest.TestCase):
    """The Milestone 4.3 sources, and the provenance rule that separates them."""

    NEW_HELP = (
        "H:overheating",
        "H:licence-plate",
        "H:blurry-video",
        "H:random-restarting",
        "H:repeatedly-on-off",
        "H:frozen-screen",
    )

    def test_corpus_shape(self) -> None:
        manuals = [s for s in md.SOURCES.values() if s.kind == "manual_text"]
        help_center = [
            s for s in md.SOURCES.values() if s.kind == "help_center_html"
        ]
        self.assertEqual(len(manuals), 7)
        self.assertEqual(len(help_center), 18)
        self.assertEqual(len(md.SOURCES), 28)

    def test_every_registered_file_exists(self) -> None:
        for source in md.SOURCES.values():
            with self.subTest(doc=source.doc_code):
                self.assertTrue((_REPO_ROOT / source.path).is_file())

    def test_m7_has_a_url_and_is_not_operator_attested(self) -> None:
        # `docs/06` §4.4: a real source URL is a stronger provenance than an
        # attestation, and it is what keeps M7 out of prototype-only scope.
        source = md.SOURCES["M7"]
        self.assertEqual(source.provenance, md.PROVENANCE_CRAWLER)
        self.assertTrue(source.source_url.startswith("https://cdn.shopify.com/"))
        self.assertEqual(source.speakable_scope, md.SCOPE_PRODUCTION)
        for chunk in chunk_source(source):
            with self.subTest(chunk=chunk.chunk_id):
                self.assertIsNone(chunk.attested_by)
                self.assertEqual(chunk.model_applicability, [md.R2_4K_DUAL_PRO])
                self.assertFalse(chunk.cross_model)
                self.assertEqual(chunk.firmware_applicability, {"version": "unknown"})

    def test_new_help_articles_are_tier_1_with_urls(self) -> None:
        for code in self.NEW_HELP:
            with self.subTest(doc=code):
                source = md.SOURCES[code]
                self.assertEqual(source.tier, md.TIER)
                self.assertEqual(source.provenance, md.PROVENANCE_CRAWLER)
                self.assertTrue(
                    source.source_url.startswith("https://hc1.gorgias.help/en-US/")
                )
                self.assertTrue(chunk_source(source), f"{code} produced no chunks")

    #: Milestone 5.2 wrote the `docs/02` Category H guards these three
    #: articles were waiting on. Until 5.2 they were Tier 1 material with no
    #: entry to hang a status on, so they were UNVERIFIED and unspeakable and
    #: this test asserted exactly that. The entries now exist, so the
    #: assertion inverts -- which is the point of the milestone, and is worth
    #: a test rather than a silent deletion.
    GUARDED_ARTICLES = {
        "H:random-restarting": "GAP-RANDOM-RESTART",
        "H:repeatedly-on-off": "GAP-ON-OFF-CYCLING",
        "H:frozen-screen": "GAP-FROZEN-SCREEN",
    }

    def test_formerly_unmapped_articles_are_now_guarded(self) -> None:
        for code, gap_id in self.GUARDED_ARTICLES.items():
            with self.subTest(doc=code):
                chunks = chunk_source(md.SOURCES[code])
                grounding = [c for c in chunks if gap_id in c.taxonomy_ids]
                self.assertTrue(
                    grounding, f"{code} grounds no chunk for {gap_id}"
                )
                self.assertTrue(
                    any(c.speakable for c in grounding),
                    f"{code} grounds {gap_id} but no chunk is speakable",
                )
                for chunk in grounding:
                    with self.subTest(chunk=chunk.chunk_id):
                        self.assertEqual(chunk.verification_status, md.VERIFIED)
                        self.assertIn("GAP", chunk.categories)

    def test_a_chunk_matching_no_entry_is_still_unverified(self) -> None:
        # The inversion above must not become "everything in these articles
        # is speakable now". A chunk that matches neither an A-G rule nor a
        # Category H rule is still unevidenced, and `docs/06` §4.5 still
        # keeps it out of the speakable store.
        for code in self.GUARDED_ARTICLES:
            for chunk in chunk_source(md.SOURCES[code]):
                if chunk.taxonomy_ids:
                    continue
                with self.subTest(chunk=chunk.chunk_id):
                    self.assertEqual(chunk.verification_status, md.UNVERIFIED)
                    self.assertFalse(chunk.speakable)

    def test_pwr_02_is_now_grounded(self) -> None:
        self.assertEqual(md.TAXONOMY_STATUS["PWR-02"], md.CORRECTED)
        speakable = [
            c
            for c in chunk_source(md.SOURCES["H:overheating"])
            if c.speakable and "PWR-02" in c.taxonomy_ids
        ]
        self.assertTrue(
            speakable,
            "PWR-02 was promoted but H:overheating grounds no speakable chunk",
        )

    def test_firmware_facet_and_tier_hold_across_the_whole_corpus(self) -> None:
        for source in md.SOURCES.values():
            for chunk in chunk_source(source):
                with self.subTest(chunk=chunk.chunk_id):
                    self.assertEqual(chunk.tier, md.TIER)
                    self.assertEqual(
                        chunk.firmware_applicability, {"version": "unknown"}
                    )
                    self.assertEqual(md.contains_firmware_version(chunk.text), [])


if __name__ == "__main__":
    unittest.main()
