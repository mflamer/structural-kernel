"""Spatial structural constraints: capture, enforcement, exploration binding, and
the extensibility proof (ADR 0011, PO note 0002).

The primitive is proven by two registered predicate instances
(``no_vertical_support_within`` = clear-span, ``min_bay_spacing`` = min-bay) and,
as the real generalization test, a third predicate nobody planned for
(``clear_height_below``) that registers and enforces with *no kernel change*.
"""

from __future__ import annotations

from pathlib import Path

from conftest import AUTHOR, T0, decision, ft, inches, psf
from reference_solver import ReferenceEngine
from structural_kernel.capture import ConstraintCapture
from structural_kernel.constraints import (
    PREDICATES,
    ConstraintViolation,
    PredicateRegistration,
    ResolvedRegion,
    check_project_constraints,
    register_predicate,
)
from structural_kernel.decisions import (
    AreaLoad,
    GravityFramingStrategyParams,
    GridLine,
    GridParams,
    GridRegion,
    LateralStrategyParams,
    Level,
    LevelsParams,
    LoadAssumptionsParams,
)
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.explorations import (
    Convergence,
    ExplorationBudget,
    Objective,
    Proposal,
    SpatialConstraintsPreservedConstraint,
    SystemChoiceProposer,
    run_exploration,
)
from structural_kernel.ids import new_ulid
from structural_kernel.kernel import ProposeResult, load_snapshot, propose
from structural_kernel.llm import FakeLLMClient, ToolInvocation
from structural_kernel.objects import (
    AddConstraint,
    AddDecision,
    Changeset,
    ChangesetOp,
    Decision,
    KernelModel,
    ModifyDecision,
    ProjectConstraint,
)
from structural_kernel.store import FileStore
from structural_kernel.units import LengthQuantity
from structural_kernel.validation import ResolvedSnapshot, ValidationReport, resolved_snapshot_hash

# A wide bay whose grid carries an interior x-line (1.5) inside the west band, so
# a framing region can honestly place a column line at gridline 1.5 — the vision's
# "a column at gridline C.5 west of line 4."
WX = "L000000W0"  # x = 0 ft   (west edge, "1")
MX = "L000000M0"  # x = 20 ft  (interior, "1.5")
EX = "L000000E0"  # x = 40 ft  ("2")
SY = "L000000S0"  # y = 0 ft   ("A")
NY = "L000000N0"  # y = 30 ft  ("B")


def _grid() -> GridParams:
    return GridParams(
        lines=[
            GridLine(line_id=WX, name="1", axis="x", offset=ft(0.0)),
            GridLine(line_id=MX, name="1.5", axis="x", offset=ft(20.0)),
            GridLine(line_id=EX, name="2", axis="x", offset=ft(40.0)),
            GridLine(line_id=SY, name="A", axis="y", offset=ft(0.0)),
            GridLine(line_id=NY, name="B", axis="y", offset=ft(30.0)),
        ]
    )


def _levels() -> LevelsParams:
    # Nonzero elevation so the framing derives columns (they carry to grade).
    return LevelsParams(levels=[Level(level_id="LV1", name="Roof", elevation=ft(16.0))])


def _loads() -> LoadAssumptionsParams:
    return LoadAssumptionsParams(
        area_loads=[
            AreaLoad(case="D", magnitude=psf(15.0)),
            AreaLoad(case="L", magnitude=psf(40.0)),
        ],
        combo_set="ASCE7-22-2.4-ASD",
    )


def _framing(x_from: str, x_to: str) -> GravityFramingStrategyParams:
    """Wood framing over the x_from..x_to bay; columns land at the region corners,
    so region WX..MX puts a column line at gridline 1.5 (interior to the west band),
    while WX..EX spans the full 40 ft with columns only on the boundary lines."""
    return GravityFramingStrategyParams(
        region=GridRegion(x_from=x_from, x_to=x_to, y_from=SY, y_to=NY),
        system="joists_on_beams_on_posts",
        joist_axis="y",
        joist_spacing=inches(16.0),
        member_family="sawn_lumber",
        member_grade="DF-L No.2",
        joist_section="2x10",
        beam_section="4x12",
        post_section="4x4",
    )


