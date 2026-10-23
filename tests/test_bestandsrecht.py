"""Unit tests for the Bestandsrecht selection (offline, no Claude: the model call is faked)."""

import json
from dataclasses import replace

from backend import bestandsrecht, config
from backend.bestandsrecht import model as bestandsrecht_model
from backend.bestandsrecht.reference import Reference, Resolved
from backend.bestandsrecht.resolve import Resolution, resolve
from backend.gii import index
from backend.llm import structured
from backend.text import squash
from tests import gii_fixtures
from tests.gii_fixtures import TEILLISTE, zip_source

# Excerpt of Drucksache 21/1853 as pypdf extracts it: Artikel 1 with the page
# break inside the new § 2 and the misplaced opening quote, plus the opening of
# Artikel 7 and a Stammgesetz.
DRAFT = """\
Entwurf eines Gesetzes zur Modernisierung des Wehrdienstes
Vorblatt: Die §§ 99 und 100 des Wehrpflichtgesetzes stehen nicht im Wortlaut.
Der Bundestag hat mit Zustimmung des Bundesrates das folgende Gesetz beschlossen:
Artikel 1
Änderung des Wehrpflichtgesetzes
Das Wehrpflichtgesetz in der Fassung der Bekanntmachung vom 15. August 2011 (BGBl. I S. 1730), das
zuletzt durch Artikel 5 des Gesetzes vom 27. Februar 2025 (BGBl. 2025 I Nr. 72) geändert worden ist, wird wie
folgt geändert:
1. Die Inhaltsübersicht wird wie folgt geändert:
a) Die Angabe zu § 2 wird durch die folgende Angabe ersetzt:
„§ 2 Anwendung dieses Gesetzes
§ 2a Anordnung der Einberufung zum Grundwehrdienst; Verordnungsermächtigung“.
b) Die Angabe zu § 53 wird gestrichen.
2. § 2 wird durch die folgenden §§ 2 und 2a ersetzt:
§ 2„
Anwendung dieses Gesetzes
(1) Die nachfolgenden Vorschriften gelten nach Maßgabe der folgenden Absätze.
(2) Die §§ 3 bis 52 gelten
1. im Spannungs- oder Verteidigungsfall,
2. im Falle der Geltung einer Rechtsverordnung nach § 2a.
Anlage 1
Drucksache 21/1853 – 10 – Deutscher Bundestag – 21. Wahlperiode


(3) Außerhalb des Spannungs- oder Verteidigungsfalls und solange keine Rechtsverordnung nach § 2a
gilt, gelten die §§ 3, 8a bis 20b, 25, 32 bis 35, 44 und 45 mit der Maßgabe, dass die Vorschriften über die
Musterung erst ab dem 1. Juli 2027 anzuwenden sind.
§ 2a
Anordnung der Einberufung zum Grundwehrdienst; Verordnungsermächtigung
Die Bundesregierung wird ermächtigt, durch Rechtsverordnung anzuordnen, dass ungediente
Wehrpflichtige zum Grundwehrdienst nach § 5 einberufen werden.“
3. In § 6 Absatz 2 wird die Angabe „Die Gesamtdauer der Wehrübungen“ durch die Angabe „§ 77“ ersetzt.
4. Nach § 7 wird der folgende § 7a eingefügt:
„§ 7a
Wehrdienstberatung
Die Beratung umfasst die Leistungen nach § 7 Absatz 1 des Unterhaltssicherungsgesetzes.“
Artikel 7
Änderung des Soldatenversorgungsgesetzes
Das Soldatenversorgungsgesetz vom 20. August 2021 (BGBl. I S. 3932, 3958), das zuletzt durch Artikel 9
des Gesetzes vom 27. Februar 2025 (BGBl. 2025 I Nr. 72) geändert worden ist, wird wie folgt geändert:
1. § 16 wird wie folgt geändert:
a) Absatz 1 wird durch den folgenden Absatz 1 ersetzt:
(1) „ Die Leistung bemisst sich nach § 9 Absatz 3.“
Artikel 8
Wehrpflichtsoldgesetz
(WPflSG)
§ 3
Anwendung von Vorschriften des Bundesbesoldungsgesetzes
Die §§ 9 und 9a des Bundesbesoldungsgesetzes gelten entsprechend. § 4 dieses Gesetzes bleibt unberührt.
Artikel 9
Inkrafttreten
Dieses Gesetz tritt am 1. Januar 2026 in Kraft.
Begründung
A. Allgemeiner Teil
Nach § 99 des Soldatengesetzes wird nichts geändert.
"""


