"""Analysis pipeline CLI — the composition root (D6).

Wires the DIP client, PDF text extraction, the Claude analyzer and the SQLite
store into one batch job:

    uv run python -m backend.pipeline [--limit N] [--force] [--skip-analysis]
                                      [--concurrency N] [--max-attempts N]
                                      [--bestandsrecht | --no-bestandsrecht]

Only this module imports all three detail layers; none of them import it. The
web server (``backend/server.py``) is untouched — serving and data production
share only the database file.

Per bill the job is:

1. Fetch Gesetzentwurf metadata from DIP, refresh the Vorgang ``status`` and
   upsert it into the DB. There is one Gesetzentwurf per lawmaking Vorgang.
   The Beschlussempfehlungen DIP lists for that Vorgang (one sweep per run) are
   catalogued in ``bill_documents``; when the sweep fails, the stored catalog
   stands in.
2. Decide whether (re-)analysis is needed — see :func:`needs_analysis`. The
   input set is the Gesetzentwurf plus its Beschlussempfehlungen; the decision
   compares its document versions against the ones the stored analysis read
   (``analysis_documents``), not against the bill's metadata columns, which
   every upsert overwrites — even after a failed analysis.
3. When needed: download the PDFs, extract text, skip the bill if the summed
   text exceeds ``analyzer.MAX_INPUT_CHARS``, otherwise analyze with Claude,
   derive the overall risk and persist findings + analysis metadata, including
   the list of documents the analysis read.

With the Bestandsrecht context on (``config.BESTANDSRECHT_CONTEXT``,
``--bestandsrecht``), step 3 also selects, resolves and fetches the existing §§
the draft amends or cites (``backend.bestandsrecht.provide``) and feeds them
after the draft and the Beschlussempfehlungen. They get the characters
``analyzer.MAX_INPUT_CHARS`` leaves: over that, only the amended §§ are fed, and
if those do not fit either, none — the bill is analyzed without them. The fed §§
enter ``analysis_documents`` as ``bestandsrecht`` entries but never decide
whether a bill is re-analyzed; neither does the switch (``--force`` does).

Bills are processed by a thread pool (``config.PIPELINE_CONCURRENCY`` workers,
``--concurrency`` to override): workers do the slow, thread-safe parts (DIP
status fetch, PDF download + extraction, the Claude call), while every SQLite
read and write stays serial on the main thread.

Per-bill errors are isolated: a failing bill is retried up to
``config.PIPELINE_MAX_ATTEMPTS`` times (``--max-attempts``, default 2), every
failed attempt — retried or final — is appended to the run's error log, and
the run continues. The process exits non-zero only when analyses were attempted
and every one of them failed.

Every run gets a folder under ``config.PIPELINE_RUNS_DIR``, named by its UTC
start: ``errors.jsonl`` and ``traces/``, one trace per Claude call
(``21-1234.jsonl``, ``21-1234.attempt-2.jsonl`` for a retry; the Bestandsrecht
selection as ``21-1234.select.jsonl``), and with the Bestandsrecht context on
``bestandsrecht/21-1234.json``: what was selected, resolved, fetched and fed. A
stored analysis names its trace in ``bills.analysis_trace``.
"""

import argparse
import logging
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from backend import bestandsrecht, config, db, errorlog
from backend.analysis import analyzer, quotes
from backend.dip import client as dip_client
from backend.dip import pdf_text
from backend.gii import index as gii_index

log = logging.getLogger("llm_lesung.pipeline")

# ``bill_documents.typ`` of the related documents the pipeline catalogues.
BESCHLUSSEMPFEHLUNG = "beschlussempfehlung"

# ``analysis_documents.typ`` of the existing §§ an analysis read.
BESTANDSRECHT = "bestandsrecht"


