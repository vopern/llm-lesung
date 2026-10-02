# GG-Recall — how well does a model remember the Grundgesetz?

A self-contained eval: download the official Grundgesetz, turn it into a test set of
citations with their verbatim text, ask a model through the Claude CLI with no lookup
allowed, and score the answers by string comparison — no LLM judge anywhere.

```bash
make gg-build                                  # download the GG, build the test set
make gg-run   GG_MODEL=claude-sonnet-5         # ask the model
make gg-score GG_TAG=claude-sonnet-5-on        # score -> data/gg/report-<tag>.html
```

or step by step: `uv run python -m eval.gg {fetch,build,run,score}`.

## Pipeline

| Step | Module | Output |
|---|---|---|
| `fetch` | `gg/fetch.py` | `data/gg/gg.json` — 198 Artikel, 529 Absätze, parsed from the official XML at gesetze-im-internet.de (public domain, no auth), with the `Stand` line kept |
| `build` | `gg/dataset.py` | `data/gg/testset.jsonl` — 102 items, each with `prompt` and `expected` |
| `run` | `gg/run.py` | `data/gg/responses-<tag>.jsonl` — one `claude -p` subprocess per item |
| `score` | `gg/score.py` | `data/gg/score-<tag>.json` + `report-<tag>.html` |
| `report` | `gg/report.py` | `report-<tag>.html` again, from the stored score file (free) |

`run` is resumable: re-running skips ids that already have a successful answer.

### The lookup ban is enforced, not requested

Each item is a fresh CLI session with `--disallowed-tools WebSearch WebFetch Bash Read
Glob Grep Edit Write ...`, `--strict-mcp-config`, `--setting-sources ""`, a replaced
`--system-prompt`, and a working directory outside the repo so no `CLAUDE.md` is
discovered. The model answers from parameters alone.

## The test set

Three item kinds, stratified by **how often real Bundestag bills cite the article**. That
weight is computed from the pipeline's own PDF cache (`data/pdf-cache/*.txt`, 348
Drucksachen), so `hot` means "an article the LLM-Lesung actually meets" — Art. 74, 76,
72, 2, 1 — not "an article that is famous".

| kind | prompt | expected | n |
|---|---|---|---|
| `zitat` | "Gib den Wortlaut von Artikel 5 Absatz 1 des Grundgesetzes wörtlich wieder." | the Absatz (or a single Satz), verbatim | 60 |
| `reverse` | a verbatim Absatz → "aus welchem Artikel?" | the article number | 21 |
| `nonexistent` | "Artikel 10 Absatz 3" — the article exists, that Absatz does not | `UNBEKANNT` | 21 |

Sätze are only split out where the splitter is unambiguous (no enumerations, no
abbreviation- or ordinal-final sentences, every part ≥ 60 characters); a wrong split would
become wrong ground truth.

## Scoring is mechanical

An LLM judge on a verbatim-recall task adds its own recall error to the measurement, so
every verdict here is deterministic string work (`gg/normalize.py`):

- **`korrekt`** — normalized exact match. Normalization folds only what is *not*
  knowledge: markdown, an `ANTWORT:` envelope, typographic quotes and dashes, a repeated
  citation, a leading `(2)`, and `ß`→`ss` (the GG still carries pre-1996 orthography —
  "daß", "muß"; modern spelling is not a memory failure).
- **`fast_korrekt`** — at most one changed token (or 2% on long Absätze). Measured in
  token edits, not a similarity ratio, so the bar means the same on a 12-word Satz and a
  200-word Absatz.
- **`teilweise`** — substantially overlapping, materially different (bag-of-words
  F1 ≥ 0.6).
- **`falsch`** — below that.
- **`enthalten`** — declined instead of guessing.

`teilweise` and `falsch` are **word-overlap thresholds and nothing more** — they say how
far the answer is from the expected text, never *which* citation was quoted. German legal
boilerplate is repetitive enough ("bedürfen der Zustimmung des Bundesrates …") that a
genuinely different Absatz can clear 0.6, and a bad misquote of the right one can fall
below it.

Which citation was quoted is therefore measured separately: every wrong answer is compared
against **the text of all 1470 citations in the GG** (each Absatz and each Satz), and if
another one fits better than the one that was asked for, the item records
`misattributed_to: "Art 94 Abs 3"`. That column is the one that means "quoted a different
citation"; the verdict ladder does not.

Candidates that are *part of* the asked-for text are skipped. The list holds an Absatz and
its own Sätze, so an answer reproducing only the first sentence of the right Absatz would
otherwise match that Satz entry best and be scored as a different citation, when it is a
truncated quote of the correct one.

Word order is deliberately *not* folded. Haiku answering *"Sie zu schützen und zu achten"*
for Art. 1 Abs. 1 (the GG says *"zu achten und zu schützen"*) is a real error and scores as
one.

The headline is not accuracy. It is the split between **`falsch` and `enthalten`**: for a
pipeline that reports constitutional defects, an invented Absatz is what becomes a false
`verfassungsrisiko` finding; an abstention is only a miss.

## Results