def test_wortlaut_runs_from_the_enacting_clause_to_the_begruendung_without_furniture():
    text = bestandsrecht.wortlaut(DRAFT)
    assert text.lstrip().startswith("Artikel 1")
    assert "Begründung" not in text and "Vorblatt" not in text
    assert "Drucksache 21/1853" not in text and "Anlage 1" not in text


def _fake_call(selection, seen=None):
    async def fake(user_message, model=None, effort=None, on_message=None):
        if seen is not None:
            seen.append(user_message)
        return structured.StructuredRun(selection, None, [], None, None)
    return fake


SELECTION = bestandsrecht_model.Selection(gesetze=[
    bestandsrecht_model.SelectedLaw(
        gesetz="Wehrpflichtgesetz", fundstelle="BGBl. I S. 1730", paragraphen=[
            {"paragraph": "§ 2", "rolle": "geaendert", "von": "§ 1",
             "beleg": "§ 2 wird durch die folgenden §§ 2 und 2a ersetzt"},
            {"paragraph": "§ 45", "rolle": "verwiesen", "von": "§ 2",
             "beleg": "§§ 3, 8a bis 20b, 25, 32 bis 35, 44 und 45"},
            {"paragraph": "§ 99", "rolle": "verwiesen", "von": "§ 2",
             "beleg": "die §§ 99 und 100 des Wehrpflichtgesetzes"}]),
    bestandsrecht_model.SelectedLaw(
        gesetz="Wehrpflichtsoldgesetz", abk="WPflSG", neu=True, paragraphen=[
            {"paragraph": "§ 3", "rolle": "geaendert", "beleg": "§ 3"}]),
])


def test_the_model_selector_reads_only_the_wortlaut(monkeypatch):
    seen = []
    monkeypatch.setattr(bestandsrecht_model, "run_query", _fake_call(SELECTION, seen))
    bestandsrecht.select("Wehrdienst-Modernisierungsgesetz", DRAFT)
    (message,) = seen
    assert "<titel>Wehrdienst-Modernisierungsgesetz</titel>" in message
    assert "§§ 3, 8a bis 20b" in message
    assert "Vorblatt" not in message and "Begründung" not in message


def test_the_model_selection_becomes_references_and_unfounded_entries_are_flagged(monkeypatch):
    monkeypatch.setattr(bestandsrecht_model, "run_query", _fake_call(SELECTION))
    selected = bestandsrecht.select("", DRAFT)
    refs = selected.references
    assert [(r.gesetz, r.paragraph, r.rolle, r.von) for r in refs] == [
        ("Wehrpflichtgesetz", "§ 2", "geaendert", None),  # an amended § has no citing §
        ("Wehrpflichtgesetz", "§ 45", "verwiesen", "§ 2"),
        ("Wehrpflichtgesetz", "§ 99", "verwiesen", "§ 2"),
    ]  # the new law has nothing to fetch
    # § 99's beleg stands only outside the Wortlaut: kept, but flagged.
    assert [r.paragraph for r in selected.unbelegt] == ["§ 99"]
    assert all(r.fundstelle == "BGBl. I S. 1730" for r in refs)
    assert selected.call["prompt_version"] == config.BESTANDSRECHT_PROMPT_VERSION


def test_the_selection_schema_has_no_root_title():
    assert "title" not in bestandsrecht_model._output_schema()


def _ref(gesetz, paragraph, abk=None, fundstelle=None, rolle="verwiesen"):
    return Reference(gesetz=gesetz, paragraph=paragraph, rolle=rolle, beleg=paragraph,
                     abk=abk, fundstelle=fundstelle)