def document_versions(documents: list[dict]) -> set[tuple]:
    """The identity of each document version: id plus ``pdf_hash``.

    Falls back to ``aktualisiert`` for documents DIP publishes without a hash.
    Existing §§ (``bestandsrecht``) are left out: they follow from the draft and
    are only known once it is analyzed.
    """
    return {
        (d.get("document_id"), d.get("pdf_hash") or d.get("aktualisiert"))
        for d in documents
        if d.get("typ") != BESTANDSRECHT
    }


def needs_analysis(existing_row: dict | None, inputs: list[dict], force: bool) -> bool:
    """Decide whether a bill must be (re-)analyzed.

    Pure and side-effect free so it can be unit-tested in isolation. Analysis is
    needed when any of these hold:

    - ``force`` is set;
    - the bill is unknown (no existing row);
    - it has never been analyzed (stored ``risk`` is ``NULL``);
    - the documents the stored analysis read (``analysis_documents``) differ
      from ``inputs`` — a document added, removed, or with a new ``pdf_hash``
      (``aktualisiert`` when it has none) — including an analysis with no
      documents recorded;
    - the stored ``prompt_version`` no longer matches ``config.PROMPT_VERSION``.

    ``existing_row`` is the stored row (with ``analysis_documents`` parsed);
    ``inputs`` is the fresh input set, Gesetzentwurf first (see
    :func:`_input_documents`).
    """
    return _decision_reason(existing_row, inputs, force) != "unverändert"


def _decision_reason(existing_row: dict | None, inputs: list[dict], force: bool) -> str:
    """Reason for the (re-)analysis decision; ``"unverändert"`` means skip."""
    if force:
        return "force"
    if existing_row is None:
        return "neu"
    if existing_row.get("risk") is None:
        return "unanalysiert"
    stored = existing_row.get("analysis_documents") or []
    if not stored:
        return "Dokumente nicht erfasst"
    if document_versions(stored) != document_versions(inputs):
        return _documents_change(stored, inputs)
    if existing_row.get("prompt_version") != config.PROMPT_VERSION:
        return "prompt_version geändert"
    return "unverändert"


def _documents_change(stored: list[dict], inputs: list[dict]) -> str:
    """Name what differs between the stored and the fresh input documents."""
    stored = [d for d in stored if d.get("typ") != BESTANDSRECHT]
    stored_by_id = {d.get("document_id"): d for d in stored}
    input_ids = {d.get("document_id") for d in inputs}
    changes = []
    for doc in inputs:
        label = _document_label(doc)
        previous = stored_by_id.get(doc.get("document_id"))
        if previous is None:
            changes.append(f"neu: {label}")
        elif document_versions([previous]) != document_versions([doc]):
            changes.append(f"geändert: {label}")
    changes.extend(
        f"entfallen: {_document_label(d)}"
        for d in stored
        if d.get("document_id") not in input_ids
    )
    return "; ".join(changes) or "Dokumente geändert"


def _document_label(doc: dict) -> str:
    """``Beschlussempfehlung 21/6393`` — a document as named in log lines."""
    if doc.get("typ") == BESTANDSRECHT:
        return f"Bestandsrecht {doc.get('dokumentnummer')}"
    typ = "Beschlussempfehlung" if doc.get("typ") == BESCHLUSSEMPFEHLUNG else "Entwurf"
    return f"{typ} {doc.get('dokumentnummer')}"


def entwurf_document(bill: dict) -> dict:
    """The ``analysis_documents`` entry for the bill's Gesetzentwurf itself."""
    return {
        "document_id": bill.get("id"),
        "typ": "gesetzentwurf",
        "dokumentnummer": bill.get("dokumentnummer"),
        "datum": bill.get("datum"),
        "pdf_url": bill.get("pdf_url"),
        "pdf_hash": bill.get("pdf_hash"),
        "aktualisiert": bill.get("aktualisiert"),
        "text_chars": bill.get("text_chars"),
    }


def _input_documents(bill: dict, related: list[dict]) -> list[dict]:
    """The analysis input set: the Gesetzentwurf, then its related documents."""
    return [entwurf_document(bill)] + [
        {**d, "text_chars": None} for d in related
    ]


