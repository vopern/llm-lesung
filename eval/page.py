"""The shared page kit: one look for every eval report.

Palette, shell and the few components all three reports need — tiles, badges,
tables, an explainer panel, collapsible detail. Reports keep their own
structure and their own prose; only the rendering lives here, so a change to
the look lands in one place.

Chrome is English, the material stays German: the drafts, findings, Grundgesetz
text and case stories are quoted as they are.
"""

import re
from html import escape

# Tone, not verdict: each report maps its own verdicts onto these five.
TONES = ("good", "warn", "bad", "info", "muted")

CSS = """
:root{--bg:#fbfaf7;--panel:#fff;--ink:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;
--good:#1f7a4d;--good-bg:#e2f3ea;--warn:#946200;--warn-bg:#fbf0d4;--dim:#6b6a65;--dim-bg:#efede7;
--bad:#b3261e;--bad-bg:#fbe4e2;--info:#2b5bb5;--info-bg:#e6ecfa;--accent:#2b5bb5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161614;--panel:#1f1f1c;
--ink:#ecebe6;--muted:#a3a19a;--line:#34332f;--good:#6fd3a0;--good-bg:#173527;--warn:#e8bd5c;
--warn-bg:#3a2f14;--dim:#a3a19a;--dim-bg:#2a2926;--bad:#f2968f;--bad-bg:#3d1c1a;
--info:#8fb0f0;--info-bg:#1b2740;--accent:#8fb0f0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 12px}
h3{font-size:1rem;margin:0}
.muted{color:var(--muted)}.small{font-size:.85rem}
.note{border-left:3px solid var(--line);background:var(--panel);padding:10px 14px;margin:16px 0;border-radius:4px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}
.tile b{display:block;font-size:1.4rem;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:.8rem}
.tile.meta{display:flex;flex-direction:column;justify-content:center;gap:4px}
.tile.meta div{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.tile.meta b{display:inline;font-size:1rem}
table{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.8rem;color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.text{font-size:.85rem;max-width:40ch}
.scroll{overflow-x:auto}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.78rem;font-weight:600;white-space:nowrap}
.badge.good{color:var(--good);background:var(--good-bg)}
.badge.warn{color:var(--warn);background:var(--warn-bg)}
.badge.bad{color:var(--bad);background:var(--bad-bg)}
.badge.info{color:var(--info);background:var(--info-bg)}
.badge.muted{color:var(--dim);background:var(--dim-bg)}
.cat{font-family:ui-monospace,monospace;font-size:.8rem;color:var(--muted)}
.alert{border-left:3px solid var(--bad);background:var(--bad-bg);color:var(--bad);
padding:10px 14px;margin:16px 0;border-radius:4px}
details.doc{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin:10px 0}
details.doc>summary{cursor:pointer;padding:10px 14px;list-style:none;display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}
details.doc>summary::-webkit-details-marker{display:none}
details.doc[open]>summary{border-bottom:1px solid var(--line)}
.body{padding:12px 14px}
.case{border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin:8px 0}
.finding{border-top:1px solid var(--line);padding:8px 0}
.finding:first-child{border-top:0}
.matched{outline:2px solid var(--good);outline-offset:4px;border-radius:2px}
blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--muted);white-space:pre-wrap}
details.about{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin:16px 0}
details.about>summary{cursor:pointer;padding:10px 14px;list-style:none;font-weight:600}
details.about>summary::-webkit-details-marker{display:none}
details.about[open]>summary{border-bottom:1px solid var(--line)}
details.about .body>p{margin:0 0 10px;max-width:78ch}
.file{border-top:1px solid var(--line);padding:10px 0}
.file:first-child{border-top:0}
.file b{display:block}
details.bg{margin:8px 0 0}
details.bg>summary{cursor:pointer;font-size:.85rem;color:var(--accent);list-style:none}
details.bg>summary::-webkit-details-marker{display:none}
details.bg>summary::before{content:"▸  "}
details.bg[open]>summary::before{content:"▾  "}
.bg-body{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:6px 0 2px;
font-size:.9rem;line-height:1.65;max-width:72ch}
.bg-body p{margin:0 0 10px}
dl.fields{display:grid;grid-template-columns:max-content 1fr;gap:5px 14px;margin:8px 0 0}
dl.fields dt{color:var(--muted);font-size:.85rem;font-weight:600}
dl.fields dd{margin:0;max-width:78ch}
dl.fields blockquote{margin:0}
@media(max-width:700px){dl.fields{grid-template-columns:1fr;gap:2px}
dl.fields dd{margin:0 0 8px}}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.filters button{font:inherit;font-size:.85rem;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:14px;padding:3px 12px;cursor:pointer}
.filters button[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
.hidden{display:none}
"""

