"""The ingestion seam, increments B and C: referenced geometry as a first-class
kind + the IFC grid/level fixture importer, and capture reading off it (design doc
0005 §3-4, ADR 0013; PO note 0004).

Referenced geometry is read-only external context a constraint anchors to — never
a decision. This proves: a deterministic IFC grid/storey import produces
referenced geometry a captured region anchors to (a real gridline-id), the region
resolves and enforces exactly like a decision-grid region, an unresolved
referenced anchor is inert (never fatal), a re-issued model surfaces affected
constraints for re-confirmation rather than silently diverging, and — increment C
— capture reads referenced geometry to propose ``inferred`` constraints (inert
until ratified) entirely on a fake reader (no vision model, no secrets).
"""

from __future__ import annotations

from pathlib import Path

from conftest import AUTHOR, T0, decision, ft, inches, psf
from structural_kernel.canonical import content_hash, model_document
from structural_kernel.capture import ConstraintCapture
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
from structural_kernel.ids import new_ulid
from structural_kernel.kernel import ProposeResult, load_snapshot, propose
from structural_kernel.llm import FakeLLMClient, ToolInvocation
from structural_kernel.objects import (
    AddConstraint,
    AddDecision,
    AddReferencedGeometry,
    Changeset,
    ChangesetOp,
    Decision,
    InferredConstraintProvenance,
    ProjectConstraint,
    RatifyConstraint,
    ReferencedGeometry,
    ReissueReferencedGeometry,
)
from structural_kernel.referenced import IMPORTER_VERSION, import_ifc_grids_and_levels
from structural_kernel.store import FileStore

FIXTURES = Path(__file__).parent / "fixtures"
V1 = FIXTURES / "arch-grids-v1.json"
V2_MOVED = FIXTURES / "arch-grids-v2-moved.json"
V2_REMOVED = FIXTURES / "arch-grids-v2-removed.json"

# Decision grid, sharing the plan origin with the architect's referenced grid: WX
# coincides with referenced grid GA (x=0), so a framing post at gridline 1.5
# (x=20) falls inside a referenced band measured off GA.
WX = "L000000W0"  # x = 0 ft
MX = "L000000M0"  # x = 20 ft
EX = "L000000E0"  # x = 40 ft
SY = "L000000S0"  # y = 0 ft
NY = "L000000N0"  # y = 30 ft


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


def _referenced_clear_span(
    ref_id: str, anchor_grid: str, extent_ft: float, side: str, statement: str
) -> ProjectConstraint:
    """An authored clear-span whose region anchors to a *referenced* gridline."""
    return ProjectConstraint.model_validate(
        {
            "cid": new_ulid(),
            "predicate": "no_vertical_support_within",
            "region": {
                "kind": "referenced_region",
                "ref_id": ref_id,
                "anchor_grid": anchor_grid,
                "extent": {"mag": extent_ft, "unit": "ft"},
                "side": side,
            },
            "payload": {},
            "statement": statement,
            "provenance": {"source": "authored", "captured_by": "human"},
        }
    )


# -- the importer --------------------------------------------------------------------


def test_importer_is_deterministic_and_stamps_external_provenance() -> None:
    ref_id = new_ulid()
    first = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09", version=1)
    second = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09", version=1)
    assert first == second  # same bytes -> same object, byte-for-byte
    assert first.version == 1
    assert first.provenance.source_file == "arch-grids-v1.json"
    assert first.provenance.importer == IMPORTER_VERSION
    assert len(first.provenance.file_hash) == 64  # sha256 hex
    # IFC tags become the stable grid/level ids; units convert to canonical.
    ga = next(g for g in first.grids if g.grid_id == "GA")
    assert ga.axis == "x"
    assert ga.offset.si_mag == 0.0
    assert {g.grid_id for g in first.grids} == {"GA", "GB", "G1", "G2"}
    assert {lv.level_id for lv in first.levels} == {"S1", "S2"}


