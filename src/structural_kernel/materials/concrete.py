"""Concrete engine: the aciconcrete (ACI 318-19) adapter (ADR 0007).

Concrete is the divergent case, and naming it is part of the preparation. Wood
and steel are *catalog* materials — a member is a designation plus a grade — so
they implement the ``MaterialEngine`` protocol. A concrete member is not: it is
explicit geometry (b, h) plus reinforcement (bar sizes, counts, layers), with
no catalog. aciconcrete reflects this with ``Beam``/``Column`` classes instead
of a unified ``Member``, and LRFD-only results that carry an ``informational``
flag and an ``extra`` bag the others lack.

So concrete does *not* register as a catalog engine. What this module proves is
that the kernel's neutral result vocabulary (``MemberCheckData``) still carries
concrete results faithfully — moment-dimensioned, informational results
skipped, provision and factor trail intact. Concrete becomes a full engine when
the phase-2 concrete framing decision kind (carrying b, h, reinforcement)
exists to describe its members; this adapter is where that wiring will land.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from structural_kernel.materials.base import MemberCheckData, ProvisionFactor
from structural_kernel.units import UNITS, Dimension

_M_PER_IN = UNITS["in"].si_factor
_N_PER_LBF = UNITS["lbf"].si_factor
_NM_PER_LBIN = _N_PER_LBF * _M_PER_IN

CODE = "ACI 318-19"


@dataclass(frozen=True, slots=True)
class ConcreteBeam:
    """A reinforced rectangular beam, canonical SI in / reinforcement neutral."""

    breadth_m: float
    depth_to_steel_m: float  # d
    steel_area_m2: float  # As
    fc_pa: float  # concrete compressive strength
    rebar_grade: str = "Gr60"


def check_beam_flexure(beam: ConcreteBeam, moment_nm: float) -> MemberCheckData:
    """ACI flexural design check, re-expressed in kernel vocabulary."""
    from aciconcrete import Beam, Concrete, rebar

    member: Any = Beam(
        b=beam.breadth_m / _M_PER_IN,
        d=beam.depth_to_steel_m / _M_PER_IN,
        As=beam.steel_area_m2 / _M_PER_IN**2,
        concrete=Concrete(fc=beam.fc_pa / UNITS["psi"].si_factor),
        steel=rebar(beam.rebar_grade),
    )
    result: Any = member.check_flexure(Mu_inlb=moment_nm / _NM_PER_LBIN)
    return _convert("bending", result, Dimension.MOMENT, _NM_PER_LBIN)


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
    )
