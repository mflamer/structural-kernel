"""Load combinations: the ASCE 7 seam (ADR 0007).

Load combinations are code, not kernel physics — the same posture the material
engines have (ADR 0006/0007). This module is where the ASCE 7 library plugs in
as the combination engine, keyed by the ``combo_set`` a ``load_assumptions``
decision selects. Today it carries built-ins for the sets phase-1/2 use (ASCE
7-22 §2.4 ASD for wood, §2.3 LRFD for steel, gravity slices); when the ASCE 7
library is wired here, ``combos_for`` delegates to it and the built-ins become
the fallback for the sets they cover.

A ``Combo`` is kernel vocabulary: a name, factors by load case, and a
**purpose**. Strength combinations size members (ASD service-level stress or
LRFD factored strength); *service* combinations (always unfactored) drive the
deflection/serviceability limits, which are load-level checks independent of the
member-design method (IBC 1604.3 / ASCE 7 Appendix C). Under ASD the two
coincide — the §2.4 combinations *are* service-level — so ASD combos are tagged
``service`` and design both strength and deflection. Under LRFD they diverge:
factored combos size the steel, unfactored combos check its deflection. Nothing
ASCE-library-typed crosses this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ComboPurpose = Literal["strength", "service"]

COMBO_SETS = ("ASCE7-22-2.4-ASD", "ASCE7-22-2.3-LRFD")


@dataclass(frozen=True, slots=True)
class Combo:
    name: str
    factors: dict[str, float]
    purpose: ComboPurpose = "strength"


def combos_for(combo_set: str, cases: frozenset[str]) -> list[Combo]:
    """Load combinations for a selected set, limited to the cases the snapshot
    actually defines. (The ASCE 7 library will back this; the built-ins cover
    the phase-1/2 sets.)"""
    if combo_set == "ASCE7-22-2.4-ASD":
        return _asce7_22_asd_gravity(cases)
    if combo_set == "ASCE7-22-2.3-LRFD":
        return _asce7_22_lrfd_gravity(cases)
    raise ValueError(f"no combination engine for combo set {combo_set!r}")


def _asce7_22_asd_gravity(cases: frozenset[str]) -> list[Combo]:
    """The gravity slice of ASCE 7-22 §2.4 ASD combinations. ASD combinations
    are service-level, so each serves both member stress and deflection."""
    combos: list[Combo] = []
    if "D" in cases:
        combos.append(Combo(name="D", factors={"D": 1.0}, purpose="service"))
    if {"D", "L"} <= cases:
        combos.append(Combo(name="D+L", factors={"D": 1.0, "L": 1.0}, purpose="service"))
    if {"D", "S"} <= cases:
        combos.append(Combo(name="D+S", factors={"D": 1.0, "S": 1.0}, purpose="service"))
    if {"D", "L", "S"} <= cases:
        combos.append(
            Combo(
                name="D+0.75L+0.75S",
                factors={"D": 1.0, "L": 0.75, "S": 0.75},
                purpose="service",
            )
        )
    return combos


def _asce7_22_lrfd_gravity(cases: frozenset[str]) -> list[Combo]:
    """The gravity slice of ASCE 7-22 §2.3.1 LRFD strength combinations, plus
    the unfactored service combinations the deflection checks use. Steel is
    designed to the factored strength combos; its deflection is a serviceability
    limit checked under the service combos (IBC 1604.3), never under 1.2D+1.6L."""
    combos: list[Combo] = []
    # Strength (factored) — size the members.
    if "D" in cases:
        combos.append(Combo(name="1.4D", factors={"D": 1.4}, purpose="strength"))
    if {"D", "L"} <= cases:
        combos.append(Combo(name="1.2D+1.6L", factors={"D": 1.2, "L": 1.6}, purpose="strength"))
    if {"D", "S"} <= cases:
        combos.append(Combo(name="1.2D+1.6S", factors={"D": 1.2, "S": 1.6}, purpose="strength"))
    if {"D", "L", "S"} <= cases:
        combos.append(
            Combo(name="1.2D+1.6L+0.5S", factors={"D": 1.2, "L": 1.6, "S": 0.5}, purpose="strength")
        )
        combos.append(
            Combo(name="1.2D+1.6S+1.0L", factors={"D": 1.2, "S": 1.6, "L": 1.0}, purpose="strength")
        )
    # Service (unfactored) — the deflection checks. Named to match the ASD
    # service combos so the L/360-L/240 code path finds "D" for live-deflection.
    if "D" in cases:
        combos.append(Combo(name="D", factors={"D": 1.0}, purpose="service"))
    if {"D", "L"} <= cases:
        combos.append(Combo(name="D+L", factors={"D": 1.0, "L": 1.0}, purpose="service"))
    if {"D", "S"} <= cases:
        combos.append(Combo(name="D+S", factors={"D": 1.0, "S": 1.0}, purpose="service"))
    return combos
