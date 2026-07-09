"""Units layer: NIST-exact conversions, dimensional validation, curated whitelist."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from structural_kernel.units import (
    CANONICAL_SI,
    UNITS,
    Dimension,
    DimensionError,
    PressureQuantity,
    Quantity,
    convert,
    parse_quantity,
)


def test_kip_matches_nist_exactly() -> None:
    assert Quantity(mag=1.0, unit="kip").si_mag == 4448.2216152605


def test_inch_matches_nist_exactly() -> None:
    assert Quantity(mag=16.0, unit="in").si_mag == 16.0 * 0.0254


def test_psf_composes_from_nist_primitives() -> None:
    assert Quantity(mag=40.0, unit="psf").si_mag == 40.0 * (4.4482216152605 / 0.3048**2)


def test_ksi_composes_from_nist_primitives() -> None:
    assert Quantity(mag=1.0, unit="ksi").si_mag == 1e3 * 4.4482216152605 / 0.0254**2


def test_every_dimension_has_a_canonical_si_unit_with_factor_one() -> None:
    for dimension, unit in CANONICAL_SI.items():
        assert UNITS[unit].dimension is dimension
        assert UNITS[unit].si_factor == 1.0


def test_every_dimension_is_reachable_from_a_canonical_unit() -> None:
    # No dimension may be introduced without a canonical SI spelling.
    assert set(CANONICAL_SI) == set(Dimension)


def test_board_foot_is_one_hundred_forty_four_cubic_inches() -> None:
    assert Quantity(mag=1.0, unit="BF").si_mag == 144.0 * 0.0254**3
    assert Quantity(mag=1.0, unit="MBF").si_mag == 1e3 * (144.0 * 0.0254**3)


def test_dollars_per_pound_composes_from_nist_pound_mass() -> None:
    # $1/lb is $ (1/0.45359237) per kg — the pound is the international pound.
    assert Quantity(mag=1.0, unit="USD/lb").si_mag == 1.0 / 0.45359237


def test_dollars_per_hour_is_dollars_per_second_over_thirty_six_hundred() -> None:
    assert Quantity(mag=90.0, unit="USD/hr").si_mag == 90.0 / 3600.0


def test_dollars_per_board_foot_is_a_money_per_volume_rate() -> None:
    rate = Quantity(mag=2.5, unit="USD/BF")
    assert rate.dimension is Dimension.MONEY_PER_VOLUME
    assert rate.si_mag == 2.5 / (144.0 * 0.0254**3)


def test_week_is_seven_days_of_seconds() -> None:
    assert Quantity(mag=14.0, unit="week").si_mag == 14.0 * 604800.0


def test_money_rate_dimensions_are_distinct() -> None:
    assert Quantity(mag=1.0, unit="USD/kg").dimension is Dimension.MONEY_PER_MASS
    assert Quantity(mag=1.0, unit="USD/m3").dimension is Dimension.MONEY_PER_VOLUME
    assert Quantity(mag=1.0, unit="USD/s").dimension is Dimension.MONEY_PER_TIME
    assert Quantity(mag=1.0, unit="USD").dimension is Dimension.MONEY


def test_convert_rejects_dimension_mismatch() -> None:
    with pytest.raises(DimensionError):
        convert(Quantity(mag=1.0, unit="ft"), "kip")


def test_unknown_unit_is_rejected_at_validation() -> None:
    with pytest.raises(ValidationError):
        Quantity(mag=1.0, unit="furlong")


def test_nan_and_infinity_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Quantity(mag=float("nan"), unit="m")
    with pytest.raises(ValidationError):
        Quantity(mag=float("inf"), unit="m")


def test_parse_authoring_register() -> None:
    assert parse_quantity("16 in") == Quantity(mag=16.0, unit="in")
    assert parse_quantity("40 psf") == Quantity(mag=40.0, unit="psf")
    assert parse_quantity("-1.5e2 kN/m") == Quantity(mag=-150.0, unit="kN/m")


def test_parse_rejects_garbage_and_unknown_units() -> None:
    for text in ("16", "in", "16 furlongs", "1 + 1 m", ""):
        with pytest.raises(ValueError):  # both parse errors and whitelist rejections
            parse_quantity(text)


def test_dimension_constrained_field_rejects_wrong_dimension() -> None:
    class Slice(BaseModel):
        load: PressureQuantity

    assert Slice(load=Quantity(mag=40.0, unit="psf")).load.dimension is Dimension.PRESSURE
    with pytest.raises(ValidationError):
        Slice(load=Quantity(mag=40.0, unit="ft"))


@given(
    mag=st.floats(min_value=-1e12, max_value=1e12, allow_nan=False),
    unit=st.sampled_from(sorted(UNITS)),
)
def test_si_round_trip_is_lossless_to_float_tolerance(mag: float, unit: str) -> None:
    q = Quantity(mag=mag, unit=unit)
    back = convert(q.to_si(), unit)
    assert back.unit == unit
    assert back.mag == pytest.approx(mag, rel=1e-12, abs=1e-12)


@given(unit=st.sampled_from(sorted(UNITS)))
def test_to_si_is_idempotent(unit: str) -> None:
    q = Quantity(mag=3.5, unit=unit).to_si()
    assert q.to_si() == q
