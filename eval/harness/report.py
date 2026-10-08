"""Score a harness run against its case set: a summary and the detailed results.

A recall run scores the selected cases as they are. A precision run
(``--beschlussempfehlung``) scores every case with ``repaired_by`` as repaired
(kind ``behoben``): ``clear`` when no finding lands on its anchor, ``touched``
when one does.

Offline and free. Verdicts are the mechanical passage verdicts of
``eval/testset/score.py`` (``hit`` / ``near`` / ``miss`` for positives,
``touched`` / ``clear`` for negatives), plus what a run itself can end in:

``fired`` / ``quiet``  an unanchored Angreifer negative with / without findings.
``oversize``  the input is over ``MAX_INPUT_CHARS`` and was not sent.
``failed``    the call raised; the sample has a ``.failed.json``.
``not_run``   the run has no sample for the document.

Two files in the run directory, per case set:

``summary-<cases>.json``  run metadata, sample status, cost, passage recall per
                          split × context and per expected category.
``results-<cases>.json``  per document: the expectations and the analysis
                          with every finding and each case's verdict, naming
                          the findings that matched by index.

    uv run python -m eval.harness report --tag v6-text-json-claude-opus-4-8-effort-high
    uv run python -m eval.harness report --task angreifer --split dev
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eval.quotecheck import squash
from eval.testset import config as testset_config
from eval.testset.lint import TEXTS, documents, load, load_manifest
from eval.testset.score import (POSITIVE, REPAIRED, _pct, locate, repaired_summary, score_case,
                                 summarize)

from . import config, html, tasks
from .tasks import Task

# Every case set name of every task, for ``--cases``.
ALL_CASE_SETS = sorted({name for t in tasks.TASKS.values() for name in t.case_sets})

# Which cases a run scores, by ``requires_context``. ``none``: cases the draft
# alone can settle. ``bestandsrecht``: cases that need the existing law, run on
# the draft alone (baseline) or with their pinned norms fed (oracle). EU law and
# outside facts have no pinned context and are not run.
CONTEXTS = ["none", "bestandsrecht"]

# Case fields a reader of the results needs next to the verdict.
EXPECTATION_FIELDS = ("id", "kind", "expected_passage", "anchor", "expected_defect",
                      "expected_category", "expected_severity", "requires_context",
                      "forbidden_claim", "repaired_by", "story", "source")


def case_set(task: Task, name: str | None) -> str:
    """``name`` if the task has that case set, the task's default if ``None``."""
    if name is None:
        return task.default_cases
    if name not in task.case_sets:
        raise SystemExit(f"--cases {name}: {task.name} has {', '.join(task.case_sets)}")
    return name


def load_cases(task: Task, case_set: str, context: str = "none",
               repaired: bool = False) -> list[dict]:
    """The cases of a case set that require ``context``; with ``repaired``,
    every case with ``repaired_by`` instead, whatever its context, as kind
    ``behoben``."""
    cases = load(task.case_sets[case_set])
    if repaired:
        return [c | {"kind": REPAIRED} for c in cases if c.get("repaired_by")]
    return [c for c in cases if c["requires_context"] == context]


def load_samples(out: Path) -> dict[str, dict]:
    """Every sample and failure record of a run, by document.

    A sample supersedes a failure of the same document, which the run deletes
    anyway; this keeps a stale failure file from hiding a result.
    """
    samples: dict[str, dict] = {}
    paths = sorted((out / "samples").glob("*.json"),
                   key=lambda p: not p.name.endswith(".failed.json"))
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        samples[record["doc"]] = record
    return samples


def _status_row(case: dict, verdict: str) -> dict:
    return {"id": case["id"], "kind": case["kind"], "split": case["split"],
            "requires_context": case["requires_context"],
            "expected_category": case["expected_category"],
            "verdict": verdict}


