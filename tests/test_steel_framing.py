"""Steel three-tier framing (ADR 0008): the derivation rule, the LRFD analysis
artifact, and the AISC design checks steel members earn automatically because
the checks resolve their engine by family."""

import pytest

from conftest import (
    compact_grid_params,
    decision,
    grid_params,
    levels_params,
    lrfd_loads_params,
    steel_framing_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.canonical import canonical_bytes, model_document
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.design_checks import run_design_checks
from structural_kernel.objects import Decision, LoadTarget
from structural_kernel.solver import LocalSolverService, SolveResult
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash


def _snapshot(*decisions: Decision) -> ResolvedSnapshot:
    return ResolvedSnapshot(decisions={d.did: d for d in decisions})


def _steel_model(grid_fn: object = grid_params) -> tuple[DerivedModel, dict[str, Decision]]:
    grid = decision("grid", "Grid", grid_fn())  # type: ignore[operator]
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "steel_framing_strategy",
        "Steel frame",
        steel_framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    snapshot = _snapshot(grid, levels, loads, framing)
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    return model, {"grid": grid, "levels": levels, "loads": loads, "framing": framing}


def _solved(model: DerivedModel) -> SolveResult:
    assert model.analysis is not None
    service = LocalSolverService(ReferenceEngine())
    [result] = service.results(service.submit([model.analysis]))
    assert result.status == "solved"
    return result


# -- the derived three-tier topology -----------------------------------------------------


def test_steel_frame_derives_beams_girders_and_columns() -> None:
    model, ids = _steel_model()
    beams = [e for e in model.elements if e.role == "beam"]
    girders = [e for e in model.elements if e.role == "girder"]
    columns = [e for e in model.elements if e.role == "column"]

    assert len(beams) == 5  # 24 ft at 6 ft: ordinals 0..4
    assert len(girders) == 2  # on lines A and B
    assert len(columns) == 4  # region corners

    for element in beams + girders + columns:
        assert element.family == "hot_rolled_steel"
        assert element.grade == "A992"
        assert element.design_method == "LRFD"
        assert ids["framing"].did in element.eid  # the inducing decision
    assert {e.section for e in beams} == {"W10x12"}
    assert {e.section for e in girders} == {"W12x16"}
    assert {e.section for e in columns} == {"W8x24"}


def test_steel_eids_use_the_three_tier_tokens() -> None:
    model, _ = _steel_model()
    prefixes = {e.eid.split(":", 1)[0] for e in model.elements}
    assert prefixes == {"bm", "gdr", "col"}


def test_steel_load_path_is_beam_on_girder_on_column() -> None:
    model, _ = _steel_model()
    by_eid = {e.eid: e for e in model.elements}
    beams = [e for e in model.elements if e.role == "beam"]
    girders = [e for e in model.elements if e.role == "girder"]

    # every beam bears on both girders...
    girder_eids = {g.eid for g in girders}
    for beam in beams:
        assert set(beam.supports) == girder_eids
    # ...and every girder bears on two columns.
    for girder in girders:
        assert len(girder.supports) == 2
        assert all(by_eid[s].role == "column" for s in girder.supports)
    # columns are the terminals: they support nothing.
    columns = [e for e in model.elements if e.role == "column"]
    assert all(not column.supports for column in columns)


def test_steel_members_carry_gravity_and_serviceability_intent() -> None:
    model, ids = _steel_model()
    for element in model.elements:
        categories = {i.category for i in element.intent}
        if element.role in ("beam", "girder"):
            assert categories == {"gravity_load_path", "serviceability"}
        else:  # columns carry the load path but not a deflection limit
            assert categories == {"gravity_load_path"}
        for instance in element.intent:
            assert instance.provenance.inducer == ids["framing"].did
    # the gravity intent names the load decision it carries
    beam = next(e for e in model.elements if e.role == "beam")
    gravity = next(i for i in beam.intent if i.category == "gravity_load_path")
    assert LoadTarget(load=ids["loads"].did) in [r.target for r in gravity.relations]


def test_steel_analysis_carries_lrfd_strength_and_service_combos() -> None:
    model, _ = _steel_model()
    assert model.analysis is not None
    names = {c.name: c.purpose for c in model.analysis.combos}
    assert names["1.4D"] == "strength"
    assert names["1.2D+1.6L"] == "strength"
    assert names["D"] == "service"
    assert names["D+L"] == "service"


def test_steel_frame_picks_every_primary_member() -> None:
    # 5 beams + 2 girders + 4 columns, each a crane pick (ADR 0012).
    model, _ = _steel_model()
    steel_members = [e for e in model.elements if e.family == "hot_rolled_steel"]
    assert model.bill.countables.crane_picks == len(steel_members) == 11


def test_steel_derivation_is_deterministic() -> None:
    grid = decision("grid", "Grid", grid_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "steel_framing_strategy", "F", steel_framing_params(), deps=[grid.did, loads.did]
    )
    a = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    b = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    assert canonical_bytes(model_document(a)) == canonical_bytes(model_document(b))


# -- the AISC checks steel earns for free ------------------------------------------------


def test_steel_members_get_aisc_lrfd_checks_deflection_stays_service() -> None:
    model, _ = _steel_model(compact_grid_params)  # a bay small enough to pass
    report = run_design_checks(model, _solved(model))

    bending = [c for c in report.checks if c.check == "bending"]
    assert bending and all(c.provision.startswith("AISC") for c in bending)
    # strength checks ran on a factored LRFD combo, never a service one
    assert all(c.combo.startswith("1.") for c in report.checks if c.check in ("bending", "shear"))
    # deflection ran on a service (unfactored) combo, never 1.2D+1.6L
    deflection = [c for c in report.checks if c.check.startswith("deflection")]
    assert deflection and all(not c.combo.startswith("1.") for c in deflection)
    # columns earn compression checks resolved through the AISC engine
    columns = {e.eid for e in model.elements if e.role == "column"}
    compression = [c for c in report.checks if c.check == "compression"]
    assert compression and {c.eid for c in compression} <= columns
    assert all(c.provision.startswith("AISC") for c in compression)
    # this small steel bay is a real design
    assert report.all_pass, [c.eid for c in report.checks if not c.passes]


def test_steel_bending_cites_the_gravity_intent_it_enforces() -> None:
    model, _ = _steel_model(compact_grid_params)
    report = run_design_checks(model, _solved(model))
    for check in report.checks:
        if check.check in ("bending", "shear", "compression"):
            assert check.enforces.category == "gravity_load_path"
            assert check.enforces.carrier == check.eid


def test_screening_results_are_refused_for_steel_too() -> None:
    model, _ = _steel_model(compact_grid_params)
    result = _solved(model)
    screening = result.model_copy(
        update={"engine": result.engine.model_copy(update={"fidelity": "screening"})}
    )
    with pytest.raises(ValueError, match="verification-grade"):
        run_design_checks(model, screening)
