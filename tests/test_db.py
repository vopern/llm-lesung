"""Round-trip tests for the SQLite storage layer (in-memory, no network)."""

import pytest

from backend import db


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


def _bill(bill_id: str, **overrides) -> dict:
    base = {
        "id": bill_id,
        "dokumentnummer": f"21/{bill_id}",
        "wahlperiode": 21,
        "titel": f"Entwurf {bill_id}",
        "urheber": "Bundesregierung",
        "datum": "2026-01-01",
        "aktualisiert": "2026-01-02T10:00:00",
        "status": "Überwiesen",
        "vorgang_id": f"v{bill_id}",
        "pdf_url": f"https://example.org/{bill_id}.pdf",
        "pdf_hash": "abc",
        "text_chars": 1000,
    }
    base.update(overrides)
    return base


def test_upsert_and_get_bill(conn):
    db.upsert_bill(conn, _bill("100"))
    bill = db.get_bill(conn, "100")
    assert bill is not None
    assert bill["dokumentnummer"] == "21/100"
    assert bill["titel"] == "Entwurf 100"
    assert bill["findings"] == []
    assert bill["risk"] is None


def test_get_bill_unknown(conn):
    assert db.get_bill(conn, "nope") is None


def test_upsert_is_idempotent_update(conn):
    db.upsert_bill(conn, _bill("100", titel="Alt"))
    db.upsert_bill(conn, _bill("100", titel="Neu"))
    assert db.get_bill(conn, "100")["titel"] == "Neu"
    # only one row
    rows, total = db.list_bills(conn)
    assert total == 1


def test_upsert_preserves_analysis(conn):
    db.upsert_bill(conn, _bill("100"))
    db.mark_analyzed(conn, "100", "hoch", "Zusammenfassung", "v1-systematisch", "claude-opus-4-8", [])
    # re-upsert (e.g. metadata refresh) must not wipe analysis
    db.upsert_bill(conn, _bill("100", titel="Neuer Titel"))
    bill = db.get_bill(conn, "100")
    assert bill["risk"] == "hoch"
    assert bill["summary"] == "Zusammenfassung"
    assert bill["titel"] == "Neuer Titel"


def test_replace_findings_and_count(conn):
    db.upsert_bill(conn, _bill("100"))
    findings = [
        {
            "severity": "hoch",
            "category": "referenz",
            "title": "Falscher Verweis",
            "description": "Verweis geht ins Leere.",
            "quote": "§ 5 Abs. 9",
        },
        {
            "severity": "niedrig",
            "category": "unklarheit",
            "title": "Mehrdeutig",
            "description": "Unklare Formulierung.",
            "quote": None,
        },
    ]
    db.replace_findings(conn, "100", findings)
    bill = db.get_bill(conn, "100")
    assert len(bill["findings"]) == 2
    assert bill["findings"][0]["category"] == "referenz"
    assert bill["findings"][1]["quote"] is None

    # replace wholesale
    db.replace_findings(conn, "100", [findings[0]])
    assert len(db.get_bill(conn, "100")["findings"]) == 1


def test_mark_analyzed(conn):
    db.upsert_bill(conn, _bill("100"))
    db.mark_analyzed(conn, "100", "mittel", "OK", "v1-systematisch", "claude-opus-4-8", [])
    bill = db.get_bill(conn, "100")
    assert bill["risk"] == "mittel"
    assert bill["summary"] == "OK"
    assert bill["prompt_version"] == "v1-systematisch"
    assert bill["model"] == "claude-opus-4-8"
    assert bill["analyzed_at"] is not None
    assert bill["analysis_trace"] is None


def test_mark_analyzed_records_the_trace(conn):
    db.upsert_bill(conn, _bill("100"))
    trace = "20261001-120000/traces/21-100.jsonl"
    db.mark_analyzed(conn, "100", "mittel", "OK", "v", "m", [], trace=trace)
    assert db.get_bill(conn, "100")["analysis_trace"] == trace


