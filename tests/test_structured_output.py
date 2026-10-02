"""The shared structured call: plain-text answer, local parse, rescue call (offline, no Claude).

The main call answers as JSON in a text block; the fakes replay well-formed,
wrapped, broken and prose answers, and the rescue call's tool-call shapes.
"""

import asyncio
import json
from dataclasses import replace

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from backend import errorlog
from backend.analysis import analyzer, redteam, structured
from backend.analysis.schema import BillAnalysis, RedTeamAnalysis

REJECTED = ("Output does not match required schema: root: must have required property "
            "'summary', root: must have required property 'findings', "
            "root: must NOT have additional properties")

FINDING = {"severity": "mittel", "category": "widerspruch",
           "title": "Widerspruch zur Übergangsregelung",
           "description": "Die Begründung beschreibt eine Übergangsregelung, die im Normtext fehlt.",
           "quote": "§ 3 Absatz 2 gilt ab dem 1. Januar 2027."}


def _analysis(summary="Der Entwurf ist überwiegend stimmig.", findings=(FINDING,)):
    return {"summary": summary, "findings": list(findings)}


def _response(*blocks, n=1, stop_reason="tool_use"):
    return AssistantMessage(content=list(blocks), model="m", session_id=f"sess{n}",
                            stop_reason=stop_reason)


def _tool(payload, n=1):
    return ToolUseBlock(id=f"t{n}", name="StructuredOutput", input=payload)


def _rejection(n=1):
    return UserMessage(content=[ToolResultBlock(tool_use_id=f"t{n}", content=REJECTED,
                                                is_error=True)])


def _result(subtype, structured_output=None, session="sess1", cost=0.8):
    return ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1,
                         is_error=subtype != "success", num_turns=2, session_id=session,
                         total_cost_usd=cost, structured_output=structured_output,
                         errors=None if subtype == "success"
                         else ["Reached maximum number of turns (1)"])


MAX_TURNS_ERROR = Exception("Claude Code returned an error result: Reached maximum number of turns (1)")


def _fake_query(monkeypatch, main, rescue=None):
    """``main``/``rescue``: ``(messages, exception or None)``; records the rescue prompt."""
    prompts = []

    async def fake(prompt, options):
        is_rescue = options.system_prompt == structured.RESCUE_SYSTEM_PROMPT
        if is_rescue:
            prompts.append((prompt, options))
        messages, error = rescue if is_rescue else main
        for message in messages:
            yield message
        if error is not None:
            raise error
    monkeypatch.setattr(structured, "query", fake)
    return prompts


def _run(**kwargs):
    return asyncio.run(analyzer.run_query("Nachricht", **kwargs))


def _rescued(output, cost=0.02):
    """A rescue call that returns ``output`` cleanly."""
    return [_response(_tool(output, n=9), n=9),
            _result("success", output, session="rescue", cost=cost)], None



def _answered(text, stop_reason="end_turn"):
    """A main call that answered with ``text`` and ended normally."""
    return [_response(TextBlock(text=text), stop_reason=stop_reason), _result("success")], None


def _json(analysis):
    return json.dumps(analysis, ensure_ascii=False)


# --- options -------------------------------------------------------------------------

def test_every_structured_call_is_single_turn():
    assert structured.MAX_TURNS == 1
    assert analyzer._options().max_turns == 1 and redteam._options().max_turns == 1
    assert analyzer.MAX_TURNS == redteam.MAX_TURNS == 1


def test_no_call_can_end_the_conversation_instead_of_answering():
    for options in (analyzer._options(), redteam._options(), structured._rescue_options({})):
        assert options.tools == [] and "EndConversation" in options.disallowed_tools


def test_the_main_call_asks_for_the_schema_as_text_without_a_tool(monkeypatch):
    seen = []

    async def fake(prompt, options):
        seen.append(options)
        yield _response(TextBlock(text=_json(_analysis())), stop_reason="end_turn")
        yield _result("success")
    monkeypatch.setattr(structured, "query", fake)
    _run(max_turns=2)
    (options,) = seen
    assert options.output_format is None and options.tools == [] and options.max_turns == 2
    assert options.system_prompt.startswith(analyzer.SYSTEM_PROMPT)
    assert options.system_prompt.endswith(structured.format_section(analyzer._output_schema()))
    assert '"findings"' in options.system_prompt and "„…“" in options.system_prompt


def test_every_call_returns_its_thinking_as_a_summary(monkeypatch):
    seen = []

    async def fake(prompt, options):
        seen.append(options)
        yield _response(TextBlock(text=_json(_analysis())), stop_reason="end_turn")
        yield _result("success")
    monkeypatch.setattr(structured, "query", fake)
    _run()
    assert seen[0].thinking == structured.THINKING == {"type": "adaptive", "display": "summarized"}
    assert structured._rescue_options({}).thinking == structured.THINKING


