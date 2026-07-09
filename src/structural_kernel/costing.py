"""Cost quantity kinds: an open registry of *countables the derived model emits*,
which a cost basis prices (ADR 0012, revised per PO note 0003).

The whole cost model is "a table of priced factors over derived quantities".
This module owns the *quantities* half — the registry of quantity kinds a factor
may price and how each resolves over a derived model. `decisions.py` owns the
*prices* half (the `cost_basis` factor table); `explorations.py` multiplies them.

The one boundary that must stay strict (note 0003): **derivation emits
quantities; pricing never invents them.** A resolver only *aggregates* what
derivation already produced (member weights, board-feet, piece / connection /
pick counts) — never estimates a quantity. That is exactly what makes
re-ranking-without-re-solving hold: re-ranking changes *factors*, never
*quantities*, so stored physics is reused untouched.

`register_quantity_kind` is the whole extension surface (the ADR 0004 / 0007
move applied to cost). A cost driver nobody planned for — a carbon price over a
CO2e countable — is one registration plus a factor row, no kernel change. A
factor naming a kind no resolver is registered for fails cleanly at validation,
pointing at the missing countable, never by inventing it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from structural_kernel.materials import engine_for, families
from structural_kernel.units import Dimension

if TYPE_CHECKING:
    from structural_kernel.derivation import DerivedModel

# A resolver reads a derived model and an optional (family, role) scope and
# returns the aggregate quantity's canonical-SI magnitude. Kept to primitive
# scope args so this module need not import the `FactorScope` schema (which lives
# in decisions.py and imports back here) — no cycle.
Resolver = Callable[["DerivedModel", str | None, str | None], float]


@dataclass(frozen=True)
class QuantityKind:
    """One countable a factor may price. ``dimension`` is the physical dimension
    of the aggregate (``MASS`` for weight, ``VOLUME`` for board-feet) or ``None``
    for a dimensionless count (pieces, picks, connections) — it is what the price
    unit is validated against."""

    name: str
    dimension: Dimension | None
    resolve: Resolver


QUANTITY_KINDS: dict[str, QuantityKind] = {}


def register_quantity_kind(kind: QuantityKind) -> None:
    """Register a cost quantity kind. The whole extension surface: a new cost
    driver — a CO2e countable, a formwork area — is one call, no kernel edit."""
    QUANTITY_KINDS[kind.name] = kind


def quantity_kind(name: str) -> QuantityKind | None:
    return QUANTITY_KINDS.get(name)


def quantity_kinds() -> frozenset[str]:
    return frozenset(QUANTITY_KINDS)


# -- built-in kinds: pure aggregations of what derivation already emits ---------------


def _in_scope(family: str, role: str, scope_family: str | None, scope_role: str | None) -> bool:
    return (scope_family is None or family == scope_family) and (
        scope_role is None or role == scope_role
    )


def _member_weight(model: DerivedModel, family: str | None, role: str | None) -> float:
    total = 0.0
    catalog = families()
    for element in model.elements:
        if element.grade is None or element.family not in catalog:
            continue
        if not _in_scope(element.family, element.role, family, role):
            continue
        engine = engine_for(element.family)
        section = engine.section_properties(element.section)
        density = engine.mass_density_kg_m3(element.grade)
        if section is None or density is None:
            continue
        total += section.area_m2 * element.length.si_mag * density
    return total


def _board_feet(model: DerivedModel, family: str | None, role: str | None) -> float:
    total = 0.0
    catalog = families()
    for element in model.elements:
        if element.family not in catalog:
            continue
        if not _in_scope(element.family, element.role, family, role):
            continue
        volume = engine_for(element.family).nominal_volume_m3(
            element.section, element.length.si_mag
        )
        if volume is not None:
            total += volume
    return total


def _piece_count(model: DerivedModel, family: str | None, role: str | None) -> float:
    return float(sum(1 for e in model.elements if _in_scope(e.family, e.role, family, role)))


def _crane_picks(model: DerivedModel, family: str | None, role: str | None) -> float:
    total = 0
    catalog = families()
    for element in model.elements:
        if element.family not in catalog:
            continue
        if not _in_scope(element.family, element.role, family, role):
            continue
        total += engine_for(element.family).crane_picks_per_member()
    return float(total)


def _connection_count(model: DerivedModel, family: str | None, role: str | None) -> float:
    if family is None and role is None:
        return float(len(model.load_path))  # every load-path edge is a connection
    by_eid = {e.eid: e for e in model.elements}
    return float(
        sum(
            1
            for edge in model.load_path
            if (bearing := by_eid.get(edge.bearing)) is not None
            and _in_scope(bearing.family, bearing.role, family, role)
        )
    )


for _kind in (
    QuantityKind("member_weight", Dimension.MASS, _member_weight),
    QuantityKind("board_feet", Dimension.VOLUME, _board_feet),
    QuantityKind("piece_count", None, _piece_count),
    QuantityKind("connection_count", None, _connection_count),
    QuantityKind("crane_picks", None, _crane_picks),
):
    register_quantity_kind(_kind)
