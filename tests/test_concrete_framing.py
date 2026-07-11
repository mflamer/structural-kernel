"""Concrete three-tier framing (ADR 0014, note 0006): the dimensioned decision
kind, the derivation rule, the concrete countables, and — increment 3 — the ACI
design checks concrete members earn automatically because checks resolve their
engine by family. The sprint's real acceptance: registering concrete required a
new member *description*, and no change to MemberCheckData, the registry shape,
or how checks are consumed.
"""

import pytest

from conftest import (
    concrete_framing_params,
    decision,
    grid_params,
    inches,
    levels_params,
    lrfd_loads_params,
)
from structural_kernel.canonical import canonical_bytes, model_document
from structural_kernel.costing import quantity_kind
from structural_kernel.decisions import ConcreteMemberSpec
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.materials.concrete import section_designation
from structural_kernel.objects import Decision
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash

_M_PER_IN = 0.0254


def _snapshot(*decisions: Decision) -> ResolvedSnapshot:
    return ResolvedSnapshot(decisions={d.did: d for d in decisions})


def _concrete_model() -> tuple[DerivedModel, dict[str, Decision]]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "concrete_framing_strategy",
        "Concrete frame",
        concrete_framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    snapshot = _snapshot(grid, levels, loads, framing)
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    return model, {"grid": grid, "levels": levels, "loads": loads, "framing": framing}


# -- the member-description schema (the one representational divergence) ------------


def test_member_spec_is_structured_not_a_string() -> None:
    """Reinforcement is structured, tagged-unit data (note 0006's demand): a
    stirrup pair comes together, and cover must be inside the depth."""
    with pytest.raises(ValueError, match="together or not at all"):
        ConcreteMemberSpec(
            breadth=inches(12.0),
            depth=inches(16.0),
            bars=3,
            bar="#6",
            cover=inches(2.5),
            stirrup_bar="#3",  # spacing missing
        )
    with pytest.raises(ValueError, match="less than the overall depth"):
        ConcreteMemberSpec(
            breadth=inches(12.0),
            depth=inches(16.0),
            bars=3,
            bar="#6",
            cover=inches(16.0),
        )


# -- the derived three-tier topology -------------------------------------------------


def test_concrete_frame_derives_beams_girders_and_columns() -> None:
    model, ids = _concrete_model()
    beams = [e for e in model.elements if e.role == "beam"]
    girders = [e for e in model.elements if e.role == "girder"]
    columns = [e for e in model.elements if e.role == "column"]

    assert len(beams) == 5  # 24 ft at 6 ft: ordinals 0..4
    assert len(girders) == 2  # on lines A and B
    assert len(columns) == 4  # region corners

    for element in beams + girders + columns:
        assert element.family == "cast_in_place_concrete"
        assert element.grade == "4000psi"  # the mix designation is the grade key
        assert element.design_method == "LRFD"
        assert ids["framing"].did in element.eid

    # Sections are dimensioned designations rendered from the authored (b, h).
    assert {e.section for e in beams} == {section_designation(12 * _M_PER_IN, 16 * _M_PER_IN)}
    assert {e.section for e in girders} == {section_designation(12 * _M_PER_IN, 24 * _M_PER_IN)}
    assert {e.section for e in columns} == {section_designation(12 * _M_PER_IN, 12 * _M_PER_IN)}


def test_concrete_members_carry_their_reinforcement() -> None:
    """The authored reinforcement travels on the derived member — the fact the
    designation cannot carry, persisted in the element (ADR 0014)."""
    model, _ = _concrete_model()
    beam = next(e for e in model.elements if e.role == "beam")
    girder = next(e for e in model.elements if e.role == "girder")
    column = next(e for e in model.elements if e.role == "column")

    assert beam.reinforcement is not None
    assert (beam.reinforcement.bars, beam.reinforcement.bar) == (3, "#6")
    assert beam.reinforcement.stirrup_bar == "#3"
    assert beam.reinforcement.grade == "Gr60"
    assert girder.reinforcement is not None
    assert (girder.reinforcement.bars, girder.reinforcement.bar) == (3, "#8")
    assert column.reinforcement is not None
    assert (column.reinforcement.bars, column.reinforcement.bar) == (4, "#8")
    assert column.reinforcement.transverse == "ties"
    # cover is a tagged quantity, to the tension-steel centroid
    assert beam.reinforcement.cover.si_mag == pytest.approx(2.5 * _M_PER_IN)


def test_concrete_eids_use_the_three_tier_tokens() -> None:
    model, _ = _concrete_model()
    prefixes = {e.eid.split(":", 1)[0] for e in model.elements}
    assert prefixes == {"bm", "gdr", "col"}


def test_concrete_load_path_is_beam_on_girder_on_column() -> None:
    model, _ = _concrete_model()
    by_eid = {e.eid: e for e in model.elements}
    girder_eids = {e.eid for e in model.elements if e.role == "girder"}
    for beam in (e for e in model.elements if e.role == "beam"):
        assert set(beam.supports) == girder_eids
    for girder_eid in girder_eids:
        girder = by_eid[girder_eid]
        assert len(girder.supports) == 2
        assert all(by_eid[s].role == "column" for s in girder.supports)


