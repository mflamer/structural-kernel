"""Hand-calc verification suite (design doc 0001 §9).

Fixtures with closed-form answers, run through the solver-service interface.
Tolerances per the design doc: 0.5% on displacements, 0.1% on reactions
(moment extrema held to 0.5%). The direct-stiffness fixture engine (ADR 0003)
is the independent second opinion and runs everywhere; the same fixtures run
through the xara adapter wherever its native runtime exists (not Windows, as
of 2026-07), keeping both engines answerable to the same hand calcs.
"""

from __future__ import annotations

import pytest

from conftest import decision, framing_params, grid_params, levels_params
from reference_solver import ReferenceEngine
from structural_kernel.derivation import (
    AnalysisElement,
    AnalysisLineLoad,
    AnalysisModel,
    AnalysisNode,
    AnalysisPointLoad,
    AnalysisSupport,
    Combo,
    DerivationProvenance,
    Releases,
    derive,
)
from structural_kernel.solver import EngineAdapter, LocalSolverService, SolveResult
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash
from structural_kernel.xara_adapter import XaraEngine, xara_available

DISP_RTOL = 0.005  # 0.5 %
REACTION_RTOL = 0.001  # 0.1 %
MOMENT_RTOL = 0.005

E = 1.1e10  # Pa (order of sawn lumber)
A = 0.01  # m2
I = 2e-5  # m4  # noqa: E741 - conventional symbol
L = 4.0  # m
W = -2000.0  # N/m, gravity down
P = -10_000.0  # N, gravity down

Fix6 = tuple[bool, bool, bool, bool, bool, bool]
PIN: Fix6 = (True, True, True, False, False, False)
FIXED: Fix6 = (True, True, True, True, True, True)
_PROV = DerivationProvenance(snapshot="sha256:" + "0" * 64, derivation_version=1)


def _engines() -> list[EngineAdapter]:
    engines: list[EngineAdapter] = [ReferenceEngine()]
    if xara_available():
        engines.append(XaraEngine())
    return engines


def _beam(
    nodes: list[tuple[str, float]],
    elements: list[tuple[str, str, str]],
    supports: list[tuple[str, Fix6]],
    loads: list[AnalysisLineLoad | AnalysisPointLoad],
) -> AnalysisModel:
    return AnalysisModel(
        provenance=_PROV,
        nodes=[AnalysisNode(id=n, xyz_m=(s, 0.0, 0.0)) for n, s in nodes],
        elements=[
            AnalysisElement(
                id=e,
                type="frame",
                nodes=(i, j),
                E_pa=E,
                A_m2=A,
                I_strong_m4=I,
                I_weak_m4=I,
                releases=Releases(start="pin", end="pin"),
                source_eid=f"src:{e}",
            )
            for e, i, j in elements
        ],
        supports=[AnalysisSupport(node=n, fix=f) for n, f in supports],
        loads=list(loads),
        combos=[Combo(name="D", factors={"D": 1.0})],
    )


def _solve(engine: EngineAdapter, artifact: AnalysisModel) -> SolveResult:
    service = LocalSolverService(engine)
    [result] = service.results(service.submit([artifact]))
    assert result.status == "solved", result.failure
    assert result.engine.fidelity == "verification"
    return result