def _clear_span(anchor: str, extent_ft: float, side: str, statement: str) -> ProjectConstraint:
    return ProjectConstraint.model_validate(
        {
            "cid": new_ulid(),
            "predicate": "no_vertical_support_within",
            "region": {
                "kind": "offset_band",
                "anchor": anchor,
                "extent": {"mag": extent_ft, "unit": "ft"},
                "side": side,
            },
            "payload": {},
            "statement": statement,
            "provenance": {"source": "authored", "captured_by": "human"},
        }
    )


def _commit(store: FileStore, ops: list[ChangesetOp], base: str | None) -> str:
    result = propose(
        store, Changeset(base_commit=base, ops=ops), author=AUTHOR, message="t", timestamp=T0
    )
    assert result.outcome == "committed", result.issues
    assert result.commit is not None
    return result.commit


def _try(store: FileStore, ops: list[ChangesetOp], base: str | None) -> ProposeResult:
    return propose(
        store, Changeset(base_commit=base, ops=ops), author=AUTHOR, message="t", timestamp=T0
    )


def _base_bay(store: FileStore) -> tuple[str, dict[str, Decision]]:
    """Grid, levels, loads committed — no structural system yet."""
    grid = decision("grid", "Grid", _grid())
    levels = decision("levels", "Levels", _levels())
    loads = decision("load_assumptions", "Loads", _loads())
    tip = _commit(store, [AddDecision(decision=d) for d in (grid, levels, loads)], None)
    return tip, {"grid": grid, "levels": levels, "loads": loads}


def _framing_decision(dids: dict[str, Decision], x_from: str, x_to: str) -> Decision:
    return decision(
        "gravity_framing_strategy",
        f"Framing {x_from[-2:]}..{x_to[-2:]}",
        _framing(x_from, x_to),
        deps=[dids["grid"].did, dids["levels"].did, dids["loads"].did],
    )


# -- capture -------------------------------------------------------------------------


def _clear_span_client() -> FakeLLMClient:
    return FakeLLMClient(
        [
            ToolInvocation(
                name="capture_clear_span",
                input={
                    "statement": "The west 40 feet must be column-free.",
                    "anchor_line": WX,
                    "extent_ft": 40.0,
                    "side": "greater",
                },
            )
        ]
    )


