"""Text normalization, sentence splitting and mechanical match metrics.

Everything here is deterministic string work — no model is asked whether an
answer is right. That is the point: an LLM judge on a verbatim-recall task
would add its own recall error to the measurement.

Normalization folds only differences that are *not* knowledge:

* typographic quotes/dashes, markdown emphasis, non-breaking spaces
* an ``ANTWORT:`` envelope, a leading ``(3)`` Absatz marker, wrapping quotes
* ``ß`` -> ``ss``. The consolidated GG still carries pre-1996 orthography
  ("daß", "muß", "Bewußtsein"); a model reproducing modern spelling is not
  misremembering the norm, so both sides are folded.

It deliberately does *not* fold word order, inflection or synonyms — Haiku
answering "Sie zu schützen und zu achten" for Art. 1 Abs. 1 (the GG says
"zu achten und zu schützen") is a real recall error and must score as one.
"""

import difflib
import re
import unicodedata

# Sentence-final abbreviations that must never end a Satz in legal German.
_ABBREVIATIONS = {
    "abs", "art", "nr", "buchst", "lit", "vgl", "bzw", "ff", "f", "ggf",
    "insbes", "usw", "z", "b", "d", "h", "s", "ziff", "abschn", "bgbl",
    "i", "v", "m", "u", "a", "evtl", "sog", "hs", "halbs", "einschl", "gem",
}

_MARKDOWN = re.compile(r"[*_`#]+")
_ENVELOPE = re.compile(r"(?is)^.*?\bANTWORT\s*:\s*")
_ABSATZ_MARKER = re.compile(r"^\s*\(\d{1,2}[a-z]?\)\s*")
_WRAPPING_QUOTES = re.compile(r'^[\s"„“”«»\']+|[\s"„“”«»\']+$')

# A citation prefix the model may prepend even when told not to, e.g.
# "Artikel 5 Absatz 1 GG: Jeder hat ...".
_CITATION_PREFIX = re.compile(
    r"(?i)^\s*(?:art(?:\.|ikel)?\s*\d{1,3}\s*[a-z]?"
    r"(?:\s*(?:abs(?:\.|atz)?|absatz)\s*\d{1,2}\s*[a-z]?)?"
    r"(?:\s*(?:satz|s\.)\s*\d{1,2})?"
    r"(?:\s*(?:des\s+)?(?:grundgesetz(?:es)?|gg))?)\s*[:–—-]\s*"
)

ABSTENTION = "UNBEKANNT"

# Ways a model signals it does not know, beyond the requested token.
_ABSTENTION_MARKERS = re.compile(
    r"(?i)\b(unbekannt|weiss nicht|weiß nicht|nicht sicher|kann ich nicht|"
    r"erinnere mich nicht|nicht bekannt|existiert nicht|gibt es nicht|"
    r"keinen? (?:solchen|derartigen)|nicht vorhanden|i don't know|unknown)\b"
)


def split_saetze(text: str) -> list[str]:
    """Split an Absatz into its Sätze (legal sentence numbering).

    Conservative on purpose: a wrong split becomes wrong ground truth. Splits
    only at ``.!?`` followed by whitespace and an uppercase/quote start, and
    never after an ordinal ("1. Januar", "Nummer 3.") or a known abbreviation
    ("Abs.", "Nr.", "vgl.").
    """
    if not text:
        return []

    pieces = re.split(r"(?<=[.!?])\s+", text)
    saetze: list[str] = []
    for piece in pieces:
        if saetze and _continues_previous(saetze[-1], piece):
            saetze[-1] = f"{saetze[-1]} {piece}"
        else:
            saetze.append(piece)
    return [s.strip() for s in saetze if s.strip()]


