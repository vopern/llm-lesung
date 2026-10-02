"""Structural guards on the adversarial prompt (docs/REDTEAM.md § 4).

No network and no Claude call. Two things can silently drift and both are
expensive: the ``Muster`` literal against the prompt's enumeration (a pattern
the model was never told about would simply never fire, and the recall number
would blame the model), and the discipline rules of § 3 — they are the
only thing standing between an adversarial persona and eight confident attacks
per bill.
"""

from typing import get_args

from backend.analysis.redteam import REDTEAM_SYSTEM_PROMPT
from backend.analysis.schema import Muster
from backend.analysis.style import STYLE_SECTION

# The seven roles of docs/REDTEAM.md § 3, worked in fixed order so the pass is
# systematic rather than free-associative.
ROLES = [
    "Der Verpflichtete",
    "Der Begünstigte",
    "Der Intermediär",
    "Der Etablierte",
    "Die vollziehende Behörde",
    "Die Eingriffsbehörde",
    "Der Verfahrensbeteiligte",
]


def test_every_muster_named_in_prompt():
    missing = [m for m in get_args(Muster) if m not in REDTEAM_SYSTEM_PROMPT]
    assert missing == []


def test_every_role_named_in_prompt():
    missing = [r for r in ROLES if r not in REDTEAM_SYSTEM_PROMPT]
    assert missing == []


def test_discipline_rules_present():
    """The five rules that make an attack falsifiable rather than a story."""
    assert "allein mit dem Wortlaut des Entwurfs begründbar" in REDTEAM_SYSTEM_PROMPT  # lawful
    assert "MUSS ein wörtliches Zitat enthalten" in REDTEAM_SYSTEM_PROMPT  # quote
    assert '„Jemand könnte" ist kein Befund' in REDTEAM_SYSTEM_PROMPT  # named actor
    assert "Übersteigt der Aufwand den Vorteil, melde nichts." in REDTEAM_SYSTEM_PROMPT  # priced
    assert "Benenne die fehlende Absicherung" in REDTEAM_SYSTEM_PROMPT  # named fix


def test_political_criticism_excluded():
    """The standing exclusion — without it the pass becomes a policy critic."""
    assert "Keine Kritik am politischen Ziel." in REDTEAM_SYSTEM_PROMPT


def test_ambiguity_needs_a_chooser():
    """An ambiguity is only an attack if the actor picks the reading.

    The recurring drift the rule answers: v1 reported a missing transitional
    provision on F3 and v2 an open question about a suspended step on F2, both
    as attacks. Neither has a winner who chooses anything — they are the Lektor
    category ``unklarheit`` (docs/REDTEAM.md § 11, run 3). The discriminator
    has to be the chooser, not the ambiguity, or it would also suppress
    ``definitionsmacht``, where the actor's own structuring decides whether the
    term applies (B2, the Beherbergung split).
    """
    assert "Eine Unklarheit ist nur dann ein Angriff" in REDTEAM_SYSTEM_PROMPT
    assert "günstige Lesart selbst herbeiführen" in REDTEAM_SYSTEM_PROMPT
    assert "wer die Lesart wählt" in REDTEAM_SYSTEM_PROMPT


def test_finding_cap_present():
    """The eight-finding cap is one of the precision mitigations (§ 9)."""
    assert "Höchstens acht Befunde" in REDTEAM_SYSTEM_PROMPT


def test_quote_must_be_contiguous():
    """No ellipsis in the quote.

    The quote check is a pure string comparison, so an elided quote is only
    ever verified in its longest fragment — 8 of the 35 findings of run 1 were
    elided and thus only partly checkable (docs/REDTEAM.md § 12). The rule
    trades nothing away: it makes the quote *more* falsifiable, not shorter.
    """
    assert "ohne jede Auslassung" in REDTEAM_SYSTEM_PROMPT
    assert "kürzeste zusammenhängende Passage" in REDTEAM_SYSTEM_PROMPT


