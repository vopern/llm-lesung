"""The eval harness: document selection, one sample, and scoring (offline, no Claude).

``run_query`` is replaced by a fake, so these pin what the harness sends and
records, not what a model answers.
"""

import hashlib
import json
from types import SimpleNamespace

from backend import config as backend_config
from backend.analysis import analyzer, redteam, structured
from backend.analysis.schema import BillAnalysis, RedTeamAnalysis
from eval import page
from eval.harness import config, html, report, run, tasks
from eval.testset import about, lint
from tests.test_testset_export_score import TEXT, _doc
from tests.test_testset_lint import _case


LEKTOR = tasks.get("lektor")
ANGREIFER = tasks.get("angreifer")


def _manifest(case):
    return {case["doc"]: {"titel": "Entwurf eines Gesetzes", "gesetzentwurf": case["text"]}}


def _document(case):
    return run.select([case], _manifest(case), "all", None)[0]


def _fake_query(monkeypatch, findings, sent):
    async def fake(message, model=None, on_message=None, effort=None, max_turns=1):
        sent.append((message, model))
        if on_message is not None:
            on_message(SimpleNamespace(content="stream"))
        result = SimpleNamespace(num_turns=1, session_id="s", total_cost_usd=0.5, usage={})
        return structured.StructuredRun(
            BillAnalysis(summary="Zusammenfassung", findings=findings), result, [], None, None)
    monkeypatch.setattr(analyzer, "run_query", fake)


def _finding(quote, category="vollstaendigkeit", severity="hoch"):
    return {"severity": severity, "category": category, "title": "t",
            "description": "d", "quote": quote}


def test_select_filters_split_and_documents_and_takes_manifest_inputs(tmp_path):
    dev = _case(tmp_path)
    test = _case(tmp_path, id="L-X", doc="21/9", split="test")
    manifest = _manifest(dev) | _manifest(test)
    assert [d["doc"] for d in run.select([dev, test], manifest, "all", None)] == ["21/537", "21/9"]
    assert [d["doc"] for d in run.select([dev, test], manifest, "test", None)] == ["21/9"]
    assert run.select([dev, test], manifest, "all", {"21/537"}) == [{
        "doc": "21/537", "split": "dev", "titel": "Entwurf eines Gesetzes",
        "file": "21-537.txt", "sha256": dev["text"]["sha256"]}]


def test_run_one_sends_the_pipeline_message_and_records_the_result(tmp_path, monkeypatch):
    document = _document(_doc(tmp_path))
    sent = []
    _fake_query(monkeypatch, [_finding("§ 10 Absatz 3 wird gestrichen.")], sent)
    trace = tmp_path / "traces" / "21-537.jsonl"

    record = run.run_one(LEKTOR, document, TEXT, "claude-x", "tag", trace)

    assert sent == [(analyzer.build_message("Entwurf eines Gesetzes", "21/537", TEXT), "claude-x")]
    assert record["status"] == "ok" and record["risk"] == "hoch"
    assert record["inputs"] == [{"typ": "gesetzentwurf", "doc": "21/537", "file": "21-537.txt",
                                 "sha256": document["sha256"], "chars": len(TEXT)}]
    assert record["analysis"]["findings"][0]["quote"] == "§ 10 Absatz 3 wird gestrichen."
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["model"] == "claude-x" and len(lines) == 3


def test_effort_reaches_the_query_and_the_record_and_names_the_run(tmp_path, monkeypatch):
    efforts = []

    async def fake(message, model=None, on_message=None, effort=None, max_turns=1):
        efforts.append(effort)
        result = SimpleNamespace(num_turns=1, session_id="s", total_cost_usd=0.1, usage={})
        return structured.StructuredRun(BillAnalysis(summary="s", findings=[]), result, [], None, None)
    monkeypatch.setattr(analyzer, "run_query", fake)

    record = run.run_one(LEKTOR, _document(_doc(tmp_path)), TEXT, "claude-x", "tag", effort="low")
    assert efforts == ["low"] and record["effort"] == "low"
    assert analyzer._options("claude-x", "low").effort == "low"
    assert analyzer._options("claude-x").effort == backend_config.ANALYSIS_EFFORT
    assert config.default_tag(LEKTOR, "claude-x") == f"{backend_config.PROMPT_VERSION}-claude-x"
    assert config.default_tag(LEKTOR, "claude-x", "low").endswith("-claude-x-effort-low")
    assert config.default_tag(LEKTOR, "claude-x", None, 1) == config.default_tag(LEKTOR, "claude-x")
    assert config.default_tag(LEKTOR, "claude-x", "low", 2).endswith(
        "-claude-x-effort-low-turns-2")
    assert config.default_tag(ANGREIFER, "claude-x", "high") == (
        f"{backend_config.REDTEAM_PROMPT_VERSION}-claude-x-effort-high")


