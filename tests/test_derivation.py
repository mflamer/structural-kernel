"""Derivation: the ADR 0005 property tests and the milestone structure's physics.

Tests 1-8 from docs/design/0002 §6, as far as increment 3 can exercise them
(override displacement is the overrides increment; LOD prefix stability waits
for a second resolution).
"""

from hypothesis import given
from hypothesis import strategies as st

from conftest import (
    LX2,
    LY_A,
    LY_B,
    decision,
    framing_params,
    ft,
    grid_params,
    inches,
    lateral_params,
    levels_params,
    loads_params,
    opening_params,
)
from structural_kernel.canonical import canonical_bytes, model_document
from structural_kernel.decisions import GridLine, GridParams
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.eids import render_eid
from structural_kernel.objects import Decision, DecisionTarget, EidTarget
from structural_kernel.validation import ResolvedSnapshot

_PSF = 4.4482216152605 / 0.3048**2


def _snapshot(*decisions: Decision) -> ResolvedSnapshot:
    return ResolvedSnapshot(decisions={d.did: d for d in decisions})


def _derive(*decisions: Decision) -> DerivedModel:
    return derive(_snapshot(*decisions), snapshot_hash="sha256:" + "0" * 64)


def _milestone() -> tuple[DerivedModel, dict[str, Decision]]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    framing = decision(
        "gravity_framing_strategy",
        "Floor framing",
        framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    lateral = decision("lateral_strategy", "Shear walls", lateral_params(), deps=[grid.did])
    opening = decision(
        "opening", "Door D1", opening_params(), deps=[grid.did, framing.did, loads.did]
    )
    model = _derive(grid, levels, loads, framing, lateral, opening)
    return model, {
        "grid": grid,
        "levels": levels,
        "loads": loads,
        "framing": framing,
        "lateral": lateral,
        "opening": opening,
    }


def _eids(model: DerivedModel) -> set[str]:
    return {e.eid for e in model.elements}


def _with_params(d: Decision, params: object) -> Decision:
    dumped = params.model_dump(mode="json") if hasattr(params, "model_dump") else params  # type: ignore[union-attr]
    return d.model_copy(update={"params": dumped})


# -- test 1: determinism ---------------------------------------------------------


def test_derivation_is_deterministic() -> None:
    first, _ = _milestone()
    # rebuild with the SAME dids is impossible (fresh ULIDs), so derive the
    # same resolved snapshot twice instead
    grid = decision("grid", "Grid", grid_params())
    framing = decision("gravity_framing_strategy", "F", framing_params(), deps=[grid.did])
    a = _derive(grid, framing)
    b = _derive(grid, framing)
    assert canonical_bytes(model_document(a)) == canonical_bytes(model_document(b))
    assert first.schema_version == 1


# -- test 2: gridline-move invariance ---------------------------------------------


def test_moving_a_gridline_changes_geometry_but_no_eids() -> None:
    grid = decision("grid", "Grid", grid_params())
    framing = decision("gravity_framing_strategy", "F", framing_params(), deps=[grid.did])
    before = _derive(grid, framing)

    # move the far span line (LY_B) 14 ft -> 16 ft: span geometry changes,
    # joist count does not
    moved_lines = [
        line if line.line_id != LY_B else line.model_copy(update={"offset": ft(16.0)})
        for line in grid_params().lines
    ]
    moved = _with_params(grid, GridParams(lines=moved_lines))
    after = _derive(moved, framing)

    assert _eids(before) == _eids(after)
    length_before = {e.eid: e.length.mag for e in before.elements if e.role == "joist"}
    length_after = {e.eid: e.length.mag for e in after.elements if e.role == "joist"}
    assert all(length_after[eid] > length_before[eid] for eid in length_before)


# -- test 3: gridline-rename invariance ---------------------------------------------


def test_renaming_a_gridline_changes_nothing_at_all() -> None:
    grid = decision("grid", "Grid", grid_params())
    framing = decision("gravity_framing_strategy", "F", framing_params(), deps=[grid.did])
    renamed_lines = [
        line.model_copy(update={"name": f"renamed-{line.name}"}) for line in grid_params().lines
    ]
    renamed = _with_params(grid, GridParams(lines=renamed_lines))

    before = _derive(grid, framing)
    after = _derive(renamed, framing)
    assert canonical_bytes(model_document(before)) == canonical_bytes(model_document(after))


# -- test 4: locality ----------------------------------------------------------------


def _three_line_grid_params() -> GridParams:
    return GridParams(
        lines=[
            *grid_params().lines,
            GridLine(line_id="L000000A3", name="3", axis="x", offset=ft(48.0)),
        ]
    )


def test_editing_one_rule_instance_perturbs_no_other_eids() -> None:
    grid = decision("grid", "Grid", _three_line_grid_params())
    bay_a = decision("gravity_framing_strategy", "Bay A", framing_params(), deps=[grid.did])
    bay_b_params = framing_params().model_copy(
        update={
            "region": framing_params().region.model_copy(
                update={"x_from": LX2, "x_to": "L000000A3"}
            )
        }
    )
    bay_b = decision("gravity_framing_strategy", "Bay B", bay_b_params, deps=[grid.did])

    before = _derive(grid, bay_a, bay_b)
    respaced = _with_params(bay_b, bay_b_params.model_copy(update={"joist_spacing": inches(19.2)}))
    after = _derive(grid, bay_a, respaced)

    bay_a_before = {eid for eid in _eids(before) if bay_a.did in eid}
    bay_a_after = {eid for eid in _eids(after) if bay_a.did in eid}
    assert bay_a_before == bay_a_after


# -- test 6: cross-branch correspondence -----------------------------------------------


def test_branches_differing_only_in_loads_share_all_eids() -> None:
    grid = decision("grid", "Grid", grid_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    framing = decision(
        "gravity_framing_strategy", "F", framing_params(), deps=[grid.did, loads.did]
    )
    heavier = _with_params(
        loads,
        {
            "area_loads": [
                {"case": "D", "magnitude": {"mag": 15.0, "unit": "psf"}},
                {"case": "L", "magnitude": {"mag": 100.0, "unit": "psf"}},
            ],
            "combo_set": "ASCE7-22-2.4-ASD",
        },
    )
    assert _eids(_derive(grid, loads, framing)) == _eids(_derive(grid, heavier, framing))


# -- test 7: honest renumbering --------------------------------------------------------


def test_spacing_change_renumbers_that_bay_only() -> None:
    grid = decision("grid", "Grid", grid_params())
    framing = decision("gravity_framing_strategy", "F", framing_params(), deps=[grid.did])
    before = _derive(grid, framing)
    respaced = _with_params(
        framing, framing_params().model_copy(update={"joist_spacing": inches(19.2)})
    )
    after = _derive(grid, respaced)

    joists_before = {eid for eid in _eids(before) if eid.startswith("jst:")}
    joists_after = {eid for eid in _eids(after) if eid.startswith("jst:")}
    assert joists_before != joists_after  # different members, honestly renumbered
    non_joists_before = _eids(before) - joists_before
    non_joists_after = _eids(after) - joists_after
    assert non_joists_before == non_joists_after  # beams and posts held


# -- partial derived models (standing requirement 10) -----------------------------------


def test_open_framing_derives_partially_never_raises() -> None:
    grid = decision("grid", "Grid", grid_params())
    open_framing = decision("gravity_framing_strategy", "Framing TBD", None, state="open")
    model = _derive(grid, open_framing)
    assert model.elements == []
    assert model.analysis is None  # absence is a valid state, not a failure
    assert [(o.did, o.kind) for o in model.open_decisions] == [
        (open_framing.did, "gravity_framing_strategy")
    ]


# -- the milestone structure -------------------------------------------------------------


def test_milestone_member_counts_spans_and_tributaries() -> None:
    model, _ = _milestone()
    joists = [e for e in model.elements if e.role == "joist"]
    beams = [e for e in model.elements if e.role == "beam"]
    posts = [e for e in model.elements if e.role == "post"]
    walls = [e for e in model.elements if e.role == "wall_segment"]
    headers = [e for e in model.elements if e.role == "header"]

    assert len(joists) == 19  # 24 ft at 16 in: ordinals 0..18
    assert len(beams) == 2
    assert len(posts) == 4
    assert len(walls) == 1
    assert len(headers) == 1

    span_m = 14.0 * 0.3048
    assert all(abs(j.length.si_mag - span_m) < 1e-9 for j in joists)
    interior_trib = 16.0 * 0.0254
    assert abs(joists[1].tributary_width.si_mag - interior_trib) < 1e-9  # type: ignore[union-attr]
    assert all(abs(b.tributary_width.si_mag - span_m / 2) < 1e-9 for b in beams)  # type: ignore[union-attr]


def test_header_intent_and_load_path_rerouting() -> None:
    model, decisions = _milestone()
    [header] = [e for e in model.elements if e.role == "header"]
    [intent] = header.intent
    assert intent.category == "gravity_load_path"
    assert intent.provenance.source == "derived"
    assert intent.provenance.inducer == decisions["opening"].did

    redirect_targets = [r.target for r in intent.relations if r.role == "redirects_load_around"]
    assert redirect_targets == [DecisionTarget(decision=decisions["opening"].did)]

    carried = sorted(
        r.target.eid
        for r in intent.relations
        if r.role == "carries" and isinstance(r.target, EidTarget)
    )
    # opening spans x = 8 ft .. 11 ft: joists at 96, 112, 128 in (ordinals 6, 7, 8)
    assert [eid.rsplit("+", 1)[1] for eid in carried] == ["006", "007", "008"]

    for joist_eid in carried:
        [joist] = [e for e in model.elements if e.eid == joist_eid]
        assert header.eid in joist.supports
    edges = {(e.bearing, e.on) for e in model.load_path}
    assert (header.eid, header.supports[0]) in edges  # header bears on the wall-line beam


def test_analysis_artifact_loads_combos_and_sources() -> None:
    model, _decisions = _milestone()
    analysis = model.analysis
    assert analysis is not None
    assert analysis.provenance.snapshot.startswith("sha256:")

    by_source = {e.source_eid: e.id for e in analysis.elements}
    flexural_eids = {e.eid for e in model.elements if e.role in ("joist", "beam", "header")}
    assert set(by_source) == flexural_eids

    # interior joist: w_L = 40 psf x 16 in tributary, straight down
    interior = next(eid for eid in by_source if eid.endswith("+001"))
    loads_on = {
        load.case: load.w_n_per_m for load in analysis.loads if load.element == by_source[interior]
    }
    expected_wl = 40.0 * _PSF * (16.0 * 0.0254)
    assert abs(loads_on["L"][2] + expected_wl) < 1e-9
    assert loads_on["L"][0] == loads_on["L"][1] == 0.0

    assert [c.name for c in analysis.combos] == ["D", "D+L"]
    assert {c.name: c.factors for c in analysis.combos}["D+L"] == {"D": 1.0, "L": 1.0}

    e_pa = 1.6e6 * (4.4482216152605 / 0.0254**2)
    assert all(abs(e.E_pa - e_pa) < 1e-6 for e in analysis.elements)


def test_bill_of_elements_and_countables() -> None:
    model, _ = _milestone()
    by_key = {(line.role, line.section): line for line in model.bill.lines}
    assert by_key[("joist", "2x10")].count == 19
    assert by_key[("beam", "4x12")].count == 2
    assert by_key[("post", "4x4")].count == 4
    assert by_key[("header", "4x12")].count == 1
    assert model.bill.countables.piece_count == len(model.elements)
    assert model.bill.countables.connection_count == len(model.load_path)
    assert model.bill.countables.crane_picks is None  # reserved, honestly absent


def test_rendered_eids_are_presentation_only() -> None:
    model, _decisions = _milestone()
    names = {line.line_id: line.name for line in grid_params().lines}
    [header] = [e for e in model.elements if e.role == "header"]
    rendered = render_eid(header.eid, names)
    assert "A" in rendered and LY_A not in rendered
    assert render_eid(header.eid, {}) == header.eid  # unknown tokens pass through


# -- hypothesis: tributary widths tile the region exactly --------------------------------


@given(
    spacing_in=st.sampled_from([12.0, 16.0, 19.2, 24.0]),
    width_ft=st.floats(min_value=4.0, max_value=60.0),
)
def test_joist_tributaries_tile_the_region(spacing_in: float, width_ft: float) -> None:
    lines = [
        line if line.line_id != LX2 else line.model_copy(update={"offset": ft(width_ft)})
        for line in grid_params().lines
    ]
    grid = decision("grid", "Grid", GridParams(lines=lines))
    framing = decision(
        "gravity_framing_strategy",
        "F",
        framing_params().model_copy(update={"joist_spacing": inches(spacing_in)}),
        deps=[grid.did],
    )
    model = _derive(grid, framing)
    total = sum(
        e.tributary_width.si_mag  # type: ignore[union-attr]
        for e in model.elements
        if e.role == "joist"
    )
    assert abs(total - width_ft * 0.3048) < 1e-6
