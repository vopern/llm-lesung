"""Claude-based analysis of a Gesetzentwurf (Contract 3).

One single-turn Claude Agent SDK call per bill (``structured.run``) returns a
``BillAnalysis`` written as plain-text JSON and validated locally, rescued when
it does not validate. The SDK drives the bundled Claude Code CLI, so authentication uses whatever Claude Code is logged in with (a claude.ai
subscription via ``claude login``, or ``ANTHROPIC_API_KEY`` if set). The system
prompt is the product core: a versioned German instruction (see
``config.PROMPT_VERSION``) that turns Claude into a systematic legal proofreader.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from backend import config, tracelog

from . import structured
from .schema import RISK_BEARING_CATEGORIES, BillAnalysis, Finding, Severity
from .style import STYLE_SECTION

# Upper bound on the summed characters of all input documents (Gesetzentwurf
# plus Beschlussempfehlungen): 500k tokens of Drucksache text at the measured
# 2.0 chars/token, leaving the rest of the 1M window for prompt, thinking and
# output. Inputs over it are skipped by the pipeline, never truncated — a cut
# document yields confident false negatives on the missing part.
MAX_INPUT_CHARS = 1_000_000

MAX_TURNS = structured.MAX_TURNS

# Placed between the Entwurf and its Beschlussempfehlungen: how the two relate
# and where findings and quotes may come from.
BESCHLUSSEMPFEHLUNG_NOTICE = (
    "Zu diesem Entwurf liegt die Beschlussempfehlung des federführenden "
    "Ausschusses vor. Eine Beschlussempfehlung ÄNDERT den Entwurf und geht ihm "
    "vor: Prüfe den Entwurf in der Fassung der Beschlussempfehlung. Fehler "
    "können auch in den Maßgaben der Beschlussempfehlung selbst stecken. Benenne "
    "bei Befunden, die sich auf die Beschlussempfehlung beziehen, dies "
    "ausdrücklich mit ihrer Drucksachennummer; quote darf dann wörtlich aus der "
    "Beschlussempfehlung stammen. Melde keine Mängel des Entwurfs, die eine "
    "Maßgabe der Beschlussempfehlung bereits behebt."
)

# Placed before the excerpts of existing law the draft amends or cites: what
# they are for and what may not be concluded from them.
BESTANDSRECHT_NOTICE = (
    "Es folgen Auszüge aus dem geltenden Recht, das der Entwurf ändert oder in "
    "Bezug nimmt, jeweils mit dem Stand, den der Auszug wiedergibt. Prüfe jeden "
    "Änderungsbefehl und jede Verweisung des Entwurfs gegen diesen Wortlaut: Gibt "
    "es die angesprochene Gliederungseinheit, steht dort die zu ersetzende "
    "Angabe, kollidieren Einfügungen und Umnummerierungen? Frage auch, welche "
    "bestehenden Verweisungen ins Leere gehen und welche unveränderten Vorschriften "
    "durch den Entwurf ihren Anwendungsbereich ändern. Die Auszüge sind eine "
    "Auswahl: Melde nichts, was nur daraus folgt, dass eine Vorschrift hier nicht "
    "abgedruckt ist. quote stammt weiterhin wörtlich aus dem Entwurf."
)

SYSTEM_PROMPT = """\
Du bist ein erfahrener juristischer Lektor für Gesetzentwürfe des Deutschen \
Bundestags. Prüfe den Entwurf auf handwerkliche Fehler und klar \
benennbare verfassungs- und kompetenzrechtliche Defekte. Der Regelungstext \
(Artikel, Änderungsbefehle, neu gefasste Vorschriften) hat Vorrang: Prüfe ihn \
zuerst und am gründlichsten. Fehler nur in Begründung, Vorblatt oder \
Erfüllungsaufwand sind nachrangig und in der Regel niedrig.

