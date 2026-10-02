"""Unit tests for the pipeline composition root (Story S5).

Fully offline: the DIP client, PDF functions and the Claude analyzer are all
patched, so no network call and no Claude credentials are ever needed.
"""

import pytest

from backend import config, db, pipeline
from backend.analysis.schema import BillAnalysis, Finding


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def runs_dir(tmp_path, monkeypatch):
    """Redirect the per-run folders (error log, traces) away from ./data for every test."""
    directory = tmp_path / "runs"
    monkeypatch.setattr(config, "PIPELINE_RUNS_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def no_beschlussempfehlungen(monkeypatch):
    """Keep the Beschlussempfehlung sweep offline; tests override as needed."""
    monkeypatch.setattr(pipeline.dip_client, "fetch_beschlussempfehlungen", lambda: [])


def _error_records(directory):
    """All JSONL records across a test's run error logs, oldest first."""
    import json

    records = []
    if directory.exists():
        for path in sorted(directory.glob("*/errors.jsonl")):
            with path.open(encoding="utf-8") as f:
                records.extend(json.loads(line) for line in f)
    return records


def _doc(doc_id: str, **overrides) -> dict:
    """A minimal DIP document as document_to_bill expects it."""
    base = {
        "id": doc_id,
        "dokumentnummer": f"21/{doc_id}",
        "wahlperiode": 21,
        "titel": f"Entwurf eines Gesetzes {doc_id}",
        "urheber": [{"bezeichnung": "Bundesregierung"}],
        "datum": "2026-01-01",
        "aktualisiert": "2026-01-02T10:00:00",
        "pdf_hash": f"hash-{doc_id}",
        "fundstelle": {"pdf_url": f"https://example.org/{doc_id}.pdf"},
        "vorgangsbezug": [{"id": f"v{doc_id}"}],
    }
    base.update(overrides)
    return base


def _fresh(**overrides) -> dict:
    """A freshly mapped bill dict (as produced by document_to_bill)."""
    base = {
        "id": "1",
        "dokumentnummer": "21/1",
        "aktualisiert": "2026-01-02T10:00:00",
        "pdf_hash": "hash-1",
    }
    base.update(overrides)
    return base


def _inputs(*related: dict, **overrides) -> list[dict]:
    """The input set for ``_fresh(**overrides)`` plus related catalog rows."""
    return pipeline._input_documents(_fresh(**overrides), list(related))


def _be_row(doc_id: str = "900", **overrides) -> dict:
    """A ``bill_documents`` row for a Beschlussempfehlung."""
    base = {
        "document_id": doc_id,
        "typ": "beschlussempfehlung",
        "dokumentnummer": f"21/{doc_id}",
        "titel": f"Beschlussempfehlung {doc_id}",
        "datum": "2026-03-01",
        "aktualisiert": "2026-03-02T10:00:00",
        "pdf_url": f"https://example.org/{doc_id}.pdf",
        "pdf_hash": f"hash-{doc_id}",
    }
    base.update(overrides)
    return base


def _analysis(*findings: Finding, summary: str = "Zusammenfassung.") -> BillAnalysis:
    return BillAnalysis(summary=summary, findings=list(findings))


def _finding(severity: str = "mittel", category: str = "referenz") -> Finding:
    return Finding(
        severity=severity,
        category=category,
        title="Titel",
        description="Beschreibung.",
        quote="Zitat",
    )


def _patch_dip(monkeypatch, documents):
    monkeypatch.setattr(
        pipeline.dip_client, "fetch_gesetzentwuerfe", lambda limit=None: documents
    )
    monkeypatch.setattr(
        pipeline.dip_client, "fetch_beratungsstand", lambda vorgang_id: "Überwiesen"
    )


def _patch_pdf(monkeypatch, text="Ein Gesetzestext."):
    monkeypatch.setattr(
        pipeline.pdf_text, "get_text", lambda url, cache_key=None: text
    )


# --------------------------------------------------------------------------- #
# needs_analysis decision logic (pure function)
# --------------------------------------------------------------------------- #
def _stored(**overrides) -> dict:
    """A stored, analyzed row whose analysis read the bill as ``_fresh()`` maps it."""
    base = {
        "risk": "mittel",
        "prompt_version": config.PROMPT_VERSION,
        "analysis_documents": [pipeline._entwurf_document(_fresh())],
    }
    base.update(overrides)
    return base


def test_needs_analysis_fresh_bill_unknown():
    assert pipeline.needs_analysis(None, _inputs(), force=False) is True


def test_needs_analysis_risk_null():
    existing = _stored(risk=None)
    assert pipeline.needs_analysis(existing, _inputs(), force=False) is True


def test_needs_analysis_unchanged_analyzed_bill_is_false():
    assert pipeline.needs_analysis(_stored(), _inputs(), force=False) is False


def test_needs_analysis_aktualisiert_alone_does_not_count_when_hashed():
    # DIP bumps aktualisiert on metadata-only edits; the pdf_hash identifies the text.
    inputs = _inputs(aktualisiert="2026-03-01T00:00:00")
    assert pipeline.needs_analysis(_stored(), inputs, force=False) is False


def test_needs_analysis_changed_aktualisiert_without_hash():
    existing = _stored(
        analysis_documents=[pipeline._entwurf_document(_fresh(pdf_hash=None))]
    )
    inputs = _inputs(pdf_hash=None, aktualisiert="2026-03-01T00:00:00")
    assert pipeline.needs_analysis(existing, inputs, force=False) is True


def test_needs_analysis_changed_pdf_hash():
    inputs = _inputs(pdf_hash="new-hash")
    assert pipeline.needs_analysis(_stored(), inputs, force=False) is True
    assert (
        pipeline._decision_reason(_stored(), inputs, force=False)
        == "geändert: Entwurf 21/1"
    )


def test_needs_analysis_changed_prompt_version():
    existing = _stored(prompt_version="v0-alt")
    assert pipeline.needs_analysis(existing, _inputs(), force=False) is True


def test_needs_analysis_force_overrides_unchanged():
    assert pipeline.needs_analysis(_stored(), _inputs(), force=True) is True


def test_needs_analysis_no_documents_recorded():
    existing = _stored(analysis_documents=[])
    assert pipeline.needs_analysis(existing, _inputs(), force=False) is True
    assert (
        pipeline._decision_reason(existing, _inputs(), force=False)
        == "Dokumente nicht erfasst"
    )


def test_needs_analysis_ignores_bill_metadata_columns():
    # The row's own aktualisiert/pdf_hash are overwritten by every upsert, so
    # only the documents the analysis read count.
    existing = _stored(aktualisiert="2026-03-01T00:00:00", pdf_hash="new-hash")
    inputs = _inputs(aktualisiert="2026-03-01T00:00:00", pdf_hash="new-hash")
    assert pipeline.needs_analysis(existing, inputs, force=False) is True


def test_needs_analysis_new_beschlussempfehlung():
    inputs = _inputs(_be_row("900"))
    assert pipeline.needs_analysis(_stored(), inputs, force=False) is True
    assert (
        pipeline._decision_reason(_stored(), inputs, force=False)
        == "neu: Beschlussempfehlung 21/900"
    )


def test_needs_analysis_unchanged_with_beschlussempfehlung():
    existing = _stored(analysis_documents=_inputs(_be_row("900")))
    assert pipeline.needs_analysis(existing, _inputs(_be_row("900")), force=False) is False


def test_needs_analysis_changed_beschlussempfehlung_hash():
    existing = _stored(analysis_documents=_inputs(_be_row("900")))
    inputs = _inputs(_be_row("900", pdf_hash="hash-neu"))
    assert (
        pipeline._decision_reason(existing, inputs, force=False)
        == "geändert: Beschlussempfehlung 21/900"
    )


def test_needs_analysis_beschlussempfehlung_without_hash_keys_on_aktualisiert():
    existing = _stored(analysis_documents=_inputs(_be_row("900", pdf_hash=None)))
    same = _inputs(_be_row("900", pdf_hash=None))
    bumped = _inputs(_be_row("900", pdf_hash=None, aktualisiert="2026-04-01T00:00:00"))
    assert pipeline.needs_analysis(existing, same, force=False) is False
    assert pipeline.needs_analysis(existing, bumped, force=False) is True


def test_needs_analysis_vanished_beschlussempfehlung():
    existing = _stored(analysis_documents=_inputs(_be_row("900")))
    assert (
        pipeline._decision_reason(existing, _inputs(), force=False)
        == "entfallen: Beschlussempfehlung 21/900"
    )


# --------------------------------------------------------------------------- #
# End-to-end run with fully mocked deps
# --------------------------------------------------------------------------- #
def test_run_end_to_end_persists_bill_findings_risk_status(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch, text="Text mit 20 Zeichen!!")
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(_finding("hoch")),
    )

    code = pipeline.run(conn, limit=None, force=False, skip_analysis=False)
    assert code == 0

    bill = db.get_bill(conn, "1")
    assert bill is not None
    assert bill["status"] == "Überwiesen"
    assert bill["risk"] == "hoch"
    assert bill["summary"] == "Zusammenfassung."
    assert bill["prompt_version"] == config.PROMPT_VERSION
    assert bill["model"] == config.ANALYSIS_MODEL
    assert bill["text_chars"] == len("Text mit 20 Zeichen!!")
    assert len(bill["findings"]) == 1
    assert bill["findings"][0]["severity"] == "hoch"
    assert bill["analysis_documents"] == [
        {
            "document_id": "1",
            "typ": "gesetzentwurf",
            "dokumentnummer": "21/1",
            "datum": "2026-01-01",
            "pdf_url": "https://example.org/1.pdf",
            "pdf_hash": "hash-1",
            "aktualisiert": "2026-01-02T10:00:00",
            "text_chars": len("Text mit 20 Zeichen!!"),
        }
    ]


