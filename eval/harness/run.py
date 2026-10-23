"""Run a pass — Lektor or red-team — over the documents of a case set.

A recall run reads the draft without Beschlussempfehlungen. A precision run
(``--beschlussempfehlung``, Lektor) reads the draft with its pinned
Beschlussempfehlungen and selects every case with ``repaired_by``: a defect the
committee repaired, which the run must not report. The two are separate
measurements; neither reads the other's samples.

``--context`` picks the cases that select documents and get scored: ``none``
(the default) the cases the draft alone settles, ``bestandsrecht`` the cases
that need the existing law, ``all`` every case. Those run on the draft alone
(the same samples as a ``none`` run) or, for ``bestandsrecht`` with ``--oracle``,
with the paragraphs pinned for the document fed after the draft (Lektor only; its own
run directory).

``--retrieved`` (Lektor, not with ``--oracle``) feeds the existing law the
pipeline retrieves instead: ``bestandsrecht.provide`` selects, resolves and
fetches it for the pinned draft and fits it into the pipeline's budget. It is
pipeline output, not test content: the selection and the texts are frozen per
document under ``data/eval/bestandsrecht/<21-537>/`` and shared by every run, so
runs on other models or Lektor prompts read the same context, while a new
selection prompt, model or effort, or a changed resolver, gives a new one. Each
sample lists what was fed. It combines with every ``--context`` and with
``--beschlussempfehlung`` (the input as the pipeline sends it).

Inputs come from the test set alone: the pinned draft text, the title, the
pinned paragraphs and Beschlussempfehlungen in ``eval/testset/inputs.yaml``. The message is built and sent by the task's own
``build_message`` and ``run_query`` — the calls the pass ships with — so the run
measures the shipped prompt, model and input format without reading or writing
the database. A draft over ``analyzer.MAX_INPUT_CHARS`` is not sent, for either
task: the pipeline skips it on the same rule.

One sample per document lands in ``data/eval/runs/<task>-<tag>/samples/``; the
call's message stream in ``traces/``. After the calls the run is scored
(``report.py``).

    uv run python -m eval.harness run --split dev --only 21/537,21/1493
    uv run python -m eval.harness run --task exploit --split dev
    uv run python -m eval.harness run --context bestandsrecht --oracle --split dev
    uv run python -m eval.harness run --context all --split dev
    uv run python -m eval.harness run --beschlussempfehlung --split dev
    uv run python -m eval.harness run --retrieved --context bestandsrecht --split dev
"""

import argparse
import asyncio
import json
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend import bestandsrecht, tracelog
from backend.analysis import analyzer
from backend.gii import index as gii_index
from backend.llm import structured
from eval.testset.lint import TEXTS, load_manifest, sha256

from . import config, report, tasks
from .tasks import Task

# What a sample read: the Gesetzentwurf alone, with the pinned paragraphs, or with
# its Beschlussempfehlungen; ``+abgerufen`` adds the retrieved existing law.
ENTWURF = "entwurf"
ORACLE = "entwurf+bestandsrecht"
BESCHLUSSEMPFEHLUNG = "entwurf+beschlussempfehlung"
ABGERUFEN = "+abgerufen"

# ``(titel, text, budget) -> Context``: the retrieval for one document.
Provide = Callable[[str, str, int], bestandsrecht.Context]


def input_set(oracle: bool = False, committee: bool = False, retrieved: bool = False) -> str:
    base = BESCHLUSSEMPFEHLUNG if committee else ORACLE if oracle else ENTWURF
    return base + (ABGERUFEN if retrieved else "")


def stem(document: dict) -> str:
    """``21-537`` for Drucksache 21/537."""
    return document["file"].removesuffix(".txt")


def sample_path(out: Path, document: dict) -> Path:
    return out / "samples" / f"{stem(document)}.json"


def failure_path(out: Path, document: dict) -> Path:
    return out / "samples" / f"{stem(document)}.failed.json"


def trace_path(out: Path, document: dict) -> Path:
    return out / "traces" / f"{stem(document)}.jsonl"


def retrieval(out: Path, document: dict, entries: list[gii_index.Entry]) -> Provide:
    """The pipeline's retrieval for ``document``: selection and texts frozen in
    ``config.RETRIEVED_DIR`` across runs, logged to ``bestandsrecht/<21-537>.json``,
    the selection call traced beside the Lektor's."""
    def provide(titel: str, text: str, budget: int) -> bestandsrecht.Context:
        return bestandsrecht.provide(
            titel, text, freeze_dir=config.RETRIEVED_DIR / stem(document),
            log=out / "bestandsrecht" / f"{stem(document)}.json",
            trace=out / "traces" / f"{stem(document)}.select.jsonl",
            entries=entries, budget=budget)
    return provide


