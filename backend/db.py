"""SQLite storage layer for LLM-Lesung (Contract 1).

Plain stdlib ``sqlite3``, no ORM. One database file holds the bills and their
AI findings. All public functions take an open connection so callers control
transaction/lifecycle. The web server and the analysis pipeline share only this
database file.
"""

import json
import os
import sqlite3

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
  id            TEXT PRIMARY KEY,        -- DIP drucksache id
  dokumentnummer TEXT NOT NULL,          -- e.g. "21/6916"
  wahlperiode   INTEGER NOT NULL,
  titel         TEXT NOT NULL,
  urheber       TEXT,                    -- initiator, e.g. "Bundesregierung"
  datum         TEXT,                    -- ISO date of the Drucksache
  aktualisiert  TEXT,                    -- DIP 'aktualisiert' timestamp
  status        TEXT,                    -- vorgang 'beratungsstand', may be NULL
  vorgang_id    TEXT,
  pdf_url       TEXT NOT NULL,
  pdf_hash      TEXT,                    -- DIP-provided pdf_hash
  text_chars    INTEGER,                 -- length of extracted text
  -- analysis result:
  risk          TEXT,                    -- 'hoch'|'mittel'|'niedrig'|NULL (=not analyzed)
  summary       TEXT,                    -- 1-3 sentence German summary of the assessment
  prompt_version TEXT,
  model         TEXT,
  analyzed_at   TEXT,
  analysis_documents TEXT,               -- JSON array: documents the stored analysis read; NULL = none recorded
  analysis_trace TEXT                    -- trace of the call that produced it, relative to PIPELINE_RUNS_DIR; NULL = none
);

CREATE TABLE IF NOT EXISTS findings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  bill_id     TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  severity    TEXT NOT NULL,             -- 'hoch'|'mittel'|'niedrig'
  category    TEXT NOT NULL,             -- see analysis.schema.Category (6 craft + verfassungsrisiko|kompetenz)
  title       TEXT NOT NULL,             -- short German headline
  description TEXT NOT NULL,             -- German explanation
  quote       TEXT                       -- verbatim excerpt from the bill, may be NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_bill_id ON findings(bill_id);