def test_oversize_input_is_recorded_not_sent(tmp_path, monkeypatch):
    sent = []
    _fake_query(monkeypatch, [], sent)
    monkeypatch.setattr(analyzer, "MAX_INPUT_CHARS", len(TEXT) - 1)
    record = run.run_one(LEKTOR, _document(_doc(tmp_path)), TEXT, "claude-x", "tag")
    assert record["status"] == "oversize" and sent == []


def _write_sample(out, name, record):
    path = out / "samples" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_report_scores_run_statuses_and_matched_indices(tmp_path, monkeypatch):
    case = _doc(tmp_path)
    document = _document(case)
    _fake_query(monkeypatch, [_finding("Artikel 9 Inkrafttreten", "datum"),
                              _finding("§ 10 Absatz 3 wird gestrichen.")], [])
    out = tmp_path / "run"
    _write_sample(out, "21-537.json", run.run_one(LEKTOR, document, TEXT, "claude-x", "tag"))
    (tmp_path / "21-9.txt").write_text(TEXT, encoding="utf-8")
    failed = case | {"id": "L-F", "doc": "21/9",
                     "text": {"file": "21-9.txt", "sha256": case["text"]["sha256"]}}
    _write_sample(out, "21-9.failed.json", {"doc": "21/9", "status": "failed",
                  "error_type": "RuntimeError", "error": "boom"})
    (tmp_path / "21-8.txt").write_text(TEXT, encoding="utf-8")
    unrun = case | {"id": "L-Y", "doc": "21/8",
                    "text": {"file": "21-8.txt", "sha256": case["text"]["sha256"]}}
    manifest = _manifest(case) | _manifest(failed) | _manifest(unrun)

    rows, results = report.build(LEKTOR, [case, failed, unrun], report.load_samples(out),
                                 manifest, texts=tmp_path, near=100)

    assert [(r["id"], r["verdict"]) for r in rows] == [
        ("L-C13", "hit"), ("L-F", "failed"), ("L-Y", "not_run")]
    assert rows[0]["matched"] == [{"index": 1, "category": "vollstaendigkeit", "title": "t"}]
    assert [f["located"] for f in results[0]["run"]["findings"]] == [True, True]
    assert results[1]["run"]["error"] == "RuntimeError: boom" and results[2]["run"] is None

    summary = report.summarize_run(LEKTOR, rows, results, "beschlussempfehlungen", "tag", 100)
    assert summary["runs"] == {"ok": 1, "failed": 1, "not_run": 1}
    assert summary["efforts"] == {None: 2}
    assert summary["cost_usd"] == 0.5
    assert summary["words_per_sentence"] > 0
    assert summary["recall"]["dev"]["all"]["scorable"] == 1
    assert summary["recall"]["dev"]["all"]["strict"] == 1.0
    assert summary["recall_by_category"]["dev"]["vollstaendigkeit"]["counts"] == {
        "hit": 1, "failed": 1, "not_run": 1}


def test_words_per_sentence_keeps_abbreviations_inside_the_sentence():
    texts = ["Der Verweis in § 5 Abs. 2 geht ins Leere. Absatz 2 gibt es nicht mehr.",
             "Keine Befunde."]
    assert report.words_per_sentence(texts) == 6.0  # 18 words, 3 sentences
    assert report.words_per_sentence(["", "  "]) is None


