"""From ``Reference`` to GII unit: which law, then which § of it.

The lookup is lazy: GII's list of laws gives candidates by abbreviation and
title, only the candidates' zips are fetched, and a candidate is confirmed in
this order: (1) the Eingangsformel's citation against the law's Ausfertigung and
Neubekanntmachungen, (2) the abbreviation against ``amtabk``/``jurabk``, (3) the
name against Kurz- or Langtitel. A step decides only on exactly one law; nothing
is guessed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.bestandsrecht.reference import Reference, Resolved, Unresolved
from backend.gii import client, index
from backend.gii import law as gii_law


@dataclass(frozen=True)
class Resolution:
    resolved: list[Resolved]
    unresolved: list[Unresolved]
    laws: dict[str, gii_law.Law]  # by slug, every law a reference resolved to

    @property
    def ids(self) -> list[str]:
        return list(dict.fromkeys(r.id for r in self.resolved))


def _confirm(laws: list[gii_law.Law], ref: Reference) -> tuple[gii_law.Law | None, str]:
    citations = gii_law.draft_citations(ref.fundstelle)
    steps = [
        [law for law in laws if citations & law.citations],
        [law for law in laws if ref.abk and index.abk_key(ref.abk) in
         {index.abk_key(a) for a in (law.amtabk, *law.jurabk) if a}],
        [law for law in laws if index.key(ref.gesetz) in
         {index.key(t) for t in (law.kurzue, law.langue) if t}],
    ]
    for found in steps:
        if len(found) == 1:
            return found[0], ""
        if len(found) > 1:
            return None, "ambiguous"
    return None, "no match"


def resolve(references: list[Reference], entries: list[index.Entry] | None = None,
            zip_path: Callable[[str], Path] = client.zip_path) -> Resolution:
    entries = index.load() if entries is None else entries
    loaded: dict[str, gii_law.Law | str] = {}  # slug -> law, or the download error

    def load(slug: str) -> gii_law.Law | str:
        if slug not in loaded:
            try:
                loaded[slug] = gii_law.load(slug, zip_path(slug))
            except Exception as e:  # noqa: BLE001 — a failed download is a reason, not a crash
                loaded[slug] = f"download failed: {e}"
        return loaded[slug]

    by_law: dict[tuple, tuple[gii_law.Law | None, str]] = {}
    resolved, unresolved, laws = [], [], {}
    for ref in references:
        key = (ref.gesetz, ref.abk, ref.fundstelle)
        if key not in by_law:
            slugs = index.candidates(entries, ref.abk, ref.gesetz)
            got = [load(s) for s in slugs]
            candidates = [g for g in got if isinstance(g, gii_law.Law)]
            if not slugs:
                by_law[key] = (None, "no candidate")
            elif not candidates:
                by_law[key] = (None, next(g for g in got if isinstance(g, str)))
            else:
                by_law[key] = _confirm(candidates, ref)
        law, reason = by_law[key]
        if law is None:
            unresolved.append(Unresolved(ref, reason))
            continue
        units = law.expand(ref.paragraph)
        if not units:
            unresolved.append(Unresolved(ref, "paragraph not in law"))
            continue
        laws[law.slug] = law
        resolved += [Resolved(f"{law.slug}/{u.id}", u.enbez, ref) for u in units]
    return Resolution(resolved, unresolved, laws)