-- Related Drucksachen DIP currently lists for a bill's Vorgang (e.g.
-- Beschlussempfehlungen); which of them an analysis read is analysis_documents.
CREATE TABLE IF NOT EXISTS bill_documents (
  bill_id        TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  document_id    TEXT NOT NULL,          -- DIP drucksache id
  typ            TEXT NOT NULL,          -- 'beschlussempfehlung'
  dokumentnummer TEXT NOT NULL,
  titel          TEXT,
  datum          TEXT,
  aktualisiert   TEXT,
  pdf_url        TEXT NOT NULL,
  pdf_hash       TEXT,
  PRIMARY KEY (bill_id, document_id)
);
"""

# The categories that do not count toward a bill's risk: the complement of
# RISK_BEARING_CATEGORIES in backend/analysis/schema.py. Duplicated rather than
# imported because backend/analysis/ is a detail module and this is the shared
# core, so importing it would invert the dependency (ARCHITECTURE D5). A test in
# tests/test_db.py asserts the two stay in sync.
_NON_RISK_BEARING_CATEGORIES = ("verfassungsrisiko", "kompetenz")

# Columns of the bills table that ``upsert_bill`` writes on insert/refresh.
# Analysis-result columns are managed separately by ``mark_analyzed``.
_BILL_COLUMNS = [
    "id",
    "dokumentnummer",
    "wahlperiode",
    "titel",
    "urheber",
    "datum",
    "aktualisiert",
    "status",
    "vorgang_id",
    "pdf_url",
    "pdf_hash",
    "text_chars",
]


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    Creates the parent directory for the DB file, enables ``dict``-like row
    access, and turns on foreign-key enforcement (needed for the findings
    ``ON DELETE CASCADE``). Pass ``":memory:"`` for an in-memory database
    (used by tests).
    """
    path = db_path if db_path is not None else config.DB_PATH
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    # check_same_thread=False: FastAPI runs sync dependencies and endpoints in
    # different threadpool threads; each connection still serves one request at
    # a time, so cross-thread use is sequential and safe.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the tables if they do not already exist.

    ``CREATE TABLE IF NOT EXISTS`` never adds columns to an existing table, so
    columns newer than a database file are added here.
    """
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(bills)")}
    if "analysis_documents" not in columns:
        conn.execute("ALTER TABLE bills ADD COLUMN analysis_documents TEXT")
    if "analysis_trace" not in columns:
        conn.execute("ALTER TABLE bills ADD COLUMN analysis_trace TEXT")
    conn.commit()


def upsert_bill(conn: sqlite3.Connection, bill: dict) -> None:
    """Insert or update the DIP-sourced columns of a bill.

    Analysis columns (risk, summary, findings, ...) are left untouched so an
    unchanged re-fetch never wipes an existing analysis. Missing keys default
    to ``None``.
    """
    values = [bill.get(col) for col in _BILL_COLUMNS]
    placeholders = ", ".join("?" for _ in _BILL_COLUMNS)
    columns = ", ".join(_BILL_COLUMNS)
    updates = ", ".join(
        f"{col}=excluded.{col}" for col in _BILL_COLUMNS if col != "id"
    )
    conn.execute(
        f"INSERT INTO bills ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def replace_findings(
    conn: sqlite3.Connection, bill_id: str, findings: list[dict]
) -> None:
    """Replace all findings for a bill wholesale (idempotent re-analysis)."""
    conn.execute("DELETE FROM findings WHERE bill_id = ?", (bill_id,))
    conn.executemany(
        "INSERT INTO findings (bill_id, severity, category, title, description, quote) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                bill_id,
                f.get("severity"),
                f.get("category"),
                f.get("title"),
                f.get("description"),
                f.get("quote"),
            )
            for f in findings
        ],
    )
    conn.commit()


def mark_analyzed(
    conn: sqlite3.Connection,
    bill_id: str,
    risk: str,
    summary: str,
    prompt_version: str,
    model: str,
    documents: list[dict],
    trace: str | None = None,
) -> None:
    """Record analysis metadata on a bill; sets ``analyzed_at`` to now (UTC).

    ``documents`` lists the documents the analysis read (see
    ``analysis_documents`` in the schema) and ``trace`` the trace file of the
    call that produced it; both are stored in the same statement as the result
    so they cannot drift apart.
    """
    conn.execute(
        "UPDATE bills SET risk = ?, summary = ?, prompt_version = ?, model = ?, "
        "analysis_documents = ?, analysis_trace = ?, analyzed_at = datetime('now') "
        "WHERE id = ?",
        (
            risk,
            summary,
            prompt_version,
            model,
            json.dumps(documents, ensure_ascii=False),
            trace,
            bill_id,
        ),
    )
    conn.commit()


_RELATED_COLUMNS = [
    "document_id",
    "typ",
    "dokumentnummer",
    "titel",
    "datum",
    "aktualisiert",
    "pdf_url",
    "pdf_hash",
]


def replace_bill_documents(
    conn: sqlite3.Connection, bill_id: str, typ: str, documents: list[dict]
) -> None:
    """Replace a bill's related documents of one ``typ``; other types are kept."""
    conn.execute(
        "DELETE FROM bill_documents WHERE bill_id = ? AND typ = ?", (bill_id, typ)
    )
    columns = ", ".join(_RELATED_COLUMNS)
    placeholders = ", ".join("?" for _ in _RELATED_COLUMNS)
    conn.executemany(
        f"INSERT INTO bill_documents (bill_id, {columns}) VALUES (?, {placeholders})",
        [
            [bill_id] + [{**d, "typ": typ}.get(col) for col in _RELATED_COLUMNS]
            for d in documents
        ],
    )
    conn.commit()


