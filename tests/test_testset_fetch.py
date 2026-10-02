import pytest

from eval.testset.fetch import pdf_url, pins


def test_pdf_url_folders_by_hundreds():
    assert pdf_url("21-17.txt") == "https://dserver.bundestag.de/btd/21/000/2100017.pdf"
    assert pdf_url("16-2712.txt") == "https://dserver.bundestag.de/btd/16/027/1602712.pdf"
    assert pdf_url("18-12086.txt") == "https://dserver.bundestag.de/btd/18/120/1812086.pdf"


def test_pdf_url_rejects_other_names():
    with pytest.raises(ValueError):
        pdf_url("excerpt.txt")


def test_pins_collects_cases_and_manifest():
    cases = [{"text": {"file": "21-17.txt", "sha256": "a"}},
             {"text": {"file": "21-17.txt", "sha256": "a"}}]
    manifest = {"21/16": {"titel": "T", "gesetzentwurf": {"file": "21-16.txt", "sha256": "b"}}}
    assert pins(cases, manifest) == {"21-17.txt": "a", "21-16.txt": "b"}


def test_pins_rejects_conflicting_hashes():
    cases = [{"text": {"file": "21-17.txt", "sha256": "a"}},
             {"text": {"file": "21-17.txt", "sha256": "b"}}]
    with pytest.raises(ValueError):
        pins(cases, {})
