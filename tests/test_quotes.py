"""Locating a finding's quote in the page texts of a Drucksache."""

from backend.analysis import quotes

PAGES = [
    "Drucksache 21/1 Artikel 1 Der Antrag ist schrift-\nlich zu stellen.",
    "Die Behörde ent scheidet innerhalb von „drei Monaten“ nach Eingang.",
]


def _docs():
    return [quotes.Document("d1", PAGES)]


def test_locate_names_the_page_and_keeps_the_documents_spelling():
    location = quotes.locate('Die Behörde entscheidet innerhalb von "drei Monaten"', _docs())
    assert location["document_id"] == "d1"
    assert location["page"] == 2
    assert location["match"] == "Die Behörde ent scheidet innerhalb von „drei Monaten“"
    assert location["before"].endswith("schriftlich zu stellen. ")
    assert location["after"] == " nach Eingang."


def test_locate_finds_a_quote_across_a_line_break_hyphen():
    location = quotes.locate("Der Antrag ist schriftlich zu stellen.", _docs())
    assert location["page"] == 1
    assert location["match"] == "Der Antrag ist schriftlich zu stellen."


def test_locate_gives_the_page_the_quote_starts_on():
    location = quotes.locate("schriftlich zu stellen. Die Behörde entscheidet", _docs())
    assert location["page"] == 1


def test_locate_returns_none_for_missing_short_or_absent_quotes():
    assert quotes.locate(None, _docs()) is None
    assert quotes.locate("Artikel 1", _docs()) is None  # too short to point at one place
    assert quotes.locate("Dieser Satz steht nirgends im Entwurf.", _docs()) is None


def test_locate_searches_the_documents_in_order():
    docs = [quotes.Document("d1", PAGES), quotes.Document("d2", ["Ein ganz anderer Satz im Bericht."])]
    assert quotes.locate("Ein ganz anderer Satz im Bericht.", docs)["document_id"] == "d2"


def test_locate_falls_back_to_the_head_of_a_long_quote():
    head = "Die zuständige Behörde kann im Einzelfall Ausnahmen von den Anforderungen zulassen,"
    docs = [quotes.Document("d1", [head + " Drucksache 21/1 – 2 – soweit dies erforderlich ist."])]
    location = quotes.locate(head + " soweit dies erforderlich ist.", docs)
    assert location["page"] == 1
    assert head.startswith(location["match"])


def test_context_is_cut_at_word_boundaries():
    filler = "wort " * 200
    docs = [quotes.Document("d1", [filler + "Die Frist beträgt drei Monate. " + filler])]
    location = quotes.locate("Die Frist beträgt drei Monate.", docs)
    assert location["before"].startswith("…wort ")
    assert location["after"].endswith(" wort…")
    assert len(location["before"]) <= quotes.CONTEXT_CHARS + 1


def test_excerpt_keeps_a_suspended_hyphen():
    docs = [quotes.Document("d1", ["Die Ein- und Ausfuhr von Waren ist genehmi-\ngungspflichtig."])]
    location = quotes.locate("Die Ein- und Ausfuhr von Waren ist genehmigungspflichtig.", docs)
    assert location["match"] == "Die Ein- und Ausfuhr von Waren ist genehmigungspflichtig."