def test_capture_commits_an_authored_clear_span_constraint(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    ops = ConstraintCapture(_clear_span_client()).capture(
        utterance="the west 40 feet needs to be column-free", snapshot=load_snapshot(store, base)
    )
    assert len(ops) == 1
    tip = _commit(store, ops, base)

    snapshot = load_snapshot(store, tip)
    assert len(snapshot.constraints) == 1
    [constraint] = list(snapshot.constraints.values())
    assert constraint.predicate == "no_vertical_support_within"
    assert constraint.provenance.source == "authored"
    assert constraint.provenance.captured_by == "fake-llm"  # the model identity is recorded
    assert "column-free" in constraint.statement


def test_capture_with_no_tool_calls_captures_nothing(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    ops = ConstraintCapture(FakeLLMClient([])).capture(
        utterance="looks good, no constraints", snapshot=load_snapshot(store, base)
    )
    assert ops == []


def test_a_malformed_capture_is_a_recorded_rejection(tmp_path: Path) -> None:
    """A min-bay capture missing its spacing builds an op, but the ordinary
    pipeline rejects it at the schema stage — never a silent write."""
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    client = FakeLLMClient(
        [ToolInvocation(name="capture_min_bay", input={"statement": "no tight bays"})]
    )
    ops = ConstraintCapture(client).capture(
        utterance="don't crowd the columns", snapshot=load_snapshot(store, base)
    )
    result = _try(store, ops, base)
    assert result.outcome == "rejected"
    assert any(i.code == "schema_invalid" for i in result.issues)


# -- clear-span enforcement, captured while the system is open -----------------------


def _commit_base_with_clear_span(store: FileStore) -> tuple[str, dict[str, Decision]]:
    base, dids = _base_bay(store)
    ops = ConstraintCapture(_clear_span_client()).capture(
        utterance="the west 40 feet needs to be column-free", snapshot=load_snapshot(store, base)
    )
    return _commit(store, ops, base), dids


def test_clear_span_holds_while_the_structural_system_is_unresolved(tmp_path: Path) -> None:
    """Standing requirement: a decision may be held explicitly open in a committed
    model. The constraint is captured against an *open* structural-system decision
    and binds whichever system is later chosen."""
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", _grid())
    levels = decision("levels", "Levels", _levels())
    loads = decision("load_assumptions", "Loads", _loads())
    open_system = Decision.model_validate(
        {
            "did": new_ulid(),
            "kind": "gravity_framing_strategy",
            "title": "Structural system: unresolved",
            "state": "open",
        }
    )
    base = _commit(
        store, [AddDecision(decision=d) for d in (grid, levels, loads, open_system)], None
    )
    tip = _commit(
        store,
        [AddConstraint(constraint=_clear_span(WX, 40.0, "greater", "west 40 ft column-free"))],
        base,
    )

    snapshot = load_snapshot(store, tip)
    assert snapshot.decisions[open_system.did].state == "open"  # still unresolved
    assert len(snapshot.constraints) == 1

    # Resolve the open system to a scheme that puts a column line inside the west
    # band — the constraint rejects it, citing the decision.
    resolved = open_system.model_copy(
        update={
            "state": "resolved",
            "params": _framing(WX, MX).model_dump(mode="json"),
            "deps": [grid.did, levels.did, loads.did],
        }
    )
    result = _try(store, [ModifyDecision(decision=resolved)], tip)
    assert result.outcome == "rejected"
    [issue] = [i for i in result.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    assert issue.detail["predicate"] == "no_vertical_support_within"


def test_a_column_inside_the_protected_region_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, dids = _commit_base_with_clear_span(store)
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], tip)
    assert result.outcome == "rejected"
    [issue] = [i for i in result.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    supports = issue.detail["supports"]
    assert isinstance(supports, list) and supports
    assert any(str(eid).startswith("pst:") for eid in supports)


def test_a_compliant_framing_commits(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, dids = _commit_base_with_clear_span(store)
    # WX..EX spans the full 40 ft with columns only on the boundary lines — a real
    # 40 ft clear span, no interior support.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, EX))], tip)
    assert result.outcome == "committed", result.issues


# -- min-bay enforcement -------------------------------------------------------------


def _commit_base_with_min_bay(store: FileStore) -> tuple[str, dict[str, Decision]]:
    base, dids = _base_bay(store)
    client = FakeLLMClient(
        [
            ToolInvocation(
                name="capture_min_bay",
                input={"statement": "No bays tighter than 25 ft.", "min_spacing_ft": 25.0},
            )
        ]
    )
    ops = ConstraintCapture(client).capture(
        utterance="let's not go tighter than 25 foot bays", snapshot=load_snapshot(store, base)
    )
    return _commit(store, ops, base), dids


def test_a_bay_tighter_than_the_minimum_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, dids = _commit_base_with_min_bay(store)
    # WX..MX is a 20 ft bay — under the 25 ft minimum.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], tip)
    assert result.outcome == "rejected"
    [issue] = [i for i in result.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    assert issue.detail["predicate"] == "min_bay_spacing"
    assert issue.detail["axis"] == "x"


def test_bays_at_or_above_the_minimum_commit(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, dids = _commit_base_with_min_bay(store)
    # WX..EX is 40 ft in x, 30 ft in y — both above the 25 ft minimum.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, EX))], tip)
    assert result.outcome == "committed", result.issues


def test_min_bay_counts_a_bearing_wall_as_a_bay_line(tmp_path: Path) -> None:
    """A bearing wall defines a bay line just like a column (Mark's call). Corner
    columns 40 ft apart pass the minimum; a shear wall on the interior y=20 ft line
    then splits that into two 20 ft bays — under the 25 ft minimum."""
    my = "L000000Y0"  # interior y-line at 20 ft
    b40 = "L000000B4"  # y = 40 ft
    grid = decision(
        "grid",
        "Grid",
        GridParams(
            lines=[
                GridLine(line_id=WX, name="1", axis="x", offset=ft(0.0)),
                GridLine(line_id=EX, name="2", axis="x", offset=ft(40.0)),
                GridLine(line_id=SY, name="A", axis="y", offset=ft(0.0)),
                GridLine(line_id=my, name="A.5", axis="y", offset=ft(20.0)),
                GridLine(line_id=b40, name="B", axis="y", offset=ft(40.0)),
            ]
        ),
    )
    levels = decision("levels", "Levels", _levels())
    loads = decision("load_assumptions", "Loads", _loads())
    framing = decision(
        "gravity_framing_strategy",
        "Framing",
        GravityFramingStrategyParams(
            region=GridRegion(x_from=WX, x_to=EX, y_from=SY, y_to=b40),
            system="joists_on_beams_on_posts",
            joist_axis="y",
            joist_spacing=inches(16.0),
            member_family="sawn_lumber",
            member_grade="DF-L No.2",
            joist_section="2x10",
            beam_section="4x12",
            post_section="4x4",
        ),
        deps=[grid.did, levels.did, loads.did],
    )
    min_bay = ProjectConstraint.model_validate(
        {
            "cid": new_ulid(),
            "predicate": "min_bay_spacing",
            "region": {"kind": "whole_plan"},
            "payload": {"min_spacing": {"mag": 25.0, "unit": "ft"}},
            "statement": "No bays tighter than 25 ft.",
            "provenance": {"source": "authored", "captured_by": "human"},
        }
    )
    store = FileStore(tmp_path)
    # Columns alone sit at y 0 and 40 ft — 40 ft bays, above the minimum: this commits.
    tip = _commit(
        store,
        [
            AddDecision(decision=grid),
            AddDecision(decision=levels),
            AddDecision(decision=loads),
            AddDecision(decision=framing),
            AddConstraint(constraint=min_bay),
        ],
        None,
    )
    # A shear wall on the interior y=20 ft line adds a bay line — two 20 ft bays.
    wall = decision(
        "lateral_strategy", "Shear wall", LateralStrategyParams(wall_lines=[my]), deps=[grid.did]
    )
    result = _try(store, [AddDecision(decision=wall)], tip)
    assert result.outcome == "rejected"
    errors = [i for i in result.issues if i.severity == "error"]
    # The wall splits the 40 ft span into two 20 ft bays — both under the minimum.
    assert errors
    assert all(
        i.code == "constraint_violation"
        and i.detail["predicate"] == "min_bay_spacing"
        and i.detail["axis"] == "y"
        for i in errors
    )


# -- inert constraint (unresolved anchor) --------------------------------------------


def test_an_unknown_predicate_is_rejected_at_the_schema_stage(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    bad = ProjectConstraint.model_validate(
        {
            "cid": new_ulid(),
            "predicate": "not_a_registered_predicate",
            "region": {"kind": "whole_plan"},
            "payload": {},
            "statement": "nonsense",
            "provenance": {"source": "authored", "captured_by": "human"},
        }
    )
    result = _try(store, [AddConstraint(constraint=bad)], base)
    assert result.outcome == "rejected"
    assert any(i.code == "unknown_predicate" for i in result.issues)


# -- exploration binding -------------------------------------------------------------


def test_an_exploration_candidate_in_the_protected_region_dies_pre_solve(tmp_path: Path) -> None:
    """The vision's "41 rejected pre-solve, most put a column line in the protected
    zone": a candidate placing a support in a clear-span region is rejected by the
    ordinary pipeline and never solved — no exploration-side enforcement needed."""
    store = FileStore(tmp_path)
    tip, dids = _commit_base_with_clear_span(store)
    proposer = SystemChoiceProposer(
        [
            Proposal(
                ops=[AddDecision(decision=_framing_decision(dids, WX, MX))],
                rationale="wood scheme with a column line at gridline 1.5, inside the west zone",
            )
        ]
    )
    exploration = run_exploration(
        store,
        base_commit=tip,
        objectives=[Objective(metric="total_member_mass_kg", direction="min")],
        constraints=[SpatialConstraintsPreservedConstraint()],
        proposer=proposer,
        budget=ExplorationBudget(max_solves=10, max_generations=2),
        convergence=Convergence(),
        engine=ReferenceEngine(),
        timestamp=T0,
    )
    [candidate] = exploration.generations[0].candidates
    assert not candidate.committed
    assert candidate.result is None  # never solved
    report = store.get_model(candidate.report, ValidationReport)
    assert any(i.code == "constraint_violation" for i in report.issues)


# -- the extensibility proof: a third predicate, no kernel change --------------------


class _ClearHeightPayload(KernelModel):
    max_height: LengthQuantity


def _clear_height_below(
    model: DerivedModel,
    constraint: ProjectConstraint,
    region: ResolvedRegion,
    snapshot: ResolvedSnapshot,
) -> list[ConstraintViolation]:
    payload = _ClearHeightPayload.model_validate(constraint.payload)
    limit = payload.max_height.si_mag
    tall = sorted(
        e.eid
        for e in model.elements
        if region.contains_point_closed(e.start.x.si_mag, e.start.y.si_mag)
        and max(e.start.z.si_mag, e.end.z.si_mag) > limit + 1e-6
    )
    if not tall:
        return []
    return [
        ConstraintViolation(
            cid=constraint.cid,
            predicate=constraint.predicate,
            message=f"elements rise above {limit:g} m: {', '.join(tall)}",
            detail={"elements": list(tall)},
        )
    ]


def test_a_new_predicate_kind_registers_and_enforces_with_no_kernel_change(
    tmp_path: Path,
) -> None:
    """The acceptance signal the note calls the real proof: a predicate nobody
    planned for drops in as data — one register_predicate call, its own payload
    schema and checker — and is enforced by the ordinary pipeline unchanged."""
    register_predicate(
        PredicateRegistration(
            name="clear_height_below",
            payload_model=_ClearHeightPayload,
            check_site="commit",
            checker=_clear_height_below,
        )
    )
    try:
        store = FileStore(tmp_path)
        base, dids = _base_bay(store)
        constraint = ProjectConstraint.model_validate(
            {
                "cid": new_ulid(),
                "predicate": "clear_height_below",
                "region": {"kind": "whole_plan"},
                "payload": {"max_height": {"mag": 1.0, "unit": "ft"}},
                "statement": "keep the plan clear below 1 ft (fixture)",
                "provenance": {"source": "authored", "captured_by": "human"},
            }
        )
        tip = _commit(store, [AddConstraint(constraint=constraint)], base)
        # Any framing puts members well above 1 ft, so the new predicate bites.
        result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, EX))], tip)
        assert result.outcome == "rejected"
        assert any(
            i.code == "constraint_violation" and i.detail.get("predicate") == "clear_height_below"
            for i in result.issues
        )
    finally:
        PREDICATES.pop("clear_height_below", None)


# -- purity / determinism ------------------------------------------------------------


def test_the_predicate_checkers_are_pure_and_deterministic() -> None:
    grid = decision("grid", "Grid", _grid())
    levels = decision("levels", "Levels", _levels())
    loads = decision("load_assumptions", "Loads", _loads())
    framing = decision(
        "gravity_framing_strategy",
        "Framing",
        _framing(WX, MX),
        deps=[grid.did, levels.did, loads.did],
    )
    constraint = _clear_span(WX, 40.0, "greater", "west 40 ft column-free")
    snapshot = ResolvedSnapshot(
        decisions={d.did: d for d in (grid, levels, loads, framing)},
        constraints={constraint.cid: constraint},
    )
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    first, _ = check_project_constraints(model, snapshot)
    second, _ = check_project_constraints(model, snapshot)
    assert [v.model_dump() for v in first] == [v.model_dump() for v in second]
    assert first  # the violating framing does violate
