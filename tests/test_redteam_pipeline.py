"""Unit tests for the adversarial pass over the stored bills.

Fully offline: the PDF text and the Claude call are patched, so no network
call and no Claude credentials are ever needed.
"""

import json

import pytest

from backend import config, db, pipeline, redteam_pipeline
from backend.analysis.schema import Exploit, RedTeamAnalysis


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
def pdf(monkeypatch):
    """Serve every draft from memory; tests override as needed."""
    monkeypatch.setattr(
        redteam_pipeline.pdf_text, "get_text", lambda url, cache_key=None: "Ein Gesetzestext."
    )


def _bill(bill_id: str, **overrides) -> dict:
    base = {
        "id": bill_id,
        "dokumentnummer": f"21/{bill_id}",
        "wahlperiode": 21,
        "titel": f"Entwurf {bill_id}",
        "datum": "2026-01-01",
        # Later ids are newer, so the pass walks them in descending id order.
        "aktualisiert": f"2026-01-{int(bill_id):02d}T10:00:00",
        "pdf_url": f"https://example.org/{bill_id}.pdf",
        "pdf_hash": "abc",
    }
    base.update(overrides)
    return base


def _exploit(severity: str = "hoch", muster: str = "schwellenwert") -> Exploit:
    return Exploit(
        muster=muster,
        akteur="Ein Konzern, der die Steuer vermeiden will.",
        titel="Titel",
        schritte=["Schritt eins.", "Schritt zwei."],
        vorteil="Die Steuer entfällt.",
        aufwand="mittel",
        quote="Zitat",
        fehlende_absicherung="Eine Zurechnung fehlt.",
        severity=severity,
    )


def _result(*exploits: Exploit, summary: str = "Zusammenfassung.") -> RedTeamAnalysis:
    return RedTeamAnalysis(summary=summary, exploits=list(exploits))


def _patch_redteam(monkeypatch, result=None, fail_on=()):
    """Stand in for the Claude call; returns the list of red-teamed dokumentnummern."""
    calls = []

    def _redteam_bill(titel, dokumentnummer, text, trace=None, trace_fields=None):
        calls.append(dokumentnummer)
        if dokumentnummer in fail_on:
            raise RuntimeError(f"boom {dokumentnummer}")
        return result if result is not None else _result(_exploit())

    monkeypatch.setattr(redteam_pipeline.redteam, "redteam_bill", _redteam_bill)
    return calls


