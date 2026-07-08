"""Phase 1 milestone acceptance tests (charter: "Phase 1 milestone").

Written early and red until earned, increment by increment; as of increment 7
(2026-07-08) every criterion is green. Do not weaken these to match the
implementation; the charter governs. Per the charter, passing this suite means
phase 1 stops here for a representation review before any scope is added.
"""

from pathlib import Path

import pytest

from conftest import (
    AUTHOR,
    T0,
    compact_grid_params,
    decision,
    framing_params,
    grid_params,
    lateral_params,
    levels_params,
    loads_params,
    opening_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.derivation import derive
from structural_kernel.explorations import (
    Exploration,
    ExplorationBudget,
    GridSweepProposer,
    IntentPreservedConstraint,
    MetricConstraint,
    Objective,
    StubLLMProposer,
    exploration_ref,
    run_exploration,
)
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.objects import (
    AddDecision,
    AddOverride,
    Changeset,
    Commit,
    Decision,
    ModifyDecision,
    Override,
    OverrideProvenance,
    OverrideTarget,
    Snapshot,
)
from structural_kernel.queries import best_variant, header_for_opening, what_carries, why
from structural_kernel.solver import LocalSolverService
from structural_kernel.store import FileStore
from structural_kernel.units import Quantity
from structural_kernel.xara_adapter import XaraEngine, xara_available


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
    [intent] = [i for i in header.intent if i.category == "gravity_load_path"]
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


def test_surveyed_override_flows_through_with_provenance(tmp_path: Path) -> None:
    """A pinned surveyed member size differing from the derived value flows
    through derivation and analysis with provenance intact.
    (Earned in increment 5.)"""
    store = FileStore(tmp_path)
    structure = _commit_milestone_structure(store)
    framing = next(d for d in structure if d.kind == "gravity_framing_strategy")
    joist_eid = next(
        e.eid
        for e in derive(
            load_snapshot(store, store.read_ref("main")),
            snapshot_hash="sha256:" + "0" * 64,
        ).elements
        if e.role == "joist" and e.eid.endswith("+004")
    )
    assert framing.params is not None and framing.params["joist_section"] == "2x10"

    override = Override(
        target=OverrideTarget(eid=joist_eid, field="section"),
        value="4x10",
        provenance=OverrideProvenance(
            observed_by="M. Flamer",
            method="site_survey_tape",
            observed_at="2026-06-30",
            confidence="measured",
        ),
    )
    result = propose(
        store,
        Changeset(base_commit=store.read_ref("main"), ops=[AddOverride(override=override)]),
        author=AUTHOR,
        message="pin surveyed joist size",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues

    tip = store.read_ref("main")
    assert tip is not None
    commit = store.get_model(tip, Commit)
    model = derive(load_snapshot(store, tip), snapshot_hash=commit.snapshot)

    [element] = [e for e in model.elements if e.eid == joist_eid]
    assert element.section == "4x10"  # differs from the derived 2x10
    assert element.overridden["section"].observed_by == "M. Flamer"
    assert element.overridden["section"].confidence == "measured"
    [attachment] = model.override_attachments
    assert attachment.state == "attached"

    # and it flows into analysis stiffness exactly as if derived
    assert model.analysis is not None
    analysis_element = next(e for e in model.analysis.elements if e.source_eid == joist_eid)
    b, d = 3.5 * 0.0254, 9.25 * 0.0254  # dressed 4x10
    assert abs(analysis_element.I_strong_m4 - b * d**3 / 12) < 1e-12


def test_intent_violating_changeset_is_rejected_with_structured_error(
    tmp_path: Path,
) -> None:
    """Deleting the header while the opening remains dies in validation with a
    structured error citing the violated intent and the broken load path.
    (Earned in increment 6.)

    The header is derived, so 'deleting it' means proposing the change that
    makes it vanish: dropping the framing dep from the opening decision. The
    opening remains; the header disappears; joists bear inside the hole."""
    store = FileStore(tmp_path)
    structure = _commit_milestone_structure(store)
    opening = next(d for d in structure if d.kind == "opening")
    framing = next(d for d in structure if d.kind == "gravity_framing_strategy")

    orphaned = opening.model_copy(update={"deps": [d for d in opening.deps if d != framing.did]})
    result = propose(
        store,
        Changeset(
            base_commit=store.read_ref("main"),
            ops=[ModifyDecision(decision=orphaned)],
        ),
        author=AUTHOR,
        message="delete the header while the opening remains",
        timestamp=T0,
    )
    assert result.outcome == "rejected"
    [issue] = result.issues
    assert issue.code == "intent_violation"
    assert issue.severity == "error"
    assert issue.detail["category"] == "gravity_load_path"  # the violated intent
    assert issue.detail["violated"] == "redirects_load_around"
    assert issue.detail["opening"] == opening.did
    broken_path = issue.detail["broken_path"]
    assert isinstance(broken_path, list)
    assert any(str(part).startswith("jst:") for part in broken_path)  # the broken load path
    assert store.read_ref("main") is not None  # tip unchanged; nothing half-applied


def _sweep_exploration(store: FileStore, base: str) -> Exploration:
    return run_exploration(
        store,
        base_commit=base,
        objectives=[Objective(metric="total_member_mass_kg", direction="min")],
        # "all members under unity" — max_unity spans strength AND the L/360
        # live / L/240 total deflection checks (they report as unity too)
        constraints=[
            MetricConstraint(metric="max_unity", op="<=", value=1.0),
            IntentPreservedConstraint(),
        ],
        proposer=GridSweepProposer(
            [Quantity(mag=v, unit="in") for v in (12.0, 16.0, 19.2, 24.0)],
            [{"beam_section": "4x12"}, {"beam_section": "4x10"}, {"beam_section": "4x4"}],
        ),
        budget=ExplorationBudget(max_solves=50, max_generations=5),
        engine=ReferenceEngine(),
        timestamp=T0,
    )


def _commit_compact_bay(store: FileStore) -> str:
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    framing = decision(
        "gravity_framing_strategy",
        "Bay framing",
        framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    result = propose(
        store,
        Changeset(
            base_commit=None,
            ops=[AddDecision(decision=d) for d in (grid, levels, loads, framing)],
        ),
        author=AUTHOR,
        message="compact bay",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    tip = store.read_ref("main")
    assert tip is not None
    return tip


def test_exploration_sweep_is_persisted_replayable_and_pluggable(tmp_path: Path) -> None:
    """Joist spacing 12/16/19.2/24 in crossed with beam layouts; objective min weight;
    hard constraints unity and deflection (L/360 live, L/240 total); concurrent
    dispatch; every generation persisted; replayable; stub LLM proposer slots
    into the same protocol. (Earned in increment 7.)"""
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)

    exploration = _sweep_exploration(store, base)
    [generation] = exploration.generations
    assert len(generation.candidates) == 12  # 4 spacings x 3 layouts
    assert all(c.rationale for c in generation.candidates)

    # every generation persisted: the record reloads from the store byte-true
    stored = store.read_ref(exploration_ref(exploration.exploration_id))
    assert stored is not None
    assert store.get_model(stored, Exploration) == exploration

    # replayable: the same base and proposer reproduce the searched space
    replay = _sweep_exploration(store, base)
    assert [(c.key, c.changeset) for g in replay.generations for c in g.candidates] == [
        (c.key, c.changeset) for g in exploration.generations for c in g.candidates
    ]
    assert replay.evaluations[-1].ranking == exploration.evaluations[-1].ranking

    # the pluggable seam: an LLM stub satisfies the identical protocol
    llm = run_exploration(
        store,
        base_commit=base,
        objectives=[Objective(metric="total_member_mass_kg", direction="min")],
        constraints=[MetricConstraint(metric="max_unity", op="<=", value=1.0)],
        proposer=StubLLMProposer(),
        budget=ExplorationBudget(max_solves=5, max_generations=2),
        engine=ReferenceEngine(),
        timestamp=T0,
    )
    assert llm.proposer.strategy == "llm_stub"
    [llm_generation] = llm.generations
    assert llm_generation.candidates[0].committed


def test_milestone_queries_answer(tmp_path: Path) -> None:
    """ "What carries joist J5?", "why does opening D1 have a header?", "which
    variant minimizes weight while keeping all members under unity?".
    (Earned in increment 7.)"""
    store = FileStore(tmp_path)
    structure = _commit_milestone_structure(store)
    tip = store.read_ref("main")
    assert tip is not None
    commit = store.get_model(tip, Commit)
    model = derive(load_snapshot(store, tip), snapshot_hash=commit.snapshot)
    framing = next(d for d in structure if d.kind == "gravity_framing_strategy")
    opening = next(d for d in structure if d.kind == "opening")

    # "what carries joist J5?" — an ordinary joist bears on both beams
    j5 = next(e.eid for e in model.elements if e.role == "joist" and e.eid.endswith("+005"))
    carriers = what_carries(model, j5)
    assert carriers and all(c.startswith("bm:") for c in carriers)

    # a redirected joist answers with the header — the load path knows
    j7 = next(e.eid for e in model.elements if e.role == "joist" and e.eid.endswith("+007"))
    assert any(c.startswith("hdr:") for c in what_carries(model, j7))

    # "why does opening D1 have a header?" — computed intent, citing the opening
    header_eid = header_for_opening(model, opening.did)
    assert header_eid is not None
    reasons = why(model, header_eid)
    gravity = next(i for i in reasons if i.category == "gravity_load_path")
    assert gravity.provenance.inducer == opening.did
    assert any(r.role == "redirects_load_around" for r in gravity.relations)

    # "which variant minimizes weight while keeping all members under unity?"
    exploration_store = FileStore(tmp_path / "exploration")
    base = _commit_compact_bay(exploration_store)
    exploration = _sweep_exploration(exploration_store, base)
    winner = best_variant(exploration)
    assert winner is not None
    [evaluation] = exploration.evaluations
    assert evaluation.per_candidate[winner].feasible
    feasible_masses = [
        e.metrics["total_member_mass_kg"] for e in evaluation.per_candidate.values() if e.feasible
    ]
    assert evaluation.per_candidate[winner].metrics["total_member_mass_kg"] == min(feasible_masses)
    assert framing.did  # the milestone structure remains the record of why