def test_a_sample_supersedes_a_stale_failure(tmp_path, monkeypatch):
    _fake_query(monkeypatch, [], [])
    out = tmp_path / "run"
    _write_sample(out, "21-537.failed.json", {"doc": "21/537", "status": "failed"})
    _write_sample(out, "21-537.json", run.run_one(LEKTOR, _document(_doc(tmp_path)), TEXT, "claude-x", "tag"))
    assert report.load_samples(out)["21/537"]["status"] == "ok"


def test_only_cases_without_context_are_run():
    for task in tasks.TASKS.values():
        for case_set in task.case_sets:
            cases = report.load_cases(task, case_set)
            assert cases and {c["requires_context"] for c in cases} == {"none"}


def test_report_on_one_split_ignores_samples_of_the_other(tmp_path, monkeypatch):
    dev = _doc(tmp_path)
    (tmp_path / "21-9.txt").write_text(TEXT, encoding="utf-8")
    test = dev | {"id": "L-T", "doc": "21/9", "split": "test",
                  "text": {"file": "21-9.txt", "sha256": dev["text"]["sha256"]}}
    monkeypatch.setattr(report, "load_cases", lambda task, case_set: [dev, test])
    monkeypatch.setattr(report, "load_manifest", lambda: _manifest(dev) | _manifest(test))
    _fake_query(monkeypatch, [_finding("§ 10 Absatz 3 wird gestrichen.")], [])
    out = tmp_path / "run"
    for case in (dev, test):
        _write_sample(out, case["text"]["file"].replace(".txt", ".json"),
                      run.run_one(LEKTOR, _document(case), TEXT, "claude-x", "tag"))

    summary = report.write_report(out, LEKTOR, "beschlussempfehlungen", "tag", split="dev")

    assert summary["split"] == "dev" and summary["runs"] == {"ok": 1, "not_run": 0}
    assert set(summary["recall"]) == {"dev"}
    assert (out / "summary-beschlussempfehlungen-dev.json").is_file()
    assert not (out / "summary-beschlussempfehlungen.json").exists()


def test_html_escapes_model_text_and_documents_every_case(tmp_path, monkeypatch):
    case = _doc(tmp_path)
    monkeypatch.setattr(report, "load_cases", lambda task, case_set: [case])
    monkeypatch.setattr(report, "load_manifest", lambda: _manifest(case))
    _fake_query(monkeypatch, [_finding("§ 10 Absatz 3 wird gestrichen.") | {"title": "<script>x</script>"}], [])
    out = tmp_path / "run"
    _write_sample(out, "21-537.json", run.run_one(LEKTOR, _document(case), TEXT, "claude-x", "tag"))
    report.write_report(out, LEKTOR, "beschlussempfehlungen", "tag", split="dev")

    page = (out / "report-beschlussempfehlungen-dev.html").read_text(encoding="utf-8")
    assert "L-C13" in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert "<script>x</script>" not in page
    # A case is documented in full: expectation, anchor, story and source.
    assert "keine Übergangsregel" in page and "§ 10 Absatz 3 wird gestrichen" in page
    assert "Der Ausschuss strich § 10 Abs. 3, ohne Altfälle zu regeln." in page
    assert "Volltext geprüft." in page


def test_about_section_describes_only_the_case_file_that_was_scored():
    name = "cases-lektor-beschlussempfehlungen.yaml"
    rendered = html._about(name, 7, "dev")
    assert name in rendered and page.esc(about.FILES[name]["mined"]) in rendered
    assert "7 of them in this run, split dev" in rendered
    assert "cases-angreifer.yaml" not in rendered and "cases-lektor.yaml</b>" not in rendered


def test_case_sets_name_every_file_of_each_task():
    assert LEKTOR.case_sets == {"beschlussempfehlungen":
                                    lint.DIR / "cases-lektor-beschlussempfehlungen.yaml",
                                "lektor": lint.DIR / "cases-lektor.yaml"}
    assert LEKTOR.default_cases == "beschlussempfehlungen"
    assert ANGREIFER.case_sets == {"angreifer": lint.DIR / "cases-angreifer.yaml"}
    assert report.case_set(ANGREIFER, None) == "angreifer"


