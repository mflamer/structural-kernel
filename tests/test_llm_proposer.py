"""The LLM proposer (ADR 0009): an LLM chooses the structural systems, through
the ordinary pipeline. Driven here by a deterministic FakeLLMClient — the real
Anthropic client sits behind the same protocol and is not exercised in CI.

Proves: a slate of candidates of DIFFERENT kinds (wood vs steel) is proposed,
validated, solved, and ranked together; a malformed proposal becomes a recorded
rejection (never committed, never solved — the AI never edits state directly);
the model's rationale and identity flow into the record; and the prompt actually
describes the bay and both materials.
"""

from pathlib import Path

from conftest import (
    AUTHOR,
    LX1,
    LX2,
    LY_A,
    LY_B,
    T0,
    compact_grid_params,
    decision,
    levels_params,
    loads_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.decisions import GridRegion
from structural_kernel.explorations import (
    Convergence,
    Evaluation,
    Exploration,
    ExplorationBudget,
    IntentPreservedConstraint,
    LLMProposer,
    MetricConstraint,
    Objective,
    run_exploration,
)
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.llm import FakeLLMClient, LLMClient, ScriptedLLMClient, ToolInvocation
from structural_kernel.objects import AddDecision, Changeset
from structural_kernel.queries import best_variant
from structural_kernel.store import FileStore
from structural_kernel.validation import ValidationReport

REGION = GridRegion(x_from=LX1, x_to=LX2, y_from=LY_A, y_to=LY_B)
OBJECTIVES = [Objective(metric="total_member_mass_kg", direction="min")]
CONSTRAINTS = [
    MetricConstraint(metric="max_unity", op="<=", value=1.0),
    IntentPreservedConstraint(),
]

WOOD_CALL = ToolInvocation(
    name="propose_wood_framing",
    input={
        "rationale": "Light 2x10 joists at 16 in span the short way — cheap and quick.",
        "joist_axis": "y",
        "joist_spacing_in": 16,
        "member_grade": "DF-L No.2",
        "joist_section": "2x10",
        "beam_section": "4x12",
        "post_section": "4x4",
    },
)
STEEL_CALL = ToolInvocation(
    name="propose_steel_framing",
    input={
        "rationale": "Wide-flange beams on girders on columns, deck-braced.",
        "beam_axis": "y",
        "beam_spacing_ft": 6,
        "member_grade": "A992",
        "beam_section": "W10x12",
        "girder_section": "W12x16",
        "column_section": "W8x24",
    },
)


def _commit_base(store: FileStore) -> str:
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    result = propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=d) for d in (grid, levels, loads)]),
        author=AUTHOR,
        message="base",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    tip = store.read_ref("main")
    assert tip is not None
    return tip


def _run(store: FileStore, client: LLMClient) -> Exploration:
    return run_exploration(
        store,
        base_commit=_commit_base(store),
        objectives=OBJECTIVES,
        constraints=CONSTRAINTS,
        proposer=LLMProposer(client, region=REGION),
        budget=ExplorationBudget(max_solves=10, max_generations=3),
        engine=ReferenceEngine(),
        timestamp=T0,
    )


