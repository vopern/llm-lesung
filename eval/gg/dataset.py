"""Build the GG-recall test set from the parsed Grundgesetz.

Three item kinds, all with mechanically checkable ground truth:

``zitat``        citation -> verbatim Absatz (or Satz). The task as asked for.
``reverse``      verbatim phrase -> which Artikel. Harder, and closer to what
                 the analyzer actually needs: recognising which citation a text belongs to.
``nonexistent``  a citation that does not exist ("Artikel 5 Absatz 4"). The
                 only correct answer is an abstention. This is the adversarial
                 half: a model that invents a plausible Absatz here is the same
                 model that invents a ``verfassungsrisiko`` finding.

Items are stratified by how often real Bundestag bills cite the article. The
weights come from the pipeline's own PDF cache, so "hot" means "an article the
LLM-Lesung actually meets", not "an article that is famous". Recall on hot
articles is the number that matters for the product; the cold stratum is where
models differ.
"""

import argparse
import collections
import json
import random
import re
from pathlib import Path

from . import config
from .normalize import ABSTENTION

# An "Artikel N" mention counts as a GG citation only when a GG marker appears
# in the same neighbourhood — bills cite Artikel of many other laws.
_ARTICLE_MENTION = re.compile(r"\bArt(?:\.|ikel)\s*(\d{1,3}\s*[a-z]?)\b")
_GG_MARKER = re.compile(r"\bGrundgesetz|\bGG\b")
_CONTEXT_CHARS = 160

# Corpus-citation thresholds for the three strata.
HOT_MIN = 10
WARM_MIN = 1

# Shortest Absatz / Satz worth asking about; one-liners like Art. 102 are
# trivially memorised and carry no signal.
MIN_ABSATZ_CHARS = 90
MIN_SATZ_CHARS = 60

SYSTEM_PROMPT_ABSTAIN = f"""\
Du beantwortest Fragen zum Grundgesetz für die Bundesrepublik Deutschland \
ausschließlich aus deinem Gedächtnis. Du hast keine Hilfsmittel und \
recherchierst nicht.

Antworte ausschließlich im Format:
ANTWORT: <Text>

Wenn du den Wortlaut nicht sicher erinnerst oder die genannte Vorschrift nicht \
existiert, antworte genau:
ANTWORT: {ABSTENTION}

Rate nicht. Keine Einleitung, keine Begründung, keine Anführungszeichen, keine \
Absatz- oder Satznummer im Antworttext.
"""

SYSTEM_PROMPT_FORCED = """\
Du beantwortest Fragen zum Grundgesetz für die Bundesrepublik Deutschland \
ausschließlich aus deinem Gedächtnis. Du hast keine Hilfsmittel und \
recherchierst nicht.

Antworte ausschließlich im Format:
ANTWORT: <Text>

Gib immer deine beste Antwort, auch wenn du unsicher bist. Keine Einleitung, \
keine Begründung, keine Anführungszeichen, keine Absatz- oder Satznummer im \
Antworttext.
"""