def test_referenced_geometry_persists_and_reloads(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    tip = _commit(store, [AddReferencedGeometry(geometry=geometry)], base)
    reloaded = load_snapshot(store, tip).referenced_geometry
    assert set(reloaded) == {ref_id}
    assert reloaded[ref_id].version == 1
    assert {g.grid_id for g in reloaded[ref_id].grids} == {"GA", "GB", "G1", "G2"}


# -- a referenced region resolves and enforces ---------------------------------------


def test_a_referenced_region_anchors_to_a_gridline_and_enforces(tmp_path: Path) -> None:
    """The acceptance signal: an IFC grid import produces referenced geometry a
    captured region anchors to (grid GA), and the constraint enforces exactly like
    a decision-grid region — a post interior to the band is rejected."""
    store = FileStore(tmp_path)
    base, dids = _base_bay(store)
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    constraint = _referenced_clear_span(ref_id, "GA", 40.0, "greater", "west 40 ft off arch grid A")
    tip = _commit(
        store,
        [AddReferencedGeometry(geometry=geometry), AddConstraint(constraint=constraint)],
        base,
    )
    # A post at gridline 1.5 (x=20) is interior to the band [0, 40] off GA.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], tip)
    assert result.outcome == "rejected"
    [issue] = [i for i in result.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    assert issue.detail["cid"] == constraint.cid


def test_a_full_span_framing_commits_under_a_referenced_region(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, dids = _base_bay(store)
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    constraint = _referenced_clear_span(ref_id, "GA", 40.0, "greater", "west 40 ft off arch grid A")
    tip = _commit(
        store,
        [AddReferencedGeometry(geometry=geometry), AddConstraint(constraint=constraint)],
        base,
    )
    # WX..EX spans the full 40 ft with posts only on the boundaries — allowed.
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, EX))], tip)
    assert result.outcome == "committed", result.issues


def test_a_referenced_region_with_no_backing_geometry_is_inert(tmp_path: Path) -> None:
    """An unresolved referenced anchor is inert with a warning, never fatal — the
    override-like posture (a constraint pointing at un-imported geometry does not
    reject a changeset; it goes dangling)."""
    store = FileStore(tmp_path)
    base, dids = _base_bay(store)
    # No AddReferencedGeometry: the constraint's ref_id resolves to nothing.
    constraint = _referenced_clear_span(new_ulid(), "GA", 40.0, "greater", "dangling reference")
    tip = _commit(store, [AddConstraint(constraint=constraint)], base)
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], tip)
    assert result.outcome == "committed", result.issues
    inert = [i for i in result.issues if i.code == "constraint_inert"]
    assert any(i.detail["cid"] == constraint.cid for i in inert)


# -- re-issue: surface for re-confirmation, never silently diverge --------------------


def _setup_referenced_constraint(store: FileStore) -> tuple[str, dict[str, Decision], str, str]:
    base, dids = _base_bay(store)
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    constraint = _referenced_clear_span(ref_id, "GA", 40.0, "greater", "west 40 ft off arch grid A")
    tip = _commit(
        store,
        [AddReferencedGeometry(geometry=geometry), AddConstraint(constraint=constraint)],
        base,
    )
    return tip, dids, ref_id, constraint.cid


def test_reissue_that_moves_the_anchor_surfaces_reconfirmation_and_keeps_binding(
    tmp_path: Path,
) -> None:
    store = FileStore(tmp_path)
    tip, dids, ref_id, cid = _setup_referenced_constraint(store)
    moved = import_ifc_grids_and_levels(
        V2_MOVED, ref_id=ref_id, imported_at="2026-07-10", version=2
    )
    result = propose(
        store,
        Changeset(base_commit=tip, ops=[ReissueReferencedGeometry(geometry=moved)]),
        author=AUTHOR,
        message="architect moved grid A",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    reissue = [i for i in result.issues if i.code == "referenced_reissue"]
    assert len(reissue) == 1
    assert reissue[0].detail["cid"] == cid
    assert reissue[0].detail["change"] == "moved"
    # The constraint still binds at the new position: a post at x=20 is still
    # interior to the band [2, 42] off the moved grid A.
    assert result.commit is not None
    follow = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], result.commit)
    assert follow.outcome == "rejected"
    assert any(i.code == "constraint_violation" for i in follow.issues)


