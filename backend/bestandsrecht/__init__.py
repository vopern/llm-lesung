"""Which existing §§ the analysis of a draft needs to read, and their text.

``select`` hands the draft's Wortlaut to the model selector and flags the
entries whose ``beleg`` does not stand in that Wortlaut (``in_wortlaut``); they
are kept, the flag only shows how faithfully the selector quotes. ``resolve``
finds each in GII (``wehrpflg/__3``).
``provide`` does both, fetches the texts, freezes the selection and the texts
per bill, turns them into blocks (``Context.blocks``: a § in full, or only the
headings of a long cited range), fits the blocks into the analysis's size
budget (``fit``) and logs what it selected, resolved, could not resolve and fed.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from backend import config, gii
from backend.bestandsrecht import model
from backend.bestandsrecht.reference import Reference, Resolved, Unresolved
from backend.bestandsrecht.resolve import Resolution, resolve
from backend.gii import client
from backend.gii import index as gii_index
from backend.text import squash

# Page headers and footers pypdf puts between the lines of a provision.
_FURNITURE = re.compile(
    r"^[ \t]*(?:"
    r"Drucksache \d+/\d+ *[–-] *\d+ *[–-] *Deutscher Bundestag *[–-] *\d+\. Wahlperiode"
    r"|Deutscher Bundestag *[–-] *\d+\. Wahlperiode *[–-] *\d+ *[–-] *Drucksache \d+/\d+"
    r"|Anlage \d+"
    r"|Vorabfassung - wird durch die lektorierte Fassung ersetzt\."
    r")[ \t]*\n?",
    re.MULTILINE,
)
_START = re.compile(r"das\s+folgende\s+Gesetz\s+beschlossen[^:]{0,80}:")
_END = re.compile(r"^[ \t]*Begründung[ \t]*$", re.MULTILINE)


def wortlaut(text: str) -> str:
    """The draft's Wortlaut: from the enacting clause to the Begründung, without
    page furniture. Falls back to the start and the end of ``text``."""
    start = _START.search(text)
    text = text[start.end():] if start else text
    end = _END.search(text)
    return _FURNITURE.sub("", text[:end.start()] if end else text)


@dataclass(frozen=True)
class Selected:
    references: list[Reference]
    unbelegt: list[Reference]  # those whose beleg is not in the Wortlaut
    call: dict  # prompt version, model, effort, cost, usage


# A beleg may skip what the selector shortened: the numbering between two lines
# of a Befehl, the wording an "Angabe" is replaced by. Its words must still stand
# in the Wortlaut in their order, each at most this many squashed characters
# after the previous one.
_GAP = 200
_EDGES = "\"'.,:;()"


def in_wortlaut(beleg: str, haystack: str) -> bool:
    """Whether ``beleg`` stands in ``haystack`` (a squashed Wortlaut): verbatim,
    or word by word in order with gaps of at most ``_GAP`` characters."""
    words: list[str] = []
    for w in beleg.split():
        w = squash(w).strip(_EDGES)
        if words and words[-1].strip("§") == "":
            words[-1] += w  # "§ 6" is one word: "6" alone also stands in "16"
        elif w:
            words.append(w)
    if not words:
        return False
    if squash(beleg) in haystack:
        return True
    ends = set()
    start = haystack.find(words[0])
    while start != -1:
        ends.add(start + len(words[0]))
        start = haystack.find(words[0], start + 1)
    for word in words[1:]:
        reached = set()
        for end in ends:
            limit = end + _GAP + len(word)
            i = haystack.find(word, end, limit)
            while i != -1:
                reached.add(i + len(word))
                i = haystack.find(word, i + 1, limit)
        if not reached:
            return False
        ends = reached
    return True


def select(titel: str, text: str, trace: Path | None = None,
           model_name: str | None = None, effort: str | None = None) -> Selected:
    draft = wortlaut(text)
    refs, call = model.references(titel, draft, trace, model_name, effort)
    return Selected(refs, _unbelegt(refs, draft), call)


def _unbelegt(refs: list[Reference], draft: str) -> list[Reference]:
    haystack = squash(draft)
    return [r for r in refs if not in_wortlaut(r.beleg, haystack)]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _frozen_selection(titel: str, text: str, freeze_dir: Path, trace: Path | None,
                      model_name: str | None, effort: str | None) -> Selected:
    """``select``, answered from ``freeze_dir/selection.json`` while the draft's
    Wortlaut, the title and the selection settings are unchanged."""
    key = {"titel_sha256": _sha256(titel), "wortlaut_sha256": _sha256(wortlaut(text)),
           "prompt_version": config.BESTANDSRECHT_PROMPT_VERSION,
           "model": model_name or config.BESTANDSRECHT_MODEL,
           "effort": effort or config.BESTANDSRECHT_EFFORT}
    path = freeze_dir / "selection.json"
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored.get("key") == key:
            refs = [Reference(**r) for r in stored["references"]]
            return Selected(refs, _unbelegt(refs, wortlaut(text)),
                            stored["call"] | {"frozen": True})
    selected = select(titel, text, trace, model_name, effort)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key,
                                "references": [asdict(r) for r in selected.references],
                                "call": selected.call}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return selected


@dataclass(frozen=True)
class Fetched:
    """The frozen text of one unit, as fed to the Lektor."""

    id: str
    gesetz: str  # the law's amtliche Abkürzung, else its slug
    enbez: str
    titel: str
    stand: str | None  # GII's "zuletzt geändert durch …"
    builddate: str | None  # GII's build of the law, YYYYMMDDhhmmss
    text: str
    sha256: str


# A cited range of more units than this ("Die §§ 3 bis 50 gelten …") is fed as
# the headings of its units, not their wording; a § the draft amends, or cites
# on its own or in a short range, is always fed in full.
RANGE_IN_FULL_MAX = 5

Form = Literal["wortlaut", "ueberschriften"]


@dataclass(frozen=True)
class Block:
    """One ``<geltende-fassung>`` block: a unit in full, or a range's headings."""

    key: str  # the unit's id, or "<slug>/<range as cited>" for a range's headings
    form: Form
    rolle: str
    gesetz: str
    paragraph: str
    stand: str
    text: str
    ids: tuple[str, ...]  # the units it covers

    def message(self) -> tuple[str, str, str, str]:
        """``(gesetz, paragraph, stand, text)`` for ``analyzer.build_message``."""
        return (self.gesetz, self.paragraph, self.stand, self.text)


