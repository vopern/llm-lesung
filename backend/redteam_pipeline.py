"""Adversarial pass CLI — red-teams the bills stored in the database.

    uv run python -m backend.redteam_pipeline [--limit N] [--force]
                                              [--concurrency N] [--max-attempts N]

Runs the Angreifer (``backend/analysis/redteam.py``) over the bills the
analysis pipeline has stored and persists its exploits. It is a batch job of
its own: it reads only each bill's Gesetzentwurf (from the PDF cache, or the
public PDF), never calls DIP, and never touches a bill's findings or risk.

Per bill the job is:

1. Decide whether the pass is due — see :func:`needs_redteam`. ``--limit``
   caps the bills that are due, so it bounds the number of Claude calls.
2. Extract the Gesetzentwurf's text, skip the bill if it exceeds
   ``analyzer.MAX_INPUT_CHARS``, otherwise red-team it with Claude and persist
   the exploits together with the pass's metadata and the document it read.

Bills are processed by a thread pool (``config.PIPELINE_CONCURRENCY`` workers):
workers do the PDF text and the Claude call, while every SQLite read and write
stays serial on the main thread. A failing bill is retried up to
``config.PIPELINE_MAX_ATTEMPTS`` times and keeps its stored exploits; the next
run picks it up again. The process exits non-zero only when calls were
attempted and every one of them failed.

Every run gets a folder ``<UTC start>-redteam`` under
``config.PIPELINE_RUNS_DIR`` with the same contents as a pipeline run:
``errors.jsonl`` and ``traces/``. A stored pass names its trace in
``bills.redteam_trace``.
"""

import argparse
import logging
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend import config, db, errorlog, pipeline
from backend.analysis import analyzer, redteam
from backend.dip import pdf_text

log = logging.getLogger("llm_lesung.redteam_pipeline")

RUN_DIR_SUFFIX = "-redteam"
PHASE = "redteam"


def needs_redteam(row: dict, force: bool) -> bool:
    """Decide whether a stored bill must be (re-)red-teamed.

    Pure and side-effect free. The pass is due when any of these hold:

    - ``force`` is set;
    - it has never run (``redteamed_at`` is ``NULL``);
    - the Gesetzentwurf the stored pass read (``redteam_documents``) is not the
      bill's current one — another ``pdf_hash`` (``aktualisiert`` when it has
      none);
    - the stored ``redteam_prompt_version`` no longer matches
      ``config.REDTEAM_PROMPT_VERSION``.

    ``row`` is the stored bill as ``db.get_bill`` returns it.
    """
    return _decision_reason(row, force) != "unverändert"


def _decision_reason(row: dict, force: bool) -> str:
    """Reason for the decision; ``"unverändert"`` means skip."""
    if force:
        return "force"
    if row.get("redteamed_at") is None:
        return "nie gelaufen"
    stored = row.get("redteam_documents") or []
    current = [pipeline.entwurf_document(row)]
    if pipeline.document_versions(stored) != pipeline.document_versions(current):
        return "Entwurf geändert"
    if row.get("redteam_prompt_version") != config.REDTEAM_PROMPT_VERSION:
        return "prompt_version geändert"
    return "unverändert"


def _trace_fields(bill: dict, attempt: int, document: dict) -> dict:
    """The header of a trace: the call's settings and the document it read."""
    return {
        "pass": "angreifer",
        "doc": bill.get("dokumentnummer"),
        "bill_id": bill.get("id"),
        "attempt": attempt,
        "prompt_version": config.REDTEAM_PROMPT_VERSION,
        "model": config.REDTEAM_MODEL,
        "effort": config.REDTEAM_EFFORT,
        "max_turns": redteam.MAX_TURNS,
        "inputs": [
            {k: document.get(k) for k in
             ("typ", "dokumentnummer", "document_id", "pdf_hash", "text_chars")}
        ],
    }


def _attempt_bill(bill: dict, run_dir: Path, attempt: int) -> dict:
    """One attempt of the slow, thread-safe work for one bill.

    Touches no SQLite and never raises. Returned keys: ``bill`` and, on
    success, ``analysis`` + ``documents`` + ``trace`` (relative to
    ``config.PIPELINE_RUNS_DIR``); ``oversize`` (the text length) when the
    draft exceeds ``analyzer.MAX_INPUT_CHARS``; ``error`` on failure.
    """
    outcome: dict = {"bill": bill}
    try:
        text = pdf_text.get_text(
            bill.get("pdf_url"),
            cache_key=bill.get("pdf_hash") or bill.get("aktualisiert"),
        )
        if len(text) > analyzer.MAX_INPUT_CHARS:
            outcome["oversize"] = len(text)
            return outcome
        document = pipeline.entwurf_document(bill) | {"text_chars": len(text)}
        trace = pipeline.trace_file(run_dir, bill.get("dokumentnummer"), attempt)
        outcome["analysis"] = redteam.redteam_bill(
            bill.get("titel"),
            bill.get("dokumentnummer"),
            text,
            trace=trace,
            trace_fields=_trace_fields(bill, attempt, document),
        )
        outcome["documents"] = [document]
        outcome["trace"] = trace.relative_to(
            Path(config.PIPELINE_RUNS_DIR)
        ).as_posix()
        return outcome
    except Exception as exc:  # noqa: BLE001 — per-bill isolation is intentional
        outcome["error"] = exc
        return outcome


