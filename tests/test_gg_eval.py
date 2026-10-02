"""Unit tests for the GG-recall eval (no network / no Claude calls).

Covers the three places where a bug would silently corrupt the measurement:
the XML parse, the Satz splitter (a wrong split becomes wrong ground truth),
and the verdict ladder.
"""

import json

import pytest

from eval.gg import dataset, fetch, score
from eval.gg.normalize import (
    find_articles,
    is_abstention,
    normalize,
    similarity,
    split_saetze,
    strip_envelope,
    token_f1,
)

GG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<dokumente doknr="TEST" builddate="20260101000000">
 <norm doknr="TEST0"><metadaten><jurabk>GG</jurabk>
   <standangabe><standtyp>Stand</standtyp>
   <standkommentar>Zuletzt geändert durch Art. 1 G v. 22.3.2025</standkommentar>
   </standangabe></metadaten></norm>
 <norm doknr="TESTG1"><metadaten><jurabk>GG</jurabk><gliederungseinheit>
   <gliederungsbez>I.</gliederungsbez>
   <gliederungstitel>Die Grundrechte</gliederungstitel>
   </gliederungseinheit></metadaten>
   <textdaten><text format="XML"><Content><P/></Content></text></textdaten></norm>
 <norm doknr="TESTE1"><metadaten><jurabk>GG</jurabk><enbez>Eingangsformel</enbez></metadaten>
   <textdaten><text format="XML"><Content><P>Der Parlamentarische Rat …</P></Content></text></textdaten></norm>
 <norm doknr="TESTA1"><metadaten><jurabk>GG</jurabk><enbez>Art 1</enbez></metadaten>
   <textdaten><text format="XML"><Content>
     <P>(1) Die Würde des Menschen ist unantastbar. Sie zu achten und zu schützen ist Verpflichtung aller staatlichen Gewalt.</P>
     <P>(2) Das Deutsche Volk bekennt sich zu unverletzlichen Menschenrechten.</P>
   </Content></text></textdaten></norm>
 <norm doknr="TESTA2"><metadaten><jurabk>GG</jurabk><enbez>Art 12a</enbez></metadaten>
   <textdaten><text format="XML"><Content>
     <P>(1) Männer können vom vollendeten achtzehnten Lebensjahr an zum Dienst in den Streitkräften, im Bundesgrenzschutz oder in einem Zivilschutzverband verpflichtet werden.</P>
   </Content></text></textdaten></norm>
 <norm doknr="TESTA3"><metadaten><jurabk>GG</jurabk><enbez>Art 106</enbez></metadaten>
   <textdaten><text format="XML"><Content>
     <P>(1) Der Ertrag steht dem Bund zu:
       <DL Type="arabic"><DT>1.</DT><DD><LA>die Zölle,</LA></DD>
       <DT>2.</DT><DD><LA>die Verbrauchsteuern.</LA></DD></DL></P>
   </Content></text></textdaten></norm>
 <norm doknr="TESTA5"><metadaten><jurabk>GG</jurabk><enbez>Art 56</enbez></metadaten>
   <textdaten><text format="XML"><Content>
     <P>Der Bundespräsident leistet folgenden Eid: <DL Type="arabic"><DT/><DD><LA>"Ich schwöre, daß ich meine Kraft dem Wohle des Volkes widmen werde."</LA></DD></DL>Der Eid kann auch ohne religiöse Beteuerung geleistet werden.</P>
   </Content></text></textdaten></norm>
 <norm doknr="TESTA4"><metadaten><jurabk>GG</jurabk><enbez>Art 49</enbez></metadaten>
   <textdaten><text format="XML"><Content><P/></Content></text></textdaten></norm>
