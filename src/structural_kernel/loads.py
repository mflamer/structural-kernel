"""Load combinations: the ASCE 7 seam (ADR 0007).

Load combinations are code, not kernel physics — the same posture the material
engines have (ADR 0006/0007). This module is where the ASCE 7 library plugs in
as the combination engine, keyed by the ``combo_set`` a ``load_assumptions``
decision selects. Today it carries a built-in for the one combo set phase 1
uses (ASCE 7-22 §2.4 ASD, gravity slice, review Q2); when the ASCE 7 library is
wired here, ``combos_for`` delegates to it and the built-in becomes the
fallback for the sets it covers.

A ``Combo`` is kernel vocabulary: a name and factors by load case. Nothing
ASCE-library-typed crosses this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

COMBO_SETS = ("ASCE7-22-2.4-ASD",)


@dataclass(frozen=True, slots=True)
class Combo:
    name: str
    factors: dict[str, float]


def combos_for(combo_set: str, cases: frozenset[str]) -> list[Combo]:
    """Load combinations for a selected set, limited to the cases the snapshot
    actually defines. (The ASCE 7 library will back this; the built-in covers
    the phase-1 set.)"""
    if combo_set == "ASCE7-22-2.4-ASD":
        return _asce7_22_asd_gravity(cases)
    raise ValueError(f"no combination engine for combo set {combo_set!r}")


def _asce7_22_asd_gravity(cases: frozenset[str]) -> list[Combo]:
    """The gravity slice of ASCE 7-22 §2.4 ASD combinations."""
    combos: list[Combo] = []
    if "D" in cases:
        combos.append(Combo(name="D", factors={"D": 1.0}))
    if {"D", "L"} <= cases:
        combos.append(Combo(name="D+L", factors={"D": 1.0, "L": 1.0}))
    if {"D", "S"} <= cases:
        combos.append(Combo(name="D+S", factors={"D": 1.0, "S": 1.0}))
    if {"D", "L", "S"} <= cases:
        combos.append(Combo(name="D+0.75L+0.75S", factors={"D": 1.0, "L": 0.75, "S": 0.75}))
    return combos
