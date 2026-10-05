"""SQLite storage layer for LLM-Lesung (Contract 1).

Plain stdlib ``sqlite3``, no ORM. One database file holds the bills, their AI
findings and the exploits of the adversarial pass. All public functions take an open connection so callers control
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
  analysis_trace TEXT,                   -- trace of the call that produced it, relative to PIPELINE_RUNS_DIR; NULL = none
  -- adversarial pass (independent of the analysis above):
  redteam_summary TEXT,                  -- 1-3 sentence German summary of the pass
  redteam_prompt_version TEXT,
  redteam_model TEXT,
  redteamed_at  TEXT,                    -- NULL = pass not run; set even when it found no exploit
  redteam_documents TEXT,                -- JSON array: the Gesetzentwurf the stored pass read; NULL = none recorded
  redteam_trace TEXT                     -- trace of the call that produced it, relative to PIPELINE_RUNS_DIR; NULL = none
);

CREATE TABLE IF NOT EXISTS findings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  bill_id     TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  severity    TEXT NOT NULL,             -- 'hoch'|'mittel'|'niedrig'
  category    TEXT NOT NULL,             -- see analysis.schema.Category (6 craft + verfassungsrisiko|kompetenz)
  title       TEXT NOT NULL,             -- short German headline
  description TEXT NOT NULL,             -- German explanation
  quote       TEXT,                      -- verbatim excerpt from the bill, may be NULL
  -- where the quote stands in the documents the analysis read; all NULL when not located:
  quote_document_id TEXT,                -- DIP drucksache id
  quote_page  INTEGER,                   -- 1-based page of the PDF
  quote_before TEXT,                     -- document text before the quote
  quote_match TEXT,                      -- the quote as the document spells it
  quote_after TEXT                       -- document text after the quote
);

CREATE INDEX IF NOT EXISTS idx_findings_bill_id ON findings(bill_id);

-- Attacks the adversarial pass found; never part of a bill's risk.
CREATE TABLE IF NOT EXISTS exploits (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  bill_id     TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  muster      TEXT NOT NULL,             -- see analysis.schema.Muster
  akteur      TEXT NOT NULL,             -- role, interest and capability
  titel       TEXT NOT NULL,             -- short German headline
  schritte_json TEXT NOT NULL,           -- JSON array: the attack as a sequence of steps
  vorteil     TEXT NOT NULL,             -- what is extracted, in the bill's own currency
  aufwand     TEXT NOT NULL,             -- 'niedrig'|'mittel'|'hoch'
  quote       TEXT NOT NULL,             -- verbatim excerpt from the bill
  fehlende_absicherung TEXT NOT NULL,    -- the sentence that would have stopped it
  severity    TEXT NOT NULL              -- 'hoch'|'mittel'|'niedrig'
);

CREATE INDEX IF NOT EXISTS idx_exploits_bill_id ON exploits(bill_id);

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

# Columns of the bills table added after its first release; ``init_db`` adds
# the ones a database file lacks.
_ADDED_BILL_COLUMNS = [
    "analysis_documents",
    "analysis_trace",
    "redteam_summary",
    "redteam_prompt_version",
    "redteam_model",
    "redteamed_at",
    "redteam_documents",
    "redteam_trace",
]

# The same for the findings table. Each maps a key of a finding's ``location``
# to its column and type.
_LOCATION_COLUMNS = {
    "document_id": ("quote_document_id", "TEXT"),
    "page": ("quote_page", "INTEGER"),
    "before": ("quote_before", "TEXT"),
    "match": ("quote_match", "TEXT"),
    "after": ("quote_after", "TEXT"),
}

# Columns of the bills table that ``upsert_bill`` writes on insert/refresh.
# Result columns are managed separately by ``mark_analyzed`` and
# ``mark_redteamed``.
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
    access, and turns on foreign-key enforcement (needed for the
    ``ON DELETE CASCADE`` of findings and exploits). Pass ``":memory:"`` for an in-memory database
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
    for column in _ADDED_BILL_COLUMNS:
        if column not in columns:
            conn.execute(f"ALTER TABLE bills ADD COLUMN {column} TEXT")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(findings)")}
    for column, sql_type in _LOCATION_COLUMNS.values():
        if column not in columns:
            conn.execute(f"ALTER TABLE findings ADD COLUMN {column} {sql_type}")
    conn.commit()


def upsert_bill(conn: sqlite3.Connection, bill: dict) -> None:
    """Insert or update the DIP-sourced columns of a bill.

    Result columns (risk, summary, ``redteam_*``, ...) are left untouched so an
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
    """Replace all findings for a bill wholesale (idempotent re-analysis).

    A finding's optional ``location`` (``document_id``, ``page``, ``before``,
    ``match``, ``after``) says where its quote stands.
    """
    location_columns = [column for column, _ in _LOCATION_COLUMNS.values()]
    columns = ["bill_id", "severity", "category", "title", "description", "quote"]
    columns += location_columns
    conn.execute("DELETE FROM findings WHERE bill_id = ?", (bill_id,))
    conn.executemany(
        f"INSERT INTO findings ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        [
            (
                bill_id,
                f.get("severity"),
                f.get("category"),
                f.get("title"),
                f.get("description"),
                f.get("quote"),
                *((f.get("location") or {}).get(key) for key in _LOCATION_COLUMNS),
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


_EXPLOIT_COLUMNS = [
    "muster",
    "akteur",
    "titel",
    "vorteil",
    "aufwand",
    "quote",
    "fehlende_absicherung",
    "severity",
]


def replace_exploits(
    conn: sqlite3.Connection, bill_id: str, exploits: list[dict]
) -> None:
    """Replace all exploits for a bill wholesale (idempotent re-run)."""
    conn.execute("DELETE FROM exploits WHERE bill_id = ?", (bill_id,))
    columns = ", ".join(_EXPLOIT_COLUMNS)
    placeholders = ", ".join("?" for _ in _EXPLOIT_COLUMNS)
    conn.executemany(
        f"INSERT INTO exploits (bill_id, schritte_json, {columns}) "
        f"VALUES (?, ?, {placeholders})",
        [
            [bill_id, json.dumps(e.get("schritte"), ensure_ascii=False)]
            + [e.get(col) for col in _EXPLOIT_COLUMNS]
            for e in exploits
        ],
    )
    conn.commit()


def mark_redteamed(
    conn: sqlite3.Connection,
    bill_id: str,
    summary: str,
    prompt_version: str,
    model: str,
    documents: list[dict],
    trace: str | None = None,
) -> None:
    """Record the adversarial pass on a bill; sets ``redteamed_at`` to now (UTC).

    ``documents`` lists what the pass read, in the shape of
    ``analysis_documents``, and ``trace`` the trace file of the call. The
    analysis columns are not touched.
    """
    conn.execute(
        "UPDATE bills SET redteam_summary = ?, redteam_prompt_version = ?, "
        "redteam_model = ?, redteam_documents = ?, redteam_trace = ?, "
        "redteamed_at = datetime('now') WHERE id = ?",
        (
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
    verfassung: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Return a page of bills (with finding counts) and the total match count.

    Each row carries ``finding_count`` (all findings) plus the breakdown the
    list page shows: ``findings_hoch``/``findings_mittel``/``findings_niedrig``
    over the risk-bearing categories only, so they reconcile with ``risk``, and
    ``findings_verfassung`` for the categories excluded from it.

    Filtered optionally by ``risk``, ``status``, a title substring ``q``
    (SQLite LIKE — case-insensitive for ASCII only, so umlauts match
    case-sensitively) and/or ``verfassung`` (only bills with a finding in the
    categories excluded from ``risk``). Ordered newest first (by ``aktualisiert`` then
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
    cats = ", ".join("?" for _ in _NON_RISK_BEARING_CATEGORIES)
    if verfassung:
        where.append(
            "EXISTS (SELECT 1 FROM findings v WHERE v.bill_id = b.id "
            f"AND v.category IN ({cats}))"
        )
        params.extend(_NON_RISK_BEARING_CATEGORIES)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM bills b {where_sql}", params
    ).fetchone()[0]

    page = max(1, page)
    offset = (page - 1) * page_size
    # Placeholders for the non-risk-bearing category names, repeated once per
    # aggregate below. They precede the WHERE params because sqlite3 binds
    # positionally and the SELECT list comes first.
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


def bill_ids(conn: sqlite3.Connection) -> list[str]:
    """Every bill's id, newest first (the order of ``list_bills``)."""
    rows = conn.execute(
        "SELECT id FROM bills ORDER BY aktualisiert DESC, datum DESC, id DESC"
    ).fetchall()
    return [r["id"] for r in rows]


def get_bill(conn: sqlite3.Connection, bill_id: str) -> dict | None:
    """Return a bill with ``findings``, ``exploits`` and ``related_documents``, or ``None``.

    ``analysis_documents`` and ``redteam_documents`` are parsed into lists
    (``[]`` when none recorded), and each exploit's ``schritte`` likewise. Each
    finding carries ``location``: where its quote stands, or ``None``. The
    ``id`` of a finding or exploit lasts only until its bill's next replace.
    """
    row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if row is None:
        return None
    bill = dict(row)
    for key in ("analysis_documents", "redteam_documents"):
        bill[key] = json.loads(bill[key]) if bill.get(key) else []
    location_columns = ", ".join(column for column, _ in _LOCATION_COLUMNS.values())
    finding_rows = conn.execute(
        f"SELECT id, severity, category, title, description, quote, {location_columns} "
        "FROM findings WHERE bill_id = ? ORDER BY id",
        (bill_id,),
    ).fetchall()
    bill["findings"] = [
        {
            **{key: f[key] for key in ("id", "severity", "category", "title", "description", "quote")},
            "location": (
                {key: f[column] for key, (column, _) in _LOCATION_COLUMNS.items()}
                if f["quote_page"] is not None
                else None
            ),
        }
        for f in finding_rows
    ]
    exploit_rows = conn.execute(
        f"SELECT id, schritte_json, {', '.join(_EXPLOIT_COLUMNS)} "
        "FROM exploits WHERE bill_id = ? ORDER BY id",
        (bill_id,),
    ).fetchall()
    bill["exploits"] = [
        {"id": e["id"], **{col: e[col] for col in _EXPLOIT_COLUMNS},
         "schritte": json.loads(e["schritte_json"])}
        for e in exploit_rows
    ]
    bill["related_documents"] = get_bill_documents(conn, bill_id)
    return bill


def get_feedback_target(conn: sqlite3.Connection, kind: str, target_id: int) -> dict | None:
    """What a piece of feedback is about: one finding or exploit plus the run that produced it.

    ``kind`` is ``"finding"`` or ``"exploit"``. The result is self-contained,
    because the row itself is gone after the bill's next analysis.
    """
    if kind == "finding":
        sql = (
            "SELECT b.id AS bill_id, b.dokumentnummer, f.category, f.severity, f.title, f.quote, "
            "b.prompt_version, b.model, b.analyzed_at "
            "FROM findings f JOIN bills b ON b.id = f.bill_id WHERE f.id = ?"
        )
    else:
        sql = (
            "SELECT b.id AS bill_id, b.dokumentnummer, e.muster AS category, e.severity, "
            "e.titel AS title, e.quote, b.redteam_prompt_version AS prompt_version, "
            "b.redteam_model AS model, b.redteamed_at AS analyzed_at "
            "FROM exploits e JOIN bills b ON b.id = e.bill_id WHERE e.id = ?"
        )
    row = conn.execute(sql, (target_id,)).fetchone()
    return dict(row) if row else None


def counts(conn: sqlite3.Connection) -> dict:
    """Aggregate bill counts by risk plus ``unanalysiert`` and ``total``.

    ``verfassung`` counts the bills with a finding in the categories excluded
    from ``risk``; it overlaps the risk counts.
    """
    result = {"hoch": 0, "mittel": 0, "niedrig": 0, "unanalysiert": 0, "total": 0}
    cats = ", ".join("?" for _ in _NON_RISK_BEARING_CATEGORIES)
    result["verfassung"] = conn.execute(
        f"SELECT COUNT(DISTINCT bill_id) FROM findings WHERE category IN ({cats})",
        _NON_RISK_BEARING_CATEGORIES,
    ).fetchone()[0]
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