Decision = Literal["vollstaendig", "nur_geaendert", "entfallen", "keine"]


@dataclass(frozen=True)
class Fit:
    """Which blocks the analysis reads, under its size budget.

    ``vollstaendig``: all of them fit. ``nur_geaendert``: only the blocks of
    units a Befehl amends fit, the cited ones are left out. ``entfallen``: not
    even those fit, nothing is fed. ``keine``: nothing was fetched. Sizes are
    the characters of the blocks' texts, like the documents' ``text_chars``;
    ``fed`` and ``left_out`` are block keys.
    """

    decision: Decision
    budget: int
    chars_all: int
    chars_geaendert: int
    chars_fed: int
    fed: list[str]
    left_out: list[str]

    def summary(self) -> dict:
        """The decision without the key lists, for log lines and trace headers."""
        return {k: v for k, v in asdict(self).items() if k not in ("fed", "left_out")} | {
            "fed_count": len(self.fed), "left_out_count": len(self.left_out)}


@dataclass(frozen=True)
class Context:
    selected: Selected
    resolution: Resolution
    fetched: list[Fetched]
    fit: Fit | None = None  # set by ``provide`` when given a budget

    def rolle(self, paragraph_id: str) -> str:
        """``geaendert`` when any reference amends the unit, else ``verwiesen``."""
        return _rollen(self.resolution).get(paragraph_id, "verwiesen")

    def blocks(self) -> list[Block]:
        """Every block, in the order of the fetched units.

        A unit some reference names on its own, in a short range or as amended
        is a block of its wording. A long cited range is one block of its
        units' headings, placed at its first unit; its units that no other
        reference names are fed only there.
        """
        by_id = {f.id: f for f in self.fetched}
        ranges: dict[str, list[str]] = {}  # long cited range -> its unit ids
        span: dict[Reference, list[str]] = {}
        for r in self.resolution.resolved:
            span.setdefault(r.reference, []).append(r.id)
        in_full = set()
        for ref, ids in span.items():
            if ref.rolle == "verwiesen" and len(ids) > RANGE_IN_FULL_MAX:
                slug = ids[0].split("/", 1)[0]
                ranges.setdefault(f"{slug}/{ref.paragraph}", list(dict.fromkeys(ids)))
            else:
                in_full.update(ids)
        starts = {ids[0]: key for key, ids in ranges.items()}
        out = []
        for f in self.fetched:
            if f.id in in_full:
                out.append(Block(f.id, "wortlaut", self.rolle(f.id), f.gesetz, f.enbez,
                                 _date(f.builddate), f"{f.enbez} {f.titel}".strip()
                                 + f"\n{f.text}", (f.id,)))
            for key, ids in ranges.items():
                if starts.get(f.id) == key:
                    out.append(_headings(key, [by_id[i] for i in ids if i in by_id]))
        return out

    def fed(self) -> list[tuple[str, str, str, str]]:
        """The blocks ``fit`` keeps (every block without a fit), for ``build_message``."""
        keys = None if self.fit is None else set(self.fit.fed)
        return [b.message() for b in self.blocks() if keys is None or b.key in keys]

    def summary(self) -> dict:
        """The size decision and the selection call, for trace headers and samples."""
        call = self.selected.call
        return (self.fit.summary() if self.fit is not None else {}) | {
            "references": len(self.selected.references),
            "unbelegt": len(self.selected.unbelegt),
            "unresolved": len(self.resolution.unresolved),
            "selection": {k: call.get(k) for k in
                          ("prompt_version", "model", "effort", "cost_usd", "frozen")},
        }

    def documents(self) -> list[dict]:
        """An ``analysis_documents`` entry per fed block."""
        keys = None if self.fit is None else set(self.fit.fed)
        by_id = {f.id: f for f in self.fetched}
        out = []
        for b in self.blocks():
            if keys is not None and b.key not in keys:
                continue
            first = by_id[b.ids[0]]
            entry = {"document_id": b.key, "typ": "bestandsrecht", "form": b.form,
                     "dokumentnummer": f"{b.paragraph} {b.gesetz}", "gesetz": b.gesetz,
                     "rolle": b.rolle, "stand": first.stand, "builddate": first.builddate,
                     "pdf_url": gii.url(b.ids[0]),
                     "pdf_hash": first.sha256 if b.form == "wortlaut" else _sha256(b.text),
                     "text_chars": len(b.text)}
            if b.form == "ueberschriften":
                entry["ids"] = list(b.ids)
            out.append(entry)
        return out