def locate_findings(findings: list[dict], documents: list[dict]) -> list[dict]:
    """``findings`` with a ``location`` each: where its quote stands in ``documents``.

    ``documents`` are ``analysis_documents`` entries, searched in order; the
    existing §§ are not, since quotes come from the Drucksachen. ``location``
    is ``None`` for a finding without a quote or whose quote is not found.
    Never raises: a document whose pages cannot be read is left out.
    """
    prepared = []
    if any(f.get("quote") for f in findings):
        for doc in documents:
            if doc.get("typ") == BESTANDSRECHT:
                continue
            try:
                pages = pdf_text.get_pages(
                    doc.get("pdf_url"),
                    cache_key=doc.get("pdf_hash") or doc.get("aktualisiert"),
                )
            except Exception as exc:  # noqa: BLE001 — a missing page link must not cost the analysis
                log.warning("%s: no page texts (%s)", _document_label(doc), exc)
                continue
            prepared.append(quotes.Document(doc.get("document_id"), pages))
    return [{**f, "location": quotes.locate(f.get("quote"), prepared)} for f in findings]


def new_run_dir(suffix: str = "") -> Path:
    """A new run's folder under ``config.PIPELINE_RUNS_DIR``; created lazily by its writers.

    Named by the UTC start plus ``suffix``, which tells the passes' folders apart.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path(config.PIPELINE_RUNS_DIR) / f"{stamp}{suffix}"


def bill_stem(dokumentnummer: str) -> str:
    """``21-1234`` for Drucksache 21/1234: the bill's name in file names."""
    return dokumentnummer.replace("/", "-")


def trace_file(run_dir: Path, dokumentnummer: str, attempt: int, kind: str = "") -> Path:
    """``traces/21-1234.jsonl``, from the second attempt on ``21-1234.attempt-2.jsonl``;
    a ``kind`` such as ``select`` gives ``21-1234.select.jsonl``."""
    suffix = (f".{kind}" if kind else "") + ("" if attempt == 1 else f".attempt-{attempt}")
    return run_dir / "traces" / f"{bill_stem(dokumentnummer)}{suffix}.jsonl"


def bestandsrecht_log(run_dir: Path, dokumentnummer: str, attempt: int) -> Path:
    """``bestandsrecht/21-1234.json``: what the selection found and what was fed."""
    suffix = "" if attempt == 1 else f".attempt-{attempt}"
    return run_dir / "bestandsrecht" / f"{bill_stem(dokumentnummer)}{suffix}.json"


def _trace_fields(bill: dict, attempt: int, inputs: list[dict], context_on: bool = False,
                  context: bestandsrecht.Context | None = None) -> dict:
    """The header of a pipeline trace: the call's settings and its input set.

    ``inputs`` include the fed existing §§ with their ``rolle``; ``bestandsrecht``
    holds the size decision behind them.
    """
    fields = {
        "pass": "lektor",
        "doc": bill.get("dokumentnummer"),
        "bill_id": bill.get("id"),
        "attempt": attempt,
        "prompt_version": config.PROMPT_VERSION,
        "model": config.ANALYSIS_MODEL,
        "effort": config.ANALYSIS_EFFORT,
        "max_turns": analyzer.MAX_TURNS,
        "bestandsrecht_context": context_on,
        "inputs": [_trace_input(doc) for doc in inputs],
    }
    if context is not None:
        fields["bestandsrecht"] = context.summary()
    return fields


def _trace_input(doc: dict) -> dict:
    keys = ["typ", "dokumentnummer", "document_id", "pdf_hash", "text_chars"]
    if doc.get("typ") == BESTANDSRECHT:
        keys.append("rolle")
    return {k: doc.get(k) for k in keys}