Runs of 2026-09-05 on the full 102-item set, GG Stand *"Zuletzt geändert durch Art. 1 G v.
22.3.2025 I Nr. 94"*. Abstention permitted ("Rate nicht").

| | Haiku 4.5 | Sonnet 5 | Opus 4.8 | Opus 5 |
|---|---|---|---|---|
| `zitat` exact | 10 % | 23 % | 60 % | **73 %** |
| `zitat` exact + near | 10 % | 27 % | 67 % | **82 %** |
| — hot article | 20 % | 30 % | 80 % | 85 % |
| — warm article | 10 % | 30 % | 65 % | 75 % |
| — **cold article** | 0 % | 10 % | 35 % | **60 %** |
| `zitat` wrong (`teilweise`+`falsch`) | 12 % | 20 % | 22 % | 17 % |
| — of which **a different citation** | 5 % | **10 %** | 3 % | **2 %** |
| `zitat` abstained | 78 % | 53 % | 12 % | 2 % |
| `reverse` exact | 71 % | 90 % | 100 % | 100 % |
| **`nonexistent` (trap)** | **100 %** | **81 %** | **95 %** | **100 %** |

Recall rises monotonically with model size; **calibration does not**. Read the last four
rows together:

- **Haiku knows almost nothing verbatim but knows that it doesn't.** 78 % abstention, 0 %
  on cold articles, every trap caught. Useless as a recall source, honest about it.
- **Sonnet is the least safe of the four.** Half its wrong answers (6 of 12) reproduce a
  *different citation* than the one asked for — verified against the whole GG, not
  inferred: Art. 113 Abs. 1 Satz 1 answered with Art. 110 Abs. 2 Satz 1 (fit 0.95),
  Art. 47 Satz 1 with Art. 46 Abs. 1 Satz 1 (0.84). It also fails 4 of 21 traps the same
  way, returning the neighbouring Absatz. For the analyzer that is the worst possible
  shape: a real, correctly quoted constitutional sentence under a citation it does not
  belong to. Nothing downstream can tell it from a true finding.
- **Opus 5 is the first model that is good at this** — 100 % on both traps and `reverse`,
  60 % on the cold stratum, and 9 of its 10 wrong answers are loose quotes of the citation
  actually asked for (2–15 changed tokens) rather than a different one.
- **But it abstains on 2 % while getting 17 % materially wrong.** Better recall did not buy
  calibration: the misquotes read as authoritative and carry no warning.

### Text that changed after the cutoff is scored as hallucination

A model can only know the GG as of its training cutoff; the eval scores it against the
current text. Art. 93 Abs. 3 is the example here: every knowledge-carrying model returned
the *same* text, verbatim correct — but for **Art. 94 Abs. 3**, where the December 2024
BVerfG-Resilienz amendment moved it. Three independent models agreeing on one "wrong"
answer is the signature of superseded law, not of invention. ~1 % of items here, and the
bias points one way. Mitigation: the `Stand` line is stamped into every item, report and
score file; items are not yet flagged by amendment date.

## Is this a good test?

Two caveats matter more than the rest.

**Verbatim recall is not the skill the pipeline needs.** The analyzer never asks Claude to
recite a citation's text; it asks whether a bill triggers a doctrinal test. A model can
quote Art. 19 Abs. 1 Satz 2 perfectly and still miss a Zitiergebot violation. Recall
correlates with, but does not measure, application. The `reverse` items (text → which
citation) test recognition rather than recitation, which is one step closer; an applied
task — bill excerpt → the citation it triggers — would be the real measurement and belongs
next to `data/testcases-controversial-bills.md`, not here.

**Without an abstention option, the test would measure the wrong variable.** Asked to quote
something it doesn't know, a model produces plausible legal German either way; scoring only
right/wrong hides whether it *knew* it was guessing, which is the property that decides
whether the analyzer emits a false finding. Hence the `nonexistent` traps, the explicit
`UNBEKANNT` option, the `enthalten` verdict, and the `--abstention off` mode that reruns the
same set under forced guessing. This is where the signal turned out to be: Opus 5 is at 2 %
abstention and 17 % materially wrong on `zitat`, yet 100 % on the structural traps.

Two smaller things the design already handles: the ceiling effect on famous articles
(Art. 1, 3, 5, 12, 14, 20), answered by stratifying on corpus citation frequency and
reporting `cold` separately — that is where the models actually differ; and exact match
punishing non-knowledge differences, answered by the normalization rules and the
`fast_korrekt` bucket.

## What this decides

Should the analyzer keep relying on parametric recall? The ~50 GG articles its doctrinal
tests depend on are perhaps 15k tokens — small enough to paste into the prompt verbatim.
The numbers argue for it even on the best model available: Opus 5 gets 17 % of the
citations it is asked for materially wrong while abstaining on 2 %, and recites a
2024-superseded Art. 93 with full confidence. Injection fixes both the recall gap *and* the
staleness, which no amount of prompt tuning does; the cost is ~15k extra input tokens per
bill, made cheap by prompt caching. This eval is the go/no-go, and the re-measurement
afterwards.
