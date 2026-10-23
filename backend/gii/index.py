"""GII's list of laws: slug, abbreviation and title, from the 35 Teillisten.

The list is cached as ``index.json`` under ``config.GII_DIR`` and read again
from GII only when missing or with ``refresh``. It is the candidate source of
the lazy lookup: a law's own metadata (citations, Kurztitel) is only in its zip.
"""

import html
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from backend import config
from backend.gii import client

PAGES = [f"Teilliste_{c}.html" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"]

_ENTRY = re.compile(
    r'<a href="\./(?P<slug>[^/"]+)/index\.html"><abbr title="(?P<titel>[^"]*)">'
    r"\s*(?P<abk>[^<]*?)\s*</abbr>")


@dataclass(frozen=True)
class Entry:
    slug: str
    abk: str
    titel: str


def parse(page: str) -> list[Entry]:
    return [Entry(m["slug"], html.unescape(m["abk"]), html.unescape(m["titel"]))
            for m in _ENTRY.finditer(page)]


def load(refresh: bool = False,
         fetch: Callable[[str], bytes] = client.get) -> list[Entry]:
    path = Path(config.GII_DIR) / "index.json"
    if path.exists() and not refresh:
        return [Entry(**e) for e in json.loads(path.read_text(encoding="utf-8"))]
    entries = {e.slug: e for page in PAGES
               for e in parse(fetch(page).decode("iso-8859-1"))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in entries.values()], ensure_ascii=False,
                               indent=0), encoding="utf-8")
    return list(entries.values())


def key(name: str) -> str:
    """A name compared across spelling: case, hyphenation, case endings and
    footnote marks folded. "Fünften Buches" = "Fünfte Buch"."""
    name = re.sub(r"\s*(?:\d\)|\*)$", "", name.strip())
    name = re.sub(r"-\s+", "", name.lower())
    words = re.findall(r"[\wäöüß]+", name)
    return " ".join(re.sub(r"(?:es|en|e|s|n)$", "", w) for w in words)


def abk_key(abk: str) -> str:
    """"SVG 2025" and "SVG" compare equal; so do "SGB V" and "SGB 5"."""
    roman = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7",
             "VIII": "8", "IX": "9", "X": "10", "XI": "11", "XII": "12", "XIV": "14"}
    words = [roman.get(w, w) for w in abk.replace(".", "").split()]
    if len(words) > 1 and re.fullmatch(r"(?:19|20)\d\d", words[-1]):
        words = words[:-1]
    return " ".join(words).lower()


def candidates(entries: list[Entry], abk: str | None, name: str | None) -> list[str]:
    """Slugs whose abbreviation or title matches; by abbreviation first."""
    by_abk = [e.slug for e in entries if abk and abk_key(e.abk) == abk_key(abk)]
    by_name = [e.slug for e in entries if name and key(e.titel) == key(name)]
    return list(dict.fromkeys(by_abk + by_name))