def _log_fit(bill: dict, fit: bestandsrecht.Fit) -> None:
    """One line per bill on what of the existing law the analysis reads."""
    prefix = f"[{bill.get('dokumentnummer')}] {short(bill.get('titel'))} — Bestandsrecht"
    if fit.decision == "keine":
        log.info("%s: nothing to feed", prefix)
    elif fit.decision == "vollstaendig":
        log.info("%s: %d § fed (%d chars)", prefix, len(fit.fed), fit.chars_fed)
    elif fit.decision == "nur_geaendert":
        log.warning("%s: over budget (%d of %d chars), only the %d amended § fed "
                    "(%d chars), %d cited § left out", prefix, fit.chars_all, fit.budget,
                    len(fit.fed), fit.chars_fed, len(fit.left_out))
    else:
        log.warning("%s: dropped, the amended § alone are over budget (%d of %d chars); "
                    "analyzing without it", prefix, fit.chars_geaendert, fit.budget)


def _provide_bestandsrecht(bill: dict, text: str, budget: int, run_dir: Path | None,
                           attempt: int, entries: list | None) -> bestandsrecht.Context:
    """The existing §§ for one bill, frozen under ``GII_DIR/frozen/<21-1234>/``."""
    dnr = bill.get("dokumentnummer")
    return bestandsrecht.provide(
        bill.get("titel") or "", text,
        freeze_dir=Path(config.GII_DIR) / "frozen" / bill_stem(dnr),
        log=bestandsrecht_log(run_dir, dnr, attempt) if run_dir is not None else None,
        trace=trace_file(run_dir, dnr, attempt, "select") if run_dir is not None else None,
        entries=entries, budget=budget)


def short(text: str | None, length: int = 60) -> str:
    """Truncate a title for single-line logging."""
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= length else text[: length - 1] + "…"


