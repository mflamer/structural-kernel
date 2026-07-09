"""The ingestion seam, increment A: inferred provenance, ratification, and the
inertness that keeps a machine reading from masquerading as authored intent
(design doc 0005 §5, ADR 0013; PO note 0004).

The backbone acceptance signal: a constraint proposed from a drawing commits as
``inferred`` and is **inert by type** — it cannot reject a changeset or make an
exploration candidate infeasible — until an engineer ratifies it, after which it
enforces exactly as an authored one. Ratification is a recorded who/when/modified
event; the audit trail keeps "the AI read it, the engineer agreed" distinct from
"the engineer authored it".

Increment A constructs inferred constraints directly (the canned proposal an
ingestion reader will later emit); capture wiring is increment C. Fixtures mirror
the ADR 0011 west-band grid but keep their own copies — the only new variable is
the provenance.
"""

from __future__ import annotations

from pathlib import Path

from conftest import AUTHOR, T0, decision, ft, inches, psf
from reference_solver import ReferenceEngine
from structural_kernel.decisions import (
    AreaLoad,
    GravityFramingStrategyParams,
    GridLine,
    GridParams,
    GridRegion,
    Level,
    LevelsParams,
    LoadAssumptionsParams,
)
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
from structural_kernel.objects import (
    AddConstraint,
    AddDecision,
    Changeset,
    ChangesetOp,
    Decision,
    InferredConstraintProvenance,
    ProjectConstraint,
    RatifyConstraint,
)
from structural_kernel.store import FileStore
from structural_kernel.validation import ValidationReport

# The west-band grid: an interior x-line (1.5) inside the west band lets a framing
# region honestly place a column line at gridline 1.5 — the vision's "a column at
# gridline C.5 west of line 4". A low 8 ft roof keeps the 4x4 post within the NDS
# slenderness limit so an inert candidate that reaches the solver resolves cleanly.
WX = "L000000W0"  # x = 0 ft   ("1", west edge)
MX = "L000000M0"  # x = 20 ft  ("1.5", interior)
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
    return LevelsParams(levels=[Level(level_id="LV1", name="Roof", elevation=ft(8.0))])


def _loads() -> LoadAssumptionsParams:
    return LoadAssumptionsParams(
        area_loads=[
            AreaLoad(case="D", magnitude=psf(15.0)),
            AreaLoad(case="L", magnitude=psf(40.0)),
        ],
        combo_set="ASCE7-22-2.4-ASD",
    )


def _framing(x_from: str, x_to: str) -> GravityFramingStrategyParams:
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


def _inferred_clear_span(
    anchor: str,
    extent_ft: float,
    side: str,
    statement: str,
    *,
    cid: str | None = None,
    confidence: str = "high",
) -> ProjectConstraint:
    """An unratified inferred clear-span reading — what the ingestion AI proposes
    off a drawing, before any engineer has confirmed it."""
    return ProjectConstraint.model_validate(
        {
            "cid": cid or new_ulid(),
            "predicate": "no_vertical_support_within",
            "region": {
                "kind": "offset_band",
                "anchor": anchor,
                "extent": {"mag": extent_ft, "unit": "ft"},
                "side": side,
            },
            "payload": {},
            "statement": statement,
            "provenance": {
                "source": "inferred",
                "captured_by": "fake-vision-1",
                "basis": {
                    "region_ref": "A-101 / grid 1 west zone",
                    "reason": "the west ~40 ft reads as a column-free assembly bay",
                },
                "confidence": confidence,
            },
        }
    )


def _base_with_inferred_clear_span(store: FileStore) -> tuple[str, dict[str, Decision], str]:
    """Grid/levels/loads + an inferred, unratified west-40 clear-span constraint."""
    base, dids = _base_bay(store)
    constraint = _inferred_clear_span(WX, 40.0, "greater", "west 40 ft reads as column-free")
    tip = _commit(store, [AddConstraint(constraint=constraint)], base)
    return tip, dids, constraint.cid


# -- the provenance model ------------------------------------------------------------


def test_inferred_provenance_is_binding_only_when_ratified() -> None:
    constraint = _inferred_clear_span(WX, 40.0, "greater", "west 40 ft column-free")
    prov = constraint.provenance
    assert isinstance(prov, InferredConstraintProvenance)
    assert prov.is_binding is False  # inert by type until ratified
    ratified = prov.model_copy(
        update={"ratified": {"ratified_by": "eng:mark", "ratified_at": T0, "modified": False}}
    )
    assert ratified.is_binding is True


# -- the backbone: inert before ratify, binding after --------------------------------


def test_a_post_in_an_inferred_region_commits_with_an_unratified_warning(tmp_path: Path) -> None:
    """A support inside an inferred, unratified clear-span region is NOT rejected —
    the reading is inert by type. The commit carries a ``constraint_unratified``
    warning naming the constraint, so it is visible but non-binding."""
    store = FileStore(tmp_path)
    tip, dids, cid = _base_with_inferred_clear_span(store)
    # WX..MX puts a post at gridline 1.5, interior to the west band.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], tip)
    assert result.outcome == "committed", result.issues
    assert not any(i.code == "constraint_violation" for i in result.issues)
    unratified = [i for i in result.issues if i.code == "constraint_unratified"]
    assert len(unratified) == 1
    assert unratified[0].severity == "warning"
    assert unratified[0].detail["cid"] == cid
    assert unratified[0].detail["inert_reason"] == "unratified"


