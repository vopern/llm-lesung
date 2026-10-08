"""Render one scored run as a self-contained HTML report.

Offline and free; reads ``results-<name>.json`` and the test-set YAML behind
``eval.testset.about``. The page stands on its own: what the evaluation set is and how
each case file was mined, every scored case with its anchor, its story and its
source, and what the verdicts are — passage positions, not a judgement that the
defect was found — because nothing else on it would stop a reader from taking
"hit" at face value.

    uv run python -m eval.harness html --split dev --tag <tag> [--task angreifer]
"""

import argparse
import json
from pathlib import Path

from eval import page
from eval.testset import about

from . import config, tasks

VERDICT_ORDER = ["hit", "near", "miss", "touched", "clear", "fired", "quiet", "unanchored",
                 "oversize", "failed", "not_run"]
TONE = {"hit": "good", "near": "warn", "miss": "muted", "clear": "muted", "quiet": "good",
        "unanchored": "muted", "not_run": "muted", "touched": "bad", "fired": "bad",
        "failed": "bad", "oversize": "bad"}

_POSITION = (
    "A verdict is a position check: <i>hit</i> means a finding's quote overlaps the case's "
    "anchor, <i>near</i> that one lies within {near} characters of it, <i>miss</i> neither. It "
    "does not say the finding names the expected {thing} — a hit can describe a different "
    "{thing} in the same passage, and a finding that names the {thing} but quotes another "
    "passage scores as a miss. Compare the matched finding with the expected {thing} before "
    "counting it. ")

# Per task: what a case expects, and what the verdicts can and cannot say.
TEXT = {
    "lektor": {
        "note": _POSITION.replace("{thing}", "defect") + (
            "<b>The findings themselves are not scored.</b> This page measures recall — were "
            "the known defects found — and never precision: a finding that matches no case may "
            "be a real defect the evaluation set does not list, or it may be wrong, and nothing "
            "here tells the two apart. A run with more findings is therefore not a better run."),
        "kind": {"positiv": "a defect the analysis should find",
                 "negativ": "a claim the analysis must not make",
                 "invers": "a gap already closed — must not be reported as still open",
                 "behoben": "a defect the Beschlussempfehlung in the input repaired — "
                            "must not be reported"},
        "expected": "Expected finding",
    },
    "angreifer": {
        "note": _POSITION.replace("{thing}", "attack") + (
            "The Angreifer reads a draft that may be technically flawless and reports what a "
            "bad-faith actor gets out of it; each finding is one attack, with actor, steps, "
            "gain and the missing safeguard. On drafts that offer nothing to exploit, "
            "<i>fired</i> means the pass reported attacks anyway and <i>quiet</i> that it "
            "stayed silent — the only precision signal on this page. Elsewhere a finding that "
            "matches no case may be a real attack the evaluation set does not list, or it may "
            "be invented, and nothing here tells the two apart."),
        "kind": {"positiv": "an attack the pass should find",
                 "negativ": "a draft with nothing to exploit — any attack is a false alarm",
                 "invers": "a gap already closed — must not be reported as still open"},
        "expected": "Expected attack",
    },
}
# A precision run: the draft with its Beschlussempfehlungen, every case repaired.
PRECISION_NOTE = (
    "This run read each draft together with its Beschlussempfehlungen, as the pipeline does. "
    "Every case here is a drafting defect the committee repaired, so the analysis must not "
    "report it. <i>clear</i> means no finding lands within {near} characters of the case's "
    "anchor; <i>touched</i> means one does — a candidate re-report to read, since a finding "
    "can say something else about the same passage. The category column shows whether that "
    "finding has the defect's category, the stronger sign of a re-report. Findings that quote "
    "the Beschlussempfehlung cannot be placed in the draft and never touch an anchor. "
    "<b>This page measures precision on repaired defects only</b>, independent of whether a "
    "run without the Beschlussempfehlung finds them; findings that match no case are not "
    "scored.")
CONTEXT = {"none": "none — the draft alone settles it",
           "bestandsrecht": "law outside the draft",
           "eu-recht": "EU law",
           "external-facts": "facts from outside the documents"}
NO_ANCHOR = ("none — the defect is something the draft does not say, so there is no "
             "wording to point at")


def _badge(verdict: str) -> str:
    return page.badge(verdict, TONE.get(verdict, "muted"))