Prüfe systematisch und in dieser Reihenfolge auf:
1. Fehlerhafte oder ins Leere gehende Verweise auf Paragrafen, Absätze, \
Nummern, Sätze, Anlagen oder andere Gesetze (Kategorie: referenz). Prüfe jeden \
Verweis gegen die neue Fassung der Vorschrift: Verschiebt, streicht oder \
vertauscht der Entwurf Absätze, Sätze oder Nummern, vergibt er eine \
Paragrafennummer doppelt, regelt die Zielstelle, wofür sie zitiert wird?
2. Widersprüche zwischen Regelungstext und Begründung oder innerhalb des \
Regelungstextes (Kategorie: widerspruch).
3. Rechenfehler in Beträgen, Prozentsätzen und Summen (Kategorie: \
rechenfehler).
4. Unmögliche oder widersprüchliche Daten und Fristen, etwa Inkrafttreten vor \
der Verkündung (Kategorie: datum).
5. Unvollständigkeit — in Bezug genommene, aber fehlende Anlagen, nicht \
definierte, aber verwendete Begriffe sowie Regelungen, die der Entwurf selbst \
voraussetzt, aber nicht trifft (Kategorie: vollstaendigkeit).
6. Erhebliche Mehrdeutigkeit mit praktischen Folgen für die Anwendung \
(Kategorie: unklarheit).
7. Materiell-verfassungsrechtliche Defekte — nur, wenn ein benannter \
Prüfmaßstab aus einer dieser drei Gruppen konkret ausgelöst ist: \
(a) Grundrechtseingriff ohne tragfähige gesetzliche Grundlage: \
Wesentlichkeitsvorbehalt, Bestimmtheitsgebot, Zitiergebot, Sonderrecht gegen \
eine bestimmte Meinung (Art. 5 Abs. 2 GG), Ungleichbehandlung vergleichbarer \
Fälle ohne erkennbaren Grund; \
(b) rechtsstaatliche Garantien: Rückwirkung, Entzug einer Rechtsposition ohne \
Entschädigungs- oder Übergangsregelung, Umkehr der Beweislast zulasten des \
Betroffenen, erneute Verfolgung derselben Tat (Art. 103 Abs. 3 GG), \
Rechtsweggarantie (Art. 19 Abs. 4 GG); \
(c) Haushaltsverfassung: Vorherigkeit, Jährlichkeit und Jährigkeit, \
Notlagenkredite ohne Veranlassungszusammenhang (Art. 109, 110, 115 GG). \
Diese Liste ist abschließend (Kategorie: verfassungsrisiko).
8. Kompetenz- und Bund-Länder-Defekte: fehlende oder erkennbar nicht tragende \
Gesetzgebungskompetenz (Art. 70 ff. GG), Übertragung neuer Aufgaben oder Kosten \
auf Länder oder Kommunen ohne Kosten- oder Konnexitätsregelung, \
Aufgabenübertragung unmittelbar auf Gemeinden (Art. 84 Abs. 1 Satz 7 GG), im \
Vorblatt verneinte Zustimmungsbedürftigkeit trotz zustimmungsauslösender \
Regelung, Verteilung von Bundesmitteln nach Kriterien, die vergleichbare Länder \
ohne erkennbaren Grund ausschließen (Kategorie: kompetenz).

Zwei weitere Durchgänge ohne eigene Kategorie; ordne ihre Befunde in 1 bis 8 \
ein:
9. Was fehlt? Prüfe auf Regelungen, die Entwürfe dieses Typs regelmäßig \
enthalten: bei Eingriffen in laufende Rechtsverhältnisse eine \
Übergangs- oder Stichtagsregelung, bei neuen Aufgaben für Länder oder Kommunen \
eine Kosten- oder Konnexitätsregelung, bei neuen Eingriffsbefugnissen \
Schwellen, Fristen und Rechtsschutz. Erweitert, verengt, streicht oder \
benennt der Entwurf einen Begriff, Anwendungsbereich oder eine Befugnis um: \
Sind parallele Vorschriften, Verweise, Anwendungs- und Übergangsregeln \
angepasst?
10. Welche Kritik steht bereits im Dokument? Stellungnahmen von Bundesrat und \
Bundesregierung, Gegenäußerung, Bericht des Normenkontrollrats, abgedruckte \
Gutachten. Melde einen dort erhobenen Einwand nur, wenn er \
einen konkreten Mangel betrifft, den der Regelungstext nicht ausräumt; eine Gegenäußerung, die den Einwand lediglich bestreitet, räumt \
ihn nicht aus. Zitiere dann die betroffene Stelle des Regelungstextes und \
nenne den Einwand in der description.

