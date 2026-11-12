"""Tests for step 2: the compiled knowledge packs."""
import json

import pytest

from knowledge import factcheck

REGISTRY = json.loads((factcheck.HERE / "registry.json").read_text(encoding="utf-8"))
PACK_NAMES = list(REGISTRY["models"]) + ["general", "identify"]


@pytest.mark.parametrize("name", PACK_NAMES)
def test_pack_passes_factcheck(name):
    rep = factcheck.check(name)
    assert not rep.unsupported_numbers, f"numbers not in sources: {rep.unsupported_numbers}"
    assert not rep.firmware_versions, f"firmware versions stated: {rep.firmware_versions}"
    assert not rep.bad_citations, f"citations to unknown sources: {rep.bad_citations}"
    assert not rep.missing_sections, f"missing sections: {rep.missing_sections}"
    assert rep.citations >= 20, "pack is barely cited"


@pytest.mark.parametrize("model", list(REGISTRY["models"]))
def test_model_pack_has_procedures_and_playbook(model):
    pack = (factcheck.PACKS / f"{model}.md").read_text(encoding="utf-8")
    playbook = pack.split("## Troubleshooting playbook", 1)[1]
    assert playbook.count("### ") >= 8, "playbook covers too few symptoms"
    assert "DESTRUCTIVE" in pack, "destructive steps are not marked"


@pytest.mark.parametrize("name", PACK_NAMES)
def test_pack_has_no_obfuscated_email_placeholder(name):
    assert "[email protected]" not in (factcheck.PACKS / f"{name}.md").read_text(encoding="utf-8")


def test_general_pack_states_the_real_support_address():
    assert "help@rovedashcam.com" in (factcheck.PACKS / "general.md").read_text(encoding="utf-8")


def test_packs_fit_in_context():
    # Largest model pack + general + identify must stay well inside one prompt.
    sizes = {n: len((factcheck.PACKS / f"{n}.md").read_text(encoding="utf-8")) for n in PACK_NAMES}
    biggest = max(sizes[m] for m in REGISTRY["models"])
    assert (biggest + sizes["general"] + sizes["identify"]) / 4 < 40_000  # ~tokens


def test_checker_catches_an_invented_number(tmp_path, monkeypatch):
    (tmp_path / "R3.md").write_text(
        (factcheck.PACKS / "R3.md").read_text(encoding="utf-8").replace(
            "## Key facts\n",
            "## Key facts\n- Wi-Fi: 7.3GHz band, 999GB max, works within 2 meters [manual: r3-manual-website-files]\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(factcheck, "PACKS", tmp_path)
    unsupported = factcheck.check("R3").unsupported_numbers
    assert {"7.3GHz", "999GB", "2 meters"} <= set(unsupported)


def test_unit_synonyms_match():
    assert factcheck.norm("10 feet") == factcheck.norm("10ft")
    assert factcheck.norm("1 minute") == factcheck.norm("1-min")