def _headings(key: str, units: list[Fetched]) -> Block:
    paragraph = key.split("/", 1)[1]
    lines = [f"{u.enbez} {u.titel}".strip() for u in units]
    text = (f"{paragraph}: nur die Überschriften, der Wortlaut ist nicht abgedruckt.\n"
            + "\n".join(lines))
    first = units[0]
    return Block(key, "ueberschriften", "verwiesen", first.gesetz, paragraph,
                 _date(first.builddate), text, tuple(u.id for u in units))


def _rollen(resolution: Resolution) -> dict[str, str]:
    rollen: dict[str, str] = {}
    for r in resolution.resolved:
        if rollen.get(r.id) != "geaendert":
            rollen[r.id] = r.reference.rolle
    return rollen


def fit(context: Context, budget: int) -> Fit:
    """All blocks if they fit ``budget``, else those of amended units, else none."""
    blocks = context.blocks()
    sizes = {b.key: len(b.text) for b in blocks}
    geaendert = [b.key for b in blocks if b.rolle == "geaendert"]
    chars_all = sum(sizes.values())
    chars_geaendert = sum(sizes[k] for k in geaendert)
    if not sizes:
        decision, fed = "keine", []
    elif chars_all <= budget:
        decision, fed = "vollstaendig", list(sizes)
    elif geaendert and chars_geaendert <= budget:
        decision, fed = "nur_geaendert", geaendert
    else:
        decision, fed = "entfallen", []
    return Fit(decision, budget, chars_all, chars_geaendert, sum(sizes[k] for k in fed), fed,
               [k for k in sizes if k not in fed])


