"""Decision-kind parameter schemas: shape and dimensional validation."""

import pytest
from pydantic import ValidationError

from conftest import (
    LX1,
    LX2,
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
    ExceptionParams,
    GravityFramingStrategyParams,
    GridLine,
    GridParams,
    LoadAssumptionsParams,
    SteelFramingStrategyParams,
    line_refs,
    parse_params,
)


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
