"""Backfill: locating the quotes of findings that are already stored."""

import pytest

from backend import db, locate_quotes, pipeline


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


def test_run_locates_stored_quotes_and_is_idempotent(conn, monkeypatch):
    db.upsert_bill(conn, {
        "id": "1", "dokumentnummer": "21/1", "wahlperiode": 21, "titel": "T",
        "pdf_url": "https://example.org/1.pdf",
    })
    finding = {"severity": "hoch", "category": "referenz", "title": "t", "description": "d",
               "quote": "Die Frist beträgt drei Monate."}
    db.replace_findings(conn, "1", [finding, {**finding, "quote": None}])
    document = {"document_id": "1", "typ": "gesetzentwurf", "dokumentnummer": "21/1",
                "pdf_url": "https://example.org/1.pdf", "pdf_hash": "h"}
    db.mark_analyzed(conn, "1", "hoch", "S", "v7", "m", [document])
    monkeypatch.setattr(
        pipeline.pdf_text, "get_pages",
        lambda url, cache_key=None: ["Erste Seite.", "Die Frist beträgt drei Monate."],
    )

    assert locate_quotes.run(conn) == 0
    first = db.get_bill(conn, "1")
    assert first["findings"][0]["location"]["page"] == 2
    assert first["findings"][1]["location"] is None
    assert first["risk"] == "hoch"

    assert locate_quotes.run(conn) == 0
    def without_ids(findings):
        return [{k: v for k, v in f.items() if k != "id"} for f in findings]

    assert without_ids(db.get_bill(conn, "1")["findings"]) == without_ids(first["findings"])