def _about(cases_file: str, scored: int, split: str) -> str:
    """What the evaluation set is, how the file scored here was mined, how much ran."""
    here = f"{scored} of them in this run" + ("" if split == "all" else f", split {split}")
    files = "".join(f'<div class="file"><b>{page.esc(f["name"])}</b>'
                    f'<div class="small muted">{page.esc(f["title"])} · {page.esc(f["counts"])} · '
                    f'{page.esc(here)}</div>'
                    f'<div class="small">{page.esc(f["mined"])}</div></div>'
                    for f in about.files() if f["name"] == cases_file)
    return page.panel("The evaluation set",
                      f'<p class="small">{page.esc(about.INTRO)}</p>{files}')


def _run_config(summary: dict) -> str:
    keys = lambda d: ", ".join(str(k) for k in d) or "–"
    efforts = ", ".join("default" if k in (None, "None", "null") else str(k)
                        for k in summary["efforts"])
    return (f"{keys(summary['models'])} · effort {efforts or '–'} · max turns "
            f"{keys(summary['max_turns'])} · prompt {keys(summary['prompt_versions'])}")


def _model_name(model: str) -> str:
    """``claude-opus-4-8`` -> ``Claude Opus 4.8``."""
    words = model.split("-")
    version = [w for w in words if w.isdigit()]
    name = [w.capitalize() for w in words if not w.isdigit()]
    return " ".join(name + ([".".join(version)] if version else []))


def _heading(summary: dict) -> tuple[str, str, str]:
    """``(title, headline, config line)``: what was measured, then how."""
    cases = about.FILES.get(summary["cases_file"], {}).get("title", summary["cases_file"])
    split = summary.get("split", "all")
    prompts = ", ".join(str(k) for k in summary["prompt_versions"]) or "–"
    efforts = ", ".join("default" if k in (None, "None", "null") else str(k)
                        for k in summary["efforts"]) or "–"
    models = ", ".join(_model_name(str(m)) for m in summary["models"]) or "–"
    config_line = " · ".join([
        f"Prompt {prompts}",
        models,
        f"reasoning effort {efforts}",
        f"{summary['documents']} drafts",
        f"scored {summary['generated_at'][:10]}"])
    title = tasks.get(summary["task"]).title
    context = summary.get("requires_context", "none")
    if _precision(summary):
        title = title.replace("evaluation", "precision evaluation")
        cases += f" (repaired defects, input {summary['input_set']})"
    elif context != "none":
        cases += f" ({context} cases, input {summary['input_set']})"
    return (f"{title} · {cases} · {split} · {prompts} · {models}",
            f"{title}: {cases}, " + ("all splits" if split == "all" else f"{split} split"),
            config_line)


def _precision(summary: dict) -> bool:
    return summary.get("measures") == "precision"


def _tiles(summary: dict) -> str:
    rec = summary["recall"]
    split = summary.get("split", "all")
    entry = rec.get(split) if split != "all" else None
    items = []
    for name, e in ([(split, entry)] if entry else list(rec.items())):
        if _precision(summary):
            rep = e.get("behoben", {}).get("all", {})
            items.append(page.tile(f'{page.pct(rep.get("precision"))} <small class="muted">/ '
                                   f'{page.pct(rep.get("precision_category"))}</small>',
                                   "ratio: clear / ratio: clear + touched in another category"))
            items.append(page.meta_tile([(name, "split"),
                                         (str(rep.get("scorable", 0)), "evaluated cases"),
                                         (str(rep.get("touched_same_category", 0)),
                                          "touched, same category")]))
            continue
        pos = e["all"]
        items.append(page.tile(f'{page.pct(pos["strict"])} <small class="muted">/ '
                               f'{page.pct(pos["lenient"])}</small>',
                               "ratio: hit / ratio: hit + near"))
        items.append(page.meta_tile([(name, "split"),
                                     (str(pos["scorable"]), "evaluated cases")]))
        neg = e["negatives"]
        if neg.get("quiet") or neg.get("fired"):
            items.append(page.tile(f'{neg.get("quiet", 0)} / {neg.get("quiet", 0) + neg.get("fired", 0)}',
                                   "drafts with nothing to exploit left quiet"))
    runs = summary["runs"]
    items.append(page.tile(f"{runs.get('ok', 0)} / {summary['documents']}",
                           "drafts analyzed"
                           + (f" · {runs['failed']} failed" if runs.get("failed") else "")))
    items.append(page.tile(str(summary["findings"]["total"]), "findings"))
    if summary.get("words_per_sentence") is not None:
        items.append(page.tile(str(summary["words_per_sentence"]), "words per sentence"))
    # Cost, time and rescues are run mechanics, not a result: one tile, last.
    detail = ", ".join(f"{k} {v}" for k, v in summary["rescued"].items())
    items.append(page.meta_tile([
        (page.money(summary["cost_usd"]), "cost"),
        (page.duration(summary["seconds"]), "model time"),
        (str(sum(summary["rescued"].values())),
         f"rescued outputs ({detail})" if detail else "rescued outputs")]))
    return page.tiles(items)