def test_run_derive_risk_hoch_beats_mittel(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(
            _finding("mittel"), _finding("hoch"), _finding("niedrig")
        ),
    )

    pipeline.run(conn)
    assert db.get_bill(conn, "1")["risk"] == "hoch"


def test_run_idempotent_second_run_skips(conn, monkeypatch):
    calls = {"n": 0}

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls["n"] += 1
        return _analysis(_finding("mittel"))

    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    pipeline.run(conn)  # first run analyzes
    pipeline.run(conn)  # second run: unchanged -> skip
    assert calls["n"] == 1


def test_run_force_reanalyzes(conn, monkeypatch):
    calls = {"n": 0}

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls["n"] += 1
        return _analysis(_finding("mittel"))

    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    pipeline.run(conn)
    pipeline.run(conn, force=True)
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# Per-bill error isolation
# --------------------------------------------------------------------------- #
def test_run_error_isolation_one_bad_bill_does_not_stop_others(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1"), _doc("2"), _doc("3")])
    _patch_pdf(monkeypatch)

    def _analyze(titel, dnr, text, context_docs=None, **_):
        if dnr == "21/2":
            raise RuntimeError("boom")
        return _analysis(_finding("mittel"))

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    code = pipeline.run(conn)
    # Not everything failed -> exit 0.
    assert code == 0
    # The two good bills are analyzed; the bad one has no risk.
    assert db.get_bill(conn, "1")["risk"] == "mittel"
    assert db.get_bill(conn, "3")["risk"] == "mittel"
    assert db.get_bill(conn, "2")["risk"] is None
    # But bill 2's metadata still landed (upsert happened before analysis).
    assert db.get_bill(conn, "2") is not None
    assert db.get_bill(conn, "2")["status"] == "Überwiesen"
    assert db.get_bill(conn, "2")["analysis_documents"] == []


def test_run_failed_reanalysis_is_retried_next_run(conn, monkeypatch):
    _patch_pdf(monkeypatch)
    _patch_dip(monkeypatch, [_doc("1")])
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(_finding("mittel")),
    )
    pipeline.run(conn)
    before = db.get_bill(conn, "1")["analysis_documents"]

    def _boom(titel, dnr, text, context_docs=None, **_):
        raise RuntimeError("boom")

    _patch_dip(monkeypatch, [_doc("1", pdf_hash="hash-neu")])
    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _boom)
    pipeline.run(conn)

    bill = db.get_bill(conn, "1")
    assert bill["pdf_hash"] == "hash-neu"
    assert bill["analysis_documents"] == before
    assert bill["analysis_documents"][0]["pdf_hash"] == "hash-1"

    # The next run sees the analysis read an older PDF and retries.
    calls = {"n": 0}

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls["n"] += 1
        return _analysis(_finding("hoch"))

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)
    pipeline.run(conn)

    assert calls["n"] == 1
    bill = db.get_bill(conn, "1")
    assert bill["risk"] == "hoch"
    assert bill["analysis_documents"][0]["pdf_hash"] == "hash-neu"


