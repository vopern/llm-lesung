"""The system prompt is the product core; these guard it structurally.

No network and no Claude call — the prompt is a module-level string. The one
invariant worth pinning is that the prompt and the ``Category`` literal cannot
drift apart: the prompt enumerates the categories twice (as numbered
Prüfpunkte and again in the Regeln), so a category added to the schema alone
would leave the model with a vocabulary it was never told about. The user
message is pinned too: without Beschlussempfehlungen it must not change, since
``PROMPT_VERSION`` does not track it.
"""

from typing import get_args

from backend.analysis import analyzer, structured
from backend.analysis.analyzer import SYSTEM_PROMPT, build_message
from backend.analysis.schema import Category
from backend.analysis.style import STYLE_SECTION


def test_every_category_named_in_prompt():
    missing = [c for c in get_args(Category) if c not in SYSTEM_PROMPT]
    assert missing == []


def test_category_list_in_regeln_is_complete():
    """The Regeln repeat the full list; both enumerations must agree."""
    marker = "Ordne jedem Finding genau eine Kategorie aus dieser Liste zu:"
    assert marker in SYSTEM_PROMPT
    tail = SYSTEM_PROMPT.split(marker, 1)[1].split(".", 1)[0]
    assert {c.strip() for c in tail.split(",")} == set(get_args(Category))


def test_constitutional_categories_are_gated():
    """The narrow gate on 7/8 is the guard on the 0-false-positive record."""
    assert "Diese Liste ist abschließend" in SYSTEM_PROMPT
    assert "Im Zweifel kein Finding." in SYSTEM_PROMPT


def test_shared_style_section_is_appended():
    assert SYSTEM_PROMPT.endswith(STYLE_SECTION)


# --- the user message -------------------------------------------------------

_DRAFT_ONLY = (
    "Analysiere den folgenden Gesetzentwurf des Deutschen Bundestags.\n\n"
    "<dokumentnummer>21/1</dokumentnummer>\n"
    "<titel>Titel</titel>\n"
    "<entwurfstext>\n"
    "Entwurf.\n"
    "</entwurfstext>"
)


def test_user_message_without_context_is_the_draft_alone():
    assert build_message("Titel", "21/1", "Entwurf.") == _DRAFT_ONLY
    assert build_message("Titel", "21/1", "Entwurf.", []) == _DRAFT_ONLY


def test_user_message_appends_beschlussempfehlungen_verbatim_in_order():
    be_text = "Artikel 1 Nummer 2 wird wie folgt gefasst:\n  „§ 3 <neu>“"
    message = build_message(
        "Titel", "21/1", "Entwurf.", [("21/5", be_text), ("21/9", "Zweite.")]
    )
    assert message.startswith(_DRAFT_ONLY + "\n\n" + analyzer.BESCHLUSSEMPFEHLUNG_NOTICE)
    first = f'<beschlussempfehlung nummer="21/5">\n{be_text}\n</beschlussempfehlung>'
    second = '<beschlussempfehlung nummer="21/9">\nZweite.\n</beschlussempfehlung>'
    assert first in message and second in message
    assert message.index(first) < message.index(second)
    assert message.endswith(second)


def test_user_message_appends_bestandsrecht_after_beschlussempfehlungen():
    excerpts = [("AufenthG", "§ 44a", "2025-06-23", "§ 44a Titel\n(1) Satz."),
                ("StAG", "§ 10", "2025-06-23", "§ 10 Titel")]
    assert build_message("Titel", "21/1", "Entwurf.", None, []) == _DRAFT_ONLY
    message = build_message("Titel", "21/1", "Entwurf.", [("21/5", "BE.")], excerpts)
    be = '<beschlussempfehlung nummer="21/5">\nBE.\n</beschlussempfehlung>'
    first = ('<geltende-fassung gesetz="AufenthG" norm="§ 44a" stand="2025-06-23">\n'
             "§ 44a Titel\n(1) Satz.\n</geltende-fassung>")
    second = '<geltende-fassung gesetz="StAG" norm="§ 10" stand="2025-06-23">\n§ 10 Titel\n</geltende-fassung>'
    assert message.index(be) < message.index(analyzer.BESTANDSRECHT_NOTICE) < message.index(first)
    assert message.index(first) < message.index(second) and message.endswith(second)
    alone = build_message("Titel", "21/1", "Entwurf.", bestandsrecht=excerpts)
    assert alone.startswith(_DRAFT_ONLY + "\n\n" + analyzer.BESTANDSRECHT_NOTICE)
    assert analyzer.BESCHLUSSEMPFEHLUNG_NOTICE not in alone


def test_analyzer_never_truncates(monkeypatch):
    sent = []

    async def _fake(user_message, on_message=None):
        sent.append(user_message)
        return structured.StructuredRun(None, None, [], None, None)

    monkeypatch.setattr(analyzer, "run_query", _fake)
    text = "x" * (analyzer.MAX_INPUT_CHARS + 10)
    analyzer.analyze_bill("Titel", "21/1", text)
    assert text in sent[0]
    assert not hasattr(analyzer, "TRUNCATION_NOTICE")
