"""Text normalisation shared by every mechanical match against a Drucksache."""

import re

# Everything the PDF text layer is free to move around: whitespace and every
# kind of hyphen/dash.
_DROPPED = re.compile(r"[\s\-‐-―]")

# Typographic variants a model normalises silently and pypdf does not.
_FOLDED = {"­": "", "„": '"', "“": '"', "”": '"', "»": '"', "«": '"',
           "‚": "'", "‘": "'", "’": "'"}


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def ascii_umlauts(s: str) -> str:
    """``s`` with umlauts and ß spelled out, as the schema's enum values are."""
    return s.translate(_UMLAUTS)


def squash(s: str) -> str:
    """Strip everything the PDF text layer mangles: whitespace, hyphens, quotes."""
    s = s.replace("­", "")  # soft hyphen
    for ch in "„“”»«":
        s = s.replace(ch, '"')
    for ch in "‚‘’":
        s = s.replace(ch, "'")
    return re.sub(r"[\s\-‐-―]+", "", s).lower()


def squash_with_index(s: str) -> tuple[str, list[int]]:
    """``squash(s)`` plus, per squashed character, its offset in ``s``.

    Needed to give a match back in its original spelling: "hatdieBundesregierung"
    is worth less to a reader checking a finding by hand than the text as
    written. Deliberately a second function rather than a rewrite of ``squash``:
    the regex above is the version the scored numbers were measured with, and
    ``test_squash_with_index_agrees_with_squash`` holds the two together.
    """
    out: list[str] = []
    index: list[int] = []
    for pos, ch in enumerate(s):
        ch = _FOLDED.get(ch, ch)
        if not ch or _DROPPED.match(ch):
            continue
        lowered = ch.lower()
        out.append(lowered)
        index.extend([pos] * len(lowered))
    return "".join(out), index