def test_concrete_analysis_uses_gross_section_and_ec() -> None:
    """The analysis artifact idealizes concrete uncracked: gross A and Ig from
    the parseable designation, Ec from the mix (ACI 19.2.2.1) — the documented
    ADR 0014 idealization (Ie refinement deferred)."""
    model, _ = _concrete_model()
    assert model.analysis is not None
    girder_eid = next(e.eid for e in model.elements if e.role == "girder")
    analysis_girder = next(e for e in model.analysis.elements if e.source_eid == girder_eid)
    b, h = 12 * _M_PER_IN, 24 * _M_PER_IN
    assert analysis_girder.A_m2 == pytest.approx(b * h)
    assert analysis_girder.I_strong_m4 == pytest.approx(b * h**3 / 12)
    psi = 4.4482216152605 / _M_PER_IN**2
    assert analysis_girder.E_pa == pytest.approx(57000 * 4000**0.5 * psi, rel=1e-6)
    # LRFD strength combos + service combos both present (deflection is service).
    purposes = {c.purpose for c in model.analysis.combos}
    assert purposes == {"strength", "service"}


def test_concrete_frame_is_formed_not_picked() -> None:
    model, _ = _concrete_model()
    assert model.bill.countables.crane_picks == 0  # CIP: 0 picks (PO call)


def test_concrete_derivation_is_deterministic() -> None:
    grid = decision("grid", "Grid", grid_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "concrete_framing_strategy", "F", concrete_framing_params(), deps=[grid.did, loads.did]
    )
    a = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    b = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    assert canonical_bytes(model_document(a)) == canonical_bytes(model_document(b))


# -- the concrete countables (derived, never invented by pricing; note 0003) ---------


def test_concrete_volume_formwork_and_rebar_are_derived_countables() -> None:
    model, _ = _concrete_model()
    length_beam = 14 * 0.3048  # beams span y: 14 ft
    length_girder = 24 * 0.3048
    length_column = 10 * 0.3048  # levels elevation

    volume = quantity_kind("concrete_volume")
    assert volume is not None
    expected_volume = (
        5 * (12 * _M_PER_IN) * (16 * _M_PER_IN) * length_beam
        + 2 * (12 * _M_PER_IN) * (24 * _M_PER_IN) * length_girder
        + 4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    assert volume.resolve(model, None, None) == pytest.approx(expected_volume)

    formwork = quantity_kind("formwork_area")
    assert formwork is not None
    b_bm, h_bm = 12 * _M_PER_IN, 16 * _M_PER_IN
    b_gd, h_gd = 12 * _M_PER_IN, 24 * _M_PER_IN
    b_c = 12 * _M_PER_IN
    expected_formwork = (
        5 * (b_bm + 2 * h_bm) * length_beam  # beams: 3 formed sides
        + 2 * (b_gd + 2 * h_gd) * length_girder  # girders: 3 formed sides
        + 4 * (2 * (b_c + b_c)) * length_column  # columns: 4 formed sides
    )
    assert formwork.resolve(model, None, None) == pytest.approx(expected_formwork)

    rebar = quantity_kind("rebar_mass")
    assert rebar is not None
    steel_density = 7850.0
    as_6 = 3 * 0.44 * _M_PER_IN**2  # 3-#6
    as_8_beams = 3 * 0.79 * _M_PER_IN**2  # 3-#8 (girders)
    as_8_cols = 4 * 0.79 * _M_PER_IN**2  # 4-#8 (columns)
    expected_rebar = steel_density * (
        5 * as_6 * length_beam + 2 * as_8_beams * length_girder + 4 * as_8_cols * length_column
    )
    assert rebar.resolve(model, None, None) == pytest.approx(expected_rebar)

    # Scoping works: the role scope isolates a tier.
    assert volume.resolve(model, "cast_in_place_concrete", "column") == pytest.approx(
        4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    # And a wood/steel-only model yields zero concrete countables (not an error).
    assert volume.resolve(model, "hot_rolled_steel", None) == 0.0


def test_concrete_member_weight_needs_no_special_case() -> None:
    """The generic member_weight countable prices concrete through the same
    section_properties + density path as any catalog family — the parseable
    designation makes the mass substrate just work (the exploration mass metric
    reads the identical engine facts; increment 3 ranks on it publicly)."""
    model, _ = _concrete_model()
    weight = quantity_kind("member_weight")
    assert weight is not None
    length_beam, length_girder, length_column = 14 * 0.3048, 24 * 0.3048, 10 * 0.3048
    expected = 2400.0 * (
        5 * (12 * _M_PER_IN) * (16 * _M_PER_IN) * length_beam
        + 2 * (12 * _M_PER_IN) * (24 * _M_PER_IN) * length_girder
        + 4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    assert weight.resolve(model, "cast_in_place_concrete", None) == pytest.approx(expected)
