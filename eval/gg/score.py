"""Score a run mechanically and write a JSON verdict file plus an HTML report.

No model judges anything here. Every verdict is a string comparison against the
official text, which is what makes the numbers reproducible and comparable
across models and across time.

Verdicts per item:

``korrekt``       normalized exact match — the norm, verbatim
``fast_korrekt``  >= 0.98 token similarity: a stray comma or a folded spelling
``teilweise``     substantially overlapping, materially different
``falsch``        below that
``enthalten``     the model declined instead of guessing
``fehler``        the CLI call failed; excluded from the rates

The headline is not accuracy alone. A verbatim-recall eval whose consumer is a
legal-analysis pipeline cares more about the split between *wrong* and
*abstained*: an invented Absatz is what turns into a false ``verfassungsrisiko``
finding, an abstention is merely a miss.
"""

import argparse
import collections
import functools
import json
from datetime import UTC, datetime

from . import config
from .normalize import (
    find_articles,
    is_abstention,
    normalize,
    similarity,
    token_edits,
    strip_envelope,
    token_f1,
)
from .run import load_testset

def _addressable_units(gg: dict) -> list[tuple[str, str]]:
    """Every citation in the GG with its text: each Absatz and each of its Sätze."""
    units = []
    for article in gg["articles"]:
        for absatz in article["absaetze"]:
            label = f"Art {article['artikel']} Abs {absatz['nr']}"
            units.append((label, absatz["text"]))
            for index, satz in enumerate(absatz["saetze"], start=1):
                units.append((f"{label} Satz {index}", satz))
    return units


@functools.cache
def _units() -> list[tuple[str, str]]:
    if not config.GG_JSON.exists():
        return []
    return _addressable_units(json.loads(config.GG_JSON.read_text(encoding="utf-8")))


def best_match(answer: str, expected: str, units: list[tuple[str, str]]) -> str | None:
    """Which citation's text the answer reproduces, or None if the asked-for one.

    The ``teilweise``/``falsch`` boundary is a word-overlap threshold and says
    nothing about *which* citation was quoted — German legal boilerplate is
    repetitive enough that a different Absatz can clear it. This compares the
    answer against the text of every citation in the GG (each Absatz, each Satz)
    and reports the best fit, so "quoted a different citation" becomes a
    measurement instead of a label.

    Candidates that are part of the asked-for text are skipped: the unit list
    holds an Absatz *and* its own Sätze, so an answer that reproduces only the
    first sentence of the right Absatz matches that Satz entry best. That is a
    truncated quote of the correct citation, not a different one.
    """
    if not units or not answer:
        return None
    wanted = normalize(expected)

    def is_candidate(text: str) -> bool:
        other = normalize(text)
        if other == wanted:
            return True  # the asked-for text itself must stay in the running
        return other not in wanted and wanted not in other

    candidates = [unit for unit in units if is_candidate(unit[1])]
    if not candidates:
        return None
    label, text = max(candidates, key=lambda unit: similarity(unit[1], answer))
    if text == expected or similarity(text, expected) > 0.9:
        return None
    return label


EXACT = "korrekt"
NEAR = "fast_korrekt"
PARTIAL = "teilweise"
WRONG = "falsch"
ABSTAINED = "enthalten"
ERROR = "fehler"

# A near-miss is a typo, not a memory failure; a partial answer is the right
# asked-for text remembered loosely. Below that it is quoting something else.
# "Near" is measured in changed tokens, not in a ratio, so it means the same
# thing for a 12-word Satz and a 200-word Absatz.
NEAR_MAX_EDITS = 1
NEAR_EDIT_FRACTION = 0.02
PARTIAL_THRESHOLD = 0.60


