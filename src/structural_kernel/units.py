"""Unit-tagged quantities: canonical SI internally, curated spellings at the boundary.

ADR 0002: every value crossing any interface travels as ``{mag, unit}``. The
``unit`` tag is validated against a curated whitelist (no free-form unit
parser), dimensional correctness is checked at schema validation, and the
conversion table lives here — in code, tested against NIST constants. US
customary is the authoring/display register; conversion happens once at each
boundary and nowhere else.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator


class Dimension(StrEnum):
    LENGTH = "length"
    AREA = "area"
    SECOND_MOMENT_OF_AREA = "second_moment_of_area"
    MASS = "mass"
    TIME = "time"
    FORCE = "force"
    PRESSURE = "pressure"  # stress and area load share Pa
    LINE_LOAD = "line_load"
    MOMENT = "moment"


class DimensionError(ValueError):
    """A quantity's dimension does not match what the context requires."""


# NIST SP 811 exact definitions — the only place conversion primitives live.
_M_PER_FT: Final = 0.3048
_M_PER_IN: Final = 0.0254
_N_PER_LBF: Final = 4.4482216152605
_N_PER_KIP: Final = 4448.2216152605


@dataclass(frozen=True, slots=True)
class UnitDef:
    dimension: Dimension
    si_factor: float  # magnitude in this unit times si_factor = magnitude in canonical SI


UNITS: Final[dict[str, UnitDef]] = {
    # length
    "m": UnitDef(Dimension.LENGTH, 1.0),
    "mm": UnitDef(Dimension.LENGTH, 1e-3),
    "ft": UnitDef(Dimension.LENGTH, _M_PER_FT),
    "in": UnitDef(Dimension.LENGTH, _M_PER_IN),
    # area
    "m2": UnitDef(Dimension.AREA, 1.0),
    "ft2": UnitDef(Dimension.AREA, _M_PER_FT**2),
    "in2": UnitDef(Dimension.AREA, _M_PER_IN**2),
    # second moment of area
    "m4": UnitDef(Dimension.SECOND_MOMENT_OF_AREA, 1.0),
    "in4": UnitDef(Dimension.SECOND_MOMENT_OF_AREA, _M_PER_IN**4),
    # mass / time
    "kg": UnitDef(Dimension.MASS, 1.0),
    "s": UnitDef(Dimension.TIME, 1.0),
    # force
    "N": UnitDef(Dimension.FORCE, 1.0),
    "kN": UnitDef(Dimension.FORCE, 1e3),
    "lbf": UnitDef(Dimension.FORCE, _N_PER_LBF),
    "kip": UnitDef(Dimension.FORCE, _N_PER_KIP),
    # pressure / stress / area load
    "Pa": UnitDef(Dimension.PRESSURE, 1.0),
    "kPa": UnitDef(Dimension.PRESSURE, 1e3),
    "MPa": UnitDef(Dimension.PRESSURE, 1e6),
    "psf": UnitDef(Dimension.PRESSURE, _N_PER_LBF / _M_PER_FT**2),
    "psi": UnitDef(Dimension.PRESSURE, _N_PER_LBF / _M_PER_IN**2),
    "ksi": UnitDef(Dimension.PRESSURE, 1e3 * _N_PER_LBF / _M_PER_IN**2),
    # line load
    "N/m": UnitDef(Dimension.LINE_LOAD, 1.0),
    "kN/m": UnitDef(Dimension.LINE_LOAD, 1e3),
    "plf": UnitDef(Dimension.LINE_LOAD, _N_PER_LBF / _M_PER_FT),
    "klf": UnitDef(Dimension.LINE_LOAD, _N_PER_KIP / _M_PER_FT),
    # moment
    "N*m": UnitDef(Dimension.MOMENT, 1.0),
    "kN*m": UnitDef(Dimension.MOMENT, 1e3),
    "kip*ft": UnitDef(Dimension.MOMENT, _N_PER_KIP * _M_PER_FT),
    "kip*in": UnitDef(Dimension.MOMENT, _N_PER_KIP * _M_PER_IN),
}

CANONICAL_SI: Final[dict[Dimension, str]] = {
    Dimension.LENGTH: "m",
    Dimension.AREA: "m2",
    Dimension.SECOND_MOMENT_OF_AREA: "m4",
    Dimension.MASS: "kg",
    Dimension.TIME: "s",
    Dimension.FORCE: "N",
    Dimension.PRESSURE: "Pa",
    Dimension.LINE_LOAD: "N/m",
    Dimension.MOMENT: "N*m",
}


class Quantity(BaseModel):
    """A unit-tagged value: the only way a number crosses an interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mag: float
    unit: str

    @field_validator("mag")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("magnitude must be finite (no NaN/Infinity in the model)")
        return v

    @field_validator("unit")
    @classmethod
    def _registered(cls, v: str) -> str:
        if v not in UNITS:
            raise ValueError(f"unit {v!r} is not in the curated whitelist")
        return v

    @property
    def dimension(self) -> Dimension:
        return UNITS[self.unit].dimension

    @property
    def si_mag(self) -> float:
        """Magnitude in the canonical SI unit of this quantity's dimension."""
        return self.mag * UNITS[self.unit].si_factor

    def to_si(self) -> Quantity:
        return Quantity(mag=self.si_mag, unit=CANONICAL_SI[self.dimension])


def convert(quantity: Quantity, unit: str) -> Quantity:
    """Convert to another whitelisted unit of the same dimension."""
    target = UNITS.get(unit)
    if target is None:
        raise ValueError(f"unit {unit!r} is not in the curated whitelist")
    if target.dimension is not quantity.dimension:
        raise DimensionError(
            f"cannot convert {quantity.dimension} ({quantity.unit!r}) "
            f"to {target.dimension} ({unit!r})"
        )
    return Quantity(mag=quantity.si_mag / target.si_factor, unit=unit)


_QUANTITY_RE: Final = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s+(\S+)\s*$")


def parse_quantity(text: str) -> Quantity:
    """Parse an authoring-register string like ``"16 in"`` or ``"40 psf"``.

    Deliberately rigid: a number, whitespace, a whitelisted unit spelling.
    No unit arithmetic, no expressions — the whitelist is the grammar.
    """
    m = _QUANTITY_RE.match(text)
    if m is None:
        raise ValueError(f"cannot parse quantity from {text!r} (expected '<number> <unit>')")
    return Quantity(mag=float(m.group(1)), unit=m.group(2))


def _expect(dimension: Dimension) -> AfterValidator:
    def check(q: Quantity) -> Quantity:
        if q.dimension is not dimension:
            raise DimensionError(f"expected a {dimension} quantity, got {q.dimension} ({q.unit!r})")
        return q

    return AfterValidator(check)


# Dimension-constrained field types: a mis-dimensioned value is a schema
# validation failure — a rejected changeset, not a latent bug.
LengthQuantity = Annotated[Quantity, _expect(Dimension.LENGTH)]
AreaQuantity = Annotated[Quantity, _expect(Dimension.AREA)]
ForceQuantity = Annotated[Quantity, _expect(Dimension.FORCE)]
PressureQuantity = Annotated[Quantity, _expect(Dimension.PRESSURE)]
LineLoadQuantity = Annotated[Quantity, _expect(Dimension.LINE_LOAD)]
MomentQuantity = Annotated[Quantity, _expect(Dimension.MOMENT)]
