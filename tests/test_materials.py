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
    ReinforcementData,
    SectionProperties,
    engine_for,
    families,
)
from structural_kernel.materials.concrete import section_designation
from structural_kernel.units import Dimension

_PSI = 4.4482216152605 / 0.0254**2
_KSI = 1000 * _PSI


# -- registry --------------------------------------------------------------------


def test_registry_holds_all_three_family_engines() -> None:
    assert families() == frozenset({"sawn_lumber", "hot_rolled_steel", "cast_in_place_concrete"})
    assert engine_for("sawn_lumber").family == "sawn_lumber"
    assert engine_for("hot_rolled_steel").family == "hot_rolled_steel"
    assert engine_for("cast_in_place_concrete").family == "cast_in_place_concrete"


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


def test_costing_takeoff_facts_differ_by_family() -> None:
    # Steel is craned and priced by weight; sawn lumber is hand-set and priced by
    # nominal board-feet (ADR 0012). The engines carry that family fact.
    wood = engine_for("sawn_lumber")
    steel = engine_for("hot_rolled_steel")
    assert steel.crane_picks_per_member() == 1
    assert wood.crane_picks_per_member() == 0
    assert steel.nominal_volume_m3("W18x50", 6.0) is None  # steel is not volume-priced
    # a 2x10 over 8 ft: 2 in x 10 in nominal x length
    length_m = 8.0 * 0.3048
    assert wood.nominal_volume_m3("2x10", length_m) == pytest.approx(
        (2 * 0.0254) * (10 * 0.0254) * length_m
    )
    assert wood.nominal_volume_m3("W18x50", length_m) is None  # not a sawn designation


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


# -- concrete engine (the dimensioned family, ADR 0014) ---------------------------
#
# A 12x24 in beam with 3-#8 tension steel (cover 2.5 in to the bar centroid, so
# d = 21.5 in) and a 12x12 in tied column with 4-#8 — the smallest real members.

_BEAM = section_designation(12 * 0.0254, 24 * 0.0254)
_COLUMN = section_designation(12 * 0.0254, 12 * 0.0254)
_BEAM_REBAR = ReinforcementData(
    bars=3,
    bar="#8",
    cover_m=2.5 * 0.0254,
    grade="Gr60",
    stirrup_bar="#3",
    stirrup_spacing_m=10 * 0.0254,
)
_COLUMN_REBAR = ReinforcementData(bars=4, bar="#8", cover_m=2.5 * 0.0254, grade="Gr60")


def test_concrete_designation_is_parseable_geometry() -> None:
    """The dimensioned family's "catalog": a designation is b x h in mm, and the
    engine serves gross section properties straight from it."""
    concrete = engine_for("cast_in_place_concrete")
    assert _BEAM == "304.8x609.6"
    section = concrete.section_properties(_BEAM)
    assert isinstance(section, SectionProperties)
    b, h = 12 * 0.0254, 24 * 0.0254
    assert section.breadth_m == pytest.approx(b)
    assert section.depth_m == pytest.approx(h)
    assert section.area_m2 == pytest.approx(b * h)
    assert section.i_strong_m4 == pytest.approx(b * h**3 / 12)  # gross Ig (ADR 0014)
    assert concrete.section_properties("W18x50") is None  # not a dimensioned designation


def test_concrete_modulus_density_and_takeoff_facts() -> None:
    concrete = engine_for("cast_in_place_concrete")
    # Ec = 57000 sqrt(f'c) psi (ACI 19.2.2.1), from the mix designation.
    ec = concrete.elastic_modulus_pa("4000psi")
    assert ec == pytest.approx(57000 * 4000**0.5 * _PSI, rel=1e-6)
    assert concrete.elastic_modulus_pa("A992") is None
    assert concrete.mass_density_kg_m3("4000psi") == pytest.approx(2400.0)
    # Placed volume is concrete's trade pricing basis; CIP is formed, not picked.
    length_m = 6.0
    volume = concrete.nominal_volume_m3(_BEAM, length_m)
    assert volume == pytest.approx((12 * 0.0254) * (24 * 0.0254) * length_m)
    assert concrete.crane_picks_per_member() == 0


def test_concrete_flexure_and_shear_map_to_the_neutral_vocabulary() -> None:
    """The ADR 0007 boundary held: real ACI checks arrive as ordinary
    MemberCheckData — moment/force-dimensioned, provisions and factor trail
    intact — with reinforcement travelling on the request."""
    concrete = engine_for("cast_in_place_concrete")
    checks = concrete.check_flexure(
        FlexureRequest(
            designation=_BEAM,
            grade="4000psi",
            moment_nm=150e3,  # 150 kN·m — under phi*Mn for 3-#8 at d=21.5 in
            shear_n=40e3,
            span_m=6.0,
            method="LRFD",
            reinforcement=_BEAM_REBAR,
        )
    )
    kinds = {c.check: c for c in checks}
    assert set(kinds) == {"bending", "shear"}
    bending = kinds["bending"]
    assert bending.dimension is Dimension.MOMENT
    assert bending.demand == pytest.approx(150e3)  # SI round-trips through in-lb
    assert bending.provision.startswith("ACI")
    assert any(f.symbol == "phi" for f in bending.factors)
    assert bending.passes and 0.0 < bending.unity < 1.0
    shear = kinds["shear"]
    assert shear.dimension is Dimension.FORCE
    assert shear.provision.startswith("ACI")
    assert shear.passes  # stirruped: Vc + Vs carries 40 kN


def test_concrete_column_checks_concentric_axial() -> None:
    """Concentric phi*Pn,max (ACI 22.4.2, tied) — parity with the axial-only
    idealization steel/wood columns get (ADR 0014)."""
    concrete = engine_for("cast_in_place_concrete")
    check = concrete.check_axial(
        AxialRequest(
            designation=_COLUMN,
            grade="4000psi",
            force_n=500e3,  # 500 kN, well under phi*Pn,max ~ 1546 kN
            sense="compression",
            method="LRFD",
            reinforcement=_COLUMN_REBAR,
        )
    )
    assert check.check == "compression"
    assert check.dimension is Dimension.FORCE
    assert check.provision.startswith("ACI")
    assert check.passes and 0.0 < check.unity < 1.0


def test_concrete_guards_are_clear_errors() -> None:
    concrete = engine_for("cast_in_place_concrete")
    with pytest.raises(ValueError, match="LRFD-only"):
        concrete.check_flexure(
            FlexureRequest(
                designation=_BEAM,
                grade="4000psi",
                moment_nm=1.0,
                shear_n=1.0,
                span_m=6.0,
                method="ASD",
                reinforcement=_BEAM_REBAR,
            )
        )
    with pytest.raises(ValueError, match="ReinforcementData"):
        concrete.check_flexure(
            FlexureRequest(
                designation=_BEAM,
                grade="4000psi",
                moment_nm=1.0,
                shear_n=1.0,
                span_m=6.0,
                method="LRFD",
            )
        )
    with pytest.raises(ValueError, match="compression only"):
        concrete.check_axial(
            AxialRequest(
                designation=_COLUMN,
                grade="4000psi",
                force_n=1.0,
                sense="tension",
                method="LRFD",
                reinforcement=_COLUMN_REBAR,
            )
        )