def get_bill_documents(conn: sqlite3.Connection, bill_id: str) -> list[dict]:
    """A bill's related documents, ordered by ``typ``, then chronologically."""
    rows = conn.execute(
        f"SELECT {', '.join(_RELATED_COLUMNS)} FROM bill_documents WHERE bill_id = ? "
        "ORDER BY typ, datum, dokumentnummer",
        (bill_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards in a user-supplied search term (ESCAPE '\\')."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_bills(
    conn: sqlite3.Connection,
    risk: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Return a page of bills (with finding counts) and the total match count.

    Each row carries ``finding_count`` (all findings) plus the breakdown the
    list page shows: ``findings_hoch``/``findings_mittel``/``findings_niedrig``
    over the risk-bearing categories only, so they reconcile with ``risk``, and
    ``findings_verfassung`` for the categories excluded from it.

    Filtered optionally by ``risk``, ``status``, and/or a title substring ``q``
    (SQLite LIKE — case-insensitive for ASCII only, so umlauts match
    case-sensitively). Ordered newest first (by ``aktualisiert`` then
    ``datum``). Returns ``(rows, total)``.
    """
    where = []
    params: list = []
    if risk is not None:
        where.append("b.risk = ?")
        params.append(risk)
    if status is not None:
        where.append("b.status = ?")
        params.append(status)
    if q:
        where.append("b.titel LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(q)}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM bills b {where_sql}", params
    ).fetchone()[0]

    page = max(1, page)
    offset = (page - 1) * page_size
    # Placeholders for the non-risk-bearing category names, repeated once per
    # aggregate below. They precede the WHERE params because sqlite3 binds
    # positionally and the SELECT list comes first.
    cats = ", ".join("?" for _ in _NON_RISK_BEARING_CATEGORIES)
    cat_params = list(_NON_RISK_BEARING_CATEGORIES) * 4
    rows = conn.execute(
        f"""
        SELECT b.*,
               COUNT(f.id) AS finding_count,
               SUM(CASE WHEN f.category NOT IN ({cats})
                         AND f.severity = 'hoch' THEN 1 ELSE 0 END) AS findings_hoch,
               SUM(CASE WHEN f.category NOT IN ({cats})
                         AND f.severity = 'mittel' THEN 1 ELSE 0 END) AS findings_mittel,
               SUM(CASE WHEN f.category NOT IN ({cats})
                         AND f.severity = 'niedrig' THEN 1 ELSE 0 END) AS findings_niedrig,
               SUM(CASE WHEN f.category IN ({cats})
                        THEN 1 ELSE 0 END) AS findings_verfassung
        FROM bills b
        LEFT JOIN findings f ON f.bill_id = b.id
        {where_sql}
        GROUP BY b.id
        ORDER BY b.aktualisiert DESC, b.datum DESC, b.id DESC
        LIMIT ? OFFSET ?
        """,
        cat_params + params + [page_size, offset],
    ).fetchall()
    return [dict(r) for r in rows], total


def get_bill(conn: sqlite3.Connection, bill_id: str) -> dict | None:
    """Return a bill with ``findings`` and ``related_documents``, or ``None``.

    ``analysis_documents`` is parsed into a list (``[]`` when none recorded).
    """
    row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if row is None:
        return None
    bill = dict(row)
    raw_documents = bill.get("analysis_documents")
    bill["analysis_documents"] = json.loads(raw_documents) if raw_documents else []
    finding_rows = conn.execute(
        "SELECT severity, category, title, description, quote "
        "FROM findings WHERE bill_id = ? ORDER BY id",
        (bill_id,),
    ).fetchall()
    bill["findings"] = [dict(f) for f in finding_rows]
    bill["related_documents"] = get_bill_documents(conn, bill_id)
    return bill


def counts(conn: sqlite3.Connection) -> dict:
    """Aggregate bill counts by risk plus ``unanalysiert`` and ``total``."""
    result = {"hoch": 0, "mittel": 0, "niedrig": 0, "unanalysiert": 0, "total": 0}
    for row in conn.execute(
        "SELECT risk, COUNT(*) AS n FROM bills GROUP BY risk"
    ).fetchall():
        risk, n = row["risk"], row["n"]
        if risk in ("hoch", "mittel", "niedrig"):
            result[risk] = n
        else:
            result["unanalysiert"] += n
        result["total"] += n
    return result


def distinct_statuses(conn: sqlite3.Connection) -> list[str]:
    """Return the distinct non-NULL bill statuses, alphabetically."""
    rows = conn.execute(
        "SELECT DISTINCT status FROM bills WHERE status IS NOT NULL ORDER BY status"
    ).fetchall()
    return [r["status"] for r in rows]
