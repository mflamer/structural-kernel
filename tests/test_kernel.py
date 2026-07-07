"""The write path: propose → validate → commit | reject, with structured errors."""

from pathlib import Path

from conftest import (
    AUTHOR,
    LX1,
    T0,
    decision,
    framing_params,
    grid_params,
    lateral_params,
    levels_params,
    opening_params,
)
from structural_kernel.ids import new_ulid
from structural_kernel.kernel import ProposeResult, propose
from structural_kernel.objects import (
    AddDecision,
    AddOverride,
    Changeset,
    Commit,
    Decision,
    ModifyDecision,
    Override,
    OverrideProvenance,
    OverrideSet,
    OverrideTarget,
    RemoveDecision,
    Snapshot,
)
from structural_kernel.store import FileStore
from structural_kernel.validation import ValidationReport


def _propose(store: FileStore, changeset: Changeset) -> ProposeResult:
    return propose(store, changeset, author=AUTHOR, message="test", timestamp=T0)


def _commit_structure(store: FileStore) -> tuple[Decision, Decision]:
    """Commit grid + framing; returns (grid, framing)."""
    grid = decision("grid", "Grid", grid_params())
    framing = decision(
        "gravity_framing_strategy", "Floor framing", framing_params(), deps=[grid.did]
    )
    result = _propose(
        store,
        Changeset(
            base_commit=None,
            ops=[AddDecision(decision=grid), AddDecision(decision=framing)],
        ),
    )
    assert result.outcome == "committed", result.issues
    return grid, framing


def _codes(result: ProposeResult) -> set[str]:
    return {issue.code for issue in result.issues}


def test_genesis_commit_advances_ref_and_persists_everything(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid, framing = _commit_structure(store)

    commit_hash = store.read_ref("main")
    assert commit_hash is not None
    commit = store.get_model(commit_hash, Commit)
    assert commit.parents == []
    snapshot = store.get_model(commit.snapshot, Snapshot)
    assert set(snapshot.decisions) == {grid.did, framing.did}
    assert store.get_model(snapshot.decisions[grid.did], Decision) == grid
    assert commit.changeset is not None
    assert commit.changeset in store


def test_second_commit_chains_to_first(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid, _ = _commit_structure(store)
    base = store.read_ref("main")

    lateral = decision("lateral_strategy", "Shear walls", lateral_params(), deps=[grid.did])
    result = _propose(store, Changeset(base_commit=base, ops=[AddDecision(decision=lateral)]))
    assert result.outcome == "committed"
    tip = store.read_ref("main")
    assert tip is not None and tip != base
    assert store.get_model(tip, Commit).parents == [base]


def test_schema_stage_rejects_mis_dimensioned_params(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    bad = decision(
        "load_assumptions",
        "loads",
        {
            "area_loads": [{"case": "L", "magnitude": {"mag": 40.0, "unit": "ft"}}],
            "combo_set": "ASCE7-22-2.4-ASD",
        },
    )
    result = _propose(store, Changeset(base_commit=None, ops=[AddDecision(decision=bad)]))
    assert result.outcome == "rejected"
    assert _codes(result) == {"schema_invalid"}
    assert store.read_ref("main") is None
    # the attempt and its judgment persist
    report = store.get_model(result.report, ValidationReport)
    assert report.outcome == "rejected"
    assert report.changeset == result.changeset
    assert result.changeset in store


def test_referential_stage_rejects_unknown_line_ref(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    bad = decision(
        "opening",
        "door",
        opening_params().model_copy(update={"wall_line": "L0DEADBEE"}),
        deps=[grid.did],
    )
    result = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=grid), AddDecision(decision=bad)]),
    )
    assert result.outcome == "rejected"
    assert _codes(result) == {"unknown_line_ref"}