@pytest.mark.parametrize("engine", _engines(), ids=lambda e: e.info.name)
class TestHandCalcFixtures:
    def test_simply_supported_udl(self, engine: EngineAdapter) -> None:
        artifact = _beam(
            nodes=[("n1", 0.0), ("n2", L)],
            elements=[("e1", "n1", "n2")],
            supports=[("n1", PIN), ("n2", PIN)],
            loads=[AnalysisLineLoad(case="D", element="e1", w_n_per_m=(0.0, 0.0, W))],
        )
        [combo] = _solve(engine, artifact).combos
        [member] = combo.members

        delta = 5 * abs(W) * L**4 / (384 * E * I)
        assert member.max_deflection_m == pytest.approx(delta, rel=DISP_RTOL)
        assert member.max_abs_moment_nm == pytest.approx(abs(W) * L**2 / 8, rel=MOMENT_RTOL)
        assert member.max_abs_shear_n == pytest.approx(abs(W) * L / 2, rel=MOMENT_RTOL)
        for reaction in combo.reactions:
            assert reaction.f_n[2] == pytest.approx(abs(W) * L / 2, rel=REACTION_RTOL)

    def test_midspan_point_load(self, engine: EngineAdapter) -> None:
        artifact = _beam(
            nodes=[("n1", 0.0), ("n2", L)],
            elements=[("e1", "n1", "n2")],
            supports=[("n1", PIN), ("n2", PIN)],
            loads=[AnalysisPointLoad(case="D", element="e1", position=0.5, p_n=(0.0, 0.0, P))],
        )
        [combo] = _solve(engine, artifact).combos
        [member] = combo.members

        assert member.max_deflection_m == pytest.approx(abs(P) * L**3 / (48 * E * I), rel=DISP_RTOL)
        assert member.max_abs_moment_nm == pytest.approx(abs(P) * L / 4, rel=MOMENT_RTOL)
        for reaction in combo.reactions:
            assert reaction.f_n[2] == pytest.approx(abs(P) / 2, rel=REACTION_RTOL)

    def test_two_span_continuous_udl(self, engine: EngineAdapter) -> None:
        artifact = _beam(
            nodes=[("n1", 0.0), ("n2", L), ("n3", 2 * L)],
            elements=[("e1", "n1", "n2"), ("e2", "n2", "n3")],
            supports=[("n1", PIN), ("n2", PIN), ("n3", PIN)],
            loads=[
                AnalysisLineLoad(case="D", element="e1", w_n_per_m=(0.0, 0.0, W)),
                AnalysisLineLoad(case="D", element="e2", w_n_per_m=(0.0, 0.0, W)),
            ],
        )
        [combo] = _solve(engine, artifact).combos
        reactions = {r.node: r.f_n[2] for r in combo.reactions}

        assert reactions["n1"] == pytest.approx(3 * abs(W) * L / 8, rel=REACTION_RTOL)
        assert reactions["n3"] == pytest.approx(3 * abs(W) * L / 8, rel=REACTION_RTOL)
        assert reactions["n2"] == pytest.approx(10 * abs(W) * L / 8, rel=REACTION_RTOL)

        by_element = {m.element: m for m in combo.members}
        support_moment = abs(W) * L**2 / 8  # hogging at the center support
        assert by_element["e1"].max_abs_moment_nm == pytest.approx(support_moment, rel=MOMENT_RTOL)
        # peak span deflection of the equivalent propped cantilever
        delta_max = 0.0054161 * abs(W) * L**4 / (E * I)
        assert by_element["e1"].max_deflection_m == pytest.approx(delta_max, rel=DISP_RTOL)

    def test_cantilever_tip_load(self, engine: EngineAdapter) -> None:
        artifact = _beam(
            nodes=[("n1", 0.0), ("n2", L)],
            elements=[("e1", "n1", "n2")],
            supports=[("n1", FIXED)],
            loads=[AnalysisPointLoad(case="D", element="e1", position=1.0, p_n=(0.0, 0.0, P))],
        )
        [combo] = _solve(engine, artifact).combos
        [member] = combo.members

        assert member.max_deflection_m == pytest.approx(abs(P) * L**3 / (3 * E * I), rel=DISP_RTOL)
        assert member.max_abs_moment_nm == pytest.approx(abs(P) * L, rel=MOMENT_RTOL)
        [reaction] = combo.reactions
        assert reaction.f_n[2] == pytest.approx(abs(P), rel=REACTION_RTOL)
        assert abs(reaction.m_nm[1]) == pytest.approx(abs(P) * L, rel=MOMENT_RTOL)


def test_unsupported_beam_is_a_structured_failure_not_an_exception() -> None:
    artifact = _beam(
        nodes=[("n1", 0.0), ("n2", L)],
        elements=[("e1", "n1", "n2")],
        supports=[],  # a mechanism
        loads=[AnalysisLineLoad(case="D", element="e1", w_n_per_m=(0.0, 0.0, W))],
    )
    service = LocalSolverService(ReferenceEngine())
    job = service.submit([artifact])
    [result] = service.results(job)
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.code == "singular_system"
    assert service.status(job).per_artifact[result.artifact] == "failed"


def test_batch_dispatch_is_one_call() -> None:
    artifacts = [
        _beam(
            nodes=[("n1", 0.0), ("n2", length)],
            elements=[("e1", "n1", "n2")],
            supports=[("n1", PIN), ("n2", PIN)],
            loads=[AnalysisLineLoad(case="D", element="e1", w_n_per_m=(0.0, 0.0, W))],
        )
        for length in (3.0, 4.0, 5.0)
    ]
    service = LocalSolverService(ReferenceEngine())
    results = service.results(service.submit(artifacts))
    assert [r.status for r in results] == ["solved"] * 3
    assert len({r.artifact for r in results}) == 3  # keyed by artifact hash


def test_derived_milestone_artifact_solves_and_matches_hand_calc() -> None:
    """End-to-end: the derivation increment's artifact, through the service,
    against the simple-span hand calc — the schema mapping is the thing
    actually under test."""
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision(
        "load_assumptions",
        "Loads",
        {
            "area_loads": [{"case": "D", "magnitude": {"mag": 15.0, "unit": "psf"}}],
            "combo_set": "ASCE7-22-2.4-ASD",
        },
    )
    framing = decision(
        "gravity_framing_strategy",
        "F",
        framing_params(),
        deps=[grid.did, levels.did, loads.did],
    )
    snapshot = ResolvedSnapshot(decisions={d.did: d for d in (grid, levels, loads, framing)})
    model = derive(snapshot, snapshot_hash=resolved_snapshot_hash(snapshot))
    assert model.analysis is not None

    service = LocalSolverService(ReferenceEngine())
    [result] = service.results(service.submit([model.analysis]))
    assert result.status == "solved", result.failure

    [combo] = [c for c in result.combos if c.combo == "D"]
    interior = next(e for e in model.elements if e.role == "joist" and e.eid.endswith("+001"))
    member = next(m for m in combo.members if m.source_eid == interior.eid)

    psf = 4.4482216152605 / 0.3048**2
    w = 15.0 * psf * interior.tributary_width.si_mag  # type: ignore[union-attr]
    span = interior.length.si_mag
    section_e = 1.6e6 * (4.4482216152605 / 0.0254**2)
    b, d = 1.5 * 0.0254, 9.25 * 0.0254  # dressed 2x10
    i_strong = b * d**3 / 12
    expected_delta = 5 * w * span**4 / (384 * section_e * i_strong)
    assert member.max_deflection_m == pytest.approx(expected_delta, rel=DISP_RTOL)
    assert member.max_abs_moment_nm == pytest.approx(w * span**2 / 8, rel=MOMENT_RTOL)
