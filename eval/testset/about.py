"""Prose about the evaluation set and how each case file was mined, for the reports.

It lives next to the YAML so a reader of a report and a reader of the set get
the same account, and so a new case file describes itself in one place. The
counts are read from the YAML at render time, never written down twice.
"""

from . import lint

INTRO = (
    "The evaluation sets were researched and written completely by an AI pointed to documents or online resources — "
    "committee reports, court rulings, press coverage — not by a legal expert, so they may contain errors "
    "and hallucinations. A case is either a defect the analysis pipeline should find in a "
    "draft bill (positive), or a claim it must not make about one (negative). There may be several test cases per Bundestags-Drucksache. "
)

FILES = {
    "cases-lektor-beschlussempfehlungen.yaml": {
        "title": "Committee repairs",
        "mined": (
            "Mined by comparing a Gesetzentwurf with the report of "
            "the Bundestag committee that handled it: wherever the committee corrected the "
            "draft and said so, that correction becomes a case, pinned to the faulty wording "
            "in the original text. Political changes and unrelated additions are not drafting "
            "mistakes and were left out. The committee's report is the answer key here, so the "
            "analysis never sees it — only runs on the draft alone are scored against this "
            "file."
        ),
    },
    "cases-lektor.yaml": {
        "title": "Press-documented controversies",
        "mined": (
            "Built from the outside in: a ruling of the Bundesverfassungsgericht, a later "
            "repair law or documented expert criticism points to a draft, and the passage "
            "that carried the defect is then quoted from the original Drucksache. Four "
            "groups — constitutional rulings, repair laws and drafting errors, bills of the "
            "current Wahlperiode passed or pending, and drafts that never passed. Most cases "
            "are the opposite test: bills whose controversy was political rather than a flaw "
            "in the text, each with the claim the analysis must not make."
        ),
    },
    "cases-angreifer.yaml": {
        "title": "Attack surfaces",
        "mined": (
            "Built backwards from observed consequences: drafts that were not technically wrong, but "
            "whose wording allowed unintended exploits — share-deal thresholds, the "
            "certificate that shielded online marketplaces from VAT liability, cum-ex — "
            "traced from press coverage and hearing statements back to the passage that "
            "made it possible. Negative test cases are the opposite: a later law that closed "
            "such a gap, which must not be reported as still open, and current bills that "
            "offer no known exploits, where a reported attack is a false alarm."
        ),
    },
}


def _counts(cases: list[dict]) -> str:
    """Counts in the report's own words: what to find, what not to report."""
    find = sum(1 for c in cases if c["kind"] == "positiv")
    withhold = len(cases) - find
    split = f" ({find} to find, {withhold} that must not be reported)" if withhold else ""
    documents = len({c["doc"] for c in cases})
    settled = sum(1 for c in cases if c["requires_context"] == "none")
    return (f"{len(cases)} cases{split} · {documents} Drucksachen · "
            f"{settled} answerable from the draft alone")


def files() -> list[dict]:
    """Every case file: its prose and the counts read from the YAML."""
    return [{"name": path.name, "counts": _counts(lint.load(path)), **FILES[path.name]}
            for path in lint.PATHS if path.name in FILES]
