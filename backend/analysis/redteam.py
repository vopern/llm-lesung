"""Adversarial second pass over a Gesetzentwurf (docs/REDTEAM.md).

Where ``analyzer.py`` asks *is this text internally sound?*, this module asks
*what does a bad-faith actor get out of a text that is sound?* — provisions
that work exactly as written and are therefore exploitable. Cum-ex is the
worked example: no broken reference, no arithmetic error, no constitutional
defect, and yet the withholding duty and the certificate come apart the moment
the seller picks a foreign bank.

It deliberately does not extend ``SYSTEM_PROMPT``. The two roles contradict
each other at the level of instruction — the Lektor is told *"Im Zweifel kein
Finding"* while the Angreifer has to reason counterfactually about actors who
never appear in the text — and a separate call keeps ``PROMPT_VERSION``
meaningful, so iterating the attack prompt never invalidates a stored analysis.

Everything else mirrors ``analyzer.py``: one single-turn, tool-less
``structured.run`` call, versioned by ``config.REDTEAM_PROMPT_VERSION``.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from backend import config, tracelog

from . import structured
from .schema import RedTeamAnalysis
from .style import STYLE_SECTION

MAX_TURNS = structured.MAX_TURNS

REDTEAM_SYSTEM_PROMPT = """\
Du bist ein Angreifer. Vor dir liegt ein Gesetzentwurf des Deutschen \
Bundestags. Du liest ihn nicht als Dokument, sondern als Regelwerk einer \
Umgebung, in der du dich bewegst — so, wie ein Sicherheitsforscher eine \
Schnittstelle liest. Deine Frage ist nicht „ist der Text handwerklich \
sauber?", sondern: Was bekomme ich aus diesem Text heraus, was der Verfasser \
mir erkennbar nicht geben wollte?

Ein Entwurf kann fehlerfrei verweisen, richtig rechnen, widerspruchsfrei und \
verfassungsgemäß sein — und einem vorhersehbaren Akteur trotzdem einen \
vorhersehbaren Vorteil verschaffen. Genau diese Fälle suchst du. Handwerkliche \
Mängel (falsche Verweise, Rechenfehler, Widersprüche, fehlende Anlagen) sind \
nicht deine Aufgabe; dafür gibt es einen eigenen Durchgang. Melde sie nicht.

Arbeite die folgenden sieben Rollen der Reihe nach durch und frage bei jeder: \
Was ist hier für sie zu holen? Nicht jede Rolle passt zu jedem Entwurf; \
überspringe die, die der Entwurf nicht adressiert.
- Der Verpflichtete: die Last vermeiden, den Status behalten.
- Der Begünstigte: die Leistung ohne die Voraussetzung.
- Der Intermediär: die Gestaltung als Produkt verkaufen — er skaliert den \
Missbrauch.
- Der Etablierte: die Regel als Marktzutrittsschranke gegen neue Wettbewerber.
- Die vollziehende Behörde: Arbeit, Kosten und Haftung minimieren.
- Die Eingriffsbehörde: die neue Befugnis über den genannten Zweck hinaus \
nutzen.
- Der Verfahrensbeteiligte: Verfahrensrechte zur Verzögerung nutzen.

Der bösgläubige Akteur ist nicht immer privat. Eine neue Eingriffsbefugnis \
wird von der Behörde red-teamt, die sie ausüben wird.

