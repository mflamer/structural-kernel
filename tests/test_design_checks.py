"""Solve-time design checks: NDS strength via ndswood, kernel-side deflection,
provision citations, and the intent linkage (ADR 0004 site b)."""

import pytest

from conftest import (
    decision,
    framing_params,
    grid_params,
    levels_params,
    loads_params,
)
from reference_solver import ReferenceEngine
from structural_kernel.derivation import DerivedModel, derive
from structural_kernel.design_checks import DesignCheckReport, run_design_checks
from structural_kernel.solver import LocalSolverService, SolveResult
from structural_kernel.validation import ResolvedSnapshot, resolved_snapshot_hash

_PSF = 4.4482216152605 / 0.3048**2
_PSI = 4.4482216152605 / 0.0254**2


def _solved_milestone() -> tuple[DerivedModel, SolveResult]:
    grid = decision("grid", "Grid", grid_params())
    levels = decision("levels", "Levels", levels_params())
    loads = decision("load_assumptions", "Loads", loads_params())
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
    assert result.status == "solved"
    return model, result


@pytest.fixture(scope="module")
def report_and_model() -> tuple[DesignCheckReport, DerivedModel]:
    model, result = _solved_milestone()
    return run_design_checks(model, result), model


def test_joist_bending_matches_the_hand_calc(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    report, model = report_and_model
    interior = next(e for e in model.elements if e.role == "joist" and e.eid.endswith("+001"))
    [check] = [
        c
        for c in report.checks
        if c.eid == interior.eid and c.check == "bending" and c.combo == "D+L"
    ]
    # fb = M / S: w = 55 psf x 16 in tributary over the 14 ft span, S(2x10) = 21.39 in^3
    w = 55.0 * _PSF * (16.0 * 0.0254)  # N/m
    span = interior.length.si_mag
    moment = w * span**2 / 8
    s_m3 = (1.5 * 0.0254) * (9.25 * 0.0254) ** 2 / 6
    expected_fb_pa = moment / s_m3
    assert check.demand.mag == pytest.approx(expected_fb_pa, rel=0.01)
    assert check.unity == pytest.approx(check.demand.mag / check.capacity.mag, rel=1e-9)
    assert check.passes  # 2x10 @ 16" over 14 ft works in bending


def test_strength_checks_cite_nds_provisions_and_factors(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    report, _ = report_and_model
    bending = [c for c in report.checks if c.check == "bending"]
    assert bending
    for check in bending:
        assert check.provision.startswith("NDS")
        symbols = {f.symbol for f in check.factors}
        assert "CD" in symbols and "CF" in symbols
        for factor in check.factors:
            assert factor.ref  # every factor carries its NDS reference
    # repetitive-member factor applies to joists (spacing <= 24 in, sheathed)
    joist_check = next(c for c in bending if c.eid.startswith("jst:"))
    cr = next((f for f in joist_check.factors if f.symbol == "Cr"), None)
    assert cr is not None and cr.value == pytest.approx(1.15)


def test_deflection_checks_enforce_the_serviceability_intent(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    report, model = report_and_model
    interior = next(e for e in model.elements if e.role == "joist" and e.eid.endswith("+001"))
    [live] = [c for c in report.checks if c.eid == interior.eid and c.check == "deflection_live"]
    [total] = [c for c in report.checks if c.eid == interior.eid and c.check == "deflection_total"]

    span = interior.length.si_mag
    e_pa = 1.6e6 * _PSI
    i_m4 = (1.5 * 0.0254) * (9.25 * 0.0254) ** 3 / 12
    w_live = 40.0 * _PSF * (16.0 * 0.0254)
    expected_live = 5 * w_live * span**4 / (384 * e_pa * i_m4)
    assert live.demand.mag == pytest.approx(expected_live, rel=0.01)
    assert live.capacity.mag == pytest.approx(span / 360)
    assert total.capacity.mag == pytest.approx(span / 240)
    assert live.passes and total.passes

    # ADR 0004: the deflection check cites the serviceability intent it enforces
    assert live.enforces.category == "serviceability"
    assert live.enforces.carrier == interior.eid
    assert "1604.3" in live.provision


def test_strength_checks_cite_the_gravity_intent(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    report, _ = report_and_model
    for check in report.checks:
        if check.check in ("bending", "shear", "compression"):
            assert check.enforces.category == "gravity_load_path"
            assert check.enforces.carrier == check.eid


def test_posts_get_compression_checks_from_bearing_reactions(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    report, model = report_and_model
    posts = [e.eid for e in model.elements if e.role == "post"]
    compression = [c for c in report.checks if c.check == "compression"]
    assert {c.eid for c in compression} == set(posts)
    # corner post carries one beam end: P = 55 psf x 7 ft x 12 ft under D+L
    [check] = [c for c in compression if c.eid == min(posts) and c.combo == "D+L"]
    p_expected_n = 55.0 * _PSF * (7 * 0.3048) * (12 * 0.3048)
    area_m2 = (3.5 * 0.0254) ** 2
    assert check.demand.mag == pytest.approx(p_expected_n / area_m2, rel=0.01)


def test_the_milestone_beam_honestly_fails_bending(
    report_and_model: tuple[DesignCheckReport, DerivedModel],
) -> None:
    """A 4x12 spanning 24 ft with 7 ft of tributary is not a real design —
    the checks must say so, because explorations will rank around it."""
    report, _ = report_and_model
    beam_bending = [
        c
        for c in report.checks
        if c.eid.startswith("bm:") and c.check == "bending" and c.combo == "D+L"
    ]
    assert beam_bending and all(not c.passes for c in beam_bending)
    assert not report.all_pass
    assert report.max_unity > 1.0


def test_screening_grade_results_are_refused() -> None:
    model, result = _solved_milestone()
    screening = result.model_copy(
        update={"engine": result.engine.model_copy(update={"fidelity": "screening"})}
    )
    with pytest.raises(ValueError, match="verification-grade"):
        run_design_checks(model, screening)
