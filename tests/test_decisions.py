"""Decision-kind parameter schemas: shape and dimensional validation."""

import pytest
from pydantic import ValidationError

from conftest import (
    LX1,
    LX2,
    cost_basis_params,
    decision,
    framing_params,
    grid_params,
    inches,
    lateral_params,
    levels_params,
    loads_params,
    opening_params,
    psf,
    steel_framing_params,
)
from structural_kernel.decisions import (
    CostBasisParams,
    CostFactor,
    DirectPrice,
    ExceptionParams,
    FactorScope,
    GravityFramingStrategyParams,
    GridLine,
    GridParams,
    LaborPrice,
    LoadAssumptionsParams,
    SteelFramingStrategyParams,
    line_refs,
    parse_params,
)
from structural_kernel.units import Quantity


def test_every_milestone_kind_round_trips_through_parse_params() -> None:
    cases = [
        ("grid", grid_params()),
        ("levels", levels_params()),
        ("load_assumptions", loads_params()),
        ("gravity_framing_strategy", framing_params()),
        ("steel_framing_strategy", steel_framing_params()),
        ("lateral_strategy", lateral_params()),
        ("opening", opening_params()),
        (
            "exception",
            ExceptionParams(
                target_eid="jst:01JXF:LX1-LX2.LYA+03",
                field="section",
                value={"designation": "2x10 doubled"},
            ),
        ),
        ("cost_basis", cost_basis_params()),
    ]
    for kind, params in cases:
        parsed = parse_params(decision(kind, f"test {kind}", params))
        assert parsed == params


def test_open_decision_parses_to_none() -> None:
    open_decision = decision("lateral_strategy", "system TBD", None, state="open")
    assert parse_params(open_decision) is None


def test_grid_rejects_duplicate_line_ids() -> None:
    line = GridLine(line_id=LX1, name="1", axis="x", offset=inches(0.0))
    with pytest.raises(ValidationError, match="duplicate line_id"):
        GridParams(lines=[line, line.model_copy(update={"name": "2"})])


def test_grid_rejects_duplicate_names_on_one_axis() -> None:
    with pytest.raises(ValidationError, match="duplicate line name"):
        GridParams(
            lines=[
                GridLine(line_id=LX1, name="1", axis="x", offset=inches(0.0)),
                GridLine(line_id=LX2, name="1", axis="x", offset=inches(24.0)),
            ]
        )


def test_mis_dimensioned_params_are_rejected() -> None:
    with pytest.raises(ValidationError):  # spacing must be a length, not a pressure
        GravityFramingStrategyParams.model_validate(
            framing_params().model_dump(mode="json") | {"joist_spacing": psf(40.0).model_dump()}
        )
    with pytest.raises(ValidationError):  # area load must be pressure-dimensioned
        LoadAssumptionsParams.model_validate(
            {
                "area_loads": [{"case": "D", "magnitude": {"mag": 1.0, "unit": "ft"}}],
                "combo_set": "ASCE7-22-2.4-ASD",
            }
        )


def test_cost_basis_has_no_line_refs() -> None:
    # A cost basis is global — it anchors to no grid line.
    assert line_refs(cost_basis_params()) == set()


def test_cost_factor_over_unknown_quantity_kind_fails_cleanly() -> None:
    # The clean-failure boundary (note 0003): a factor naming a countable no
    # resolver provides is rejected, pointing at the missing kind — never invented.
    with pytest.raises(ValidationError, match="which no derived countable provides"):
        CostFactor(
            quantity_kind="formwork_area",
            pricing=DirectPrice(unit_price=Quantity(mag=1.0, unit="USD")),
            source="x",
        )


def test_direct_price_dimension_must_match_the_quantity_kind() -> None:
    # member_weight is a MASS kind: it wants a money-per-mass rate, not $/BF.
    with pytest.raises(ValidationError, match="unit price"):
        CostFactor(
            quantity_kind="member_weight",
            pricing=DirectPrice(unit_price=Quantity(mag=2.5, unit="USD/BF")),
            source="x",
        )
    # a count kind wants plain USD-each, not a per-mass rate.
    with pytest.raises(ValidationError, match="unit price"):
        CostFactor(
            quantity_kind="crane_picks",
            pricing=DirectPrice(unit_price=Quantity(mag=2.5, unit="USD/lb")),
            source="x",
        )


def test_labor_pricing_only_applies_to_a_count_kind() -> None:
    with pytest.raises(ValidationError, match="labor pricing applies to a count kind"):
        CostFactor(
            quantity_kind="member_weight",  # a MASS kind, not a count
            scope=FactorScope(family="hot_rolled_steel"),
            pricing=LaborPrice(
                crew_rate=Quantity(mag=140.0, unit="USD/hr"),
                productivity=Quantity(mag=0.5, unit="hr"),
            ),
            source="x",
        )


def test_cost_basis_uncertainty_must_be_a_sane_percentage() -> None:
    payload = cost_basis_params().model_dump(mode="json") | {"uncertainty_pct": 0.0}
    with pytest.raises(ValidationError):
        CostBasisParams.model_validate(payload)


def test_unknown_load_case_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_params(
            decision(
                "load_assumptions",
                "bad case",
                {
                    "area_loads": [{"case": "Q", "magnitude": {"mag": 1.0, "unit": "psf"}}],
                    "combo_set": "ASCE7-22-2.4-ASD",
                },
            )
        )


def test_line_refs_extraction() -> None:
    assert line_refs(parse_params(decision("grid", "g", grid_params()))) == set()
    framing = parse_params(decision("gravity_framing_strategy", "f", framing_params()))
    assert line_refs(framing) == {LX1, LX2, "L000000B1", "L000000B2"}
    steel = parse_params(decision("steel_framing_strategy", "s", steel_framing_params()))
    assert line_refs(steel) == {LX1, LX2, "L000000B1", "L000000B2"}
    opening = parse_params(decision("opening", "o", opening_params()))
    assert line_refs(opening) == {"L000000B1", LX1}


def test_steel_framing_rejects_an_unregistered_material_family() -> None:
    with pytest.raises(ValidationError, match="no registered design-check engine"):
        SteelFramingStrategyParams.model_validate(
            steel_framing_params().model_dump(mode="json") | {"member_family": "titanium"}
        )


def test_steel_framing_rejects_a_mis_dimensioned_spacing() -> None:
    with pytest.raises(ValidationError):  # beam spacing must be a length, not a pressure
        SteelFramingStrategyParams.model_validate(
            steel_framing_params().model_dump(mode="json")
            | {"beam_spacing": psf(40.0).model_dump()}
        )