def _documents() -> list[dict]:
    return [
        {
            "document_id": "100",
            "typ": "gesetzentwurf",
            "dokumentnummer": "21/100",
            "datum": "2026-01-01",
            "pdf_url": "https://example.org/100.pdf",
            "pdf_hash": "abc",
            "aktualisiert": "2026-01-02T10:00:00",
            "text_chars": 1000,
        },
        {
            "document_id": "900",
            "typ": "beschlussempfehlung",
            "dokumentnummer": "21/900",
            "datum": "2026-02-01",
            "pdf_url": "https://example.org/900.pdf",
            "pdf_hash": None,
            "aktualisiert": "2026-02-02T10:00:00",
            "text_chars": 2000,
        },
    ]


def test_analysis_documents_round_trip(conn):
    db.upsert_bill(conn, _bill("100"))
    db.mark_analyzed(conn, "100", "mittel", "OK", "v", "m", _documents())
    assert db.get_bill(conn, "100")["analysis_documents"] == _documents()


def test_analysis_documents_empty_when_not_recorded(conn):
    db.upsert_bill(conn, _bill("100"))
    assert db.get_bill(conn, "100")["analysis_documents"] == []


def test_upsert_preserves_analysis_documents(conn):
    db.upsert_bill(conn, _bill("100"))
    db.mark_analyzed(conn, "100", "mittel", "OK", "v", "m", _documents())
    db.upsert_bill(conn, _bill("100", pdf_hash="changed"))
    assert db.get_bill(conn, "100")["analysis_documents"] == _documents()


def test_reanalysis_replaces_analysis_documents(conn):
    db.upsert_bill(conn, _bill("100"))
    db.mark_analyzed(conn, "100", "mittel", "OK", "v", "m", _documents())
    db.mark_analyzed(conn, "100", "hoch", "Neu", "v", "m", _documents()[:1])
    assert db.get_bill(conn, "100")["analysis_documents"] == _documents()[:1]


def test_init_db_adds_analysis_documents_to_existing_table():
    c = db.connect(":memory:")
    # A bills table without the analysis_documents column.
    c.execute(
        "CREATE TABLE bills (id TEXT PRIMARY KEY, dokumentnummer TEXT NOT NULL, "
        "wahlperiode INTEGER NOT NULL, titel TEXT NOT NULL, urheber TEXT, datum TEXT, "
        "aktualisiert TEXT, status TEXT, vorgang_id TEXT, pdf_url TEXT NOT NULL, "
        "pdf_hash TEXT, text_chars INTEGER, risk TEXT, summary TEXT, "
        "prompt_version TEXT, model TEXT, analyzed_at TEXT)"
    )
    c.execute(
        "INSERT INTO bills (id, dokumentnummer, wahlperiode, titel, pdf_url, risk) "
        "VALUES ('1', '21/1', 21, 'Alt', 'https://example.org/1.pdf', 'hoch')"
    )
    db.init_db(c)
    db.init_db(c)  # idempotent
    bill = db.get_bill(c, "1")
    assert bill["risk"] == "hoch"
    assert bill["analysis_documents"] == []
    c.close()


def test_cascade_delete_findings(conn):
    db.upsert_bill(conn, _bill("100"))
    db.replace_findings(conn, "100", [
        {"severity": "hoch", "category": "referenz", "title": "t", "description": "d", "quote": None}
    ])
    conn.execute("DELETE FROM bills WHERE id = ?", ("100",))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0


def test_list_bills_filters_and_finding_count(conn):
    db.upsert_bill(conn, _bill("1", status="Überwiesen"))
    db.upsert_bill(conn, _bill("2", status="Verabschiedet"))
    db.upsert_bill(conn, _bill("3", status="Überwiesen"))
    db.mark_analyzed(conn, "1", "hoch", "s", "v1-systematisch", "m", [])
    db.mark_analyzed(conn, "2", "niedrig", "s", "v1-systematisch", "m", [])
    db.replace_findings(conn, "1", [
        {"severity": "hoch", "category": "referenz", "title": "t", "description": "d", "quote": None},
        {"severity": "mittel", "category": "datum", "title": "t", "description": "d", "quote": None},
    ])

    rows, total = db.list_bills(conn, risk="hoch")
    assert total == 1
    assert rows[0]["id"] == "1"
    assert rows[0]["finding_count"] == 2

    rows, total = db.list_bills(conn, status="Überwiesen")
    assert total == 2

    rows, total = db.list_bills(conn, risk="hoch", status="Überwiesen")
    assert total == 1

    rows, total = db.list_bills(conn, status="Verabschiedet")
    assert total == 1
    assert rows[0]["finding_count"] == 0


