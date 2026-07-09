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

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import Field, JsonValue

from structural_kernel.canonical import content_hash
from structural_kernel.decisions import (
    CostBasisParams,
    GravityFramingStrategyParams,
    GridParams,
    GridRegion,
    LevelsParams,
    LoadAssumptionsParams,
    SteelFramingStrategyParams,
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
from structural_kernel.units import Dimension

if TYPE_CHECKING:
    from structural_kernel.derivation import Element
    from structural_kernel.materials import MaterialEngine
    from structural_kernel.store import FileStore
    from structural_kernel.units import Quantity
    from structural_kernel.validation import ResolvedSnapshot

# Cost metrics require a committed cost_basis (ADR 0012); an objective naming one
# without a basis is a configuration error caught before the loop runs.
_COST_METRICS = frozenset({"material_cost_usd", "installation_cost_usd", "installed_cost_usd"})

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


class SpatialConstraintsPreservedConstraint(KernelModel):
    """The vision's clear-span / min-bay protection as an exploration constraint
    (ADR 0011, note 0002). Hard, and enforced *structurally*: the standing project
    constraints live in the base snapshot every candidate branches from, so a
    candidate that puts a support in a protected region — or bays under the
    minimum — is rejected by ``propose``'s stage 5 and never solved. Its presence
    here makes the binding explicit and auditable ("41 rejected pre-solve, most
    put a column line in the protected zone"); enforcement needs no code beyond
    the ordinary pipeline, exactly as ``IntentPreservedConstraint``."""

    kind: Literal["spatial_constraints_preserved"] = "spatial_constraints_preserved"


Constraint = Annotated[
    MetricConstraint | IntentPreservedConstraint | SpatialConstraintsPreservedConstraint,
    Field(discriminator="kind"),
]


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
    # Lead-time and basis annotations that ride alongside the ranking but never
    # price into it (ADR 0012) — e.g. "glulam: 14 wk lead time (not priced)".
    flags: list[str] = Field(default_factory=list[str])


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
    edits state directly").

    Two modes. In the default single-slate mode one slate is one generation, then
    it converges. In ``refine`` mode (ADR 0010, closed-loop) it keeps proposing:
    each generation after the first, the prior round's results — which candidates
    were feasible, their mass and governing unity, why the rejected ones were
    rejected, and the best feasible design so far — are fed back into the prompt,
    and the model proposes an improved slate. The loop ends when the model
    proposes nothing, or the kernel's convergence / budget stops it.

    Determinism/replay: the emitted proposals are recorded in the exploration, so
    replay reads the record — it never re-calls the model."""

    def __init__(self, client: LLMClient, *, region: GridRegion, refine: bool = False) -> None:
        self._client = client
        self._region = region
        self._refine = refine

    @property
    def ref(self) -> ProposerRef:
        return ProposerRef(
            strategy="llm",
            params={
                "client": self._client.descriptor,
                "mode": "refine" if self._refine else "slate",
            },
            version=1,
        )

    def propose(self, exploration: Exploration, store: FileStore) -> list[Proposal]:
        if exploration.generations and not self._refine:
            return []  # single-slate mode: one generation, then converge
        snapshot = load_snapshot(store, exploration.base_commit)
        grid = _single_decision(snapshot, "grid")
        levels = _single_decision(snapshot, "levels")
        loads = _single_decision(snapshot, "load_assumptions")
        deps = [grid.did, levels.did, loads.did]
        if exploration.generations:  # refine mode, a later generation: feed results back
            user = _llm_refine_prompt(
                grid, levels, loads, self._region, _feedback_summary(exploration, store)
            )
        else:
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


def _llm_refine_prompt(
    grid: Decision, levels: Decision, loads: Decision, region: GridRegion, feedback: str
) -> str:
    """The refinement-round prompt (ADR 0010): the base bay plus the prior round's
    results and instructions to improve on them."""
    return (
        _llm_user_prompt(grid, levels, loads, region)
        + "\n\nThis is a refinement round.\n"
        + feedback
        + "\nPropose an improved slate: make any INFEASIBLE candidate work by increasing "
        "the size of the governing members (a failing bending or deflection check wants a "
        "deeper section; a failing compression check wants a larger column), and lighten a "
        "FEASIBLE candidate that has unity margin by choosing a smaller section. Keep "
        "spanning wood and steel. If you judge the best feasible design cannot be improved, "
        "propose no candidates to end the search."
    )


def _feedback_summary(exploration: Exploration, store: FileStore) -> str:
    """Summarize the latest generation's candidates (kind, sizes, feasibility, mass,
    governing unity, or rejection reason) plus the best feasible design so far — the
    results the model refines against."""
    from structural_kernel.validation import ValidationReport

    generation = exploration.generations[-1]
    evaluation = exploration.evaluations[-1] if exploration.evaluations else None
    lines: list[str] = []
    for candidate in generation.candidates:
        if candidate.committed and candidate.commit is not None:
            snapshot = load_snapshot(store, candidate.commit)
            framing = next(
                (d for d in snapshot.decisions.values() if d.kind.endswith("framing_strategy")),
                None,
            )
            desc = _describe_framing(framing) if framing is not None else "a framing scheme"
            per = evaluation.per_candidate.get(candidate.key) if evaluation is not None else None
            if per is None:
                lines.append(f"- {desc}: committed but not solved (over budget).")
                continue
            verdict = "FEASIBLE" if per.feasible else "INFEASIBLE"
            mass = per.metrics.get("total_member_mass_kg", 0.0)
            unity = per.metrics.get("max_unity", 0.0)
            lines.append(f"- {desc}: {verdict}, mass {mass:.0f} kg, worst unity {unity:.2f}.")
        else:
            report = store.get_model(candidate.report, ValidationReport)
            reason = report.issues[0].message if report.issues else "rejected in validation"
            lines.append(f"- a rejected proposal ({reason}).")

    best = _best_feasible_mass(exploration)
    header = (
        f"Best feasible design so far: {best:.0f} kg.\n"
        if best is not None
        else "No feasible design yet.\n"
    )
    return header + "Your last round of candidates:\n" + "\n".join(lines)


def _describe_framing(decision: Decision) -> str:
    params = parse_params(decision)
    if isinstance(params, GravityFramingStrategyParams):
        s = params.joist_spacing
        return (
            f"wood ({params.joist_section} joists at {s.mag:g} {s.unit}, {params.beam_section} "
            f"beams, {params.post_section} posts, {params.member_grade})"
        )
    if isinstance(params, SteelFramingStrategyParams):
        s = params.beam_spacing
        return (
            f"steel ({params.beam_section} beams at {s.mag:g} {s.unit}, {params.girder_section} "
            f"girders, {params.column_section} columns, {params.member_grade})"
        )
    return "a framing scheme"


def _best_feasible_mass(exploration: Exploration) -> float | None:
    best: float | None = None
    for evaluation in exploration.evaluations:
        for per in evaluation.per_candidate.values():
            if per.feasible and "total_member_mass_kg" in per.metrics:
                mass = per.metrics["total_member_mass_kg"]
                best = mass if best is None else min(best, mass)
    return best


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
    objectives: Sequence[Objective],
    constraints: Sequence[Constraint],
    proposer: Proposer,
    budget: ExplorationBudget,
    convergence: Convergence | None = None,
    engine: EngineAdapter,
    cost_basis: Decision | None = None,
    timestamp: Timestamp,
) -> Exploration:
    """Run the loop to completion. Callers configure; they do not orchestrate.

    When an objective ranks on cost, pass the committed ``cost_basis`` decision
    (ADR 0012); every generation's evaluation is priced under it. Re-ranking a
    finished exploration under a revised basis is a bare ``evaluate`` call — no
    re-run, no re-solve."""
    if cost_basis is None and any(o.metric in _COST_METRICS for o in objectives):
        raise ValueError(
            "an objective ranks on installed cost but no cost_basis decision was given; "
            "cost assumptions are decisions (ADR 0012) — commit and pass one"
        )
    exploration = Exploration(
        exploration_id=new_ulid(),
        base_commit=base_commit,
        objectives=list(objectives),
        constraints=list(constraints),
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
        evaluation = evaluate(store, exploration, cost_basis)
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
    store: FileStore, exploration: Exploration, cost_basis: Decision | None = None
) -> Evaluation:
    """Evaluate all solved candidates from *stored* results — physics is reused,
    never recomputed (this function has no solver; re-ranking cannot re-solve by
    construction). Passing a committed ``cost_basis`` decision prices every
    candidate under it (material + installation → installed cost) and ranks on
    the requested metric; the same call under a revised basis appends a new
    evaluation over the *same* result set. The basis's own ``did`` is recorded,
    so a ranking always cites what it was priced under."""
    basis = _cost_basis_params(cost_basis)
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
            flags: list[str] = []
            if basis is not None:
                material, installation, cost_notes = _installed_cost(model, basis)
                metrics["material_cost_usd"] = material
                metrics["installation_cost_usd"] = installation
                metrics["installed_cost_usd"] = material + installation
                flags = _lead_time_flags(model, basis)
                for note in cost_notes:
                    if note not in notes:
                        notes.append(note)
            feasible = report.all_pass and _metric_constraints_ok(exploration.constraints, metrics)
            per_candidate[candidate.key] = CandidateEvaluation(
                metrics=metrics, feasible=feasible, flags=flags
            )
            result_refs[candidate.key] = candidate.result

    ranking = _rank(exploration.objectives, per_candidate)
    if cost_basis is not None:
        assert basis is not None
        notes.append(
            f"priced under cost_basis {cost_basis.did} (region {basis.region}, as of {basis.as_of})"
        )
        objective = exploration.objectives[0] if exploration.objectives else None
        if objective is not None and objective.metric in _COST_METRICS:
            ranked_costs = [
                per_candidate[k].metrics[objective.metric]
                for k in ranking
                if per_candidate[k].feasible and objective.metric in per_candidate[k].metrics
            ]
            note = uncertainty_note(ranked_costs, basis.uncertainty_pct)
            if note:
                notes.append(note)

    return Evaluation(
        result_set=content_hash(result_refs),
        cost_basis=cost_basis.did if cost_basis is not None else None,
        per_candidate=per_candidate,
        ranking=ranking,
        notes="; ".join(notes),
    )


def _cost_basis_params(cost_basis: Decision | None) -> CostBasisParams | None:
    if cost_basis is None:
        return None
    if cost_basis.kind != "cost_basis":
        raise ValueError(f"decision {cost_basis.did} is a {cost_basis.kind}, not a cost_basis")
    params = parse_params(cost_basis)
    assert isinstance(params, CostBasisParams)
    return params


def _installed_cost(model: DerivedModel, basis: CostBasisParams) -> tuple[float, float, list[str]]:
    """Layered installed cost in canonical USD (ADR 0012): material from derived
    quantities priced by the family's basis rate, installation from derived
    countables. Returns (material, installation, notes)."""
    rate_by_family = {rate.family: rate.rate for rate in basis.material_rates}
    material = 0.0
    notes: list[str] = []
    for element in model.elements:
        if element.grade is None:
            continue  # non-catalog induced members (wall panels) carry no material price
        rate = rate_by_family.get(element.family)
        if rate is None:
            notes.append(
                f"no material rate for {element.family!r} in the basis; "
                "its members are omitted from material cost"
            )
            continue
        quantity = _priced_quantity(engine_for(element.family), element, rate.dimension)
        if quantity is None:
            notes.append(
                f"cannot price {element.section!r} ({element.family}) by "
                f"{rate.unit}; omitted from material cost"
            )
            continue
        material += rate.si_mag * quantity  # (USD/kg)*kg or (USD/m3)*m3 -> USD

    countables = model.bill.countables
    picks = countables.crane_picks or 0
    erection_hours_s = (
        countables.piece_count * basis.hours_per_piece.si_mag + picks * basis.hours_per_pick.si_mag
    )
    installation = (
        countables.connection_count * basis.connection_cost.si_mag
        + erection_hours_s * basis.crew_rate.si_mag  # (USD/s)*s -> USD
    )
    return material, installation, notes


def _priced_quantity(
    engine: MaterialEngine, element: Element, dimension: Dimension
) -> float | None:
    """The SI quantity a rate of this dimension prices: mass for money-per-mass,
    nominal volume for money-per-volume. The rate's dimension is the switch."""
    if dimension is Dimension.MONEY_PER_MASS:
        assert element.grade is not None
        section = engine.section_properties(element.section)
        density = engine.mass_density_kg_m3(element.grade)
        if section is None or density is None:
            return None
        return section.area_m2 * element.length.si_mag * density
    if dimension is Dimension.MONEY_PER_VOLUME:
        return engine.nominal_volume_m3(element.section, element.length.si_mag)
    return None


