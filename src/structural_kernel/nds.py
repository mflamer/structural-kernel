"""ndswood adapter: the NDS 2024 calculation engine boundary (ADR 0006).

Every ndswood import lives in this module; nothing ndswood-typed leaves it.
The kernel side speaks tagged SI quantities and our check vocabulary; this
adapter converts once at the boundary (kernel canonical SI ⇄ ndswood's
lb/in/psi floats) and re-expresses ndswood's ``CheckResult`` — including its
factor audit trail with real NDS references — in kernel schemas.

ndswood ships no type stubs; strictness relaxations are scoped to this file.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from structural_kernel.units import UNITS

_M_PER_IN = UNITS["in"].si_factor
_PA_PER_PSI = UNITS["psi"].si_factor
_N_PER_LBF = UNITS["lbf"].si_factor
_NM_PER_LBIN = _N_PER_LBF * _M_PER_IN


@dataclass(frozen=True, slots=True)
class SectionProperties:
    """Canonical-SI section properties, from ndswood's verified dressed sizes."""

    breadth_m: float
    depth_m: float
    area_m2: float
    i_strong_m4: float
    i_weak_m4: float


@dataclass(frozen=True, slots=True)
class ProvisionFactorData:
    symbol: str
    value: float
    ref: str
    note: str


@dataclass(frozen=True, slots=True)
class MemberCheckData:
    """One ndswood check, re-expressed in kernel vocabulary (SI)."""

    check: Literal["bending", "shear", "compression"]
    demand_pa: float
    capacity_pa: float
    unity: float
    passes: bool
    provision: str
    factors: tuple[ProvisionFactorData, ...]


def _nominal(designation: str) -> tuple[int, int] | None:
    parts = designation.split("x")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def section_properties(designation: str) -> SectionProperties | None:
    """Dressed sawn-lumber section properties, or None for unknown designations."""
    from ndswood import RectangularSection

    nominal = _nominal(designation)
    if nominal is None:
        return None
    try:
        section: Any = RectangularSection.sawn(*nominal)
    except Exception:
        return None
    b_m, d_m = section.b * _M_PER_IN, section.d * _M_PER_IN
    return SectionProperties(
        breadth_m=b_m,
        depth_m=d_m,
        area_m2=section.area * _M_PER_IN**2,
        i_strong_m4=section.Ix * _M_PER_IN**4,
        i_weak_m4=section.Iy * _M_PER_IN**4,
    )


def grade_e_pa(grade: str) -> float | None:
    """Reference E for a sawn grade, canonical SI. None for unknown grades."""
    from ndswood import sawn

    try:
        return float(sawn(grade).E) * _PA_PER_PSI
    except Exception:
        return None


def combo_duration(cases: set[str]) -> str:
    """ASD load-duration class for a combo's case set (NDS 2.3.2): snow governs
    at two months, occupancy live at ten years, dead-only is permanent."""
    if "S" in cases:
        return "two_months"
    if "L" in cases or "Lr" in cases:
        return "ten_years"
    return "permanent"


def check_flexural_member(
    *,
    section: str,
    grade: str,
    repetitive: bool,
    duration: str,
    moment_nm: float,
    shear_n: float,
) -> list[MemberCheckData]:
    """NDS bending + shear checks for a sawn flexural member.

    ``lu_in=0`` (continuously braced compression edge — sheathed floor
    framing, a phase-1 assumption flagged in note 0003 territory).
    """
    member = _member(section, grade, repetitive, duration)
    results: list[MemberCheckData] = []
    bending: Any = member.check_bending(M_inlb=moment_nm / _NM_PER_LBIN, lu_in=0)
    results.append(_convert("bending", bending))
    shear: Any = member.check_shear(V_lb=shear_n / _N_PER_LBF)
    results.append(_convert("shear", shear))
    return results


def check_post(
    *,
    section: str,
    grade: str,
    duration: str,
    axial_n: float,
    unbraced_length_m: float,
) -> MemberCheckData:
    """NDS column check for a sawn post, pinned both ends, le = full height."""
    member = _member(section, grade, repetitive=False, duration=duration)
    result: Any = member.check_compression(
        P_lb=axial_n / _N_PER_LBF, le1_in=unbraced_length_m / _M_PER_IN
    )
    return _convert("compression", result)


def _member(section: str, grade: str, repetitive: bool, duration: str) -> Any:
    from ndswood import Member, RectangularSection, sawn

    nominal = _nominal(section)
    if nominal is None:
        raise ValueError(f"not a sawn designation: {section!r}")
    return Member(
        section=RectangularSection.sawn(*nominal),
        material=sawn(grade),
        method="ASD",
        duration=duration,
        repetitive=repetitive,
        nominal=nominal,
    )


def _convert(check: Literal["bending", "shear", "compression"], result: Any) -> MemberCheckData:
    return MemberCheckData(
        check=check,
        demand_pa=float(result.demand) * _PA_PER_PSI,
        capacity_pa=float(result.capacity) * _PA_PER_PSI,
        unity=float(result.ratio),
        passes=bool(result.passes),
        provision=str(result.ref),
        factors=tuple(
            ProvisionFactorData(
                symbol=str(f.symbol),
                value=float(f.value),
                ref=str(f.ref),
                note=str(f.note or ""),
            )
            for f in result.factors
        ),
    )
