"""Decision-kind parameter schemas (design doc 0001 §2.3; increment 2).

The ``Decision`` envelope stores ``params`` as JSON; each kind gets its schema
here. Validation stage 1 parses params against the kind's model, so a
mis-shaped or mis-dimensioned parameter is a rejected changeset, not a latent
bug. The kind union is closed in phase 1 — a non-exhaustive ``match`` over it
is a bug (``assert_never``).

Grid lines carry stable ``line_id``s (ADR 0005): the canonical identity that
eids and other decisions' params reference. Display names are presentation.
"""

from __future__ import annotations

from typing import Annotated, Literal, assert_never

from pydantic import AfterValidator, Field, JsonValue, StringConstraints, model_validator

from structural_kernel.ids import LineId
from structural_kernel.materials import families
from structural_kernel.objects import Decision, Eid, IsoDate, KernelModel, SurveyedAnchor
from structural_kernel.units import (
    Dimension,
    LengthQuantity,
    MoneyPerTimeQuantity,
    MoneyQuantity,
    PressureQuantity,
    Quantity,
    TimeQuantity,
)

Name = Annotated[str, StringConstraints(min_length=1)]


def _registered_family(value: str) -> str:
    if value not in families():
        raise ValueError(
            f"material family {value!r} has no registered design-check engine; "
            f"registered: {sorted(families())}"
        )
    return value


# A catalog material family with a registered engine (ADR 0007). Open by
# design — the set grows as engines register, without a schema edit.
MaterialFamily = Annotated[str, StringConstraints(min_length=1), AfterValidator(_registered_family)]


# -- grid ----------------------------------------------------------------------


class GridLine(KernelModel):
    line_id: LineId
    name: Name  # display only — never enters an eid or a reference (ADR 0005 E1)
    axis: Literal["x", "y"]  # the coordinate this line holds constant
    offset: LengthQuantity  # from the grid origin, along `axis`


class GridParams(KernelModel):
    lines: list[GridLine] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> GridParams:
        ids = [line.line_id for line in self.lines]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate line_id in grid")
        names = [(line.axis, line.name) for line in self.lines]
        if len(set(names)) != len(names):
            raise ValueError("duplicate line name on one axis")
        return self

    def line_ids(self) -> set[str]:
        return {line.line_id for line in self.lines}


# -- levels ---------------------------------------------------------------------


class Level(KernelModel):
    level_id: Name  # opaque stable token, same posture as line_id
    name: Name
    elevation: LengthQuantity


class LevelsParams(KernelModel):
    levels: list[Level] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> LevelsParams:
        ids = [level.level_id for level in self.levels]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate level_id")
        return self


# -- load assumptions -------------------------------------------------------------

LoadCase = Literal["D", "L", "Lr", "S", "W", "E"]


class AreaLoad(KernelModel):
    case: LoadCase
    magnitude: PressureQuantity


class LoadAssumptionsParams(KernelModel):
    area_loads: list[AreaLoad] = Field(min_length=1)
    # The combination set unity is measured against (loads.py is the engine).
    # ASD for wood (NDS), LRFD for steel (AISC) — a closed literal over the sets
    # loads.py can build; each candidate of a heterogeneous exploration selects
    # the set its material's code requires.
    combo_set: Literal["ASCE7-22-2.4-ASD", "ASCE7-22-2.3-LRFD"]


# -- gravity framing strategy ------------------------------------------------------


class GridRegion(KernelModel):
    """A rectangular grid extent bounded by stable line-ids."""

    x_from: LineId
    x_to: LineId
    y_from: LineId
    y_to: LineId


