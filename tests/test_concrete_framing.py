"""Concrete three-tier framing (ADR 0014, note 0006): the dimensioned decision
kind, the derivation rule, the concrete countables, and — increment 3 — the ACI
design checks concrete members earn automatically because checks resolve their
engine by family. The sprint's real acceptance: registering concrete required a
new member *description*, and no change to MemberCheckData, the registry shape,
or how checks are consumed.
"""

from pathlib import Path

import pytest

from conftest import (
    AUTHOR,
    T0,
    compact_grid_params,
    concrete_framing_params,
    cost_basis_params,
    decision,
    framing_params,
    ft,
    grid_params,
    inches,
    levels_params,
    loads_params,
    lrfd_loads_params,
    steel_framing_params,
    usd,
)
from reference_solver import ReferenceEngine
from structural_kernel.canonical import canonical_bytes, model_document
from structural_kernel.costing import quantity_kind
from structural_kernel.decisions import (
    ConcreteMemberSpec,
    CostFactor,
    DirectPrice,
    GridLine,
    GridParams,
    GridRegion,
)
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.design_checks import run_design_checks
from structural_kernel.explorations import (
    Convergence,
    Exploration,
    ExplorationBudget,
    IntentPreservedConstraint,
    MetricConstraint,
    Objective,
    Proposal,
    SpatialConstraintsPreservedConstraint,
    SystemChoiceProposer,
    evaluate,
    run_exploration,
)
from structural_kernel.ids import new_ulid
from structural_kernel.kernel import load_snapshot, propose
from structural_kernel.materials.concrete import section_designation
from structural_kernel.objects import (
    AddConstraint,
    AddDecision,
    Changeset,
    ChangesetOp,
    Decision,
    ModifyDecision,
    ProjectConstraint,
)
from structural_kernel.solver import LocalSolverService, SolveResult
from structural_kernel.store import FileStore
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash

_M_PER_IN = 0.0254


def _snapshot(*decisions: Decision) -> ResolvedSnapshot:
    return ResolvedSnapshot(decisions={d.did: d for d in decisions})


def _concrete_model() -> tuple[DerivedModel, dict[str, Decision]]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "concrete_framing_strategy",
        "Concrete frame",
        concrete_framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    snapshot = _snapshot(grid, levels, loads, framing)
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    return model, {"grid": grid, "levels": levels, "loads": loads, "framing": framing}


# -- the member-description schema (the one representational divergence) ------------


def test_member_spec_is_structured_not_a_string() -> None:
    """Reinforcement is structured, tagged-unit data (note 0006's demand): a
    stirrup pair comes together, and cover must be inside the depth."""
    with pytest.raises(ValueError, match="together or not at all"):
        ConcreteMemberSpec(
            breadth=inches(12.0),
            depth=inches(16.0),
            bars=3,
            bar="#6",
            cover=inches(2.5),
            stirrup_bar="#3",  # spacing missing
        )
    with pytest.raises(ValueError, match="less than the overall depth"):
        ConcreteMemberSpec(
            breadth=inches(12.0),
            depth=inches(16.0),
            bars=3,
            bar="#6",
            cover=inches(16.0),
        )


# -- the derived three-tier topology -------------------------------------------------


def test_concrete_frame_derives_beams_girders_and_columns() -> None:
    model, ids = _concrete_model()
    beams = [e for e in model.elements if e.role == "beam"]
    girders = [e for e in model.elements if e.role == "girder"]
    columns = [e for e in model.elements if e.role == "column"]

    assert len(beams) == 5  # 24 ft at 6 ft: ordinals 0..4
    assert len(girders) == 2  # on lines A and B
    assert len(columns) == 4  # region corners

    for element in beams + girders + columns:
        assert element.family == "cast_in_place_concrete"
        assert element.grade == "4000psi"  # the mix designation is the grade key
        assert element.design_method == "LRFD"
        assert ids["framing"].did in element.eid

    # Sections are dimensioned designations rendered from the authored (b, h).
    assert {e.section for e in beams} == {section_designation(12 * _M_PER_IN, 16 * _M_PER_IN)}
    assert {e.section for e in girders} == {section_designation(12 * _M_PER_IN, 24 * _M_PER_IN)}
    assert {e.section for e in columns} == {section_designation(12 * _M_PER_IN, 12 * _M_PER_IN)}