def select(cases: list[dict], manifest: dict[str, dict], split: str,
           only: set[str] | None, oracle: bool = False,
           committee: bool = False) -> list[dict]:
    """The documents to run, in case order, each with its manifest inputs.

    ``only`` holds Drucksachen or case ids. With ``oracle`` each document also
    carries its pinned paragraphs under ``bestandsrecht``; with ``committee`` its
    pinned Beschlussempfehlungen under ``beschlussempfehlungen``.
    """
    documents: dict[str, dict] = {}
    for case in cases:
        doc = case["doc"]
        if split != "all" and case["split"] != split:
            continue
        if only is not None and doc not in only and case["id"] not in only:
            continue
        entry = manifest[doc]
        document = documents.setdefault(doc, {"doc": doc, "split": case["split"],
                                              "titel": entry["titel"], **entry["gesetzentwurf"]})
        if oracle:
            document["bestandsrecht"] = entry.get("bestandsrecht", [])
        if committee:
            document["beschlussempfehlungen"] = entry.get("beschlussempfehlungen", [])
    return list(documents.values())


def read_pinned(file: str, digest: str) -> str:
    path = TEXTS / file
    if sha256(path) != digest:
        raise SystemExit(f"{file}: sha256 mismatch — run make eval-lint")
    return path.read_text(encoding="utf-8")


