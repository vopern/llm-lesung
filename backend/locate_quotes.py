"""Locate the quotes of the stored findings — ``python -m backend.locate_quotes``.

The pipeline locates quotes as it analyzes. This CLI does the same for the
findings already stored: it reads the documents each analysis recorded from the
PDF cache (downloading a missing one) and rewrites the bill's findings with
their locations. No Claude call, no DIP call, idempotent.
"""

import logging
import sys

from backend import db, pipeline

log = logging.getLogger("llm_lesung.locate_quotes")


def run(conn) -> int:
    """Locate the quotes of every analyzed bill's findings; returns an exit code."""
    quoted = located = 0
    for bill_id in db.bill_ids(conn):
        bill = db.get_bill(conn, bill_id)
        if not bill["findings"] or not bill["analysis_documents"]:
            continue
        findings = pipeline.locate_findings(bill["findings"], bill["analysis_documents"])
        db.replace_findings(conn, bill_id, findings)
        with_quote = [f for f in findings if f.get("quote")]
        found = sum(1 for f in with_quote if f["location"])
        quoted += len(with_quote)
        located += found
        log.info("[%s] %d of %d quote(s) located", bill["dokumentnummer"], found, len(with_quote))
    log.info("Summary: %d of %d quote(s) located", located, quoted)
    return 0


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    conn = db.connect()
    try:
        db.init_db(conn)
        return run(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