def _process_bill(
    bill: dict, errors: errorlog.ErrorLog, max_attempts: int, run_dir: Path
) -> dict:
    """Red-team one bill with up to ``max_attempts`` attempts — worker thread.

    Every failed attempt is appended to the run's error log. Returns the last
    attempt's outcome; never raises.
    """
    for attempt in range(1, max_attempts + 1):
        outcome = _attempt_bill(bill, run_dir, attempt)
        error = outcome.get("error")
        if error is None:
            return outcome
        errors.record(bill, PHASE, attempt, max_attempts, error)
        if attempt < max_attempts:
            log.warning(
                "[%s] %s — attempt %d/%d failed (%s: %s); retrying",
                bill.get("dokumentnummer"),
                pipeline.short(bill.get("titel")),
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
    concurrency: int | None = None,
    max_attempts: int | None = None,
) -> int:
    """Run the pass against an open DB connection; return an exit code.

    ``limit`` caps how many due bills are red-teamed, newest first. Returns
    ``1`` only when at least one call was attempted and all attempts failed;
    otherwise ``0``.
    """
    if concurrency is None:
        concurrency = config.PIPELINE_CONCURRENCY
    concurrency = max(1, concurrency)
    if max_attempts is None:
        max_attempts = config.PIPELINE_MAX_ATTEMPTS
    max_attempts = max(1, max_attempts)
    run_dir = pipeline.new_run_dir(RUN_DIR_SUFFIX)
    errors = errorlog.ErrorLog(run_dir)

    due = []
    unchanged = 0
    for bill_id in db.bill_ids(conn):
        if limit is not None and len(due) >= limit:
            break
        bill = db.get_bill(conn, bill_id)
        reason = _decision_reason(bill, force)
        if reason == "unverändert":
            unchanged += 1
            continue
        due.append((bill, reason))
    log.info(
        "Red-teaming %d bill(s) (limit=%s, force=%s, concurrency=%d, "
        "max_attempts=%d); %d unchanged",
        len(due),
        limit,
        force,
        concurrency,
        max_attempts,
        unchanged,
    )

    redteamed = 0
    oversize = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for bill, reason in due:
            log.info(
                "[%s] %s — red-team (%s)",
                bill.get("dokumentnummer"),
                pipeline.short(bill.get("titel")),
                reason,
            )
            futures.append(
                pool.submit(_process_bill, bill, errors, max_attempts, run_dir)
            )

        for future in as_completed(futures):
            outcome = future.result()  # never raises; errors are in the dict
            bill = outcome["bill"]
            dokumentnummer = bill.get("dokumentnummer")
            title = pipeline.short(bill.get("titel"))

            if outcome.get("error") is not None:
                failed += 1
                log.error(
                    "[%s] %s — red-team failed: %s",
                    dokumentnummer,
                    title,
                    outcome["error"],
                )
                continue

            if "oversize" in outcome:
                oversize += 1
                log.warning(
                    "[%s] %s — skip (oversize: %d chars vs %d)",
                    dokumentnummer,
                    title,
                    outcome["oversize"],
                    analyzer.MAX_INPUT_CHARS,
                )
                continue

            analysis = outcome["analysis"]
            db.replace_exploits(
                conn, bill.get("id"), [e.model_dump() for e in analysis.exploits]
            )
            db.mark_redteamed(
                conn,
                bill.get("id"),
                analysis.summary,
                config.REDTEAM_PROMPT_VERSION,
                config.REDTEAM_MODEL,
                outcome["documents"],
                trace=outcome["trace"],
            )
            redteamed += 1
            log.info(
                "[%s] %s — done: %d exploit(s)",
                dokumentnummer,
                title,
                len(analysis.exploits),
            )

    log.info(
        "Summary: redteamed=%d unchanged=%d oversize=%d failed=%d",
        redteamed,
        unchanged,
        oversize,
        failed,
    )
    if errors.count:
        log.warning(
            "Logged %d failed attempt(s) to %s", errors.count, errors.path
        )

    # Non-zero exit only if calls were attempted and every one failed.
    if failed > 0 and redteamed == 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parses flags, runs the pass, returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m backend.redteam_pipeline",
        description=(
            "LLM-Lesung adversarial pass: red-team the stored Gesetzentwürfe "
            "with Claude and store the exploits."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="limit how many due bills are red-teamed, newest first (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="red-team every bill even if its stored pass is current",
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
            concurrency=args.concurrency,
            max_attempts=args.max_attempts,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
