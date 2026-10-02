"""The test-set exporter and the anchor scorer (offline, no Claude).

The scorer turns positions into a verdict that gets compared across runs, so the
tests sit on the cuts: overlap versus near versus miss, a quote that is only
placeable by its longest run, and a document no run covers.
"""

import hashlib

from eval.testset import export, lint, score
from tests.test_testset_lint import _case

FILLER = "Die Begründung erläutert ausführlich den Zweck der Regelung. " * 20
TEXT = (FILLER + "§ 10 Absatz 3 wird gestrichen. Eine Übergangsregel fehlt vollständig. "
        + FILLER + "Artikel 9 Inkrafttreten: Dieses Gesetz tritt am Tag nach der Verkündung in Kraft.")


def _doc(tmp_path, **overrides):
    case = _case(tmp_path, **overrides)
    (tmp_path / "21-537.txt").write_text(TEXT, encoding="utf-8")
    case["text"]["sha256"] = hashlib.sha256(TEXT.encode()).hexdigest()
    return case


def _finding(quote, category="vollstaendigkeit"):
    return {"category": category, "title": "t", "quote": quote}


def _verdict(tmp_path, findings, **overrides):
    case = _doc(tmp_path, **overrides)
    return score.score_case(case, findings, score.squash(TEXT), near=100)


def test_overlapping_quote_is_a_hit_with_category(tmp_path):
    row = _verdict(tmp_path, [_finding("Absatz 3 wird ge-\nstrichen")])
    assert (row["verdict"], row["category_match"]) == ("hit", True)


def test_adjacent_quote_is_near_and_far_quote_is_miss(tmp_path):
    near = _verdict(tmp_path, [_finding("Eine Übergangsregel fehlt vollständig.", "unklarheit")])
    assert (near["verdict"], near["category_match"]) == ("near", False)
    far = _verdict(tmp_path, [_finding("tritt am Tag nach der Verkündung in Kraft")])
    assert far["verdict"] == "miss" and far["distance"] > 100


def test_best_level_wins_over_order(tmp_path):
    row = _verdict(tmp_path, [_finding("Eine Übergangsregel fehlt vollständig.", "unklarheit"),
                              _finding("§ 10 Absatz 3", "referenz")])
    assert row["verdict"] == "hit"
    assert [m["category"] for m in row["matched"]] == ["referenz"]


def test_quote_placed_by_longest_run_and_unplaceable_quote_counted(tmp_path):
    spliced = "§ 10 Absatz 3 wird gestrichen. Eine Übergangsregel fehlt [Seite 4] ganz"
    row = _verdict(tmp_path, [_finding(spliced), _finding("frei erfunden")])
    assert (row["verdict"], row["unlocated"]) == ("hit", 1)


def test_negative_is_touched_not_counted(tmp_path):
    row = _verdict(tmp_path, [_finding("§ 10 Absatz 3")], kind="negativ",
                   expected_defect=None, expected_category=None, expected_severity=None,
                   forbidden_claim="Streichung sei verfassungswidrig")
    assert (row["verdict"], row["category_match"]) == ("touched", None)
    assert _verdict(tmp_path, [], anchor=None)["verdict"] == "unanchored"


def test_score_marks_documents_without_run_and_summarizes(tmp_path):
    case = _doc(tmp_path)
    runs = {("lektor", "21/537"): [{"label": "a", "findings": [_finding("§ 10 Absatz 3")]},
                                   {"label": "b", "findings": [_finding("in Kraft")]}]}
    rows = score.score([case], runs, tmp_path, near=100)
    assert [(r["run"], r["verdict"]) for r in rows] == [("a", "hit"), ("b", "miss")]
    assert score.score([case], {}, tmp_path)[0]["verdict"] == "not_run"
    summary = score.summarize(rows)["dev"]["all"]
    assert (summary["scorable"], summary["strict"]) == (2, 0.5)


def test_export_groups_cases_into_one_sample_per_document(tmp_path):
    cases = [_doc(tmp_path), _doc(tmp_path, id="L-C14", kind="negativ", expected_defect=None,
                                  expected_category=None, expected_severity=None,
                                  forbidden_claim="x")]
    [((suite, split), [sample])] = export.build(cases, tmp_path).items()
    assert (suite, split, sample["id"]) == ("lektor", "dev", "L-21-537")
    assert sample["input"] == TEXT
    assert sample["target"] == ["keine Übergangsregel"]
    meta = sample["metadata"]
    assert meta["canary"] == lint.CANARY and meta["doc"] == "21/537"
    assert [c["id"] for c in meta["cases"]] == ["L-C13", "L-C14"]
    assert "text" not in meta["cases"][0]
