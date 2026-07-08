"""The exploration loop: real branches, batch dispatch, persisted generations,
the separate evaluation layer, replayability, and the pluggable proposer seam."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from conftest import (
    AUTHOR,
    T0,
    compact_grid_params,
    decision,
    framing_params,
    levels_params,
    loads_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.derivation import AnalysisModel
from structural_kernel.explorations import (
    Convergence,
    Exploration,
    ExplorationBudget,
    GridSweepProposer,
    IntentPreservedConstraint,
    MetricConstraint,
    Objective,
    StubLLMProposer,
    evaluate,
    exploration_ref,
    run_exploration,
)
from structural_kernel.kernel import propose
from structural_kernel.objects import AddDecision, Changeset
from structural_kernel.queries import best_variant
from structural_kernel.solver import LocalSolverService
from structural_kernel.store import FileStore
from structural_kernel.units import Quantity
from structural_kernel.validation import ValidationReport


def _inches(value: float) -> Quantity:
    return Quantity(mag=value, unit="in")


SPACINGS = [_inches(v) for v in (12.0, 16.0, 19.2, 24.0)]
LAYOUTS: list[dict[str, object]] = [
    {"beam_section": "4x12"},
    {"beam_section": "4x10"},
    {"beam_section": "4x4"},  # honestly infeasible: rankable, never a winner
]
OBJECTIVES = [Objective(metric="total_member_mass_kg", direction="min")]
CONSTRAINTS = [
    MetricConstraint(metric="max_unity", op="<=", value=1.0),
    IntentPreservedConstraint(),
]


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


def _run(store: FileStore, base: str, **overrides: object) -> Exploration:
    kwargs: dict[str, object] = {
        "base_commit": base,
        "objectives": OBJECTIVES,
        "constraints": CONSTRAINTS,
        "proposer": GridSweepProposer(SPACINGS, list(LAYOUTS)),  # type: ignore[arg-type]
        "budget": ExplorationBudget(max_solves=50, max_generations=5),
        "convergence": Convergence(),
        "engine": ReferenceEngine(),
        "timestamp": T0,
    }
    kwargs.update(overrides)
    return run_exploration(store, **kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def sweep() -> tuple[FileStore, str, Exploration]:
    root = Path(__file__).parent / ".pytest_cache" / "exploration-store"
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    store = FileStore(root)
    base = _commit_compact_bay(store)
    return store, base, _run(store, base)


def test_sweep_produces_the_full_cross_product_as_real_branches(
    sweep: tuple[FileStore, str, Exploration],
) -> None:
    store, _base, exploration = sweep
    [generation] = exploration.generations
    assert len(generation.candidates) == len(SPACINGS) * len(LAYOUTS)
    for candidate in generation.candidates:
        assert candidate.rationale  # mandatory, even mechanical
        assert candidate.changeset in store  # persisted even if rejected
        assert candidate.report in store
        assert candidate.committed
        assert store.read_ref(candidate.branch) == candidate.commit
    assert exploration.status == "converged"


def test_evaluation_is_a_separate_layer_with_feasibility_and_ranking(
    sweep: tuple[FileStore, str, Exploration],
) -> None:
    _, _, exploration = sweep
    [evaluation] = exploration.evaluations
    assert evaluation.cost_basis is None  # phase 1: physics-only metrics
    assert len(evaluation.per_candidate) == len(SPACINGS) * len(LAYOUTS)

    # the 4x4 beam layout fails its checks; the others pass
    feasible = [k for k, e in evaluation.per_candidate.items() if e.feasible]
    infeasible = [k for k, e in evaluation.per_candidate.items() if not e.feasible]
    assert len(feasible) == len(SPACINGS) * 2
    assert len(infeasible) == len(SPACINGS)
    assert all(evaluation.per_candidate[k].metrics["max_unity"] > 1.0 for k in infeasible)

    # ranking: feasible first, ascending mass
    ranked_feasible = evaluation.ranking[: len(feasible)]
    masses = [evaluation.per_candidate[k].metrics["total_member_mass_kg"] for k in ranked_feasible]
    assert masses == sorted(masses)
    assert set(ranked_feasible) == set(feasible)


def test_the_winner_is_the_lightest_feasible_variant(
    sweep: tuple[FileStore, str, Exploration],
) -> None:
    _, _, exploration = sweep
    winner = best_variant(exploration)
    assert winner is not None
    [evaluation] = exploration.evaluations
    assert evaluation.per_candidate[winner].feasible
    # widest spacing + lighter passing beam = least wood
    winner_candidate = next(
        c for g in exploration.generations for c in g.candidates if c.key == winner
    )
    assert "24" in winner_candidate.rationale
    assert "4x10" in winner_candidate.rationale


def test_generations_persist_and_the_record_reloads(
    sweep: tuple[FileStore, str, Exploration],
) -> None:
    store, _, exploration = sweep
    ref = exploration_ref(exploration.exploration_id)
    stored_hash = store.read_ref(ref)
    assert stored_hash is not None
    reloaded = store.get_model(stored_hash, Exploration)
    assert reloaded == exploration
    for generation in reloaded.generations:
        for candidate in generation.candidates:
            if candidate.artifact is not None:
                store.get_model(candidate.artifact, AnalysisModel)  # solvable record


def test_reevaluation_reuses_stored_physics_without_solving(
    sweep: tuple[FileStore, str, Exploration],
) -> None:
    store, _, exploration = sweep
    again = evaluate(store, exploration)
    [original] = exploration.evaluations
    assert again.result_set == original.result_set  # same physics, keyed identically
    assert again.ranking == original.ranking
    assert again.per_candidate == original.per_candidate


def test_replay_reproduces_the_searched_space(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)
    first = _run(store, base)
    second = _run(store, base)

    def record(e: Exploration) -> list[tuple[str, str, bool]]:
        return [(c.key, c.changeset, c.committed) for g in e.generations for c in g.candidates]

    assert record(first) == record(second)  # same changesets, same outcomes
    assert first.evaluations[-1].ranking == second.evaluations[-1].ranking


def test_batch_dispatch_is_one_submit_per_generation(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)
    calls: list[int] = []

    class CountingEngine(ReferenceEngine):
        pass

    real_submit = LocalSolverService.submit

    def counting_submit(self: LocalSolverService, batch: Sequence[AnalysisModel]) -> str:
        calls.append(len(batch))
        return real_submit(self, batch)

    LocalSolverService.submit = counting_submit  # type: ignore[method-assign]
    try:
        _run(store, base, engine=CountingEngine())
    finally:
        LocalSolverService.submit = real_submit  # type: ignore[method-assign]
    assert calls == [len(SPACINGS) * len(LAYOUTS)]  # the whole generation, one call


def test_rejected_candidates_are_recorded_and_never_solved(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)
    exploration = _run(
        store,
        base,
        proposer=GridSweepProposer(
            [_inches(16.0)],
            [{"beam_section": "4x10"}, {"beam_section": "3x17"}],  # no such section
        ),
    )
    [generation] = exploration.generations
    rejected = [c for c in generation.candidates if not c.committed]
    assert len(rejected) == 1
    assert rejected[0].result is None  # never solved
    report = store.get_model(rejected[0].report, ValidationReport)
    assert report.outcome == "rejected"
    assert report.issues[0].code == "derivation_failure"
    assert rejected[0].key not in exploration.evaluations[-1].per_candidate


def test_solve_budget_exhaustion_is_recorded_honestly(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)
    exploration = _run(store, base, budget=ExplorationBudget(max_solves=3, max_generations=5))
    assert exploration.status == "budget_exhausted"
    [generation] = exploration.generations
    solved = [c for c in generation.candidates if c.result is not None]
    unsolved = [c for c in generation.candidates if c.committed and c.result is None]
    assert len(solved) == 3
    assert unsolved  # recorded, honestly unsolved


def test_the_stub_llm_proposer_slots_into_the_same_protocol(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base = _commit_compact_bay(store)
    exploration = _run(store, base, proposer=StubLLMProposer())
    assert exploration.proposer.strategy == "llm_stub"
    [generation] = exploration.generations
    [candidate] = generation.candidates
    assert candidate.committed and candidate.result is not None
    assert "llm_stub" in candidate.rationale
    assert exploration.evaluations[-1].per_candidate[candidate.key].feasible
