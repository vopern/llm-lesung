"""Unit tests for the shared quote matcher (offline, no Claude)."""

import re

import pytest

from eval import quotecheck

# The normalisation the red-team numbers were measured with, kept here as the
# reference the indexed variant has to agree with.
_REFERENCE_SQUASH_RE = re.compile(r"[\s\-‐-―]+")


def _reference_squash(s: str) -> str:
    s = s.replace("­", "")
    for ch in "„“”»«":
        s = s.replace(ch, '"')
    for ch in "‚‘’":
        s = s.replace(ch, "'")
    return _REFERENCE_SQUASH_RE.sub("", s).lower()


@pytest.mark.parametrize("text", [
    "minde-\nstens 90 Prozent",
    "Re chnung  über\t1.000 €",
    "„Wortlaut“ – mit Gedankenstrich",
    "soft­hyphen",
    "§ 73b Abs. 1 S. 1 Nr. 1 StGB",
    "ÄÖÜ ß Erdoğan",
    "",
])
def test_squash_with_index_agrees_with_squash(text):
    """Two implementations of one normalisation; a drift between them would
    silently mis-locate every reported fragment."""
    squashed, index = quotecheck.squash_with_index(text)
    assert squashed == quotecheck.squash(text) == _reference_squash(text)
    assert len(index) == len(squashed)
    assert all(0 <= i < len(text) for i in index)


def test_squash_with_index_points_at_the_original_characters():
    text = "minde-\nstens 90"
    squashed, index = quotecheck.squash_with_index(text)
    # The fragment recovered through the index keeps the draft's own spelling,
    # hyphen and line break included.
    assert text[index[0]:index[9] + 1] == "minde-\nstens"


def test_longest_run_finds_the_longest_common_substring():
    haystack = quotecheck.squash("Der Unternehmer haftet nicht nach Absatz 1.")
    needle = quotecheck.squash("Der Erwerber haftet nicht nach Absatz 1.")
    start, length = quotecheck.longest_run(needle, haystack)
    # "Unternehmer" and "Erwerber" share their last two characters, so the
    # longest run reaches back into the word before the common clause.
    assert needle[start:start + length] == quotecheck.squash("er haftet nicht nach Absatz 1.")


def test_longest_run_is_empty_for_unrelated_text():
    start, length = quotecheck.longest_run("zzzz", "aaaa")
    assert (start, length) == (0, 0)


def test_grounded_runs_cover_a_spliced_quote_but_not_an_invented_one():
    source = quotecheck.squash(
        "Die Frist beträgt sechs Jahre. Dazwischen steht ein Seitenkopf. "
        "Die Ausweisung erfolgt durch Anzeige bei der Bundesnetzagentur."
    )
    spliced = quotecheck.squash("Die Frist beträgt sechs Jahre. "
                                "Die Ausweisung erfolgt durch Anzeige")
    runs = quotecheck.grounded_runs(spliced, source)
    assert len(runs) == 2
    assert sum(n for _, n in runs) == len(spliced)

    invented = quotecheck.squash("Der Bund trägt die Kosten der Länder allein.")
    assert sum(n for _, n in quotecheck.grounded_runs(invented, source)) < len(invented)


def test_grounded_runs_ignore_coincidental_short_matches():
    """Eight characters of boilerplate are not evidence; counting them would
    flatter a fabrication's coverage."""
    source = quotecheck.squash("in Kraft treten die Vorschriften des Gesetzes")
    invented = quotecheck.squash("in Kraft XXXXXXXXXXXXXXXXXXXXXXX")
    assert quotecheck.grounded_runs(invented, source, min_len=12) == []


def test_fold_umlauts_is_diagnostic_only():
    assert quotecheck.fold_umlauts("erfüllungsaufwand") == "erfuellungsaufwand"
    # squash itself must never fold: a transliterated quote is not verbatim.
    assert quotecheck.squash("Erfüllungsaufwand") != "erfuellungsaufwand"