def test_the_eingangsformel_citation_decides_between_laws_of_one_abbreviation(tmp_path):
    refs = [_ref("Soldatenversorgungsgesetz", "§ 16", "SVG",
                 "vom 20. August 2021 (BGBl. I S. 3932, 3958)")]
    res = resolve(refs, index.parse(TEILLISTE), zip_source(tmp_path))
    assert res.ids == ["svg_2025/__16"] and not res.unresolved


def test_without_a_citation_two_laws_of_one_abbreviation_stay_unresolved(tmp_path):
    res = resolve([_ref("Soldatenversorgung", "§ 16", "SVG")], index.parse(TEILLISTE),
                  zip_source(tmp_path))
    assert res.ids == [] and [u.reason for u in res.unresolved] == ["ambiguous"]


def test_a_name_resolves_through_the_kurztitel_when_it_is_unique(tmp_path):
    entries = index.parse(TEILLISTE) + [index.Entry("svg_2025", "SVG 2025",
                                                    "Soldatenversorgungsgesetz")]
    res = resolve([_ref("Soldatenversorgungsgesetz", "§ 16")], entries, zip_source(tmp_path))
    assert res.ids == ["svg_2025/__16"]


def test_unresolved_references_carry_their_reason(tmp_path):
    entries = index.parse(TEILLISTE) + [index.Entry("weg", "WEG", "Weg")]
    res = resolve([_ref("Wehrpflichtgesetz", "§ 7", "WPflG"),
                   _ref("Unbekanntgesetz", "§ 1", "UnbkG"),
                   _ref("Weg", "§ 1", "WEG")], entries, zip_source(tmp_path))
    assert [(u.reference.gesetz, u.reason) for u in res.unresolved] == [
        ("Wehrpflichtgesetz", "paragraph not in law"), ("Unbekanntgesetz", "no candidate"),
        ("Weg", "download failed: GII weg/xml.zip: HTTP 404")]


def test_a_range_resolves_to_every_unit_and_each_law_is_fetched_once(tmp_path):
    calls = []
    res = resolve([_ref("Wehrpflichtgesetz", "§§ 8a bis 20b", "WPflG"),
                   _ref("Wehrpflichtgesetz", "§ 45", "WPflG")],
                  index.parse(TEILLISTE), zip_source(tmp_path, calls))
    assert res.ids == ["wehrpflg/__8a", "wehrpflg/__9", "wehrpflg/__20b", "wehrpflg/__45"]
    assert calls == ["wehrpflg"]


GII_SELECTION = bestandsrecht_model.Selection(gesetze=[
    bestandsrecht_model.SelectedLaw(
        gesetz="Wehrpflichtgesetz", abk="WPflG",
        fundstelle="in der Fassung der Bekanntmachung vom 15. August 2011 (BGBl. I S. 1730)",
        paragraphen=[
            {"paragraph": "§ 2", "rolle": "geaendert",
             "beleg": "§ 2 wird durch die folgenden §§ 2 und 2a ersetzt"},
            {"paragraph": "§ 45", "rolle": "verwiesen", "von": "§ 2",
             "beleg": "§§ 3, 8a bis 20b, 25, 32 bis 35, 44 und 45"},
            {"paragraph": "§ 25", "rolle": "verwiesen", "von": "§ 2",
             "beleg": "§§ 3, 8a bis 20b, 25, 32 bis 35, 44 und 45"}]),
])