def test_list_bills_search_by_title(conn):
    db.upsert_bill(conn, _bill("1", titel="Gesetz zur Änderung des Glücksspielstaatsvertrags"))
    db.upsert_bill(conn, _bill("2", titel="Haushaltsgesetz 2026"))
    db.upsert_bill(conn, _bill("3", titel="Gesetz über das Glücksspielwesen"))

    rows, total = db.list_bills(conn, q="Glücksspiel")
    assert total == 2
    assert {r["id"] for r in rows} == {"1", "3"}

    # substring match anywhere in the title, ASCII case-insensitive
    rows, total = db.list_bills(conn, q="haushaltsGESETZ")
    assert total == 1
    assert rows[0]["id"] == "2"

    rows, total = db.list_bills(conn, q="Kein Treffer")
    assert total == 0


def test_list_bills_search_escapes_like_wildcards(conn):
    db.upsert_bill(conn, _bill("1", titel="Gesetz zu 100% erneuerbarer Energie"))
    db.upsert_bill(conn, _bill("2", titel="Gesetz zu 100 Punkten"))

    rows, total = db.list_bills(conn, q="100%")
    assert total == 1
    assert rows[0]["id"] == "1"

    # bare wildcard must not match everything
    rows, total = db.list_bills(conn, q="_")
    assert total == 0


def test_list_bills_search_combines_with_filters(conn):
    db.upsert_bill(conn, _bill("1", titel="Steuergesetz", status="Überwiesen"))
    db.upsert_bill(conn, _bill("2", titel="Steuergesetz II", status="Verabschiedet"))
    db.mark_analyzed(conn, "1", "hoch", "s", "v", "m", [])

    rows, total = db.list_bills(conn, q="Steuer", status="Überwiesen")
    assert total == 1
    assert rows[0]["id"] == "1"

    rows, total = db.list_bills(conn, q="Steuer", risk="hoch")
    assert total == 1

    rows, total = db.list_bills(conn, q="Steuer", risk="niedrig")
    assert total == 0


def test_list_bills_pagination(conn):
    for i in range(25):
        # zero-pad aktualisiert so ordering is deterministic
        db.upsert_bill(conn, _bill(f"{i:02d}", aktualisiert=f"2026-01-{(i % 28) + 1:02d}T00:00:00"))

    rows, total = db.list_bills(conn, page=1, page_size=10)
    assert total == 25
    assert len(rows) == 10

    rows, total = db.list_bills(conn, page=3, page_size=10)
    assert total == 25
    assert len(rows) == 5


def test_counts(conn):
    db.upsert_bill(conn, _bill("1"))
    db.upsert_bill(conn, _bill("2"))
    db.upsert_bill(conn, _bill("3"))
    db.upsert_bill(conn, _bill("4"))
    db.mark_analyzed(conn, "1", "hoch", "s", "v", "m", [])
    db.mark_analyzed(conn, "2", "mittel", "s", "v", "m", [])
    db.mark_analyzed(conn, "3", "niedrig", "s", "v", "m", [])
    c = db.counts(conn)
    assert c == {"hoch": 1, "mittel": 1, "niedrig": 1, "unanalysiert": 1, "total": 4}


def test_distinct_statuses(conn):
    db.upsert_bill(conn, _bill("1", status="Überwiesen"))
    db.upsert_bill(conn, _bill("2", status="Verabschiedet"))
    db.upsert_bill(conn, _bill("3", status="Überwiesen"))
    db.upsert_bill(conn, _bill("4", status=None))
    assert db.distinct_statuses(conn) == ["Verabschiedet", "Überwiesen"]