def test_run_exit_1_when_all_attempts_fail(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1"), _doc("2")])
    _patch_pdf(monkeypatch)

    def _analyze(titel, dnr, text, context_docs=None, **_):
        raise RuntimeError("always boom")

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    code = pipeline.run(conn)
    assert code == 1


def test_run_no_attempts_exits_0(conn, monkeypatch):
    # Skip-analysis makes zero attempts -> exit 0 even though nothing analyzed.
    _patch_dip(monkeypatch, [_doc("1")])
    code = pipeline.run(conn, skip_analysis=True)
    assert code == 0


# --------------------------------------------------------------------------- #
# --skip-analysis touches neither the PDF nor the analyzer
# --------------------------------------------------------------------------- #
def test_skip_analysis_does_not_analyze_or_touch_pdf(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])

    def _boom(*a, **k):
        raise AssertionError("must not be called under --skip-analysis")

    monkeypatch.setattr(pipeline.pdf_text, "get_text", _boom)
    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _boom)

    code = pipeline.run(conn, skip_analysis=True)
    assert code == 0

    bill = db.get_bill(conn, "1")
    assert bill is not None
    assert bill["status"] == "Überwiesen"  # metadata + status refreshed
    assert bill["risk"] is None  # but never analyzed


# --------------------------------------------------------------------------- #
# Concurrency: many bills through the worker pool, serial DB writes
# --------------------------------------------------------------------------- #
def test_run_concurrent_analyzes_all_bills(conn, monkeypatch):
    import threading

    docs = [_doc(str(i)) for i in range(1, 9)]
    _patch_dip(monkeypatch, docs)
    _patch_pdf(monkeypatch)

    active = {"now": 0, "peak": 0}
    lock = threading.Lock()
    gate = threading.Barrier(4, timeout=5)

    def _analyze(titel, dnr, text, context_docs=None, **_):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        gate.wait()  # forces ≥4 analyses to overlap before any finishes
        with lock:
            active["now"] -= 1
        return _analysis(_finding("mittel"))

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    code = pipeline.run(conn, concurrency=4)
    assert code == 0
    assert active["peak"] >= 4
    for i in range(1, 9):
        assert db.get_bill(conn, str(i))["risk"] == "mittel"