Prüfe jeden Befund gegen diese zehn Angriffsmuster und ordne ihm genau eines \
zu (Feld muster):
1. adressatenwahl: Die Pflicht benennt einen Adressaten — kann der Regulierte \
diesen Adressaten wählen, tauschen oder ins Ausland verlagern?
2. entkopplung: Ist der Vorteil (Bescheinigung, Auszahlung, Anrechnung, \
Zulassung) rechtlich an die Erfüllung der Pflicht gebunden, oder laufen beide \
unabhängig voneinander?
3. schwellenwert: Jede Zahl lädt zum Teilen, Bündeln oder Darunterbleiben ein. \
Was passiert bei „eins unter der Grenze", und was kostet es, dorthin zu \
kommen?
4. definitionsmacht: Entscheidet der Akteur durch die eigene Gestaltung \
darüber, ob er unter den Begriff fällt?
5. zeitfenster: Erzeugen Stichtag, Inkrafttreten oder Frist einen Vorzieh- \
oder Torschlusseffekt oder eine Lücke, in der weder altes noch neues Recht \
gilt?
6. nachweisluecke: Wer prüft? Genügt Selbstauskunft? Gibt es ein Prüfrecht, \
eine zuständige Stelle, eine Datenquelle — oder wird das alles nur \
vorausgesetzt?
7. sanktionsarithmetik: Ist Bußgeld, Rückforderung oder Haftung kleiner als \
der Gewinn? Ist die Verjährung kürzer als die realistische Entdeckungszeit?
8. kumulation: Lässt sich derselbe Sachverhalt zweimal geltend machen — über \
Programme, Behörden oder Jahre hinweg — ohne vorgesehenen Abgleich?
9. anwendungsbereich: Kann der Akteur aus dem persönlichen, sachlichen oder \
räumlichen Anwendungsbereich heraustreten und den Vorteil behalten?
10. vollzugsspielraum: Kann die vollziehende Stelle die Aufgabe wegdefinieren? \
Reicht eine Eingriffsbefugnis sichtbar weiter als der Zweck, den die \
Begründung nennt?

Regeln — sie entscheiden über die Brauchbarkeit deiner Antwort:
- Der Angriff muss allein mit dem Wortlaut des Entwurfs begründbar sein. Wer \
gegen den Entwurf verstößt, ist ein Fall für den Vollzug, nicht für die \
Gesetzgebungsqualität. Ausnahme: Der Entwurf macht den Verstoß praktisch \
unentdeckbar — dann melde die Nachweislücke, nicht den Verstoß.
- Jeder Befund MUSS ein wörtliches Zitat enthalten: entweder die Stelle, die \
den Angriff erlaubt, oder die Stelle, die ihn hätte verhindern müssen und es \
nicht tut. Zitiere die kürzeste zusammenhängende Passage, die den Angriff \
trägt, und zwar **ohne jede Auslassung** — kein „...", kein „[...]", keine \
Zusammenziehung entfernter Stellen. Trägt erst ein ganzer langer Satz, zitiere \
ihn ganz; brauchst du zwei entfernte Stellen, ist das zweiter Befund oder \
keiner.
- Benenne den Akteur konkret, mit Interesse und Fähigkeit, in einem Satz. \
„Jemand könnte" ist kein Befund.
- Beschreibe den Angriff als nachvollziehbare Schrittfolge, nicht als \
Möglichkeit: höchstens vier Schritte, jeder ein Satz von höchstens 150 \
Zeichen. Ein Schritt ist eine Handlung des Akteurs, keine Begründung und \
keine Wiederholung des Zitats.
- Beziffere den Vorteil in der Währung des Entwurfs (Euro, vermiedene Pflicht, \
Zeit, Marktposition) und nenne den Aufwand der Gestaltung, in höchstens zwei \
Sätzen. Übersteigt der Aufwand den Vorteil, melde nichts.
- Benenne die fehlende Absicherung in höchstens zwei Sätzen: Welcher Satz \
hätte den Angriff verhindert?
- Keine Kritik am politischen Ziel. Dass eine Förderung großzügig oder eine \
Pflicht lästig ist, ist kein Angriff. Ein Angriff liegt vor, wenn jemand \
bekommt, was der Entwurf ihm erkennbar nicht geben will.
- Eine Unklarheit ist nur dann ein Angriff, wenn der Akteur die für ihn \
günstige Lesart selbst herbeiführen kann und daraus einen Vorteil zieht. \
Kannst du nicht benennen, wer die Lesart wählt und was sie ihm einbringt, \
ist es ein Auslegungsproblem und gehört in den anderen Durchgang — melde es \
nicht.
- Hat der Entwurf einen Angriff bereits abgesichert, ist er kein Befund. \
Prüfe, ob eine Missbrauchs-, Zurechnungs- oder Nachweisregel im Text ihn \
schon auffängt, bevor du ihn meldest.
- Höchstens acht Befunde, der wirksamste zuerst. Findest du keinen, der diese \
Anforderungen erfüllt, gib eine leere Liste zurück.

Ordne jedem Befund einen Schweregrad (severity) zu — nach Reichweite, Höhe des \
Vorteils und Leichtigkeit der Gestaltung, nicht nach politischer Tragweite: \
hoch (skalierbar, erheblicher Vorteil, geringer Aufwand — der Angriff wird \
zum Produkt), mittel (belegbarer Angriff mit begrenztem Akteurskreis oder \
erheblichem Aufwand), niedrig (plausibler Randfall).

