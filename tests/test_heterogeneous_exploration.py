"""Heterogeneous exploration (standing requirement 1, the vision's first
ambition): rank candidates that differ in decision *kind* — a wood framing
scheme against a steel framing scheme for the same region — through the ordinary
changeset → validate → derive → solve → evaluate pipeline, on the shared
method-neutral mass metric. NDS checks the wood, AISC checks the steel; nothing
in the exploration or evaluation layer assumes the candidates share a strategy.
"""

from pathlib import Path

from conftest import (
    AUTHOR,
    T0,
    compact_grid_params,
    decision,
    framing_params,
    levels_params,
    loads_params,
    lrfd_loads_params,
    steel_framing_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.explorations import (
    Exploration,
    ExplorationBudget,
    IntentPreservedConstraint,
    MetricConstraint,
    Objective,
    Proposal,
    SystemChoiceProposer,
    run_exploration,
)
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.objects import AddDecision, Changeset, Commit, Decision, ModifyDecision
from structural_kernel.queries import best_variant, what_carries, why
from structural_kernel.store import FileStore

OBJECTIVES = [Objective(metric="total_member_mass_kg", direction="min")]
CONSTRAINTS = [
    MetricConstraint(metric="max_unity", op="<=", value=1.0),
    IntentPreservedConstraint(),
]


def _commit_base(store: FileStore) -> tuple[str, Decision, Decision, Decision]:
    """Grid, levels, and (ASD) loads — the geometry the structural system is
    chosen over. The system itself is left unresolved for the exploration."""
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    result = propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=d) for d in (grid, levels, loads)]),
        author=AUTHOR,
        message="base: geometry + loads",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    tip = store.read_ref("main")
    assert tip is not None
    return tip, grid, levels, loads


def _systems(grid: Decision, levels: Decision, loads: Decision) -> list[Proposal]:
    deps = [grid.did, levels.did, loads.did]
    wood_framing = decision(
        "gravity_framing_strategy", "Wood joist framing", framing_params(), deps
    )
    steel_framing = decision(
        "steel_framing_strategy", "Steel WF frame", steel_framing_params(), deps
    )
    # The steel branch designs LRFD, so it also swaps the load assumptions onto
    # the §2.3 strength combinations — the same load decision, restated.
    loads_lrfd = loads.model_copy(update={"params": lrfd_loads_params().model_dump(mode="json")})
    return [
        Proposal(
            ops=[AddDecision(decision=wood_framing)],
            rationale="wood: joists on beams on posts, designed NDS/ASD",
        ),
        Proposal(
            ops=[AddDecision(decision=steel_framing), ModifyDecision(decision=loads_lrfd)],
            rationale="steel: WF beams on girders on columns, designed AISC/LRFD",
        ),
    ]


def _run(store: FileStore) -> Exploration:
    base, grid, levels, loads = _commit_base(store)
    return run_exploration(
        store,
        base_commit=base,
        objectives=OBJECTIVES,
        constraints=CONSTRAINTS,
        proposer=SystemChoiceProposer(_systems(grid, levels, loads)),
        budget=ExplorationBudget(max_solves=10, max_generations=3),
        engine=ReferenceEngine(),
        timestamp=T0,
    )


def _model(store: FileStore, commit_hash: str) -> DerivedModel:
    commit = store.get_model(commit_hash, Commit)
    return derive(load_snapshot(store, commit_hash), snapshot_hash=commit.snapshot)


def test_candidates_of_different_kinds_are_real_branches(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    exploration = _run(store)
    [generation] = exploration.generations
    assert len(generation.candidates) == 2
    assert all(c.committed and c.result is not None for c in generation.candidates)

    # the two candidates resolved DIFFERENT framing kinds — heterogeneity, not a
    # parameter sweep (standing requirement 1)
    kind_by_key: dict[str, str] = {}
    for candidate in generation.candidates:
        assert candidate.commit is not None
        snapshot = load_snapshot(store, candidate.commit)
        [framing] = [d for d in snapshot.decisions.values() if d.kind.endswith("framing_strategy")]
        kind_by_key[candidate.key] = framing.kind
    assert set(kind_by_key.values()) == {"gravity_framing_strategy", "steel_framing_strategy"}


def test_wood_and_steel_rank_together_on_the_shared_mass_metric(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    exploration = _run(store)
    [evaluation] = exploration.evaluations
    assert len(evaluation.per_candidate) == 2
    assert all(e.feasible for e in evaluation.per_candidate.values())  # both are real designs

    # both carry a mass; the ranking is by ascending mass across the two systems
    masses = {k: e.metrics["total_member_mass_kg"] for k, e in evaluation.per_candidate.items()}
    assert all(m > 0.0 for m in masses.values())
    ranked = evaluation.ranking
    assert set(ranked) == set(masses)
    assert [masses[k] for k in ranked] == sorted(masses.values())

    # the winner is the lightest feasible system, whichever kind that is
    winner = best_variant(exploration)
    assert winner is not None
    assert masses[winner] == min(masses.values())


def test_reevaluation_reuses_physics_and_keeps_the_heterogeneous_ranking(tmp_path: Path) -> None:
    from structural_kernel.explorations import evaluate

    store = FileStore(tmp_path)
    exploration = _run(store)
    again = evaluate(store, exploration)
    [original] = exploration.evaluations
    assert again.result_set == original.result_set  # same physics, keyed identically
    assert again.ranking == original.ranking


def test_queries_read_a_steel_member_unchanged(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    exploration = _run(store)
    [generation] = exploration.generations
    steel = next(
        c
        for c in generation.candidates
        if c.commit is not None
        and any(
            d.kind == "steel_framing_strategy"
            for d in load_snapshot(store, c.commit).decisions.values()
        )
    )
    assert steel.commit is not None
    model = _model(store, steel.commit)

    beam = next(e for e in model.elements if e.role == "beam")
    supports = what_carries(model, beam.eid)  # a beam bears on the girders
    assert supports and all(s.startswith("gdr:") for s in supports)
    reasons = why(model, beam.eid)  # its structural intent, derived not typed
    assert any(i.category == "gravity_load_path" for i in reasons)
    assert any(i.category == "serviceability" for i in reasons)