def test_run_concurrency_floor_is_one(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(_finding("niedrig")),
    )
    assert pipeline.run(conn, concurrency=0) == 0
    assert db.get_bill(conn, "1")["risk"] == "niedrig"


# --------------------------------------------------------------------------- #
# --limit is forwarded to the DIP client
# --------------------------------------------------------------------------- #
def test_run_forwards_limit_to_dip(conn, monkeypatch):
    seen = {}

    def _fetch(limit=None):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(pipeline.dip_client, "fetch_gesetzentwuerfe", _fetch)
    pipeline.run(conn, limit=5)
    assert seen["limit"] == 5


# --------------------------------------------------------------------------- #
# Retries and the per-run error log
# --------------------------------------------------------------------------- #
def test_run_retries_failed_bill_and_logs_the_attempt(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    calls = {"n": 0}

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient boom")
        return _analysis(_finding("mittel"))

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    code = pipeline.run(conn)  # default max_attempts = 2
    assert code == 0
    assert calls["n"] == 2
    assert db.get_bill(conn, "1")["risk"] == "mittel"

    records = _error_records(runs_dir)
    assert len(records) == 1
    record = records[0]
    assert record["dokumentnummer"] == "21/1"
    assert record["phase"] == "attempted"
    assert record["attempt"] == 1
    assert record["max_attempts"] == 2
    assert record["final"] is False
    assert record["error_type"] == "RuntimeError"
    assert "transient boom" in record["error"]
    assert "RuntimeError" in record["traceback"]


def _traced_run_query(fail_first: bool):
    """A ``run_query`` stand-in that streams one message through ``on_message``."""
    from types import SimpleNamespace

    from backend.analysis import structured

    calls = {"n": 0}

    async def _run_query(user_message, on_message=None, **_):
        calls["n"] += 1
        on_message(SimpleNamespace(content=[SimpleNamespace(text=f"call {calls['n']}")]))
        if fail_first and calls["n"] == 1:
            raise RuntimeError("transient boom")
        return structured.StructuredRun(_analysis(_finding("mittel")), None, [], None, None)

    return _run_query


def test_run_traces_the_call_and_links_it_from_the_bill(conn, monkeypatch, runs_dir):
    from backend import tracelog

    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(pipeline.analyzer, "run_query", _traced_run_query(False))

    assert pipeline.run(conn) == 0
    trace = db.get_bill(conn, "1")["analysis_trace"]
    assert trace.endswith("/traces/21-1.jsonl")
    header, messages, footer = tracelog.read(runs_dir / trace)
    assert header["doc"] == "21/1" and header["attempt"] == 1
    assert header["prompt_version"] == config.PROMPT_VERSION
    assert header["inputs"][0]["typ"] == "gesetzentwurf"
    assert "Ein Gesetzestext." not in (runs_dir / trace).read_text(encoding="utf-8")
    assert len(messages) == 1 and footer["ok"] is True


def test_run_keeps_the_failed_attempts_trace_beside_the_retry(conn, monkeypatch, runs_dir):
    from backend import tracelog

    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(pipeline.analyzer, "run_query", _traced_run_query(True))

    assert pipeline.run(conn) == 0
    (run_dir,) = runs_dir.iterdir()
    first = run_dir / "traces" / "21-1.jsonl"
    second = run_dir / "traces" / "21-1.attempt-2.jsonl"
    assert tracelog.read(first)[2]["ok"] is False
    assert tracelog.read(second)[2]["ok"] is True
    assert db.get_bill(conn, "1")["analysis_trace"] == f"{run_dir.name}/traces/21-1.attempt-2.jsonl"
    assert (run_dir / "errors.jsonl").exists()


def test_run_logs_every_attempt_up_to_final_threshold(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)

    def _analyze(titel, dnr, text, context_docs=None, **_):
        raise RuntimeError("always boom")

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    code = pipeline.run(conn)  # default max_attempts = 2
    assert code == 1
    # Metadata still persisted, analysis never succeeded.
    assert db.get_bill(conn, "1")["risk"] is None

    records = _error_records(runs_dir)
    assert [r["attempt"] for r in records] == [1, 2]
    assert [r["final"] for r in records] == [False, True]
    assert all(r["max_attempts"] == 2 for r in records)


def test_run_max_attempts_one_disables_retry(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    calls = {"n": 0}

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)

    pipeline.run(conn, max_attempts=1)
    assert calls["n"] == 1

    records = _error_records(runs_dir)
    assert len(records) == 1
    assert records[0]["final"] is True


def test_run_metadata_failure_is_retried_and_logged(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])

    def _boom_status(vorgang_id):
        raise RuntimeError("DIP down")

    monkeypatch.setattr(pipeline.dip_client, "fetch_beratungsstand", _boom_status)

    pipeline.run(conn)
    # Metadata-phase failures leave no row.
    assert db.get_bill(conn, "1") is None

    records = _error_records(runs_dir)
    assert len(records) == 2
    assert all(r["phase"] == "metadata" for r in records)
    assert "DIP down" in records[0]["error"]