Regeln:
- Melde nur konkrete, belegbare Probleme. Jedes Finding MUSS ein wörtliches \
Zitat (quote) aus dem Entwurfstext enthalten, das das Problem belegt; nur wenn \
das Problem ausdrücklich das Fehlen einer Stelle betrifft, darf quote null sein \
— zitiere auch dann die Stelle, die die Lücke erzeugt, sofern es eine gibt.
- Keine politischen oder inhaltlichen Bewertungen, keine Stilkritik.
- Für verfassungsrisiko und kompetenz gilt zusätzlich: Benenne den ausgelösten \
Prüfmaßstab im ersten Satz der description; quote darf hier nicht null sein. \
Verboten sind allgemeine Verhältnismäßigkeitsprosa, politische Bewertung und \
Wendungen wie „könnte verfassungsrechtlich angegriffen werden“ ohne benannten \
Prüfmaßstab. Eine politisch umstrittene, aber verfassungsrechtlich vertretbare \
Entscheidung des Gesetzgebers ist kein Finding. Im Zweifel kein Finding.
- Ordne jedem Finding genau eine Kategorie aus dieser Liste zu: referenz, \
widerspruch, rechenfehler, datum, vollstaendigkeit, unklarheit, \
verfassungsrisiko, kompetenz. Ein handwerklicher Mangel bleibt in seiner \
Kategorie 1 bis 6, auch wenn er zugleich verfassungsrechtlich bedenklich ist; 7 \
und 8 sind für Defekte, die sich nur verfassungs- oder kompetenzrechtlich \
beschreiben lassen. Betrifft eine Ungleichbehandlung das Verhältnis von Bund zu \
Ländern oder Kommunen, gilt kompetenz. Melde denselben Mangel nur einmal.
- Ordne jedem Finding genau einen Schweregrad (severity) zu: hoch (klarer, \
gravierender Fehler mit praktischen Folgen), mittel (belegbares Problem mit \
begrenzter Tragweite), niedrig (kleinerer oder unsicherer Befund). Bei \
verfassungsrisiko und kompetenz richtet sich der Schweregrad nach der \
Eindeutigkeit des ausgelösten Prüfmaßstabs, nicht nach der politischen \
Tragweite.
- Findest du nichts, gib eine leere Findings-Liste zurück und sage das im \
summary.
- Schreibe auf Deutsch; das summary fasst die Gesamteinschätzung in 1 bis 3 \
Sätzen zusammen.
""" + STYLE_SECTION


def _output_schema() -> dict:
    """The ``BillAnalysis`` JSON schema without the root ``title``.

    Pydantic stamps the class name as the schema's root ``title``; the model
    routinely mistakes it for a required wrapper key and returns
    ``{"BillAnalysis": {...}}``, which fails validation and burns retries.
    ``title`` is annotation-only, so dropping it changes nothing else.
    """
    schema = BillAnalysis.model_json_schema()
    schema.pop("title", None)
    return schema


def _options(model: str | None = None, effort: str | None = None,
             max_turns: int = MAX_TURNS) -> ClaudeAgentOptions:
    """Options for a single-shot, tool-less analysis; ``structured.run`` adds the schema.

    ``effort`` ``None`` uses ``config.ANALYSIS_EFFORT``.
    """
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model or config.ANALYSIS_MODEL,
        effort=effort or config.ANALYSIS_EFFORT,
        tools=[],  # pure text analysis — no filesystem/web/bash access
        disallowed_tools=structured.DISALLOWED_TOOLS,
        extra_args=structured.EXTRA_ARGS,
        max_turns=max_turns,
    )


async def run_query(
    user_message: str,
    model: str | None = None,
    on_message: Callable[[Any], None] | None = None,
    effort: str | None = None,
    max_turns: int = MAX_TURNS,
) -> structured.StructuredRun:
    """Run one analysis call (``structured.run``); ``.output`` is the ``BillAnalysis``.

    ``on_message`` sees every streamed message as it arrives, so a caller can
    keep a trace of a call that never returns a result.
    """
    return await structured.run(user_message, _options(model, effort, max_turns), BillAnalysis,
                                _output_schema(), on_message)


def build_message(
    titel: str,
    dokumentnummer: str,
    text: str,
    context_docs: list[tuple[str, str]] | None = None,
    bestandsrecht: list[tuple[str, str, str, str]] | None = None,
) -> str:
    """The user message: the Entwurf, each Beschlussempfehlung, then existing law, verbatim.

    ``context_docs`` is a list of ``(dokumentnummer, text)`` in the order the
    Beschlussempfehlungen were issued; ``bestandsrecht`` a list of
    ``(gesetz, norm, stand, text)`` excerpts. Without either, the message is
    the Entwurf alone. The pipeline and the eval harness both build their
    message here, so an eval measures the shipped input.
    """
    message = (
        "Analysiere den folgenden Gesetzentwurf des Deutschen Bundestags.\n\n"
        f"<dokumentnummer>{dokumentnummer}</dokumentnummer>\n"
        f"<titel>{titel}</titel>\n"
        "<entwurfstext>\n"
        f"{text}\n"
        "</entwurfstext>"
    )
    if context_docs:
        blocks = "".join(
            f'\n\n<beschlussempfehlung nummer="{nummer}">\n{be_text}\n</beschlussempfehlung>'
            for nummer, be_text in context_docs
        )
        message = f"{message}\n\n{BESCHLUSSEMPFEHLUNG_NOTICE}{blocks}"
    if bestandsrecht:
        blocks = "".join(
            f'\n\n<geltende-fassung gesetz="{gesetz}" norm="{norm}" stand="{stand}">'
            f"\n{norm_text}\n</geltende-fassung>"
            for gesetz, norm, stand, norm_text in bestandsrecht
        )
        message = f"{message}\n\n{BESTANDSRECHT_NOTICE}{blocks}"
    return message


def analyze_bill(
    titel: str,
    dokumentnummer: str,
    text: str,
    context_docs: list[tuple[str, str]] | None = None,
    trace: Path | None = None,
    trace_fields: dict | None = None,
) -> BillAnalysis:
    """Analyze a single bill with Claude and return the validated result.

    ``context_docs`` are the bill's Beschlussempfehlungen as
    ``(dokumentnummer, text)``. Texts are sent whole; the caller keeps their sum
    within ``MAX_INPUT_CHARS``. With ``trace`` set, the call's message stream is
    written there (``tracelog.traced``), headed by ``trace_fields``.
    """
    user_message = build_message(titel, dokumentnummer, text, context_docs)
    with tracelog.traced(trace, trace_fields or {}, user_message) as on_message:
        return asyncio.run(run_query(user_message, on_message=on_message)).output


def derive_risk(findings: list[Finding]) -> Severity:
    """Derive a bill's overall risk from its risk-bearing findings.

    Only findings whose category is in ``RISK_BEARING_CATEGORIES`` count;
    ``verfassungsrisiko`` and ``kompetenz`` are reported but never raise the
    headline risk (docs/RECALL_IMPROVEMENT.md, M1).

    ``hoch`` if any counting finding is ``hoch``, else ``mittel`` if any is
    ``mittel``, else ``niedrig`` — including the no-findings case and the case
    of purely constitutional findings.
    """
    severities = {
        f.severity for f in findings if f.category in RISK_BEARING_CATEGORIES
    }
    if "hoch" in severities:
        return "hoch"
    if "mittel" in severities:
        return "mittel"
    return "niedrig"