def _category_table(summary: dict) -> str:
    rows = []
    for split, cats in summary["recall_by_category"].items():
        for cat, c in cats.items():
            counts = c["counts"]
            rows.append(f"<tr><td>{page.esc(split)}</td><td class=\"cat\">{page.esc(cat)}</td>"
                        + "".join(f'<td class="num">{counts.get(v, 0)}</td>'
                                  for v in ("hit", "near", "miss"))
                        + f'<td class="num">{sum(counts.get(v, 0) for v in ("failed", "oversize", "not_run"))}</td>'
                        + f'<td class="num">{page.pct(c["strict"])}</td></tr>')
    return page.table(["split", "expected category", "hit", "near", "miss", "not scored",
                       "hit ratio"], rows, numeric_from=2)


def _finding(f: dict, matched: bool) -> str:
    quote = (f"<blockquote>{page.esc(f['quote'])}</blockquote>" if f.get("quote")
             else '<div class="small muted">no quote</div>')
    located = ("" if f.get("located") or not f.get("quote")
               else " " + page.badge("quote not in draft", "bad"))
    return (f'<div class="finding{" matched" if matched else ""}">'
            f'<div><span class="cat">#{f["index"]} {page.esc(f["category"])} · '
            f'{page.esc(f["severity"])}</span>{located}</div>'
            f"<div><b>{page.esc(f['title'])}</b></div>"
            f"<div>{page.esc(f['description'])}</div>{quote}</div>")


def _case_doc(e: dict, text: dict) -> str:
    """One case in full: what it expects, what it points at, how it came about."""
    rows = [("Case is", page.esc(text["kind"].get(e["kind"], e["kind"]))),
            ("Expected category", f'<span class="cat">{page.esc(e["expected_category"])}</span>')]
    if e.get("expected_severity"):
        rows.append(("Expected severity", page.esc(e["expected_severity"])))
    rows += [("Knowledge needed",
              page.esc(CONTEXT.get(e["requires_context"], e["requires_context"]))),
             ("Where in the draft", page.esc(e["expected_passage"])),
             (text["expected"], page.esc(e["expected_defect"]))]
    if e.get("forbidden_claim"):
        rows.append(("Must not be claimed", page.esc(e["forbidden_claim"])))
    if e.get("repaired_by"):
        rows.append(("Repaired by", f"Beschlussempfehlung {page.esc(e['repaired_by'])}"))
    rows.append(("Anchor in the draft",
                 f'<blockquote>{page.esc(e["anchor"])}</blockquote>'
                 '<div class="small muted">A finding counts as a hit when its quote '
                 'overlaps this wording.</div>' if e.get("anchor")
                 else f'<span class="small muted">{page.esc(NO_ANCHOR)}</span>'))
    background = page.prose(e["story"]) if e.get("story") else ""
    if e.get("source"):
        background += f'<p class="small muted"><b>Source:</b> {page.esc(e["source"])}</p>'
    if background:
        rows.append(("Background",
                     '<details class="bg"><summary>How this case came about</summary>'
                     f'<div class="bg-body">{background}</div></details>'))
    fields = "".join(f"<dt>{page.esc(label)}</dt><dd>{value}</dd>" for label, value in rows)
    return (f'<div class="case"><div><b>{page.esc(e["id"])}</b></div>'
            f'<dl class="fields">{fields}</dl></div>')


def _verdict_table(run: dict) -> str:
    """Per case: where the findings landed relative to the anchor."""
    rows = []
    for v in run["verdicts"]:
        matched = [m["index"] for m in v.get("matched", []) if "index" in m]
        match_txt = "".join(f'<div class="small">#{i} {page.esc(run["findings"][i]["title"])}</div>'
                            for i in matched) or "–"
        cat = ("–" if v.get("category_match") is None
               else "matches" if v["category_match"] else "differs")
        dist = "–" if v.get("distance") is None else str(v["distance"])
        rows.append(f'<tr><td><b>{page.esc(v["id"])}</b></td><td>{_badge(v["verdict"])}</td>'
                    f'<td class="num">{page.esc(dist)}</td><td>{page.esc(cat)}</td>'
                    f"<td>{match_txt}</td></tr>")
    return page.table(["case", "verdict", "distance", "category", "matched findings"], rows)


