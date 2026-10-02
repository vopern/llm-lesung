"""Render a scored GG-recall run as a self-contained page.

The page has to carry its own explanation: a reader who has not read the code
cannot otherwise tell what "teilweise" means, why abstaining is not a failure,
or why a wrong answer's *content* is measured separately from its verdict.

Chrome is English, the material is German — the Grundgesetz text, the citations
and the model's answers are quoted as they are.
"""

from eval import page

from .score import ABSTAINED, ERROR, EXACT, NEAR, PARTIAL, WRONG

TONE = {EXACT: "good", NEAR: "good", PARTIAL: "warn", WRONG: "bad",
        ABSTAINED: "info", ERROR: "muted"}
ORDER = [EXACT, NEAR, PARTIAL, WRONG, ABSTAINED, ERROR]
VERDICTS = {
    EXACT: "the wording, verbatim (spelling and punctuation folded, nothing else)",
    NEAR: "one token away — a stray comma, a folded ß; a human would say it knows the norm",
    PARTIAL: "substantially overlapping but materially different wording",
    WRONG: "no substantial overlap, or, for a citation that does not exist, text invented for it",
    ABSTAINED: "declined to answer instead of guessing",
    ERROR: "the call itself failed; left out of every rate",
}
KINDS = {
    "zitat": "Asked for the wording of a named article or paragraph. Right answer: that text.",
    "reverse": "Shown a verbatim passage, asked which article it is from. Right answer: "
               "that article number.",
    "nonexistent": "Asked for a paragraph that does not exist in an article that does. Right "
                   "answer: saying so. Any text offered is invented.",
}
STRATA = {"hot": "articles real bills cite most often",
          "warm": "cited now and then",
          "cold": "rarely or never cited"}

ABOUT = (
    "<p>The analysis pipeline lets the model flag constitutional risk in a draft bill. That "
    "only holds up if the model remembers what the Grundgesetz actually says, so this page "
    "measures exactly that and nothing else.</p>"
    "<p>Every item is asked in its own session with web search, file access and all other "
    "tools switched off, and with no project instructions in reach: the answer comes from the "
    "model's memory or not at all. The questions are generated from the official Grundgesetz "
    "text published at gesetze-im-internet.de, and how often an article is cited in real "
    "Bundestag bills decides how many questions it gets — the articles this project keeps "
    "meeting are tested hardest.</p>"
    "<p>Nothing here is judged by a model. Every verdict is a string comparison against the "
    "official wording.</p>")

NOTE_TEXT = (
    "The ladder measures <i>distance from the expected wording</i>, never which citation was "
    "quoted: German legal language repeats itself enough that a different paragraph can look "
    "close, and a clumsy rendering of the right one can look far. So a wrong answer is checked "
    "separately against the text of all 1470 citations in the Grundgesetz, and the column "
    "<b>quoted a different citation</b> is the one that carries that meaning. Declining is "
    "tracked apart from being wrong on purpose: an abstention costs a finding, an invented "
    "norm produces a false one.")


def _tiles(report: dict) -> str:
    o = report["overall"]
    return page.tiles([
        page.tile(page.pct(o["exact_rate"]), "verbatim"),
        page.tile(page.pct(o["known_rate"]), "verbatim or one token off"),
        page.tile(page.pct(o["hallucination_rate"]), "wrong instead of declining"),
        page.tile(page.pct(o["misattribution_rate"]), "quoted a different citation"),
        page.tile(page.pct(o["abstention_rate"]), "declined"),
        page.meta_tile([(str(o["n_scored"]), "items scored"),
                        (str(o["counts"].get(ERROR, 0)), "calls failed"),
                        (page.money(report["total_cost_usd"]), "cost")]),
    ])


def _legend() -> str:
    rows = [f"<tr><td>{page.badge(v, TONE[v])}</td><td>{page.esc(text)}</td></tr>"
            for v, text in VERDICTS.items()]
    kinds = [f"<tr><td><b>{page.esc(k)}</b></td><td>{page.esc(text)}</td></tr>"
             for k, text in KINDS.items()]
    return (page.table(["question type", "what is asked, what counts as right"], kinds)
            + '<h2>Verdicts</h2>' + page.table(["verdict", "meaning"], rows))


