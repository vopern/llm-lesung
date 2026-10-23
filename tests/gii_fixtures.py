"""Tiny GII laws as ``xml.zip`` files, for offline tests of ``backend.gii`` and resolution."""

import zipfile
from pathlib import Path

TEILLISTE = """\
<h1 class="headline">Gesetze / Verordnungen - Teilliste W</h1><div id="paddingLR12">
    <p><a href="./wehrpflg/index.html"><abbr title="Wehrpflichtgesetz"> WPflG </abbr></a><br />
Wehrpflichtgesetz&nbsp;&nbsp;<a href="./wehrpflg/WPflG.pdf">PDF</a> </p>
    <p><a href="./svg_2025/index.html"><abbr title="Gesetz &#252;ber die Versorgung der fr&#252;heren Soldatinnen"> SVG 2025 </abbr></a><br />
    <p><a href="./svg_alt/index.html"><abbr title="Soldatenversorgungsgesetz 1957"> SVG </abbr></a><br />
"""


def law_xml(amtabk: str, langue: str, zitstelle: str, units: list[tuple[str, str, str]],
            neuf: str | None = None, kurzue: str | None = None) -> str:
    stand = ('<standangabe><standtyp>Neuf</standtyp><standkommentar>'
             f'Neugefasst durch Bek. v. {neuf}</standkommentar></standangabe>' if neuf else "")
    head = (f'<norm doknr="X"><metadaten><jurabk>{amtabk}</jurabk><amtabk>{amtabk}</amtabk>'
            + (f"<kurzue>{kurzue}</kurzue>" if kurzue else "")
            + f'<fundstelle typ="amtlich"><periodikum>BGBl I</periodikum>'
            f'<zitstelle>{zitstelle}</zitstelle></fundstelle><langue>{langue}</langue>{stand}'
            '<standangabe><standtyp>Stand</standtyp><standkommentar>zuletzt geändert durch '
            'Art. 1 G v. 22.12.2025 I Nr. 370</standkommentar></standangabe>'
            '</metadaten><textdaten/></norm>')
    body = "".join(
        f'<norm doknr="Y"><metadaten><jurabk>{amtabk}</jurabk><enbez>{enbez}</enbez>'
        f'<titel format="XML">{titel}</titel></metadaten><textdaten><text format="XML">'
        f"<Content>{content}</Content></text></textdaten></norm>"
        for enbez, titel, content in units)
    return (f'<?xml version="1.0" encoding="UTF-8" ?><dokumente builddate="20260506174525">'
            f"{head}{body}</dokumente>")


WPFLG = law_xml("WPflG", "Wehrpflichtgesetz", "1956, 651", [
    ("Inhaltsübersicht", "", "<P>§ 1 …</P>"),
    ("§ 2", "Anwendung dieses Gesetzes", "<P>(1) Erster Absatz.</P><P>(2) Zweiter.</P>"),
    ("§ 3", "Inhalt und Dauer", "<P>(1) Die Wehrpflicht.</P><DL><DT>1.</DT><DD><LA>eins,</LA>"
     "</DD><DT>2.</DT><DD><LA>zwei.</LA></DD></DL>"),
    ("§ 8a", "A", "<P>a</P>"), ("§ 9", "B", "<P>b</P>"), ("§ 20b", "C", "<P>c</P>"),
    ("§ 45", "Bußgeld", "<P>Ordnungswidrig handelt …</P>"),
], neuf="15.8.2011 I 1730")
SVG_2025 = law_xml("SVG", "Gesetz über die Versorgung der früheren Soldatinnen",
                   "2021, 3932, 3958", [("§ 16", "Übergangsgebührnisse", "<P>(1) …</P>")],
                   kurzue="Soldatenversorgungsgesetz")
SVG_ALT = law_xml("SVG", "Soldatenversorgungsgesetz 1957", "1957, 785",
                  [("§ 16", "Alt", "<P>alt</P>")])
EGBGB = law_xml("EGBGB", "Einführungsgesetz zum Bürgerlichen Gesetzbuche", "1896, 604", [
    ("Art 229 § 1", "Eins", "<P>1</P>"), ("Art 229 § 2", "Zwei", "<P>2</P>"),
    ("Anlage", "", "<P>Tabelle</P>")])

LAWS = {"wehrpflg": WPFLG, "svg_2025": SVG_2025, "svg_alt": SVG_ALT, "bgbeg": EGBGB}


def write_zip(directory: Path, slug: str, xml: str) -> Path:
    path = directory / f"{slug}.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("BJNR000.xml", xml)
    return path


def zip_source(directory: Path, calls: list[str] | None = None):
    """A ``zip_path`` replacement serving ``LAWS``; records each slug asked for."""
    def zip_path(slug: str) -> Path:
        if calls is not None:
            calls.append(slug)
        if slug not in LAWS:
            raise RuntimeError(f"GII {slug}/xml.zip: HTTP 404")
        return write_zip(directory, slug, LAWS[slug])
    return zip_path