def test_reissue_that_removes_the_anchor_surfaces_removed_and_goes_inert(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, dids, ref_id, cid = _setup_referenced_constraint(store)
    removed = import_ifc_grids_and_levels(
        V2_REMOVED, ref_id=ref_id, imported_at="2026-07-10", version=2
    )
    result = propose(
        store,
        Changeset(base_commit=tip, ops=[ReissueReferencedGeometry(geometry=removed)]),
        author=AUTHOR,
        message="architect removed grid A",
        timestamp=T0,
    )
    assert result.outcome == "committed", result.issues
    reissue = [i for i in result.issues if i.code == "referenced_reissue"]
    assert any(i.detail["cid"] == cid and i.detail["change"] == "removed" for i in reissue)
    # With the anchor gone, the region no longer resolves — inert (dangling), so a
    # post interior to the old band is no longer rejected.
    assert result.commit is not None
    follow = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], result.commit)
    assert follow.outcome == "committed", follow.issues


# -- re-issue guards -----------------------------------------------------------------


def test_reissue_requires_a_strictly_higher_version(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    tip, _dids, ref_id, _cid = _setup_referenced_constraint(store)
    same = import_ifc_grids_and_levels(V2_MOVED, ref_id=ref_id, imported_at="2026-07-10", version=1)
    result = _try(store, [ReissueReferencedGeometry(geometry=same)], tip)
    assert result.outcome == "rejected"
    assert any(i.code == "stale_referenced_version" for i in result.issues)


def test_reissuing_unknown_referenced_geometry_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    orphan = import_ifc_grids_and_levels(V1, ref_id=new_ulid(), imported_at="2026-07-10", version=2)
    result = _try(store, [ReissueReferencedGeometry(geometry=orphan)], base)
    assert result.outcome == "rejected"
    assert any(i.code == "unknown_referenced_geometry" for i in result.issues)


def test_adding_a_duplicate_referenced_lineage_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    tip = _commit(store, [AddReferencedGeometry(geometry=geometry)], base)
    again = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    result = _try(store, [AddReferencedGeometry(geometry=again)], tip)
    assert result.outcome == "rejected"
    assert any(i.code == "duplicate_referenced_geometry" for i in result.issues)


# -- increment C: capture reads referenced geometry ----------------------------------


def _clear_span_reader() -> FakeLLMClient:
    """A canned vision reader: proposes a clear-span off referenced grid GA, with a
    stated basis and confidence — no real vision model in the test path."""
    return FakeLLMClient(
        [
            ToolInvocation(
                name="capture_clear_span",
                input={
                    "statement": "The west 40 ft reads as column-free.",
                    "anchor_line": "GA",
                    "extent_ft": 40.0,
                    "side": "greater",
                    "reason": "the west assembly bay carries no columns in the arch model",
                    "confidence": "high",
                },
            )
        ]
    )


def _import_geometry(store: FileStore, base: str) -> tuple[str, str, ReferencedGeometry]:
    ref_id = new_ulid()
    geometry = import_ifc_grids_and_levels(V1, ref_id=ref_id, imported_at="2026-07-09")
    tip = _commit(store, [AddReferencedGeometry(geometry=geometry)], base)
    return tip, ref_id, geometry


def test_capture_from_referenced_commits_an_inferred_constraint(tmp_path: Path) -> None:
    """Reading a drawing proposes an ``inferred`` constraint anchored to a real
    referenced gridline, carrying the model's basis (the version it read, its
    reason) and confidence — committed inert, never authored."""
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    tip, ref_id, geometry = _import_geometry(store, base)
    ops = ConstraintCapture(_clear_span_reader()).capture(
        utterance="", snapshot=load_snapshot(store, tip), referenced=geometry
    )
    assert len(ops) == 1
    committed = _commit(store, ops, tip)

    [constraint] = list(load_snapshot(store, committed).constraints.values())
    prov = constraint.provenance
    assert isinstance(prov, InferredConstraintProvenance)  # inferred, not authored
    assert prov.captured_by == "fake-llm"  # the reader identity is recorded
    assert prov.confidence == "high"
    assert prov.ratified is None  # inert until an engineer ratifies it
    # The basis records exactly the referenced-geometry version that was read.
    assert prov.basis.referenced_geometry == content_hash(model_document(geometry))
    assert "GA" in (prov.basis.region_ref or "")
    region = constraint.region.model_dump()
    assert region["kind"] == "referenced_region"
    assert region["ref_id"] == ref_id
    assert region["anchor_grid"] == "GA"


def _capture_and_commit(store: FileStore) -> tuple[str, dict[str, Decision], str]:
    """Import geometry, read an inferred clear-span off it, and commit it."""
    base, dids = _base_bay(store)
    tip, _ref_id, geometry = _import_geometry(store, base)
    ops = ConstraintCapture(_clear_span_reader()).capture(
        utterance="", snapshot=load_snapshot(store, tip), referenced=geometry
    )
    captured = _commit(store, ops, tip)
    [constraint] = list(load_snapshot(store, captured).constraints.values())
    return captured, dids, constraint.cid


def test_a_captured_inferred_constraint_is_inert_before_ratify(tmp_path: Path) -> None:
    """The whole path on a fake reader (no vision model, no secrets): a post in the
    captured reading's region commits, inert, with an unratified warning."""
    store = FileStore(tmp_path)
    captured, dids, _cid = _capture_and_commit(store)
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], captured)
    assert result.outcome == "committed", result.issues
    assert any(i.code == "constraint_unratified" for i in result.issues)