def test_manifest_must_cover_every_document_with_its_pinned_text(tmp_path):
    case = _case(tmp_path)
    manifest = _manifest(case)
    assert lint.check_manifest(manifest, [case], tmp_path) == []
    assert lint.check_manifest({}, [case], tmp_path) == ["inputs.yaml: 21/537 missing"]
    other = {"file": "21-537.txt", "sha256": hashlib.sha256(b"x").hexdigest()}
    stale = {"21/537": {"titel": "T", "gesetzentwurf": other}}
    assert lint.check_manifest(stale, [case], tmp_path) == [
        "inputs.yaml: 21/537 gesetzentwurf differs from its cases",
        "inputs.yaml: 21/537 sha256 mismatch"]
    extra = manifest | {"21/9": {"titel": "", "gesetzentwurf": case["text"]}}
    assert lint.check_manifest(extra, [case], tmp_path) == [
        "inputs.yaml: 21/9 used by no case", "inputs.yaml: 21/9 without titel"]


def test_run_one_records_a_rescue_and_its_cost(tmp_path, monkeypatch):
    async def fake(message, model=None, on_message=None, effort=None, max_turns=1):
        result = SimpleNamespace(num_turns=2, session_id="s", total_cost_usd=0.5, usage={})
        rescue = SimpleNamespace(session_id="r", total_cost_usd=0.02)
        return structured.StructuredRun(BillAnalysis(summary="s", findings=[]), result, [],
                                        "call", rescue)
    monkeypatch.setattr(analyzer, "run_query", fake)

    record = run.run_one(LEKTOR, _document(_doc(tmp_path)), TEXT, "claude-x", "tag")
    assert record["status"] == "ok" and record["rescued_by"] == "call"
    assert record["cost_usd"] == 0.52 and record["rescue_cost_usd"] == 0.02
    assert record["session_id"] == "s" and record["rescue_session_id"] == "r"


def test_heading_names_what_was_measured_and_how():
    summary = {"task": "lektor",
               "cases_file": "cases-lektor-beschlussempfehlungen.yaml", "split": "dev",
               "prompt_versions": {"v6-text-json": 21}, "models": {"claude-opus-4-8": 21},
               "efforts": {"high": 21}, "documents": 21,
               "generated_at": "2026-09-30T10:00:00+00:00"}
    assert html._heading(summary) == (
        "Lektor evaluation · Committee repairs · dev · v6-text-json · Claude Opus 4.8",
        "Lektor evaluation: Committee repairs, dev split",
        "Prompt v6-text-json · Claude Opus 4.8 · reasoning effort high · 21 drafts · "
        "scored 2026-09-30")
    assert html._heading(summary | {"split": "all"})[1].endswith("all splits")


# --- the Angreifer task -------------------------------------------------------

def _exploit(quote, muster="schwellenwert", severity="hoch"):
    return {"muster": muster, "akteur": "Ein Erwerber", "titel": "<b>Angriff</b>",
            "schritte": ["Erwirbt 89,9 %.", "Wartet."], "vorteil": "Keine Steuer.",
            "aufwand": "niedrig", "quote": quote, "fehlende_absicherung": "Zurechnung.",
            "severity": severity}


def _fake_redteam(monkeypatch, exploits, sent):
    async def fake(message, model=None, on_message=None, effort=None, max_turns=1):
        sent.append((message, model, effort))
        result = SimpleNamespace(num_turns=1, session_id="s", total_cost_usd=0.3, usage={})
        return structured.StructuredRun(
            RedTeamAnalysis(summary="Angriffsfläche", exploits=exploits), result, [], None, None)
    monkeypatch.setattr(redteam, "run_query", fake)


def _angreifer_case(tmp_path, **overrides):
    return _doc(tmp_path) | {"id": "R-X1", "suite": "angreifer",
                             "expected_category": "schwellenwert"} | overrides