def _error_records(directory):
    return [
        json.loads(line)
        for path in directory.glob("*/errors.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


# --------------------------------------------------------------------------- #
# needs_redteam decision logic (pure function)
# --------------------------------------------------------------------------- #
def _stored(**overrides) -> dict:
    """A stored row whose pass read the bill's current Gesetzentwurf."""
    row = _bill("1")
    row.update(
        redteamed_at="2026-02-01 10:00:00",
        redteam_prompt_version=config.REDTEAM_PROMPT_VERSION,
        redteam_documents=[pipeline.entwurf_document(row)],
    )
    row.update(overrides)
    return row


def test_needs_redteam_never_run():
    row = _bill("1") | {"redteamed_at": None, "redteam_documents": []}
    assert redteam_pipeline.needs_redteam(row, force=False) is True


def test_needs_redteam_current_pass_is_false():
    assert redteam_pipeline.needs_redteam(_stored(), force=False) is False


def test_needs_redteam_force_overrides_current():
    assert redteam_pipeline.needs_redteam(_stored(), force=True) is True


def test_needs_redteam_changed_pdf_hash():
    assert redteam_pipeline.needs_redteam(_stored(pdf_hash="changed"), force=False) is True


def test_needs_redteam_aktualisiert_alone_does_not_count_when_hashed():
    row = _stored(aktualisiert="2026-09-01T10:00:00")
    assert redteam_pipeline.needs_redteam(row, force=False) is False


def test_needs_redteam_without_hash_keys_on_aktualisiert():
    unhashed = _bill("1", pdf_hash=None)
    row = _stored(pdf_hash=None, redteam_documents=[pipeline.entwurf_document(unhashed)])
    assert redteam_pipeline.needs_redteam(row, force=False) is False
    row["aktualisiert"] = "2026-09-01T10:00:00"
    assert redteam_pipeline.needs_redteam(row, force=False) is True


def test_needs_redteam_changed_prompt_version():
    row = _stored(redteam_prompt_version="v0")
    assert redteam_pipeline.needs_redteam(row, force=False) is True


def test_needs_redteam_ignores_the_lektor_analysis():
    row = _stored(risk=None, prompt_version="v0", analysis_documents=[])
    assert redteam_pipeline.needs_redteam(row, force=False) is False


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def test_run_persists_exploits_and_the_pass(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch, _result(_exploit("hoch"), _exploit("niedrig", "zeitfenster")))

    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1"]
    bill = db.get_bill(conn, "1")
    assert [e["muster"] for e in bill["exploits"]] == ["schwellenwert", "zeitfenster"]
    assert bill["exploits"][0]["schritte"] == ["Schritt eins.", "Schritt zwei."]
    assert bill["redteam_summary"] == "Zusammenfassung."
    assert bill["redteam_prompt_version"] == config.REDTEAM_PROMPT_VERSION
    assert bill["redteam_model"] == config.REDTEAM_MODEL
    assert bill["redteamed_at"] is not None
    assert bill["redteam_documents"] == [
        pipeline.entwurf_document(_bill("1")) | {"text_chars": len("Ein Gesetzestext.")}
    ]


def test_run_leaves_findings_and_risk_alone(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    finding = {"severity": "mittel", "category": "referenz", "title": "t", "description": "d",
               "quote": None, "location": None}
    db.replace_findings(conn, "1", [finding])
    db.mark_analyzed(conn, "1", "mittel", "Lektor", "v7", "m", [])
    _patch_redteam(monkeypatch, _result(_exploit("hoch")))

    assert redteam_pipeline.run(conn) == 0
    bill = db.get_bill(conn, "1")
    assert bill["risk"] == "mittel" and bill["summary"] == "Lektor"
    assert [{k: v for k, v in f.items() if k != "id"} for f in bill["findings"]] == [finding]
    assert len(bill["exploits"]) == 1


def test_run_runs_on_bills_the_lektor_has_not_analyzed(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    bill = db.get_bill(conn, "1")
    assert bill["risk"] is None and len(bill["exploits"]) == 1


def test_run_without_exploits_still_records_the_pass(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch, _result(summary="Nichts gefunden."))

    assert redteam_pipeline.run(conn) == 0
    bill = db.get_bill(conn, "1")
    assert bill["exploits"] == [] and bill["redteamed_at"] is not None
    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1"]


def test_run_second_run_skips(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1"]


def test_run_force_reruns_and_replaces(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    _patch_redteam(monkeypatch, _result(_exploit(), _exploit()))
    assert redteam_pipeline.run(conn) == 0
    calls = _patch_redteam(monkeypatch, _result(_exploit()))
    assert redteam_pipeline.run(conn, force=True) == 0
    assert calls == ["21/1"]
    assert len(db.get_bill(conn, "1")["exploits"]) == 1


def test_run_reruns_after_a_prompt_version_change(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    monkeypatch.setattr(config, "REDTEAM_PROMPT_VERSION", "v-next")
    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1", "21/1"]
    assert db.get_bill(conn, "1")["redteam_prompt_version"] == "v-next"


def test_run_reruns_after_the_entwurf_changed(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    db.upsert_bill(conn, _bill("1", pdf_hash="republished"))
    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1", "21/1"]
    assert db.get_bill(conn, "1")["redteam_documents"][0]["pdf_hash"] == "republished"


def test_run_limit_caps_the_due_bills_newest_first(conn, monkeypatch):
    for bill_id in ("1", "2", "3", "4"):
        db.upsert_bill(conn, _bill(bill_id))
    calls = _patch_redteam(monkeypatch)

    assert redteam_pipeline.run(conn, limit=2, concurrency=1) == 0
    assert sorted(calls) == ["21/3", "21/4"]
    # Current bills do not use up the limit: the next run reaches the older two.
    assert redteam_pipeline.run(conn, limit=2, concurrency=1) == 0
    assert sorted(calls[2:]) == ["21/1", "21/2"]
    assert redteam_pipeline.run(conn, limit=2) == 0
    assert len(calls) == 4


def test_run_limit_zero_calls_nothing(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    calls = _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn, limit=0) == 0
    assert calls == []


def test_run_failure_is_isolated_logged_and_keeps_the_stored_pass(conn, monkeypatch, runs_dir):
    db.upsert_bill(conn, _bill("1"))
    db.upsert_bill(conn, _bill("2"))
    _patch_redteam(monkeypatch, _result(_exploit(), _exploit()))
    assert redteam_pipeline.run(conn) == 0
    before = db.get_bill(conn, "1")

    calls = _patch_redteam(monkeypatch, fail_on={"21/1"})
    assert redteam_pipeline.run(conn, force=True, max_attempts=2) == 0
    assert calls.count("21/1") == 2 and calls.count("21/2") == 1
    assert db.get_bill(conn, "1") == before
    assert len(db.get_bill(conn, "2")["exploits"]) == 1

    records = _error_records(runs_dir)
    assert [r["attempt"] for r in records] == [1, 2]
    assert {r["phase"] for r in records} == {"redteam"}
    assert {r["dokumentnummer"] for r in records} == {"21/1"}
    assert records[-1]["final"] is True


def test_run_failed_bill_is_retried_next_run(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    _patch_redteam(monkeypatch, fail_on={"21/1"})
    assert redteam_pipeline.run(conn) == 1
    assert db.get_bill(conn, "1")["redteamed_at"] is None

    calls = _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    assert calls == ["21/1"]


def test_run_exit_0_when_nothing_is_due(conn, monkeypatch):
    _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0


def test_run_skips_an_oversize_entwurf(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1"))
    monkeypatch.setattr(redteam_pipeline.analyzer, "MAX_INPUT_CHARS", 5)
    calls = _patch_redteam(monkeypatch)

    assert redteam_pipeline.run(conn) == 0
    assert calls == []
    bill = db.get_bill(conn, "1")
    assert bill["redteamed_at"] is None and bill["redteam_documents"] == []


def test_run_reads_the_pdf_by_the_bills_hash(conn, monkeypatch):
    db.upsert_bill(conn, _bill("1", pdf_hash="h1"))
    seen = []

    def _get_text(url, cache_key=None):
        seen.append((url, cache_key))
        return "Text."

    monkeypatch.setattr(redteam_pipeline.pdf_text, "get_text", _get_text)
    _patch_redteam(monkeypatch)
    assert redteam_pipeline.run(conn) == 0
    assert seen == [("https://example.org/1.pdf", "h1")]


def test_run_traces_the_call_into_its_own_run_folder(conn, monkeypatch, runs_dir):
    from types import SimpleNamespace

    from backend import tracelog
    from backend.analysis import structured

    async def _run_query(user_message, on_message=None, **_):
        on_message(SimpleNamespace(content=[SimpleNamespace(text="call")]))
        return structured.StructuredRun(_result(_exploit()), None, [], None, None)

    db.upsert_bill(conn, _bill("1"))
    monkeypatch.setattr(redteam_pipeline.redteam, "run_query", _run_query)

    assert redteam_pipeline.run(conn) == 0
    trace = db.get_bill(conn, "1")["redteam_trace"]
    folder, rest = trace.split("/", 1)
    assert folder.endswith("-redteam") and rest == "traces/21-1.jsonl"
    header, messages, footer = tracelog.read(runs_dir / trace)
    assert header["pass"] == "angreifer"
    assert header["doc"] == "21/1" and header["attempt"] == 1
    assert header["prompt_version"] == config.REDTEAM_PROMPT_VERSION
    assert header["inputs"] == [
        {"typ": "gesetzentwurf", "dokumentnummer": "21/1", "document_id": "1",
         "pdf_hash": "abc", "text_chars": len("Ein Gesetzestext.")}
    ]
    assert "Ein Gesetzestext." not in (runs_dir / trace).read_text(encoding="utf-8")
    assert len(messages) == 1 and footer["ok"] is True
