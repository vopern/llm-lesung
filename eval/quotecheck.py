"""Mechanical quote matching: does this string really occur in that draft?

Used by the test-set scorer (`eval/testset/score.py`) and through it by the eval
harness. Pure string comparison, never an LLM judge, so a number from either can
be quoted.

``squash()`` is the whole trick. pypdf splits words mid-token ("Re chnung") and
hyphenates across line breaks ("minde- stens"), so a naive substring test misses
most quotes that are in fact fully grounded. Anyone rebuilding a
check like this and forgetting the normalisation measures the PDF extractor,
not the model.

Beyond the yes/no verdict a check needs to tell a spliced quote from an
invented one, which is what ``longest_run`` and ``grounded_runs`` are for: a
quote that resolves as two long pieces with a small gap is a page header the
model read past, a quote whose longest grounded piece is eleven characters is
not in the draft at all.
"""

import re

# Everything the PDF text layer is free to move around: whitespace and every
# kind of hyphen/dash.
_DROPPED = re.compile(r"[\s\-‐-―]")

# Typographic variants a model normalises silently and pypdf does not.
_FOLDED = {"­": "", "„": '"', "“": '"', "”": '"', "»": '"', "«": '"',
           "‚": "'", "‘": "'", "’": "'"}


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

    Only needed to quote a *fragment* back in its original spelling: the sweep
    reports which part of a quote resolved, and "hatdieBundesregierung" is worth
    less to a reader checking a finding by hand than the text as written.
    Deliberately a second function rather than a rewrite of ``squash``: the
    regex above is the version the scored numbers were measured with, and
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


def fold_umlauts(s: str) -> str:
    """ä→ae, ß→ss and the rest, on an already squashed string.

    A diagnostic, never part of the verdict: some stored quotes transliterate
    ("Erfuellungsaufwand" for "Erfüllungsaufwand") where the draft does not. A
    quote that resolves only after folding is a rewritten quote — grounded in
    substance, not verbatim — and must stay distinguishable from a verbatim one.
    """
    for umlaut, digraph in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(umlaut, digraph)
    return s


def longest_run(needle: str, haystack: str) -> tuple[int, int]:
    """``(start, length)`` of the longest substring of ``needle`` in ``haystack``.

    Both arguments must already be squashed. The window never shrinks: if
    ``needle[i:i+n]`` occurs in the haystack then so does ``needle[i+1:i+n]``,
    so one forward pass suffices and the cost stays linear in ``len(needle)``
    substring searches rather than quadratic.
    """
    if not needle or not haystack:
        return 0, 0
    best_start = best_len = 0
    i = j = 0
    n = len(needle)
    while j < n:
        if needle[i:j + 1] in haystack:
            if j + 1 - i > best_len:
                best_start, best_len = i, j + 1 - i
            j += 1
        elif i == j:  # this single character occurs nowhere; skip it
            i = j = j + 1
        else:
            i += 1
    return best_start, best_len


def _match_len_at(needle: str, start: int, haystack: str) -> int:
    """Length of the longest prefix of ``needle[start:]`` found in ``haystack``.

    Exponential probe then binary search, so a long grounded run costs
    ~2·log(n) substring searches instead of one per character.
    """
    n = len(needle) - start
    if n <= 0 or needle[start] not in haystack:
        return 0
    lo, hi = 1, 2
    while hi <= n and needle[start:start + hi] in haystack:
        lo, hi = hi, hi * 2
    hi = min(hi - 1, n)  # this length is known to fail, unless it is the rest
    while lo < hi:  # largest length that still matches, in [lo, hi]
        mid = (lo + hi + 1) // 2
        if needle[start:start + mid] in haystack:
            lo = mid
        else:
            hi = mid - 1
    return lo


def grounded_runs(needle: str, haystack: str, min_len: int = 8) -> list[tuple[int, int]]:
    """Greedy left-to-right cover of ``needle`` by substrings of ``haystack``.

    The diagnostic that separates a spliced quote from an invented one: a quote
    interrupted by a page header resolves as two long runs covering nearly all
    of it, an invented quote as a scatter of short ones. Runs shorter than
    ``min_len`` are dropped — at that length German legal boilerplate matches by
    coincidence and counting it would inflate the coverage of a fabrication.
    """
    runs: list[tuple[int, int]] = []
    pos = 0
    while pos < len(needle):
        length = _match_len_at(needle, pos, haystack)
        if length >= min_len:
            runs.append((pos, length))
        pos += max(length, 1)
    return runs
