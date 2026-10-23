"""One law from its GII ``xml.zip``: metadata, units and their text.

A unit is what GII gives a page of its own: a §, an Artikel, an Anlage. Its id
is the page's name: ``§ 8a`` → ``__8a``, ``Art 5`` → ``art_5``, ``Art 229 § 1``
→ ``art_229__1``, ``Anlage`` → ``anlage``.

A citation is ``(year, page)`` or ``(year, "Nr. n")`` in BGBl. I; a law's own
are its Ausfertigung (``zitstelle``) and every Neubekanntmachung (``standangabe``
Neuf), which is what an Eingangsformel cites.
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

Citation = tuple[int, str]


@dataclass(frozen=True)
class Unit:
    enbez: str  # as GII labels it: "§ 3", "Art 5", "Anlage"
    id: str  # page name within the law: "__3"
    titel: str
    text: str


@dataclass(frozen=True)
class Law:
    slug: str
    amtabk: str | None
    jurabk: tuple[str, ...]
    kurzue: str | None
    langue: str | None
    citations: frozenset[Citation]
    stand: str | None  # "zuletzt geändert durch …"
    builddate: str | None
    units: tuple[Unit, ...] = field(repr=False)

    def unit(self, paragraph: str) -> Unit | None:
        """The unit a citation names: "§ 3", "Art. 5", "§ 8a"."""
        wanted = unit_id(paragraph)
        return next((u for u in self.units if u.id == wanted), None)

    def expand(self, paragraph: str) -> list[Unit]:
        """"§§ 8a bis 20b" → every unit from § 8a to § 20b; a single § → itself."""
        m = re.fullmatch(r"(§§|Art(?:t|ikel)?\.?)\s*(\S+)\s+bis\s+(\S+)", paragraph.strip())
        if not m:
            unit = self.unit(paragraph)
            if unit:
                return [unit]
            # "Art. 229" EGBGB is split into pages "Art 229 § 1", "Art 229 § 2", …
            prefix = unit_id(paragraph) + "__"
            return [u for u in self.units if u.id.startswith(prefix)]
        sign = "§" if m[1] == "§§" else "Art"
        ids = [u.id for u in self.units]
        first, last = unit_id(f"{sign} {m[2]}"), unit_id(f"{sign} {m[3]}")
        if first not in ids or last not in ids:
            return []
        i, j = ids.index(first), ids.index(last)
        return list(self.units[i:j + 1]) if i <= j else []


def unit_id(enbez: str) -> str:
    s = re.sub(r"\(.*", "", enbez).strip()
    s = re.sub(r"\s*§+\s*", "__", s)
    s = re.sub(r"^Art(?:ikel)?\.?\s*", "art_", s)
    return re.sub(r"[^a-z0-9_]", "_", s.lower().replace(" ", "_"))


_BGBL = re.compile(
    r"BGBl\.?\s*(?:(?P<year>\d{4})\s+)?(?:Teil\s+)?I\b\.?\s*"
    r"(?:S\.\s*(?P<pages>\d+(?:\s*,\s*\d+)*)|Nr\.\s*(?P<nr>\d+))")
_DATE_YEAR = re.compile(r"\b\d{1,2}\.\s*(?:[A-ZÄÖÜ][a-zäöü]+|\d{1,2}\.)\s*(\d{4})\b")


def draft_citations(fundstelle: str | None) -> frozenset[Citation]:
    """The citations of an Eingangsformel's fundstelle: "vom 20. August 2021 (BGBl. I
    S. 3932, 3958)", "vom 7. Juli 2025 (BGBl. 2025 I Nr. 131)". Empty without a year."""
    if not fundstelle:
        return frozenset()
    m = _BGBL.search(fundstelle)
    if not m:
        return frozenset()
    year = m["year"]
    if not year:
        dates = _DATE_YEAR.findall(fundstelle[:m.start()])
        year = dates[-1] if dates else None
    if not year:
        return frozenset()
    if m["nr"]:
        return frozenset({(int(year), f"Nr. {m['nr']}")})
    return frozenset((int(year), p.strip()) for p in m["pages"].split(","))


def _zitstelle(text: str) -> set[Citation]:
    """"1956, 651", "2021, 3932, 3958", "2024, Nr. 131"."""
    year, _, rest = text.partition(",")
    if not year.strip().isdigit():
        return set()
    out = set()
    for part in rest.split(","):
        part = " ".join(part.split())
        if part.isdigit():
            out.add((int(year), part))
        elif m := re.fullmatch(r"Nr\.\s*(\d+)", part):
            out.add((int(year), f"Nr. {m[1]}"))
    return out


_NEUF = re.compile(r"Bek\.\s*v\.\s*\d{1,2}\.\d{1,2}\.(\d{4})\s+I\s+(Nr\.\s*\d+|\d+)")


def _neuf(text: str) -> set[Citation]:
    """"Neugefasst durch Bek. v. 15.8.2011 I 1730"."""
    return {(int(y), " ".join(p.split())) for y, p in _NEUF.findall(text)}


def _text(el: ET.Element | None) -> str:
    """Plain text of a GII ``Content`` element: one line per P, list item and row."""
    if el is None:
        return ""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        if e.tag == "BR":
            parts.append("\n")
        elif e.tag == "DT":
            parts.append("\n")
        elif e.tag in ("DD",):
            parts.append(" ")
        elif e.tag == "entry":
            parts.append(" | ")
        if e.text and e.tag not in ("pre",):
            parts.append(e.text)
        elif e.tag == "pre" and e.text:
            parts.append(e.text)
        for child in e:
            walk(child)
        if e.tag in ("P", "row", "title"):
            parts.append("\n")
        if e.tail:
            parts.append(e.tail)

    walk(el)
    lines = (" ".join(line.split()).strip(" |") for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def parse(slug: str, xml: bytes) -> Law:
    root = ET.fromstring(xml)
    elements = root.findall("norm")
    meta = elements[0].find("metadaten") if elements else None

    def first(tag: str) -> str | None:
        el = meta.find(tag) if meta is not None else None
        return " ".join(el.text.split()) if el is not None and el.text else None

    citations: set[Citation] = set()
    stand = None
    if meta is not None:
        for zs in meta.iter("zitstelle"):
            citations |= _zitstelle(zs.text or "")
        for sa in meta.findall("standangabe"):
            typ, kommentar = sa.findtext("standtyp"), sa.findtext("standkommentar") or ""
            if typ == "Neuf":
                citations |= _neuf(kommentar)
            elif typ == "Stand" and stand is None:
                stand = " ".join(kommentar.split())

    units = []
    for element in elements:
        nm = element.find("metadaten")
        enbez = nm.findtext("enbez") if nm is not None else None
        if not enbez or enbez.strip() in ("Inhaltsübersicht", "Eingangsformel"):
            continue
        enbez = " ".join(enbez.split())
        titel = " ".join("".join(nm.find("titel").itertext()).split()) \
            if nm.find("titel") is not None else ""
        body = _text(element.find("textdaten/text/Content"))
        units.append(Unit(enbez, unit_id(enbez), titel, body))

    return Law(
        slug=slug,
        amtabk=first("amtabk"),
        jurabk=tuple(" ".join(e.text.split()) for e in meta.findall("jurabk") if e.text)
        if meta is not None else (),
        kurzue=first("kurzue"),
        langue=first("langue"),
        citations=frozenset(citations),
        stand=stand,
        builddate=root.get("builddate"),
        units=tuple(units),
    )


def load(slug: str, path: Path) -> Law:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        return parse(slug, z.read(name))
