"""FastAPI TestClient tests for the HTTP API (Contract 4).

No network: seeds a temporary SQLite file via the db.py public functions and
points the server at it by monkeypatching ``config.DB_PATH``.
"""

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.server import app


def _bill(bill_id: str, **overrides) -> dict:
    base = {
        "id": bill_id,
        "dokumentnummer": f"21/{bill_id}",
        "wahlperiode": 21,
        "titel": f"Entwurf {bill_id}",
        "urheber": "Bundesregierung",
        "datum": "2026-01-01",
        "aktualisiert": f"2026-01-{bill_id[-2:]}T10:00:00",
        "status": "Überwiesen",
        "vorgang_id": f"v{bill_id}",
        "pdf_url": f"https://example.org/{bill_id}.pdf",
        "pdf_hash": "abc",
        "text_chars": 1000,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)

    # Seed the database via the public db.py API.
    conn = db.connect(db_path)
    db.init_db(conn)

    db.upsert_bill(conn, _bill("10", status="Überwiesen"))
    db.upsert_bill(conn, _bill("20", status="Beschlossen"))
    db.upsert_bill(conn, _bill("30", status="Überwiesen"))

    db.replace_findings(
        conn,
        "10",
        [
            {
                "severity": "hoch",
                "category": "referenz",
                "title": "Falscher Verweis",
                "description": "Verweis auf § 5 geht ins Leere.",
                "quote": "gemäß § 5 Absatz 3",
            },
            {
                "severity": "mittel",
                "category": "datum",
                "title": "Unmögliches Datum",
                "description": "Frist endet vor Beginn.",
                "quote": None,
            },
        ],
    )
    db.mark_analyzed(
        conn, "10", "hoch", "Erhebliche Mängel.", config.PROMPT_VERSION, config.ANALYSIS_MODEL,
        [{"document_id": "10", "typ": "gesetzentwurf", "dokumentnummer": "21/10",
          "datum": "2026-01-01", "pdf_url": "https://example.org/10.pdf",
          "pdf_hash": "abc", "aktualisiert": "2026-01-10T10:00:00", "text_chars": 1000}],
        trace="20260101-000000/traces/21-10.jsonl",
    )

    db.replace_findings(
        conn,
        "20",
        [
            {
                "severity": "niedrig",
                "category": "unklarheit",
                "title": "Leichte Mehrdeutigkeit",
                "description": "Begriff nicht definiert.",
                "quote": "der Betreiber",
            }
        ],
    )
    db.mark_analyzed(conn, "20", "niedrig", "Kaum Auffälligkeiten.", config.PROMPT_VERSION, config.ANALYSIS_MODEL, [])

    db.replace_bill_documents(
        conn, "10", "beschlussempfehlung",
        [{"document_id": "900", "dokumentnummer": "21/900", "titel": "Beschlussempfehlung",
          "datum": "2026-02-01", "aktualisiert": "2026-02-02T10:00:00",
          "pdf_url": "https://example.org/900.pdf", "pdf_hash": None}],
    )

    # Bill "30" left unanalyzed (risk NULL, no findings).
    conn.close()

    with TestClient(app) as c:
        yield c


def test_list_shape_and_fields(client):
    resp = client.get("/api/bills")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 3
    item = body["items"][0]
    assert set(item.keys()) == {
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
    }


def test_list_finding_count(client):
    resp = client.get("/api/bills")
    by_id = {i["id"]: i for i in resp.json()["items"]}
    assert by_id["10"]["finding_count"] == 2
    assert by_id["20"]["finding_count"] == 1
    assert by_id["30"]["finding_count"] == 0


