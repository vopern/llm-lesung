"""Run a pass — Lektor or Angreifer — over the documents of a case set, Entwurf only.

Only cases with ``requires_context: none`` are selected and scored; a document
whose cases all need context is not run.

Inputs come from the test set alone: the pinned draft text and the title in
``eval/testset/inputs.yaml``. The message is built and sent by the task's own
``build_message`` and ``run_query`` — the calls the pass ships with — so the run
measures the shipped prompt, model and input format without reading or writing
the database. A draft over ``analyzer.MAX_INPUT_CHARS`` is not sent, for either
task: the pipeline skips it on the same rule.

One sample per document lands in ``data/eval/runs/<task>-<tag>/samples/``; the
call's message stream in ``traces/``. After the calls the run is scored
(``report.py``).

    uv run python -m eval.harness run --split dev --only 21/537,21/1493
    uv run python -m eval.harness run --task angreifer --split dev
"""

import argparse
import asyncio
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend import tracelog
from backend.analysis import analyzer, structured
from eval.testset.lint import TEXTS, load_manifest, sha256

from . import config, report, tasks
from .tasks import Task

# The only input set so far: the Gesetzentwurf alone.
INPUT_SET = "entwurf"


def stem(document: dict) -> str:
    """``21-537`` for Drucksache 21/537."""
    return document["file"].removesuffix(".txt")


def sample_path(out: Path, document: dict) -> Path:
    return out / "samples" / f"{stem(document)}.json"


def failure_path(out: Path, document: dict) -> Path:
    return out / "samples" / f"{stem(document)}.failed.json"


def trace_path(out: Path, document: dict) -> Path:
    return out / "traces" / f"{stem(document)}.jsonl"


def select(cases: list[dict], manifest: dict[str, dict], split: str,
           only: set[str] | None) -> list[dict]:
    """The documents to run, in case order, each with its manifest inputs.

    ``only`` holds Drucksachen or case ids.
    """
    documents: dict[str, dict] = {}
    for case in cases:
        doc = case["doc"]
        if split != "all" and case["split"] != split:
            continue
        if only is not None and doc not in only and case["id"] not in only:
            continue
        entry = manifest[doc]
        documents.setdefault(doc, {"doc": doc, "split": case["split"],
                                   "titel": entry["titel"], **entry["gesetzentwurf"]})
    return list(documents.values())