def judge(item: dict, record: dict) -> dict:
    """Verdict + metrics for one answered item. Pure string comparison."""
    result = {
        "id": item["id"],
        "kind": item["kind"],
        "stratum": item["stratum"],
        "unit": item["unit"],
        "artikel": item["artikel"],
        "citation": item["citation"],
        "corpus_citations": item["corpus_citations"],
        "expected": item["expected"],
        "answer": "",
        "verdict": ERROR,
        "similarity": 0.0,
        "f1": 0.0,
        "cost_usd": record.get("cost_usd", 0.0),
    }
    if record.get("error"):
        result["error"] = record["error"]
        return result

    answer = strip_envelope(record.get("raw", ""))
    result["answer"] = answer

    if is_abstention(record.get("raw", "")):
        # For a trap item, declining *is* the correct answer.
        result["verdict"] = EXACT if item["kind"] == "nonexistent" else ABSTAINED
        return result

    if item["kind"] == "nonexistent":
        # It answered a citation that does not exist: invented text.
        result["verdict"] = WRONG
        return result

    if item["kind"] == "reverse":
        cited = find_articles(answer)
        expected = item["expected"].lower()
        if cited and cited[0] == expected:
            result["verdict"] = EXACT
        elif expected in cited:
            result["verdict"] = PARTIAL  # right article, buried among others
        else:
            result["verdict"] = WRONG
        return result

    ratio = similarity(item["expected"], answer)
    _, _, f1 = token_f1(item["expected"], answer)
    edits = token_edits(item["expected"], answer)
    allowed = max(NEAR_MAX_EDITS, round(NEAR_EDIT_FRACTION * len(item["expected"].split())))
    result["similarity"] = round(ratio, 4)
    result["f1"] = round(f1, 4)
    result["token_edits"] = edits
    if normalize(item["expected"]) == normalize(answer):
        result["verdict"] = EXACT
    elif edits <= allowed:
        result["verdict"] = NEAR
    elif f1 >= PARTIAL_THRESHOLD:
        result["verdict"] = PARTIAL
    else:
        result["verdict"] = WRONG
    if result["verdict"] in (PARTIAL, WRONG):
        result["misattributed_to"] = best_match(answer, item["expected"], _units())
    return result


def _rates(results: list[dict]) -> dict:
    """Verdict counts and the three rates that matter, over scored items only."""
    counts = collections.Counter(r["verdict"] for r in results)
    scored = [r for r in results if r["verdict"] != ERROR]
    n = len(scored) or 1
    return {
        "n": len(results),
        "n_scored": len(scored),
        "counts": dict(counts),
        # Verbatim recall: the strict number.
        "exact_rate": round(counts[EXACT] / n, 4),
        # Exact or typo-level — what a human would call "knows the citation".
        "known_rate": round((counts[EXACT] + counts[NEAR]) / n, 4),
        # Confidently wrong: the failure mode that produces bad findings.
        "hallucination_rate": round((counts[WRONG] + counts[PARTIAL]) / n, 4),
        "abstention_rate": round(counts[ABSTAINED] / n, 4),
        # Of the wrong answers, how many reproduce the text of a *different*
        # citation rather than misquoting the one that was asked for. Verified
        # against every Absatz and Satz in the GG, not inferred from the verdict.
        "misattribution_rate": round(
            sum(1 for r in results if r.get("misattributed_to")) / n, 4
        ),
    }


def _group(results: list[dict], key: str) -> dict:
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for result in results:
        buckets[str(result[key])].append(result)
    return {name: _rates(rows) for name, rows in sorted(buckets.items())}


def score(items: list[dict], records: list[dict]) -> dict:
    by_id = {r["id"]: r for r in records}
    results = [judge(i, by_id[i["id"]]) for i in items if i["id"] in by_id]

    zitat = [r for r in results if r["kind"] == "zitat"]
    return {
        "scored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": next((r.get("model") for r in records if r.get("model")), ""),
        "gg_stand": items[0].get("gg_stand", "") if items else "",
        "total_cost_usd": round(sum(r.get("cost_usd", 0.0) for r in records), 4),
        "overall": _rates(results),
        "by_kind": _group(results, "kind"),
        "by_stratum": _group(zitat, "stratum"),
        "by_unit": _group(zitat, "unit"),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    # Imported here: the renderer reads this module's verdict constants.
    from . import report as report_html

    parser = argparse.ArgumentParser(description="Score a GG-recall run")
    parser.add_argument("--tag", required=True, help="run tag used by `run`")
    args = parser.parse_args(argv)

    items = load_testset(config.TESTSET)
    records = load_testset(config.responses_path(args.tag))
    report = score(items, records)

    config.score_path(args.tag).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config.report_path(args.tag).write_text(
        report_html.render(report, args.tag), encoding="utf-8"
    )

    overall = report["overall"]
    print(
        f"{args.tag}: {overall['n_scored']} items | "
        f"exakt {overall['exact_rate']:.0%} | "
        f"exakt+fast {overall['known_rate']:.0%} | "
        f"falsch/teilw {overall['hallucination_rate']:.0%} | "
        f"anderes Zitat {overall['misattribution_rate']:.0%} | "
        f"enthalten {overall['abstention_rate']:.0%}\n"
        f"  {config.score_path(args.tag)}\n  {config.report_path(args.tag)}"
    )
    for name, stats in report["by_stratum"].items():
        print(f"  stratum {name:5s} n={stats['n_scored']:3d} exakt {stats['exact_rate']:.0%}")
    return 0
