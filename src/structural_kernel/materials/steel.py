"""Steel engine: the aiscsteel (AISC 360-22) adapter (ADR 0007).

Every aiscsteel import lives here. Kernel canonical SI ⇄ aiscsteel's
kip/kip-ft/ft floats is converted once; its ``CheckResult`` — including the
governing limit state and the phi/Omega factor trail with AISC references —
becomes kernel ``MemberCheckData``. Unlike wood, steel flexure and axial checks
are moment/force-based, so results are MOMENT- and FORCE-dimensioned.

Phase-1 preparation: the doubly-symmetric catalog shapes (W/M/S/HP and HSS)
this covers exercise the whole adapter; steel is not yet wired into a framing
decision kind (that, and heterogeneous exploration, is the phase-2 lift the
representation review gates).
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
_M_PER_FT = UNITS["ft"].si_factor
_N_PER_KIP = UNITS["kip"].si_factor
_NM_PER_KIPFT = UNITS["kip*ft"].si_factor
_STEEL_DENSITY_KG_M3 = 7849.0  # ~490 pcf, all structural steel grades


class SteelEngine:
    """AISC 360-22 hot-rolled / HSS member design via aiscsteel."""

    family = "hot_rolled_steel"

    @property
    def code(self) -> str:
        from aiscsteel import EDITION

        return str(EDITION)

    def section_properties(self, designation: str) -> SectionProperties | None:
        from aiscsteel import has, shape

        if not has(designation):
            return None
        s: Any = shape(designation)
        return SectionProperties(
            breadth_m=float(s.get("bf", s.get("B", 0.0))) * _M_PER_IN,
            depth_m=float(s.get("d", s.get("Ht", s.get("OD", 0.0)))) * _M_PER_IN,
            area_m2=float(s.A) * _M_PER_IN**2,
            i_strong_m4=float(s.Ix) * _M_PER_IN**4,
            i_weak_m4=float(s.Iy) * _M_PER_IN**4,
        )

    def elastic_modulus_pa(self, grade: str) -> float | None:
        from aiscsteel import E_KSI

        return float(E_KSI) * 1000.0 * UNITS["psi"].si_factor

    def mass_density_kg_m3(self, grade: str) -> float | None:
        return _STEEL_DENSITY_KG_M3

    def nominal_volume_m3(self, designation: str, length_m: float) -> float | None:
        return None  # steel is priced by weight, not by volume

    def crane_picks_per_member(self) -> int:
        return 1  # each primary steel member is a crane pick (Mark's phase-2 call)

    def check_flexure(self, request: FlexureRequest) -> list[MemberCheckData]:
        member = self._member(request.designation, request.grade, request.method)
        axis = "x" if request.axis == "strong" else "y"
        flexure: Any = member.check_flexure(
            M_kipft=request.moment_nm / _NM_PER_KIPFT,
            axis=axis,
            Lb_ft=request.unbraced_length_m / _M_PER_FT,
            Cb=request.cb,
        )
        shear: Any = member.check_shear(V_kip=request.shear_n / _N_PER_KIP)
        return [
            _convert("bending", flexure, Dimension.MOMENT, _NM_PER_KIPFT),
            _convert("shear", shear, Dimension.FORCE, _N_PER_KIP),
        ]

    def check_axial(self, request: AxialRequest) -> MemberCheckData:
        member = self._member(request.designation, request.grade, request.method)
        length_ft = request.unbraced_length_m / _M_PER_FT
        if request.sense == "tension":
            result: Any = member.check_tension(T_kip=request.force_n / _N_PER_KIP)
            return _convert("tension", result, Dimension.FORCE, _N_PER_KIP)
        result = member.check_compression(
            P_kip=request.force_n / _N_PER_KIP, Lcx_ft=length_ft, Lcy_ft=length_ft
        )
        return _convert("compression", result, Dimension.FORCE, _N_PER_KIP)

    def _member(self, designation: str, grade: str, method: str) -> Any:
        from aiscsteel import Member, steel

        material = None
        if grade:
            try:
                material = steel(grade)
            except Exception:
                material = None
        return Member(section=designation, material=material, method=method)


def _convert(check: str, result: Any, dimension: Dimension, si_per_unit: float) -> MemberCheckData:
    return MemberCheckData(
        check=check,
        demand=float(result.demand) * si_per_unit,
        capacity=float(result.capacity) * si_per_unit,
        dimension=dimension,
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
        governing=str(getattr(result, "governing", "") or ""),
    )