def _date(builddate: str | None) -> str:
    b = builddate or ""
    return f"{b[:4]}-{b[4:6]}-{b[6:8]}" if len(b) >= 8 else ""


def fetch(paragraph_id: str, resolution: Resolution) -> Fetched:
    """The unit's text from the law ``resolve`` loaded."""
    slug, unit_id = paragraph_id.split("/", 1)
    law = resolution.laws[slug]
    unit = next(u for u in law.units if u.id == unit_id)
    return Fetched(paragraph_id, law.amtabk or slug, unit.enbez, unit.titel, law.stand,
                   law.builddate, unit.text, _sha256(unit.text))


def _frozen(freeze_dir: Path, paragraph_id: str, resolution: Resolution) -> Fetched:
    """The unit's text as first fetched for this bill; never fetched again."""
    path = freeze_dir / f"{paragraph_id}.json"
    if path.exists():
        return Fetched(**json.loads(path.read_text(encoding="utf-8")))
    fetched = fetch(paragraph_id, resolution)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(fetched), ensure_ascii=False, indent=1), encoding="utf-8")
    return fetched


def _resolved(r: Resolved) -> dict:
    return {"id": r.id, "enbez": r.enbez, **asdict(r.reference)}


def _unresolved(u: Unresolved) -> dict:
    return {**asdict(u.reference), "reason": u.reason}


def record(selected: Selected, resolution: Resolution,
           fetched: list[Fetched] | None = None, fitted: Fit | None = None) -> dict:
    """What a selection found, as logged by ``provide`` and stored by the eval.

    With ``fetched``, also each unit's size and every block with its form and size.
    """
    out = {
        "call": selected.call,
        "ids": resolution.ids,
        "resolved": [_resolved(r) for r in resolution.resolved],
        "unresolved": [_unresolved(u) for u in resolution.unresolved],
        "references": [asdict(r) for r in selected.references],
        "unbelegt": [asdict(r) for r in selected.unbelegt],
    }
    if fetched is not None:
        rollen = _rollen(resolution)
        out["fetched"] = [{k: v for k, v in asdict(f).items() if k != "text"}
                          | {"rolle": rollen.get(f.id), "chars": len(f.text)} for f in fetched]
        out["blocks"] = [{"key": b.key, "form": b.form, "rolle": b.rolle, "chars": len(b.text),
                          "ids": list(b.ids)}
                         for b in Context(selected, resolution, fetched).blocks()]
    if fitted is not None:
        out["fit"] = asdict(fitted)
    return out


def provide(titel: str, text: str, *, freeze_dir: Path, log: Path | None = None,
            trace: Path | None = None, model_name: str | None = None,
            effort: str | None = None, entries: list[gii_index.Entry] | None = None,
            zip_path: Callable[[str], Path] = client.zip_path,
            budget: int | None = None) -> Context:
    """Select, resolve and fetch the existing law a draft needs.

    The selection and the texts are frozen under ``freeze_dir`` (one bill's
    folder): the selection is reused while the draft and the selection
    settings are unchanged, a unit fetched once is read from there ever after.
    Resolution runs every time. With ``budget`` (characters left for the
    blocks), ``fit`` decides what is fed. ``log`` receives ``record`` as JSON,
    ``trace`` the selection call's message stream.
    """
    selected = _frozen_selection(titel, text, freeze_dir, trace, model_name, effort)
    resolution = resolve(selected.references, entries, zip_path)
    fetched = [_frozen(freeze_dir, pid, resolution) for pid in resolution.ids]
    context = Context(selected, resolution, fetched)
    if budget is not None:
        context = replace(context, fit=fit(context, budget))
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(record(selected, resolution, fetched, context.fit),
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return context
