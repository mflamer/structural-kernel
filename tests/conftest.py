"""Shared builders: the milestone one-story structure as decision payloads."""

from pydantic import JsonValue

from structural_kernel.decisions import (
    AreaLoad,
    CostBasisParams,
    FamilyLeadTime,
    GravityFramingStrategyParams,
    GridLine,
    GridParams,
    GridRegion,
    LateralStrategyParams,
    Level,
    LevelsParams,
    LoadAssumptionsParams,
    MaterialRate,
    OpeningParams,
    SteelFramingStrategyParams,
)
from structural_kernel.ids import new_ulid
from structural_kernel.objects import Author, Decision, KernelModel
from structural_kernel.units import Quantity


def ft(value: float) -> Quantity:
    return Quantity(mag=value, unit="ft")


def inches(value: float) -> Quantity:
    return Quantity(mag=value, unit="in")


def psf(value: float) -> Quantity:
    return Quantity(mag=value, unit="psf")


AUTHOR = Author(kind="human", id="mark")
T0 = "2026-07-07T22:00:00Z"

# Stable line-ids for the test grid (minted once; tests need determinism, not
# freshness). Display names "1"/"2" run east-west (constant y is wrong way
# around: axis is the coordinate the line holds constant).
LX1 = "L000000A1"  # x = 0 ft, named "1"
LX2 = "L000000A2"  # x = 24 ft, named "2"
LY_A = "L000000B1"  # y = 0 ft, named "A"
LY_B = "L000000B2"  # y = 14 ft, named "B"


def grid_params() -> GridParams:
    return GridParams(
        lines=[
            GridLine(line_id=LX1, name="1", axis="x", offset=ft(0.0)),
            GridLine(line_id=LX2, name="2", axis="x", offset=ft(24.0)),
            GridLine(line_id=LY_A, name="A", axis="y", offset=ft(0.0)),
            GridLine(line_id=LY_B, name="B", axis="y", offset=ft(14.0)),
        ]
    )


def levels_params() -> LevelsParams:
    return LevelsParams(levels=[Level(level_id="LV1", name="Level 1", elevation=ft(10.0))])


def loads_params() -> LoadAssumptionsParams:
    return LoadAssumptionsParams(
        area_loads=[
            AreaLoad(case="D", magnitude=psf(15.0)),
            AreaLoad(case="L", magnitude=psf(40.0)),
        ],
        combo_set="ASCE7-22-2.4-ASD",
    )


def lrfd_loads_params() -> LoadAssumptionsParams:
    """Same area loads as the ASD builder, but selecting the ASCE 7-22 §2.3 LRFD
    strength combinations the steel branch is designed to."""
    return LoadAssumptionsParams(
        area_loads=[
            AreaLoad(case="D", magnitude=psf(15.0)),
            AreaLoad(case="L", magnitude=psf(40.0)),
        ],
        combo_set="ASCE7-22-2.3-LRFD",
    )


def framing_params() -> GravityFramingStrategyParams:
    return GravityFramingStrategyParams(
        region=GridRegion(x_from=LX1, x_to=LX2, y_from=LY_A, y_to=LY_B),
        system="joists_on_beams_on_posts",
        joist_axis="y",
        joist_spacing=inches(16.0),
        member_family="sawn_lumber",
        member_grade="DF-L No.2",
        joist_section="2x10",
        beam_section="4x12",
        post_section="4x4",
    )


def steel_framing_params() -> SteelFramingStrategyParams:
    """A three-tier steel frame over the same region as the wood framing —
    beams span y at 6 ft, on girders on lines A/B, on columns at the corners."""
    return SteelFramingStrategyParams(
        region=GridRegion(x_from=LX1, x_to=LX2, y_from=LY_A, y_to=LY_B),
        system="beams_on_girders_on_columns",
        beam_axis="y",
        beam_spacing=ft(6.0),
        member_family="hot_rolled_steel",
        member_grade="A992",
        beam_section="W10x12",
        girder_section="W12x16",
        column_section="W8x24",
    )


def usd(value: float, per: str = "USD") -> Quantity:
    return Quantity(mag=value, unit=per)


def cost_basis_params(*, steel_rate_usd_per_lb: float = 1.20) -> CostBasisParams:
    """A regional default basis (illustrative placeholder — the numbers await PO
    verification, like the dressed-size table). Steel priced by weight, sawn
    lumber by nominal board-feet; glulam-style lead time stands in on lumber."""
    return CostBasisParams(
        region="Pacific NW (placeholder)",
        as_of="2026-03-01",
        material_rates=[
            MaterialRate(family="hot_rolled_steel", rate=usd(steel_rate_usd_per_lb, "USD/lb")),
            MaterialRate(family="sawn_lumber", rate=usd(2.50, "USD/BF")),
        ],
        connection_cost=usd(85.0),
        crew_rate=usd(140.0, "USD/hr"),
        hours_per_piece=Quantity(mag=0.35, unit="hr"),
        hours_per_pick=Quantity(mag=0.75, unit="hr"),
        lead_times=[FamilyLeadTime(family="sawn_lumber", lead_time=Quantity(mag=2.0, unit="week"))],
        uncertainty_pct=4.0,
    )


def lateral_params() -> LateralStrategyParams:
    return LateralStrategyParams(wall_lines=[LY_A])


def opening_params() -> OpeningParams:
    return OpeningParams(
        wall_line=LY_A,
        offset_from=LX1,
        offset=ft(8.0),
        width=ft(3.0),
        height=ft(6.67),
    )


def compact_grid_params() -> GridParams:
    """A 12 ft x 8 ft bay: small enough that real sweep variants actually pass
    the NDS checks (the 24 ft milestone beams honestly fail everything)."""
    return GridParams(
        lines=[
            GridLine(line_id=LX1, name="1", axis="x", offset=ft(0.0)),
            GridLine(line_id=LX2, name="2", axis="x", offset=ft(12.0)),
            GridLine(line_id=LY_A, name="A", axis="y", offset=ft(0.0)),
            GridLine(line_id=LY_B, name="B", axis="y", offset=ft(8.0)),
        ]
    )


def decision(
    kind: str,
    title: str,
    params: KernelModel | dict[str, JsonValue] | None,
    deps: list[str] | None = None,
    **extra: object,
) -> Decision:
    payload: JsonValue = (
        params.model_dump(mode="json") if isinstance(params, KernelModel) else params
    )
    return Decision.model_validate(
        {
            "did": new_ulid(),
            "kind": kind,
            "title": title,
            "params": payload,
            "deps": deps or [],
            **extra,
        }
    )