def _group_table(title: str, caption: str, groups: dict, first: str) -> str:
    rows = [f"<tr><td>{page.esc(name)}</td>"
            f'<td class="num">{s["n_scored"]}</td>'
            f'<td class="num">{page.pct(s["exact_rate"])}</td>'
            f'<td class="num">{page.pct(s["known_rate"])}</td>'
            f'<td class="num">{page.pct(s["hallucination_rate"])}</td>'
            f'<td class="num">{page.pct(s["misattribution_rate"])}</td>'
            f'<td class="num">{page.pct(s["abstention_rate"])}</td></tr>'
            for name, s in groups.items()]
    return (f"<h2>{page.esc(title)}</h2><p class=\"muted small\">{page.esc(caption)}</p>"
            + page.table([first, "items", "verbatim", "+ one token off",
                          "wrong instead of declining", "quoted a different citation",
                          "declined"], rows, numeric_from=1))


def _items(report: dict) -> str:
    rows = []
    for r in sorted(report["results"], key=lambda r: (ORDER.index(r["verdict"]), r["id"])):
        answer = r["answer"] or r.get("error") or ""
        other = (f'<div class="small muted">reproduces {page.esc(r["misattributed_to"])}</div>'
                 if r.get("misattributed_to") else "")
        rows.append(
            f'<tr class="item-row" data-v="{page.esc(r["verdict"])}">'
            f'<td><b>{page.esc(r["citation"])}</b>'
            f'<div class="cat">{page.esc(r["kind"])} · {page.esc(r["stratum"])}</div></td>'
            f'<td>{page.badge(r["verdict"], TONE[r["verdict"]])}{other}</td>'
            f'<td class="num">{r["similarity"]:.2f}</td>'
            f'<td class="text">{page.esc(r["expected"][:400])}</td>'
            f'<td class="text">{page.esc(answer[:400])}</td></tr>')
    return (page.filters("tr.item-row", ORDER)
            + page.table(["citation", "verdict", "similarity", "expected wording",
                          "the model's answer"], rows))


def render(report: dict, tag: str) -> str:
    body = (f"<h1>Grundgesetz recall · {page.esc(tag)}</h1>"
            + page.panel("What this measures", ABOUT + _legend())
            + page.note("Reading the verdicts.", NOTE_TEXT)
            + _tiles(report)
            + _group_table("By question type", "The three ways an item can be asked.",
                           report["by_kind"], "question type")
            + _group_table("By how often bills cite the article",
                           "Wording items only, grouped by how present the article is in real "
                           "Bundestag drafts: " + ", ".join(f"{k} = {v}" for k, v in STRATA.items())
                           + ".", report["by_stratum"], "corpus stratum")
            + _group_table("By size of the asked-for passage",
                           "Wording items only: a whole Absatz against a single Satz.",
                           report["by_unit"], "passage")
            + f"<h2>Every item ({len(report['results'])})</h2>" + _items(report)
            + "<h2>Run details</h2>"
            f'<div class="muted small">model {page.esc(report["model"])} · '
            f'Grundgesetz as of {page.esc(report["gg_stand"])} · '
            f'scored {page.esc(report["scored_at"])}</div>')
    return page.page(f"Grundgesetz recall {tag}", body)


def main(argv: list[str]) -> int:
    """Re-render a stored score file. Offline and free — no model is called."""
    import argparse
    import json

    from . import config

    parser = argparse.ArgumentParser(prog="python -m eval.gg report",
                                     description="Render a scored run as HTML. Offline, free.")
    parser.add_argument("--tag", required=True, help="run tag used by `run`")
    args = parser.parse_args(argv)
    path = config.score_path(args.tag)
    if not path.is_file():
        print(f"no {path} (run `score --tag {args.tag}` first)")
        return 1
    out = config.report_path(args.tag)
    out.write_text(render(json.loads(path.read_text(encoding="utf-8")), args.tag),
                   encoding="utf-8")
    print(f"-> {out}")
    return 0
