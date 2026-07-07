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

from pydantic import Field, JsonValue, StringConstraints, model_validator

from structural_kernel.ids import LineId
from structural_kernel.objects import Decision, Eid, KernelModel, SurveyedAnchor
from structural_kernel.units import LengthQuantity, PressureQuantity

Name = Annotated[str, StringConstraints(min_length=1)]


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
    # Review Q2: ASD combos define unity in phase 1. A closed literal until a
    # second combo set actually exists.
    combo_set: Literal["ASCE7-22-2.4-ASD"]


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
    member_family: Literal["sawn_lumber"]  # review Q1: phase 1 is sawn lumber
    # Review Q4: sizes are decision parameters; explorations vary them.
    joist_section: Name
    beam_section: Name
    post_section: Name


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


DecisionParams = (
    GridParams
    | LevelsParams
    | LoadAssumptionsParams
    | GravityFramingStrategyParams
    | LateralStrategyParams
    | OpeningParams
    | ExceptionParams
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
        case "lateral_strategy":
            return LateralStrategyParams.model_validate(payload)
        case "opening":
            return OpeningParams.model_validate(payload)
        case "exception":
            return ExceptionParams.model_validate(payload)
        case _:
            assert_never(decision.kind)


def line_refs(params: DecisionParams | None) -> set[str]:
    """The stable line-ids a decision's params reference — the referential
    integrity substrate for ADR 0005 E3 (a referenced line cannot be deleted
    out from under its referrers)."""
    match params:
        case GravityFramingStrategyParams():
            region = params.region
            return {region.x_from, region.x_to, region.y_from, region.y_to}
        case LateralStrategyParams():
            return set(params.wall_lines)
        case OpeningParams():
            return {params.wall_line, params.offset_from}
        case GridParams() | LevelsParams() | LoadAssumptionsParams() | ExceptionParams() | None:
            return set()
        case _:
            assert_never(params)