def test_run_without_errors_writes_no_error_file(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(_finding("niedrig")),
    )

    assert pipeline.run(conn) == 0
    assert not runs_dir.exists()


# --------------------------------------------------------------------------- #
# Beschlussempfehlungen: catalogued in bill_documents and analysis inputs
# --------------------------------------------------------------------------- #
def _be_doc(doc_id: str, *vorgang_ids: str, **overrides) -> dict:
    """A minimal DIP Beschlussempfehlung covering the given Vorgänge."""
    base = {
        "id": doc_id,
        "dokumentnummer": f"21/{doc_id}",
        "titel": f"Beschlussempfehlung {doc_id}",
        "datum": "2026-03-01",
        "aktualisiert": "2026-03-02T10:00:00",
        "pdf_hash": f"hash-{doc_id}",
        "fundstelle": {"pdf_url": f"https://example.org/{doc_id}.pdf"},
        "vorgangsbezug": [{"id": v} for v in vorgang_ids],
    }
    base.update(overrides)
    return base


def _patch_be(monkeypatch, documents):
    monkeypatch.setattr(
        pipeline.dip_client, "fetch_beschlussempfehlungen", lambda: documents
    )


def _related_ids(conn, bill_id):
    return [d["document_id"] for d in db.get_bill_documents(conn, bill_id)]


