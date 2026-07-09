"""Cost as the ranking variable, honestly modeled (the vision's item 2; ADR
0012).

A committed ``cost_basis`` decision prices a heterogeneous wood-vs-steel slate by
layered installed cost — material from derived quantities, installation from
derived countables — and the ranking cites its basis. The load-bearing beat:
re-ranking under a revised basis (the fabricator's re-quote) appends a new
evaluation over the *same* stored solve results — no re-solving.
"""

from pathlib import Path

import pytest

from conftest import (
    AUTHOR,
    T0,
    compact_grid_params,
    cost_basis_params,
    decision,
    framing_params,
    levels_params,
    loads_params,
    lrfd_loads_params,
    steel_framing_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.explorations import (
    Exploration,
    ExplorationBudget,
    IntentPreservedConstraint,
    MetricConstraint,
    Objective,
    Proposal,
    SystemChoiceProposer,
    evaluate,
    run_exploration,
    uncertainty_note,
)
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.objects import AddDecision, Changeset, Decision, ModifyDecision
from structural_kernel.queries import best_variant
from structural_kernel.solver import SolveResult
from structural_kernel.store import FileStore

INSTALLED = [Objective(metric="installed_cost_usd", direction="min")]
CONSTRAINTS = [
    MetricConstraint(metric="max_unity", op="<=", value=1.0),
    IntentPreservedConstraint(),
]


def _commit_base(store: FileStore, basis: Decision) -> tuple[str, list[Decision]]:
    """Geometry, loads, and the cost basis are committed as ordinary decisions;
    the structural system is left unresolved for the exploration to choose."""
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    result = propose(
        store,
        Changeset(
            base_commit=None,
            ops=[AddDecision(decision=d) for d in (grid, levels, loads, basis)],
        ),
        author=AUTHOR,
        message="base: geometry + loads + cost basis",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    tip = store.read_ref("main")
    assert tip is not None
    return tip, [grid, levels, loads]


def _systems(grid: Decision, levels: Decision, loads: Decision) -> list[Proposal]:
    deps = [grid.did, levels.did, loads.did]
    wood = decision("gravity_framing_strategy", "Wood joist framing", framing_params(), deps)
    steel = decision("steel_framing_strategy", "Steel WF frame", steel_framing_params(), deps)
    loads_lrfd = loads.model_copy(update={"params": lrfd_loads_params().model_dump(mode="json")})
    return [
        Proposal(ops=[AddDecision(decision=wood)], rationale="wood: NDS/ASD joists on beams"),
        Proposal(
            ops=[AddDecision(decision=steel), ModifyDecision(decision=loads_lrfd)],
            rationale="steel: AISC/LRFD WF beams on girders on columns",
        ),
    ]


def _run(store: FileStore, basis: Decision) -> Exploration:
    base, (grid, levels, loads) = _commit_base(store, basis)
    return run_exploration(
        store,
        base_commit=base,
        objectives=INSTALLED,
        constraints=CONSTRAINTS,
        proposer=SystemChoiceProposer(_systems(grid, levels, loads)),
        budget=ExplorationBudget(max_solves=10, max_generations=3),
        engine=ReferenceEngine(),
        cost_basis=basis,
        timestamp=T0,
    )


def _kind_by_key(store: FileStore, exploration: Exploration) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for candidate in exploration.generations[0].candidates:
        assert candidate.commit is not None
        snapshot = load_snapshot(store, candidate.commit)
        [framing] = [d for d in snapshot.decisions.values() if d.kind.endswith("framing_strategy")]
        kinds[candidate.key] = framing.kind
    return kinds


# -- pricing composition -----------------------------------------------------------------


def test_installed_cost_is_material_plus_installation_and_ranks(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    basis = decision("cost_basis", "Regional default (Mar)", cost_basis_params())
    exploration = _run(store, basis)
    [evaluation] = exploration.evaluations
    assert evaluation.cost_basis == basis.did  # the ranking cites its basis

    for per in evaluation.per_candidate.values():
        material = per.metrics["material_cost_usd"]
        installation = per.metrics["installation_cost_usd"]
        assert material > 0.0 and installation > 0.0
        assert per.metrics["installed_cost_usd"] == pytest.approx(material + installation)

    # ranking is feasible-first by ascending installed cost
    feasible = [k for k, e in evaluation.per_candidate.items() if e.feasible]
    costs = [evaluation.per_candidate[k].metrics["installed_cost_usd"] for k in evaluation.ranking]
    assert costs == sorted(costs)
    winner = best_variant(exploration)
    assert winner in feasible
    assert evaluation.per_candidate[winner].metrics["installed_cost_usd"] == min(
        evaluation.per_candidate[k].metrics["installed_cost_usd"] for k in feasible
    )


def test_installation_cost_reflects_steel_picks_and_piece_count(tmp_path: Path) -> None:
    # Steel members each cost a crane pick; wood is hand-set. Installation cost is
    # not a fixed fraction of material — that is the whole point of item 2.
    store = FileStore(tmp_path)
    basis = decision("cost_basis", "basis", cost_basis_params())
    exploration = _run(store, basis)
    [evaluation] = exploration.evaluations
    kinds = _kind_by_key(store, exploration)
    steel_key = next(k for k, v in kinds.items() if v == "steel_framing_strategy")
    wood_key = next(k for k, v in kinds.items() if v == "gravity_framing_strategy")

    steel = evaluation.per_candidate[steel_key].metrics
    wood = evaluation.per_candidate[wood_key].metrics
    # installation is a different share of installed cost for the two systems
    steel_share = steel["installation_cost_usd"] / steel["installed_cost_usd"]
    wood_share = wood["installation_cost_usd"] / wood["installed_cost_usd"]
    assert steel_share != pytest.approx(wood_share)


# -- the re-rank beat: no re-solving ------------------------------------------------------


def test_requoting_steel_reranks_without_resolving(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    basis1 = decision("cost_basis", "March basis", cost_basis_params(steel_rate_usd_per_lb=1.20))
    exploration = _run(store, basis1)
    [priced] = exploration.evaluations
    kinds = _kind_by_key(store, exploration)
    steel_key = next(k for k, v in kinds.items() if v == "steel_framing_strategy")
    wood_key = next(k for k, v in kinds.items() if v == "gravity_framing_strategy")

    # the fabricator re-quotes erected steel up 20% — a NEW cost_basis decision
    basis2 = decision(
        "cost_basis", "Re-quote: steel +20%", cost_basis_params(steel_rate_usd_per_lb=1.20 * 1.20)
    )
    reranked = evaluate(store, exploration, cost_basis=basis2)

    # SAME physics: the result set is byte-identical; nothing was re-solved.
    assert reranked.result_set == priced.result_set
    assert reranked.cost_basis == basis2.did != priced.cost_basis
    # every stored SolveResult reused verbatim (they are still the candidates' results)
    for candidate in exploration.generations[0].candidates:
        assert candidate.result is not None
        store.get_model(candidate.result, SolveResult)  # unchanged, still resolvable

    # only steel's material cost moved; wood's installed cost is untouched.
    assert reranked.per_candidate[wood_key].metrics["installed_cost_usd"] == pytest.approx(
        priced.per_candidate[wood_key].metrics["installed_cost_usd"]
    )
    assert (
        reranked.per_candidate[steel_key].metrics["material_cost_usd"]
        > priced.per_candidate[steel_key].metrics["material_cost_usd"]
    )
    assert "priced under cost_basis" in reranked.notes


def test_a_cost_objective_without_a_basis_is_a_configuration_error(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    basis = decision("cost_basis", "basis", cost_basis_params())
    base, (grid, levels, loads) = _commit_base(store, basis)
    with pytest.raises(ValueError, match="cost assumptions are decisions"):
        run_exploration(
            store,
            base_commit=base,
            objectives=INSTALLED,
            constraints=CONSTRAINTS,
            proposer=SystemChoiceProposer(_systems(grid, levels, loads)),
            budget=ExplorationBudget(max_solves=10, max_generations=3),
            engine=ReferenceEngine(),
            cost_basis=None,  # the objective ranks on cost but no basis was given
            timestamp=T0,
        )


# -- lead-time flags annotate, never price ------------------------------------------------


def test_lead_time_is_flagged_but_never_priced_in(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    basis = decision("cost_basis", "basis", cost_basis_params())
    exploration = _run(store, basis)
    [evaluation] = exploration.evaluations
    kinds = _kind_by_key(store, exploration)
    wood_key = next(k for k, v in kinds.items() if v == "gravity_framing_strategy")

    # the basis carries a sawn-lumber lead time; the wood candidate is flagged...
    flags = evaluation.per_candidate[wood_key].flags
    assert any("sawn_lumber" in f and "lead time" in f and "not priced" in f for f in flags)

    # ...but the flag changes no number: pricing with the lead time removed gives
    # the identical installed cost.
    no_lead = cost_basis_params()
    no_lead = no_lead.model_copy(update={"lead_times": []})
    basis_no_lead = decision("cost_basis", "no lead times", no_lead)
    reranked = evaluate(store, exploration, cost_basis=basis_no_lead)
    assert reranked.per_candidate[wood_key].metrics["installed_cost_usd"] == pytest.approx(
        evaluation.per_candidate[wood_key].metrics["installed_cost_usd"]
    )
    assert not reranked.per_candidate[wood_key].flags


# -- "inside the noise" -------------------------------------------------------------------


def test_close_comparison_is_reported_inside_the_noise() -> None:
    band = 4.0  # the basis's committed uncertainty percentage
    assert "inside the noise" in uncertainty_note([100_000.0, 103_000.0], band)  # +3%
    outside = uncertainty_note([100_000.0, 112_000.0], band)  # +12%
    assert "outside" in outside and "inside the noise" not in outside
    assert uncertainty_note([100_000.0], band) == ""  # nothing to compare