def test_provide_freezes_the_texts_logs_the_selection_and_feeds_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(bestandsrecht_model, "run_query", _fake_call(GII_SELECTION))
    calls, freeze, log = [], tmp_path / "frozen", tmp_path / "run" / "21-1853.json"
    (tmp_path / "zips").mkdir()
    kwargs = {"freeze_dir": freeze, "log": log, "entries": index.parse(TEILLISTE),
              "zip_path": zip_source(tmp_path / "zips", calls)}

    ctx = bestandsrecht.provide("Wehrdienst-Modernisierungsgesetz", DRAFT, **kwargs)
    assert [f.id for f in ctx.fetched] == ["wehrpflg/__2", "wehrpflg/__45"]
    assert ctx.blocks()[0].message() == ("WPflG", "§ 2", "2026-05-06",
                               "§ 2 Anwendung dieses Gesetzes\n(1) Erster Absatz.\n(2) Zweiter.")
    assert (freeze / "wehrpflg" / "__45.json").exists()

    logged = json.loads(log.read_text(encoding="utf-8"))
    assert logged["ids"] == ["wehrpflg/__2", "wehrpflg/__45"]
    assert [(u["paragraph"], u["reason"]) for u in logged["unresolved"]] == [
        ("§ 25", "paragraph not in law")]
    assert logged["fetched"][1]["sha256"] == ctx.fetched[1].sha256
    assert "text" not in logged["fetched"][0]
    assert logged["call"]["model"] == config.BESTANDSRECHT_MODEL

    # GII changes; the bill keeps the text it first read.
    monkeypatch.setitem(gii_fixtures.LAWS, "wehrpflg",
                        gii_fixtures.WPFLG.replace("Erster Absatz.", "Neu."))
    again = bestandsrecht.provide("Wehrdienst-Modernisierungsgesetz", DRAFT, **kwargs)
    assert again.fetched[0].text == ctx.fetched[0].text


def _context(*units):
    """A context of ``(id, rolle, text)`` units, without GII."""
    resolved = [Resolved(i, f"§ {i.split('__')[1]}", _ref("Wehrpflichtgesetz", "§ x", rolle=rolle))
                for i, rolle, _ in units]
    fetched = [bestandsrecht.Fetched(i, "WPflG", f"§ {i.split('__')[1]}", "", None,
                                     "20260506120000", text, "h" + i) for i, _, text in units]
    return bestandsrecht.Context(bestandsrecht.Selected([], [], {"model": "m", "cost_usd": 0.01}),
                                 Resolution(resolved, [], {}), fetched)


def test_a_unit_amended_by_any_reference_counts_as_amended():
    ctx = _context(("wehrpflg/__2", "verwiesen", "a"), ("wehrpflg/__2", "geaendert", "a"),
                   ("wehrpflg/__3", "verwiesen", "b"))
    assert ctx.rolle("wehrpflg/__2") == "geaendert"
    assert ctx.rolle("wehrpflg/__3") == "verwiesen"


def test_fit_feeds_all_then_the_amended_then_nothing():
    ctx = _context(("wehrpflg/__2", "geaendert", "x" * 10), ("wehrpflg/__3", "verwiesen", "y" * 20))
    size = {b.key: len(b.text) for b in ctx.blocks()}
    everything, amended = sum(size.values()), size["wehrpflg/__2"]

    full = bestandsrecht.fit(ctx, everything)
    assert (full.decision, full.fed, full.left_out) == (
        "vollstaendig", ["wehrpflg/__2", "wehrpflg/__3"], [])
    assert full.chars_fed == everything

    reduced = bestandsrecht.fit(ctx, everything - 1)
    assert (reduced.decision, reduced.fed, reduced.left_out) == (
        "nur_geaendert", ["wehrpflg/__2"], ["wehrpflg/__3"])
    assert (reduced.chars_all, reduced.chars_geaendert, reduced.chars_fed) == (
        everything, amended, amended)

    dropped = bestandsrecht.fit(ctx, amended - 1)
    assert (dropped.decision, dropped.fed, dropped.chars_fed) == ("entfallen", [], 0)
    assert dropped.left_out == ["wehrpflg/__2", "wehrpflg/__3"]

    assert bestandsrecht.fit(_context(), 100).decision == "keine"


def test_over_budget_without_amended_units_feeds_nothing():
    ctx = _context(("wehrpflg/__3", "verwiesen", "y" * 20))
    assert bestandsrecht.fit(ctx, 5).decision == "entfallen"


