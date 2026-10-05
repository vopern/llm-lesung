"""Mechanical quote matching: does this string really occur in that draft?

Used by the test-set scorer (`eval/testset/score.py`) and through it by the eval
harness. Pure string comparison, never an LLM judge, so a number from either can
be quoted.

``squash()`` (``backend/analysis/quotes.py``, which the pipeline locates quotes
with) is the whole trick: it strips what the PDF text layer mangles.

Beyond the yes/no verdict a check needs to tell a spliced quote from an
invented one, which is what ``longest_run`` and ``grounded_runs`` are for: a
quote that resolves as two long pieces with a small gap is a page header the
model read past, a quote whose longest grounded piece is eleven characters is
not in the draft at all.
"""

from backend.analysis.quotes import squash, squash_with_index  # noqa: F401 — shared with the pipeline


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