def _continues_previous(previous: str, following: str) -> bool:
    """True when ``following`` belongs to ``previous`` rather than starting a Satz."""
    if not following[:1].isupper() and following[:1] not in '"„(':
        return True
    last = previous.rstrip()
    if not last.endswith("."):
        return True  # only a period is ambiguous; ! and ? really do end here
    token = re.split(r"[\s(\[]", last[:-1])[-1].lower()
    token = token.strip("„“\"',;:")
    if token in _ABBREVIATIONS:
        return True
    return bool(re.fullmatch(r"\d+", token))  # ordinal: "1.", "23."


def strip_envelope(raw: str) -> str:
    """Pull the payload out of a model reply.

    Takes everything after the last ``ANTWORT:`` marker, then drops the
    decorations a chatty model adds anyway: markdown, a repeated citation,
    a leading ``(2)``, wrapping quotes.
    """
    text = (raw or "").strip()
    if "ANTWORT" in text.upper():
        text = _ENVELOPE.sub("", text, count=1)
    text = _MARKDOWN.sub("", text)
    # Quotes, a citation prefix and an Absatz marker can nest in any order
    # ("\"(1) Die Würde ...\"", "Art. 1 Abs. 1 GG: \"...\""), so peel until stable.
    for _ in range(4):
        peeled = _ABSATZ_MARKER.sub("", _CITATION_PREFIX.sub("", _WRAPPING_QUOTES.sub("", text)))
        if peeled == text:
            break
        text = peeled
    return re.sub(r"\s+", " ", text).strip()


def is_abstention(text: str) -> bool:
    """True when the reply declines to answer instead of guessing."""
    stripped = strip_envelope(text)
    if not stripped:
        return True
    if stripped.strip(" .!").upper() == ABSTENTION:
        return True
    # Only treat it as abstention when the reply is short; a long answer that
    # happens to contain "nicht bekannt" is an answer, not a refusal.
    return len(stripped) < 200 and bool(_ABSTENTION_MARKERS.search(stripped))


def normalize(text: str) -> str:
    """Fold non-knowledge differences so two spellings of the same norm match."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace(" ", " ")
    for dash in "‐‑‒–—−":
        text = text.replace(dash, "-")
    for quote in "„“”«»‘’‚":
        text = text.replace(quote, '"')
    text = text.casefold().replace("ß", "ss")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .\"'")


def tokens(text: str) -> list[str]:
    """Word tokens of the normalized text; punctuation dropped."""
    return re.findall(r"[0-9a-zäöü]+", normalize(text))


def similarity(a: str, b: str) -> float:
    """Token-level ratio in [0, 1] — insensitive to punctuation, order-aware."""
    return difflib.SequenceMatcher(None, tokens(a), tokens(b)).ratio()


def token_edits(expected: str, actual: str) -> int:
    """Number of token insertions/deletions/replacements between the two texts.

    A ratio cannot express "one word off" on a short norm — a single inserted
    word in a 17-token Satz already costs ~3% similarity, while the same word
    in a 200-token Absatz costs 0.5%. Counting edits makes the near-miss
    threshold mean the same thing at every length.
    """
    want, got = tokens(expected), tokens(actual)
    edits = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, want, got).get_opcodes():
        if tag != "equal":
            edits += max(i2 - i1, j2 - j1)
    return edits


def token_f1(expected: str, actual: str) -> tuple[float, float, float]:
    """Bag-of-words precision, recall and F1 of ``actual`` against ``expected``."""
    from collections import Counter

    want, got = Counter(tokens(expected)), Counter(tokens(actual))
    if not want or not got:
        return 0.0, 0.0, 0.0
    overlap = sum((want & got).values())
    precision = overlap / sum(got.values())
    recall = overlap / sum(want.values())
    if precision + recall == 0:
        return 0.0, 0.0, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def find_articles(text: str) -> list[str]:
    """Article numbers cited in ``text``: "Art. 12a", "Artikel 5" -> ["12a", "5"]."""
    found = re.findall(r"(?i)\bart(?:\.|ikel)?\s*(\d{1,3})\s*([a-z])?\b", text or "")
    return [f"{number}{letter.lower()}" for number, letter in found]
