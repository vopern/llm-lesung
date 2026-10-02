"""One schema-bound Claude call, with rescue — shared by Lektor and Angreifer.

The main call writes its answer as a JSON object in plain text: the system
prompt carries the schema (``format_section``), the call has no tools and no
``output_format``. ``parse_answer`` validates the text locally. The CLI's own
structured-output tool is not used for the main call: it checks the tool input
only after the fact, and of an unparseable input it keeps just the first 2048
characters — too little for a rescue.

An answer that does not validate goes to the rescue call, a second, draft-free
call (``config.RESCUE_MODEL``, schema-constrained through the CLI) that
transcribes the complete answer text into the schema. ``verify`` checks the
transcription (every free-text value verbatim in the answer, every enum value
in it, every empty list named in it, no prose of the JSON part dropped) and
rejects one that fails. A response cut off at the token limit is never
rescued.

Thinking is never rescue material: an answer the model did not write is not an
answer.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any, NamedTuple

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from pydantic import BaseModel, ValidationError

from backend import config

_log = logging.getLogger("llm_lesung.structured")

# One model response per call. The main call has no tools, so its answer is
# always its first response; the rescue call answers through the CLI's
# structured-output tool within the same limit.
MAX_TURNS = 1

# Tools the CLI offers every session even with ``tools=[]``. A call to one ends
# the single turn without an answer.
DISALLOWED_TOOLS = ["EndConversation"]

# Loads no MCP servers but those the options name (none). Without it the CLI
# offers every tool of the user's own MCP servers, ``tools=[]`` notwithstanding.
EXTRA_ARGS: dict[str, str | None] = {"strict-mcp-config": None}

# The model name of assistant messages the CLI writes itself — usage-limit and
# API-error notices ("You've hit your session limit · resets …"). They are not
# model output and must never become rescue material.
SYNTHETIC_MODEL = "<synthetic>"

# The key under which the CLI hands back a tool input it could not parse.
UNPARSED_KEY = "__unparsedToolInput"

# Adaptive thinking, with its text returned as a summary. Opus 4.7+ omits the
# text by default (signature only), which leaves a trace without the reasoning
# that was paid for. ``effort`` still sets how much the model thinks.
THINKING = {"type": "adaptive", "display": "summarized"}

FORMAT_SECTION = """

Ausgabeformat: Antworte ausschließlich mit einem einzigen JSON-Objekt nach dem \
folgenden JSON-Schema, ohne Text davor oder danach. Setze Anführungszeichen \
innerhalb von Texten als „…“; ein gerades Anführungszeichen in einem Text muss \
als \\" maskiert sein. Deine Antwort ist das JSON-Objekt selbst; danach ist \
nichts weiter zu tun.

<schema>
{schema}
</schema>
"""


def format_section(schema: dict) -> str:
    """The system-prompt section that asks for ``schema`` as a plain-text JSON object."""
    return FORMAT_SECTION.format(schema=json.dumps(schema, ensure_ascii=False))

# Text left over in the answer's JSON part after the rescued values are cut out counts as
# dropped from this length on; shorter remainders are labels and wrapper keys.
PROSE_CHARS = 40

RESCUE_SYSTEM_PROMPT = """\
Du überträgst die Ausgabe eines Analysemodells in ein vorgegebenes JSON-Schema. \
Die Ausgabe ist fertig; sie entsprach nur formal nicht dem Schema. Du analysierst \
nichts und bewertest nichts.