def test_list_filter_by_risk(client):
    resp = client.get("/api/bills", params={"risk": "hoch"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "10"


def test_list_filter_by_status(client):
    resp = client.get("/api/bills", params={"status": "Überwiesen"})
    body = resp.json()
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {"10", "30"}


def test_list_search_by_title(client):
    # Seeded titles are "Entwurf 10", "Entwurf 20", "Entwurf 30".
    resp = client.get("/api/bills", params={"q": "entwurf 2"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "20"

    resp = client.get("/api/bills", params={"q": "kein treffer"})
    assert resp.json()["total"] == 0


def test_list_search_blank_q_ignored(client):
    resp = client.get("/api/bills", params={"q": "   "})
    assert resp.json()["total"] == 3


def test_list_search_combines_with_status(client):
    resp = client.get("/api/bills", params={"q": "Entwurf", "status": "Überwiesen"})
    body = resp.json()
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {"10", "30"}


def test_list_pagination(client):
    resp = client.get("/api/bills", params={"page": 2, "page_size": 2})
    body = resp.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 1


def test_list_page_size_capped(client):
    resp = client.get("/api/bills", params={"page_size": 5000})
    assert resp.json()["page_size"] == 100


def test_list_invalid_risk_rejected(client):
    resp = client.get("/api/bills", params={"risk": "kritisch"})
    assert resp.status_code == 422


def test_detail_includes_findings(client):
    resp = client.get("/api/bills/10")
    assert resp.status_code == 200
    bill = resp.json()
    assert bill["id"] == "10"
    assert bill["dokumentnummer"] == "21/10"
    assert bill["risk"] == "hoch"
    assert bill["summary"] == "Erhebliche Mängel."
    assert isinstance(bill["findings"], list)
    assert len(bill["findings"]) == 2
    finding = bill["findings"][0]
    assert set(finding.keys()) == {
        "severity",
        "category",
        "title",
        "description",
        "quote",
    }


def test_detail_includes_analysis_documents(client):
    documents = client.get("/api/bills/10").json()["analysis_documents"]
    assert documents == [
        {
            "document_id": "10",
            "typ": "gesetzentwurf",
            "dokumentnummer": "21/10",
            "datum": "2026-01-01",
            "pdf_url": "https://example.org/10.pdf",
            "pdf_hash": "abc",
            "aktualisiert": "2026-01-10T10:00:00",
            "text_chars": 1000,
        }
    ]


def test_detail_never_exposes_the_local_trace_path(client):
    assert "analysis_trace" not in client.get("/api/bills/10").json()


def test_detail_analysis_documents_empty_when_unanalyzed(client):
    assert client.get("/api/bills/30").json()["analysis_documents"] == []


def test_detail_includes_related_documents(client):
    assert client.get("/api/bills/10").json()["related_documents"] == [
        {
            "document_id": "900",
            "typ": "beschlussempfehlung",
            "dokumentnummer": "21/900",
            "titel": "Beschlussempfehlung",
            "datum": "2026-02-01",
            "aktualisiert": "2026-02-02T10:00:00",
            "pdf_url": "https://example.org/900.pdf",
            "pdf_hash": None,
        }
    ]
    assert client.get("/api/bills/30").json()["related_documents"] == []


def test_list_items_omit_related_documents(client):
    items = client.get("/api/bills").json()["items"]
    assert all("related_documents" not in item for item in items)


def test_detail_unknown_404(client):
    resp = client.get("/api/bills/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Bill not found"}


def test_meta_shape(client):
    resp = client.get("/api/meta")
    assert resp.status_code == 200
    meta = resp.json()
    assert set(meta.keys()) == {
        "counts",
        "statuses",
        "prompt_version",
        "model",
        "last_analyzed_at",
        "contact_email",
    }
    assert meta["counts"] == {
        "hoch": 1,
        "mittel": 0,
        "niedrig": 1,
        "unanalysiert": 1,
        "total": 3,
    }
    assert meta["statuses"] == ["Beschlossen", "Überwiesen"]
    assert meta["prompt_version"] == config.PROMPT_VERSION
    assert meta["model"] == config.ANALYSIS_MODEL
    assert meta["last_analyzed_at"] is not None


def test_meta_last_analyzed_null_when_none(tmp_path, monkeypatch):
    db_path = str(tmp_path / "empty.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    conn = db.connect(db_path)
    db.init_db(conn)
    db.upsert_bill(conn, _bill("99"))  # never analyzed
    conn.close()
    with TestClient(app) as c:
        meta = c.get("/api/meta").json()
    assert meta["last_analyzed_at"] is None
    assert meta["counts"]["unanalysiert"] == 1


def test_meta_contact_email_null_unless_configured(client, monkeypatch):
    monkeypatch.setattr(config, "CONTACT_EMAIL", "")
    assert client.get("/api/meta").json()["contact_email"] is None
    monkeypatch.setattr(config, "CONTACT_EMAIL", "kontakt@example.org")
    assert client.get("/api/meta").json()["contact_email"] == "kontakt@example.org"


# --- Evaluation reports -----------------------------------------------------


@pytest.fixture()
def eval_client(tmp_path, monkeypatch):
    folder = tmp_path / "eval-public"
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "EVAL_PUBLIC_DIR", str(folder))
    with TestClient(app) as c:
        yield c, folder


def test_eval_without_folder(eval_client):
    client, _ = eval_client
    resp = client.get("/api/eval")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["X-Robots-Tag"].startswith("noindex")


def test_eval_lists_and_serves_html_reports(eval_client):
    client, folder = eval_client
    (folder / "runs").mkdir(parents=True)
    (folder / "runs" / "dev.html").write_text("<html><title> Lauf\n dev </title>", encoding="utf-8")
    (folder / "top.html").write_text("<p>no title</p>", encoding="utf-8")
    (folder / "notes.txt").write_text("x", encoding="utf-8")

    reports = client.get("/api/eval").json()
    assert [(r["path"], r["title"]) for r in reports] == [("top.html", "top.html"),
                                                          ("runs/dev.html", "Lauf dev")]
    assert all(r["modified"] for r in reports)

    report = client.get("/api/eval/reports/runs/dev.html")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/html")
    assert report.headers["X-Robots-Tag"].startswith("noindex")
    assert client.get("/api/eval/reports/notes.txt").status_code == 404


def test_eval_reports_stay_inside_the_folder(eval_client, tmp_path):
    client, folder = eval_client
    folder.mkdir()
    (tmp_path / "secret.html").write_text("secret", encoding="utf-8")
    (folder / "link.html").symlink_to(tmp_path / "secret.html")

    assert client.get("/api/eval/reports/%2E%2E/secret.html").status_code == 404
    assert client.get("/api/eval/reports/link.html").status_code == 404


def test_eval_folder_behind_a_swapped_symlink(eval_client, tmp_path):
    client, folder = eval_client
    for name in ("r1", "r2"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.html").write_text(name, encoding="utf-8")
    folder.symlink_to(tmp_path / "r1")
    assert [r["path"] for r in client.get("/api/eval").json()] == ["r1.html"]

    folder.unlink()
    folder.symlink_to(tmp_path / "r2")
    assert [r["path"] for r in client.get("/api/eval").json()] == ["r2.html"]
    assert client.get("/api/eval/reports/r2.html").text == "r2"