def test_run_catalogues_beschlussempfehlungen_under_skip_analysis(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1"), _doc("2")])
    _patch_be(monkeypatch, [_be_doc("900", "v1", "v2"), _be_doc("901", "v1"), _be_doc("902", "vX")])

    assert pipeline.run(conn, skip_analysis=True) == 0

    assert _related_ids(conn, "1") == ["900", "901"]
    assert _related_ids(conn, "2") == ["900"]
    row = db.get_bill_documents(conn, "2")[0]
    assert row["typ"] == "beschlussempfehlung"
    assert row["pdf_url"] == "https://example.org/900.pdf"


def test_run_new_beschlussempfehlung_triggers_reanalysis_with_its_text(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    monkeypatch.setattr(
        pipeline.pdf_text, "get_text",
        lambda url, cache_key=None: {"https://example.org/900.pdf": "BE-Text."}.get(
            url, "Entwurfstext."
        ),
    )
    calls = []

    def _analyze(titel, dnr, text, context_docs=None, **_):
        calls.append((dnr, text, context_docs))
        return _analysis()

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _analyze)
    pipeline.run(conn)
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    pipeline.run(conn)
    pipeline.run(conn)

    assert calls == [
        ("21/1", "Entwurfstext.", []),
        ("21/1", "Entwurfstext.", [("21/900", "BE-Text.")]),
    ]
    documents = db.get_bill(conn, "1")["analysis_documents"]
    assert [(d["document_id"], d["typ"], d["text_chars"]) for d in documents] == [
        ("1", "gesetzentwurf", len("Entwurfstext.")),
        ("900", "beschlussempfehlung", len("BE-Text.")),
    ]


def test_run_beschlussempfehlungen_are_sent_in_date_order(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    _patch_be(monkeypatch, [
        _be_doc("902", "v1", datum="2026-05-01"),
        _be_doc("901", "v1", datum="2026-04-01"),
    ])
    seen = []
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: seen.append(
            [n for n, _ in context_docs]
        ) or _analysis(),
    )
    pipeline.run(conn)
    assert seen == [["21/901", "21/902"]]


def test_run_one_beschlussempfehlung_covering_two_bills(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1"), _doc("2")])
    _patch_pdf(monkeypatch)
    _patch_be(monkeypatch, [_be_doc("900", "v1", "v2")])
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: _analysis(),
    )
    pipeline.run(conn)
    for bill_id in ("1", "2"):
        ids = [d["document_id"] for d in db.get_bill(conn, bill_id)["analysis_documents"]]
        assert ids == [bill_id, "900"]


def test_run_vanished_beschlussempfehlung_reanalyzes(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    calls = []
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: calls.append(context_docs) or _analysis(),
    )
    pipeline.run(conn)
    _patch_be(monkeypatch, [])
    pipeline.run(conn)
    assert calls == [[("21/900", "Ein Gesetzestext.")], []]
    assert _related_ids(conn, "1") == []


def test_run_failed_sweep_uses_stored_catalog_and_does_not_reanalyze(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    calls = []
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: calls.append(dnr) or _analysis(),
    )
    pipeline.run(conn)

    def _boom():
        raise RuntimeError("DIP down")

    monkeypatch.setattr(pipeline.dip_client, "fetch_beschlussempfehlungen", _boom)
    pipeline.run(conn)
    assert calls == ["21/1"]

    # Forced, the stored catalog row is still an input.
    seen = []
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: seen.append(context_docs) or _analysis(),
    )
    pipeline.run(conn, force=True)
    assert seen == [[("21/900", "Ein Gesetzestext.")]]