Regeln:
- Übernimm jeden Text Zeichen für Zeichen, einschließlich Umlauten, \
Anführungszeichen, Paragrafenzeichen und Zeilenumbrüchen. Kürze, ergänze, \
übersetze, korrigiere oder formuliere nichts um.
- Übernimm alle Einträge. Lass keinen weg, fasse keine zusammen und erfinde \
keinen hinzu.
- Ordne Angaben zu Kategorien, Mustern, Schweregrad oder Aufwand dem erlaubten \
Wert zu, der in der Ausgabe genannt ist.
- Fehlt eine Angabe, für die das Schema null erlaubt, setze null.
- Gib das Ergebnis ausschließlich über das StructuredOutput-Werkzeug zurück.
"""


class StructuredOutputError(RuntimeError):
    """A call that produced no usable structured output.

    ``attempts`` and ``session_id`` go into the error logs; the CLI's own
    session transcript is deleted after a retention period.
    """

    def __init__(self, message: str, attempts: list[dict], session_id: str | None):
        super().__init__(message)
        self.attempts = attempts
        self.session_id = session_id


class StructuredRun(NamedTuple):
    output: Any  # the validated pydantic model
    result: ResultMessage | None  # the main call's result message
    # The rescue call's tool calls (see ``AttemptLog``); on failure also the
    # main call's answer text (``answer_entry``).
    attempts: list[dict]
    rescued_by: str | None  # None or "call"
    rescue_result: ResultMessage | None  # the rescue call's result message


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part)
                         for part in content)
    return "" if content is None else str(content)


class AttemptLog:
    """Collects tool calls, their results and the text blocks of one call."""

    def __init__(self, call: str = "main") -> None:
        self.call = call
        self.attempts: list[dict] = []
        self.texts: list[str] = []
        self.stop_reasons: list[str] = []
        # Texts of the CLI's own notices (``SYNTHETIC_MODEL``), kept for the error.
        self.notices: list[str] = []
        self.session_id: str | None = None
        self._by_id: dict[str, dict] = {}

    def message(self, message: Any) -> None:
        session_id = getattr(message, "session_id", None)
        if session_id:
            self.session_id = session_id
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason and getattr(message, "model", None) is not None:
            self.stop_reasons.append(stop_reason)
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return
        if getattr(message, "model", None) == SYNTHETIC_MODEL:
            self.notices += [t for b in content if isinstance(t := getattr(b, "text", None), str)]
            return
        for block in content:
            tool_input = getattr(block, "input", None)
            name = getattr(block, "name", None)
            if name is not None and isinstance(tool_input, dict):
                entry = {
                    "call": self.call,
                    "attempt": len(self.attempts) + 1,
                    "tool": name,
                    "keys": list(tool_input),
                    "payload_chars": len(json.dumps(tool_input, ensure_ascii=False)),
                    "payload": tool_input,
                }
                self.attempts.append(entry)
                self._by_id[getattr(block, "id", "")] = entry
                continue
            tool_use_id = getattr(block, "tool_use_id", None)
            if tool_use_id in self._by_id:
                entry = self._by_id[tool_use_id]
                entry["is_error"] = bool(getattr(block, "is_error", False))
                entry["result"] = _result_text(getattr(block, "content", None))
                continue
            text = getattr(block, "text", None)
            if isinstance(text, str) and getattr(message, "model", None) is not None:
                self.texts.append(text)


def _candidates(payload: dict) -> list[Any]:
    """The payload itself, then its content after one unwrapping step.

    Every value is a candidate, not only the value of a single-key wrapper: the
    model also wraps as ``{"$PARAMETER_NAME": "response", "$PARAMETER_VALUE":
    "<result as a JSON string>"}``.
    """
    candidates: list[Any] = [payload]
    unparsed = payload.get(UNPARSED_KEY)
    if isinstance(unparsed, dict) and isinstance(unparsed.get("raw"), str):
        candidates.append(unparsed["raw"])
    else:
        candidates.extend(payload.values())
    return candidates


def recover[M: BaseModel](attempts: list[dict], model: type[M]) -> M | None:
    """The first rejected payload that is a complete ``model``, marked ``recovered``.

    Earliest first: a retry answers a format complaint, so its content is not
    better than the first answer.
    """
    for entry in attempts:
        for candidate in _candidates(entry["payload"]):
            if isinstance(candidate, str):
                try:
                    candidate = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
            try:
                result = model.model_validate(candidate)
            except ValidationError:
                continue
            entry["recovered"] = True
            return result
    return None


# --- the answer text ------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _json_texts(text: str) -> list[str]:
    """``text`` itself, the content of each code fence, and its outermost ``{…}``."""
    text = text.strip()
    found = [text, *(m.group(1).strip() for m in _FENCE.finditer(text))]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        found.append(text[start:end + 1])
    return found


def parse_answer[M: BaseModel](texts: list[str], model: type[M]) -> tuple[M | None, str]:
    """The answer as ``model``, or ``None`` and why not.

    Tries each text block, last first, then all of them joined; within one, the
    whole text, a code fence and the outermost braces, each after at most one
    unwrapping step (``_candidates``).
    """
    why = "no text in the response"
    for text in [*reversed(texts), "\n".join(texts)] if texts else []:
        for candidate in _json_texts(text):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError as exc:
                why = f"answer is not valid JSON ({exc})"
                continue
            for item in _candidates(data) if isinstance(data, dict) else [data]:
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        continue
                try:
                    return model.model_validate(item), ""
                except ValidationError as exc:
                    why = f"answer does not match the schema ({exc.error_count()} errors: " \
                          f"{exc.errors()[0]['msg']} at {'.'.join(map(str, exc.errors()[0]['loc']))})"
    return None, why


def answer_entry(log: AttemptLog) -> dict:
    """The main call's answer text, as an entry of an error's ``attempts``."""
    text = "\n".join(log.texts)
    return {"call": log.call, "attempt": 0, "tool": None, "answer_chars": len(text),
            "answer": text}


# --- rescue call ---------------------------------------------------------------

def rescue_material(log: AttemptLog) -> tuple[list[str], list[str]]:
    """``(JSON part, text around it)`` of the answer — never thinking.

    The JSON part (first ``{`` to last ``}``) is checked both ways by ``verify``;
    the text around it forward only, since prose around an answer is not part of
    it. An answer without braces is all prose.
    """
    text = "\n".join(log.texts)
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        around = [t for t in (text[:start], text[end + 1:]) if t.strip()]
        return [text[start:end + 1]], around
    return [], [t for t in log.texts if t.strip()]


def rescue_message(log: AttemptLog) -> str:
    return ("Übertrage die folgende Ausgabe unverändert in das Schema.\n\n<ausgabe>\n"
            + "\n".join(log.texts) + "\n</ausgabe>")


_ESCAPE = re.compile(r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])')
_SIMPLE = {'"': '"', "\\": "\\", "/": "/", "b": " ", "f": " ", "n": "\n", "r": "\n", "t": "\t"}


def _unescape(text: str) -> str:
    return _ESCAPE.sub(lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] == "u"
                       else _SIMPLE[m.group(1)], text)


def _normalize(text: str) -> str:
    """JSON escapes resolved (twice, for a double-encoded payload) and whitespace
    collapsed, so a value compares equal however the response wrote it."""
    return " ".join(_unescape(_unescape(text)).split())


def _empty_lists(data: Any, name: str | None = None) -> list[str]:
    """The property name of every empty list in ``data``."""
    if isinstance(data, list):
        return [name or "list"] if not data else [n for item in data for n in _empty_lists(item)]
    if isinstance(data, dict):
        return [n for key, value in data.items() for n in _empty_lists(value, key)]
    return []


def _leaves(data: Any, schema: dict, defs: dict) -> list[tuple[str, str]]:
    """``(kind, value)`` for every string in ``data``: ``enum`` or ``text``."""
    ref = schema.get("$ref", "")
    if ref.startswith("#/$defs/"):
        schema = defs[ref.split("/")[-1]]
    if isinstance(data, str):
        variants = [schema, *schema.get("anyOf", [])]
        return [("enum" if any("enum" in v for v in variants) else "text", data)]
    if isinstance(data, list):
        return [leaf for item in data for leaf in _leaves(item, schema.get("items", {}), defs)]
    if isinstance(data, dict):
        props = schema.get("properties", {})
        return [leaf for key, value in data.items()
                for leaf in _leaves(value, props.get(key, {}), defs)]
    return []


def verify(output: BaseModel, payloads: list[str], texts: list[str]) -> str | None:
    """Why ``output`` is not a faithful transcription, or ``None`` if it is.

    Forward: every free-text value is a verbatim part of the material, every enum
    value appears in it, and every empty list is named in it — an empty list
    carries no text, so a schema-required list the response never wrote would
    otherwise pass as "nothing found". Backward: no prose of the JSON part is left
    once the output's values are cut out of it, so nothing was dropped. Text around it is
    checked forward only — prose around an answer is not part of it.
    """
    material = _normalize("\n".join(payloads + texts))
    schema = type(output).model_json_schema()
    leaves = _leaves(output.model_dump(), schema, schema.get("$defs", {}))
    for kind, value in leaves:
        norm = _normalize(value)
        if kind == "text" and (not norm or norm not in material):
            return f"text not in the response: {value[:80]!r}"
        if kind == "enum" and norm.casefold() not in material.casefold():
            return f"enum value not in the response: {value!r}"
    for name in _empty_lists(output.model_dump()):
        if name not in material:
            return f"empty list not in the response: {name!r}"
    names = _names(schema) | {v for kind, v in leaves if kind == "enum"}
    values = [_normalize(v) for kind, v in leaves if kind == "text"]
    for payload in payloads:
        left = _residue(_normalize(payload), values, names)
        if left is not None:
            return f"dropped from the response: {left[:80]!r}"
    return None


def _names(schema: Any) -> set[str]:
    """Every property name in the schema, ``$defs`` included."""
    if isinstance(schema, dict):
        found = set(schema.get("properties", {})) if isinstance(schema.get("properties"), dict) else set()
        return found.union(*(_names(v) for v in schema.values()))
    if isinstance(schema, list):
        return set().union(*(_names(v) for v in schema))
    return set()


_SYNTAX = re.compile(r'[\s{}\[\]":,]+')


def _residue(material: str, values: list[str], names: set[str]) -> str | None:
    """Prose left in ``material`` once every carried value is cut out.

    Works on broken JSON too, where string boundaries cannot be trusted: what
    remains between the cut-outs should be only syntax, property names, enum
    values and literals.
    """
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            material = material.replace(value, "\x00")
    for chunk in material.split("\x00"):
        words = [w for w in _SYNTAX.split(chunk)
                 if w and w not in names and w not in ("null", "true", "false")]
        rest = " ".join(words)
        if len(rest) >= PROSE_CHARS:
            return rest
    return None


# --- the call ----------------------------------------------------------------------

def _failure(result: ResultMessage | None, error: Exception | None) -> str | None:
    """Why the call failed, or ``None`` if it ended normally."""
    if error is not None:
        return f"{type(error).__name__}: {error}"
    if result is None:
        return "Claude Agent SDK ended without a ResultMessage"
    if result.subtype != "success" or result.is_error:
        return (f"call failed ({result.subtype}): "
                f"errors={result.errors} api_error_status={result.api_error_status}")
    return None


async def _stream(prompt: str, options: ClaudeAgentOptions, log: AttemptLog,
                  on_message: Callable[[Any], None] | None
                  ) -> tuple[ResultMessage | None, Exception | None]:
    result: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            log.message(message)
            if on_message is not None:
                on_message(message)
            if isinstance(message, ResultMessage):
                result = message
    except Exception as exc:  # noqa: BLE001 — the CLI exits non-zero after an error result
        return result, exc
    return result, None


def _rescued[M: BaseModel](result: ResultMessage | None, error: Exception | None,
                           model: type[M]) -> tuple[M | None, str | None]:
    """The rescue call's structured output, validated, or ``None`` and why not."""
    reason = _failure(result, error)
    if reason is not None:
        return None, reason
    if result.structured_output is None:
        return None, "no structured output"
    try:
        return model.model_validate(result.structured_output), None
    except ValidationError as exc:
        return None, f"structured output failed validation: {exc}"


