"""The material-engine adapter boundary: neutral types and the protocol.

Design-check demands and capacities are *not* always stresses: wood member
checks are stress-based (fb vs Fb'), steel and concrete flexure are
moment-based, shear and axial are force-based. So ``MemberCheckData`` carries a
tagged SI magnitude with its dimension, not a bare Pascal — the one place the
wood-only ``demand_pa`` assumption is generalized. Everything else in the
result vocabulary (unity, pass/fail, provision citation, factor trail) is
already material-neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from structural_kernel.units import Dimension

CheckName = str  # "bending" | "shear" | "compression" | "tension" | ...
Method = Literal["ASD", "LRFD"]


@dataclass(frozen=True, slots=True)
class SectionProperties:
    """Canonical-SI section properties of a catalog section."""

    breadth_m: float
    depth_m: float
    area_m2: float
    i_strong_m4: float
    i_weak_m4: float


@dataclass(frozen=True, slots=True)
class ProvisionFactor:
    """One entry of a check's factor audit trail — carries its code reference."""

    symbol: str
    value: float
    ref: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class MemberCheckData:
    """One code check, re-expressed in kernel vocabulary (canonical SI)."""

    check: CheckName
    demand: float  # canonical SI magnitude in `dimension`
    capacity: float
    dimension: Dimension  # PRESSURE (stress) | MOMENT | FORCE
    unity: float
    passes: bool
    provision: str
    factors: tuple[ProvisionFactor, ...] = ()
    governing: str = ""  # governing limit-state name where the engine reports one


@dataclass(frozen=True, slots=True)
class FlexureRequest:
    """Verify a member as a flexural member. Neutral fields; each engine reads
    the ones its code uses (wood: load_cases→duration, repetitive→Cr; steel:
    unbraced_length→Lb, cb; concrete ignores both)."""

    designation: str
    grade: str
    moment_nm: float
    shear_n: float
    span_m: float
    unbraced_length_m: float = 0.0  # 0 = continuously braced
    axis: Literal["strong", "weak"] = "strong"
    method: Method = "ASD"
    load_cases: frozenset[str] = field(default_factory=frozenset[str])
    repetitive: bool = False
    cb: float = 1.0


@dataclass(frozen=True, slots=True)
class AxialRequest:
    """Verify a member as an axial member."""

    designation: str
    grade: str
    force_n: float
    sense: Literal["compression", "tension"] = "compression"
    unbraced_length_m: float = 0.0
    method: Method = "ASD"
    load_cases: frozenset[str] = field(default_factory=frozenset[str])


class MaterialEngine(Protocol):
    """A verified code library adapted to the kernel. Fits catalog-section
    materials (wood, steel). Concrete's dimensional-plus-reinforced members
    need the richer decision kinds of phase 2 and are not a catalog engine
    (ADR 0007) — but the same ``MemberCheckData`` vocabulary still carries
    their results."""

    @property
    def family(self) -> str: ...

    @property
    def code(self) -> str: ...

    def section_properties(self, designation: str) -> SectionProperties | None: ...

    def elastic_modulus_pa(self, grade: str) -> float | None: ...

    def mass_density_kg_m3(self, grade: str) -> float | None: ...

    def check_flexure(self, request: FlexureRequest) -> list[MemberCheckData]: ...

    def check_axial(self, request: AxialRequest) -> MemberCheckData: ...