# --------------------------------------------------------------------------- #
# Oversize inputs are skipped, never truncated
# --------------------------------------------------------------------------- #
def _patch_sizes(monkeypatch, sizes: dict[str, int]):
    monkeypatch.setattr(
        pipeline.pdf_text, "get_text", lambda url, cache_key=None: "x" * sizes[url]
    )


def _count_calls(monkeypatch) -> list:
    calls = []
    monkeypatch.setattr(
        pipeline.analyzer, "analyze_bill",
        lambda titel, dnr, text, context_docs=None, **_: calls.append(dnr) or _analysis(),
    )
    return calls


def test_run_oversize_entwurf_is_skipped(conn, monkeypatch):
    monkeypatch.setattr(pipeline.analyzer, "MAX_INPUT_CHARS", 100)
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_sizes(monkeypatch, {"https://example.org/1.pdf": 101})
    calls = _count_calls(monkeypatch)

    assert pipeline.run(conn) == 0
    assert calls == []
    bill = db.get_bill(conn, "1")
    assert bill["risk"] is None
    assert bill["analysis_documents"] == []


def test_run_oversize_sum_keeps_previous_analysis(conn, monkeypatch, runs_dir):
    monkeypatch.setattr(pipeline.analyzer, "MAX_INPUT_CHARS", 100)
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_sizes(monkeypatch, {
        "https://example.org/1.pdf": 60, "https://example.org/900.pdf": 41,
    })
    calls = _count_calls(monkeypatch)
    pipeline.run(conn)
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    pipeline.run(conn)

    assert calls == ["21/1"]
    documents = db.get_bill(conn, "1")["analysis_documents"]
    assert [d["document_id"] for d in documents] == ["1"]
    assert _related_ids(conn, "1") == ["900"]
    assert not runs_dir.exists()


def test_run_input_exactly_at_limit_is_analyzed(conn, monkeypatch):
    monkeypatch.setattr(pipeline.analyzer, "MAX_INPUT_CHARS", 100)
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    _patch_sizes(monkeypatch, {
        "https://example.org/1.pdf": 60, "https://example.org/900.pdf": 40,
    })
    calls = _count_calls(monkeypatch)
    pipeline.run(conn)
    assert calls == ["21/1"]


def test_run_vanished_beschlussempfehlung_is_removed(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    pipeline.run(conn, skip_analysis=True)
    _patch_be(monkeypatch, [])
    pipeline.run(conn, skip_analysis=True)
    assert _related_ids(conn, "1") == []


def test_run_failed_sweep_keeps_stored_documents(conn, monkeypatch, runs_dir):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_be(monkeypatch, [_be_doc("900", "v1")])
    pipeline.run(conn, skip_analysis=True)

    def _boom():
        raise RuntimeError("DIP down")

    monkeypatch.setattr(pipeline.dip_client, "fetch_beschlussempfehlungen", _boom)
    assert pipeline.run(conn, skip_analysis=True) == 0

    assert _related_ids(conn, "1") == ["900"]
    assert db.get_bill(conn, "1")["status"] == "Überwiesen"  # run continued
    records = _error_records(runs_dir)
    assert [r["phase"] for r in records] == ["beschlussempfehlungen"]


def test_run_failed_analysis_still_catalogues(conn, monkeypatch):
    _patch_dip(monkeypatch, [_doc("1")])
    _patch_pdf(monkeypatch)
    _patch_be(monkeypatch, [_be_doc("900", "v1")])

    def _boom(titel, dnr, text, context_docs=None, **_):
        raise RuntimeError("Claude down")

    monkeypatch.setattr(pipeline.analyzer, "analyze_bill", _boom)
    pipeline.run(conn, max_attempts=1)
    assert _related_ids(conn, "1") == ["900"]