class GravityFramingStrategyParams(KernelModel):
    """A rule, not a member list (design doc 0001 §2.3)."""

    region: GridRegion
    system: Literal["joists_on_beams_on_posts"]
    joist_axis: Literal["x", "y"]  # the axis joists span along
    joist_spacing: LengthQuantity
    # Which material engine designs these members (ADR 0007 registry key).
    # Phase-1 framing is sawn lumber (review Q1); the field is validated against
    # the registered catalog engines so a steel framing rule needs no schema
    # change here, only its own decision kind.
    member_family: MaterialFamily
    # Reference stiffness/strength come from this grade via the material engine;
    # the *choice* of grade is this decision's to make, never a code constant.
    member_grade: Name
    # Review Q4: sizes are decision parameters; explorations vary them.
    joist_section: Name
    beam_section: Name
    post_section: Name


# -- steel framing strategy --------------------------------------------------------


class SteelFramingStrategyParams(KernelModel):
    """A three-tier steel gravity frame (ADR 0008): infill beams → girders →
    columns. Beams span ``beam_axis`` at ``beam_spacing``, bearing on girders
    that run on the two perpendicular bearing lines; girders span between
    columns at the region corners.

    Designed to AISC 360-22 **LRFD** (Mark's call): the steel branch of a
    heterogeneous exploration carries LRFD strength combinations, while the wood
    branch stays NDS/ASD — each system to its own code, ranked on the
    method-neutral mass metric. The roof deck braces the beam compression flange
    continuously (Lb=0), so flexure reaches the full plastic moment.
    """

    region: GridRegion
    system: Literal["beams_on_girders_on_columns"]
    beam_axis: Literal["x", "y"]  # the axis infill beams span along
    beam_spacing: LengthQuantity
    # ADR 0007 registry key — validated against the registered catalog engines,
    # the same posture as gravity_framing_strategy. A steel_framing_strategy
    # names a steel family (e.g. "hot_rolled_steel"); the kind, not this field,
    # is what makes it steel.
    member_family: MaterialFamily
    member_grade: Name  # e.g. "A992"
    # W-shape designations per tier; explorations vary them (standing req. 1).
    beam_section: Name
    girder_section: Name
    column_section: Name


# -- lateral strategy ---------------------------------------------------------------


class LateralStrategyParams(KernelModel):
    """Representational only in phase 1 (review Q7): designated shear-wall lines."""

    wall_lines: list[LineId] = Field(min_length=1)


# -- opening -------------------------------------------------------------------------


class OpeningParams(KernelModel):
    """Dimensions and location only; no reason modeled (charter). Derivation of
    the enclosing framing induces the header."""

    wall_line: LineId
    offset_from: LineId  # reference line for the offset along the wall
    offset: LengthQuantity
    width: LengthQuantity
    height: LengthQuantity


# -- exception ------------------------------------------------------------------------


class ExceptionParams(KernelModel):
    """A targeted design override of another rule's output (§2.3, ADR 0005).

    References its target by eid; a vanished target is a hard
    ``dangling_exception`` error at validation. The optional location hint
    lets that error propose candidate re-targets.
    """

    target_eid: Eid
    field: Name
    value: JsonValue
    location_hint: SurveyedAnchor | None = None


# -- cost basis (standing req. 3; ADR 0012) ----------------------------------------

_MATERIAL_RATE_DIMENSIONS = frozenset({Dimension.MONEY_PER_MASS, Dimension.MONEY_PER_VOLUME})


class MaterialRate(KernelModel):
    """The unit material cost of one family. The rate's *dimension* selects the
    priced quantity: a ``USD/lb`` (money-per-mass) rate prices the member's mass,
    a ``USD/BF`` (money-per-volume) rate its nominal board-foot volume (Mark's
    call: steel by weight, sawn lumber by nominal board-feet). Nothing hardcodes
    'steel is priced by weight' — the unit tag carries it."""

    family: MaterialFamily
    rate: Quantity

    @model_validator(mode="after")
    def _priced_by_mass_or_volume(self) -> MaterialRate:
        if self.rate.dimension not in _MATERIAL_RATE_DIMENSIONS:
            raise ValueError(
                f"material rate for {self.family!r} must be money-per-mass (e.g. USD/lb) "
                f"or money-per-volume (e.g. USD/BF); got {self.rate.unit!r} "
                f"({self.rate.dimension})"
            )
        return self


