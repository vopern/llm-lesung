"""Persist the message stream of every Claude call — including the failed ones.

Used by the pipeline (``data/pipeline/runs/<stamp>/traces/``) and the eval
harness (``data/eval/runs/<tag>/traces/``), both through ``traced``.

A run record keeps only the outcome of a call; the stream of
``AssistantMessage``, ``ThinkingBlock``, ``ToolUseBlock`` and ``tool_result``
is what explains a failed or odd one, and a call that raises returns nothing
else. The CLI's own session transcripts are keyed by session, not by document,
tag or prompt version.

The shape follows ``backend/errorlog.py``: append-only JSONL, stdlib ``json``,
created lazily, one line per event. Two differences:

- **One file per call**, not one per run. Pipeline and harness fan out over a
  ``ThreadPoolExecutor``, so a shared file would need a lock on every message;
  a file per call is written by exactly one thread and needs none.
- **Written as the messages arrive**, not at the end. An aborted call is the
  one we most need to read, and it never reaches the end.

The draft text is **never** stored. The trace keeps the user message's length
and a hash; the text itself is pinned under ``eval/testset/texts/`` or cached
under ``data/pdf-cache/``.

The CLI streams a ``thinking_tokens`` system message every few hundred thinking
tokens. They carry no text, so they are counted into the footer instead of
written one per line.
"""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Thinking blocks are stored in full: the reasoning is most of the output
# tokens, and it is what makes a failed run diagnosable.
STORE_THINKING_IN_FULL = True

# The ``SystemMessage`` subtype of the CLI's thinking progress ticks.
THINKING_TICK = "thinking_tokens"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _block(block: Any) -> dict:
    """One content block, flattened to something greppable.

    Deliberately not ``dataclasses.asdict``: the SDK's block types are a union
    that grows between versions, and a normaliser that silently drops an unknown
    block is worse than one that records its type and repr.
    """
    kind = type(block).__name__
    out: dict[str, Any] = {"block": kind}

    text = getattr(block, "text", None)
    if text is not None:
        out["chars"] = len(text)
        out["text"] = text
        return out

    thinking = getattr(block, "thinking", None)
    if thinking is not None:
        out["chars"] = len(thinking)
        out["thinking"] = thinking if STORE_THINKING_IN_FULL else thinking[:500]
        return out

    name = getattr(block, "name", None)
    if name is not None:
        out["name"] = name
    payload = getattr(block, "input", None)
    if isinstance(payload, dict):
        out["input_keys"] = list(payload)
        # The failure signature worth keeping verbatim: the CLI hands back what
        # it could not parse under this key.
        unparsed = payload.get("__unparsedToolInput")
        if isinstance(unparsed, dict):
            out["unparsed_raw"] = unparsed.get("raw", "")
        else:
            out["input"] = payload
    elif payload is not None:
        out["input_repr"] = repr(payload)[:2000]

    content = getattr(block, "content", None)
    if content is not None and "input" not in out:
        out["content"] = content if isinstance(content, str) else repr(content)[:4000]
    for attr in ("tool_use_id", "is_error"):
        value = getattr(block, attr, None)
        if value is not None:
            out[attr] = value
    return out


def message_entry(message: Any, index: int) -> dict:
    """One streamed SDK message as a JSONL-ready dict.

    ``message_id`` is kept because it marks the API response boundary: blocks
    sharing an id are one response and cost one turn.
    """
    entry: dict[str, Any] = {
        "i": index,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": type(message).__name__,
    }
    for attr in ("message_id", "stop_reason", "subtype", "session_id",
                 "num_turns", "is_error", "total_cost_usd"):
        value = getattr(message, attr, None)
        if value is not None:
            entry[attr] = value

    usage = getattr(message, "usage", None)
    if usage is not None:
        entry["usage"] = usage

    content = getattr(message, "content", None)
    if isinstance(content, list):
        entry["blocks"] = [_block(b) for b in content]
    elif isinstance(content, str):
        entry["chars"] = len(content)
        entry["text"] = content

    errors = getattr(message, "errors", None)
    if errors:
        entry["errors"] = errors

    # ``SystemMessage.data``: the ``init`` message carries the CLI version,
    # model and settings the call actually ran with.
    data = getattr(message, "data", None)
    if isinstance(data, dict) and data:
        entry["data"] = data
    return entry


class TraceLog:
    """Append-only JSONL trace of one call.

    Used as a context manager so the header is written before the first message
    and the footer even when the call raises — which is the case the file is
    for.
    """

    def __init__(self, path: Path, header: dict):
        self.path = path
        self._header = header
        self._n = 0
        self._ticks = 0
        self._last_tick: dict | None = None

    def __enter__(self) -> "TraceLog":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate: a re-run of the same document replaces its trace, matching
        # the sample next to it rather than accumulating silent history.
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"record": "header",
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 **self._header},
                ensure_ascii=False, default=str) + "\n")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        footer: dict[str, Any] = {"record": "footer",
                                  "timestamp": datetime.now(timezone.utc).isoformat(),
                                  "messages": self._n,
                                  "ok": exc is None}
        if self._ticks:
            footer["thinking_ticks"] = self._ticks
            if self._last_tick:
                footer["thinking_tokens_last"] = self._last_tick
        if exc is not None:
            import traceback as tb_mod
            footer["error_type"] = exc_type.__name__
            footer["error"] = str(exc)
            footer["traceback"] = "".join(
                tb_mod.format_exception(exc_type, exc, tb))
        self._append(footer)
        return False  # never swallow: the caller decides what a failure means

    def _append(self, entry: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def message(self, message: Any) -> None:
        """Append one streamed SDK message; thinking ticks are only counted."""
        if getattr(message, "subtype", None) == THINKING_TICK:
            self._ticks += 1
            data = getattr(message, "data", None)
            if isinstance(data, dict) and data:
                self._last_tick = data
            return
        self._append(message_entry(message, self._n))
        self._n += 1


def _ignore(message: Any) -> None:
    pass


@contextmanager
def traced(path: Path | None, fields: dict,
           user_message: str) -> Iterator[Callable[[Any], None]]:
    """Trace one call to ``path``; yields the ``on_message`` callback for it.

    ``fields`` go into the header together with the user message's length and
    digest. With ``path`` ``None`` nothing is written and the callback ignores
    every message, so a caller needs no branch of its own.
    """
    if path is None:
        yield _ignore
        return
    with TraceLog(path, header_for(fields, user_message)) as log:
        yield log.message


def header_for(fields: dict, user_message: str) -> dict:
    """``fields`` plus the user message's length and digest, never its body."""
    return fields | {"user_message_chars": len(user_message),
                     "user_message_sha256_16": _digest(user_message)}


def read(path: Path) -> tuple[dict, list[dict], dict | None]:
    """Read a stored trace back as ``(header, messages, footer)``."""
    header: dict = {}
    footer: dict | None = None
    messages: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        record = entry.get("record")
        if record == "header":
            header = entry
        elif record == "footer":
            footer = entry
        else:
            messages.append(entry)
    return header, messages, footer