def run_one(task: Task, document: dict, text: str, model: str, tag: str,
            trace: Path | None = None, effort: str | None = None,
            max_turns: int | None = None,
            excerpts: list[tuple[dict, str]] | None = None,
            committee: list[tuple[dict, str]] | None = None,
            provide: Provide | None = None) -> dict:
    """One call of the task's pass on one document. Returns the sample record.

    ``excerpts`` are the document's pinned paragraphs with their text; given (even
    empty), the sample counts as an oracle run. ``committee`` are its pinned
    Beschlussempfehlungen with their text, sent as the pipeline sends them.
    ``provide`` retrieves the existing law within the characters the documents
    leave, as the pipeline does; the sample lists what it fed under ``inputs``
    and the decision under ``bestandsrecht``.
    """
    max_turns = max_turns or task.max_turns
    oracle = excerpts is not None
    excerpts = excerpts or []
    precision = committee is not None
    committee = committee or []
    record = {
        "task": task.name,
        "doc": document["doc"],
        "titel": document["titel"],
        "split": document["split"],
        "input_set": input_set(oracle, precision, provide is not None),
        "inputs": [{"typ": "gesetzentwurf", "doc": document["doc"],
                    "file": document["file"], "sha256": document["sha256"],
                    "chars": len(text)}]
        + [{"typ": "beschlussempfehlung", "doc": pin["doc"], "file": pin["file"],
            "sha256": pin["sha256"], "chars": len(be_text)} for pin, be_text in committee]
        + [{"typ": "bestandsrecht", "id": ex["id"], "gesetz": ex["gesetz"], "paragraph": ex["paragraph"],
            "fassung": str(ex["fassung"]), "file": ex["file"], "sha256": ex["sha256"],
            "chars": len(paragraph_text)} for ex, paragraph_text in excerpts],
        "prompt_version": task.prompt_version,
        "model": model,
        "effort": effort,
        "max_turns": max_turns,
    }
    total = sum(i["chars"] for i in record["inputs"])
    if total > analyzer.MAX_INPUT_CHARS:
        return record | {"status": "oversize"}

    context = {}
    if precision:
        context["context_docs"] = [(pin["doc"], be_text) for pin, be_text in committee]
    if oracle:
        context["bestandsrecht"] = [(ex["gesetz"], ex["paragraph"], str(ex["fassung"]),
                                     paragraph_text) for ex, paragraph_text in excerpts]
    if provide is not None:
        retrieved = provide(document["titel"], text, analyzer.MAX_INPUT_CHARS - total)
        context["bestandsrecht"] = retrieved.fed()
        record["inputs"] += [{"typ": "bestandsrecht", "id": d["document_id"],
                              "gesetz": d["gesetz"], "paragraph": d["dokumentnummer"],
                              "rolle": d["rolle"], "sha256": d["pdf_hash"],
                              "chars": d["text_chars"]} for d in retrieved.documents()]
        record["bestandsrecht"] = retrieved.summary()
    message = task.module.build_message(document["titel"], document["doc"], text, **context)
    started = time.time()
    header = {k: record[k] for k in ("task", "doc", "input_set", "prompt_version",
                                     "model", "effort", "max_turns")}
    if provide is not None:
        header |= {"inputs": record["inputs"], "bestandsrecht": record["bestandsrecht"]}
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
        description="Run the Lektor or the red-team pass on the test set. "
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
    parser.add_argument("--context", choices=report.CONTEXTS, default="none",
                        help="run and score the cases that require this context")
    parser.add_argument("--oracle", action="store_true",
                        help="feed the pinned Bestandsrecht after the draft "
                        "(Lektor, --context bestandsrecht)")
    parser.add_argument("--beschlussempfehlung", action="store_true",
                        help="precision run: feed the pinned Beschlussempfehlungen after "
                        "the draft and score every case with repaired_by as a defect "
                        "that must not be reported (Lektor)")
    parser.add_argument("--retrieved", action="store_true",
                        help="feed the existing law the pipeline retrieves (selection, GII) "
                        "after the draft and any Beschlussempfehlungen (Lektor, not with "
                        "--oracle; one cheap selection call per document not yet frozen)")
    args = parser.parse_args(argv)
    if args.oracle and (args.task != "lektor" or args.context != "bestandsrecht"):
        parser.error("--oracle needs --task lektor and --context bestandsrecht")
    if args.beschlussempfehlung and (args.task != "lektor" or args.oracle
                                     or args.context != "none"):
        parser.error("--beschlussempfehlung needs --task lektor, without --oracle or --context")
    if args.retrieved and (args.task != "lektor" or args.oracle):
        parser.error("--retrieved needs --task lektor, without --oracle")
    inputs = input_set(args.oracle, args.beschlussempfehlung, args.retrieved)

    task = tasks.get(args.task)
    case_set = report.case_set(task, args.cases)
    model = args.model or task.model
    effort = args.effort or task.effort
    max_turns = args.max_turns or task.max_turns
    tag = args.tag or config.default_tag(task, model, effort, max_turns, oracle=args.oracle,
                                         committee=args.beschlussempfehlung,
                                         retrieved=args.retrieved)
    out = config.run_dir(task.name, tag)
    cases = report.load_cases(task, case_set, args.context, repaired=args.beschlussempfehlung)
    only = set(args.only.split(",")) if args.only else None
    documents = select(cases, load_manifest(), args.split, only, oracle=args.oracle,
                       committee=args.beschlussempfehlung)
    if args.beschlussempfehlung:
        without = [d["doc"] for d in documents if not d["beschlussempfehlungen"]]
        if without:
            print("no Beschlussempfehlung pinned, not run: " + ", ".join(without))
        documents = [d for d in documents if d["beschlussempfehlungen"]]
    if not documents:
        print("no documents selected")
        return 1

    jobs = [d for d in documents if args.force or not sample_path(out, d).exists()]
    print(f"task={task.name} tag={tag} model={model} effort={effort} "
          f"max_turns={max_turns} prompt={task.prompt_version} "
          f"cases={case_set} context={'all' if args.beschlussempfehlung else args.context} "
          f"split={args.split} "
          f"input={inputs} -> {out}")
    if not jobs:
        print(f"nothing to run — all {len(documents)} documents have samples "
              "(use --force to re-run)")
    else:
        print(f"running {len(jobs)}: " + ", ".join(d["doc"] for d in jobs))
    if args.dry_run:
        return 0

    texts = {d["doc"]: read_pinned(d["file"], d["sha256"]) for d in documents}
    excerpts = {d["doc"]: [(ex, read_pinned(ex["file"], ex["sha256"]))
                           for ex in d["bestandsrecht"]]
                for d in documents if "bestandsrecht" in d}
    committee = {d["doc"]: [(pin, read_pinned(pin["file"], pin["sha256"]))
                            for pin in d["beschlussempfehlungen"]]
                 for d in documents if "beschlussempfehlungen" in d}
    entries = gii_index.load() if args.retrieved and jobs else None

    failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, task, d, texts[d["doc"]], model, tag,
                               trace_path(out, d), effort, max_turns,
                               excerpts.get(d["doc"]), committee.get(d["doc"]),
                               retrieval(out, d, entries) if args.retrieved else None): d
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
                    "input_set": inputs, "prompt_version": task.prompt_version,
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
                print(f"  {label}: oversize "
                      f"({sum(i['chars'] for i in record['inputs'])} chars)")
            else:
                recovered = (f", rescued ({record['rescued_by']})"
                             if record["rescued_by"] else "")
                fit = record.get("bestandsrecht")
                fed = (f", Bestandsrecht {fit['decision']} ({fit['fed_count']} fed, "
                       f"{fit['left_out_count']} left out)" if fit else "")
                print(f"  {label}: {len(task.findings(record['analysis']))} findings, "
                      f"{record['num_turns']} turns, ${record['cost_usd'] or 0:.2f}"
                      f"{recovered}{fed}")

    if jobs:
        print(f"\nwrote {len(jobs) - failed}/{len(jobs)} samples")
    report.write_report(out, task, case_set, tag, split=args.split, context=args.context,
                        repaired=args.beschlussempfehlung)
    return 1 if failed else 0
