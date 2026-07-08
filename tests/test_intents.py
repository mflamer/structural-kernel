"""Intent registry and commit-time checkers (ADR 0004, validation stage 4)."""

from pathlib import Path

from conftest import (
    AUTHOR,
    T0,
    decision,
    framing_params,
    grid_params,
    levels_params,
    loads_params,
    opening_params,
)
from structural_kernel.derivation import derive
from structural_kernel.intents import REGISTRY, check_intent
from structural_kernel.kernel import ProposeResult, propose
from structural_kernel.objects import AddDecision, Changeset, Decision
from structural_kernel.store import FileStore
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash


def _propose(store: FileStore, changeset: Changeset) -> ProposeResult:
    return propose(store, changeset, author=AUTHOR, message="test", timestamp=T0)


def _structure(*, opening_declares_framing: bool) -> list[Decision]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    framing = decision(
        "gravity_framing_strategy",
        "Floor framing",
        framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    opening_deps = [grid.did, loads.did] + ([framing.did] if opening_declares_framing else [])
    opening = decision("opening", "Door D1", opening_params(), deps=opening_deps)
    return [grid, levels, loads, framing, opening]


def test_phase1_categories_are_registered_with_checkers() -> None:
    assert set(REGISTRY) == {
        "gravity_load_path",
        "lateral_capacity",
        "serviceability",
        "retrofit_rationale",
    }
    for registration in REGISTRY.values():
        assert callable(registration.checker)
        assert registration.relation_roles


def test_opening_without_header_is_an_intent_violation(tmp_path: Path) -> None:
    """An opening piercing a bearing line with no header redirecting around it:
    the load path passes through the hole."""
    store = FileStore(tmp_path)
    structure = _structure(opening_declares_framing=False)
    result = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=d) for d in structure]),
    )
    assert result.outcome == "rejected"
    [issue] = result.issues
    assert issue.code == "intent_violation"
    assert issue.detail["category"] == "gravity_load_path"
    assert issue.detail["violated"] == "redirects_load_around"
    broken = issue.detail["broken_path"]
    assert isinstance(broken, list) and "∅" in broken
    assert any(str(part).startswith("jst:") for part in broken)


def test_the_same_structure_with_the_header_commits(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    structure = _structure(opening_declares_framing=True)
    result = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=d) for d in structure]),
    )
    assert result.outcome == "committed", result.issues


def test_authored_intent_with_unknown_category_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    bad = decision(
        "levels",
        "Levels",
        levels_params(),
        intent=[
            {
                "category": "vibration",  # not registered (yet) — the charter's test case
                "payload": {},
                "provenance": {"source": "authored"},
            }
        ],
    )
    result = _propose(store, Changeset(base_commit=None, ops=[AddDecision(decision=bad)]))
    assert result.outcome == "rejected"
    assert result.issues[0].code == "unknown_intent_category"


def test_authored_intent_with_undeclared_role_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    bad = decision(
        "lateral_strategy",
        "Walls",
        {"wall_lines": [grid_params().lines[2].line_id]},
        deps=[grid.did],
        intent=[
            {
                "category": "lateral_capacity",
                "payload": {},
                "relations": [{"role": "made_up_role", "target": {"provision": "SDPWS 4.3"}}],
                "provenance": {"source": "authored"},
            }
        ],
    )
    result = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=grid), AddDecision(decision=bad)]),
    )
    assert result.outcome == "rejected"
    assert any(
        i.code == "schema_invalid" and i.detail.get("role") == "made_up_role" for i in result.issues
    )


def test_authored_eid_target_must_resolve_against_the_derived_model(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", grid_params())
    pinned = decision(
        "lateral_strategy",
        "Walls",
        {"wall_lines": [grid_params().lines[2].line_id]},
        deps=[grid.did],
        intent=[
            {
                "category": "retrofit_rationale",
                "payload": {"narrative": "restores capacity removed by the alteration"},
                "relations": [{"role": "carries", "target": {"eid": "jst:nope:X+000"}}],
                "provenance": {"source": "authored"},
            }
        ],
    )
    result = _propose(
        store,
        Changeset(base_commit=None, ops=[AddDecision(decision=grid), AddDecision(decision=pinned)]),
    )
    assert result.outcome == "rejected"
    [issue] = result.issues
    assert issue.code == "intent_violation"
    assert issue.detail["eid"] == "jst:nope:X+000"


def test_checkers_are_pure_and_deterministic() -> None:
    structure = _structure(opening_declares_framing=False)
    snapshot = ResolvedSnapshot(decisions={d.did: d for d in structure})
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    first = check_intent(model, snapshot)
    second = check_intent(model, snapshot)
    assert [v.model_dump() for v in first] == [v.model_dump() for v in second]
    assert first  # the violating structure does violate
