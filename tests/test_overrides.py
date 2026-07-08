"""Reality overrides: the §5 composition rule and ADR 0005 re-attachment states."""

from pathlib import Path

from conftest import (
    AUTHOR,
    LX1,
    LX2,
    LY_A,
    LY_B,
    T0,
    decision,
    framing_params,
    ft,
    grid_params,
    levels_params,
)
from structural_kernel.decisions import GridParams
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.kernel import propose
from structural_kernel.objects import (
    AddDecision,
    AddOverride,
    Changeset,
    Decision,
    ModifyDecision,
    Override,
    OverrideProvenance,
    OverrideSet,
    OverrideTarget,
    SurveyedAnchor,
)
from structural_kernel.store import FileStore
from structural_kernel.units import Quantity
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash

_M = 0.3048  # ft -> m


def _m(value: float) -> Quantity:
    return Quantity(mag=value, unit="m")


def _anchor(x: float, y: float, z: float, tolerance: float | None = None) -> SurveyedAnchor:
    return SurveyedAnchor(
        x=_m(x),
        y=_m(y),
        z=_m(z),
        tolerance=None if tolerance is None else _m(tolerance),
    )


def _override(
    eid: str,
    value: str = "4x10",
    anchor: SurveyedAnchor | None = None,
    confidence: str = "measured",
) -> Override:
    return Override(
        target=OverrideTarget(eid=eid, field="section"),
        value=value,
        surveyed_anchor=anchor,
        provenance=OverrideProvenance.model_validate(
            {
                "observed_by": "M. Flamer",
                "method": "site_survey_tape",
                "observed_at": "2026-06-30",
                "confidence": confidence,
            }
        ),
    )


def _structure() -> tuple[Decision, Decision, Decision]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    framing = decision(
        "gravity_framing_strategy", "F", framing_params(), deps=[grid.did, levels.did]
    )
    return grid, levels, framing


def _derive(decisions: list[Decision], overrides: list[Override]) -> DerivedModel:
    snapshot = ResolvedSnapshot(
        decisions={d.did: d for d in decisions},
        overrides=OverrideSet(overrides=overrides),
    )
    return derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))


def _joist_eid(framing: Decision, ordinal: int) -> str:
    return f"jst:{framing.did}:{LY_A}-{LY_B}.{LX1}+{ordinal:03d}"


def _beam_eid(framing: Decision) -> str:
    return f"bm:{framing.did}:{LY_A}.{LX1}-{LX2}"


def test_attached_override_substitutes_and_carries_provenance() -> None:
    grid, levels, framing = _structure()
    target = _joist_eid(framing, 1)
    # anchor at the joist's midpoint: x = 16 in, y = 7 ft, z = 10 ft
    override = _override(target, anchor=_anchor(16 * 0.0254, 7 * _M, 10 * _M))
    model = _derive([grid, levels, framing], [override])

    [attachment] = model.override_attachments
    assert attachment.state == "attached"
    [element] = [e for e in model.elements if e.eid == target]
    assert element.section == "4x10"
    assert element.overridden["section"].observed_by == "M. Flamer"

    # flows into the bill...
    by_section = {(line.role, line.section): line.count for line in model.bill.lines}
    assert by_section[("joist", "4x10")] == 1
    assert by_section[("joist", "2x10")] == 18

    # ...and into member stiffness, exactly as if derived (§5)
    assert model.analysis is not None
    analysis_element = next(e for e in model.analysis.elements if e.source_eid == target)
    b, d = 3.5 * 0.0254, 9.25 * 0.0254  # dressed 4x10
    assert abs(analysis_element.I_strong_m4 - b * d**3 / 12) < 1e-12


def test_override_without_anchor_attaches_by_eid_alone() -> None:
    grid, levels, framing = _structure()
    model = _derive([grid, levels, framing], [_override(_joist_eid(framing, 3))])
    [attachment] = model.override_attachments
    assert attachment.state == "attached"
    assert attachment.distance_m is None


def test_override_wins_over_exception_on_the_same_field() -> None:
    grid, levels, framing = _structure()
    target = _joist_eid(framing, 2)
    exception = decision(
        "exception",
        "doubled joist",
        {"target_eid": target, "field": "section", "value": "2x12"},
        deps=[framing.did],
    )
    model = _derive([grid, levels, framing, exception], [_override(target)])
    [element] = [e for e in model.elements if e.eid == target]
    assert element.section == "4x10"  # reality substitutes after design (§5 ordering)


