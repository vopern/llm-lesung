# Evals

Two measurements and the structured evaluation set live here. Every report is rendered by
the shared kit in [`page.py`](page.py) — one palette, one page shell, one set of tiles,
badges and tables — so all three read the same way: an explainer panel first (what is
measured, how the cases were made, what the verdicts mean), then the numbers, then the
material. Chrome is English, the material stays German. All follow the same
discipline and it is the point of the directory: **ground truth is fixed before
the run, scoring is mechanical or by hand, and a model never scores its own
output.** Code is version-
controlled here; every artefact lands in `data/`, which is gitignored.

| | `eval/gg` | `eval/harness` |
|---|---|---|
| Question | Does the model recall the Grundgesetz unaided? | Does the Lektor find the known drafting defects? Does the Angreifer find what a bad-faith actor gets out of a draft that is handwerklich flawless? |
| Ground truth | official GG XML, gesetze-im-internet.de | `testset/cases-*.yaml`, splits `dev` and `test` |
| Scoring | mechanical (string comparison) | mechanical (passage position); whether a hit names the defect stays a hand verdict |
| Under test | any model id | `backend/analysis/analyzer.py` and `backend/analysis/redteam.py` with their prompts |

## GG-Recall (`eval/gg`)

`make gg-eval` — fetch the GG, build the stratified test set, ask `GG_MODEL`
every item through `claude -p` with tools and settings disabled, score it
mechanically into `data/gg/report-<tag>.html`. The full design is the
**Model-knowledge eval** row of the decisions table in `CLAUDE.md`.

It exists to settle one open question: **should the analyzer prompt carry the
relevant GG articles verbatim instead of trusting the model to recall them?**
The `verfassungsrisiko` and `kompetenz` categories rest on that recall, so the
answer decides whether they can stay as they are.

## Harness (`eval/harness`)

Runs a shipped pass on the pinned test-set drafts with no database in the loop: for recall on
the draft without Beschlussempfehlungen, for precision (`--beschlussempfehlung`) on the draft
with them. `--task` picks the pass:

| Task | Pass | Case files (`--cases`) | Finding |
|---|---|---|---|
| `lektor` (default) | `analyzer` — drafting defects | `beschlussempfehlungen` (default), `lektor` | a finding |
| `angreifer` | `redteam` — what a bad-faith actor gets out of the draft | `angreifer` | an exploit, with actor, steps, gain, effort and the missing safeguard |

Inputs come from the test set alone: the pinned text, the title and, for the oracle and the
precision run, the pinned norms and Beschlussempfehlungen in `testset/inputs.yaml`.
The message is built by the pass's own `build_message` and sent by its `run_query`, so a run
measures the shipped prompt and input format. Both tasks follow the same input rule as the
pipeline: the draft is sent whole, and one over `MAX_INPUT_CHARS` is recorded as `oversize`
and not sent.

```
make eval-run EVAL_ONLY=21/537,21/1493      # those drafts (paid, one call each)
make eval-run EVAL_SPLIT=dev                # every dev draft of the case set
make eval-run EVAL_TASK=angreifer EVAL_SPLIT=dev   # the Angreifer on its dev drafts
make eval-report                            # re-score the stored samples (free)
uv run python -m eval.harness run --cases lektor --model claude-opus-4-8
make eval-run EVAL_ONLY=21/1493 EVAL_EFFORT=medium   # same drafts at a lower reasoning effort
```

`--only` takes Drucksachen or case ids. `--effort low|medium|high|xhigh|max` sets the model's
reasoning effort; unset, it is the task's shipped effort (`ANALYSIS_EFFORT`,
`REDTEAM_EFFORT`). Most of a call's time is thinking, so effort is the lever on time and cost —
compare recall between runs before changing a pass.

`--context` picks the cases a run selects documents by and scores; a document none of whose
cases match is not run.

| Mode | Flags | Cases | Input | Run directory |
|---|---|---|---|---|
| default | — | `requires_context: none` | the draft | `<task>-<tag>` |
| baseline | `--context bestandsrecht` | `requires_context: bestandsrecht` | the draft | `<task>-<tag>`, shared with the default |
| oracle | `--context bestandsrecht --oracle` (Lektor) | `requires_context: bestandsrecht` | the draft, then the document's pinned norms | `<task>-<tag>-oracle-bestandsrecht` |
| precision | `--beschlussempfehlung` (Lektor) | every case with `repaired_by`, any context | the draft, then its pinned Beschlussempfehlungen, as the pipeline sends them | `<task>-<tag>-beschlussempfehlung` |

