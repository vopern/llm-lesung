"""Mechanical passage recall: did a finding land on a case's anchor?

Every anchored case points at a verbatim span of its pinned text, and every
finding carries a verbatim quote. Both are located in the same squashed text, so
"the run looked at the passage" is a position comparison — no model, no judge.
It measures location, never the defect, and bounds neither way: a ``hit`` whose
finding says something else about the passage is still a hit (run 2 has two),
and a finding that names the defect but quotes the Begründung is a ``miss``. Use
it as triage and as a regression signal between runs; the verdict on whether
the defect was found stays with the hand verdicts.

Per case:

``hit``         a finding's quote overlaps the anchor.
``near``        none overlaps, but one lies within ``NEAR_CHARS`` of it.
``miss``        the run has findings, none of them on or near the anchor.
``touched``     negative or inverse case: a finding sits on or near the passage
                of the forbidden claim — a candidate false positive to read,
                not a counted one.
``clear``       negative or inverse case: nothing on or near that passage.
``fired``       unanchored negative whose draft offers nothing to find
                (``quiet_negatives``): the run reported something anyway.
``quiet``       the same, and the run reported nothing.
``unanchored``  the case has no anchor, so nothing can be located.
``not_run``     no run covers the document.

The stored Lektor analyses are scored here, against the pinned texts rather
than whatever the pipeline read, so a quote from a different revision shows up
as ``unlocated``; eval harness runs are scored by ``eval.harness report``:

    uv run python -m eval.testset score db
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from backend import db
from eval.quotecheck import longest_run, squash

from . import config
from .lint import FILES, TEXTS, documents, load

POSITIVE = ["hit", "near", "miss", "unanchored", "not_run"]
NEGATIVE = ["touched", "clear", "fired", "quiet", "unanchored", "not_run"]

Span = tuple[int, int]


def occurrences(needle: str, haystack: str) -> list[Span]:
    """Every ``(start, end)`` of ``needle`` in ``haystack``, overlaps included."""
    spans, at = [], haystack.find(needle)
    while needle and at >= 0:
        spans.append((at, at + len(needle)))
        at = haystack.find(needle, at + 1)
    return spans


def locate(quote: str | None, squashed: str) -> list[Span]:
    """Where a quote sits in the squashed text; ``[]`` when it cannot be placed.

    A quote that is not verbatim is placed by its longest grounded run, if that
    run reaches clause length (``config.MIN_PARTIAL_CHARS``), the cut that tells a
    spliced quote from an invented one.
    """
    needle = squash(quote or "")
    if not needle:
        return []
    spans = occurrences(needle, squashed)
    if spans:
        return spans
    start, length = longest_run(needle, squashed)
    if length < config.MIN_PARTIAL_CHARS:
        return []
    return occurrences(needle[start:start + length], squashed)


def distance(a: Span, b: Span) -> int:
    """Squashed characters between two spans; negative when they overlap."""
    return max(b[0] - a[1], a[0] - b[1])


def score_case(case: dict, findings: list[dict], squashed: str,
               near: int = config.NEAR_CHARS, quiet_negatives: bool = False) -> dict:
    """The verdict for one case against the findings of one run on its document.

    ``quiet_negatives``: an unanchored ``negativ`` case means the draft offers
    nothing to find at all, so any finding is ``fired``. True for the Angreifer;
    a Lektor negative forbids one specific claim, which no position can check.
    """
    row = {k: case[k] for k in ("id", "kind", "split", "requires_context",
                                "expected_category")}
    positive = case["kind"] == "positiv"
    row |= {"verdict": "unanchored", "category_match": None, "distance": None,
            "matched": [], "unlocated": 0}

    placed = []
    for finding in findings:
        spans = locate(finding["quote"], squashed)
        if spans:
            placed.append((finding, spans))
        else:
            row["unlocated"] += 1
    if case["anchor"] is None:
        if quiet_negatives and case["kind"] == "negativ":
            row["verdict"] = "fired" if findings else "quiet"
        return row

    anchors = occurrences(squash(case["anchor"]), squashed)
    scored = sorted(((min(distance(a, s) for a in anchors for s in spans), finding)
                     for finding, spans in placed if anchors), key=lambda pair: pair[0])
    close = [(d, f) for d, f in scored if d <= near]
    if not close:
        row["verdict"] = "miss" if positive else "clear"
        row["distance"] = scored[0][0] if scored else None
        return row

    best = close[0][0]
    level = [f for d, f in close if (d < 0) == (best < 0)]
    row["verdict"] = ("hit" if best < 0 else "near") if positive else "touched"
    row["distance"] = best
    # ``index`` (position in the run's findings) is kept when the caller passes it.
    row["matched"] = [{k: f[k] for k in ("index", "category", "title") if k in f}
                      for f in level]
    if positive:
        row["category_match"] = any(f["category"] == case["expected_category"] for f in level)
    return row


def score(cases: list[dict], runs: dict[tuple[str, str], list[dict]],
          texts: Path = TEXTS, near: int = config.NEAR_CHARS) -> list[dict]:
    """One row per case per run; ``runs`` maps ``(suite, doc)`` to its runs."""
    rows = []
    for (suite, file), group in documents(cases).items():
        doc_runs = runs.get((suite, group[0]["doc"]), [])
        if not doc_runs:
            rows += [{"id": c["id"], "kind": c["kind"], "split": c["split"],
                      "requires_context": c["requires_context"],
                      "expected_category": c["expected_category"],
                      "verdict": "not_run", "run": None} for c in group]
            continue
        squashed = squash((texts / file).read_text(encoding="utf-8"))
        for run in doc_runs:
            rows += [score_case(c, run["findings"], squashed, near) | {"run": run["label"]}
                     for c in group]
    return rows


def summarize(rows: list[dict]) -> dict:
    """Verdict counts and recall per split, positives also by context."""
    out: dict[str, dict] = {}
    for split in sorted({r["split"] for r in rows}):
        in_split = [r for r in rows if r["split"] == split]
        pos = [r for r in in_split if r["kind"] == "positiv"]
        entry = {"negatives": dict(Counter(r["verdict"] for r in in_split
                                           if r["kind"] != "positiv"))}
        for context, subset in (("all", pos),
                                ("none", [r for r in pos if r["requires_context"] == "none"]),
                                ("context", [r for r in pos if r["requires_context"] != "none"])):
            counts = Counter(r["verdict"] for r in subset)
            scorable = counts["hit"] + counts["near"] + counts["miss"]
            entry[context] = {
                "counts": dict(counts),
                "scorable": scorable,
                "strict": round(counts["hit"] / scorable, 3) if scorable else None,
                "lenient": round((counts["hit"] + counts["near"]) / scorable, 3)
                if scorable else None,
                "category_match": sum(bool(r.get("category_match")) for r in subset),
            }
        out[split] = entry
    return out


def db_runs(conn: sqlite3.Connection, docs: set[str]) -> dict[tuple[str, str], list[dict]]:
    """The stored analysis of every Lektor document that has one."""
    runs: dict[tuple[str, str], list[dict]] = {}
    bills = conn.execute(
        "SELECT id, dokumentnummer, prompt_version, model FROM bills "
        "WHERE risk IS NOT NULL ORDER BY analyzed_at").fetchall()
    for bill in bills:
        if bill["dokumentnummer"] not in docs:
            continue
        findings = [dict(f) for f in conn.execute(
            "SELECT category, title, quote FROM findings WHERE bill_id = ? ORDER BY id",
            (bill["id"],))]
        # Ordered by analysis time, so a re-analysed Drucksache keeps its latest.
        runs[("lektor", bill["dokumentnummer"])] = [{
            "label": bill["dokumentnummer"], "prompt_version": bill["prompt_version"],
            "model": bill["model"], "findings": findings}]
    return runs


def _pct(x: float | None) -> str:
    return "  –  " if x is None else f"{x:5.0%}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.testset score",
        description="Passage recall against the anchors. Offline, free.",
    )
    parser.add_argument("source", choices=["db"])
    parser.add_argument("--near", type=int, default=config.NEAR_CHARS)
    args = parser.parse_args(argv)

    cases = [c for path in FILES["lektor"] for c in load(path)]
    runs = db_runs(db.connect(), {c["doc"] for c in cases})

    rows = score(cases, runs, near=args.near)
    summary = summarize(rows)
    versions = Counter(r["prompt_version"] for rs in runs.values() for r in rs)
    result = {"source": args.source, "near_chars": args.near, "prompt_versions": dict(versions),
              "summary": summary, "rows": rows}
    path = config.score_path(args.source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"prompt versions: {dict(versions)}")
    for split, entry in summary.items():
        for context in ("all", "none", "context"):
            e = entry[context]
            counts = " ".join(f"{v}={e['counts'].get(v, 0)}" for v in POSITIVE)
            print(f"{split:8} positives {context:8} {counts}  strict {_pct(e['strict'])}"
                  f"  lenient {_pct(e['lenient'])}  category {e['category_match']}")
        counts = " ".join(f"{v}={entry['negatives'].get(v, 0)}" for v in NEGATIVE)
        print(f"{split:8} negatives          {counts}")
    print(f"-> {path}")
    return 0