def test_a_captured_inferred_constraint_binds_after_ratify(tmp_path: Path) -> None:
    """Ratified on its own branch, the captured reading then enforces exactly like
    an authored one — a post in its region is rejected."""
    store = FileStore(tmp_path)
    captured, dids, cid = _capture_and_commit(store)
    ratified = _commit(
        store, [RatifyConstraint(cid=cid, ratified_by="eng:mark", ratified_at=T0)], captured
    )
    result = _try(store, [AddDecision(decision=_framing_decision(dids, WX, MX))], ratified)
    assert result.outcome == "rejected"
    assert any(i.code == "constraint_violation" and i.detail["cid"] == cid for i in result.issues)


def test_capture_without_referenced_geometry_stays_authored(tmp_path: Path) -> None:
    """Conversation authoring is unchanged — a spoken constraint (no referenced
    geometry) commits ``authored`` and binding, not inferred."""
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    client = FakeLLMClient(
        [
            ToolInvocation(
                name="capture_clear_span",
                input={
                    "statement": "The west 40 ft must be column-free.",
                    "anchor_line": WX,
                    "extent_ft": 40.0,
                    "side": "greater",
                },
            )
        ]
    )
    ops = ConstraintCapture(client).capture(
        utterance="the west 40 feet needs to be column-free", snapshot=load_snapshot(store, base)
    )
    tip = _commit(store, ops, base)
    [constraint] = list(load_snapshot(store, tip).constraints.values())
    assert constraint.provenance.source == "authored"
    assert constraint.region.model_dump()["kind"] == "offset_band"


def test_a_malformed_inferred_capture_is_a_recorded_rejection(tmp_path: Path) -> None:
    """A bad reading is bounded by the pipeline, not parser quality: a min-bay
    proposal missing its spacing builds an op but the schema stage rejects it —
    never a silent or corrupt write."""
    store = FileStore(tmp_path)
    base, _dids = _base_bay(store)
    tip, _ref_id, geometry = _import_geometry(store, base)
    client = FakeLLMClient(
        [
            ToolInvocation(
                name="capture_min_bay",
                input={"statement": "keep bays generous", "confidence": "low"},
            )
        ]
    )
    ops = ConstraintCapture(client).capture(
        utterance="", snapshot=load_snapshot(store, tip), referenced=geometry
    )
    result = _try(store, ops, tip)
    assert result.outcome == "rejected"
    assert any(i.code == "schema_invalid" for i in result.issues)