def test_a_callers_own_thinking_setting_wins(monkeypatch):
    seen = []

    async def fake(prompt, options):
        seen.append(options)
        yield _response(TextBlock(text=_json(_analysis())), stop_reason="end_turn")
        yield _result("success")
    monkeypatch.setattr(structured, "query", fake)
    own = {"type": "disabled"}
    asyncio.run(structured.run("Nachricht", replace(analyzer._options(), thinking=own),
                               BillAnalysis, analyzer._output_schema()))
    assert seen[0].thinking == own


# --- attempt log, local parse --------------------------------------------------------

def test_attempt_log_keeps_tool_calls_rejections_and_text_but_never_thinking():
    log = structured.AttemptLog()
    for message in [_response(ThinkingBlock(thinking="geheim", signature="x"),
                              TextBlock(text="Vorbemerkung"),
                              _tool({"StructuredOutput": "{}"})),
                    _rejection()]:
        log.message(message)
    (attempt,) = log.attempts
    assert attempt["call"] == "main" and attempt["keys"] == ["StructuredOutput"]
    assert attempt["is_error"] is True and attempt["result"] == REJECTED
    assert log.texts == ["Vorbemerkung"] and log.session_id == "sess1"


@pytest.mark.parametrize("wrapper", ["StructuredOutput", "$PARAMETER_NAME"])
def test_recover_unwraps_a_json_string_under_a_single_key(wrapper):
    attempts = [{"attempt": 1, "payload": {wrapper: _json(_analysis())}}]
    assert structured.recover(attempts, BillAnalysis) == BillAnalysis.model_validate(_analysis())
    assert attempts[0]["recovered"] is True


def test_recover_unwraps_a_json_string_beside_a_parameter_name():
    payload = {"$PARAMETER_NAME": "response", "$PARAMETER_VALUE": _json(_analysis())}
    attempts = [{"attempt": 1, "payload": payload}]
    assert structured.recover(attempts, BillAnalysis) == BillAnalysis.model_validate(_analysis())


def test_recover_unwraps_an_object_and_an_unparsed_payload():
    wrapped = [{"attempt": 1, "payload": {"BillAnalysis": _analysis()}}]
    unparsed = [{"attempt": 1, "payload": {structured.UNPARSED_KEY: {"raw": json.dumps(_analysis())}}}]
    assert structured.recover(wrapped, BillAnalysis) is not None
    assert structured.recover(unparsed, BillAnalysis) is not None


def test_recover_never_accepts_a_partial_payload():
    attempts = [
        {"attempt": 1, "payload": {"summary": "Nur eine Zusammenfassung."}},
        {"attempt": 2, "payload": {"StructuredOutput": '{"summary": "abgeschnitten", "find'}},
        {"attempt": 3, "payload": FINDING},
        {"attempt": 4, "payload": {"outer": {"inner": json.dumps(_analysis())}}},
    ]
    assert structured.recover(attempts, BillAnalysis) is None
    assert not any("recovered" in a for a in attempts)


@pytest.mark.parametrize("texts", [
    [_json(_analysis())],
    ["```json\n" + _json(_analysis()) + "\n```"],
    ["Ich habe den Regelungstext zuerst geprüft.", _json(_analysis())],
    ["Ergebnis:\n" + _json(_analysis()) + "\nEnde."],
    [_json({"BillAnalysis": _analysis()})],
    [_json({"StructuredOutput": _json(_analysis())})],
])
def test_parse_answer_finds_the_json_object_in_the_text(texts):
    output, why = structured.parse_answer(texts, BillAnalysis)
    assert output == BillAnalysis.model_validate(_analysis()) and why == ""


@pytest.mark.parametrize("texts, why", [
    ([], "no text in the response"),
    ([_json({"summary": "Nur eine Zusammenfassung."})], "does not match the schema"),
    (['{"summary": "Der „Entwurf" ist stimmig.", "findings": []}'], "not valid JSON"),
    (["Der Entwurf ist überwiegend stimmig."], "not valid JSON"),
])
def test_parse_answer_never_accepts_a_partial_or_broken_answer(texts, why):
    output, reason = structured.parse_answer(texts, BillAnalysis)
    assert output is None and why in reason


def test_success_needs_no_rescue(monkeypatch):
    prompts = _fake_query(monkeypatch, _answered(_json(_analysis())))
    run = _run()
    assert run.output == BillAnalysis.model_validate(_analysis())
    assert run.rescued_by is None and run.rescue_result is None and prompts == []
    assert run.attempts == []


# --- rescue call ---------------------------------------------------------------------

