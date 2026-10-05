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


_EXPLOIT = {
    "muster": "schwellenwert",
    "akteur": "Ein Konzern, der die Steuer vermeiden will.",
    "titel": "Erwerb knapp unter der Schwelle",
    "schritte": ["Erwerb von 89,9 Prozent.", "Ein Mitinvestor hält den Rest."],
    "vorteil": "Die Steuer entfällt.",
    "aufwand": "mittel",
    "quote": "mindestens 90 vom Hundert",
    "fehlende_absicherung": "Eine Zurechnung abgestimmter Erwerbe fehlt.",
    "severity": "hoch",
}


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
    db.replace_exploits(conn, "10", [_EXPLOIT])
    db.mark_redteamed(
        conn, "10", "Ein Angriff.", config.REDTEAM_PROMPT_VERSION, config.REDTEAM_MODEL,
        [{"document_id": "10", "typ": "gesetzentwurf", "dokumentnummer": "21/10",
          "datum": "2026-01-01", "pdf_url": "https://example.org/10.pdf",
          "pdf_hash": "abc", "aktualisiert": "2026-01-10T10:00:00", "text_chars": 1000}],
        trace="20260102-000000-redteam/traces/21-10.jsonl",
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
        "id",
        "severity",
        "category",
        "title",
        "description",
        "quote",
        "location",
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
    bill = client.get("/api/bills/10").json()
    assert "analysis_trace" not in bill
    assert "redteam_trace" not in bill


def test_detail_includes_exploits_and_the_redteam_pass(client):
    bill = client.get("/api/bills/10").json()
    assert [{k: v for k, v in e.items() if k != "id"} for e in bill["exploits"]] == [_EXPLOIT]
    assert bill["redteam_summary"] == "Ein Angriff."
    assert bill["redteam_prompt_version"] == config.REDTEAM_PROMPT_VERSION
    assert bill["redteamed_at"] is not None
    assert bill["redteam_documents"][0]["dokumentnummer"] == "21/10"
    # Exploits never enter the risk.
    assert bill["risk"] == "hoch" and len(bill["findings"]) == 2


def test_detail_exploits_empty_when_the_pass_has_not_run(client):
    bill = client.get("/api/bills/20").json()
    assert bill["exploits"] == []
    assert bill["redteamed_at"] is None
    assert bill["redteam_documents"] == []


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
        "verfassung": 0,
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


def test_list_verfassung_filter(client):
    # No bill in the fixture has a constitutional finding.
    assert client.get("/api/bills?verfassung=1").json()["total"] == 0
    assert client.get("/api/bills?verfassung=0").json()["total"] == 3


# --- POST /api/feedback -----------------------------------------------------


@pytest.fixture()
def feedback_dir(tmp_path, monkeypatch):
    path = tmp_path / "feedback"
    monkeypatch.setattr(config, "FEEDBACK_DIR", str(path))
    return path


def _feedback_records(feedback_dir) -> list[dict]:
    import json

    return [json.loads(line) for file in sorted(feedback_dir.glob("*.jsonl"))
            for line in file.read_text(encoding="utf-8").splitlines()]


def test_feedback_on_a_finding_is_appended_with_its_snapshot(client, feedback_dir):
    finding = client.get("/api/bills/10").json()["findings"][0]
    r = client.post("/api/feedback", json={"kind": "finding", "id": finding["id"],
                                           "verdict": "down", "text": "  § 5 gibt es.  "})
    assert r.status_code == 201
    (record,) = _feedback_records(feedback_dir)
    assert record["at"]
    assert {k: v for k, v in record.items() if k not in ("at", "analyzed_at")} == {
        "kind": "finding", "verdict": "down", "text": "§ 5 gibt es.",
        "bill_id": "10", "dokumentnummer": "21/10", "category": "referenz",
        "severity": "hoch", "title": "Falscher Verweis", "quote": "gemäß § 5 Absatz 3",
        "prompt_version": config.PROMPT_VERSION, "model": config.ANALYSIS_MODEL,
    }


def test_feedback_on_an_exploit_records_the_redteam_run(client, feedback_dir):
    exploit = client.get("/api/bills/10").json()["exploits"][0]
    r = client.post("/api/feedback", json={"kind": "exploit", "id": exploit["id"], "verdict": "up"})
    assert r.status_code == 201
    (record,) = _feedback_records(feedback_dir)
    assert record["title"] == _EXPLOIT["titel"] and record["category"] == _EXPLOIT["muster"]
    assert record["prompt_version"] == config.REDTEAM_PROMPT_VERSION
    assert record["text"] == ""


def test_feedback_appends_one_line_per_submission(client, feedback_dir):
    finding = client.get("/api/bills/10").json()["findings"][0]
    for verdict in ("up", "down"):
        client.post("/api/feedback", json={"kind": "finding", "id": finding["id"], "verdict": verdict})
    assert [r["verdict"] for r in _feedback_records(feedback_dir)] == ["up", "down"]


def test_feedback_rejects_unknown_targets_and_bad_input(client, feedback_dir):
    finding = client.get("/api/bills/10").json()["findings"][0]
    ok = {"kind": "finding", "id": finding["id"], "verdict": "up"}
    assert client.post("/api/feedback", json=ok | {"id": 999999}).status_code == 404
    assert client.post("/api/feedback", json=ok | {"verdict": "maybe"}).status_code == 422
    assert client.post("/api/feedback", json=ok | {"kind": "bill"}).status_code == 422
    assert client.post("/api/feedback", json=ok | {"text": "x" * 2001}).status_code == 422
    assert not feedback_dir.exists()


def test_feedback_stops_when_the_months_file_is_full(client, feedback_dir, monkeypatch):
    from backend import feedback

    finding = client.get("/api/bills/10").json()["findings"][0]
    body = {"kind": "finding", "id": finding["id"], "verdict": "up"}
    assert client.post("/api/feedback", json=body).status_code == 201
    monkeypatch.setattr(feedback, "MAX_FILE_BYTES", 1)
    assert client.post("/api/feedback", json=body).status_code == 503
    assert len(_feedback_records(feedback_dir)) == 1
