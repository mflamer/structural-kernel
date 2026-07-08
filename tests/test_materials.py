"""Material engines: the ADR 0007 registry and per-material adapters.

These tests prove the neutral result vocabulary spans wood (stress-based),
steel (moment/force-based, catalog), and concrete (moment-based, dimensional +
reinforced) — three libraries with a shared CheckResult shape but divergent
construction and dimensions — without any library type crossing the boundary.
"""

import pytest

from structural_kernel.materials import (
    AxialRequest,
    FlexureRequest,
    MemberCheckData,
    SectionProperties,
    engine_for,
    families,
)
from structural_kernel.materials.concrete import ConcreteBeam, check_beam_flexure
from structural_kernel.units import Dimension

_PSI = 4.4482216152605 / 0.0254**2
_KSI = 1000 * _PSI


# -- registry --------------------------------------------------------------------


def test_registry_holds_the_catalog_engines() -> None:
    assert families() == frozenset({"sawn_lumber", "hot_rolled_steel"})
    assert engine_for("sawn_lumber").family == "sawn_lumber"
    assert engine_for("hot_rolled_steel").family == "hot_rolled_steel"


def test_unknown_family_is_a_clear_error() -> None:
    with pytest.raises(KeyError, match="no design-check engine"):
        engine_for("unobtainium")


# -- wood engine (regression: identical to the old nds adapter) -------------------


def test_wood_section_and_modulus() -> None:
    wood = engine_for("sawn_lumber")
    section = wood.section_properties("2x10")
    assert section is not None
    b, d = 1.5 * 0.0254, 9.25 * 0.0254
    assert section.area_m2 == pytest.approx(b * d)
    assert section.i_strong_m4 == pytest.approx(b * d**3 / 12)
    assert wood.elastic_modulus_pa("DF-L No.2") == pytest.approx(1.6e6 * _PSI)
    assert wood.section_properties("nope") is None
    assert wood.elastic_modulus_pa("Imaginary Grade No.9") is None


def test_wood_flexure_is_stress_dimensioned() -> None:
    wood = engine_for("sawn_lumber")
    checks = wood.check_flexure(
        FlexureRequest(
            designation="2x10",
            grade="DF-L No.2",
            moment_nm=3000.0,
            shear_n=2000.0,
            span_m=4.0,
            load_cases=frozenset({"D", "L"}),
            repetitive=True,
        )
    )
    kinds = {c.check: c for c in checks}
    assert set(kinds) == {"bending", "shear"}
    assert all(c.dimension is Dimension.PRESSURE for c in checks)
    bending = kinds["bending"]
    assert bending.provision.startswith("NDS")
    symbols = {f.symbol for f in bending.factors}
    assert "CD" in symbols and "Cr" in symbols  # duration + repetitive applied
    assert all(f.ref for f in bending.factors)


# -- steel engine (a real AISC adapter; moment/force-dimensioned) -----------------


def test_steel_section_and_modulus() -> None:
    steel = engine_for("hot_rolled_steel")
    section = steel.section_properties("W18x50")
    assert isinstance(section, SectionProperties)
    assert section.area_m2 == pytest.approx(14.7 * 0.0254**2, rel=1e-3)  # A = 14.7 in^2
    assert section.i_strong_m4 == pytest.approx(800.0 * 0.0254**4, rel=1e-2)  # Ix ~ 800 in^4
    assert steel.elastic_modulus_pa("A992") == pytest.approx(29000 * _KSI, rel=1e-6)
    assert steel.mass_density_kg_m3("A992") == pytest.approx(7849.0)
    assert steel.section_properties("W18x999") is None


def test_steel_flexure_is_moment_dimensioned_and_cites_aisc() -> None:
    steel = engine_for("hot_rolled_steel")
    checks = steel.check_flexure(
        FlexureRequest(
            designation="W18x50",
            grade="A992",
            moment_nm=100 * 1355.8179,  # 100 kip-ft
            shear_n=20 * 4448.2216,  # 20 kip
            span_m=6.0,
            unbraced_length_m=0.0,
        )
    )
    kinds = {c.check: c for c in checks}
    assert kinds["bending"].dimension is Dimension.MOMENT
    assert kinds["shear"].dimension is Dimension.FORCE
    assert kinds["bending"].provision.startswith("AISC")
    # W18x50, braced, 100 kip-ft is well under capacity
    assert kinds["bending"].passes
    assert 0.0 < kinds["bending"].unity < 1.0
    # the governing limit state (steel-only field) is carried through
    assert kinds["bending"].governing


def test_steel_axial_compression_and_tension() -> None:
    steel = engine_for("hot_rolled_steel")
    comp = steel.check_axial(
        AxialRequest(
            designation="W14x90",
            grade="A992",
            force_n=200 * 4448.2216,  # 200 kip
            sense="compression",
            unbraced_length_m=3.0,
        )
    )
    assert comp.check == "compression"
    assert comp.dimension is Dimension.FORCE
    assert comp.provision.startswith("AISC")

    ten = steel.check_axial(
        AxialRequest(designation="W14x90", grade="A992", force_n=100 * 4448.2216, sense="tension")
    )
    assert ten.check == "tension" and ten.passes


# -- concrete adapter (result vocabulary spans the divergent case) ----------------


def test_concrete_flexure_maps_to_the_neutral_vocabulary() -> None:
    beam = ConcreteBeam(
        breadth_m=12 * 0.0254,
        depth_to_steel_m=21.5 * 0.0254,
        steel_area_m2=3.0 * 0.0254**2,  # ~3 in^2 (e.g. 3-#9)
        fc_pa=4000 * _PSI,
        rebar_grade="Gr60",
    )
    check = check_beam_flexure(beam, moment_nm=150e3)  # 150 kN·m
    assert isinstance(check, MemberCheckData)
    assert check.check == "bending"
    assert check.dimension is Dimension.MOMENT  # not stress — the general case
    assert check.provision.startswith("ACI")
    assert check.factors  # phi, beta1, etc.
    assert any(f.symbol == "phi" for f in check.factors)
    assert check.unity > 0.0  # a real demand/capacity ratio