def test_list_bills_severity_counts(conn):
    """Constitutional findings stay out of the severity chips but are counted."""
    db.upsert_bill(conn, _bill("1"))
    db.upsert_bill(conn, _bill("2"))
    db.mark_analyzed(conn, "1", "mittel", "s", "v1", "m", [])
    db.mark_analyzed(conn, "2", "niedrig", "s", "v1", "m", [])
    db.replace_findings(conn, "1", [
        {"severity": "mittel", "category": "referenz", "title": "t", "description": "d", "quote": None},
        {"severity": "mittel", "category": "widerspruch", "title": "t", "description": "d", "quote": None},
        {"severity": "niedrig", "category": "datum", "title": "t", "description": "d", "quote": None},
        # Both non-risk-bearing categories, one of them 'hoch': it must not
        # appear in findings_hoch, or the chips would contradict risk='mittel'.
        {"severity": "hoch", "category": "verfassungsrisiko", "title": "t", "description": "d", "quote": None},
        {"severity": "niedrig", "category": "kompetenz", "title": "t", "description": "d", "quote": None},
    ])

    by_id = {r["id"]: r for r in db.list_bills(conn)[0]}

    one = by_id["1"]
    assert one["findings_hoch"] == 0
    assert one["findings_mittel"] == 2
    assert one["findings_niedrig"] == 1
    assert one["findings_verfassung"] == 2
    # finding_count keeps its old meaning: every finding, constitutional included.
    assert one["finding_count"] == 5
    # The breakdown partitions the findings exactly.
    assert (
        one["findings_hoch"] + one["findings_mittel"] + one["findings_niedrig"]
        + one["findings_verfassung"] == one["finding_count"]
    )

    # A bill with no findings reports zeros, not NULLs (LEFT JOIN).
    two = by_id["2"]
    assert two["finding_count"] == 0
    assert two["findings_hoch"] == 0
    assert two["findings_mittel"] == 0
    assert two["findings_niedrig"] == 0
    assert two["findings_verfassung"] == 0


def test_non_risk_bearing_categories_match_schema():
    """db.py duplicates the category split; this is what keeps it honest.

    ``db.py`` cannot import ``backend.analysis.schema`` without inverting the
    core/detail dependency (ARCHITECTURE D5), so the two definitions must be
    asserted equal instead.
    """
    from typing import get_args

    from backend.analysis.schema import RISK_BEARING_CATEGORIES, Category

    all_categories = set(get_args(Category))
    assert set(db._NON_RISK_BEARING_CATEGORIES) == all_categories - RISK_BEARING_CATEGORIES
    assert set(db._NON_RISK_BEARING_CATEGORIES).isdisjoint(RISK_BEARING_CATEGORIES)


def _related(doc_id: str, **overrides) -> dict:
    base = {
        "document_id": doc_id,
        "typ": "beschlussempfehlung",
        "dokumentnummer": f"21/{doc_id}",
        "titel": f"Beschlussempfehlung {doc_id}",
        "datum": "2026-03-01",
        "aktualisiert": "2026-03-02T10:00:00",
        "pdf_url": f"https://example.org/{doc_id}.pdf",
        "pdf_hash": None,
    }
    base.update(overrides)
    return base


def test_bill_documents_round_trip_ordered_chronologically(conn):
    db.upsert_bill(conn, _bill("100"))
    later = _related("9000", datum="2026-05-01")
    earlier = _related("10000", datum="2026-04-01")
    db.replace_bill_documents(conn, "100", "beschlussempfehlung", [later, earlier])
    assert db.get_bill_documents(conn, "100") == [earlier, later]
    assert db.get_bill(conn, "100")["related_documents"] == [earlier, later]


def test_related_documents_empty_by_default(conn):
    db.upsert_bill(conn, _bill("100"))
    assert db.get_bill(conn, "100")["related_documents"] == []


def test_replace_bill_documents_replaces_only_its_typ(conn):
    db.upsert_bill(conn, _bill("100"))
    other = _related("800", typ="stellungnahme")
    db.replace_bill_documents(conn, "100", "stellungnahme", [other])
    db.replace_bill_documents(conn, "100", "beschlussempfehlung", [_related("900")])
    db.replace_bill_documents(conn, "100", "beschlussempfehlung", [])
    assert db.get_bill_documents(conn, "100") == [other]


def test_bill_documents_shared_across_bills_and_kept_by_upsert(conn):
    db.upsert_bill(conn, _bill("100"))
    db.upsert_bill(conn, _bill("200"))
    shared = _related("900")
    db.replace_bill_documents(conn, "100", "beschlussempfehlung", [shared])
    db.replace_bill_documents(conn, "200", "beschlussempfehlung", [shared])
    db.upsert_bill(conn, _bill("100", pdf_hash="changed"))
    assert db.get_bill_documents(conn, "100") == [shared]
    assert db.get_bill_documents(conn, "200") == [shared]
