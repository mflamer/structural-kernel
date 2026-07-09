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
    usd,
)
from reference_solver import ReferenceEngine
from structural_kernel.costing import QUANTITY_KINDS, QuantityKind, register_quantity_kind
from structural_kernel.decisions import CostFactor, DirectPrice
from structural_kernel.derivation import DerivedModel
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
from structural_kernel.materials import engine_for, families
from structural_kernel.objects import AddDecision, Changeset, Decision, ModifyDecision
from structural_kernel.queries import best_variant
from structural_kernel.solver import SolveResult
from structural_kernel.store import FileStore
from structural_kernel.units import Dimension

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

    # the basis carries a sawn-lumber lead-time flag factor; the wood candidate is
    # flagged...
    flags = evaluation.per_candidate[wood_key].flags
    assert any("sawn_lumber" in f and "not priced" in f for f in flags)

    # ...but the flag changes no number: pricing with the flag factor removed gives
    # the identical installed cost (a flag never sums).
    full = cost_basis_params()
    no_lead = full.model_copy(
        update={"factors": [f for f in full.factors if f.pricing.kind != "flag"]}
    )
    basis_no_lead = decision("cost_basis", "no lead times", no_lead)
    reranked = evaluate(store, exploration, cost_basis=basis_no_lead)
    assert reranked.per_candidate[wood_key].metrics["installed_cost_usd"] == pytest.approx(
        evaluation.per_candidate[wood_key].metrics["installed_cost_usd"]
    )
    assert not reranked.per_candidate[wood_key].flags


# -- material-only vs installed: one schema, re-rankable, no re-solve ----------------------


def test_material_only_and_installed_are_one_schema_rerankable(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    installed_basis = decision("cost_basis", "installed", cost_basis_params(installed=True))
    exploration = _run(store, installed_basis)
    [installed_eval] = exploration.evaluations

    # the SAME schema, only fewer factors — material factors alone
    material_basis = decision("cost_basis", "material only", cost_basis_params(installed=False))
    material_eval = evaluate(store, exploration, cost_basis=material_basis)

    assert material_eval.result_set == installed_eval.result_set  # physics reused, no solve
    for key, per in material_eval.per_candidate.items():
        assert per.metrics["installation_cost_usd"] == pytest.approx(0.0)
        assert per.metrics["installed_cost_usd"] == pytest.approx(per.metrics["material_cost_usd"])
        # installed cost adds real installation on top of material
        assert (
            per.metrics["installed_cost_usd"]
            < installed_eval.per_candidate[key].metrics["installed_cost_usd"]
        )


# -- generalization proof: a carbon factor, zero kernel change ----------------------------


def test_a_carbon_factor_prices_and_ranks_with_no_kernel_change(tmp_path: Path) -> None:
    # A cost driver nobody planned for — a carbon price over a CO2e countable —
    # registers and prices with no kernel edit (note 0003's real proof). The
    # resolver only aggregates derived mass; it invents no physical quantity.
    intensity = {"hot_rolled_steel": 1.9, "sawn_lumber": -0.9}  # kgCO2e per kg, illustrative

    def resolve_co2e(model: DerivedModel, family: str | None, role: str | None) -> float:
        total = 0.0
        for element in model.elements:
            if element.grade is None or element.family not in families():
                continue
            if family is not None and element.family != family:
                continue
            engine = engine_for(element.family)
            section = engine.section_properties(element.section)
            density = engine.mass_density_kg_m3(element.grade)
            if section is None or density is None:
                continue
            mass = section.area_m2 * element.length.si_mag * density
            total += mass * intensity.get(element.family, 0.0)
        return total

    register_quantity_kind(QuantityKind("co2e", Dimension.MASS, resolve_co2e))
    try:
        with_carbon = cost_basis_params()  # a copy we extend with a carbon factor
        with_carbon = with_carbon.model_copy(
            update={
                "factors": [
                    *with_carbon.factors,
                    CostFactor(
                        quantity_kind="co2e",
                        pricing=DirectPrice(unit_price=usd(0.05, "USD/kg")),  # $50/tCO2e
                        source="carbon price, illustrative",
                    ),
                ]
            }
        )
        store = FileStore(tmp_path)
        exploration = _run(store, decision("cost_basis", "basis + carbon", with_carbon))
        [carbon_eval] = exploration.evaluations
        assert best_variant(exploration) is not None  # it ranked

        # the carbon factor actually moved the number: re-pricing the same physics
        # under a no-carbon basis differs, and it ran no solve.
        without = evaluate(
            store, exploration, cost_basis=decision("cost_basis", "no carbon", cost_basis_params())
        )
        assert without.result_set == carbon_eval.result_set
        steel_key = next(
            k for k, v in _kind_by_key(store, exploration).items() if v == "steel_framing_strategy"
        )
        assert carbon_eval.per_candidate[steel_key].metrics["installed_cost_usd"] != pytest.approx(
            without.per_candidate[steel_key].metrics["installed_cost_usd"]
        )
    finally:
        QUANTITY_KINDS.pop("co2e", None)


# -- "inside the noise" -------------------------------------------------------------------


def test_close_comparison_is_reported_inside_the_noise() -> None:
    band = 4.0  # the basis's committed uncertainty percentage
    assert "inside the noise" in uncertainty_note([100_000.0, 103_000.0], band)  # +3%
    outside = uncertainty_note([100_000.0, 112_000.0], band)  # +12%
    assert "outside" in outside and "inside the noise" not in outside
    assert uncertainty_note([100_000.0], band) == ""  # nothing to compare
