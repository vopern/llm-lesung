"""The trace log has to survive the case it exists for: a call that aborts.

No network and no Claude call — the SDK message objects are stood in for by
plain classes with the same duck type, which is all ``tracelog`` reads.

The properties under test: the stream is on disk *before* the call ends, the
draft text is never in it, and a raising call still produces a readable file.
"""

import json

import pytest

from backend import tracelog


class _Block:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class ThinkingBlock(_Block):
    pass


class TextBlock(_Block):
    pass


class ToolUseBlock(_Block):
    pass


class AssistantMessage:
    def __init__(self, content, message_id="msg_abc123", stop_reason="tool_use"):
        self.content = content
        self.message_id = message_id
        self.stop_reason = stop_reason
        self.usage = {"output_tokens": 42}


class ResultMessage:
    def __init__(self, subtype="success", is_error=False, num_turns=2):
        self.subtype = subtype
        self.is_error = is_error
        self.num_turns = num_turns
        self.session_id = "sess-1"
        self.errors = None
        self.usage = {}
        self.total_cost_usd = 0.21


BODY = "USER MESSAGE WITH THE WHOLE DRAFT TEXT"


def _header():
    return tracelog.header_for(
        {"task": "angreifer", "doc": "21/5588", "tag": "v4-tag", "model": "claude-opus-4-8",
         "prompt_version": "v4-prompt", "max_turns": 1}, BODY)


def test_header_records_the_draft_by_digest_not_by_body():
    header = _header()
    assert header["doc"] == "21/5588"
    assert header["user_message_chars"] == len(BODY)
    assert len(header["user_message_sha256_16"]) == 16
    assert BODY not in json.dumps(header)


def test_messages_are_on_disk_before_the_call_ends(tmp_path):
    """Written as they arrive — an aborted call never reaches the end."""
    path = tmp_path / "21-5588.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([TextBlock(text="partial output")]))
        mid = path.read_text(encoding="utf-8")
    assert "partial output" in mid  # visible before __exit__ ran


def test_failed_call_leaves_a_readable_trace_with_the_error(tmp_path):
    path = tmp_path / "21-5588.jsonl"
    with pytest.raises(RuntimeError):
        with tracelog.TraceLog(path, _header()) as trace:
            trace.message(AssistantMessage([
                ToolUseBlock(name="StructuredOutput", input={"summary": "x"})]))
            raise RuntimeError("Reached maximum number of turns (3)")

    header, messages, footer = tracelog.read(path)
    assert header["doc"] == "21/5588"
    assert len(messages) == 1
    assert footer["ok"] is False
    assert footer["error_type"] == "RuntimeError"
    assert "maximum number of turns" in footer["error"]
    assert "RuntimeError" in footer["traceback"]


def test_missing_footer_is_distinguishable_from_a_clean_run(tmp_path):
    """A killed process leaves no footer; that must not read as success."""
    path = tmp_path / "21-5588.jsonl"
    trace = tracelog.TraceLog(path, _header()).__enter__()
    trace.message(AssistantMessage([TextBlock(text="truncated")]))
    _, messages, footer = tracelog.read(path)
    assert len(messages) == 1
    assert footer is None


def test_thinking_is_stored_in_full(tmp_path):
    """The reasoning is what makes a failed run diagnosable."""
    long_thought = "weighing this " * 500
    path = tmp_path / "17-8877.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([ThinkingBlock(thinking=long_thought)]))
    _, messages, _ = tracelog.read(path)
    block = messages[0]["blocks"][0]
    assert block["thinking"] == long_thought
    assert block["chars"] == len(long_thought)


def test_unparsed_tool_input_is_kept_verbatim(tmp_path):
    raw = '{"summary": "cut off mid-string'
    path = tmp_path / "18-10207.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([ToolUseBlock(
            name="StructuredOutput",
            input={"__unparsedToolInput": {"raw": raw}})]))
    _, messages, _ = tracelog.read(path)
    assert messages[0]["blocks"][0]["unparsed_raw"] == raw


def test_schema_rejection_loop_is_reconstructable(tmp_path):
    """message_id makes turns countable — blocks sharing an id are one response."""
    path = tmp_path / "21-5588.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        for i in range(3):
            trace.message(AssistantMessage(
                [ToolUseBlock(name="StructuredOutput", input={"summary": "x"})],
                message_id=f"msg_{i}"))
        trace.message(ResultMessage(subtype="error_max_turns", is_error=True,
                                    num_turns=4))
    _, messages, footer = tracelog.read(path)
    ids = [m["message_id"] for m in messages if m["type"] == "AssistantMessage"]
    assert ids == ["msg_0", "msg_1", "msg_2"]
    assert all("exploits" not in m["blocks"][0]["input_keys"]
               for m in messages if m["type"] == "AssistantMessage")
    result = [m for m in messages if m["type"] == "ResultMessage"][0]
    assert result["subtype"] == "error_max_turns"
    assert result["is_error"] is True
    assert footer["ok"] is True  # the call returned; the caller judges the result


def test_rerun_replaces_a_trace_rather_than_appending(tmp_path):
    path = tmp_path / "21-518.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([TextBlock(text="first run")]))
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([TextBlock(text="second run")]))
    _, messages, _ = tracelog.read(path)
    assert len(messages) == 1
    assert messages[0]["blocks"][0]["text"] == "second run"


def test_unknown_block_type_is_recorded_not_dropped(tmp_path):
    """The SDK's block union grows between versions."""
    class SomeFutureBlock(_Block):
        pass

    path = tmp_path / "19-13437.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(AssistantMessage([SomeFutureBlock(mystery=1)]))
    _, messages, _ = tracelog.read(path)
    assert messages[0]["blocks"][0]["block"] == "SomeFutureBlock"


class SystemMessage:
    def __init__(self, subtype, data=None):
        self.subtype = subtype
        self.data = data or {}


def test_thinking_ticks_are_counted_into_the_footer_not_written(tmp_path):
    path = tmp_path / "trace.jsonl"
    with tracelog.TraceLog(path, _header()) as trace:
        trace.message(SystemMessage("init", {"model": "claude-opus-4-8"}))
        for n in range(3):
            trace.message(SystemMessage(tracelog.THINKING_TICK, {"tokens": n}))
        trace.message(AssistantMessage([ThinkingBlock(thinking="Zusammenfassung")]))
    _, messages, footer = tracelog.read(path)
    assert [m["type"] for m in messages] == ["SystemMessage", "AssistantMessage"]
    assert messages[0]["data"] == {"model": "claude-opus-4-8"}
    assert footer["messages"] == 2
    assert footer["thinking_ticks"] == 3
    assert footer["thinking_tokens_last"] == {"tokens": 2}


def test_traced_writes_header_stream_and_footer(tmp_path):
    path = tmp_path / "traces" / "21-1.jsonl"
    with tracelog.traced(path, {"doc": "21/1"}, BODY) as on_message:
        on_message(AssistantMessage([TextBlock(text="{}")]))
    header, messages, footer = tracelog.read(path)
    assert header["doc"] == "21/1" and header["user_message_chars"] == len(BODY)
    assert len(messages) == 1 and footer["ok"] is True
    assert BODY not in path.read_text(encoding="utf-8")


def test_traced_without_a_path_writes_nothing(tmp_path):
    with tracelog.traced(None, {"doc": "21/1"}, BODY) as on_message:
        on_message(AssistantMessage([TextBlock(text="{}")]))
    assert list(tmp_path.iterdir()) == []