def count_gg_citations(cache_dir: Path) -> dict[str, int]:
    """Per GG article, in how many cached Drucksachen it is cited.

    Document frequency, not raw count: one bill citing Art. 74 forty times
    should not outweigh forty bills citing it once.
    """
    counts: collections.Counter[str] = collections.Counter()
    if not cache_dir.is_dir():
        return {}
    for path in sorted(cache_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        seen = set()
        for match in _ARTICLE_MENTION.finditer(text):
            context = text[match.start() : match.end() + _CONTEXT_CHARS]
            if _GG_MARKER.search(context):
                seen.add(re.sub(r"\s+", "", match.group(1)).lower())
        counts.update(seen)
    return dict(counts)


def stratum_of(citations: int) -> str:
    if citations >= HOT_MIN:
        return "hot"
    if citations >= WARM_MIN:
        return "warm"
    return "cold"


def _citation(artikel: str, absatz: str | None, satz: int | None) -> str:
    parts = [f"Artikel {artikel}"]
    if absatz:
        parts.append(f"Absatz {absatz}")
    if satz:
        parts.append(f"Satz {satz}")
    return " ".join(parts) + " des Grundgesetzes"


def _zitat_items(gg: dict, weights: dict[str, int]) -> list[dict]:
    """One item per Absatz, plus one per Satz where the split is unambiguous."""
    items = []
    for article in gg["articles"]:
        artikel = article["artikel"]
        citations = weights.get(artikel.lower(), 0)
        common = {
            "kind": "zitat",
            "artikel": artikel,
            "abschnitt": article["abschnitt"],
            "abschnitt_titel": article["abschnitt_titel"],
            "corpus_citations": citations,
            "stratum": stratum_of(citations),
        }
        for absatz in article["absaetze"]:
            nummer = absatz["nr"] if absatz["numbered"] else None
            if len(absatz["text"]) >= MIN_ABSATZ_CHARS:
                items.append(
                    {
                        **common,
                        "id": f"zitat-{artikel}-{nummer or '0'}",
                        "unit": "absatz",
                        "absatz": nummer,
                        "satz": None,
                        "citation": _citation(artikel, nummer, None),
                        "expected": absatz["text"],
                    }
                )
            # Satz-level items only where the splitter is confident: no list
            # markup, several sentences, none of them suspiciously short.
            saetze = absatz["saetze"]
            if absatz["has_list"] or len(saetze) < 2:
                continue
            if any(len(s) < MIN_SATZ_CHARS for s in saetze):
                continue
            for index, satz in enumerate(saetze, start=1):
                items.append(
                    {
                        **common,
                        "id": f"zitat-{artikel}-{nummer or '0'}-s{index}",
                        "unit": "satz",
                        "absatz": nummer,
                        "satz": index,
                        "citation": _citation(artikel, nummer, index),
                        "expected": satz,
                    }
                )
    return items


def _reverse_items(gg: dict, weights: dict[str, int]) -> list[dict]:
    """Verbatim Absatz -> which Artikel. Expected answer is the article number."""
    items = []
    for article in gg["articles"]:
        artikel = article["artikel"]
        citations = weights.get(artikel.lower(), 0)
        for absatz in article["absaetze"]:
            if len(absatz["text"]) < MIN_ABSATZ_CHARS:
                continue
            nummer = absatz["nr"] if absatz["numbered"] else None
            items.append(
                {
                    "id": f"reverse-{artikel}-{nummer or '0'}",
                    "kind": "reverse",
                    "unit": "absatz",
                    "artikel": artikel,
                    "absatz": nummer,
                    "satz": None,
                    "abschnitt": article["abschnitt"],
                    "abschnitt_titel": article["abschnitt_titel"],
                    "corpus_citations": citations,
                    "stratum": stratum_of(citations),
                    "citation": _citation(artikel, nummer, None),
                    "quote": absatz["text"],
                    "expected": artikel,
                }
            )
    return items


def _nonexistent_items(gg: dict, weights: dict[str, int]) -> list[dict]:
    """Citations that cannot be answered: an Absatz past the last one.

    Derived from the real structure, so the trap is exactly as plausible as a
    real citation — the article exists, only the Absatz does not.
    """
    items = []
    for article in gg["articles"]:
        artikel = article["artikel"]
        numbered = [a for a in article["absaetze"] if a["numbered"]]
        if len(numbered) < 2:
            continue
        last = max(int(re.sub(r"\D", "", a["nr"]) or 0) for a in numbered)
        missing = str(last + 1)
        citations = weights.get(artikel.lower(), 0)
        items.append(
            {
                "id": f"nonexistent-{artikel}-{missing}",
                "kind": "nonexistent",
                "unit": "absatz",
                "artikel": artikel,
                "absatz": missing,
                "satz": None,
                "abschnitt": article["abschnitt"],
                "abschnitt_titel": article["abschnitt_titel"],
                "corpus_citations": citations,
                "stratum": stratum_of(citations),
                "citation": _citation(artikel, missing, None),
                "expected": ABSTENTION,
            }
        )
    return items


def build_prompt(item: dict) -> str:
    """The user message for one item."""
    if item["kind"] == "reverse":
        return (
            "Aus welchem Artikel des Grundgesetzes stammt der folgende "
            "Wortlaut? Nenne nur die Artikelnummer in der Form "
            '"Artikel <Nummer>".\n\n'
            f"{item['quote']}"
        )
    return (
        f"Gib den Wortlaut von {item['citation']} wörtlich wieder."
    )


def _sample(items: list[dict], per_stratum: int, rng: random.Random) -> list[dict]:
    """Take up to ``per_stratum`` items from each stratum, at most one per article.

    One item per article keeps a heavily subdivided article (Art. 106 has 9
    Absätze) from dominating its stratum.
    """
    by_stratum: dict[str, list[dict]] = collections.defaultdict(list)
    for item in items:
        by_stratum[item["stratum"]].append(item)

    chosen: list[dict] = []
    for stratum in ("hot", "warm", "cold"):
        pool = by_stratum.get(stratum, [])
        rng.shuffle(pool)
        seen_articles: set[str] = set()
        picked = []
        for item in pool:
            if item["artikel"] in seen_articles:
                continue
            seen_articles.add(item["artikel"])
            picked.append(item)
            if len(picked) >= per_stratum:
                break
        chosen.extend(picked)
    return chosen


def build_testset(
    gg: dict,
    weights: dict[str, int],
    *,
    zitat_per_stratum: int = 20,
    reverse_per_stratum: int = 7,
    nonexistent_per_stratum: int = 7,
    seed: int = 20260905,
) -> list[dict]:
    rng = random.Random(seed)
    items = (
        _sample(_zitat_items(gg, weights), zitat_per_stratum, rng)
        + _sample(_reverse_items(gg, weights), reverse_per_stratum, rng)
        + _sample(_nonexistent_items(gg, weights), nonexistent_per_stratum, rng)
    )
    for item in items:
        item["prompt"] = build_prompt(item)
        item["gg_stand"] = gg["stand"]
    items.sort(key=lambda i: i["id"])
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GG-recall test set")
    parser.add_argument("--zitat", type=int, default=20, help="zitat items per stratum")
    parser.add_argument("--reverse", type=int, default=7, help="reverse items per stratum")
    parser.add_argument(
        "--nonexistent", type=int, default=7, help="trap items per stratum"
    )
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args(argv)

    gg = json.loads(config.GG_JSON.read_text(encoding="utf-8"))
    weights = count_gg_citations(config.PDF_CACHE_DIR)
    items = build_testset(
        gg,
        weights,
        zitat_per_stratum=args.zitat,
        reverse_per_stratum=args.reverse,
        nonexistent_per_stratum=args.nonexistent,
        seed=args.seed,
    )

    config.TESTSET.parent.mkdir(parents=True, exist_ok=True)
    with config.TESTSET.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    by_kind = collections.Counter(i["kind"] for i in items)
    by_stratum = collections.Counter(i["stratum"] for i in items)
    print(
        f"{config.TESTSET}: {len(items)} items "
        f"({dict(by_kind)}, {dict(by_stratum)})\n"
        f"corpus weights from {config.PDF_CACHE_DIR}: "
        f"{len(weights)} cited articles"
    )
    return 0