def test_the_fed_blocks_and_documents_follow_the_fit():
    ctx = _context(("wehrpflg/__2", "geaendert", "x" * 10), ("wehrpflg/__3", "verwiesen", "y" * 20))
    ctx = replace(ctx, fit=bestandsrecht.fit(ctx, 15))
    assert [b[1] for b in ctx.fed()] == ["§ 2"]
    (doc,) = ctx.documents()
    assert doc == {"document_id": "wehrpflg/__2", "typ": "bestandsrecht", "form": "wortlaut",
                   "dokumentnummer": "§ 2 WPflG", "gesetz": "WPflG", "rolle": "geaendert",
                   "stand": None, "builddate": "20260506120000",
                   "pdf_url": "https://www.gesetze-im-internet.de/wehrpflg/__2.html",
                   "pdf_hash": "hwehrpflg/__2", "text_chars": len(ctx.fed()[0][3])}
    summary = ctx.summary()
    assert summary["decision"] == "nur_geaendert"
    assert (summary["fed_count"], summary["left_out_count"]) == (1, 1)
    assert summary["selection"]["cost_usd"] == 0.01 and "fed" not in summary


def test_provide_fits_the_budget_and_logs_the_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(bestandsrecht_model, "run_query", _fake_call(GII_SELECTION))
    (tmp_path / "zips").mkdir()
    log = tmp_path / "run" / "21-1853.json"
    ctx = bestandsrecht.provide("Wehrdienst-Modernisierungsgesetz", DRAFT,
                                freeze_dir=tmp_path / "frozen", log=log,
                                entries=index.parse(TEILLISTE),
                                zip_path=zip_source(tmp_path / "zips"),
                                budget=len("§ 2 Anwendung dieses Gesetzes\n(1) Erster Absatz.\n(2) Zweiter."))
    assert ctx.fit.decision == "nur_geaendert" and ctx.fit.fed == ["wehrpflg/__2"]
    logged = json.loads(log.read_text(encoding="utf-8"))
    assert logged["fit"]["decision"] == "nur_geaendert"
    assert logged["fit"]["left_out"] == ["wehrpflg/__45"]
    assert [f["rolle"] for f in logged["fetched"]] == ["geaendert", "verwiesen"]


def test_the_selection_is_frozen_per_bill_until_the_draft_or_settings_change(tmp_path, monkeypatch):
    calls = []

    def counting(selection):
        fake = _fake_call(selection)

        async def call(*args, **kwargs):
            calls.append(1)
            return await fake(*args, **kwargs)
        return call

    monkeypatch.setattr(bestandsrecht_model, "run_query", counting(GII_SELECTION))
    (tmp_path / "zips").mkdir()
    kwargs = {"freeze_dir": tmp_path / "frozen", "entries": index.parse(TEILLISTE),
              "zip_path": zip_source(tmp_path / "zips")}
    first = bestandsrecht.provide("Titel", DRAFT, **kwargs)
    again = bestandsrecht.provide("Titel", DRAFT, **kwargs)
    assert len(calls) == 1
    assert again.selected.references == first.selected.references
    assert again.selected.call["frozen"] is True and "frozen" not in first.selected.call

    # A reused selection is checked against the Wortlaut again, and keeps what fails.
    stored = json.loads((tmp_path / "frozen" / "selection.json").read_text(encoding="utf-8"))
    stored["references"][0]["beleg"] = "steht nirgends im Entwurf"
    (tmp_path / "frozen" / "selection.json").write_text(json.dumps(stored), encoding="utf-8")
    flagged = bestandsrecht.provide("Titel", DRAFT, **kwargs).selected
    assert len(calls) == 1 and len(flagged.references) == len(first.selected.references)
    assert [r.beleg for r in flagged.unbelegt] == ["steht nirgends im Entwurf"]

    bestandsrecht.provide("Titel", DRAFT.replace("§ 6 Absatz 2", "§ 6 Absatz 3"), **kwargs)
    assert len(calls) == 2  # the Wortlaut changed
    bestandsrecht.provide("Titel", DRAFT.replace("§ 6 Absatz 2", "§ 6 Absatz 3"),
                          model_name="claude-other", **kwargs)
    assert len(calls) == 3  # so did the selection model