def test_gridline_move_displaces_the_override_never_reattaches() -> None:
    """The rest of ADR 0005 property test 2: the eid persists, the geometry
    moved, the surveyed member did not — displaced, inert, warned."""
    grid, levels, framing = _structure()
    beam = _beam_eid(framing)
    # surveyed at the beam midpoint while LY_A sat at y = 0
    override = _override(beam, anchor=_anchor(12 * _M, 0.0, 10 * _M))

    before = _derive([grid, levels, framing], [override])
    assert before.override_attachments[0].state == "attached"

    moved_lines = [
        line if line.line_id != LY_A else line.model_copy(update={"offset": ft(2.0)})
        for line in grid_params().lines
    ]
    moved = grid.model_copy(
        update={"params": GridParams(lines=moved_lines).model_dump(mode="json")}
    )
    after = _derive([moved, levels, framing], [override])

    # identity survived the move; correspondence-in-space did not
    assert {e.eid for e in after.elements} == {e.eid for e in before.elements}
    [attachment] = after.override_attachments
    assert attachment.state == "displaced"
    assert attachment.distance_m is not None
    assert abs(attachment.distance_m - 2 * _M) < 1e-9
    [element] = [e for e in after.elements if e.eid == beam]
    assert element.section == "4x12"  # inert: the derived value stands
    assert element.overridden == {}


def test_dangling_override_is_inert_and_proposes_candidates() -> None:
    grid, levels, framing = _structure()
    gone = _joist_eid(framing, 99)
    # surveyed near joist ordinal 6 (x = 96 in)
    override = _override(gone, anchor=_anchor(96 * 0.0254, 7 * _M, 10 * _M))
    model = _derive([grid, levels, framing], [override])

    [attachment] = model.override_attachments
    assert attachment.state == "dangling"
    assert _joist_eid(framing, 6) in attachment.candidates
    assert all(e.overridden == {} for e in model.elements)


def test_assumed_confidence_is_advisory_and_never_displaces() -> None:
    grid, levels, framing = _structure()
    target = _joist_eid(framing, 1)
    far = _anchor(50.0, 50.0, 0.0)  # nowhere near the joist
    model = _derive([grid, levels, framing], [_override(target, anchor=far, confidence="assumed")])
    assert model.override_attachments[0].state == "attached"


def test_explicit_tolerance_overrides_the_confidence_bucket() -> None:
    grid, levels, framing = _structure()
    target = _joist_eid(framing, 1)
    off_by_a_foot = _anchor(16 * 0.0254 + 1 * _M, 7 * _M, 10 * _M, tolerance=2.0)
    model = _derive([grid, levels, framing], [_override(target, anchor=off_by_a_foot)])
    assert model.override_attachments[0].state == "attached"


def test_commit_that_displaces_an_override_warns_but_commits(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid, levels, framing = _structure()
    setup = propose(
        store,
        Changeset(
            base_commit=None,
            ops=[
                AddDecision(decision=grid),
                AddDecision(decision=levels),
                AddDecision(decision=framing),
                AddOverride(
                    override=_override(_beam_eid(framing), anchor=_anchor(12 * _M, 0.0, 10 * _M))
                ),
            ],
        ),
        author=AUTHOR,
        message="structure + surveyed beam",
        timestamp=T0,
    )
    assert setup.outcome == "committed"
    assert setup.issues == []  # attached cleanly

    moved_lines = [
        line if line.line_id != LY_A else line.model_copy(update={"offset": ft(2.0)})
        for line in grid_params().lines
    ]
    moved = grid.model_copy(
        update={"params": GridParams(lines=moved_lines).model_dump(mode="json")}
    )
    result = propose(
        store,
        Changeset(base_commit=store.read_ref("main"), ops=[ModifyDecision(decision=moved)]),
        author=AUTHOR,
        message="move gridline A north 2 ft",
        timestamp=T0,
    )
    assert result.outcome == "committed"  # a warning, never a rejection
    [warning] = result.issues
    assert warning.code == "displaced_override"
    assert warning.severity == "warning"
    assert "surveyed by M. Flamer" in warning.message


def test_unsupported_override_field_is_rejected_at_commit(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid, levels, framing = _structure()
    bad = Override(
        target=OverrideTarget(eid=_joist_eid(framing, 1), field="length"),
        value="not a thing",
        provenance=OverrideProvenance(
            observed_by="M. Flamer",
            method="site_survey_tape",
            observed_at="2026-06-30",
            confidence="measured",
        ),
    )
    result = propose(
        store,
        Changeset(
            base_commit=None,
            ops=[
                AddDecision(decision=grid),
                AddDecision(decision=levels),
                AddDecision(decision=framing),
                AddOverride(override=bad),
            ],
        ),
        author=AUTHOR,
        message="bad override",
        timestamp=T0,
    )
    assert result.outcome == "rejected"
    assert result.issues[0].code == "derivation_failure"
