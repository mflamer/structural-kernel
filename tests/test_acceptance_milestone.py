"""Phase 1 milestone acceptance tests (charter: "Phase 1 milestone").

Written early, red until earned. Each is a strict xfail: when an increment
makes one pass, the suite fails until the marker is removed — progress is
recorded deliberately, never by accident. Do not weaken these to match the
implementation; the charter governs.
"""

from pathlib import Path

import pytest

from conftest import (
    AUTHOR,
    T0,
    decision,
    framing_params,
    grid_params,
    lateral_params,
    levels_params,
    loads_params,
    opening_params,
)
from structural_kernel.derivation import derive
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.objects import AddDecision, Changeset, Commit, Decision, Snapshot
from structural_kernel.solver import LocalSolverService
from structural_kernel.store import FileStore
from structural_kernel.xara_adapter import XaraEngine, xara_available


def _increment(name: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        raises=NotImplementedError, strict=True, reason=f"red until increment: {name}"
    )


def _commit_milestone_structure(store: FileStore) -> list[Decision]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Floor loads", loads_params())
    framing = decision(
        "gravity_framing_strategy",
        "Floor framing",
        framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    structure = [
        grid,
        levels,
        loads,
        framing,
        decision("lateral_strategy", "Shear walls", lateral_params(), deps=[grid.did]),
        decision("opening", "Door D1", opening_params(), deps=[grid.did, framing.did, loads.did]),
    ]
    result = propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=d) for d in structure]),
        author=AUTHOR,
        message="the milestone structure, decisions only",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    return structure


def test_one_story_structure_is_defined_only_by_decisions(tmp_path: Path) -> None:
    """Grid + gravity framing strategy + one lateral strategy + one opening,
    all committed through the changeset pipeline. (Earned in increment 2.)"""
    store = FileStore(tmp_path)
    structure = _commit_milestone_structure(store)

    tip = store.read_ref("main")
    assert tip is not None
    snapshot = store.get_model(store.get_model(tip, Commit).snapshot, Snapshot)
    assert set(snapshot.decisions) == {d.did for d in structure}


def test_derivation_produces_members_analysis_artifact_and_bill(tmp_path: Path) -> None:
    """Member instances with spans and tributary widths; a self-contained
    analysis model artifact; a bill of elements. The opening induces a header
    carrying gravity-load-path intent — computed, not typed in.
    (Earned in increment 3.)"""
    store = FileStore(tmp_path)
    _commit_milestone_structure(store)

    tip = store.read_ref("main")
    assert tip is not None
    commit = store.get_model(tip, Commit)
    model = derive(load_snapshot(store, tip), snapshot_hash=commit.snapshot)

    joists = [e for e in model.elements if e.role == "joist"]
    assert joists and all(e.length.si_mag > 0 and e.tributary_width is not None for e in joists)
    assert model.analysis is not None
    assert model.analysis.provenance.snapshot == commit.snapshot
    assert model.bill.lines and model.bill.countables.piece_count == len(model.elements)

    [header] = [e for e in model.elements if e.role == "header"]
    [intent] = header.intent
    assert intent.category == "gravity_load_path"
    assert intent.provenance.source == "derived"  # computed, not typed in
    assert any(r.role == "redirects_load_around" for r in intent.relations)


@pytest.mark.skipif(
    not xara_available(),
    reason="ADR 0003 reserves this criterion for the blessed engine, and xara "
    "ships no Windows binaries — this test runs for real on Linux CI",
)
def test_solver_results_verify_against_hand_calcs(tmp_path: Path) -> None:
    """The solver service (local, cloud-shaped interface) solves the artifact;
    results match hand calculations within the stated tolerances.
    (Earned in increment 4, on platforms where xara's native runtime exists.)"""
    store = FileStore(tmp_path)
    _commit_milestone_structure(store)
    tip = store.read_ref("main")
    assert tip is not None
    commit = store.get_model(tip, Commit)
    model = derive(load_snapshot(store, tip), snapshot_hash=commit.snapshot)
    assert model.analysis is not None

    service = LocalSolverService(XaraEngine())
    [result] = service.results(service.submit([model.analysis]))
    assert result.status == "solved", result.failure
    assert result.engine.name == "xara"
    assert result.engine.fidelity == "verification"

    [combo] = [c for c in result.combos if c.combo == "D+L"]
    interior = next(e for e in model.elements if e.role == "joist" and e.eid.endswith("+001"))
    member = next(m for m in combo.members if m.source_eid == interior.eid)

    psf = 4.4482216152605 / 0.3048**2
    w = (15.0 + 40.0) * psf * interior.tributary_width.si_mag  # type: ignore[union-attr]
    span = interior.length.si_mag
    e_pa = 1.6e6 * (4.4482216152605 / 0.0254**2)
    b, d = 1.5 * 0.0254, 9.25 * 0.0254  # dressed 2x10
    i_strong = b * d**3 / 12
    assert member.max_deflection_m == pytest.approx(
        5 * w * span**4 / (384 * e_pa * i_strong), rel=0.005
    )
    assert member.max_abs_moment_nm == pytest.approx(w * span**2 / 8, rel=0.005)


@_increment("overrides")
def test_surveyed_override_flows_through_with_provenance() -> None:
    """A pinned surveyed member size differing from the derived value flows
    through derivation and analysis with provenance intact."""
    raise NotImplementedError


@_increment("intent checkers + solve-time design checks")
def test_intent_violating_changeset_is_rejected_with_structured_error() -> None:
    """Deleting the header while the opening remains dies in validation with a
    structured error citing the violated intent and the broken load path."""
    raise NotImplementedError


@_increment("exploration loop")
def test_exploration_sweep_is_persisted_replayable_and_pluggable() -> None:
    """Joist spacing 12/16/19.2/24 in crossed with beam layouts; objective min weight;
    hard constraints unity and deflection (L/360 live, L/240 total); concurrent
    dispatch; every generation persisted; replayable; stub LLM proposer slots
    into the same protocol."""
    raise NotImplementedError


@_increment("exploration loop")
def test_milestone_queries_answer() -> None:
    """ "What carries joist J5?", "why does opening D1 have a header?", "which
    variant minimizes weight while keeping all members under unity?"."""
    raise NotImplementedError