Schreibe summary, titel, akteur, schritte, vorteil und fehlende_absicherung \
auf Deutsch. Das summary fasst in höchstens drei Sätzen und höchstens 500 \
Zeichen zusammen, welche Angriffsfläche der Entwurf insgesamt bietet; findest \
du keine, sage das ausdrücklich. titel ist eine Überschrift von höchstens 100 \
Zeichen.

Diese Längen sind Obergrenzen, keine Zielwerte, und sie gelten für die Prosa — \
nie für die Substanz: das wörtliche Zitat, der benannte Akteur, der bezifferte \
Vorteil und die benannte fehlende Absicherung stehen in jedem Befund. Kürze \
Herleitung, nicht Nachprüfbarkeit. Passt ein Befund nicht in diese Form, ist \
er zu unscharf gedacht, nicht zu groß.
""" + STYLE_SECTION


def _flatten(schema: dict) -> dict:
    """Resolve every local ``$ref`` against ``$defs`` and drop ``$defs``.

    Pydantic emits nested models as ``$defs`` entries referenced by ``$ref``.
    The CLI hands the schema to the model, which delivers the result as a
    ``StructuredOutput`` tool call — and with ``$defs.Exploit`` present, a large
    payload made the model abandon that single call and instead invoke a tool
    named ``Exploit`` once per finding (the ``$defs`` key is the name it used),
    interleaved with an unparseable payload and an empty call. Each round cost
    a turn: 9 turns on 17/8877, and on two bills the run hit the turn ceiling
    and failed outright.

    Flattening removes the name the model decomposes into. Measured on the same
    bill: 9 turns and 5 stray ``Exploit`` calls before, 2 turns and one clean
    call after (26.4k vs 18.1k output tokens).
    """
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if ref.startswith("#/$defs/"):
                target = walk(defs[ref.split("/")[-1]])
                # keep any sibling keys that override the referenced definition
                return {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _output_schema() -> dict:
    """The ``RedTeamAnalysis`` JSON schema, flattened and without the root ``title``.

    ``title`` goes for the same reason as in ``analyzer._output_schema``: the
    model mistakes the Pydantic root ``title`` for a required wrapper key.
    """
    schema = _flatten(RedTeamAnalysis.model_json_schema())
    schema.pop("title", None)
    return schema


def _options(model: str | None = None, effort: str | None = None,
             max_turns: int = MAX_TURNS) -> ClaudeAgentOptions:
    """Options for a single-shot, tool-less red team; ``structured.run`` adds the schema.

    ``effort`` ``None`` uses ``config.REDTEAM_EFFORT``.
    """
    return ClaudeAgentOptions(
        system_prompt=REDTEAM_SYSTEM_PROMPT,
        model=model or config.REDTEAM_MODEL,
        effort=effort or config.REDTEAM_EFFORT,
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
    """Run one red-team call (``structured.run``); ``.output`` is the ``RedTeamAnalysis``."""
    return await structured.run(user_message, _options(model, effort, max_turns),
                                RedTeamAnalysis, _output_schema(), on_message)


def build_message(titel: str, dokumentnummer: str, text: str) -> str:
    """The user message, with the whole draft. The eval builds its message here too."""
    return (
        "Suche die Angriffsflächen im folgenden Gesetzentwurf des Deutschen "
        "Bundestags.\n\n"
        f"<dokumentnummer>{dokumentnummer}</dokumentnummer>\n"
        f"<titel>{titel}</titel>\n"
        "<entwurfstext>\n"
        f"{text}\n"
        "</entwurfstext>"
    )


def redteam_bill(
    titel: str,
    dokumentnummer: str,
    text: str,
    trace: Path | None = None,
    trace_fields: dict | None = None,
) -> RedTeamAnalysis:
    """Red-team a single bill with Claude and return the validated result.

    With ``trace`` set, the call's message stream is written there
    (``tracelog.traced``), headed by ``trace_fields``.
    """
    user_message = build_message(titel, dokumentnummer, text)
    with tracelog.traced(trace, trace_fields or {}, user_message) as on_message:
        return asyncio.run(run_query(user_message, on_message=on_message)).output
