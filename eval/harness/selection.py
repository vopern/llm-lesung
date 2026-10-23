"""Score the Bestandsrecht selection against the paragraphs the cases need.

For every document with a ``requires_context: bestandsrecht`` case, the
shipped selection runs on the pinned draft (``bestandsrecht.select``, one cheap
Claude call) and its references are resolved in GII (``resolve``, candidate zips
downloaded, their texts read from them for the sizes). Each case lists the GII ids it needs under
``bestandsrecht``; a needed id is a ``hit`` when the selection holds it,
``paragraph missed`` when the selection holds other paragraphs of its law, and
``law missed`` when it holds none; a hit is fed as ``wortlaut`` or, inside a long
cited range, only as one of the range's ``ueberschriften``. Per document the
blocks the pipeline would feed are sized (characters, all and amended only).
Recall is reported per ``rolle``:
``nicht_genannt`` paragraphs are not named in the draft's Wortlaut, so no
reading of the draft reaches them; they are counted apart.

One sample per document in ``data/eval/runs/select-<tag>/samples/``; a document
with a sample is not run again (``--force`` re-runs it), so re-scoring is free.

    uv run python -m eval.harness select --split dev
    uv run python -m eval.harness select --cases lektor --split dev
    uv run python -m eval.harness select --rescore --split dev
"""

import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend import bestandsrecht
from backend import config as backend_config
from backend.bestandsrecht.resolve import resolve
from backend.gii import index
from backend.gii.law import unit_id
from backend.llm import structured
from eval import page as p
from eval.testset.lint import load_manifest

from . import config, report, run, tasks

ROLLEN = ["geaendert", "verwiesen", "nicht_genannt"]
REACHABLE = ("geaendert", "verwiesen")
TONE = {"hit": "good", "paragraph missed": "warn", "law missed": "bad",
        "failed": "bad", "not_run": "muted"}


def default_tag(model: str, effort: str) -> str:
    return f"{backend_config.BESTANDSRECHT_PROMPT_VERSION}-{model}-effort-{effort}"


def select_one(document: dict, text: str, model: str, effort: str, trace: Path,
               entries: list[index.Entry]) -> dict:
    started = time.time()
    selected = bestandsrecht.select(document["titel"], text, trace, model, effort)
    resolution = resolve(selected.references, entries)
    fetched = [bestandsrecht.fetch(pid, resolution) for pid in resolution.ids]
    return {"doc": document["doc"], "titel": document["titel"], "split": document["split"],
            "file": document["file"], "sha256": document["sha256"], "status": "ok",
            "seconds": round(time.time() - started, 1),
            **bestandsrecht.record(selected, resolution, fetched)}


def score_case(case: dict, sample: dict | None) -> list[dict]:
    """One row per paragraph the case needs."""
    rows = []
    for needed in case["bestandsrecht"]:
        slug, unit = needed["id"].split("/", 1)
        row = {"case": case["id"], "doc": case["doc"], "split": case["split"],
               "id": needed["id"], "rolle": needed["rolle"], "unresolved": []}
        if sample is None or sample.get("status") != "ok":
            rows.append(row | {"verdict": "failed" if sample else "not_run"})
            continue
        ids = set(sample["ids"])
        if needed["id"] in ids:
            verdict = "hit"
            forms = {b["form"] for b in sample.get("blocks", []) if needed["id"] in b["ids"]}
            row["fed_as"] = "wortlaut" if "wortlaut" in forms else next(iter(forms), None)
        elif any(i.split("/", 1)[0] == slug for i in ids):
            verdict = "paragraph missed"
        else:
            verdict = "law missed"
        if verdict != "hit":
            # A reference of the same § that GII did not resolve: Resolve lost it, not Select.
            row["unresolved"] = [f"{u['gesetz']} {u['paragraph']}: {u['reason']}"
                                 for u in sample["unresolved"]
                                 if unit_id(u["paragraph"]) == unit]
        rows.append(row | {"verdict": verdict})
    return rows


def _recall(rows: list[dict]) -> dict:
    hits = sum(r["verdict"] == "hit" for r in rows)
    return {"needed": len(rows), "hit": hits, "recall": hits / len(rows) if rows else None}


def _sizes(blocks: list[dict] | None) -> dict:
    """Characters of the blocks the pipeline would feed: all, and amended only."""
    if blocks is None:
        return {"chars": None, "chars_geaendert": None, "ranges": None}
    return {"chars": sum(b["chars"] for b in blocks),
            "chars_geaendert": sum(b["chars"] for b in blocks if b["rolle"] == "geaendert"),
            "ranges": sum(b["form"] == "ueberschriften" for b in blocks)}