def build(task: Task, cases: list[dict], samples: dict[str, dict], manifest: dict[str, dict],
          texts: Path = TEXTS, near: int = testset_config.NEAR_CHARS) -> tuple[list[dict], list[dict]]:
    """``(rows, documents)``: one verdict row per case, and the results."""
    rows: list[dict] = []
    results: list[dict] = []
    for (_, file), group in documents(cases).items():
        doc = group[0]["doc"]
        entry = {"doc": doc, "titel": manifest[doc]["titel"], "split": group[0]["split"],
                 "text_file": file,
                 "expectations": [{k: c[k] for k in EXPECTATION_FIELDS} for c in group],
                 "run": None}
        results.append(entry)
        record = samples.get(doc)
        if record is None:
            rows += [_status_row(c, "not_run") for c in group]
            continue
        status = record["status"]
        run = {"status": status,
               **{k: record.get(k) for k in ("input_set", "prompt_version", "model", "effort", "max_turns", "risk",
                                             "cost_usd", "num_turns", "seconds",
                                             "tool_calls", "rescued_by")}}
        if status != "ok":
            if status == "failed":
                run["error"] = f"{record['error_type']}: {record['error']}"
            verdicts = [_status_row(c, status) for c in group]
        else:
            squashed = squash((texts / file).read_text(encoding="utf-8"))
            findings = [f | {"index": i}
                        for i, f in enumerate(task.findings(record["analysis"]))]
            run["summary"] = record["analysis"]["summary"]
            run["findings"] = [f | {"located": bool(locate(f["quote"], squashed))}
                               for f in findings]
            verdicts = [score_case(c, findings, squashed, near, task.quiet_negatives)
                        for c in group]
        run["verdicts"] = verdicts
        rows += verdicts
        entry["run"] = run
    return rows, results


# A sentence ends at . ! or ? followed by whitespace and a capital letter, so
# "Abs. 2" and "§ 5 Nr. 3" stay inside their sentence.
SENTENCE_END = re.compile(r"[.!?]\s+(?=[A-ZÄÖÜ„])")


def words_per_sentence(texts: list[str]) -> float | None:
    """Mean words per sentence over ``texts``; ``None`` when there is no text."""
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return None
    words = sum(len(t.split()) for t in texts)
    sentences = sum(len(SENTENCE_END.findall(t)) + 1 for t in texts)
    return round(words / sentences, 1)


def by_category(rows: list[dict]) -> dict[str, dict]:
    """Positive verdicts per split and expected category."""
    out: dict[str, dict] = {}
    for row in rows:
        if row["kind"] != "positiv":
            continue
        cell = out.setdefault(row["split"], {}).setdefault(row["expected_category"], Counter())
        cell[row["verdict"]] += 1
    return {split: {cat: {"counts": dict(c),
                          "scorable": c["hit"] + c["near"] + c["miss"],
                          "strict": round(c["hit"] / s, 3) if (s := c["hit"] + c["near"] + c["miss"]) else None}
                    for cat, c in sorted(cats.items())}
            for split, cats in sorted(out.items())}


def summarize_run(task: Task, rows: list[dict], results: list[dict], case_set: str,
                  tag: str, near: int, context: str = "none", repaired: bool = False) -> dict:
    runs = [d["run"] for d in results if d["run"]]
    findings = [f for r in runs for f in r.get("findings", [])]
    return {
        "task": task.name,
        "tag": tag,
        "case_set": case_set,
        "cases_file": task.case_sets[case_set].name,
        # What the samples read; more than one means a mixed run directory.
        "input_set": ", ".join(sorted({r["input_set"] for r in runs
                                       if r.get("input_set")})) or "–",
        "requires_context": "all" if repaired else context,
        "measures": "precision" if repaired else "recall",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_versions": dict(Counter(r["prompt_version"] for r in runs)),
        "models": dict(Counter(r["model"] for r in runs)),
        # ``null`` is the model's default effort.
        "efforts": dict(Counter(r["effort"] for r in runs)),
        "max_turns": dict(Counter(r["max_turns"] for r in runs)),
        "shipped_prompt_version": task.prompt_version,
        "near_chars": near,
        "documents": len(results),
        "cases": len({r["id"] for r in rows}),
        "runs": dict(Counter(r["status"] for r in runs))
        | {"not_run": sum(not d["run"] for d in results)},
        "rescued": dict(Counter(r["rescued_by"] for r in runs if r.get("rescued_by"))),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in runs), 2),
        "seconds": round(sum(r["seconds"] or 0 for r in runs), 1),
        "findings": {"total": len(findings),
                     "unlocated": sum(not f["located"] for f in findings if f["quote"]),
                     "by_category": dict(Counter(f["category"] for f in findings)),
                     "by_severity": dict(Counter(f["severity"] for f in findings))},
        # Readability of the prose a reader sees: summaries and finding descriptions.
        "words_per_sentence": words_per_sentence(
            [r["summary"] for r in runs if r.get("summary")]
            + [f["description"] for f in findings]),
        "recall": summarize(rows),
        "recall_by_category": by_category(rows),
    }


def report_name(case_set: str, split: str, context: str = "none",
                repaired: bool = False) -> str:
    """``beschlussempfehlungen`` for every split, ``beschlussempfehlungen-dev`` for one;
    ``beschlussempfehlungen-bestandsrecht-dev`` for the cases that need existing law,
    ``beschlussempfehlungen-beschlussempfehlung-dev`` for a precision run."""
    name = (f"{case_set}-beschlussempfehlung" if repaired
            else case_set if context == "none" else f"{case_set}-{context}")
    return name if split == "all" else f"{name}-{split}"


