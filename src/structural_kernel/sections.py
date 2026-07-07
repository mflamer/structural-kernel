"""Sawn-lumber reference tables: dressed sizes and reference stiffness.

Reference data, not decisions — the *choice* of section and grade lives in the
decision graph; these tables only translate a designation into geometry and
stiffness, the same posture as unit-conversion constants (ADR 0002). Dressed
sizes per the NDS Supplement; E reference values by grade.

An unknown designation or grade is a ``DerivationError`` at the derivation
dry-run — a rejected changeset, not a crash later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from structural_kernel.units import UNITS

# nominal designation -> dressed (breadth, depth) in inches (NDS Supplement 1A/1B)
DRESSED_IN: Final[dict[str, tuple[float, float]]] = {
    "2x4": (1.5, 3.5),
    "2x6": (1.5, 5.5),
    "2x8": (1.5, 7.25),
    "2x10": (1.5, 9.25),
    "2x12": (1.5, 11.25),
    "4x4": (3.5, 3.5),
    "4x6": (3.5, 5.5),
    "4x8": (3.5, 7.25),
    "4x10": (3.5, 9.25),
    "4x12": (3.5, 11.25),
    "6x6": (5.5, 5.5),
}

# reference modulus of elasticity (E) by grade, psi
GRADE_E_PSI: Final[dict[str, float]] = {
    "DF-L No.2": 1.6e6,
}

_M_PER_IN: Final = UNITS["in"].si_factor
_PA_PER_PSI: Final = UNITS["psi"].si_factor


@dataclass(frozen=True, slots=True)
class SectionProperties:
    """Canonical-SI section properties of a dressed sawn-lumber section."""

    breadth_m: float
    depth_m: float
    area_m2: float
    i_strong_m4: float  # bending about the strong axis (load normal to breadth)
    i_weak_m4: float


def sawn_section(designation: str) -> SectionProperties | None:
    dressed = DRESSED_IN.get(designation)
    if dressed is None:
        return None
    b = dressed[0] * _M_PER_IN
    d = dressed[1] * _M_PER_IN
    return SectionProperties(
        breadth_m=b,
        depth_m=d,
        area_m2=b * d,
        i_strong_m4=b * d**3 / 12.0,
        i_weak_m4=d * b**3 / 12.0,
    )


def grade_e_pa(grade: str) -> float | None:
    e_psi = GRADE_E_PSI.get(grade)
    return None if e_psi is None else e_psi * _PA_PER_PSI