def summarize(rows: list[dict], samples: dict[str, dict], documents: list[dict],
              settings: dict) -> dict:
    per_doc = []
    for d in documents:
        s = samples.get(d["doc"])
        ok = s is not None and s.get("status") == "ok"
        reasons: dict[str, int] = {}
        for u in s["unresolved"] if ok else []:
            reason = u["reason"].split(":")[0]
            reasons[reason] = reasons.get(reason, 0) + 1
        per_doc.append({
            "doc": d["doc"], "titel": d["titel"], "status": s["status"] if s else "not_run",
            "references": len(s["references"]) if ok else None,
            "ids": len(s["ids"]) if ok else None,
            "unresolved": len(s["unresolved"]) if ok else None,
            "unresolved_reasons": reasons,
            "unbelegt": len(s["unbelegt"]) if ok and "unbelegt" in s else None,
            "cost_usd": s["call"].get("cost_usd") if ok else None,
            **_sizes(s["blocks"] if ok and "blocks" in s else None),
        })
    costs = [d["cost_usd"] for d in per_doc if d["cost_usd"] is not None]
    return settings | {
        "cases": len({r["case"] for r in rows}),
        "documents": len(documents),
        "reachable": _recall([r for r in rows if r["rolle"] in REACHABLE]),
        "by_rolle": {rolle: _recall([r for r in rows if r["rolle"] == rolle]) for rolle in ROLLEN},
        "verdicts": {v: sum(r["verdict"] == v for r in rows) for v in TONE},
        "cost_usd": sum(costs) if costs else None,
        "chars": sum(d["chars"] or 0 for d in per_doc),
        "unbelegt": sum(d["unbelegt"] or 0 for d in per_doc),
        "per_document": per_doc,
    }


