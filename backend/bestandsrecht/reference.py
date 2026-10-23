"""The contracts: a § the draft names (``Reference``), and where GII has it (``Resolved``)."""

from dataclasses import dataclass
from typing import Literal

Rolle = Literal["geaendert", "verwiesen"]


@dataclass(frozen=True)
class Reference:
    """An existing § of an existing law, and where the draft names it.

    ``rolle`` is ``geaendert`` for a § a Befehl amends and ``verwiesen`` for a §
    the draft's new wording cites; ``von`` is the § whose new wording cites it.
    ``paragraph`` is one § ("§ 3") or a range as the draft writes it
    ("§§ 8a bis 20b"): only the law's own list of §§ knows what lies between.
    ``beleg`` is the passage of the draft the entry was read from.
    """

    gesetz: str
    paragraph: str
    rolle: Rolle
    beleg: str
    abk: str | None = None
    fundstelle: str | None = None
    von: str | None = None


@dataclass(frozen=True)
class Resolved:
    """One GII unit a ``Reference`` names; a range yields one per unit.

    ``id`` is the GII path (``wehrpflg/__3``), ``enbez`` GII's label ("§ 3").
    """

    id: str
    enbez: str
    reference: Reference


@dataclass(frozen=True)
class Unresolved:
    """A ``Reference`` GII could not answer, and why: ``no candidate`` (no law of
    that abbreviation or name), ``no match`` / ``ambiguous`` (candidates, but not
    exactly one confirmed), ``paragraph not in law``, ``download failed``."""

    reference: Reference
    reason: str