</dokumente>
"""


@pytest.fixture
def gg():
    return fetch.parse_gg(GG_XML.encode("utf-8"))


# --- parsing ----------------------------------------------------------------


def test_parse_keeps_only_articles_with_text(gg):
    numbers = [a["artikel"] for a in gg["articles"]]
    assert numbers == ["1", "12a", "106", "56"]  # Eingangsformel and repealed Art 49 dropped


def test_parse_strips_absatz_marker_and_records_stand(gg):
    art1 = gg["articles"][0]
    assert art1["abschnitt"] == "I."
    assert art1["abschnitt_titel"] == "Die Grundrechte"
    assert art1["absaetze"][0]["nr"] == "1"
    assert art1["absaetze"][0]["numbered"] is True
    assert art1["absaetze"][0]["text"].startswith("Die Würde des Menschen")
    assert "22.3.2025" in gg["stand"]


def test_parse_keeps_a_space_at_element_boundaries(gg):
    """Art. 56 closes a <DL> and continues mid-Absatz with no whitespace.

    Concatenating the text nodes blindly produced `... helfe."Der Eid kann`,
    which silently corrupts the ground truth rather than crashing.
    """
    text = next(a for a in gg["articles"] if a["artikel"] == "56")["absaetze"][0]["text"]
    assert 'werde." Der Eid kann' in text
    assert "  " not in text


def test_parse_does_not_split_words_at_inline_markup():
    xml = (
        '<dokumente><norm><metadaten><jurabk>GG</jurabk><enbez>Art 1</enbez>'
        "</metadaten><textdaten><text><Content>"
        "<P>Das <SP>Grundgesetz</SP> gilt fuer das gesamte Deutsche Volk und "
        "bindet jede Gewalt.</P></Content></text></textdaten></norm></dokumente>"
    )
    article = fetch.parse_gg(xml.encode("utf-8"))["articles"][0]
    assert article["absaetze"][0]["text"].startswith("Das Grundgesetz gilt")


def test_parse_flattens_lists_and_flags_them(gg):
    absatz = gg["articles"][2]["absaetze"][0]
    assert absatz["has_list"] is True
    assert absatz["saetze"] == []  # never split an Absatz that carries a list
    assert "die Zölle," in absatz["text"]


# --- sentence splitting -----------------------------------------------------


def test_split_saetze_numbers_sentences():
    text = "Die Würde ist unantastbar. Sie zu achten ist Verpflichtung."
    assert split_saetze(text) == [
        "Die Würde ist unantastbar.",
        "Sie zu achten ist Verpflichtung.",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Verpflichtungen nach Absatz 3 nur nach Maßgabe des Artikels 80a Abs. 1 begründet.",
        "Das Gesetz tritt am 1. Januar 2026 in Kraft.",
        "Es gilt Nr. 4 entsprechend.",
        "Vgl. die Regelung in Satz 2.",
    ],
)
def test_split_saetze_does_not_break_on_abbreviations_or_ordinals(text):
    assert split_saetze(text) == [text]


def test_split_saetze_joins_lowercase_continuations():
    assert split_saetze("Der Bund kann handeln. sofern nötig.") == [
        "Der Bund kann handeln. sofern nötig."
    ]


# --- normalization ----------------------------------------------------------


def test_normalize_folds_old_orthography_and_typography():
    assert normalize("daß muß Bewußtsein") == normalize("dass muss Bewusstsein")
    assert normalize("„Wort“ – Text") == normalize('"Wort" - Text')


def test_normalize_keeps_word_order_a_real_difference():
    right = "Sie zu achten und zu schützen"
    wrong = "Sie zu schützen und zu achten"
    assert normalize(right) != normalize(wrong)
    assert similarity(right, wrong) < 0.9
    assert token_f1(right, wrong)[2] == 1.0  # bag of words cannot see it


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ANTWORT: Die Würde des Menschen.", "Die Würde des Menschen."),
        ('**Art. 1 Abs. 1 GG:** "(1) Die Würde."', "Die Würde."),
        ("Gerne!\nANTWORT: (2) Das Nähere regelt ein Gesetz.", "Das Nähere regelt ein Gesetz."),
    ],
)
def test_strip_envelope_removes_decoration(raw, expected):
    assert strip_envelope(raw) == expected


def test_is_abstention():
    assert is_abstention("ANTWORT: UNBEKANNT")
    assert is_abstention("ANTWORT: Diese Vorschrift existiert nicht.")
    assert not is_abstention("ANTWORT: Die Würde des Menschen ist unantastbar.")


def test_find_articles():
    assert find_articles("siehe Art. 12a und Artikel 5 GG") == ["12a", "5"]


# --- test-set construction --------------------------------------------------


def test_count_gg_citations_needs_a_gg_marker_nearby(tmp_path):
    (tmp_path / "a.txt").write_text(
        "gestützt auf Artikel 74 Absatz 1 Nummer 1 des Grundgesetzes; "
        "ferner Artikel 3 des Handelsabkommens.",
        encoding="utf-8",
    )
    assert dataset.count_gg_citations(tmp_path) == {"74": 1}


def test_count_gg_citations_is_document_frequency(tmp_path):
    (tmp_path / "a.txt").write_text("Artikel 74 GG. Artikel 74 GG.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Artikel 74 GG.", encoding="utf-8")
    assert dataset.count_gg_citations(tmp_path)["74"] == 2


def test_traps_point_past_the_last_absatz(gg):
    traps = dataset._nonexistent_items(gg, {})
    assert [t["citation"] for t in traps] == [
        "Artikel 1 Absatz 3 des Grundgesetzes"  # Art 1 in the fixture stops at (2)
    ]
    assert traps[0]["expected"] == "UNBEKANNT"


def test_build_testset_is_deterministic(gg):
    weights = {"1": 50, "12a": 3}
    first = dataset.build_testset(gg, weights, zitat_per_stratum=5)
    second = dataset.build_testset(gg, weights, zitat_per_stratum=5)
    assert [i["id"] for i in first] == [i["id"] for i in second]
    strata = {i["artikel"]: i["stratum"] for i in first}
    assert strata["1"] == "hot" and strata["12a"] == "warm"


# --- scoring ----------------------------------------------------------------


def _item(**overrides):
    base = {
        "id": "zitat-1-1",
        "kind": "zitat",
        "unit": "absatz",
        "stratum": "hot",
        "artikel": "1",
        "citation": "Artikel 1 Absatz 1 des Grundgesetzes",
        "corpus_citations": 72,
        "expected": "Die Würde des Menschen ist unantastbar. Sie zu achten und zu schützen ist Verpflichtung aller staatlichen Gewalt.",
    }
    return {**base, **overrides}


def _record(raw="", **overrides):
    return {"id": "zitat-1-1", "kind": "zitat", "raw": raw, "cost_usd": 0.0, **overrides}


@pytest.mark.parametrize(
    "raw,verdict",
    [
        # verbatim, only decorated
        ('ANTWORT: "Die Würde des Menschen ist unantastbar. Sie zu achten und zu schützen ist Verpflichtung aller staatlichen Gewalt."', score.EXACT),
        # one word swapped in — typo territory
        ("ANTWORT: Die Würde des Menschen ist unantastbar. Sie zu achten und zu schützen ist die Verpflichtung aller staatlichen Gewalt.", score.NEAR),
        # the real Haiku failure: two verbs transposed
        ("ANTWORT: Die Würde des Menschen ist unantastbar. Sie zu schützen und zu achten ist Verpflichtung aller staatlichen Gewalt.", score.PARTIAL),
        # a different citation entirely
        ("ANTWORT: Jeder hat das Recht auf die freie Entfaltung seiner Persönlichkeit.", score.WRONG),
        ("ANTWORT: UNBEKANNT", score.ABSTAINED),
    ],
)
def test_judge_zitat_verdicts(raw, verdict):
    assert score.judge(_item(), _record(raw))["verdict"] == verdict


def test_judge_reports_cli_errors_separately():
    result = score.judge(_item(), _record(error="timeout after 180s"))
    assert result["verdict"] == score.ERROR


def test_judge_reverse_needs_the_right_article():
    item = _item(kind="reverse", expected="12a", id="reverse-12a-1")
    assert score.judge(item, _record("ANTWORT: Artikel 12a"))["verdict"] == score.EXACT
    assert score.judge(item, _record("ANTWORT: Artikel 12"))["verdict"] == score.WRONG


def test_judge_trap_rewards_abstention_and_punishes_invention():
    item = _item(kind="nonexistent", expected="UNBEKANNT", id="nonexistent-1-3")
    assert score.judge(item, _record("ANTWORT: UNBEKANNT"))["verdict"] == score.EXACT
    invented = _record("ANTWORT: Die nachfolgenden Grundrechte binden alle Gewalt.")
    assert score.judge(item, invented)["verdict"] == score.WRONG


def test_rates_exclude_cli_errors_from_the_denominator():
    results = [
        {"verdict": score.EXACT},
        {"verdict": score.WRONG},
        {"verdict": score.ERROR},
    ]
    rates = score._rates(results)
    assert rates["n"] == 3 and rates["n_scored"] == 2
    assert rates["exact_rate"] == 0.5
    assert rates["hallucination_rate"] == 0.5


def test_score_report_is_json_serialisable(gg):
    items = dataset.build_testset(gg, {"1": 50}, zitat_per_stratum=5)
    records = [_record(raw="ANTWORT: UNBEKANNT", id=i["id"]) for i in items]
    report = score.score(items, records)
    assert report["overall"]["n_scored"] == len(items)
    json.dumps(report)  # must not raise
    from eval.gg import report as gg_report
    page = gg_report.render(report, "test")
    # The page has to explain itself: verdicts, question types, what is measured.
    assert "Grundgesetz recall" in page
    assert all(kind in page for kind in ("zitat", "reverse", "nonexistent"))
    assert "quoted a different citation" in page


def test_stratified_slice_stays_representative():
    from eval.gg.run import stratified_slice

    items = [
        {"id": f"{kind}-{stratum}-{n}", "kind": kind, "stratum": stratum}
        for kind in ("nonexistent", "reverse", "zitat")
        for stratum in ("cold", "hot", "warm")
        for n in range(10)
    ]
    picked = stratified_slice(items, 9)
    assert len(picked) == 9
    assert {i["kind"] for i in picked} == {"nonexistent", "reverse", "zitat"}
    assert {i["stratum"] for i in picked} == {"cold", "hot", "warm"}


# --- citation identity ------------------------------------------------------

GG_UNITS = [
    ("Art 9 Abs 3 Satz 1", "Das Recht, zur Wahrung und Förderung der Arbeits- und Wirtschaftsbedingungen Vereinigungen zu bilden, ist für jedermann gewährleistet."),
    ("Art 9 Abs 3 Satz 2", "Abreden, die dieses Recht einschränken oder zu behindern suchen, sind nichtig, hierauf gerichtete Maßnahmen sind rechtswidrig."),
]


def test_best_match_names_the_citation_that_was_actually_quoted():
    """`teilweise`/`falsch` is a word-overlap threshold, blind to citation identity."""
    asked_for = GG_UNITS[0][1]
    answered = GG_UNITS[1][1]
    assert score.best_match(answered, asked_for, GG_UNITS) == "Art 9 Abs 3 Satz 2"


def test_best_match_is_none_when_the_right_citation_was_merely_misquoted():
    asked_for = GG_UNITS[0][1]
    sloppy = "Das Recht, zur Förderung der Arbeitsbedingungen Vereinigungen zu bilden, ist für jedermann gewährleistet."
    assert score.best_match(sloppy, asked_for, GG_UNITS) is None


def test_misattribution_rate_counts_only_verified_wrong_norms():
    results = [
        {"verdict": score.WRONG, "misattributed_to": "Art 94 Abs 3"},
        {"verdict": score.PARTIAL, "misattributed_to": None},
        {"verdict": score.EXACT},
    ]
    assert score._rates(results)["misattribution_rate"] == round(1 / 3, 4)


def test_best_match_ignores_a_truncated_quote_of_the_right_citation():
    """The unit list holds an Absatz and its own Sätze; a partial quote is not
    a different citation."""
    absatz = GG_UNITS[0][1] + " " + GG_UNITS[1][1]
    units = [("Art 9 Abs 3", absatz), *GG_UNITS]
    # answered only the first sentence of the Absatz it was asked for
    assert score.best_match(GG_UNITS[0][1], absatz, units) is None