def render(summary: dict, rows: list[dict]) -> str:
    r = summary["reachable"]
    head = (f"<h1>Bestandsrecht selection</h1><p class=\"small\">{p.esc(summary['task'])} · "
            f"cases {p.esc(summary['case_set'])} · split {p.esc(summary['split'])} · "
            f"prompt {p.esc(summary['prompt_version'])} · {p.esc(summary['model'])} · "
            f"effort {p.esc(summary['effort'])}</p>")
    about = p.panel("What this measures", (
        "<p>Each case that needs existing law lists the paragraphs a reviewer must read beside "
        "the draft, as GII ids. The selection call reads the draft's Wortlaut and names the "
        "paragraphs it amends or cites; GII resolves them to ids. A needed id is a hit when "
        "the selection holds it, fed as its wording or, inside a long cited range, as a heading. "
        "Sizes are those of the blocks the pipeline would feed; no text is judged here.</p>"
        "<p><b>nicht_genannt</b> paragraphs are not named in the Wortlaut (a reverse "
        "citation, a general clause, a figure only the Begründung uses): no reading of the "
        "draft reaches them, so they are counted apart from the recall.</p>"))
    tiles = p.tiles([
        p.tile(p.pct(r["recall"]), f"recall, {r['hit']} of {r['needed']} reachable"),
        *[p.tile(f"{v['hit']}/{v['needed']}", rolle)
          for rolle, v in summary["by_rolle"].items()],
        p.meta_tile([(str(summary["cases"]), "cases"), (str(summary["documents"]), "documents"),
                     (p.money(summary["cost_usd"]), "cost")]),
        p.meta_tile([(f"{summary['chars']:,}", "chars fed"), (str(summary["unbelegt"]), "beleg not found")]),
    ])
    case_rows = [
        f"<tr><td>{p.esc(x['case'])}</td><td>{p.esc(x['doc'])}</td>"
        f"<td><a href=\"https://www.gesetze-im-internet.de/{p.esc(x['id'])}.html\">"
        f"{p.esc(x['id'])}</a></td><td>{p.esc(x['rolle'])}</td>"
        f"<td>{p.badge(x['verdict'], TONE[x['verdict']])}</td>"
        f"<td class=\"small\">{p.esc(x.get('fed_as') or '')}</td>"
        f"<td class=\"small\">{p.esc('; '.join(x['unresolved']))}</td></tr>" for x in rows]
    doc_rows = [
        f"<tr><td>{p.esc(d['doc'])}</td><td class=\"small\">{p.esc(d['titel'])}</td>"
        f"<td>{p.esc(d['status'])}</td><td class=\"num\">{p.esc(d['references'])}</td>"
        f"<td class=\"num\">{p.esc(d['ids'])}</td><td class=\"num\">{p.esc(d['unresolved'])}</td>"
        f"<td class=\"small\">{p.esc(', '.join(f'{k} {v}' for k, v in d['unresolved_reasons'].items()))}</td>"
        f"<td class=\"num\">{p.esc(d['unbelegt'])}</td><td class=\"num\">{p.esc(d['chars'])}</td>"
        f"<td class=\"num\">{p.esc(d['chars_geaendert'])}</td><td class=\"num\">{p.esc(d['ranges'])}</td>"
        f"<td class=\"num\">{p.money(d['cost_usd'])}</td></tr>"
        for d in summary["per_document"]]
    body = (head + about + tiles
            + "<h2>Needed paragraphs</h2>"
            + p.table(["Case", "Drucksache", "GII id", "Rolle", "Verdict", "Fed as",
                       "Unresolved reference"],
                      case_rows)
            + "<h2>Selection per document</h2>"
            + p.table(["Drucksache", "Titel", "Status", "References", "GII ids", "Unresolved",
                       "Why", "Beleg not found", "Chars", "Chars amended", "Ranges as headings", "Cost"],
                      doc_rows, numeric_from=3))
    return p.page("Bestandsrecht selection", body)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.harness select",
        description="Score the Bestandsrecht selection against the paragraphs the "
        "cases need. Every document not yet sampled is one cheap Claude call.")
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="lektor")
    parser.add_argument("--cases", choices=report.ALL_CASE_SETS,
                        help="which case file of the task; defaults to its first")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--only", help="comma-separated Drucksachen or case ids")
    parser.add_argument("--model", default=backend_config.BESTANDSRECHT_MODEL)
    parser.add_argument("--effort", choices=config.EFFORTS,
                        default=backend_config.BESTANDSRECHT_EFFORT)
    parser.add_argument("--tag", help="run directory name; defaults to "
                        "<prompt version>-<model>-effort-<level>")
    parser.add_argument("--force", action="store_true",
                        help="re-run documents that already have a sample")
    parser.add_argument("--rescore", action="store_true",
                        help="score the stored samples only, make no calls")
    parser.add_argument("--concurrency", type=int, default=config.CONCURRENCY)
    args = parser.parse_args(argv)

    task = tasks.get(args.task)
    case_set = report.case_set(task, args.cases)
    tag = args.tag or default_tag(args.model, args.effort)
    out = config.run_dir("select", tag)
    cases = report.load_cases(task, case_set, "bestandsrecht")
    only = set(args.only.split(",")) if args.only else None
    documents = run.select(cases, load_manifest(), args.split, only)
    if not documents:
        print("no documents selected")
        return 1
    print(f"selection tag={tag} cases={case_set} split={args.split} "
          f"documents={len(documents)} -> {out}")

    jobs = [] if args.rescore else [
        d for d in documents if args.force or not run.sample_path(out, d).exists()]
    failed = 0
    if jobs:
        print(f"running {len(jobs)}: " + ", ".join(d["doc"] for d in jobs))
        entries = index.load()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(select_one, d, run.read_pinned(d["file"], d["sha256"]),
                                   args.model, args.effort,
                                   out / "traces" / f"{run.stem(d)}.select.jsonl", entries): d
                       for d in jobs}
            for fut in as_completed(futures):
                d = futures[fut]
                try:
                    record = fut.result()
                except Exception as exc:  # one bad document never aborts the run
                    failed += 1
                    _write(run.failure_path(out, d), {
                        "doc": d["doc"], "split": d["split"], "status": "failed",
                        "error_type": type(exc).__name__, "error": str(exc),
                        **structured.failure_fields(exc),
                        "traceback": "".join(traceback.format_exception(
                            type(exc), exc, exc.__traceback__))})
                    print(f"  {d['doc']}: FAILED {type(exc).__name__}: {exc}")
                    continue
                run.failure_path(out, d).unlink(missing_ok=True)
                _write(run.sample_path(out, d), record)
                print(f"  {d['doc']}: {len(record['references'])} references, "
                      f"{len(record['unbelegt'])} beleg not found, "
                      f"{len(record['ids'])} ids, {len(record['unresolved'])} unresolved, "
                      f"{_sizes(record['blocks'])['chars']} chars, "
                      f"${record['call'].get('cost_usd') or 0:.3f}")

    samples = report.load_samples(out)
    docs = {d["doc"] for d in documents}
    rows = [row for c in cases if c["doc"] in docs
            and (args.split == "all" or c["split"] == args.split)
            and (only is None or c["doc"] in only or c["id"] in only)
            for row in score_case(c, samples.get(c["doc"]))]
    settings = {"task": task.name, "case_set": case_set, "split": args.split, "tag": tag,
                "prompt_version": backend_config.BESTANDSRECHT_PROMPT_VERSION,
                "model": args.model, "effort": args.effort}
    summary = summarize(rows, samples, documents, settings)
    name = f"{case_set}-{args.split}"
    _write(out / f"summary-{name}.json", summary | {"rows": rows})
    html_path = out / f"report-{name}.html"
    html_path.write_text(render(summary, rows), encoding="utf-8")

    r = summary["reachable"]
    print(f"\nrecall {p.pct(r['recall'])} ({r['hit']}/{r['needed']} reachable); "
          + ", ".join(f"{k} {v['hit']}/{v['needed']}" for k, v in summary["by_rolle"].items()))
    for row in rows:
        if row["verdict"] != "hit":
            extra = f"  [{'; '.join(row['unresolved'])}]" if row["unresolved"] else ""
            print(f"  {row['case']:12} {row['id']:28} {row['rolle']:14} {row['verdict']}{extra}")
        elif row.get("fed_as") == "ueberschriften":
            print(f"  {row['case']:12} {row['id']:28} {row['rolle']:14} hit, headings only")
    print(f"-> {html_path}")
    return 1 if failed else 0