def test_after_ratification_the_same_post_is_rejected(tmp_path: Path) -> None:
    """The acceptance test: the protected region does nothing before ratify and
    rejects after. Ratified on its own branch (no violating framing yet), the
    inferred constraint then enforces exactly as an authored one."""
    store = FileStore(tmp_path)
    tip, dids, cid = _base_with_inferred_clear_span(store)
    ratified_tip = _commit(
        store, [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0)], tip
    )
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], ratified_tip)
    assert result.outcome == "rejected"
    [issue] = [i for i in result.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    assert issue.detail["cid"] == cid
    assert issue.detail["predicate"] == "no_vertical_support_within"


# -- the ratification audit trail ----------------------------------------------------


def test_ratification_records_who_when_and_unmodified(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, _dids, cid = _base_with_inferred_clear_span(store)
    ratified_tip = _commit(
        store, [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0)], tip
    )
    constraint = load_snapshot(store, ratified_tip).constraints[cid]
    prov = constraint.provenance
    # Source stays inferred — the record keeps "AI read it, engineer agreed".
    assert isinstance(prov, InferredConstraintProvenance)
    assert prov.ratified is not None
    assert prov.ratified.ratified_by == "eng:mark"
    assert prov.ratified.ratified_at == T0
    assert prov.ratified.modified is False
    # The read is preserved through ratification.
    assert prov.basis.reason.startswith("the west")
    assert prov.confidence == "high"
    assert prov.is_binding is True


def test_ratification_with_an_edit_records_modified_and_preserves_the_read(tmp_path: Path) -> None:
    """The engineer corrects the reading on ratify (narrows the band to 20 ft). The
    edit takes effect, ``modified`` is recorded True, and the original inferred
    basis — what the AI actually read — is preserved for the audit trail."""
    store = FileStore(tmp_path)
    tip, dids, cid = _base_with_inferred_clear_span(store)
    edited = _clear_span(WX, 20.0, "greater", "west 20 ft column-free (corrected)")
    edited = edited.model_copy(update={"cid": cid})  # ratify targets the same constraint
    ratified_tip = _commit(
        store,
        [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0, edited=edited)],
        tip,
    )
    constraint = load_snapshot(store, ratified_tip).constraints[cid]
    prov = constraint.provenance
    assert isinstance(prov, InferredConstraintProvenance)
    assert prov.ratified is not None
    assert prov.ratified.modified is True
    assert prov.basis.reason.startswith("the west")  # the original read survives the edit
    assert constraint.statement == "west 20 ft column-free (corrected)"
    # The correction is in force: a post at gridline 1.5 (x=20 ft) is on the far
    # boundary of the narrowed open band, so it is allowed.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], ratified_tip)
    assert result.outcome == "committed", result.issues


# -- ratification guards -------------------------------------------------------------


def test_ratifying_an_authored_constraint_is_rejected(tmp_path: Path) -> None:
    """Only inferred, unratified constraints can be ratified — an authored one has
    nothing to ratify."""
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    authored = _clear_span(WX, 40.0, "greater", "west 40 ft column-free")
    tip = _commit(store, [AddConstraint(constraint=authored)], base)
    result = _try(
        store, [RatifyConstraint(cid=authored.cid, ratified_by="eng:mark", ratified_at=T0)], tip
    )
    assert result.outcome == "rejected"
    assert any(i.code == "constraint_not_ratifiable" for i in result.issues)


def test_ratifying_twice_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, _dids, cid = _base_with_inferred_clear_span(store)
    once = _commit(store, [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0)], tip)
    result = _try(store, [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0)], once)
    assert result.outcome == "rejected"
    assert any(i.code == "constraint_not_ratifiable" for i in result.issues)


def test_ratifying_an_unknown_constraint_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    result = _try(
        store, [RatifyConstraint(cid=new_ulid(), ratified_by="eng:mark", ratified_at=T0)], base
    )
    assert result.outcome == "rejected"
    assert any(i.code == "unknown_constraint" for i in result.issues)


# -- the exploration binding skips an unratified reading -----------------------------


def test_an_exploration_candidate_in_an_unratified_region_is_not_infeasible(
    tmp_path: Path,
) -> None:
    """The mirror of the ADR 0011 pre-solve-death test: with an *unratified*
    inferred constraint, a candidate placing a support in the region is NOT killed
    pre-solve — it reaches the solver. The exploration binding reads ``is_binding``
    through the same stage 5, so one inertness rule covers both sites."""
    store = FileStore(tmp_path)
    tip, dids, _cid = _base_with_inferred_clear_span(store)
    proposer = SystemChoiceProposer(
        [
            Proposal(
                ops=[AddDecision(decision=_framing_decision(dids, WX, MX))],
                rationale="wood scheme with a column line at gridline 1.5 (unratified zone)",
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
    assert candidate.result is not None  # solved, not rejected pre-solve
    report = store.get_model(candidate.report, ValidationReport)
    assert not any(i.code == "constraint_violation" for i in report.issues)


def test_a_compliant_framing_commits_under_an_inferred_reading(tmp_path: Path) -> None:
    """Sanity: the inert reading does not spuriously reject a clean framing either —
    WX..EX spans the full 40 ft with no interior support and commits."""
    store = FileStore(tmp_path)
    tip, dids, _cid = _base_with_inferred_clear_span(store)
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, EX))], tip)
    assert result.outcome == "committed", result.issues
