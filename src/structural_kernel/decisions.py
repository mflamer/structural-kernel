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


# -- cost basis: a table of priced factors (standing req. 3; ADR 0012, note 0003) --
#
# A cost basis is not a record of named price fields (`erected_steel_usd_per_lb`,
# `crew_rate`, …) — that calcifies the moment a new driver (formwork, a carbon
# price, a regional multiplier) appears. It is a *list of factors*, each pricing a
# countable the derived model emits (`costing.py` owns the quantity kinds). Adding
# a cost driver is appending a factor row; material-only vs installed cost is which
# factors are present, not two schemas. The registry-not-enum move (ADR 0004/0007)
# applied to cost.

# The money-rate dimension a `direct` price must carry to price a quantity of a
# given kind-dimension: weight (MASS) wants USD/kg, board-feet (VOLUME) USD/m3, a
# count (None) plain USD-each. The rate's dimension is the switch; nothing
# hardcodes "steel by weight".
_MONEY_DIM_FOR: dict[Dimension | None, Dimension] = {
    Dimension.MASS: Dimension.MONEY_PER_MASS,
    Dimension.VOLUME: Dimension.MONEY_PER_VOLUME,
    None: Dimension.MONEY,
}


class FactorScope(KernelModel):
    """Restricts a factor to part of the model — a family ("steel weight"), a role,
    or both. Absent = the whole model."""

    family: MaterialFamily | None = None
    role: Name | None = None


class DirectPrice(KernelModel):
    """A unit price per unit of the quantity kind — ``USD/lb`` over weight,
    ``USD/BF`` over board-feet, ``USD`` each over a count. Summed into cost."""

    kind: Literal["direct"] = "direct"
    unit_price: Quantity


class LaborPrice(KernelModel):
    """Labor over a countable: ``crew_rate * productivity * count`` (Mark's call —
    keep the crew rate and productivity explicit basis data). Productivity is a
    means-and-methods assumption that lives on the *basis*, never in derivation, so
    re-ranking under a revised rate still touches no stored physics. Applies to a
    count kind (picks, pieces, connections). Summed into cost."""

    kind: Literal["labor"] = "labor"
    crew_rate: MoneyPerTimeQuantity
    productivity: TimeQuantity  # hours per one of the counted items


class FlagAnnotation(KernelModel):
    """A factor that annotates but never sums into cost (the vision's glulam
    14-week lead time). It fires when the scoped quantity is present; ``note_value``
    is the thing to surface (a duration), not a dollar."""

    kind: Literal["flag"] = "flag"
    note_value: Quantity


FactorPricing = Annotated[DirectPrice | LaborPrice | FlagAnnotation, Field(discriminator="kind")]


class CostFactor(KernelModel):
    """One priced factor: a quantity kind (a countable the derived model emits),
    an optional scope, a pricing, and provenance for the number."""

    quantity_kind: Name
    scope: FactorScope | None = None
    pricing: FactorPricing
    source: Name  # where the number came from: a regional table + date, a quote, an assumption

    @model_validator(mode="after")
    def _kind_registered_and_price_agrees(self) -> CostFactor:
        from structural_kernel.costing import quantity_kind, quantity_kinds

        kind = quantity_kind(self.quantity_kind)
        if kind is None:
            raise ValueError(
                f"cost factor names quantity_kind {self.quantity_kind!r}, which no derived "
                f"countable provides; registered kinds: {sorted(quantity_kinds())}"
            )
        pricing = self.pricing
        if isinstance(pricing, DirectPrice):
            expected = _MONEY_DIM_FOR.get(kind.dimension)
            if expected is None:
                raise ValueError(
                    f"no money rate is defined for pricing a {kind.dimension} quantity "
                    f"({self.quantity_kind!r})"
                )
            if pricing.unit_price.dimension is not expected:
                raise ValueError(
                    f"factor over {self.quantity_kind!r} ({kind.dimension}) needs a {expected} "
                    f"unit price; got {pricing.unit_price.unit!r} ({pricing.unit_price.dimension})"
                )
        elif isinstance(pricing, LaborPrice) and kind.dimension is not None:
            raise ValueError(
                f"labor pricing applies to a count kind; {self.quantity_kind!r} is "
                f"{kind.dimension} — price it directly instead"
            )
        return self


class CostBasisParams(KernelModel):
    """A versioned cost assumption: a factor table, a region label, an as-of date,
    and the uncertainty band a ranking cites (ADR 0012, note 0003). Committed as an
    ordinary decision; a revised basis (the fabricator's re-quote) is a *new*
    cost_basis decision, so every ranking cites exactly what it was priced under."""

    region: Name
    as_of: IsoDate
    factors: list[CostFactor] = Field(min_length=1)
    # A close comparison is "inside the noise": two installed costs within this
    # percentage are a coin flip, not a verdict. A dimensionless ratio (like
    # unity), so a plain percent — but committed on the basis, never hardcoded.
    uncertainty_pct: float = Field(default=4.0, gt=0.0, lt=100.0)


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