def test_concrete_members_carry_their_reinforcement() -> None:
    """The authored reinforcement travels on the derived member — the fact the
    designation cannot carry, persisted in the element (ADR 0014)."""
    model, _ = _concrete_model()
    beam = next(e for e in model.elements if e.role == "beam")
    girder = next(e for e in model.elements if e.role == "girder")
    column = next(e for e in model.elements if e.role == "column")

    assert beam.reinforcement is not None
    assert (beam.reinforcement.bars, beam.reinforcement.bar) == (3, "#6")
    assert beam.reinforcement.stirrup_bar == "#3"
    assert beam.reinforcement.grade == "Gr60"
    assert girder.reinforcement is not None
    assert (girder.reinforcement.bars, girder.reinforcement.bar) == (3, "#8")
    assert column.reinforcement is not None
    assert (column.reinforcement.bars, column.reinforcement.bar) == (4, "#8")
    assert column.reinforcement.transverse == "ties"
    # cover is a tagged quantity, to the tension-steel centroid
    assert beam.reinforcement.cover.si_mag == pytest.approx(2.5 * _M_PER_IN)


def test_concrete_eids_use_the_three_tier_tokens() -> None:
    model, _ = _concrete_model()
    prefixes = {e.eid.split(":", 1)[0] for e in model.elements}
    assert prefixes == {"bm", "gdr", "col"}


def test_concrete_load_path_is_beam_on_girder_on_column() -> None:
    model, _ = _concrete_model()
    by_eid = {e.eid: e for e in model.elements}
    girder_eids = {e.eid for e in model.elements if e.role == "girder"}
    for beam in (e for e in model.elements if e.role == "beam"):
        assert set(beam.supports) == girder_eids
    for girder_eid in girder_eids:
        girder = by_eid[girder_eid]
        assert len(girder.supports) == 2
        assert all(by_eid[s].role == "column" for s in girder.supports)


def test_concrete_analysis_uses_gross_section_and_ec() -> None:
    """The analysis artifact idealizes concrete uncracked: gross A and Ig from
    the parseable designation, Ec from the mix (ACI 19.2.2.1) — the documented
    ADR 0014 idealization (Ie refinement deferred)."""
    model, _ = _concrete_model()
    assert model.analysis is not None
    girder_eid = next(e.eid for e in model.elements if e.role == "girder")
    analysis_girder = next(e for e in model.analysis.elements if e.source_eid == girder_eid)
    b, h = 12 * _M_PER_IN, 24 * _M_PER_IN
    assert analysis_girder.A_m2 == pytest.approx(b * h)
    assert analysis_girder.I_strong_m4 == pytest.approx(b * h**3 / 12)
    psi = 4.4482216152605 / _M_PER_IN**2
    assert analysis_girder.E_pa == pytest.approx(57000 * 4000**0.5 * psi, rel=1e-6)
    # LRFD strength combos + service combos both present (deflection is service).
    purposes = {c.purpose for c in model.analysis.combos}
    assert purposes == {"strength", "service"}


def test_concrete_frame_is_formed_not_picked() -> None:
    model, _ = _concrete_model()
    assert model.bill.countables.crane_picks == 0  # CIP: 0 picks (PO call)


def test_concrete_derivation_is_deterministic() -> None:
    grid = decision("grid", "Grid", grid_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "concrete_framing_strategy", "F", concrete_framing_params(), deps=[grid.did, loads.did]
    )
    a = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    b = derive(_snapshot(grid, loads, framing), snapshot_hash="sha256:" + "0" * 64)
    assert canonical_bytes(model_document(a)) == canonical_bytes(model_document(b))


# -- the concrete countables (derived, never invented by pricing; note 0003) ---------