class FamilyLeadTime(KernelModel):
    """A family's fabrication/delivery lead time. Annotates a ranking (the
    vision's glulam 14-week flag) — it is never priced into installed cost."""

    family: MaterialFamily
    lead_time: TimeQuantity  # authored in weeks


class CostBasisParams(KernelModel):
    """A versioned cost assumption: unit costs, crew rate, installation
    productivities, lead times, an as-of date, a region label, and the
    uncertainty band a ranking cites (ADR 0012). Committed as an ordinary
    decision; a revised basis (the fabricator's re-quote) is a *new* cost_basis
    decision, so every ranking cites exactly what it was priced under."""

    region: Name
    as_of: IsoDate
    material_rates: list[MaterialRate] = Field(min_length=1)
    # Installation drivers (Mark's model): connections priced per connection;
    # erection hours = piece_count * hours_per_piece + crane_picks * hours_per_pick,
    # costed at the crew rate.
    connection_cost: MoneyQuantity
    crew_rate: MoneyPerTimeQuantity
    hours_per_piece: TimeQuantity
    hours_per_pick: TimeQuantity
    lead_times: list[FamilyLeadTime] = Field(default_factory=list[FamilyLeadTime])
    # A close comparison is "inside the noise": two installed costs within this
    # percentage are a coin flip, not a verdict. A dimensionless ratio (like
    # unity), so a plain percent — but committed on the basis, never hardcoded.
    uncertainty_pct: float = Field(default=4.0, gt=0.0, lt=100.0)

    @model_validator(mode="after")
    def _one_rate_per_family(self) -> CostBasisParams:
        families_seen = [r.family for r in self.material_rates]
        if len(set(families_seen)) != len(families_seen):
            raise ValueError("duplicate material rate for a family in the cost basis")
        return self


DecisionParams = (
    GridParams
    | LevelsParams
    | LoadAssumptionsParams
    | GravityFramingStrategyParams
    | SteelFramingStrategyParams
    | LateralStrategyParams
    | OpeningParams
    | ExceptionParams
    | CostBasisParams
)


def parse_params(decision: Decision) -> DecisionParams | None:
    """Parse a decision's params against its kind schema.

    ``None`` for an open decision with no params (standing requirement 2).
    Raises ``pydantic.ValidationError`` on mismatch — validation stage 1
    turns that into a structured ``schema_invalid`` rejection.
    """
    payload = decision.params
    if payload is None:
        return None  # envelope guarantees this only happens for state="open"
    match decision.kind:
        case "grid":
            return GridParams.model_validate(payload)
        case "levels":
            return LevelsParams.model_validate(payload)
        case "load_assumptions":
            return LoadAssumptionsParams.model_validate(payload)
        case "gravity_framing_strategy":
            return GravityFramingStrategyParams.model_validate(payload)
        case "steel_framing_strategy":
            return SteelFramingStrategyParams.model_validate(payload)
        case "lateral_strategy":
            return LateralStrategyParams.model_validate(payload)
        case "opening":
            return OpeningParams.model_validate(payload)
        case "exception":
            return ExceptionParams.model_validate(payload)
        case "cost_basis":
            return CostBasisParams.model_validate(payload)
        case _:
            assert_never(decision.kind)


def line_refs(params: DecisionParams | None) -> set[str]:
    """The stable line-ids a decision's params reference — the referential
    integrity substrate for ADR 0005 E3 (a referenced line cannot be deleted
    out from under its referrers)."""
    match params:
        case GravityFramingStrategyParams() | SteelFramingStrategyParams():
            region = params.region
            return {region.x_from, region.x_to, region.y_from, region.y_to}
        case LateralStrategyParams():
            return set(params.wall_lines)
        case OpeningParams():
            return {params.wall_line, params.offset_from}
        case (
            GridParams()
            | LevelsParams()
            | LoadAssumptionsParams()
            | ExceptionParams()
            | CostBasisParams()
            | None
        ):
            return set()
        case _:
            assert_never(params)