def _broken(analysis):
    """Unparseable JSON: an unescaped quote inside a string, content complete."""
    return _json(analysis).replace("überwiegend", 'überwiegend "stimmig')


# The faithful transcription of ``_broken(_analysis())``.
FIXED = _analysis(summary='Der Entwurf ist überwiegend "stimmig stimmig.')


def test_an_unparseable_answer_is_rescued_by_a_verified_call(monkeypatch):
    seen = []
    prompts = _fake_query(monkeypatch, _answered(_broken(_analysis())), _rescued(FIXED))

    run = _run(on_message=seen.append)

    assert run.rescued_by == "call" and run.output == BillAnalysis.model_validate(FIXED)
    assert run.rescue_result.session_id == "rescue" and len(seen) == 4
    (prompt, options), = prompts
    assert _broken(_analysis()) in prompt
    assert options.model == structured.config.RESCUE_MODEL and options.max_turns == 1
    assert options.tools == []
    assert options.output_format == {"type": "json_schema", "schema": analyzer._output_schema()}
    assert [a["call"] for a in run.attempts] == ["rescue"]
    fields = structured.record_fields(run)
    assert fields["rescued_by"] == "call" and fields["cost_usd"] == pytest.approx(0.82)


def test_the_rescue_gets_the_whole_answer(monkeypatch):
    findings = [FINDING | {"title": f"Befund {i}", "description": f"Beschreibung {i} " * 40}
                for i in range(12)]
    long_answer = _broken(_analysis(findings=findings))
    assert len(long_answer) > 2048
    prompts = _fake_query(monkeypatch, _answered(long_answer),
                          _rescued(_analysis(summary=FIXED["summary"], findings=findings)))
    run = _run()
    assert len(run.output.findings) == 12 and long_answer in prompts[0][0]


def test_an_answer_written_as_prose_is_rescued(monkeypatch):
    text = ("Zusammenfassung: Der Entwurf ist überwiegend stimmig.\n\n"
            f"Befund (mittel, widerspruch): {FINDING['title']}\n{FINDING['description']}\n"
            f"Zitat: {FINDING['quote']}")
    prompts = _fake_query(monkeypatch, _answered(text), _rescued(_analysis()))
    run = _run()
    assert run.rescued_by == "call" and text in prompts[0][0]


@pytest.mark.parametrize("tamper, why", [
    (lambda a: a | {"summary": "Der Entwurf ist weitgehend stimmig."}, "text not in the response"),
    (lambda a: a | {"findings": [FINDING | {"quote": "§ 3 Abs. 2 gilt ab 2027."}]},
     "text not in the response"),
    (lambda a: a | {"findings": []}, "dropped from the response"),
    (lambda a: a | {"findings": [FINDING | {"category": "referenz"}]},
     "enum value not in the response"),
    (lambda a: a | {"findings": [FINDING | {"title": ""}]}, "text not in the response"),
])
def test_a_rescue_that_is_not_a_transcription_is_rejected(monkeypatch, tamper, why):
    _fake_query(monkeypatch, _answered(_broken(_analysis())), _rescued(tamper(FIXED)))
    with pytest.raises(structured.StructuredOutputError, match="not a transcription") as caught:
        _run()
    assert why in str(caught.value)
    assert [a["call"] for a in caught.value.attempts] == ["main", "rescue"]
    assert caught.value.attempts[0]["answer"] == _broken(_analysis())


def test_a_rescue_may_not_supply_a_list_the_answer_never_wrote(monkeypatch):
    """The answer carried only a summary; an empty findings list would read as a clean draft."""
    summary_only = {"summary": "Der Entwurf enthält einen Verweisfehler und einen Rechenfehler."}
    _fake_query(monkeypatch, _answered(_json(summary_only)),
                _rescued(summary_only | {"findings": []}))
    with pytest.raises(structured.StructuredOutputError, match="empty list not in the response"):
        _run()


def test_an_empty_list_the_answer_wrote_is_transcribed(monkeypatch):
    clean = _analysis(findings=())
    _fake_query(monkeypatch, _answered(_json(clean) + "}"), _rescued(clean))
    assert _run().output.findings == []


def test_verify_accepts_umlauts_escapes_and_whitespace_as_written():
    payload = json.dumps(json.dumps(_analysis(), ensure_ascii=True))  # double-encoded, \\u escapes
    assert structured.verify(BillAnalysis.model_validate(_analysis()), [payload], []) is None