def run_one(task: Task, document: dict, text: str, model: str, tag: str,
            trace: Path | None = None, effort: str | None = None,
            max_turns: int | None = None) -> dict:
    """One call of the task's pass on one document. Returns the sample record."""
    max_turns = max_turns or task.max_turns
    record = {
        "task": task.name,
        "doc": document["doc"],
        "titel": document["titel"],
        "split": document["split"],
        "input_set": INPUT_SET,
        "inputs": [{"typ": "gesetzentwurf", "doc": document["doc"],
                    "file": document["file"], "sha256": document["sha256"],
                    "chars": len(text)}],
        "prompt_version": task.prompt_version,
        "model": model,
        "effort": effort,
        "max_turns": max_turns,
    }
    if len(text) > analyzer.MAX_INPUT_CHARS:
        return record | {"status": "oversize"}

    message = task.module.build_message(document["titel"], document["doc"], text)
    started = time.time()
    header = {k: record[k] for k in ("task", "doc", "input_set", "prompt_version",
                                     "model", "effort", "max_turns")}
    with tracelog.traced(trace, header | {"tag": tag}, message) as on_message:
        run = asyncio.run(task.module.run_query(message, model, on_message=on_message,
                                                effort=effort, max_turns=max_turns))
    analysis = run.output.model_dump()
    return record | {
        "status": "ok",
        "seconds": round(time.time() - started, 1),
        **structured.record_fields(run),
        "risk": task.risk(analysis),
        "analysis": analysis,
    }


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.harness run",
        description="Run the Lektor or the Angreifer on the test set, Entwurf only. "
        "Every document is a paid Claude call.",
    )
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="lektor")
    parser.add_argument("--cases", choices=report.ALL_CASE_SETS,
                        help="which case file of the task; defaults to its first")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--only", help="comma-separated Drucksachen or case ids, "
                        "e.g. 21/537,R-C1")
    parser.add_argument("--model", help="defaults to the task's shipped model")
    parser.add_argument("--effort", choices=config.EFFORTS,
                        help="reasoning effort; defaults to the task's shipped effort")
    parser.add_argument("--max-turns", type=int, metavar="N",
                        help="model responses per call")
    parser.add_argument("--tag", help="run directory name; defaults to "
                        "<prompt version>-<model>[-effort-<level>][-turns-<n>]")
    parser.add_argument("--force", action="store_true",
                        help="re-run documents that already have a sample")
    parser.add_argument("--concurrency", type=int, default=config.CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would run, make no calls")
    args = parser.parse_args(argv)

    task = tasks.get(args.task)
    case_set = report.case_set(task, args.cases)
    model = args.model or task.model
    effort = args.effort or task.effort
    max_turns = args.max_turns or task.max_turns
    tag = args.tag or config.default_tag(task, model, effort, max_turns)
    out = config.run_dir(task.name, tag)
    cases = report.load_cases(task, case_set)
    only = set(args.only.split(",")) if args.only else None
    documents = select(cases, load_manifest(), args.split, only)
    if not documents:
        print("no documents selected")
        return 1

    jobs = [d for d in documents if args.force or not sample_path(out, d).exists()]
    print(f"task={task.name} tag={tag} model={model} effort={effort} "
          f"max_turns={max_turns} prompt={task.prompt_version} "
          f"cases={case_set} split={args.split} -> {out}")
    if not jobs:
        print(f"nothing to run — all {len(documents)} documents have samples "
              "(use --force to re-run)")
    else:
        print(f"running {len(jobs)}: " + ", ".join(d["doc"] for d in jobs))
    if args.dry_run:
        return 0

    texts = {}
    for d in documents:
        path = TEXTS / d["file"]
        if sha256(path) != d["sha256"]:
            raise SystemExit(f"{d['file']}: sha256 mismatch — run make eval-lint")
        texts[d["doc"]] = path.read_text(encoding="utf-8")

    failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, task, d, texts[d["doc"]], model, tag,
                               trace_path(out, d), effort, max_turns): d
                   for d in jobs}
        for fut in as_completed(futures):
            d = futures[fut]
            label = stem(d)
            try:
                record = fut.result()
            except Exception as exc:  # one bad document never aborts the run
                failed += 1
                _write(failure_path(out, d), {
                    "task": task.name, "doc": d["doc"], "split": d["split"],
                    "input_set": INPUT_SET, "prompt_version": task.prompt_version,
                    "model": model, "effort": effort,
                    "max_turns": max_turns, "status": "failed",
                    "error_type": type(exc).__name__, "error": str(exc),
                    **structured.failure_fields(exc),
                    "traceback": "".join(traceback.format_exception(
                        type(exc), exc, exc.__traceback__)),
                })
                print(f"  {label}: FAILED {type(exc).__name__}: {exc}")
                continue
            failure_path(out, d).unlink(missing_ok=True)
            _write(sample_path(out, d), record)
            if record["status"] == "oversize":
                print(f"  {label}: oversize ({record['inputs'][0]['chars']} chars)")
            else:
                recovered = (f", rescued ({record['rescued_by']})"
                             if record["rescued_by"] else "")
                print(f"  {label}: {len(task.findings(record['analysis']))} findings, "
                      f"{record['num_turns']} turns, ${record['cost_usd'] or 0:.2f}{recovered}")

    if jobs:
        print(f"\nwrote {len(jobs) - failed}/{len(jobs)} samples")
    report.write_report(out, task, case_set, tag, split=args.split)
    return 1 if failed else 0