def test_line_refs_resolve_only_through_declared_deps(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    framing = decision("gravity_framing_strategy", "framing", framing_params(), deps=[])
    result = _propose(
        store,
        Changeset(
            base_commit=None, ops=[AddDecision(decision=grid), AddDecision(decision=framing)]
        ),
    )
    assert result.outcome == "rejected"
    assert _codes(result) == {"unknown_line_ref"}  # grid exists, but isn't a declared dep


def test_e3_deleting_a_referenced_line_is_rejected(tmp_path: Path) -> None:
    """ADR 0005 E3: a grid edit that drops a line-id still referenced by an
    *untouched* decision fails referential validation."""
    store = FileStore(tmp_path)
    grid, _framing = _commit_structure(store)
    base = store.read_ref("main")

    pruned = grid_params().model_copy(
        update={"lines": [line for line in grid_params().lines if line.line_id != LX1]}
    )
    result = _propose(
        store,
        Changeset(
            base_commit=base,
            ops=[
                ModifyDecision(
                    decision=grid.model_copy(update={"params": pruned.model_dump(mode="json")})
                )
            ],
        ),
    )
    assert result.outcome == "rejected"
    assert "unknown_line_ref" in _codes(result)


def test_e3_removing_the_grid_decision_is_rejected_via_missing_dep(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid, _framing = _commit_structure(store)
    result = _propose(
        store,
        Changeset(base_commit=store.read_ref("main"), ops=[RemoveDecision(did=grid.did)]),
    )
    assert result.outcome == "rejected"
    assert "missing_dep" in _codes(result)


def test_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    a_did, b_did = new_ulid(), new_ulid()
    a = decision("levels", "A", levels_params(), deps=[b_did]).model_copy(update={"did": a_did})
    b = decision("levels", "B", levels_params(), deps=[a_did]).model_copy(update={"did": b_did})
    result = _propose(
        store, Changeset(base_commit=None, ops=[AddDecision(decision=a), AddDecision(decision=b)])
    )
    assert result.outcome == "rejected"
    assert _codes(result) == {"dependency_cycle"}


def test_duplicate_and_unknown_decision_ops_are_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    dup = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=grid), AddDecision(decision=grid)]),
    )
    assert dup.outcome == "rejected"
    assert _codes(dup) == {"duplicate_decision"}

    unknown = _propose(store, Changeset(base_commit=None, ops=[RemoveDecision(did=new_ulid())]))
    assert unknown.outcome == "rejected"
    assert _codes(unknown) == {"unknown_decision"}


def test_stale_base_is_rejected_not_raised(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    _commit_structure(store)
    late = _propose(
        store,
        Changeset(
            base_commit=None,  # claims genesis, but main has moved
            ops=[AddDecision(decision=decision("levels", "L", levels_params()))],
        ),
    )
    assert late.outcome == "rejected"
    assert _codes(late) == {"stale_base"}


def test_open_decision_commits_and_holds_open(tmp_path: Path) -> None:
    """Standing requirement 2: 'structural system: unresolved' is committable."""
    store = FileStore(tmp_path)
    open_lateral = decision("lateral_strategy", "Lateral system TBD", None, state="open")
    result = _propose(store, Changeset(base_commit=None, ops=[AddDecision(decision=open_lateral)]))
    assert result.outcome == "committed"
    tip = store.read_ref("main")
    assert tip is not None
    snapshot = store.get_model(store.get_model(tip, Commit).snapshot, Snapshot)
    stored = store.get_model(snapshot.decisions[open_lateral.did], Decision)
    assert stored.state == "open"


def test_override_ops_land_in_the_snapshot(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    _commit_structure(store)
    override = Override(
        target=OverrideTarget(eid="jst:x:y+01", field="section"),
        value={"designation": "4x10"},
        provenance=OverrideProvenance(
            observed_by="M. Flamer",
            method="site_survey_tape",
            observed_at="2026-06-30",
            confidence="measured",
        ),
    )
    result = _propose(
        store,
        Changeset(base_commit=store.read_ref("main"), ops=[AddOverride(override=override)]),
    )
    assert result.outcome == "committed"
    tip = store.read_ref("main")
    assert tip is not None
    snapshot = store.get_model(store.get_model(tip, Commit).snapshot, Snapshot)
    assert snapshot.override_set is not None
    assert store.get_model(snapshot.override_set, OverrideSet).overrides == [override]

    duplicate = _propose(
        store,
        Changeset(base_commit=store.read_ref("main"), ops=[AddOverride(override=override)]),
    )
    assert duplicate.outcome == "rejected"
    assert _codes(duplicate) == {"duplicate_override"}


def test_rejection_collects_all_errors_within_a_stage(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    bad_opening = decision(
        "opening",
        "door",
        opening_params().model_copy(update={"wall_line": "L0DEADBEE", "offset_from": "L0DEADBEF"}),
        deps=[grid.did],
    )
    result = _propose(
        store,
        Changeset(
            base_commit=None,
            ops=[AddDecision(decision=grid), AddDecision(decision=bad_opening)],
        ),
    )
    assert result.outcome == "rejected"
    assert len([i for i in result.issues if i.code == "unknown_line_ref"]) == 2
