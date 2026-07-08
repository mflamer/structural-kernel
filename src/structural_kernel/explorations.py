"""Explorations: propose → derive → solve → evaluate as a first-class kernel
object (design doc 0001 §8, as restructured per the PO reply, item 3).

- **Candidates are real branches** through the *ordinary* changeset pipeline —
  same validation, same intent checks. A rejected candidate is recorded with
  its structured errors and never solved. No exploration side-door into state.
- **Candidates carry physics only** (changeset, branch, rationale, artifact,
  solve-result references). **Evaluations are a separate collection** keyed by
  ``(result set, cost_basis)``; re-ranking under a revised basis appends an
  evaluation and never re-solves. Phase 1 evaluates with a null cost basis.
- **The lifecycle is kernel-owned**: this module runs the generation loop —
  propose, validate, derive, batch-dispatch (one ``submit`` for the whole
  generation), evaluate, rank, persist — and every generation persists before
  the next begins, so a killed exploration resumes or replays from its record.
- **The proposer is the pluggable seam**: a sweep today, an LLM tomorrow, same
  protocol. Rationale is mandatory on every candidate from every proposer —
  the engineer-of-record audit requirement makes this non-optional.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import Field, JsonValue

from structural_kernel.canonical import content_hash
from structural_kernel.decisions import (
    GravityFramingStrategyParams,
    GridParams,
    GridRegion,
    LevelsParams,
    LoadAssumptionsParams,
    parse_params,
)
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.design_checks import run_design_checks
from structural_kernel.ids import Did, ObjectHash, new_ulid
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.llm import LLMClient, ToolInvocation, ToolSpec
from structural_kernel.materials import engine_for
from structural_kernel.objects import (
    AddDecision,
    Author,
    Changeset,
    ChangesetOp,
    Commit,
    Decision,
    KernelModel,
    ModifyDecision,
    Timestamp,
)
from structural_kernel.solver import EngineAdapter, LocalSolverService, SolveResult

if TYPE_CHECKING:
    from structural_kernel.store import FileStore
    from structural_kernel.units import Quantity
    from structural_kernel.validation import ResolvedSnapshot

_FALLBACK_DENSITY_KG_M3 = 500.0  # used only when the grade lacks a density; noted


# -- persisted schema -----------------------------------------------------------------


class Objective(KernelModel):
    metric: str
    direction: Literal["min", "max"]


class MetricConstraint(KernelModel):
    kind: Literal["metric"] = "metric"
    metric: str
    op: Literal["<=", ">="]
    value: float


class IntentPreservedConstraint(KernelModel):
    """Hard in phase 1 (review Q9): enforced structurally — every candidate
    passes ordinary validation, so intent-violating candidates die pre-solve."""

    kind: Literal["intent_preserved"] = "intent_preserved"


Constraint = Annotated[MetricConstraint | IntentPreservedConstraint, Field(discriminator="kind")]


class ProposerRef(KernelModel):
    strategy: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    version: int


class ExplorationBudget(KernelModel):
    max_solves: int
    max_generations: int


class Convergence(KernelModel):
    no_improvement_generations: int = 1


class Candidate(KernelModel):
    """Physics only — evaluation lives in the separate keyed collection."""

    key: str  # "g0/c3"
    changeset: ObjectHash
    report: ObjectHash  # validation report; rejections carry their errors here
    branch: str
    rationale: str
    committed: bool
    commit: ObjectHash | None = None
    artifact: ObjectHash | None = None
    result: ObjectHash | None = None  # None: rejected, partial, or over budget


class Generation(KernelModel):
    n: int
    candidates: list[Candidate]


class CandidateEvaluation(KernelModel):
    metrics: dict[str, float]
    feasible: bool


class Evaluation(KernelModel):
    """Keyed by (result set, cost_basis): re-ranking never re-solves."""

    result_set: str  # content address over {candidate key: result hash}
    cost_basis: Did | None = None  # a cost_basis decision, when priced evaluation arrives
    per_candidate: dict[str, CandidateEvaluation]
    ranking: list[str]  # feasible first, objective order
    notes: str = ""


class Exploration(KernelModel):
    schema_version: Literal[1] = 1
    exploration_id: Did
    base_commit: ObjectHash
    objectives: list[Objective]
    constraints: list[Constraint]
    proposer: ProposerRef
    budget: ExplorationBudget
    convergence: Convergence
    status: Literal["running", "converged", "budget_exhausted", "terminated"]
    generations: list[Generation] = Field(default_factory=list[Generation])
    evaluations: list[Evaluation] = Field(default_factory=list[Evaluation])


# -- the proposer seam ------------------------------------------------------------------


class Proposal(KernelModel):
    ops: list[ChangesetOp] = Field(min_length=1)
    rationale: str = Field(min_length=1)  # mandatory, even when mechanical


class Proposer(Protocol):
    """propose(exploration state, store) → candidate proposals. The exploration
    object carries the full generation history; the store gives read access to
    the base snapshot. Returning [] signals convergence."""

    @property
    def ref(self) -> ProposerRef: ...

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]: ...


class GridSweepProposer:
    """The phase-1 sweep: joist spacing crossed with layout variants, one
    generation. Layouts are partial framing-param updates (e.g. a different
    beam section or joist axis)."""

    def __init__(self, spacings: list[Quantity], layouts: list[dict[str, JsonValue]]) -> None:
        self._spacings = spacings
        self._layouts = layouts

    @property
    def ref(self) -> ProposerRef:
        return ProposerRef(
            strategy="grid_sweep",
            params={
                "spacings": [s.model_dump(mode="json") for s in self._spacings],
                "layouts": list(self._layouts),
            },
            version=1,
        )

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]:
        if exploration.generations:
            return []  # the cross product is one generation; then we are done
        framing = _the_framing_decision(exploration, store)
        proposals: list[Proposal] = []
        for spacing in self._spacings:
            for layout in self._layouts:
                params = framing.params
                assert params is not None
                updated = dict(params)
                updated["joist_spacing"] = spacing.model_dump(mode="json")
                updated.update(layout)
                modified = framing.model_copy(update={"params": updated})
                layout_text = ", ".join(f"{k}={v}" for k, v in sorted(layout.items()))
                proposals.append(
                    Proposal(
                        ops=[ModifyDecision(decision=modified)],
                        rationale=(
                            f"grid sweep: joist spacing {spacing.mag:g} {spacing.unit}"
                            + (f" x {layout_text}" if layout_text else "")
                        ),
                    )
                )
        return proposals


class StubLLMProposer:
    """The demonstration that an LLM proposer slots in without kernel changes
    (charter): same protocol, canned proposal, real rationale. The real LLM
    proposer is phase 2."""

    @property
    def ref(self) -> ProposerRef:
        return ProposerRef(strategy="llm_stub", version=1)

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]:
        if exploration.generations:
            return []
        framing = _the_framing_decision(exploration, store)
        params = framing.params
        assert params is not None
        updated = dict(params)
        updated["joist_spacing"] = {"mag": 19.2, "unit": "in"}
        return [
            Proposal(
                ops=[ModifyDecision(decision=framing.model_copy(update={"params": updated}))],
                rationale=(
                    "llm_stub: 19.2 in spacing aligns joists with 8 ft sheathing "
                    "modules while shedding pieces versus 16 in — canned reasoning "
                    "standing in for a model-generated rationale"
                ),
            )
        ]


class SystemChoiceProposer:
    """The vision's *heterogeneous* exploration (standing requirement 1): a
    fixed set of candidate structural systems ranked as one generation, where
    candidates may differ in decision *kind* — a wood ``gravity_framing_strategy``
    against a steel ``steel_framing_strategy`` for the same region, not one
    strategy's parameters.

    The proposer is the only place the kinds are chosen; everything downstream —
    validation, derivation, the batch solve, the mass metric, the ranking —
    treats each candidate as an ordinary branch and assumes nothing about a
    shared strategy. That an LLM proposer will emit exactly this shape (a slate
    of dissimilar systems, each with a rationale) is why the seam stays fixed."""

    def __init__(self, systems: list[Proposal], *, strategy: str = "system_choice") -> None:
        if not systems:
            raise ValueError("a system-choice proposer needs at least one candidate system")
        self._systems = systems
        self._strategy = strategy

    @property
    def ref(self) -> ProposerRef:
        return ProposerRef(strategy=self._strategy, version=1)

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]:
        # The slate is one generation; then the exploration has converged.
        return [] if exploration.generations else list(self._systems)


_LLM_SYSTEM_PROMPT = (
    "You are a licensed structural engineer proposing candidate gravity framing "
    "systems for a single-story bay. Each candidate will be validated, solved, and "
    "checked to its own code — NDS 2024 ASD for wood, AISC 360-22 LRFD for steel — "
    "then ranked by total member mass. Propose a diverse slate (2 to 4 candidates) "
    "spanning BOTH wood and steel, so the ranking is a real system comparison, not a "
    "parameter sweep. Every candidate must be a genuine attempt at a working design; "
    "infeasible candidates are ranked, not hidden, so do not hedge. Call the propose_* "
    "tools, once per candidate, each with a one- or two-sentence rationale."
)

_WOOD_TOOL = ToolSpec(
    name="propose_wood_framing",
    description=(
        "Propose a sawn-lumber gravity framing system: repetitive joists on beams on "
        "posts, designed to NDS 2024 ASD."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rationale": {
                "type": "string",
                "description": "Why this system, in a sentence or two.",
            },
            "joist_axis": {
                "type": "string",
                "enum": ["x", "y"],
                "description": "Axis the joists span.",
            },
            "joist_spacing_in": {
                "type": "number",
                "description": "Joist spacing in inches (e.g. 12, 16, 19.2, 24).",
            },
            "member_grade": {
                "type": "string",
                "description": "Sawn-lumber grade, e.g. 'DF-L No.2'.",
            },
            "joist_section": {"type": "string", "description": "Nominal joist size, e.g. '2x10'."},
            "beam_section": {"type": "string", "description": "Nominal beam size, e.g. '4x12'."},
            "post_section": {"type": "string", "description": "Nominal post size, e.g. '4x4'."},
        },
        "required": [
            "rationale",
            "joist_axis",
            "joist_spacing_in",
            "member_grade",
            "joist_section",
            "beam_section",
            "post_section",
        ],
        "additionalProperties": False,
    },
)

_STEEL_TOOL = ToolSpec(
    name="propose_steel_framing",
    description=(
        "Propose a hot-rolled steel gravity framing system: wide-flange infill beams "
        "on girders on columns, designed to AISC 360-22 LRFD."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rationale": {
                "type": "string",
                "description": "Why this system, in a sentence or two.",
            },
            "beam_axis": {
                "type": "string",
                "enum": ["x", "y"],
                "description": "Axis the infill beams span.",
            },
            "beam_spacing_ft": {
                "type": "number",
                "description": "Infill-beam spacing in feet (e.g. 5, 6, 8).",
            },
            "member_grade": {"type": "string", "description": "Steel grade, e.g. 'A992'."},
            "beam_section": {
                "type": "string",
                "description": "W-shape infill beam, e.g. 'W10x12'.",
            },
            "girder_section": {"type": "string", "description": "W-shape girder, e.g. 'W12x16'."},
            "column_section": {"type": "string", "description": "W-shape column, e.g. 'W8x24'."},
        },
        "required": [
            "rationale",
            "beam_axis",
            "beam_spacing_ft",
            "member_grade",
            "beam_section",
            "girder_section",
            "column_section",
        ],
        "additionalProperties": False,
    },
)


class LLMProposer:
    """An LLM chooses the structural systems (ADR 0009). Given the base geometry
    and loads, it calls the propose_wood / propose_steel tools to emit a slate of
    candidate systems — of different decision kinds — each with a rationale. The
    model only *proposes*; the malformed and the intent-violating are recorded as
    rejections by the ordinary pipeline, never committed (the charter's "AI never
    edits state directly"). One slate is one generation; then it converges.

    Determinism/replay: the emitted proposals are recorded in the exploration, so
    replay reads the record — it never re-calls the model."""

    def __init__(self, client: LLMClient, *, region: GridRegion) -> None:
        self._client = client
        self._region = region

    @property
    def ref(self) -> ProposerRef:
        return ProposerRef(strategy="llm", params={"client": self._client.descriptor}, version=1)

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]:
        if exploration.generations:
            return []
        snapshot = load_snapshot(store, exploration.base_commit)
        grid = _single_decision(snapshot, "grid")
        levels = _single_decision(snapshot, "levels")
        loads = _single_decision(snapshot, "load_assumptions")
        deps = [grid.did, levels.did, loads.did]
        user = _llm_user_prompt(grid, levels, loads, self._region)
        invocations = self._client.invoke_tools(
            system=_LLM_SYSTEM_PROMPT, user=user, tools=[_WOOD_TOOL, _STEEL_TOOL]
        )
        proposals: list[Proposal] = []
        for invocation in invocations:
            proposal = self._to_proposal(invocation, deps, loads)
            if proposal is not None:
                proposals.append(proposal)
        return proposals

    def _to_proposal(
        self, invocation: ToolInvocation, deps: list[str], loads: Decision
    ) -> Proposal | None:
        data = invocation.input
        rationale = str(data.get("rationale") or "").strip()
        if invocation.name == "propose_wood_framing":
            params: dict[str, JsonValue] = {
                "region": self._region.model_dump(mode="json"),
                "system": "joists_on_beams_on_posts",
                "joist_axis": data.get("joist_axis"),
                "joist_spacing": {"mag": data.get("joist_spacing_in"), "unit": "in"},
                "member_family": "sawn_lumber",
                "member_grade": data.get("member_grade"),
                "joist_section": data.get("joist_section"),
                "beam_section": data.get("beam_section"),
                "post_section": data.get("post_section"),
            }
            decision = _framing_decision(
                "gravity_framing_strategy", "LLM: wood framing", params, deps
            )
            ops: list[ChangesetOp] = [AddDecision(decision=decision)]
            rationale = rationale or "wood joists on beams on posts (LLM proposal)"
        elif invocation.name == "propose_steel_framing":
            params = {
                "region": self._region.model_dump(mode="json"),
                "system": "beams_on_girders_on_columns",
                "beam_axis": data.get("beam_axis"),
                "beam_spacing": {"mag": data.get("beam_spacing_ft"), "unit": "ft"},
                "member_family": "hot_rolled_steel",
                "member_grade": data.get("member_grade"),
                "beam_section": data.get("beam_section"),
                "girder_section": data.get("girder_section"),
                "column_section": data.get("column_section"),
            }
            decision = _framing_decision(
                "steel_framing_strategy", "LLM: steel framing", params, deps
            )
            # Steel is LRFD, so the candidate also selects the §2.3 strength combos.
            ops = [AddDecision(decision=decision), ModifyDecision(decision=_to_lrfd_loads(loads))]
            rationale = rationale or "steel WF beams on girders on columns (LLM proposal)"
        else:
            return None  # a tool we do not know how to realize; skip it
        return Proposal(ops=ops, rationale=rationale)


def _single_decision(snapshot: ResolvedSnapshot, kind: str) -> Decision:
    matches = [d for d in snapshot.decisions.values() if d.kind == kind and d.state == "resolved"]
    if len(matches) != 1:
        raise ValueError(
            f"the LLM proposer needs exactly one {kind} decision; found {len(matches)}"
        )
    return matches[0]


def _framing_decision(
    kind: str, title: str, params: dict[str, JsonValue], deps: list[str]
) -> Decision:
    return Decision.model_validate(
        {"did": new_ulid(), "kind": kind, "title": title, "params": params, "deps": list(deps)}
    )


def _to_lrfd_loads(loads: Decision) -> Decision:
    params = dict(loads.params or {})
    params["combo_set"] = "ASCE7-22-2.3-LRFD"
    return loads.model_copy(update={"params": params})


def _llm_user_prompt(grid: Decision, levels: Decision, loads: Decision, region: GridRegion) -> str:
    grid_params = parse_params(grid)
    assert isinstance(grid_params, GridParams)
    lines = "; ".join(
        f"{line.name} (id {line.line_id}, {line.axis}={line.offset.mag:g} {line.offset.unit})"
        for line in grid_params.lines
    )
    level_params = parse_params(levels)
    assert isinstance(level_params, LevelsParams)
    levels_txt = "; ".join(
        f"{lv.name} at {lv.elevation.mag:g} {lv.elevation.unit}" for lv in level_params.levels
    )
    load_params = parse_params(loads)
    assert isinstance(load_params, LoadAssumptionsParams)
    loads_txt = "; ".join(
        f"{a.case}={a.magnitude.mag:g} {a.magnitude.unit}" for a in load_params.area_loads
    )
    region_txt = f"x from {region.x_from} to {region.x_to}, y from {region.y_from} to {region.y_to}"
    return (
        f"Grid lines: {lines}.\n"
        f"Levels: {levels_txt}.\n"
        f"Area loads: {loads_txt}.\n"
        f"Frame the rectangular bay bounded by grid lines {region_txt}.\n"
        "Hard constraint: every member must pass its strength and deflection checks "
        "(unity <= 1.0); candidates that fail are ranked below feasible ones.\n"
        "Available materials: sawn lumber (grades like 'DF-L No.2'; sections like "
        "'2x8', '2x10', '4x12', '4x4') and hot-rolled steel (grade 'A992'; W-shapes "
        "like 'W8x10', 'W10x12', 'W12x16', 'W8x24', 'W18x50').\n"
        "Propose 2 to 4 candidate systems spanning wood and steel."
    )


def _the_framing_decision(exploration: Exploration, store: FileStore) -> Decision:
    snapshot = load_snapshot(store, exploration.base_commit)
    framings = [
        d
        for d in snapshot.decisions.values()
        if d.kind == "gravity_framing_strategy" and d.state == "resolved"
    ]
    if len(framings) != 1:
        raise ValueError(
            f"the phase-1 sweep needs exactly one framing strategy; found {len(framings)}"
        )
    assert isinstance(parse_params(framings[0]), GravityFramingStrategyParams)
    return framings[0]


# -- the kernel-owned lifecycle ----------------------------------------------------------


def run_exploration(
    store: FileStore,
    *,
    base_commit: ObjectHash,
    objectives: list[Objective],
    constraints: list[Constraint],
    proposer: Proposer,
    budget: ExplorationBudget,
    convergence: Convergence | None = None,
    engine: EngineAdapter,
    timestamp: Timestamp,
) -> Exploration:
    """Run the loop to completion. Callers configure; they do not orchestrate."""
    exploration = Exploration(
        exploration_id=new_ulid(),
        base_commit=base_commit,
        objectives=objectives,
        constraints=constraints,
        proposer=proposer.ref,
        budget=budget,
        convergence=convergence or Convergence(),
        status="running",
    )
    service = LocalSolverService(engine)
    author = Author(kind="proposer", id=proposer.ref.strategy)
    solves_used = 0
    best_so_far: float | None = None
    stale_generations = 0

    for n in range(budget.max_generations):
        proposals = proposer.propose(exploration, store)
        if not proposals:
            exploration = exploration.model_copy(update={"status": "converged"})
            break

        candidates: list[Candidate] = []
        to_solve: list[tuple[int, DerivedModel]] = []  # candidate index -> model
        for i, proposal in enumerate(proposals):
            key = f"g{n}/c{i}"
            branch = f"expl/{exploration.exploration_id}/{key}"
            store.compare_and_swap(branch, None, base_commit)  # branching is a ref copy
            result = propose(
                store,
                Changeset(base_commit=base_commit, ops=proposal.ops),
                author=author,
                message=proposal.rationale,
                timestamp=timestamp,
                ref=branch,
            )
            candidate = Candidate(
                key=key,
                changeset=result.changeset,
                report=result.report,
                branch=branch,
                rationale=proposal.rationale,
                committed=result.outcome == "committed",
                commit=result.commit,
            )
            if candidate.committed and solves_used + len(to_solve) < budget.max_solves:
                assert result.commit is not None
                model = _derived(store, result.commit)
                if model.analysis is not None:
                    candidate = candidate.model_copy(
                        update={"artifact": store.put_model(model.analysis)}
                    )
                    to_solve.append((i, model))
            candidates.append(candidate)

        # Batch dispatch: the whole generation is ONE submit (design doc §7.2).
        if to_solve:
            job = service.submit([model.analysis for _, model in to_solve if model.analysis])
            results = service.results(job)
            solves_used += len(results)
            for (index, _), solve_result in zip(to_solve, results, strict=True):
                candidates[index] = candidates[index].model_copy(
                    update={"result": store.put_model(solve_result)}
                )

        generation = Generation(n=n, candidates=candidates)
        exploration = exploration.model_copy(
            update={"generations": [*exploration.generations, generation]}
        )
        evaluation = evaluate(store, exploration)
        exploration = exploration.model_copy(
            update={"evaluations": [*exploration.evaluations, evaluation]}
        )
        _persist(store, exploration)  # every generation persists before the next

        if solves_used >= budget.max_solves:
            exploration = exploration.model_copy(update={"status": "budget_exhausted"})
            break
        best_now = _best_feasible_metric(exploration, evaluation)
        if best_now is not None and (
            best_so_far is None or _improves(exploration, best_now, best_so_far)
        ):
            best_so_far = best_now
            stale_generations = 0
        else:
            stale_generations += 1
            if stale_generations >= exploration.convergence.no_improvement_generations:
                exploration = exploration.model_copy(update={"status": "converged"})
                break
    else:
        exploration = exploration.model_copy(update={"status": "budget_exhausted"})

    if exploration.status == "running":
        exploration = exploration.model_copy(update={"status": "converged"})
    _persist(store, exploration)
    return exploration


def evaluate(
    store: FileStore, exploration: Exploration, cost_basis: Did | None = None
) -> Evaluation:
    """Evaluate all solved candidates from *stored* results — physics is
    reused, never recomputed. Appending an evaluation under a revised basis is
    this same call with a different ``cost_basis``."""
    per_candidate: dict[str, CandidateEvaluation] = {}
    result_refs: dict[str, JsonValue] = {}
    notes: list[str] = []

    for generation in exploration.generations:
        for candidate in generation.candidates:
            if not candidate.committed or candidate.result is None:
                continue
            assert candidate.commit is not None
            solve_result = store.get_model(candidate.result, SolveResult)
            model = _derived(store, candidate.commit)
            report = run_design_checks(model, solve_result)
            mass, mass_note = _total_member_mass_kg(model)
            if mass_note and mass_note not in notes:
                notes.append(mass_note)
            metrics = {"total_member_mass_kg": mass, "max_unity": report.max_unity}
            feasible = report.all_pass and _metric_constraints_ok(exploration.constraints, metrics)
            per_candidate[candidate.key] = CandidateEvaluation(metrics=metrics, feasible=feasible)
            result_refs[candidate.key] = candidate.result

    return Evaluation(
        result_set=content_hash(result_refs),
        cost_basis=cost_basis,
        per_candidate=per_candidate,
        ranking=_rank(exploration.objectives, per_candidate),
        notes="; ".join(notes),
    )


def exploration_ref(exploration_id: str) -> str:
    return f"explorations/{exploration_id}"


# -- internals ----------------------------------------------------------------------------


def _persist(store: FileStore, exploration: Exploration) -> None:
    exploration_hash = store.put_model(exploration)
    ref = exploration_ref(exploration.exploration_id)
    store.compare_and_swap(ref, store.read_ref(ref), exploration_hash)


def _derived(store: FileStore, commit_hash: str) -> DerivedModel:
    commit = store.get_model(commit_hash, Commit)
    return derive(load_snapshot(store, commit_hash), snapshot_hash=commit.snapshot)


def _total_member_mass_kg(model: DerivedModel) -> tuple[float, str]:
    total = 0.0
    note = ""
    for element in model.elements:
        if element.grade is None:
            continue
        engine = engine_for(element.family)
        section = engine.section_properties(element.section)
        if section is None:
            continue
        density = engine.mass_density_kg_m3(element.grade)
        if density is None:
            density = _FALLBACK_DENSITY_KG_M3
            note = (
                f"mass density for {element.family}/{element.grade!r} not tabulated; "
                f"mass uses {_FALLBACK_DENSITY_KG_M3:g} kg/m³"
            )
        total += section.area_m2 * element.length.si_mag * density
    return total, note


def _metric_constraints_ok(constraints: list[Constraint], metrics: dict[str, float]) -> bool:
    for constraint in constraints:
        if isinstance(constraint, MetricConstraint):
            value = metrics.get(constraint.metric)
            if value is None:
                return False
            if constraint.op == "<=" and not value <= constraint.value:
                return False
            if constraint.op == ">=" and not value >= constraint.value:
                return False
    return True


def _rank(objectives: list[Objective], per_candidate: dict[str, CandidateEvaluation]) -> list[str]:
    if not objectives:
        return sorted(per_candidate)
    objective = objectives[0]  # single objective in phase 1
    sign = 1.0 if objective.direction == "min" else -1.0

    def metric(key: str) -> float:
        return sign * per_candidate[key].metrics.get(objective.metric, float("inf"))

    feasible = sorted((k for k, e in per_candidate.items() if e.feasible), key=metric)
    infeasible = sorted((k for k, e in per_candidate.items() if not e.feasible), key=metric)
    return [*feasible, *infeasible]


def _best_feasible_metric(exploration: Exploration, evaluation: Evaluation) -> float | None:
    if not exploration.objectives:
        return None
    metric = exploration.objectives[0].metric
    values = [
        e.metrics[metric]
        for e in evaluation.per_candidate.values()
        if e.feasible and metric in e.metrics
    ]
    if not values:
        return None
    return min(values) if exploration.objectives[0].direction == "min" else max(values)


def _improves(exploration: Exploration, now: float, before: float) -> bool:
    if exploration.objectives and exploration.objectives[0].direction == "max":
        return now > before
    return now < before