def test_prose_bounds_present():
    """The payload bounds of § 12 no. 1, where they were measured to be needed.

    ``schritte`` was 45 % of a finding's prose at ~180 characters per step, and
    ``summary`` ran to 755-1057 characters for a "1 to 3 sentence" instruction.
    """
    assert "höchstens vier Schritte" in REDTEAM_SYSTEM_PROMPT
    assert "150 Zeichen" in REDTEAM_SYSTEM_PROMPT
    assert "höchstens drei Sätzen und höchstens 500" in REDTEAM_SYSTEM_PROMPT


def test_bounds_never_outrank_substance():
    """The bounds must stay explicitly subordinate to the discipline rules."""
    assert "Obergrenzen, keine Zielwerte" in REDTEAM_SYSTEM_PROMPT
    assert "Kürze Herleitung, nicht Nachprüfbarkeit." in REDTEAM_SYSTEM_PROMPT


# --- the flattened output schema -------------------------------------------
# The schema handed to the CLI is the other half of this pass's reliability.
# Pydantic emits ``Exploit`` as a ``$defs`` entry; leaving it there gave the
# model a tool name to decompose into, which cost turns and failed two bills
# outright (docs/REDTEAM.md § 11). These pin the flattening without a network
# call.

import json

import jsonschema
import pytest

from backend.analysis.redteam import _flatten, _output_schema
from backend.analysis.schema import Exploit, RedTeamAnalysis


def test_output_schema_has_no_refs_or_defs():
    blob = json.dumps(_output_schema())
    assert "$ref" not in blob
    assert "$defs" not in blob


def test_output_schema_drops_root_title():
    """The model mistakes a root title for a required wrapper key."""
    assert "title" not in _output_schema()


def test_flattening_preserves_the_exploit_contract():
    """Every required field and both enums must survive inlining."""
    items = _output_schema()["properties"]["exploits"]["items"]
    assert set(items["required"]) == set(Exploit.model_fields)
    assert items["additionalProperties"] is False
    assert set(items["properties"]["muster"]["enum"]) == set(get_args(Muster))


def _example() -> dict:
    return {
        "summary": "Zusammenfassung.",
        "exploits": [{
            "muster": "schwellenwert",
            "akteur": "Investor mit Co-Investor",
            "titel": "Schwelle knapp unterschritten",
            "schritte": ["Anteile aufteilen", "Haltefrist abwarten"],
            "vorteil": "3,5 % des Kaufpreises",
            "aufwand": "mittel",
            "quote": "mindestens 90 vom Hundert der Anteile",
            "fehlende_absicherung": "Zurechnung koordinierter Erwerber",
            "severity": "hoch",
        }],
    }


def test_flattened_schema_accepts_what_the_model_accepts():
    """Flattening must not change which documents validate."""
    doc = _example()
    RedTeamAnalysis.model_validate(doc)  # the Pydantic side agrees
    jsonschema.validate(doc, _output_schema())


@pytest.mark.parametrize("break_it", [
    lambda d: d["exploits"][0].pop("quote"),          # quote is mandatory here
    lambda d: d["exploits"][0].update(muster="typo"),  # enum still enforced
    lambda d: d["exploits"][0].update(extra="x"),      # additionalProperties:false
])
def test_flattened_schema_still_rejects_bad_documents(break_it):
    doc = _example()
    break_it(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _output_schema())


def test_schema_carries_no_length_constraints():
    """The prose bounds are prompt-side on purpose.

    As ``max_length``/``max_items`` they would turn a verbose answer into a
    schema violation, and the CLI answers a violation with another model
    response — spending the turn the flattened schema just bought back
    (docs/REDTEAM.md § 11).
    """
    blob = json.dumps(_output_schema())
    for keyword in ("maxLength", "maxItems", "minLength", "minItems"):
        assert keyword not in blob


def test_flatten_keeps_sibling_keys_that_override_a_ref():
    schema = {
        "$defs": {"N": {"type": "object", "description": "orig"}},
        "properties": {"a": {"$ref": "#/$defs/N", "description": "override"}},
    }
    assert _flatten(schema)["properties"]["a"] == {
        "type": "object", "description": "override",
    }


def test_shared_style_section_is_appended():
    assert REDTEAM_SYSTEM_PROMPT.endswith(STYLE_SECTION)
