"""Model selector: one cheap Claude call lists the existing §§ a draft amends or cites.

The call reads the Wortlaut only and answers in the shape of ``Selection``,
through ``structured.run`` like the Lektor. It names each law as the draft
cites it; finding the law in GII is not its job.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import ClaudeAgentOptions
from pydantic import BaseModel, Field

from backend import config, tracelog
from backend.bestandsrecht.reference import Reference
from backend.llm import structured

SYSTEM_PROMPT = """\
Du liest den Wortlaut eines Gesetzentwurfs des Deutschen Bundestags und listest \
das geltende Recht auf, das man neben dem Entwurf lesen muss, um ihn zu prüfen: \
jeden bestehenden Paragrafen, den der Entwurf ändert oder zitiert. Du prüfst den \
Entwurf nicht und bewertest nichts.

Gib je Gesetz oder Verordnung, die der Entwurf ändert oder deren Paragrafen er \
zitiert, einen Eintrag:
- gesetz: der Name, wie der Entwurf ihn nennt, im Nominativ („Wehrpflichtgesetz“, \
„Fünftes Buch Sozialgesetzbuch“).
- abk: die amtliche Abkürzung („WPflG“, „OWiG“, „SGB V“), auch wenn der Entwurf \
sie nicht nennt; null nur, wenn das Gesetz keine hat.
- fundstelle: Datum und Fundstelle aus der Eingangsformel, wörtlich („vom 15. August \
2011 (BGBl. I S. 1730)“), sonst null. Bei „in der Fassung der Bekanntmachung vom …“ \
ist es die Bekanntmachung, nie die letzte Änderung („zuletzt durch … geändert“).
- neu: true, wenn der Entwurf das Gesetz erst erlässt; es hat dann keine Paragrafen.
- paragraphen: je bestehendem Paragrafen ein Eintrag:
  - paragraph: „§ 3“, „Art. 229“, „Anlage 2“; einen Bereich so, wie der Entwurf ihn schreibt („§§ 8a bis \
20b“). Eine Aufzählung („§§ 3, 25 und 45“) wird zu einem Eintrag je Glied.
  - rolle: „geaendert“, wenn ein Änderungsbefehl den Paragrafen ändert, ersetzt, \
aufhebt oder etwas in ihn einfügt. „verwiesen“, wenn neuer Wortlaut einen \
bestehenden Paragrafen zitiert: der Text in „…“ eines Änderungsbefehls oder der \
Text eines Gesetzes, das der Entwurf neu erlässt.
  - von: bei „verwiesen“ der Paragraf, dessen neuer Wortlaut zitiert („§ 2“), sonst null.
  - beleg: die Stelle des Entwurfs, aus der du den Eintrag liest, kurz: der \
Änderungsbefehl oder die Zitierung, höchstens etwa 15 Wörter. Schreibe ein \
zusammenhängendes Stück Zeichen für Zeichen ab: nichts auslassen, nichts \
umformulieren, keine Stellen aus verschiedenen Zeilen oder Befehlen \
zusammensetzen. Ist der Befehl länger, nimm seinen Anfang mit der Paragrafenangabe.

Regeln:
- Nur bestehende Paragrafen. Fügt der Entwurf einen Paragrafen neu ein („Nach § 7 \
wird der folgende § 7a eingefügt“), gehört § 7a nicht dazu, und § 7 nur dann, \
wenn ein anderer Befehl ihn ändert: hier bezeichnet er nur die Stelle.
- Befehle zur Inhaltsübersicht („Die Angabe zu § 53 wird gestrichen“) ändern \
keinen Paragrafen.
- Eine Zitierung ohne Gesetzesnamen, auch „dieses Gesetzes“, meint das Gesetz, \
das der umgebende Änderungsbefehl ändert.
- Neben Paragrafen auch Artikel eines in Artikeln gegliederten Gesetzes \
(Grundgesetz, EGBGB) und Anlagen eines Gesetzes; nie die Artikel des Entwurfs selbst.
- Jede Verbindung aus Gesetz, Paragraf und Rolle nur einmal.
- Der Beleg steht wörtlich im Entwurf; ein Eintrag ohne solchen Beleg wird verworfen.
"""


class SelectedParagraph(BaseModel):
    paragraph: str
    rolle: Literal["geaendert", "verwiesen"]
    von: str | None = None
    beleg: str


class SelectedLaw(BaseModel):
    gesetz: str
    abk: str | None = None
    fundstelle: str | None = None
    neu: bool = False
    paragraphen: list[SelectedParagraph] = Field(default_factory=list)


class Selection(BaseModel):
    gesetze: list[SelectedLaw]


def _output_schema() -> dict:
    """The ``Selection`` schema without its root ``title`` (see ``analyzer._output_schema``)."""
    schema = Selection.model_json_schema()
    schema.pop("title", None)
    return schema


def _options(model: str | None = None, effort: str | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model or config.BESTANDSRECHT_MODEL,
        effort=effort or config.BESTANDSRECHT_EFFORT,
        tools=[],
        disallowed_tools=structured.DISALLOWED_TOOLS,
        extra_args=structured.EXTRA_ARGS,
        max_turns=structured.MAX_TURNS,
    )


def build_message(titel: str, wortlaut: str) -> str:
    return ("Liste das geltende Recht auf, das der folgende Gesetzentwurf ändert oder zitiert.\n\n"
            f"<titel>{titel}</titel>\n<wortlaut>\n{wortlaut}\n</wortlaut>")


async def run_query(user_message: str, model: str | None = None, effort: str | None = None,
                    on_message: Callable[[Any], None] | None = None) -> structured.StructuredRun:
    """One selection call (``structured.run``); ``.output`` is the ``Selection``."""
    return await structured.run(user_message, _options(model, effort), Selection,
                                _output_schema(), on_message)


def to_references(selection: Selection) -> list[Reference]:
    """One ``Reference`` per selected §; a law the draft enacts has none."""
    return [Reference(gesetz=law.gesetz, paragraph=p.paragraph, rolle=p.rolle, beleg=p.beleg,
                      abk=law.abk, fundstelle=law.fundstelle,
                      von=p.von if p.rolle == "verwiesen" else None)
            for law in selection.gesetze if not law.neu
            for p in law.paragraphen]


def references(titel: str, wortlaut: str, trace: Path | None = None,
               model: str | None = None,
               effort: str | None = None) -> tuple[list[Reference], dict]:
    """The selected references and the call's metadata (``structured.record_fields``
    plus prompt version, model and effort); the call is traced to ``trace``."""
    message = build_message(titel, wortlaut)
    settings = {"prompt_version": config.BESTANDSRECHT_PROMPT_VERSION,
                "model": model or config.BESTANDSRECHT_MODEL,
                "effort": effort or config.BESTANDSRECHT_EFFORT}
    with tracelog.traced(trace, {"pass": "bestandsrecht"} | settings, message) as on_message:
        run = asyncio.run(run_query(message, settings["model"], settings["effort"], on_message))
    return to_references(run.output), settings | structured.record_fields(run)
