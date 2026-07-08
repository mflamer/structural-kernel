"""Wood engine: the ndswood (NDS 2024) adapter (ADR 0006).

Every ndswood import lives in this module. Kernel canonical SI ⇄ ndswood's
lb/in/psi floats is converted once here; ndswood's ``CheckResult`` — factor
trail with real NDS references included — becomes kernel ``MemberCheckData``.
All wood member checks are stress-based, so every result is PRESSURE-dimensioned.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from typing import Any

from structural_kernel.materials.base import (
    AxialRequest,
    FlexureRequest,
    MemberCheckData,
    ProvisionFactor,
    SectionProperties,
)
from structural_kernel.units import UNITS, Dimension

_M_PER_IN = UNITS["in"].si_factor
_PA_PER_PSI = UNITS["psi"].si_factor
_N_PER_LBF = UNITS["lbf"].si_factor
_NM_PER_LBIN = _N_PER_LBF * _M_PER_IN


class WoodEngine:
    """NDS 2024 sawn-lumber member design via ndswood."""

    family = "sawn_lumber"

    @property
    def code(self) -> str:
        from ndswood import EDITION

        return str(EDITION)

    def section_properties(self, designation: str) -> SectionProperties | None:
        from ndswood import RectangularSection

        nominal = _nominal(designation)
        if nominal is None:
            return None
        try:
            section: Any = RectangularSection.sawn(*nominal)
        except Exception:
            return None
        return SectionProperties(
            breadth_m=section.b * _M_PER_IN,
            depth_m=section.d * _M_PER_IN,
            area_m2=section.area * _M_PER_IN**2,
            i_strong_m4=section.Ix * _M_PER_IN**4,
            i_weak_m4=section.Iy * _M_PER_IN**4,
        )

    def elastic_modulus_pa(self, grade: str) -> float | None:
        from ndswood import sawn

        try:
            return float(sawn(grade).E) * _PA_PER_PSI
        except Exception:
            return None

    def mass_density_kg_m3(self, grade: str) -> float | None:
        """From the grade's specific gravity G (mass of water = 1000 kg/m³)."""
        from ndswood import sawn

        try:
            gravity = getattr(sawn(grade), "G", None)
        except Exception:
            return None
        return None if gravity is None else float(gravity) * 1000.0

    def check_flexure(self, request: FlexureRequest) -> list[MemberCheckData]:
        member = self._member(request.designation, request.grade, request)
        bending: Any = member.check_bending(
            M_inlb=request.moment_nm / _NM_PER_LBIN, lu_in=request.unbraced_length_m / _M_PER_IN
        )
        shear: Any = member.check_shear(V_lb=request.shear_n / _N_PER_LBF)
        return [_convert("bending", bending), _convert("shear", shear)]

    def check_axial(self, request: AxialRequest) -> MemberCheckData:
        if request.sense != "compression":
            raise ValueError("wood tension checks are not wired in phase 1")
        member = self._member(request.designation, request.grade, request)
        result: Any = member.check_compression(
            P_lb=request.force_n / _N_PER_LBF, le1_in=request.unbraced_length_m / _M_PER_IN
        )
        return _convert("compression", result)

    def _member(self, section: str, grade: str, request: object) -> Any:
        from ndswood import Member, RectangularSection, sawn

        nominal = _nominal(section)
        if nominal is None:
            raise ValueError(f"not a sawn designation: {section!r}")
        load_cases = getattr(request, "load_cases", frozenset())
        repetitive = getattr(request, "repetitive", False)
        return Member(
            section=RectangularSection.sawn(*nominal),
            material=sawn(grade),
            method="ASD",
            duration=_asd_duration(load_cases),
            repetitive=repetitive,
            nominal=nominal,
        )


def _asd_duration(cases: frozenset[str]) -> str:
    """ASD load-duration class for a combo's cases (NDS 2.3.2): snow governs at
    two months, occupancy live at ten years, dead-only is permanent."""
    if "S" in cases:
        return "two_months"
    if "L" in cases or "Lr" in cases:
        return "ten_years"
    return "permanent"


def _nominal(designation: str) -> tuple[int, int] | None:
    parts = designation.split("x")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _convert(check: str, result: Any) -> MemberCheckData:
    return MemberCheckData(
        check=check,
        demand=float(result.demand) * _PA_PER_PSI,
        capacity=float(result.capacity) * _PA_PER_PSI,
        dimension=Dimension.PRESSURE,
        unity=float(result.ratio),
        passes=bool(result.passes),
        provision=str(result.ref),
        factors=tuple(
            ProvisionFactor(
                symbol=str(f.symbol),
                value=float(f.value),
                ref=str(f.ref),
                note=str(f.note or ""),
            )
            for f in result.factors
        ),
    )
