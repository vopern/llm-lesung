"""Pydantic models for the Claude analysis of a Gesetzentwurf.

These are the structured-output contract (Contract 3): Claude returns a
``BillAnalysis`` whose findings use the fixed German severity/category
vocabulary, so the pipeline can store them verbatim in the ``findings`` table.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Severity of a single finding and, by extension, the bill's overall risk.
Severity = Literal["hoch", "mittel", "niedrig"]

# The kind of drafting problem a finding describes.
Category = Literal[
    "referenz",  # fehlerhafte/ins Leere gehende Verweise
    "widerspruch",  # widersprüchliche Formulierungen
    "rechenfehler",  # Rechenfehler in Beträgen/Prozenten/Summen
    "datum",  # unmögliche/inkonsistente Daten und Fristen
    "vollstaendigkeit",  # fehlende Anlagen/Begriffe, vorausgesetzte, aber fehlende Regelungen
    "unklarheit",  # erhebliche Mehrdeutigkeit mit praktischen Folgen
    "verfassungsrisiko",  # materiell-verfassungsrechtlicher Defekt
    "kompetenz",  # Gesetzgebungskompetenz, Bund/Länder, Konnexität
]

# The categories that count toward a bill's headline risk. The two
# constitutional categories are deliberately absent: they are reported but must
# not turn a bill red — practically every bill touches some Grundrecht, and a
# wrong constitutional hint costs far more than a wrong reference hint
# (docs/RECALL_IMPROVEMENT.md, M1). A category added later is non-risk-bearing
# until it is listed here on purpose.
RISK_BEARING_CATEGORIES: frozenset[str] = frozenset(
    {"referenz", "widerspruch", "rechenfehler", "datum", "vollstaendigkeit", "unklarheit"}
)


class Finding(BaseModel):
    """A single, concrete, evidence-backed drafting problem."""

    # extra="forbid" puts additionalProperties:false into the JSON schema,
    # which the structured-output enforcement requires on every object.
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    category: Category
    title: str  # kurze deutsche Überschrift
    description: str  # deutsche Erläuterung, konkret, mit Bezug auf die Fundstelle
    quote: str | None  # wörtliches Zitat aus dem Entwurfstext (oder None)


class BillAnalysis(BaseModel):
    """The full result of analyzing one bill."""

    model_config = ConfigDict(extra="forbid")

    summary: str  # 1-3 Sätze Gesamteinschätzung auf Deutsch
    findings: list[Finding]


# The attack patterns the adversarial pass (docs/REDTEAM.md) works through.
# Generic move classes: each is a question about the structure of a rule, not
# about its subject matter, so the taxonomy has to survive bills it was not
# built from.
Muster = Literal[
    "adressatenwahl",  # der Pflichtige kann den Adressaten wählen/tauschen/verlagern
    "entkopplung",  # Vorteil und Pflicht laufen rechtlich unabhängig voneinander
    "schwellenwert",  # jede Zahl lädt zum Teilen, Bündeln, Darunterbleiben ein
    "definitionsmacht",  # der Akteur bestimmt selbst, ob er unter den Begriff fällt
    "zeitfenster",  # Stichtag/Frist erzeugt Vorzieh-, Torschluss- oder Lückeneffekt
    "nachweisluecke",  # niemand prüft; Selbstauskunft genügt; keine Datenquelle
    "sanktionsarithmetik",  # Sanktion kleiner als Gewinn, Verjährung kürzer als Entdeckung
    "kumulation",  # derselbe Sachverhalt mehrfach abgerechnet, kein Abgleich
    "anwendungsbereich",  # aus dem Anwendungsbereich heraus, Vorteil behalten
    "vollzugsspielraum",  # Behörde definiert die Aufgabe weg / Befugnis reicht weiter als Zweck
]


class Exploit(BaseModel):
    """One lawful, priced attack a named actor can run on the draft as written.

    Unlike a ``Finding``, ``quote`` is mandatory: the Lektor may report a
    missing provision with no text to point at, but an attack without a textual
    anchor is a story (docs/REDTEAM.md § 3).
    """

    model_config = ConfigDict(extra="forbid")

    # The prose bounds below live in the prompt, deliberately not in the schema
    # as ``max_length``/``max_items``: a hard bound turns a verbose answer into
    # a schema violation, and the CLI answers a violation with another model
    # response — the very turn the flattened schema just bought back.
    muster: Muster
    akteur: str  # Rolle + Interesse + Fähigkeit, ein Satz
    titel: str  # kurze deutsche Überschrift, <= 100 Zeichen
    schritte: list[str]  # Schrittfolge: <= 4 Schritte à <= 150 Zeichen
    vorteil: str  # was herausgezogen wird, in der Währung des Entwurfs; <= 2 Sätze
    aufwand: Literal["niedrig", "mittel", "hoch"]  # Aufwand der Gestaltung
    quote: str  # wörtliches Zitat, zusammenhängend und ohne Auslassung
    fehlende_absicherung: str  # welcher Satz hätte den Angriff verhindert; <= 2 Sätze
    severity: Severity


class RedTeamAnalysis(BaseModel):
    """The full result of red-teaming one bill."""

    model_config = ConfigDict(extra="forbid")

    summary: str  # 1-3 Sätze Gesamteinschätzung auf Deutsch
    exploits: list[Exploit]