The baseline is the number the oracle is compared with: same cases, draft alone. The oracle is an
upper bound, because it hands the model exactly the norms that matter. Cases needing EU law or
outside facts have no pinned context and are not run. Reports of a context run carry the context
in their name (`report-<cases>-bestandsrecht[-<split>].html`).

The precision run turns the committee-repair cases around: the run reads the Beschlussempfehlung
that repaired each defect, so the analysis must not report it. Each case is scored as repaired
(kind `behoben`): `clear` when no finding lands on or near its anchor, `touched` when one does,
with `category_match` telling whether that finding has the defect's category. The summary's
`behoben` block gives `precision` = clear / (clear + touched) and `precision_category`, which
counts only same-category findings as re-reports, overall and by context. Recall and precision
are separate measurements: a repaired case counts whether or not a recall run finds it.
Reports carry `-beschlussempfehlung` in their name.

Samples are per document, so drafts shared by two case files or two modes on the same input are
not run twice. A document with a sample is skipped unless `--force`.

```
make eval-run EVAL_CONTEXT=bestandsrecht EVAL_SPLIT=dev                # baseline
make eval-run EVAL_CONTEXT=bestandsrecht EVAL_ORACLE=1 EVAL_SPLIT=dev  # oracle
make eval-run EVAL_BE=1 EVAL_SPLIT=dev                                 # precision
```

Output lands in `data/eval/runs/<task>-<prompt version>-<model>[-effort-<level>]/`:

| File | Content |
|---|---|
| `samples/<doc>.json` | one call: inputs with hashes, prompt version, model, turns, cost, risk, the pass's full output; `status` is `ok` or `oversize` (input over `MAX_INPUT_CHARS`, not sent) |
| `samples/<doc>.failed.json` | a call that raised, with its traceback |
| `traces/<doc>.jsonl` | the message stream of the call, written as it arrives |
| `summary-<cases>[-<split>].json` | run metadata, run status counts, cost, finding counts, passage recall per split × context and per expected category |
| `results-<cases>[-<split>].json` | per document: the expectations, the analysis's summary, every finding (with `located`: quote found in the pinned text) and each case's verdict, naming matched findings by index |
| `report-<cases>[-<split>].html` | one run as a self-contained page: how the test set was mined, headline numbers, recall per category, then every document with each scored case in full — anchor, `story`, `source` — its verdict and all findings |

The page covers one run and nothing else; re-render it any time with
`uv run python -m eval.harness html --split dev --tag <tag> [--task angreifer]`.

Verdicts are the passage verdicts of `testset/score.py` plus `oversize`, `failed` and
`not_run`. A `hit` says a finding quoted the anchored passage, not that it named the defect or
attack: reading the matched finding against `expected_defect` stays a hand verdict. For the
Angreifer, an unanchored negative is a draft that offers nothing to exploit: `fired` if the
run reported any exploit, `quiet` if none — its one precision signal. Every Lektor negative
is anchored on the passage its forbidden claim would quote.

Every call's message stream is written to `traces/<doc>.jsonl` as it arrives, by
[`backend/tracelog.py`](../backend/tracelog.py) — the same tracer the pipeline uses —
successful or not: a failed or odd call is diagnosed from its trace. The draft text is never
stored (length + hash only); the thinking summary is stored in full.

The Angreifer's positive cases are retold as stories — what happened, who profited, how much —
in [`testset/angreifer-stories.md`](testset/angreifer-stories.md). Read them before judging a
run: if you cannot tell the story, you cannot tell whether the pass found it.

## Publishing reports

The website's `/evaluation` page lists every HTML file in `data/eval-public/` and serves it
as is — copy a report there to publish it, delete it to withdraw it. Leave out reports that
show `test` cases. `make push-eval` ships the folder to production as an
atomically switched release.

## Test set (`eval/testset`)

The structured ground truth both suites are scored against — one YAML record per
expected defect or attack (`positiv`), per controversy that must not surface as
one (`negativ`, carrying a `forbidden_claim`), or per closed gap that must not be
reported as open (`invers`). Ids are `L-…` for the Lektor, `R-…` for the Angreifer.
Every record is self-contained: `story` tells how the case came about — the ruling,
repair law or criticism behind it and why it counts as positive or negative — and
`source` notes how it was mined. Lint rejects either field pointing outside the set.