def _attempt_bill(
    existing: dict | None,
    bill: dict,
    related: list[dict],
    force: bool,
    skip_analysis: bool,
    run_dir: Path | None = None,
    attempt: int = 1,
    context_on: bool = False,
    entries: list | None = None,
) -> dict:
    """One attempt of the slow, thread-safe work for one bill.

    Does the DIP status fetch, the analysis decision, the PDF downloads + text
    extraction and the Claude call. ``related`` are the bill's
    Beschlussempfehlungen (``bill_documents`` rows). Touches no SQLite; all
    persistence happens on the main thread. Never raises: errors land in the
    returned dict so the main thread keeps per-bill isolation.

    Returned keys: ``bill`` (mutated in place), ``phase`` (``"skipped"``,
    ``"attempted"`` or ``"metadata"``), ``reason``, and on success
    ``analysis`` + ``findings`` (located, see ``locate_findings``) + ``risk`` +
    ``documents`` + ``trace``, on failure ``error``.
    An input set over ``analyzer.MAX_INPUT_CHARS`` returns ``"skipped"`` with an
    ``oversize`` reason. With ``run_dir`` set, the Claude call is traced to
    ``trace_file(run_dir, …, attempt)``; ``trace`` is that path relative to
    ``config.PIPELINE_RUNS_DIR``. With ``context_on`` the existing §§ are fed
    within the budget the documents leave (``entries`` is GII's list of laws);
    a failed selection call fails the attempt.
    """
    outcome: dict = {"bill": bill, "phase": "metadata"}
    try:
        # Refresh status from the linked Vorgang.
        bill["status"] = dip_client.fetch_beratungsstand(bill.get("vorgang_id"))

        # Preserve a previously extracted text length across metadata-only
        # refreshes (the upsert would otherwise reset it to NULL).
        if existing is not None:
            bill["text_chars"] = existing.get("text_chars")

        inputs = _input_documents(bill, related)
        outcome["reason"] = _decision_reason(existing, inputs, force)
        do_analyze = (not skip_analysis) and outcome["reason"] != "unverändert"

        if not do_analyze:
            outcome["phase"] = "skipped"
            return outcome

        outcome["phase"] = "attempted"
        texts = []
        for doc in inputs:
            text = pdf_text.get_text(
                doc.get("pdf_url"),
                cache_key=doc.get("pdf_hash") or doc.get("aktualisiert"),
            )
            doc["text_chars"] = len(text)
            texts.append(text)
        bill["text_chars"] = inputs[0]["text_chars"]

        total = sum(len(t) for t in texts)
        if total > analyzer.MAX_INPUT_CHARS:
            outcome["phase"] = "skipped"
            outcome["reason"] = (
                f"oversize: {total} chars vs {analyzer.MAX_INPUT_CHARS} ("
                + ", ".join(
                    f"{_document_label(d)} {d['text_chars']}" for d in inputs
                )
                + ")"
            )
            return outcome

        log.info(
            "[%s] %s — analyze (%s)",
            bill.get("dokumentnummer"),
            short(bill.get("titel")),
            outcome["reason"],
        )
        context = None
        documents = inputs
        if context_on:
            context = _provide_bestandsrecht(
                bill, texts[0], analyzer.MAX_INPUT_CHARS - total, run_dir, attempt, entries)
            _log_fit(bill, context.fit)
            documents = inputs + context.documents()
        trace = (
            trace_file(run_dir, bill.get("dokumentnummer"), attempt)
            if run_dir is not None
            else None
        )
        analysis = analyzer.analyze_bill(
            bill.get("titel"),
            bill.get("dokumentnummer"),
            texts[0],
            context_docs=[
                (doc.get("dokumentnummer"), text)
                for doc, text in zip(inputs[1:], texts[1:])
            ],
            trace=trace,
            trace_fields=_trace_fields(bill, attempt, documents, context_on, context),
            bestandsrecht=context.fed() if context is not None else None,
        )
        outcome["analysis"] = analysis
        outcome["findings"] = locate_findings(
            [f.model_dump() for f in analysis.findings], inputs
        )
        outcome["risk"] = analyzer.derive_risk(analysis.findings)
        outcome["documents"] = documents
        outcome["trace"] = (
            trace.relative_to(Path(config.PIPELINE_RUNS_DIR)).as_posix()
            if trace is not None
            else None
        )
        return outcome
    except Exception as exc:  # noqa: BLE001 — per-bill isolation is intentional
        outcome["error"] = exc
        return outcome


def _fetch_related(errors: errorlog.ErrorLog) -> dict[str, list[dict]] | None:
    """Beschlussempfehlungen indexed by Vorgang id, or ``None`` if the sweep failed.

    A failed sweep is logged and recorded; the run continues and leaves the
    stored ``bill_documents`` rows untouched.
    """
    try:
        documents = dip_client.fetch_beschlussempfehlungen()
    except Exception as exc:  # noqa: BLE001 — a DIP outage must not abort the run
        errors.record({}, "beschlussempfehlungen", 1, 1, exc)
        log.error("Beschlussempfehlung sweep failed, keeping stored documents: %s", exc)
        return None
    log.info("Fetched %d Beschlussempfehlung document(s)", len(documents))
    return dip_client.index_by_vorgang(documents, BESCHLUSSEMPFEHLUNG)


def _related_for(
    bill: dict, existing: dict | None, related: dict[str, list[dict]] | None
) -> list[dict]:
    """A bill's Beschlussempfehlungen: from this run's sweep, else the stored catalog."""
    if related is not None:
        return related.get(bill.get("vorgang_id") or "", [])
    stored = (existing or {}).get("related_documents") or []
    return [d for d in stored if d.get("typ") == BESCHLUSSEMPFEHLUNG]


def _store_related(
    conn: sqlite3.Connection, bill: dict, related: dict[str, list[dict]] | None
) -> None:
    """Replace the bill's catalogued Beschlussempfehlungen — main thread only."""
    if related is None:
        return
    db.replace_bill_documents(
        conn,
        bill.get("id"),
        BESCHLUSSEMPFEHLUNG,
        related.get(bill.get("vorgang_id") or "", []),
    )


