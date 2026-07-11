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
class ReinforcementData:
    """Reinforcement for a *dimensioned* (non-catalog) member — the one
    member-description fact a designation string cannot carry (ADR 0014, the
    note-0006 boundary finding: the request vocabulary was catalog-shaped and
    needed exactly this additive extension). Catalog engines ignore it; a
    dimensioned family requires it on its check requests. Fields are the
    *authored* vocabulary — bar count + designation + cover — and the family
    engine resolves areas and depths (bar tables stay behind the adapter)."""

    bars: int  # longitudinal count (tension steel for flexure; total for axial)
    bar: str  # bar designation resolved by the family engine (e.g. "#8")
    cover_m: float  # to the tension-steel centroid: d = depth - cover (PO call)
    grade: str = "Gr60"
    stirrup_bar: str | None = None  # None = unstirruped (Av = 0)
    stirrup_spacing_m: float | None = None
    transverse: Literal["ties", "spirals"] = "ties"


@dataclass(frozen=True, slots=True)
class FlexureRequest:
    """Verify a member as a flexural member. Neutral fields; each engine reads
    the ones its code uses (wood: load_cases→duration, repetitive→Cr; steel:
    unbraced_length→Lb, cb; concrete: reinforcement, ignoring both)."""

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
    reinforcement: ReinforcementData | None = None  # dimensioned families only


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
    reinforcement: ReinforcementData | None = None  # dimensioned families only


class MaterialEngine(Protocol):
    """A verified code library adapted to the kernel. Catalog materials (wood,
    steel) resolve a designation against a published table; a *dimensioned*
    family (cast-in-place concrete, ADR 0014) serves the same protocol from a
    systematic designation — "304.8x609.6" is parseable b-by-h geometry — with
    reinforcement (the fact a designation cannot carry) travelling on the check
    requests. The ``MemberCheckData`` vocabulary is unchanged either way — the
    ADR 0007 boundary, confirmed under a real concrete decision kind."""

    @property
    def family(self) -> str: ...

    @property
    def code(self) -> str: ...

    def section_properties(self, designation: str) -> SectionProperties | None: ...

    def elastic_modulus_pa(self, grade: str) -> float | None: ...

    def mass_density_kg_m3(self, grade: str) -> float | None: ...

    # -- takeoff for costing (ADR 0012) --------------------------------------
    # Quantity facts, alongside section_properties / mass_density. The cost
    # basis prices mass or volume per family; a family exposes whichever its
    # trade quotes. `None` means "this family is not priced this way".

    def nominal_volume_m3(self, designation: str, length_m: float) -> float | None:
        """The nominal volume of one member, where volume is the family's trade
        pricing basis — lumber's board-feet, concrete's placed volume. Steel,
        priced by weight, returns None."""
        ...

    def crane_picks_per_member(self) -> int:
        """Crane lifts to erect one member of this family — the installation
        driver that separates a craned system from a hand-set one (phase-2
        simplification: a family-level fact; glulam-vs-sawn refinement later)."""
        ...

    def check_flexure(self, request: FlexureRequest) -> list[MemberCheckData]: ...

    def check_axial(self, request: AxialRequest) -> MemberCheckData: ...