def test_a_beleg_that_skips_numbering_or_replaced_wording_still_stands_in_the_wortlaut():
    haystack = squash(bestandsrecht.wortlaut(DRAFT))
    # Two lines of one Befehl, without the "a)" between them.
    assert bestandsrecht.in_wortlaut(
        "Die Inhaltsübersicht wird wie folgt geändert: Die Angabe zu § 2 wird", haystack)
    # The replaced wording left out, quotes dropped, a full stop added.
    assert bestandsrecht.in_wortlaut(
        "In § 6 Absatz 2 wird die Angabe Die Gesamtdauer ersetzt.", haystack)
    # Words that stand in the draft, but not in this order or not close together.
    assert not bestandsrecht.in_wortlaut("§ 7a wird durch § 6 ersetzt", haystack)
    assert not bestandsrecht.in_wortlaut("Wehrpflichtgesetzes Inkrafttreten", haystack)
    assert not bestandsrecht.in_wortlaut("die §§ 99 und 100 des Wehrpflichtgesetzes", haystack)
    assert not bestandsrecht.in_wortlaut(" ", haystack)
    # A § in parentheses is still one word with its number.
    assert bestandsrecht.in_wortlaut("(§ 6 Absatz 2 wird", haystack)


def _range_context(n):
    """§ 2 amended, § 3 cited alone, and a cited range of ``n`` units §§ 10 to 10+n-1."""
    rng = _ref("Wehrpflichtgesetz", f"§§ 10 bis {9 + n}")
    single = _ref("Wehrpflichtgesetz", "§ 3")
    amended = _ref("Wehrpflichtgesetz", "§ 2", rolle="geaendert")
    ids = ["wehrpflg/__2", "wehrpflg/__3"] + [f"wehrpflg/__{10 + i}" for i in range(n)]
    resolved = ([Resolved(ids[0], "§ 2", amended), Resolved(ids[1], "§ 3", single)]
                + [Resolved(i, "§ " + i.split("__")[1], rng) for i in ids[2:]]
                + [Resolved("wehrpflg/__10", "§ 10", single)])  # also cited alone
    fetched = [bestandsrecht.Fetched(i, "WPflG", "§ " + i.split("__")[1], f"Titel {i[-2:]}",
                                     None, "20260506", "Wortlaut " * 20, "h" + i) for i in ids]
    return bestandsrecht.Context(bestandsrecht.Selected([], [], {}),
                                 Resolution(resolved, [], {}), fetched)


def test_a_long_cited_range_is_fed_as_its_headings():
    blocks = _range_context(bestandsrecht.RANGE_IN_FULL_MAX + 1).blocks()
    assert [(b.key, b.form) for b in blocks] == [
        ("wehrpflg/__2", "wortlaut"), ("wehrpflg/__3", "wortlaut"),
        ("wehrpflg/__10", "wortlaut"),  # named on its own as well
        ("wehrpflg/§§ 10 bis 15", "ueberschriften")]
    headings = blocks[-1]
    assert headings.rolle == "verwiesen" and len(headings.ids) == 6
    assert headings.message()[:3] == ("WPflG", "§§ 10 bis 15", "2026-05-06")
    assert headings.text.splitlines()[1:3] == ["§ 10 Titel 10", "§ 11 Titel 11"]
    assert "Wortlaut Wortlaut" not in headings.text


def test_a_short_cited_range_and_an_amended_one_stay_in_full():
    blocks = _range_context(bestandsrecht.RANGE_IN_FULL_MAX).blocks()
    assert all(b.form == "wortlaut" for b in blocks) and len(blocks) == 7


def test_a_range_of_headings_counts_as_cited_in_the_fit_and_the_documents():
    ctx = _range_context(8)
    amended = len(ctx.blocks()[0].text)
    ctx = replace(ctx, fit=bestandsrecht.fit(ctx, amended))
    assert ctx.fit.decision == "nur_geaendert" and ctx.fit.fed == ["wehrpflg/__2"]
    ctx = replace(ctx, fit=bestandsrecht.fit(ctx, 10 ** 6))
    headings = ctx.documents()[-1]
    assert headings["document_id"] == "wehrpflg/§§ 10 bis 17"
    assert headings["form"] == "ueberschriften" and headings["rolle"] == "verwiesen"
    assert headings["dokumentnummer"] == "§§ 10 bis 17 WPflG" and len(headings["ids"]) == 8
