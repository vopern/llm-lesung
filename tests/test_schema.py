"""Unit tests for the analysis schema and risk derivation (no network / no API)."""

from typing import get_args

import pytest
from pydantic import ValidationError

from backend.analysis.analyzer import derive_risk
from backend.analysis.schema import (
    RISK_BEARING_CATEGORIES,
    BillAnalysis,
    Category,
    Finding,
)


SAMPLE_ANALYSIS = {
    "summary": "Der Entwurf enthält einen fehlerhaften Verweis und einen Rechenfehler.",
    "findings": [
        {
            "severity": "hoch",
            "category": "referenz",
            "title": "Verweis auf nicht existierenden Absatz",
            "description": "§ 3 verweist auf § 5 Absatz 4, der Paragraf hat aber nur drei Absätze.",
            "quote": "wird nach Maßgabe des § 5 Absatz 4 gewährt",
        },
        {
            "severity": "mittel",
            "category": "rechenfehler",
            "title": "Summe stimmt nicht",
            "description": "Die Einzelbeträge 100 und 250 ergeben 350, im Text stehen 300.",
            "quote": "insgesamt 300 Euro (100 Euro und 250 Euro)",
        },
        {
            "severity": "niedrig",
            "category": "unklarheit",
            "title": "Unklarer Begriff",
            "description": "Der Begriff wird verwendet, aber nicht definiert.",
            "quote": None,
        },
    ],
}


def test_bill_analysis_validates_from_realistic_dict():
    analysis = BillAnalysis.model_validate(SAMPLE_ANALYSIS)
    assert analysis.summary.startswith("Der Entwurf")
    assert len(analysis.findings) == 3
    assert analysis.findings[0].severity == "hoch"
    assert analysis.findings[0].category == "referenz"
    assert analysis.findings[2].quote is None


def test_quote_may_be_none():
    finding = Finding(
        severity="niedrig",
        category="vollstaendigkeit",
        title="Fehlende Anlage",
        description="Anlage 2 wird in Bezug genommen, ist dem Entwurf aber nicht beigefügt.",
        quote=None,
    )
    assert finding.quote is None


def test_invalid_severity_rejected():
    bad = dict(SAMPLE_ANALYSIS)
    bad = {
        "summary": "x",
        "findings": [
            {
                "severity": "kritisch",  # not a valid Severity
                "category": "referenz",
                "title": "t",
                "description": "d",
                "quote": None,
            }
        ],
    }
    with pytest.raises(ValidationError):
        BillAnalysis.model_validate(bad)


def test_invalid_category_rejected():
    bad = {
        "summary": "x",
        "findings": [
            {
                "severity": "hoch",
                "category": "tippfehler",  # not a valid Category
                "title": "t",
                "description": "d",
                "quote": None,
            }
        ],
    }
    with pytest.raises(ValidationError):
        BillAnalysis.model_validate(bad)


def _finding(severity, category="referenz"):
    return Finding(
        severity=severity,
        category=category,
        title="t",
        description="d",
        quote=None,
    )


def test_derive_risk_empty_is_niedrig():
    assert derive_risk([]) == "niedrig"


def test_derive_risk_only_niedrig():
    assert derive_risk([_finding("niedrig"), _finding("niedrig")]) == "niedrig"


def test_derive_risk_mittel_beats_niedrig():
    assert derive_risk([_finding("niedrig"), _finding("mittel")]) == "mittel"


def test_derive_risk_hoch_beats_all():
    assert derive_risk([_finding("niedrig"), _finding("mittel"), _finding("hoch")]) == "hoch"


def test_constitutional_categories_validate():
    analysis = BillAnalysis.model_validate(
        {
            "summary": "x",
            "findings": [
                {
                    "severity": "hoch",
                    "category": "verfassungsrisiko",
                    "title": "Sonderrecht gegen eine bestimmte Meinung",
                    "description": "Art. 5 Abs. 2 GG: die Norm richtet sich gegen eine Meinung.",
                    "quote": "wer das Existenzrecht leugnet",
                },
                {
                    "severity": "mittel",
                    "category": "kompetenz",
                    "title": "Neue Kommunalaufgabe ohne Kostenregelung",
                    "description": "Art. 84 Abs. 1 Satz 7 GG: Aufgabe unmittelbar auf Gemeinden.",
                    "quote": "die Gemeinden stellen sicher",
                },
            ],
        }
    )
    assert [f.category for f in analysis.findings] == ["verfassungsrisiko", "kompetenz"]


def test_risk_bearing_categories_partition_category_literal():
    """Adding a ninth category must be a deliberate risk decision, not an accident."""
    assert set(get_args(Category)) - RISK_BEARING_CATEGORIES == {
        "verfassungsrisiko",
        "kompetenz",
    }
    assert RISK_BEARING_CATEGORIES <= set(get_args(Category))


def test_derive_risk_ignores_verfassungsrisiko():
    assert derive_risk([_finding("hoch", "verfassungsrisiko")]) == "niedrig"


def test_derive_risk_ignores_kompetenz():
    assert derive_risk([_finding("hoch", "kompetenz")]) == "niedrig"


def test_derive_risk_mixed_counts_only_risk_bearing():
    findings = [_finding("hoch", "verfassungsrisiko"), _finding("mittel", "referenz")]
    assert derive_risk(findings) == "mittel"
