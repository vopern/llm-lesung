"""Download and parse the Grundgesetz into a structured ground truth.

Source is the official consolidated XML from gesetze-im-internet.de (juris on
behalf of the BMJ) — public domain, no auth, one zip with a single XML file.
The document model is regular enough to parse without heuristics:

    <norm><metadaten><enbez>Art 5</enbez></metadaten>
      <textdaten><text><Content><P>(1) Jeder hat das Recht ...</P>...

One ``<P>`` per Absatz, prefixed ``(n)`` when the Artikel has more than one.
Section headers ("I. Die Grundrechte") arrive as their own ``<norm>`` element in
document order, so the current Abschnitt is tracked while iterating.

The ``Stand`` line is carried into the output on purpose: the GG is amended
regularly (most recently in 2025), and a model whose knowledge cutoff predates
an amendment is measured against text it could not have seen. Any score is only
interpretable together with this date.
"""

import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx

from . import config
from .normalize import split_saetze

_TIMEOUT = 60.0

# "Art 12a" -> "12a"; the enbez is the only place the article number appears.
_ENBEZ = re.compile(r"^Art\s+(\d{1,3}[a-z]?)$")

# Leading Absatz marker in the source text, e.g. "(1) Die Würde ...".
_ABSATZ_MARKER = re.compile(r"^\((\d{1,2}[a-z]?)\)\s*")


def download_gg_xml(url: str | None = None) -> bytes:
    """Fetch the GG zip and return the single XML file inside it."""
    url = url or config.GG_XML_URL
    response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise RuntimeError(f"no XML inside {url}")
        return archive.read(names[0])


# Elements that separate running text. The source relies on layout rather than
# whitespace, so `<LA>... helfe."</LA></DD></DL>Der Eid kann ...` (Art. 56) has
# no space at the boundary — concatenating blindly would glue "helfe."Der"
# together and corrupt the ground truth. Inline elements (<SP> emphasis, <pre>)
# sit *within* a sentence and must not gain a space.
_BLOCK_TAGS = {"P", "DL", "DT", "DD", "LA", "BR", "table", "tgroup", "tbody",
               "row", "entry"}


def _text_of(element: ET.Element) -> str:
    """Flatten an element's text, turning layout markup into single spaces."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag in _BLOCK_TAGS:
            parts.append(" ")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if node.tag in _BLOCK_TAGS:
            parts.append(" ")

    walk(element)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def parse_gg(xml_bytes: bytes) -> dict:
    """Parse the GG XML into ``{metadata..., "articles": [...]}``."""
    root = ET.fromstring(xml_bytes)

    stand = ""
    for kommentar in root.iterfind("norm/metadaten/standangabe/standkommentar"):
        stand = (kommentar.text or "").strip()
        break

    articles: list[dict] = []
    abschnitt = abschnitt_titel = ""

    for norm in root.iterfind("norm"):
        gliederung = norm.find("metadaten/gliederungseinheit")
        if gliederung is not None:
            abschnitt = (gliederung.findtext("gliederungsbez") or "").strip()
            abschnitt_titel = (gliederung.findtext("gliederungstitel") or "").strip()
            continue

        match = _ENBEZ.match((norm.findtext("metadaten/enbez") or "").strip())
        if not match:
            continue  # Eingangsformel, Präambel, Anhang EV, repeal markers

        content = norm.find("textdaten/text/Content")
        if content is None:
            continue

        absaetze = []
        for index, paragraph in enumerate(content.iterfind("P"), start=1):
            text = _text_of(paragraph)
            if not text:
                continue
            has_list = paragraph.find(".//DL") is not None
            marker = _ABSATZ_MARKER.match(text)
            if marker:
                nummer, text = marker.group(1), text[marker.end():]
            else:
                nummer = str(index)
            absaetze.append(
                {
                    "nr": nummer,
                    "numbered": bool(marker),
                    "has_list": has_list,
                    "text": text,
                    "saetze": [] if has_list else split_saetze(text),
                }
            )

        if not absaetze:
            continue  # fully repealed article (Art 49, 59a, 142a)

        articles.append(
            {
                "artikel": match.group(1),
                "abschnitt": abschnitt,
                "abschnitt_titel": abschnitt_titel,
                "absaetze": absaetze,
            }
        )

    return {
        "source_url": config.GG_XML_URL,
        "doknr": root.get("doknr", ""),
        "builddate": root.get("builddate", ""),
        "stand": stand,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "articles": articles,
    }


def main(argv: list[str] | None = None) -> int:
    xml_bytes = download_gg_xml()
    gg = parse_gg(xml_bytes)
    config.GG_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.GG_JSON.write_text(
        json.dumps(gg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    absaetze = sum(len(a["absaetze"]) for a in gg["articles"])
    print(
        f"{config.GG_JSON}: {len(gg['articles'])} Artikel, {absaetze} Absätze\n"
        f"Stand: {gg['stand']}"
    )
    return 0
