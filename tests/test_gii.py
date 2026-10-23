"""Unit tests for the GII source module (offline: laws are built in the test)."""

from backend import config
from backend.gii import index, law

from tests.gii_fixtures import EGBGB, SVG_2025, TEILLISTE, WPFLG, write_zip


def test_a_teilliste_yields_slug_abbreviation_and_title():
    entries = index.parse(TEILLISTE)
    assert entries[0] == index.Entry("wehrpflg", "WPflG", "Wehrpflichtgesetz")
    assert entries[1].titel == "Gesetz über die Versorgung der früheren Soldatinnen"


def test_the_index_is_read_from_gii_once_and_then_from_its_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GII_DIR", str(tmp_path))
    pages = []

    def fetch(page):
        pages.append(page)
        return TEILLISTE.encode("iso-8859-1", "xmlcharrefreplace")

    first = index.load(fetch=fetch)
    assert len(pages) == len(index.PAGES)
    assert index.load(fetch=fetch) == first and len(pages) == len(index.PAGES)


def test_candidates_match_abbreviations_across_year_and_numbering_and_titles_across_case():
    entries = index.parse(TEILLISTE)
    assert index.candidates(entries, "SVG", None) == ["svg_2025", "svg_alt"]
    assert index.candidates(entries, None, "Wehrpflichtgesetzes") == ["wehrpflg"]
    assert index.abk_key("SGB V") == index.abk_key("SGB 5")


def test_unit_ids_are_gii_page_names():
    assert law.unit_id("§ 8a") == "__8a"
    assert law.unit_id("Art. 5") == "art_5"
    assert law.unit_id("Art 229 § 1") == "art_229__1"
    assert law.unit_id("Anlage") == "anlage"
    assert law.unit_id("Anlage 2 (zu § 3)") == "anlage_2"


def test_a_law_carries_its_citations_stand_and_units_with_plain_text(tmp_path):
    wpflg = law.load("wehrpflg", write_zip(tmp_path, "wehrpflg", WPFLG))
    assert wpflg.amtabk == "WPflG" and wpflg.langue == "Wehrpflichtgesetz"
    assert wpflg.citations == {(1956, "651"), (2011, "1730")}  # Ausfertigung + Neufassung
    assert wpflg.stand.startswith("zuletzt geändert durch")
    assert [u.id for u in wpflg.units] == ["__2", "__3", "__8a", "__9", "__20b", "__45"]
    assert wpflg.unit("§ 3").text == "(1) Die Wehrpflicht.\n1. eins,\n2. zwei."
    assert law.load("svg_2025", write_zip(tmp_path, "svg_2025", SVG_2025)).citations == {
        (2021, "3932"), (2021, "3958")}


def test_ranges_expand_through_the_laws_own_order(tmp_path):
    wpflg = law.load("wehrpflg", write_zip(tmp_path, "wehrpflg", WPFLG))
    assert [u.id for u in wpflg.expand("§§ 8a bis 20b")] == ["__8a", "__9", "__20b"]
    assert wpflg.expand("§§ 8a bis 99") == []
    assert wpflg.expand("§ 7") == []
    egbgb = law.load("bgbeg", write_zip(tmp_path, "bgbeg", EGBGB))
    assert [u.id for u in egbgb.expand("Art. 229")] == ["art_229__1", "art_229__2"]


def test_draft_citations_take_the_year_from_the_date_or_the_gazette():
    assert law.draft_citations(
        "in der Fassung der Bekanntmachung vom 15. August 2011 (BGBl. I S. 1730)") == {
        (2011, "1730")}
    assert law.draft_citations("vom 20. August 2021 (BGBl. I S. 3932, 3958)") == {
        (2021, "3932"), (2021, "3958")}
    assert law.draft_citations("vom 7. Juli 2025 (BGBl. 2025 I Nr. 131)") == {(2025, "Nr. 131")}
    assert law.draft_citations("BGBl. I S. 1730") == set()  # no year, no citation
    assert law.draft_citations(None) == set()