def test_concrete_volume_formwork_and_rebar_are_derived_countables() -> None:
    model, _ = _concrete_model()
    length_beam = 14 * 0.3048  # beams span y: 14 ft
    length_girder = 24 * 0.3048
    length_column = 10 * 0.3048  # levels elevation

    volume = quantity_kind("concrete_volume")
    assert volume is not None
    expected_volume = (
        5 * (12 * _M_PER_IN) * (16 * _M_PER_IN) * length_beam
        + 2 * (12 * _M_PER_IN) * (24 * _M_PER_IN) * length_girder
        + 4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    assert volume.resolve(model, None, None) == pytest.approx(expected_volume)

    formwork = quantity_kind("formwork_area")
    assert formwork is not None
    b_bm, h_bm = 12 * _M_PER_IN, 16 * _M_PER_IN
    b_gd, h_gd = 12 * _M_PER_IN, 24 * _M_PER_IN
    b_c = 12 * _M_PER_IN
    expected_formwork = (
        5 * (b_bm + 2 * h_bm) * length_beam  # beams: 3 formed sides
        + 2 * (b_gd + 2 * h_gd) * length_girder  # girders: 3 formed sides
        + 4 * (2 * (b_c + b_c)) * length_column  # columns: 4 formed sides
    )
    assert formwork.resolve(model, None, None) == pytest.approx(expected_formwork)

    rebar = quantity_kind("rebar_mass")
    assert rebar is not None
    steel_density = 7850.0
    as_6 = 3 * 0.44 * _M_PER_IN**2  # 3-#6
    as_8_beams = 3 * 0.79 * _M_PER_IN**2  # 3-#8 (girders)
    as_8_cols = 4 * 0.79 * _M_PER_IN**2  # 4-#8 (columns)
    expected_rebar = steel_density * (
        5 * as_6 * length_beam + 2 * as_8_beams * length_girder + 4 * as_8_cols * length_column
    )
    assert rebar.resolve(model, None, None) == pytest.approx(expected_rebar)

    # Scoping works: the role scope isolates a tier.
    assert volume.resolve(model, "cast_in_place_concrete", "column") == pytest.approx(
        4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    # And a wood/steel-only model yields zero concrete countables (not an error).
    assert volume.resolve(model, "hot_rolled_steel", None) == 0.0


def test_concrete_member_weight_needs_no_special_case() -> None:
    """The generic member_weight countable prices concrete through the same
    section_properties + density path as any catalog family — the parseable
    designation makes the mass substrate just work (the exploration mass metric
    reads the identical engine facts; increment 3 ranks on it publicly)."""
    model, _ = _concrete_model()
    weight = quantity_kind("member_weight")
    assert weight is not None
    length_beam, length_girder, length_column = 14 * 0.3048, 24 * 0.3048, 10 * 0.3048
    expected = 2400.0 * (
        5 * (12 * _M_PER_IN) * (16 * _M_PER_IN) * length_beam
        + 2 * (12 * _M_PER_IN) * (24 * _M_PER_IN) * length_girder
        + 4 * (12 * _M_PER_IN) * (12 * _M_PER_IN) * length_column
    )
    assert weight.resolve(model, "cast_in_place_concrete", None) == pytest.approx(expected)


# -- the ACI checks concrete earns for free (increment 3; the boundary confirmed) ----


def _compact_concrete_model() -> DerivedModel:
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    framing = decision(
        "concrete_framing_strategy",
        "Concrete frame",
        concrete_framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    snapshot = _snapshot(grid, levels, loads, framing)
    return derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))


def _solved(model: DerivedModel) -> SolveResult:
    assert model.analysis is not None
    service = LocalSolverService(ReferenceEngine())
    [result] = service.results(service.submit([model.analysis]))
    assert result.status == "solved"
    return result


def test_concrete_members_get_aci_checks_with_no_vocabulary_change() -> None:
    """The sprint's real acceptance (note 0006): concrete members earn ACI
    checks through the ordinary path — checks resolve the engine by family,
    results arrive as unchanged MemberCheckData/DesignCheck — with strength on
    LRFD combos and deflection staying a service-level check."""
    model = _compact_concrete_model()
    report = run_design_checks(model, _solved(model))

    bending = [c for c in report.checks if c.check == "bending"]
    assert bending and all(c.provision.startswith("ACI") for c in bending)
    assert all(any(f.symbol == "phi" for f in c.factors) for c in bending)
    shear = [c for c in report.checks if c.check == "shear"]
    assert shear and all(c.provision.startswith("ACI") for c in shear)
    # strength checks ran on factored LRFD combos, never a service one
    assert all(c.combo.startswith("1.") for c in report.checks if c.check in ("bending", "shear"))
    # deflection ran on a service combo (the gross-Ig idealization, ADR 0014)
    deflection = [c for c in report.checks if c.check.startswith("deflection")]
    assert deflection and all(not c.combo.startswith("1.") for c in deflection)
    # columns earn concentric compression checks through the ACI engine
    columns = {e.eid for e in model.elements if e.role == "column"}
    compression = [c for c in report.checks if c.check == "compression"]
    assert compression and {c.eid for c in compression} <= columns
    assert all(c.provision.startswith("ACI") for c in compression)
    # every check cites the intent it enforces (the two-site discipline, ADR 0004)
    for check in report.checks:
        if check.check in ("bending", "shear", "compression"):
            assert check.enforces.category == "gravity_load_path"
    # this small concrete bay is a real design
    assert report.all_pass, [c.eid for c in report.checks if not c.passes]


# -- spatial constraints predicate by role, not material (note 0006) -----------------

WX = "L000000W0"  # x = 0 ft
MX = "L000000M0"  # x = 20 ft
EX = "L000000E0"  # x = 40 ft
SY = "L000000S0"  # y = 0 ft
NY = "L000000N0"  # y = 30 ft


def _band_grid() -> GridParams:
    return GridParams(
        lines=[
            GridLine(line_id=WX, name="1", axis="x", offset=ft(0.0)),
            GridLine(line_id=MX, name="1.5", axis="x", offset=ft(20.0)),
            GridLine(line_id=EX, name="2", axis="x", offset=ft(40.0)),
            GridLine(line_id=SY, name="A", axis="y", offset=ft(0.0)),
            GridLine(line_id=NY, name="B", axis="y", offset=ft(30.0)),
        ]
    )


def _clear_span_constraint() -> ProjectConstraint:
    return ProjectConstraint.model_validate(
        {
            "cid": new_ulid(),
            "predicate": "no_vertical_support_within",
            "region": {
                "kind": "offset_band",
                "anchor": WX,
                "extent": {"mag": 40.0, "unit": "ft"},
                "side": "greater",
            },
            "payload": {},
            "statement": "west 40 ft column-free",
            "provenance": {"source": "authored", "captured_by": "human"},
        }
    )


def test_a_concrete_column_violates_clear_span_by_role(tmp_path: Path) -> None:
    """A spatial constraint predicates on element role, not material (note
    0006): a concrete column inside the protected band is rejected pre-solve
    exactly as a wood post or steel column would be."""
    store = FileStore(tmp_path)
    grid = decision("grid", "Grid", _band_grid())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", lrfd_loads_params())
    base = propose(
        store,
        Changeset(
            base_commit=None,
            ops=[
                *(AddDecision(decision=d) for d in (grid, levels, loads)),
                AddConstraint(constraint=_clear_span_constraint()),
            ],
        ),
        author=AUTHOR,
        message="base + clear span",
        timestamp=T0,
    )
    assert base.outcome == "committed", base.issues

    def framing(x_to: str) -> Decision:
        params = concrete_framing_params().model_copy(
            update={"region": GridRegion(x_from=WX, x_to=x_to, y_from=SY, y_to=NY)}
        )
        return decision(
            "concrete_framing_strategy",
            f"Concrete to {x_to}",
            params,
            deps=[grid.did, levels.did, loads.did],
        )

    # A concrete column at gridline 1.5 (x=20) is interior to the band: rejected.
    violating = propose(
        store,
        Changeset(base_commit=base.commit, ops=[AddDecision(decision=framing(MX))]),
        author=AUTHOR,
        message="violating concrete frame",
        timestamp=T0,
    )
    assert violating.outcome == "rejected"
    [issue] = [i for i in violating.issues if i.severity == "error"]
    assert issue.code == "constraint_violation"
    supports = issue.detail["supports"]
    assert isinstance(supports, list) and supports
    assert all(str(eid).startswith("col:") for eid in supports)  # concrete columns

    # The full 40 ft span puts columns only on the boundary lines: commits.
    compliant = propose(
        store,
        Changeset(base_commit=base.commit, ops=[AddDecision(decision=framing(EX))]),
        author=AUTHOR,
        message="compliant concrete frame",
        timestamp=T0,
    )
    assert compliant.outcome == "committed", compliant.issues


# -- heterogeneous exploration: three families, no new mechanism ---------------------


def _three_way_exploration(
    store: FileStore, *, objectives: list[Objective], basis: Decision | None = None
) -> tuple[Exploration, dict[str, str]]:
    """Wood vs steel vs concrete over the same compact bay, through the ordinary
    SystemChoiceProposer — the third family rides the ADR 0008 pattern with no
    new exploration mechanism."""
    grid = decision("grid", "Grid", compact_grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
    ops: list[ChangesetOp] = [AddDecision(decision=d) for d in (grid, levels, loads)]
    if basis is not None:
        ops.append(AddDecision(decision=basis))
    committed = propose(
        store,
        Changeset(base_commit=None, ops=ops),
        author=AUTHOR,
        message="base",
        timestamp=T0,
    )
    assert committed.outcome == "committed", committed.issues
    assert committed.commit is not None
    deps = [grid.did, levels.did, loads.did]
    loads_lrfd = loads.model_copy(update={"params": lrfd_loads_params().model_dump(mode="json")})
    wood = decision("gravity_framing_strategy", "Wood", framing_params(), deps)
    steel = decision("steel_framing_strategy", "Steel", steel_framing_params(), deps)
    concrete = decision("concrete_framing_strategy", "Concrete", concrete_framing_params(), deps)
    proposer = SystemChoiceProposer(
        [
            Proposal(ops=[AddDecision(decision=wood)], rationale="wood: NDS/ASD"),
            Proposal(
                ops=[AddDecision(decision=steel), ModifyDecision(decision=loads_lrfd)],
                rationale="steel: AISC/LRFD",
            ),
            Proposal(
                ops=[AddDecision(decision=concrete), ModifyDecision(decision=loads_lrfd)],
                rationale="concrete: ACI/LRFD, dimensioned members",
            ),
        ]
    )
    exploration = run_exploration(
        store,
        base_commit=committed.commit,
        objectives=objectives,
        constraints=[
            MetricConstraint(metric="max_unity", op="<=", value=1.0),
            IntentPreservedConstraint(),
            SpatialConstraintsPreservedConstraint(),
        ],
        proposer=proposer,
        budget=ExplorationBudget(max_solves=10, max_generations=3),
        convergence=Convergence(),
        engine=ReferenceEngine(),
        cost_basis=basis,
        timestamp=T0,
    )
    kinds: dict[str, str] = {}
    for candidate in exploration.generations[0].candidates:
        assert candidate.commit is not None
        snapshot = load_snapshot(store, candidate.commit)
        [f] = [d for d in snapshot.decisions.values() if d.kind.endswith("framing_strategy")]
        kinds[candidate.key] = f.kind
    return exploration, kinds


def test_concrete_is_a_candidate_family_in_heterogeneous_exploration(tmp_path: Path) -> None:
    """Note 0006's acceptance: concrete appears as a candidate family alongside
    wood and steel, ranked on the method-neutral mass metric, with no new
    exploration mechanism — every API in this test predates concrete."""
    store = FileStore(tmp_path)
    exploration, kinds = _three_way_exploration(
        store, objectives=[Objective(metric="total_member_mass_kg", direction="min")]
    )
    assert set(kinds.values()) == {
        "gravity_framing_strategy",
        "steel_framing_strategy",
        "concrete_framing_strategy",
    }
    [evaluation] = exploration.evaluations
    assert set(evaluation.per_candidate) == set(kinds)
    # all three solved and evaluated; the ranking is ascending mass
    masses = [
        evaluation.per_candidate[k].metrics["total_member_mass_kg"] for k in evaluation.ranking
    ]
    assert masses == sorted(masses)
    concrete_key = next(k for k, v in kinds.items() if v == "concrete_framing_strategy")
    assert evaluation.per_candidate[concrete_key].feasible  # a real, passing design
    # concrete's mass came through the same engine facts as the others (no
    # fallback-density note — the concrete engine supplied 2400 kg/m3)
    assert "fallback" not in evaluation.notes


def test_one_basis_prices_all_three_families_by_factor_rows(tmp_path: Path) -> None:
    """ADR 0012 held with no cost schema change (note 0006's acceptance): the
    concrete rows — volume $/CY, rebar $/lb (material), formwork $/ft2
    (installation) — are appended factor rows over derived countables. Re-rank
    under a formwork-only basis moves only concrete, with no solve."""
    store = FileStore(tmp_path)
    basis = decision("cost_basis", "regional, all families", cost_basis_params())
    exploration, kinds = _three_way_exploration(
        store, objectives=[Objective(metric="installed_cost_usd", direction="min")], basis=basis
    )
    [priced] = exploration.evaluations
    assert priced.cost_basis == basis.did
    concrete_key = next(k for k, v in kinds.items() if v == "concrete_framing_strategy")
    concrete = priced.per_candidate[concrete_key].metrics
    assert concrete["material_cost_usd"] > 0.0  # volume + rebar rows priced
    assert concrete["installation_cost_usd"] > 0.0  # formwork row priced

    # A formwork-only basis prices concrete alone: wood/steel resolve zero area.
    formwork_only = cost_basis_params().model_copy(
        update={
            "factors": [
                CostFactor(
                    quantity_kind="formwork_area",
                    pricing=DirectPrice(unit_price=usd(8.0, "USD/ft2")),
                    source="forming assumption — illustrative",
                )
            ]
        }
    )
    reranked = evaluate(
        store, exploration, cost_basis=decision("cost_basis", "formwork only", formwork_only)
    )
    assert reranked.result_set == priced.result_set  # same stored physics, no solve
    for key, kind_name in kinds.items():
        cost = reranked.per_candidate[key].metrics["installed_cost_usd"]
        if kind_name == "concrete_framing_strategy":
            assert cost > 0.0
        else:
            assert cost == pytest.approx(0.0)