def _lead_time_flags(model: DerivedModel, basis: CostBasisParams) -> list[str]:
    """Annotate a candidate with the lead time of any family it uses — never
    priced in, only surfaced (the vision's glulam 14-week flag)."""
    weeks_by_family = {lt.family: lt.lead_time for lt in basis.lead_times}
    used = {e.family for e in model.elements if e.family in weeks_by_family}
    flags: list[str] = []
    for family in sorted(used):
        lead = weeks_by_family[family]
        flags.append(f"{family}: {lead.mag:g} {lead.unit} lead time (annotated, not priced)")
    return flags


def uncertainty_note(ranked_costs: list[float], band_pct: float) -> str:
    """Is the top cost comparison a verdict or a coin flip (ADR 0012)? Given the
    feasible candidates' installed costs in ranked (ascending) order and the
    basis's committed uncertainty band, say whether the two best are "inside the
    noise". A pure function of the ranked costs — a UI renders this line, and it
    is unit-tested directly."""
    if len(ranked_costs) < 2 or ranked_costs[0] <= 0.0:
        return ""
    first, second = ranked_costs[0], ranked_costs[1]
    spread_pct = abs(second - first) / first * 100.0
    if spread_pct <= band_pct:
        return (
            f"top two within {spread_pct:.1f}% on installed cost (band {band_pct:g}%) — "
            "inside the noise, a coin flip on cost"
        )
    return (
        f"best installed cost leads the runner-up by {spread_pct:.1f}% "
        f"(outside the {band_pct:g}% band)"
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