def test_llm_slate_of_different_kinds_ranks_together(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    client = FakeLLMClient([WOOD_CALL, STEEL_CALL])
    exploration = _run(store, client)

    assert exploration.proposer.strategy == "llm"
    assert exploration.proposer.params["client"] == "fake-llm"  # the model is on the record

    [generation] = exploration.generations
    assert len(generation.candidates) == 2
    assert all(c.committed and c.result is not None for c in generation.candidates)

    kinds: set[str] = set()
    for candidate in generation.candidates:
        assert candidate.commit is not None
        snapshot = load_snapshot(store, candidate.commit)
        [framing] = [d for d in snapshot.decisions.values() if d.kind.endswith("framing_strategy")]
        kinds.add(framing.kind)
    assert kinds == {"gravity_framing_strategy", "steel_framing_strategy"}  # heterogeneous

    [evaluation] = exploration.evaluations
    assert all(e.feasible for e in evaluation.per_candidate.values())
    masses = {k: e.metrics["total_member_mass_kg"] for k, e in evaluation.per_candidate.items()}
    assert [masses[k] for k in evaluation.ranking] == sorted(masses.values())
    winner = best_variant(exploration)
    assert winner is not None and masses[winner] == min(masses.values())


def test_the_model_rationale_flows_into_the_record(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    exploration = _run(store, FakeLLMClient([WOOD_CALL, STEEL_CALL]))
    [generation] = exploration.generations
    rationales = [c.rationale for c in generation.candidates]
    assert any("2x10 joists" in r for r in rationales)
    assert any("Wide-flange" in r for r in rationales)


def test_a_malformed_proposal_is_a_recorded_rejection_never_solved(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    bad = ToolInvocation(
        name="propose_wood_framing",
        input={**WOOD_CALL.input, "joist_section": "not-a-section"},
    )
    exploration = _run(store, FakeLLMClient([bad, STEEL_CALL]))
    [generation] = exploration.generations
    rejected = [c for c in generation.candidates if not c.committed]
    assert len(rejected) == 1
    assert rejected[0].result is None  # never solved
    report = store.get_model(rejected[0].report, ValidationReport)
    assert report.outcome == "rejected"
    assert report.issues[0].code == "derivation_failure"
    # the good steel candidate still committed and was evaluated
    assert rejected[0].key not in exploration.evaluations[-1].per_candidate


def test_an_unknown_tool_call_is_skipped(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    client = FakeLLMClient([ToolInvocation(name="propose_masonry", input={}), WOOD_CALL])
    exploration = _run(store, client)
    [generation] = exploration.generations
    assert len(generation.candidates) == 1  # the unknown tool produced no candidate


def test_the_prompt_describes_the_bay_and_both_materials(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    client = FakeLLMClient([WOOD_CALL])
    _run(store, client)
    [(system, user, tool_names)] = client.calls
    assert "sawn lumber" in user and "hot-rolled steel" in user
    assert LX1 in user and LX2 in user  # the region's bounding line-ids
    assert "A992" in user and "W-shapes" in user
    assert set(tool_names) == {"propose_wood_framing", "propose_steel_framing"}
    assert "NDS" in system and "AISC" in system


# -- closed-loop refinement (ADR 0010) ---------------------------------------------------

# A trajectory the scripted model walks: a dense-but-feasible wood scheme and an
# undersized (infeasible) one, then a lighter feasible wood scheme plus steel,
# then nothing (satisfied — end the search).
WOOD_HEAVY = ToolInvocation(
    name="propose_wood_framing",
    input={**WOOD_CALL.input, "rationale": "Dense joists to be safe.", "joist_spacing_in": 12},
)
WOOD_UNDERSIZED = ToolInvocation(
    name="propose_wood_framing",
    input={**WOOD_CALL.input, "rationale": "Try a small beam.", "beam_section": "4x4"},
)
WOOD_LIGHT = ToolInvocation(
    name="propose_wood_framing",
    input={
        **WOOD_CALL.input,
        "rationale": "Wider spacing and a lighter beam now that I know 4x12 has margin.",
        "joist_spacing_in": 24,
        "beam_section": "4x10",
    },
)


def _best_feasible_mass(evaluation: Evaluation) -> float:
    per = evaluation.per_candidate
    return min(e.metrics["total_member_mass_kg"] for e in per.values() if e.feasible)


def test_closed_loop_refinement_improves_and_converges(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    client = ScriptedLLMClient([[WOOD_HEAVY, WOOD_UNDERSIZED], [WOOD_LIGHT, STEEL_CALL], []])
    exploration = run_exploration(
        store,
        base_commit=_commit_base(store),
        objectives=OBJECTIVES,
        constraints=CONSTRAINTS,
        proposer=LLMProposer(client, region=REGION, refine=True),
        budget=ExplorationBudget(max_solves=20, max_generations=6),
        convergence=Convergence(no_improvement_generations=5),
        engine=ReferenceEngine(),
        timestamp=T0,
    )
    assert exploration.proposer.params["mode"] == "refine"
    # two rounds proposed candidates; the empty third slate ended the search
    assert len(exploration.generations) == 2
    assert exploration.status == "converged"

    # the loop found a lighter feasible design in the refinement round
    assert _best_feasible_mass(exploration.evaluations[-1]) < _best_feasible_mass(
        exploration.evaluations[0]
    )

    # the refinement round's prompt fed the prior results back to the model
    refine_prompt = client.calls[1][1]
    assert "refinement round" in refine_prompt
    assert "Best feasible design so far" in refine_prompt
    assert "INFEASIBLE" in refine_prompt  # the undersized-beam candidate failed


def test_single_slate_mode_ignores_later_slates(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    client = ScriptedLLMClient([[WOOD_CALL], [STEEL_CALL]])  # refine defaults off in _run
    exploration = _run(store, client)
    assert exploration.proposer.params["mode"] == "slate"
    [generation] = exploration.generations  # only the first slate ran
    assert len(generation.candidates) == 1
    assert len(client.calls) == 1  # the model was consulted exactly once