def _process_bill(
    existing: dict | None,
    bill: dict,
    related: list[dict],
    force: bool,
    skip_analysis: bool,
    errors: errorlog.ErrorLog,
    max_attempts: int,
    run_dir: Path | None = None,
    context_on: bool = False,
    entries: list | None = None,
) -> dict:
    """Process one bill with up to ``max_attempts`` attempts — worker thread.

    Every failed attempt is appended to the run's error log; non-final
    failures are retried from the top (the PDF cache makes the repeat cheap —
    only the DIP calls and the Claude analysis actually run again). Returns
    the last attempt's outcome; never raises.
    """
    for attempt in range(1, max_attempts + 1):
        outcome = _attempt_bill(
            existing, bill, related, force, skip_analysis, run_dir, attempt,
            context_on=context_on, entries=entries,
        )
        error = outcome.get("error")
        if error is None:
            return outcome
        errors.record(bill, outcome["phase"], attempt, max_attempts, error)
        if attempt < max_attempts:
            log.warning(
                "[%s] %s — attempt %d/%d failed (%s: %s); retrying",
                bill.get("dokumentnummer"),
                short(bill.get("titel")),
                attempt,
                max_attempts,
                type(error).__name__,
                error,
            )
    return outcome


def run(
    conn: sqlite3.Connection,
    limit: int | None = None,
    force: bool = False,
    skip_analysis: bool = False,
    concurrency: int | None = None,
    max_attempts: int | None = None,
    bestandsrecht_context: bool | None = None,
) -> int:
    """Run the pipeline against an open DB connection; return an exit code.

    Returns ``1`` only when at least one analysis was attempted and all attempts
    failed; otherwise ``0``. ``concurrency`` bounds how many bills are processed
    in parallel (default ``config.PIPELINE_CONCURRENCY``); ``max_attempts``
    bounds how often a failing bill is retried per run (default
    ``config.PIPELINE_MAX_ATTEMPTS``). Every failed attempt is appended to a
    run's ``errors.jsonl``; every Claude call is traced into the run's
    ``traces/`` (see the module docstring). ``bestandsrecht_context`` feeds
    the existing §§ (default ``config.BESTANDSRECHT_CONTEXT``); GII's list of
    laws is then loaded once, and the run aborts if it cannot be.
    """
    if concurrency is None:
        concurrency = config.PIPELINE_CONCURRENCY
    concurrency = max(1, concurrency)
    if max_attempts is None:
        max_attempts = config.PIPELINE_MAX_ATTEMPTS
    max_attempts = max(1, max_attempts)
    if bestandsrecht_context is None:
        bestandsrecht_context = config.BESTANDSRECHT_CONTEXT
    context_on = bestandsrecht_context and not skip_analysis
    run_dir = new_run_dir()
    errors = errorlog.ErrorLog(run_dir)

    log.info(
        "Fetching Gesetzentwürfe from DIP (limit=%s, force=%s, skip_analysis=%s, "
        "concurrency=%d, max_attempts=%d, bestandsrecht=%s)",
        limit,
        force,
        skip_analysis,
        concurrency,
        max_attempts,
        context_on,
    )
    entries = gii_index.load() if context_on else None
    documents = dip_client.fetch_gesetzentwuerfe(limit=limit)
    log.info("Fetched %d Gesetzentwurf document(s)", len(documents))
    related = _fetch_related(errors)

    fetched = 0
    analyzed = 0
    skipped = 0
    failed = 0
    attempted = 0  # bills for which analysis was actually attempted

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for doc in documents:
            fetched += 1
            bill = dip_client.document_to_bill(doc)
            # Read the stored row BEFORE the (later) upsert, which overwrites
            # its metadata. All SQLite access stays on this thread; workers
            # only get plain dicts.
            existing = db.get_bill(conn, bill.get("id"))
            futures.append(
                pool.submit(
                    _process_bill,
                    existing,
                    bill,
                    _related_for(bill, existing, related),
                    force,
                    skip_analysis,
                    errors,
                    max_attempts,
                    run_dir,
                    context_on,
                    entries,
                )
            )

        for future in as_completed(futures):
            outcome = future.result()  # never raises; errors are in the dict
            bill = outcome["bill"]
            bill_id = bill.get("id")
            dokumentnummer = bill.get("dokumentnummer")
            title = short(bill.get("titel"))
            phase = outcome["phase"]

            if phase == "attempted":
                attempted += 1

            error = outcome.get("error")
            if error is not None:
                failed += 1
                # Metadata-phase failures leave no row (nothing trustworthy to
                # store); analysis-phase failures still persist the metadata.
                if phase == "attempted":
                    db.upsert_bill(conn, bill)
                    _store_related(conn, bill, related)
                log.error(
                    "[%s] %s — %s failed: %s",
                    dokumentnummer,
                    title,
                    "analysis" if phase == "attempted" else "metadata",
                    error,
                )
                continue

            db.upsert_bill(conn, bill)
            _store_related(conn, bill, related)

            if phase == "skipped":
                skipped += 1
                decision = (
                    "skip (skip-analysis)"
                    if skip_analysis
                    else f"skip ({outcome['reason']})"
                )
                level = (
                    logging.WARNING
                    if outcome["reason"].startswith("oversize")
                    else logging.INFO
                )
                log.log(level, "[%s] %s — %s", dokumentnummer, title, decision)
                continue

            analysis = outcome["analysis"]
            risk = outcome["risk"]
            db.replace_findings(conn, bill_id, outcome["findings"])
            db.mark_analyzed(
                conn,
                bill_id,
                risk,
                analysis.summary,
                config.PROMPT_VERSION,
                config.ANALYSIS_MODEL,
                outcome["documents"],
                trace=outcome.get("trace"),
            )
            analyzed += 1
            log.info(
                "[%s] %s — done: %d finding(s), risk=%s",
                dokumentnummer,
                title,
                len(analysis.findings),
                risk,
            )

    log.info(
        "Summary: fetched=%d analyzed=%d skipped=%d failed=%d",
        fetched,
        analyzed,
        skipped,
        failed,
    )
    if errors.count:
        log.warning(
            "Logged %d failed attempt(s) to %s", errors.count, errors.path
        )

    # Non-zero exit only if analyses were attempted and every one failed.
    if attempted > 0 and analyzed == 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parses flags, runs the pipeline, returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m backend.pipeline",
        description=(
            "LLM-Lesung analysis pipeline: fetch Gesetzentwürfe from DIP, "
            "extract PDF text, analyze with Claude and store findings + risk."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="limit how many bills are fetched from DIP (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-analyze every bill even if it appears unchanged",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="stop after metadata + status refresh (no PDF download, no Claude)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        metavar="N",
        help=(
            "how many bills to process in parallel "
            f"(default: PIPELINE_CONCURRENCY, currently {config.PIPELINE_CONCURRENCY})"
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        metavar="N",
        help=(
            "how often a failing bill is attempted per run "
            f"(default: PIPELINE_MAX_ATTEMPTS, currently {config.PIPELINE_MAX_ATTEMPTS})"
        ),
    )
    parser.add_argument(
        "--bestandsrecht",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "feed the existing §§ the draft amends or cites "
            f"(default: BESTANDSRECHT_CONTEXT, currently "
            f"{'on' if config.BESTANDSRECHT_CONTEXT else 'off'}); "
            "never re-analyzes an analyzed bill by itself, use --force"
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    conn = db.connect()
    try:
        db.init_db(conn)
        return run(
            conn,
            limit=args.limit,
            force=args.force,
            skip_analysis=args.skip_analysis,
            concurrency=args.concurrency,
            max_attempts=args.max_attempts,
            bestandsrecht_context=args.bestandsrecht,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