def test_angreifer_sends_the_redteam_message_whole_and_normalises_exploits(tmp_path, monkeypatch):
    sent = []
    _fake_redteam(monkeypatch, [_exploit("§ 10 Absatz 3 wird gestrichen.", severity="mittel")], sent)
    record = run.run_one(ANGREIFER, _document(_angreifer_case(tmp_path)), TEXT, "claude-x",
                         "tag", effort="high")

    assert sent == [(redteam.build_message("Entwurf eines Gesetzes", "21/537", TEXT),
                     "claude-x", "high")]
    assert "HINWEIS" not in sent[0][0]  # never truncated
    assert record["task"] == "angreifer" and record["risk"] == "mittel"
    assert record["prompt_version"] == backend_config.REDTEAM_PROMPT_VERSION
    [finding] = ANGREIFER.findings(record["analysis"])
    assert finding["category"] == "schwellenwert" and finding["title"] == "<b>Angriff</b>"
    assert finding["quote"] == "§ 10 Absatz 3 wird gestrichen."
    assert "(1) Erwirbt 89,9 %. (2) Wartet." in finding["description"]


def test_angreifer_oversize_follows_the_lektor_rule(tmp_path, monkeypatch):
    sent = []
    _fake_redteam(monkeypatch, [], sent)
    monkeypatch.setattr(analyzer, "MAX_INPUT_CHARS", len(TEXT) - 1)
    record = run.run_one(ANGREIFER, _document(_angreifer_case(tmp_path)), TEXT, "claude-x", "tag")
    assert record["status"] == "oversize" and sent == []


def test_redteam_options_carry_model_effort_and_turns():
    options = redteam._options("claude-x", "low", 2)
    assert (options.model, options.effort, options.max_turns) == ("claude-x", "low", 2)
    assert redteam._options().effort == backend_config.REDTEAM_EFFORT
    assert redteam._options().model == backend_config.REDTEAM_MODEL


def test_angreifer_negative_without_anchor_is_fired_or_quiet(tmp_path, monkeypatch):
    negative = _angreifer_case(tmp_path, id="R-F1", kind="negativ", anchor=None,
                               expected_defect=None, expected_category=None,
                               forbidden_claim="Jeder konstruierte Angriff")
    manifest = _manifest(negative)
    out = tmp_path / "run"

    _fake_redteam(monkeypatch, [_exploit("frei erfunden")], [])
    _write_sample(out, "21-537.json", run.run_one(ANGREIFER, _document(negative), TEXT, "c", "t"))
    rows, _ = report.build(ANGREIFER, [negative], report.load_samples(out), manifest,
                           texts=tmp_path)
    assert rows[0]["verdict"] == "fired"

    _fake_redteam(monkeypatch, [], [])
    _write_sample(out, "21-537.json", run.run_one(ANGREIFER, _document(negative), TEXT, "c", "t"))
    rows, _ = report.build(ANGREIFER, [negative], report.load_samples(out), manifest,
                           texts=tmp_path)
    assert rows[0]["verdict"] == "quiet"

    # The Lektor's unanchored negatives forbid one specific claim: no verdict.
    _fake_query(monkeypatch, [_finding("frei erfunden")], [])
    lektor_out = tmp_path / "lektor-run"
    _write_sample(lektor_out, "21-537.json", run.run_one(LEKTOR, _document(negative), TEXT, "c", "t"))
    rows, _ = report.build(LEKTOR, [negative | {"suite": "lektor"}],
                           report.load_samples(lektor_out), manifest, texts=tmp_path)
    assert rows[0]["verdict"] == "unanchored"


def test_angreifer_report_uses_its_own_wording(tmp_path, monkeypatch):
    case = _angreifer_case(tmp_path)
    monkeypatch.setattr(report, "load_cases", lambda task, case_set: [case])
    monkeypatch.setattr(report, "load_manifest", lambda: _manifest(case))
    _fake_redteam(monkeypatch, [_exploit("§ 10 Absatz 3 wird gestrichen.")], [])
    out = tmp_path / "run"
    _write_sample(out, "21-537.json", run.run_one(ANGREIFER, _document(case), TEXT, "c", "t"))
    summary = report.write_report(out, ANGREIFER, "angreifer", "tag", split="dev")

    assert summary["task"] == "angreifer" and summary["cases_file"] == "cases-angreifer.yaml"
    assert summary["recall"]["dev"]["all"]["counts"] == {"hit": 1}
    html_page = (out / "report-angreifer-dev.html").read_text(encoding="utf-8")
    assert "Angreifer evaluation" in html_page and "Expected attack" in html_page
    assert "Lektor evaluation" not in html_page
    assert "&lt;b&gt;Angriff&lt;/b&gt;" in html_page