def write_report(out: Path, task: Task, case_set: str, tag: str,
                 near: int = testset_config.NEAR_CHARS, split: str = "all",
                 context: str = "none", repaired: bool = False) -> dict:
    """Score the run in ``out`` on one split (or all) and write both files.

    Samples of documents outside the split or context stay on disk and are ignored.
    """
    cases = [c for c in load_cases(task, case_set, context, repaired)
             if split == "all" or c["split"] == split]
    rows, results = build(task, cases, load_samples(out), load_manifest(), near=near)
    summary = (summarize_run(task, rows, results, case_set, tag, near, context, repaired)
               | {"split": split})
    name = report_name(case_set, split, context, repaired)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"summary-{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"results-{name}.json").write_text(
        json.dumps({"summary": summary, "documents": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    html.write_run(out, name)
    _print(summary, out, name)
    return summary


def _print(summary: dict, out: Path, name: str) -> None:
    if any(len(summary[k]) > 1 for k in ("prompt_versions", "models", "efforts", "max_turns")):
        print(f"WARNING: mixed runs {summary['prompt_versions']} {summary['models']} "
              f"efforts {summary['efforts']} max_turns {summary['max_turns']}")
    print(f"runs {summary['runs']}  rescued {summary['rescued']}  cost ${summary['cost_usd']:.2f}  "
          f"findings {summary['findings']['total']} "
          f"({summary['findings']['unlocated']} unlocated)")
    if repaired := summary["measures"] == "precision":
        if any("beschlussempfehlung" not in i for i in summary["input_set"].split(", ")):
            print(f"WARNING: precision report over samples that read {summary['input_set']}")
    verdicts = POSITIVE + ["oversize", "failed"]
    for split, entry in summary["recall"].items():
        if repaired:
            for context in ("all", "none", "context"):
                e = entry.get(REPAIRED, {}).get(context) or repaired_summary([])
                counts = " ".join(f"{v}={e['counts'].get(v, 0)}"
                                  for v in ("clear", "touched", "oversize", "failed", "not_run"))
                print(f"{split:5} repaired  {context:8} {counts}  same category "
                      f"{e['touched_same_category']}  precision {_pct(e['precision'])}"
                      f"  by category {_pct(e['precision_category'])}")
            continue
        for context in ("all", "none", "context"):
            e = entry[context]
            counts = " ".join(f"{v}={e['counts'].get(v, 0)}" for v in verdicts)
            print(f"{split:5} positives {context:8} {counts}  strict {_pct(e['strict'])}"
                  f"  lenient {_pct(e['lenient'])}  category {e['category_match']}")
        if entry["negatives"]:
            print(f"{split:5} negatives          {entry['negatives']}")
    print(f"-> {out / f'summary-{name}.json'}\n-> {out / f'results-{name}.json'}"
          f"\n-> {out / f'report-{name}.html'}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.harness report",
        description="Score a harness run into summary and results JSON. Offline, free.",
    )
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="lektor")
    parser.add_argument("--cases", choices=ALL_CASE_SETS,
                        help="which case file of the task; defaults to its first")
    parser.add_argument("--model", help="defaults to the task's shipped model")
    parser.add_argument("--effort", choices=config.EFFORTS,
                        help="defaults to the task's shipped effort")
    parser.add_argument("--max-turns", type=int, metavar="N")
    parser.add_argument("--tag", help="run directory name; defaults to "
                        "<prompt version>-<model>[-effort-<level>][-turns-<n>]")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--near", type=int, default=testset_config.NEAR_CHARS)
    parser.add_argument("--context", choices=CONTEXTS, default="none",
                        help="score the cases that require this context")
    parser.add_argument("--oracle", action="store_true",
                        help="the run fed the pinned Bestandsrecht (names the run directory)")
    parser.add_argument("--beschlussempfehlung", action="store_true",
                        help="precision run: the run fed the Beschlussempfehlungen; score "
                        "every case with repaired_by as repaired")
    args = parser.parse_args(argv)

    task = tasks.get(args.task)
    tag = args.tag or config.default_tag(task, args.model or task.model,
                                         args.effort or task.effort, args.max_turns,
                                         oracle=args.oracle, committee=args.beschlussempfehlung)
    out = config.run_dir(task.name, tag)
    if not (out / "samples").is_dir():
        print(f"no samples in {out}")
        return 1
    write_report(out, task, case_set(task, args.cases), tag, args.near, args.split, args.context,
                 args.beschlussempfehlung)
    return 0