def test_verify_works_for_the_red_team_schema():
    exploit = {"muster": "schwellenwert", "akteur": "Ein Betreiber mit mehreren Anlagen.",
               "titel": "Aufteilung unter die Schwelle", "schritte": ["Anlage in zwei Teile teilen."],
               "vorteil": "Die Meldepflicht entfällt für beide Teile vollständig.",
               "aufwand": "niedrig", "quote": "ab einer Leistung von 100 Kilowatt",
               "fehlende_absicherung": "Eine Zusammenrechnungsklausel für verbundene Anlagen.",
               "severity": "hoch"}
    analysis = {"summary": "Eine Angriffsfläche.", "exploits": [exploit]}
    output = RedTeamAnalysis.model_validate(analysis)
    assert structured.verify(output, [_json(analysis)], []) is None
    tampered = RedTeamAnalysis.model_validate(
        analysis | {"exploits": [exploit | {"schritte": ["Anlage aufteilen."]}]})
    assert "text not in the response" in structured.verify(tampered, [_json(analysis)], [])


def test_the_red_team_uses_the_same_call(monkeypatch):
    calls = []

    async def fake(prompt, options, model, schema, on_message=None):
        calls.append((options.system_prompt, model, schema))
        return structured.StructuredRun(None, None, [], None, None)
    monkeypatch.setattr(structured, "run", fake)
    asyncio.run(redteam.run_query("x"))
    asyncio.run(analyzer.run_query("x"))
    assert calls == [(redteam.REDTEAM_SYSTEM_PROMPT, RedTeamAnalysis, redteam._output_schema()),
                     (analyzer.SYSTEM_PROMPT, BillAnalysis, analyzer._output_schema())]


# --- failures ------------------------------------------------------------------------

def test_a_response_cut_off_at_the_token_limit_is_not_rescued(monkeypatch):
    prompts = _fake_query(monkeypatch, _answered(_broken(_analysis()), stop_reason="max_tokens"))
    with pytest.raises(structured.StructuredOutputError, match="token limit"):
        _run()
    assert prompts == []


def test_a_response_with_only_thinking_is_not_rescued(monkeypatch):
    main = ([_response(ThinkingBlock(thinking=json.dumps(_analysis()), signature="x"),
                       stop_reason="end_turn"), _result("success", None)], None)
    prompts = _fake_query(monkeypatch, main)
    with pytest.raises(structured.StructuredOutputError, match="no text in the response"):
        _run()
    assert prompts == []


def _failing_rescue():
    return ([_response(_tool({"summary": "nur das"}, n=9), n=9), _rejection(n=9),
             _result("error_max_turns", session="rescue")], MAX_TURNS_ERROR)


def test_a_failed_rescue_call_raises_with_both_calls_logged(monkeypatch):
    _fake_query(monkeypatch, _answered(_broken(_analysis())), _failing_rescue())
    with pytest.raises(structured.StructuredOutputError, match="rescue call failed") as caught:
        _run()
    assert [a["call"] for a in caught.value.attempts] == ["main", "rescue"]
    assert caught.value.session_id == "sess1"


def test_failure_carries_the_answer_into_the_error_log(monkeypatch, tmp_path):
    answer = _json({"summary": "Nur eine Zusammenfassung."})
    _fake_query(monkeypatch, _answered(answer), _failing_rescue())
    with pytest.raises(structured.StructuredOutputError) as caught:
        _run()
    error = caught.value

    log = errorlog.ErrorLog(str(tmp_path))
    log.record({"id": "1", "dokumentnummer": "21/1"}, "attempted", 1, 2, error)
    entry = json.loads(log.path.read_text(encoding="utf-8"))
    assert entry["session_id"] == "sess1"
    assert entry["attempts"][0]["answer"] == answer
    assert entry["attempts"][1]["result"] == REJECTED
    assert structured.failure_fields(error) == {"session_id": "sess1", "attempts": error.attempts}

def test_a_usage_limit_notice_is_never_rescued_into_an_analysis(monkeypatch):
    notice = "You've hit your session limit · resets 6:20pm (Europe/Berlin)"
    main = ([AssistantMessage(content=[TextBlock(text=notice)], model=structured.SYNTHETIC_MODEL,
                              session_id="sess1", stop_reason="stop_sequence"),
             _result("success")], Exception("Claude Code returned an error result: success"))
    prompts = _fake_query(monkeypatch, main, _rescued(_analysis(summary=notice, findings=())))
    with pytest.raises(structured.StructuredOutputError) as caught:
        _run()
    assert prompts == [] and notice in str(caught.value)


def test_an_api_error_without_output_raises_without_a_rescue_call(monkeypatch):
    prompts = _fake_query(monkeypatch,
                          ([], Exception("Claude Code returned an error result: success")))
    with pytest.raises(structured.StructuredOutputError) as caught:
        _run()
    assert caught.value.attempts == [] and "error result: success" in str(caught.value)
    assert prompts == []