def _rescue_options(schema: dict) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=RESCUE_SYSTEM_PROMPT,
        model=config.RESCUE_MODEL,
        tools=[],
        disallowed_tools=DISALLOWED_TOOLS,
        extra_args=EXTRA_ARGS,
        max_turns=MAX_TURNS,
        thinking=THINKING,
        output_format={"type": "json_schema", "schema": schema},
    )


async def run[M: BaseModel](
    prompt: str,
    options: ClaudeAgentOptions,
    model: type[M],
    schema: dict,
    on_message: Callable[[Any], None] | None = None,
) -> StructuredRun:
    """Run one call that answers ``schema`` as plain-text JSON; rescue it if needed.

    ``options`` is a tool-less call without ``output_format``; its system prompt
    gets ``format_section(schema)`` appended here, and it thinks with
    ``THINKING`` unless it sets ``thinking`` itself. ``on_message`` sees every
    streamed message of both the main and the rescue call. Raises
    ``StructuredOutputError`` when nothing usable came back.
    """
    options = replace(options,
                      system_prompt=(options.system_prompt or "") + format_section(schema),
                      thinking=options.thinking or THINKING)
    log = AttemptLog("main")
    result, error = await _stream(prompt, options, log, on_message)
    output, why = parse_answer(log.texts, model)
    if output is not None:
        return StructuredRun(output, result, [], None, None)

    failure = _failure(result, error)
    reason = f"{failure}; {why}" if failure else why
    payloads, texts = rescue_material(log)
    if not payloads and not texts:
        notice = f"; CLI notice: {' '.join(log.notices)}" if log.notices else ""
        raise StructuredOutputError(f"{reason}{notice}", [], log.session_id) from error
    if log.stop_reasons[-1:] == ["max_tokens"]:
        raise StructuredOutputError(f"{reason}; response cut off at the token limit, not rescued",
                                    [answer_entry(log)], log.session_id) from error

    rescue_log = AttemptLog("rescue")
    rescue_result, rescue_error = await _stream(
        rescue_message(log), _rescue_options(schema), rescue_log, on_message)
    attempts = [answer_entry(log), *rescue_log.attempts]
    rescued, rescue_reason = _rescued(rescue_result, rescue_error, model)
    if rescued is None:
        rescued = recover(rescue_log.attempts, model)
    if rescued is None:
        raise StructuredOutputError(f"{reason}; rescue call failed: {rescue_reason}",
                                    attempts, log.session_id) from error
    mismatch = verify(rescued, payloads, texts)
    if mismatch is not None:
        raise StructuredOutputError(f"{reason}; rescue is not a transcription: {mismatch}",
                                    attempts, log.session_id) from error
    _log.warning("session %s: rescued by call %s after: %s",
                 log.session_id, rescue_log.session_id, reason)
    return StructuredRun(rescued, result, rescue_log.attempts, "call", rescue_result)


def record_fields(run: StructuredRun) -> dict:
    """The call metadata an eval record keeps, identical for every eval."""
    result, rescue = run.result, run.rescue_result
    costs = [getattr(r, "total_cost_usd", None) for r in (result, rescue)]
    return {
        "num_turns": getattr(result, "num_turns", None),
        "session_id": getattr(result, "session_id", None),
        "cost_usd": (sum(c for c in costs if c is not None)
                     if any(c is not None for c in costs) else None),
        "usage": getattr(result, "usage", None),
        "tool_calls": len(run.attempts),
        "rescued_by": run.rescued_by,
        "rescue_session_id": getattr(rescue, "session_id", None),
        "rescue_cost_usd": costs[1],
    }


def failure_fields(error: BaseException) -> dict:
    """What a failed call leaves in an eval's ``.failed.json``."""
    return {"session_id": getattr(error, "session_id", None),
            "attempts": getattr(error, "attempts", None)}