def _document(doc: dict, text: dict) -> str:
    """One draft: its cases documented, then what the analysis made of them."""
    run = doc["run"]
    present = sorted({v["verdict"] for v in run["verdicts"]} if run else {"not_run"},
                     key=VERDICT_ORDER.index)
    parts = [f"<h3>Cases ({len(doc['expectations'])})</h3>"]
    parts += [_case_doc(e, text) for e in doc["expectations"]]
    if run is None:
        parts.append('<p class="muted">Not run.</p>')
    else:
        head = (f'<p class="small muted">{page.esc(run["status"])} · {page.money(run.get("cost_usd"))} · '
                f'{page.duration(run.get("seconds"))} · rescued: {page.esc(run.get("rescued_by") or "no")} · '
                f'severity {page.esc(run.get("risk") or "–")}</p>')
        if run.get("error"):
            head += f'<p class="small"><b>Error:</b> {page.esc(run["error"])}</p>'
        if run.get("summary"):
            head += f'<h3 style="margin-top:14px">Summary</h3><p>{page.esc(run["summary"])}</p>'
        matched_all = {m["index"] for v in run["verdicts"] for m in v.get("matched", [])
                       if "index" in m}
        findings = "".join(_finding(f, f["index"] in matched_all) for f in run.get("findings", []))
        parts.append('<h3 style="margin-top:18px">Analysis</h3>' + head
                     + _verdict_table(run)
                     + (f'<h3 style="margin-top:14px">Findings ({len(run["findings"])})</h3>{findings}'
                        if run.get("findings") else ""))
    badges = " ".join(_badge(v) for v in present)
    return (f'<details class="doc" data-v="{page.esc(" ".join(present))}"><summary>'
            f'<b>{page.esc(doc["doc"])}</b> {badges} <span class="small muted">{page.esc(doc["split"])} · '
            f'{len(doc["expectations"])} case(s)</span><span class="small">{page.esc(doc["titel"])}</span>'
            f'</summary><div class="body">{"".join(parts)}</div></details>')


def render_run(results: dict) -> str:
    """One run: headline numbers, recall per category, every document."""
    s = results["summary"]
    docs = results["documents"]
    present = sorted({v["verdict"] for d in docs if d["run"] for v in d["run"]["verdicts"]}
                     | ({"not_run"} if any(not d["run"] for d in docs) else set()),
                     key=VERDICT_ORDER.index)
    title, headline, config_line = _heading(s)
    text = TEXT[s["task"]]
    body = (f"<h1>{page.esc(headline)}</h1>"
            f'<div class="muted">{page.esc(config_line)}</div>'
            + _about(s["cases_file"], sum(len(d["expectations"]) for d in docs),
                     s.get("split", "all"))
            + page.note("Reading the verdicts.",
                        (PRECISION_NOTE if _precision(s) else text["note"]).format(
                            near=s["near_chars"]))
            + _tiles(s)
            + ("" if _precision(s)
               else "<h2>Passage recall by expected category</h2>" + _category_table(s))
            + f"<h2>Documents ({len(docs)})</h2>" + page.filters("details.doc", present)
            + "".join(_document(d, text) for d in docs)
            + "<h2>Run details</h2>"
            f'<div class="muted small">{page.esc(s["cases_file"])} · split {page.esc(s.get("split", "all"))} · '
            f'input {page.esc(s["input_set"])} · cases requiring context: {page.esc(s["requires_context"])} · '
            f'scored {page.esc(s["generated_at"])}</div>'
            f'<div class="muted small">{page.esc(_run_config(s))} · run {page.esc(s["tag"])}</div>')
    return page.page(title, body)


def write_run(out: Path, name: str) -> Path:
    results = json.loads((out / f"results-{name}.json").read_text(encoding="utf-8"))
    path = out / f"report-{name}.html"
    path.write_text(render_run(results), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    from . import report

    parser = argparse.ArgumentParser(
        prog="python -m eval.harness html",
        description="Render one scored run as a self-contained HTML report in its run "
                    "directory. Offline, free. Run `report` first.",
    )
    parser.add_argument("--tag", required=True, help="run directory name")
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="lektor")
    parser.add_argument("--cases", choices=report.ALL_CASE_SETS,
                        help="which case file of the task; defaults to its first")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    parser.add_argument("--context", choices=report.CONTEXTS, default="none")
    parser.add_argument("--beschlussempfehlung", action="store_true",
                        help="the precision report of a run that read the Beschlussempfehlungen")
    args = parser.parse_args(argv)

    task = tasks.get(args.task)
    name = report.report_name(report.case_set(task, args.cases), args.split, args.context,
                              args.beschlussempfehlung)
    out = config.run_dir(task.name, args.tag)
    if not (out / f"results-{name}.json").is_file():
        print(f"no results-{name}.json in {out} (run `report --split {args.split}` first)")
        return 1
    print(f"-> {write_run(out, name)}")
    return 0