FILTER_JS = """
document.querySelectorAll('.filters').forEach(bar=>{bar.addEventListener('click',e=>{
const b=e.target.closest('button');if(!b)return;
bar.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',x===b));
const v=b.dataset.v;document.querySelectorAll(bar.dataset.target).forEach(el=>{
el.classList.toggle('hidden',v!=='all'&&!(el.dataset.v||'').split(' ').includes(v))})})});
"""


def esc(value) -> str:
    return escape("" if value is None else str(value))


def page(title: str, body: str, script: str = FILTER_JS) -> str:
    """One self-contained file: no external CSS, no fonts, no network."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main><script>{script}</script></body></html>")


def pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def money(x) -> str:
    return "–" if x is None else f"${x:.2f}"


def duration(seconds) -> str:
    if not seconds:
        return "–"
    minutes = seconds / 60
    return f"{minutes:.0f} min" if minutes < 90 else f"{minutes / 60:.1f} h"


def badge(text: str, tone: str = "muted") -> str:
    return f'<span class="badge {esc(tone)}">{esc(text)}</span>'


def tile(value: str, label: str) -> str:
    """One headline number. ``value`` may carry markup, ``label`` never does."""
    return f'<div class="tile"><b>{value}</b><span>{esc(label)}</span></div>'


def meta_tile(rows: list[tuple[str, str]]) -> str:
    """Several small numbers in one tile: run scope, run mechanics."""
    return ('<div class="tile meta">' + "".join(
        f"<div><span>{esc(label)}</span><b>{esc(value)}</b></div>" for value, label in rows)
        + "</div>")


def tiles(items: list[str]) -> str:
    return '<div class="tiles">' + "".join(items) + "</div>"


def note(lead: str, text: str) -> str:
    """The box that keeps a number from being read as more than it is."""
    return f'<div class="note small"><b>{esc(lead)}</b> {text}</div>'


def panel(title: str, body: str) -> str:
    """The opening explainer: what this eval is and how to read it."""
    return (f'<details class="about" open><summary>{esc(title)}</summary>'
            f'<div class="body">{body}</div></details>')


def table(headers: list[str], rows: list[str], numeric_from: int | None = None) -> str:
    """A table whose columns from ``numeric_from`` on are right-aligned numbers."""
    head = "".join(
        f'<th{" class=\"num\"" if numeric_from is not None and i >= numeric_from else ""}>'
        f"{esc(h)}</th>" for i, h in enumerate(headers))
    return f'<div class="scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>'


def filters(target: str, values: list[str]) -> str:
    buttons = ['<button data-v="all" aria-pressed="true">all</button>'] + [
        f'<button data-v="{esc(v)}" aria-pressed="false">{esc(v)}</button>' for v in values]
    return f'<div class="filters" data-target="{esc(target)}">{"".join(buttons)}</div>'


# The stories and Begründungen are written as one wall of prose, so the
# paragraphs are made here. A period before a capital ends a sentence unless the
# word in front of it is an abbreviation or too short to be one — legal German is
# full of "§ 9 Abs. 1", "BT-Drs. 21/537" and "vom 8. Oktober".
ABBREVIATIONS = {"Abs", "Art", "Nr", "Nrn", "Drs", "BT-Drs", "Buchst", "Doppelbuchst",
                 "lit", "Rn", "Ziff", "Var", "Alt", "Hs", "Bd", "Aufl", "BGBl", "ABl",
                 "bzw", "sog", "usw", "vgl", "ggf", "inkl", "insb", "evtl", "etc", "ca"}
WORD_BEFORE_STOP = re.compile(r"([\w\-äöüßÄÖÜ]+)\.$")
SENTENCE_BREAK = re.compile(r"(?<=\.) (?=[A-ZÄÖÜ„])")
SENTENCES_PER_PARAGRAPH = 3


def sentences(text: str) -> list[str]:
    out, start = [], 0
    for match in SENTENCE_BREAK.finditer(text):
        word = WORD_BEFORE_STOP.search(text[:match.start()])
        token = word.group(1) if word else ""
        if len(token) >= 3 and token not in ABBREVIATIONS and not token.isdigit():
            out.append(text[start:match.start()])
            start = match.end()
    return [part for part in out + [text[start:]] if part.strip()]


def prose(text: str) -> str:
    """Block text as paragraphs of a few sentences each."""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        parts = sentences(" ".join(block.split()))
        out += [" ".join(parts[i:i + SENTENCES_PER_PARAGRAPH])
                for i in range(0, len(parts), SENTENCES_PER_PARAGRAPH)]
    return "".join(f"<p>{esc(par)}</p>" for par in out if par.strip())
