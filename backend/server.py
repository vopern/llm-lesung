"""FastAPI web server for LLM-Lesung (Contract 4).

Serves the read-only JSON API over the SQLite database and, in production,
the built React SPA from ``frontend/dist``. It depends only on ``db.py`` and
``config.py``: the web layer never calls Claude or DIP, it only reads the
database the pipeline produces and lists the HTML evaluation reports placed in
``EVAL_PUBLIC_DIR``.

Endpoints:
- ``GET /api/bills``      paginated, filterable list of bills
- ``GET /api/bills/{id}`` full bill incl. findings, analyzed and related documents (404 if unknown)
- ``GET /api/meta``       aggregate counts, statuses, prompt/model, last run, contact address
- ``GET /api/eval``       the HTML evaluation reports, with title and modification time
- ``GET /api/eval/reports/{path}``   one of those reports
"""

import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import config, db

# Directory holding the built frontend (Vite output). Absent in dev.
_FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"
)

# Fields exposed for each row of the list endpoint (Contract 4).
_LIST_FIELDS = (
    "id",
    "dokumentnummer",
    "titel",
    "status",
    "risk",
    "datum",
    "aktualisiert",
    "finding_count",
    "findings_hoch",
    "findings_mittel",
    "findings_niedrig",
    "findings_verfassung",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the schema exists once at startup."""
    conn = db.connect(config.DB_PATH)
    try:
        db.init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="LLM-Lesung API", lifespan=lifespan)

# CORS for local dev (Vite dev server on a different port).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Evaluation reports carry test-set content; keep them out of search indexes and,
# as far as crawlers honour it, out of training corpora.
_NOINDEX_PREFIXES = ("/api/eval", "/evaluation")


@app.middleware("http")
async def noindex_eval(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(_NOINDEX_PREFIXES):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def get_conn():
    """Per-request database connection (FastAPI dependency).

    Reads ``config.DB_PATH`` at call time so tests can monkeypatch it.
    """
    conn = db.connect(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/bills")
def api_bills(
    risk: Literal["hoch", "mittel", "niedrig"] | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Paginated, filterable list of bills."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))  # cap page_size at 100
    q = q.strip() if q else None
    rows, total = db.list_bills(
        conn, risk=risk, status=status, q=q or None, page=page, page_size=page_size
    )
    items = [{field: row[field] for field in _LIST_FIELDS} for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/bills/{bill_id}")
def api_bill(
    bill_id: str, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """Full bill with findings, ``analysis_documents`` and ``related_documents``; 404 if unknown.

    ``analysis_trace`` names a file that exists only where the pipeline ran.
    """
    bill = db.get_bill(conn, bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    bill.pop("analysis_trace", None)
    return bill


@app.get("/api/meta")
def api_meta(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """Aggregate counts, distinct statuses, prompt/model, last analysis time, contact address."""
    # Single direct query permitted by the story (db.py has no such helper):
    # newest analysis timestamp across all bills, or None if none analyzed.
    last_analyzed_at = conn.execute("SELECT MAX(analyzed_at) FROM bills").fetchone()[0]
    return {
        "counts": db.counts(conn),
        "statuses": db.distinct_statuses(conn),
        "prompt_version": config.PROMPT_VERSION,
        "model": config.ANALYSIS_MODEL,
        "last_analyzed_at": last_analyzed_at,
        "contact_email": config.CONTACT_EMAIL or None,
    }


# --- Evaluation reports -----------------------------------------------------
# Whatever HTML sits in EVAL_PUBLIC_DIR is published. Read on every request:
# `make push-eval` swaps the directory underneath.

_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _eval_base() -> str:
    return os.path.realpath(config.EVAL_PUBLIC_DIR)


def _report_title(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        match = _TITLE.search(f.read(8192))
    return " ".join(match.group(1).split()) if match else os.path.basename(path)


@app.get("/api/eval")
def api_eval() -> list[dict]:
    """Every HTML report in the evaluation folder, by path."""
    base = _eval_base()
    reports = []
    for root, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".html"):
                path = os.path.join(root, name)
                modified = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
                reports.append({"path": os.path.relpath(path, base).replace(os.sep, "/"),
                                "title": _report_title(path),
                                "modified": modified.isoformat(timespec="seconds")})
    return reports


@app.get("/api/eval/reports/{path:path}")
def api_eval_report(path: str):
    """One HTML report from the evaluation folder; nothing outside it, nothing but HTML."""
    base = _eval_base()
    candidate = os.path.realpath(os.path.join(base, path))
    if (not candidate.startswith(base + os.sep) or not candidate.endswith(".html")
            or not os.path.isfile(candidate)):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(candidate, media_type="text/html")


# --- Static frontend (production) ------------------------------------------
# Registered AFTER the API routes so /api/* always wins. Guarded so the app
# still boots in dev when the frontend has not been built yet.
if os.path.isdir(_FRONTEND_DIST):
    _assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    _index_html = os.path.join(_FRONTEND_DIST, "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        """Serve a matching static file, else index.html (SPA client routing).

        The ``/{full_path:path}`` route is the least specific, so it only runs
        when no /api route and no mounted asset matched. Unknown /api paths
        still 404 rather than leaking the SPA shell.
        """
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = os.path.normpath(os.path.join(_FRONTEND_DIST, full_path))
        # Keep the served path inside the dist directory.
        if (
            full_path
            and candidate.startswith(_FRONTEND_DIST + os.sep)
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        return FileResponse(_index_html)
