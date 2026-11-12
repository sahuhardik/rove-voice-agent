"""Tests for step 1: the cleaned source text."""
import json
from collections import Counter
from pathlib import Path

import pytest

from knowledge import build_text as bt

CLEAN = bt.OUT
REGISTRY = json.loads((bt.HERE / "registry.json").read_text(encoding="utf-8"))
NAMES = list(REGISTRY["models"]) + ["general"]


def test_ligature_repair_uses_corpus_words():
    vocab = Counter({"settings": 5, "button": 3, "battery": 2, "connecting": 1})
    text, fixed, _ = bt.repair_ligatures("Se�ngs, bu�on, Ba�ery, Connec�Ng", vocab)
    assert text == "Settings, button, Battery, Connecting"
    assert fixed == 4


def test_boilerplate_strip_removes_only_the_line():
    text = "Manualslib.com - The Global Manuals Library\nREAL CONTENT\nmore content"
    assert bt.strip_boilerplate(text) == "REAL CONTENT\nmore content"


@pytest.mark.parametrize("name", NAMES)
def test_clean_file_exists_and_has_content(name):
    path = CLEAN / f"{name}.txt"
    assert path.exists(), "run python -m knowledge.build_text"
    text = path.read_text(encoding="utf-8")
    # Every source contributes real text; the smallest real manual is ~10k chars.
    assert len(text) > 8000, f"{name} is suspiciously short ({len(text)} chars)"
    assert "�" not in text, "unrepaired ligature damage"
    assert "Manualslib.com" not in text and "Are you at least 18" not in text


@pytest.mark.parametrize("model", list(REGISTRY["models"]))
def test_every_registry_source_is_present(model):
    text = (CLEAN / f"{model}.txt").read_text(encoding="utf-8")
    for rel in REGISTRY["models"][model]["sources"]:
        assert f"SOURCE: {rel}" in text
        assert (bt.ROOT / rel).exists()


def test_cloudflare_obfuscated_emails_are_decoded():
    # Found by the groundedness audit: the support address read "[email protected]" in the
    # sources and packs, so the agent invented one. 17 Help Center pages use this obfuscation.
    from bs4 import BeautifulSoup

    assert bt.decode_cfemail("056d60697545776a73606164766d6664682b666a68") == "help@rovedashcam.com"
    soup = BeautifulSoup('<p>Mail <a class="__cf_email__" data-cfemail="056d60697545776a73606164766d6664682b666a68">'
                         '[email&#160;protected]</a> now</p>', "html.parser")
    assert bt.reveal_emails(soup) == 1
    assert "help@rovedashcam.com" in soup.get_text() and "protected" not in soup.get_text()


@pytest.mark.parametrize("name", NAMES)
def test_no_obfuscated_email_placeholder_in_clean_text(name):
    text = (CLEAN / f"{name}.txt").read_text(encoding="utf-8")
    assert "[email protected]" not in text and "[email\xa0protected]" not in text


def test_support_address_is_in_the_general_sources():
    assert "help@rovedashcam.com" in (CLEAN / "general.txt").read_text(encoding="utf-8")


def test_known_facts_survive_cleaning():
    usb_c = (CLEAN / "R2-4K-USB-C.txt").read_text(encoding="utf-8").lower()
    assert "supercapacitor" in usb_c
    general = (CLEAN / "general.txt").read_text(encoding="utf-8")
    assert "Memory Card Too Slow" in general  # cp1252 quotes decoded, not mangled
    assert "U3" in general