Lektor cases live in two files. `cases-lektor.yaml` holds press-documented
controversies, rulings and repair laws. `cases-lektor-beschlussempfehlungen.yaml`
holds drafting defects that the lead committee's Beschlussempfehlung repaired in
the draft (positives only, every one anchored); `repaired_by` names that
Beschlussempfehlung. It is the file's ground truth, so recall runs read the draft
alone, and the precision run reads it to check that repaired defects stay unreported.

```
make eval-fetch    # download the pinned texts into testset/texts/ (once, network)
make eval-lint     # schema, sha256 of every pinned text, every anchor, splits, canary
make eval-export   # one JSONL sample per document -> data/testset/export/<suite>/<split>.jsonl
make eval-score    # passage recall of the findings table -> data/testset/score-db.json
```

After the fetch, all free and offline.

- **`texts/`** — the pypdf output of every Drucksache a case names, one file per
  Drucksache, pinned by hash. Not in git: `fetch` downloads each PDF from
  dserver.bundestag.de, extracts it with the pipeline's `extract_text` and writes
  it only if it matches the pin. Anchors and quotes are checked against these
  bytes, so a re-extraction cannot move a verdict silently.
- **`texts/bestandsrecht/`** — the golden context of the `bestandsrecht` cases:
  one file per norm (a whole §), **as it read on the draft's date**. The entries
  live in `inputs.yaml` under the draft's `bestandsrecht` key (`gesetz`, `norm`,
  `fassung`, `herkunft`, the `cases` it settles, `file`, `sha256`). gesetze-im-internet.de
  serves only the current version, which often already contains the repair, so
  these texts are pinned by hand. `herkunft` records the source and any later
  amendment reverted, and `fetch` cannot recreate them. Lint checks every hash and
  that every `bestandsrecht` case has at least one excerpt.
- **`texts/beschlussempfehlung/`** — the Beschlussempfehlungen of the
  committee-repair drafts, listed in `inputs.yaml` under the draft's
  `beschlussempfehlungen` key (`doc`, `file`, `sha256`) in issue order — what the
  pipeline reads with the draft. Fetchable like the drafts. Lint checks every hash
  and that each case's `repaired_by` is among its draft's Beschlussempfehlungen.
- **`anchor`** — a verbatim string from the pinned text, matched with
  `quotecheck.squash`; `null` where the defect is an absence with nothing to point at.
- **`split`** — held per document (lint rejects a Drucksache whose cases straddle
  splits). **`test`** is 30 % of the documents of each suite, stratified by negative /
  positive-`none` / positive-with-context and drawn in sha256 order of the file
  name. It is *frozen*, not unseen: earlier runs scored every case before the
  split existed. Prompt work reads `dev` only, and `test` is reported beside it,
  never folded in. A new document takes its split when it is added, before any
  run on it is read.
- **Canary** — both YAML files carry a BIG-bench-style canary GUID (lint checks
  it, every exported sample repeats it), so a crawler that honours canaries
  drops them and a model that completes the GUID has seen the set.
- **`export.py`** — the YAML is one record per expectation because that is how
  cases are written; a run reads a document. The export regroups: one sample
  per `(suite, text file)` with `input` = pinned text, `target` = the expected
  defects, and every case (negatives with their `forbidden_claim`) in
  `metadata.cases`. Field names are Inspect AI's `Sample`, and the
  `<suite>/<split>.jsonl` layout is a Hugging Face dataset's configs and splits,
  so either can load it without an adapter. Nothing reads the export back.
- **`score.py`** — mechanical passage recall: each finding's quote and each
  case's anchor are located in the same squashed pinned text (quotes that are
  not verbatim by their longest ≥ 40-character run), and the verdict is
  `hit` (overlap), `near` (within `TESTSET_NEAR_CHARS`, default 300), `miss`,
  `unanchored` or `not_run`; negatives are `touched` or `clear` (Angreifer: `fired` or
  `quiet` when unanchored). `score db` scores the stored Lektor analyses; harness runs
  are scored by `eval.harness report`. Reported per
  split and by `requires_context`. It measures where a run looked, not
  whether it named the defect, and bounds hand recall in neither direction:
  run 2 has two hand MISSes that score as hits (the finding quotes the passage
  for a different reason). A `touched` negative is a candidate to read, not a
  false positive. Use it to triage and to compare runs cheaply; the headline
  recall stays hand-scored.
