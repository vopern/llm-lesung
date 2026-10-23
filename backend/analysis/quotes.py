"""Mechanical quote matching: where does this string stand in that Drucksache?

Pure string comparison, never an LLM judge. ``squash()`` (``backend/text.py``) is
the whole trick. pypdf splits words mid-token ("Re chnung") and hyphenates across
line breaks ("minde- stens"), so a naive substring test misses most quotes that
are in fact fully grounded. Anyone rebuilding a check like this and forgetting the
normalisation measures the PDF extractor, not the model.

``locate()`` turns a finding's quote into a page and an excerpt a reader can
check: the page of the PDF the quote starts on, and the text around it as the
document spells it.
"""

import re
from bisect import bisect_right

from backend.text import squash, squash_with_index

# A shorter quote ("§ 5 Abs. 9") stands in too many places to point at one.
MIN_QUOTE_CHARS = 12

# A quote that does not resolve whole is retried on its head: a page header the
# model read past, or an edited tail, breaks the match further in.
_HEAD_CHARS = 60
_HEAD_MIN_QUOTE_CHARS = 80

# Original text shown on either side of the located quote.
CONTEXT_CHARS = 300


class Document:
    """One Drucksache as page texts, prepared for ``locate``."""

    def __init__(self, document_id: str, pages: list[str]):
        self.document_id = document_id
        self.text = "\n".join(pages)
        self.page_starts: list[int] = []
        offset = 0
        for page in pages:
            self.page_starts.append(offset)
            offset += len(page) + 1
        self.squashed, self.index = squash_with_index(self.text)


# A word hyphenated at a line end ("minde-\nstens"), but not "Ein- und Ausfuhr".
_LINE_END_HYPHEN = re.compile(r"(?<=\w)[-‐]\s+(?!(?:und|oder|bzw|sowie|bis)\b)(?=[a-zäöüß])")


def _readable(s: str) -> str:
    """Excerpt text on one line, with words hyphenated at a line end rejoined."""
    return re.sub(r"\s+", " ", _LINE_END_HYPHEN.sub("", s))


def _location(doc: Document, pos: int, length: int) -> dict:
    start = doc.index[pos]
    end = doc.index[pos + length - 1] + 1

    before = doc.text[max(0, start - CONTEXT_CHARS):start]
    if start > CONTEXT_CHARS:
        # The cut falls mid-word: start at the next whole word.
        before = "…" + before.partition(" ")[2]
    after = doc.text[end:end + CONTEXT_CHARS]
    if end + CONTEXT_CHARS < len(doc.text):
        after = after.rpartition(" ")[0] + "…"

    return {
        "document_id": doc.document_id,
        "page": bisect_right(doc.page_starts, start),
        "before": _readable(before).lstrip(),
        "match": _readable(doc.text[start:end]),
        "after": _readable(after).rstrip(),
    }


def locate(quote: str | None, documents: list[Document]) -> dict | None:
    """Where ``quote`` stands in ``documents``, or ``None``.

    Returns ``document_id``, ``page`` (1-based page of the PDF the match starts
    on) and the excerpt as ``before`` / ``match`` / ``after`` in the document's
    own wording. The first occurrence in the first document wins; a whole
    match anywhere beats a match on the quote's head.
    """
    needle = squash(quote or "")
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    needles = [needle]
    if len(needle) >= _HEAD_MIN_QUOTE_CHARS:
        needles.append(needle[:_HEAD_CHARS])
    for candidate in needles:
        for doc in documents:
            pos = doc.squashed.find(candidate)
            if pos >= 0:
                return _location(doc, pos, len(candidate))
    return None
