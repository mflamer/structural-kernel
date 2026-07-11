"""Concrete engine: the aciconcrete (ACI 318-19) adapter (ADR 0007, ADR 0014).

Concrete is the divergent case ADR 0007 deliberately carved out: a member is
explicit geometry (b, h) plus reinforcement, not a catalog designation. ADR 0014
cashes that check. The resolution: a rectangular concrete section is a
*systematic* catalog — the designation is parseable geometry ("304.8x609.6" =
b-by-h in mm) — so ``section_properties``, ``elastic_modulus_pa`` (Ec from the mix
designation, ACI 19.2.2.1), ``mass_density_kg_m3``, and ``nominal_volume_m3``
(placed volume, concrete's trade pricing basis) all serve the ordinary
``MaterialEngine`` protocol. Reinforcement — the one member fact a designation
cannot carry — travels on the check requests as ``ReinforcementData`` (the
note-0006 boundary finding: one additive request field; ``MemberCheckData`` and
the registry shape unchanged).

Every aciconcrete import lives here; bar tables (``bar_area``) stay behind this
adapter, and the kernel persists bar designations ("#8") as opaque names exactly
as it does "W10x12" and "2x10". Reinforcement is authored-and-checked
(single-pass, the ADR 0014 staging decision): the engine *checks* the authored
bars against demand; sizing-to-demand is the deferred staged-derivation lift.
Columns check concentric axial (ACI 22.4.2) — parity with the axial-only
gravity idealization wood posts and steel columns get; P-M interaction
(available in aciconcrete) lands when the idealization delivers column moments.
Concrete designs LRFD-only per ACI 318.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import re
from typing import Any

from structural_kernel.materials.base import (
    AxialRequest,
    FlexureRequest,
    MemberCheckData,
    ProvisionFactor,
    ReinforcementData,
    SectionProperties,
)
from structural_kernel.units import UNITS, Dimension

_M_PER_IN = UNITS["in"].si_factor
_N_PER_LBF = UNITS["lbf"].si_factor
_NM_PER_LBIN = _N_PER_LBF * _M_PER_IN
_PA_PER_PSI = UNITS["psi"].si_factor

# Normalweight reinforced concrete, ~150 pcf — the standard takeoff density.
_CONCRETE_DENSITY_KG_M3 = 2400.0

_DESIGNATION = re.compile(r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$")
_MIX = re.compile(r"^(\d+(?:\.\d+)?)psi$")


def section_designation(breadth_m: float, depth_m: float) -> str:
    """The canonical dimensioned designation: b-by-h in mm, ``:g``-formatted
    ("304.8x609.6"). Derivation renders it; the engine parses it — one format,
    defined here, round-trip exact."""
    return f"{breadth_m * 1000:g}x{depth_m * 1000:g}"


def _parse_designation(designation: str) -> tuple[float, float] | None:
    """Parse "b x h" (mm) back to canonical metres. None for a non-dimensioned
    designation — the same "not ours" answer a catalog miss gives."""
    match = _DESIGNATION.match(designation)
    if match is None:
        return None
    return float(match.group(1)) / 1000.0, float(match.group(2)) / 1000.0


def _parse_mix(grade: str) -> float | None:
    """A concrete mix designation is its specified strength: "4000psi" → f'c in
    psi. None for anything else."""
    match = _MIX.match(grade)
    if match is None:
        return None
    return float(match.group(1))


class ConcreteEngine:
    """ACI 318-19 cast-in-place member design via aciconcrete (ADR 0014)."""

    family = "cast_in_place_concrete"

    @property
    def code(self) -> str:
        from aciconcrete import EDITION

        return str(EDITION)

    def section_properties(self, designation: str) -> SectionProperties | None:
        parsed = _parse_designation(designation)
        if parsed is None:
            return None
        b, h = parsed
        # Gross (uncracked) rectangular section — the ADR 0014 analysis
        # idealization; effective-inertia (Ie) refinement is deferred.
        return SectionProperties(
            breadth_m=b,
            depth_m=h,
            area_m2=b * h,
            i_strong_m4=b * h**3 / 12.0,
            i_weak_m4=h * b**3 / 12.0,
        )

    def elastic_modulus_pa(self, grade: str) -> float | None:
        fc_psi = _parse_mix(grade)
        if fc_psi is None:
            return None
        from aciconcrete import Concrete

        return float(Concrete(fc=fc_psi).Ec) * _PA_PER_PSI  # ACI 19.2.2.1

    def mass_density_kg_m3(self, grade: str) -> float | None:
        return _CONCRETE_DENSITY_KG_M3

    def nominal_volume_m3(self, designation: str, length_m: float) -> float | None:
        parsed = _parse_designation(designation)
        if parsed is None:
            return None
        b, h = parsed
        return b * h * length_m  # placed volume — concrete's trade pricing basis

    def crane_picks_per_member(self) -> int:
        return 0  # cast in place: formed, not picked (PO call; precast is a later family)

    def check_flexure(self, request: FlexureRequest) -> list[MemberCheckData]:
        b, h, reinforcement = self._dimensioned(request.designation, request.reinforcement)
        _require_lrfd(request.method)
        from aciconcrete import Beam, bar_area

        d = h - reinforcement.cover_m  # cover is to the tension-steel centroid (PO call)
        member: Any = Beam(
            b=b / _M_PER_IN,
            d=d / _M_PER_IN,
            As=bar_area(reinforcement.bar, reinforcement.bars),
            concrete=self._concrete(request.grade),
            steel=self._rebar(reinforcement.grade),
            h=h / _M_PER_IN,
        )
        flexure: Any = member.check_flexure(Mu_inlb=request.moment_nm / _NM_PER_LBIN)
        if reinforcement.stirrup_bar is not None and reinforcement.stirrup_spacing_m is not None:
            av_in2 = bar_area(reinforcement.stirrup_bar, 2)  # two-leg stirrup
            s_in = reinforcement.stirrup_spacing_m / _M_PER_IN
        else:
            av_in2, s_in = 0.0, None  # unstirruped: Vc alone
        shear: Any = member.check_shear(
            Vu_lb=request.shear_n / _N_PER_LBF, Av_in2=av_in2, s_in=s_in
        )
        return [
            _convert("bending", flexure, Dimension.MOMENT, _NM_PER_LBIN),
            _convert("shear", shear, Dimension.FORCE, _N_PER_LBF),
        ]

    def check_axial(self, request: AxialRequest) -> MemberCheckData:
        b, h, reinforcement = self._dimensioned(request.designation, request.reinforcement)
        _require_lrfd(request.method)
        if request.sense != "compression":
            raise ValueError(
                "cast_in_place_concrete checks axial compression only in phase 2; "
                "an axially-tensioned concrete member needs its own treatment"
            )
        from aciconcrete import Column, bar_area

        member: Any = Column(
            b=b / _M_PER_IN,
            h=h / _M_PER_IN,
            Ast=bar_area(reinforcement.bar, reinforcement.bars),
            concrete=self._concrete(request.grade),
            steel=self._rebar(reinforcement.grade),
            transverse=reinforcement.transverse,
        )
        # Concentric phi*Pn,max (ACI 22.4.2) — parity with the axial-only gravity
        # idealization; interaction lands when column moments exist (ADR 0014).
        result: Any = member.check_axial_compression(Pu_lb=request.force_n / _N_PER_LBF)
        return _convert("compression", result, Dimension.FORCE, _N_PER_LBF)

    def _dimensioned(
        self, designation: str, reinforcement: ReinforcementData | None
    ) -> tuple[float, float, ReinforcementData]:
        parsed = _parse_designation(designation)
        if parsed is None:
            raise ValueError(
                f"{designation!r} is not a dimensioned concrete designation (expected 'bxh' in mm)"
            )
        if reinforcement is None:
            raise ValueError(
                "a concrete check needs ReinforcementData on the request — a dimensioned "
                "member's reinforcement cannot ride the designation (ADR 0014)"
            )
        return parsed[0], parsed[1], reinforcement

    def _concrete(self, grade: str) -> Any:
        fc_psi = _parse_mix(grade)
        if fc_psi is None:
            raise ValueError(
                f"{grade!r} is not a concrete mix designation (expected e.g. '4000psi')"
            )
        from aciconcrete import Concrete

        return Concrete(fc=fc_psi)

    def _rebar(self, grade: str) -> Any:
        from aciconcrete import rebar

        return rebar(grade)


def _require_lrfd(method: str) -> None:
    if method != "LRFD":
        raise ValueError("cast_in_place_concrete designs LRFD-only (ACI 318 strength design)")


def _convert(check: str, result: Any, dimension: Dimension, si_per_unit: float) -> MemberCheckData:
    # Concrete results may be informational (Ie, Mc): their pass/fail is
    # meaningless, so treat those as always-passing annotations.
    informational = bool(getattr(result, "informational", False))
    return MemberCheckData(
        check=check,
        demand=float(result.demand) * si_per_unit,
        capacity=float(result.capacity) * si_per_unit,
        dimension=dimension,
        unity=float(result.ratio),
        passes=True if informational else bool(result.passes),
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
