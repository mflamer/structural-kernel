"""Solve-time design checks (ADR 0004, enforcement site b).

Demand-dependent limits verified over ``SolveResult``s: NDS 2024 ASD strength
(bending, shear, post compression — through the ndswood adapter, ADR 0006)
and the phase-1 deflection limits (L/360 live, L/240 total, review Q3).

Every check cites the provision it applies (from ndswood's factor audit
trail) *and* the intent instance it enforces — that linkage is what makes the
``serviceability`` category real rather than a placeholder, and it is how a
failed check traces back to design meaning in the audit trail.

These checks are hard exploration constraints; they never run inside
commit-time validation (no solve exists there — the two-site split).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from structural_kernel.materials import (
    AxialRequest,
    FlexureRequest,
    ReinforcementData,
    engine_for,
)
from structural_kernel.objects import Eid, KernelModel
from structural_kernel.solver import EngineInfo, MemberForces, SolveResult
from structural_kernel.units import CANONICAL_SI, Quantity

if TYPE_CHECKING:
    from structural_kernel.derivation import DerivedModel, Element

_EPS = 1e-6

CheckKind = Literal[
    "bending", "shear", "compression", "tension", "deflection_live", "deflection_total"
]

_DEFLECTION_PROVISION = "IBC Table 1604.3 (L/360 live, L/240 total)"
_LIVE_DENOMINATOR = 360.0
_TOTAL_DENOMINATOR = 240.0


def _demand_purpose(design_method: str) -> str:
    """The load-combination purpose a member's strength checks demand. ASD is an
    allowable-stress method run on service-level loads; LRFD sizes on factored
    strength combos (ADR 0008)."""
    return "service" if design_method == "ASD" else "strength"


class ProvisionFactor(KernelModel):
    symbol: str
    value: float
    ref: str
    note: str = ""


class IntentRef(KernelModel):
    """The intent instance a check enforces (ADR 0004: both sites cite)."""

    carrier: Eid
    category: str


class DesignCheck(KernelModel):
    eid: Eid
    combo: str
    check: CheckKind
    demand: Quantity
    capacity: Quantity
    unity: float
    passes: bool
    provision: str
    factors: list[ProvisionFactor] = Field(default_factory=list[ProvisionFactor])
    enforces: IntentRef


class DesignCheckReport(KernelModel):
    schema_version: Literal[1] = 1
    snapshot: str
    artifact: str
    engine: EngineInfo
    checks: list[DesignCheck]
    max_unity: float
    all_pass: bool


def run_design_checks(model: DerivedModel, result: SolveResult) -> DesignCheckReport:
    """Check every member of the derived model against the solve result.

    Only verification-grade results may feed design checks (ADR 0003 /
    standing requirement 9) — enforced here, not left to callers.
    """
    if result.status != "solved":
        raise ValueError(f"cannot run design checks on a {result.status} solve")
    if result.engine.fidelity != "verification":
        raise ValueError(
            f"design checks require verification-grade results; got "
            f"{result.engine.fidelity!r} from {result.engine.name!r}"
        )
    if model.analysis is None:
        raise ValueError("the derived model has no analysis artifact to check against")

    combo_cases = {c.name: set(c.factors) for c in model.analysis.combos}
    combo_purpose = {c.name: c.purpose for c in model.analysis.combos}
    checks: list[DesignCheck] = []

    for combo_result in result.combos:
        cases = frozenset(combo_cases.get(combo_result.combo, set()))
        forces_by_eid = {m.source_eid: m for m in combo_result.members}
        for element in model.elements:
            if element.grade is None:
                continue
            # Strength checks consume the demand combos of the member's method:
            # ASD sizes on service-level combos, LRFD on factored strength combos
            # (ADR 0008). Deflection is a separate, always-service check below.
            if combo_purpose.get(combo_result.combo) != _demand_purpose(element.design_method):
                continue
            forces = forces_by_eid.get(element.eid)
            if forces is not None:
                checks += _strength_checks(element, combo_result.combo, cases, forces)

    checks += _deflection_checks(model, result, combo_purpose)
    checks += _post_checks(model, result, combo_cases, combo_purpose)

    checks.sort(key=lambda c: (c.eid, c.combo, c.check))
    max_unity = max((c.unity for c in checks), default=0.0)
    return DesignCheckReport(
        snapshot=model.provenance.snapshot,
        artifact=result.artifact,
        engine=result.engine,
        checks=checks,
        max_unity=max_unity,
        all_pass=all(c.passes for c in checks),
    )


def _reinforcement(element: Element) -> ReinforcementData | None:
    """A dimensioned member's reinforcement, mapped from the persisted element
    vocabulary to the engine request vocabulary (ADR 0014). Catalog members
    carry None and their engines ignore the field — no family dispatch here."""
    spec = element.reinforcement
    if spec is None:
        return None
    return ReinforcementData(
        bars=spec.bars,
        bar=spec.bar,
        cover_m=spec.cover.si_mag,
        grade=spec.grade,
        stirrup_bar=spec.stirrup_bar,
        stirrup_spacing_m=(None if spec.stirrup_spacing is None else spec.stirrup_spacing.si_mag),
        transverse=spec.transverse,
    )


def _strength_checks(
    element: Element, combo: str, cases: frozenset[str], forces: MemberForces
) -> list[DesignCheck]:
    assert element.grade is not None
    results = engine_for(element.family).check_flexure(
        FlexureRequest(
            designation=element.section,
            grade=element.grade,
            moment_nm=forces.max_abs_moment_nm,
            shear_n=forces.max_abs_shear_n,
            span_m=element.length.si_mag,
            method=element.design_method,
            load_cases=cases,
            repetitive=element.role == "joist",
            reinforcement=_reinforcement(element),
        )
    )
    return [_design_check(element, combo, data, "gravity_load_path") for data in results]


def _design_check(element: Element, combo: str, data: object, category: str) -> DesignCheck:
    from structural_kernel.materials import MemberCheckData

    assert isinstance(data, MemberCheckData)
    unit = CANONICAL_SI[data.dimension]
    return DesignCheck(
        eid=element.eid,
        combo=combo,
        check=data.check,  # type: ignore[arg-type]
        demand=Quantity(mag=data.demand, unit=unit),
        capacity=Quantity(mag=data.capacity, unit=unit),
        unity=data.unity,
        passes=data.passes,
        provision=data.provision,
        factors=[
            ProvisionFactor(symbol=f.symbol, value=f.value, ref=f.ref, note=f.note)
            for f in data.factors
        ],
        enforces=_intent_ref(element, category),
    )


def _deflection_checks(
    model: DerivedModel, result: SolveResult, combo_purpose: dict[str, str]
) -> list[DesignCheck]:
    """L/360 live and L/240 total. Serviceability is a load-level check, so it
    runs on the *service* (unfactored) combos regardless of the member-design
    method — under LRFD the factored strength combos would overstate deflection
    (ADR 0008). Live deflection is the total-combo deflection minus the dead-only
    deflection (linear superposition)."""
    by_combo: dict[str, dict[str, float]] = {
        c.combo: {m.source_eid: m.max_deflection_m for m in c.members}
        for c in result.combos
        if combo_purpose.get(c.combo) == "service"
    }
    dead = by_combo.get("D", {})
    checks: list[DesignCheck] = []

    for element in model.elements:
        if element.grade is None:
            continue
        span = element.length.si_mag
        total_defl = max((combo.get(element.eid, 0.0) for combo in by_combo.values()), default=0.0)
        governing_combo = next(
            (
                name
                for name, combo in by_combo.items()
                if abs(combo.get(element.eid, 0.0) - total_defl) < 1e-12
            ),
            "D",
        )
        if element.eid not in by_combo.get(governing_combo, {}):
            continue
        live_defl = max(0.0, total_defl - dead.get(element.eid, 0.0))

        for kind, deflection, denominator in (
            ("deflection_live", live_defl, _LIVE_DENOMINATOR),
            ("deflection_total", total_defl, _TOTAL_DENOMINATOR),
        ):
            limit = span / denominator
            checks.append(
                DesignCheck(
                    eid=element.eid,
                    combo=governing_combo,
                    check=kind,  # type: ignore[arg-type]
                    demand=Quantity(mag=deflection, unit="m"),
                    capacity=Quantity(mag=limit, unit="m"),
                    unity=deflection / limit if limit > 0 else 0.0,
                    passes=deflection <= limit + _EPS,
                    provision=_DEFLECTION_PROVISION,
                    enforces=_intent_ref(element, "serviceability"),
                )
            )
    return checks


def _post_checks(
    model: DerivedModel,
    result: SolveResult,
    combo_cases: dict[str, set[str]],
    combo_purpose: dict[str, str],
) -> list[DesignCheck]:
    """Axial checks for the vertical members — wood posts and steel columns.
    Their demands come from the reactions of the members the load-path graph
    says bear on them — not everything near them, or the corner joist (already
    smeared into the beam's tributary) would double-count."""
    assert model.analysis is not None
    node_xyz = {n.id: n.xyz_m for n in model.analysis.nodes}
    nodes_by_source = {e.source_eid: e.nodes for e in model.analysis.elements}
    checks: list[DesignCheck] = []

    for element in model.elements:
        if element.role not in ("post", "column") or element.grade is None:
            continue
        top = (element.end.x.si_mag, element.end.y.si_mag, element.end.z.si_mag)
        length = element.length.si_mag
        bearing_nodes = {
            node
            for carried in model.elements
            if element.eid in carried.supports
            for node in nodes_by_source.get(carried.eid, ())
            if node in node_xyz and _close(node_xyz[node], top)
        }
        for combo_result in result.combos:
            if combo_purpose.get(combo_result.combo) != _demand_purpose(element.design_method):
                continue
            axial = -sum(
                reaction.f_n[2]
                for reaction in combo_result.reactions
                if reaction.node in bearing_nodes
            )
            axial = abs(axial)
            if axial < _EPS:
                continue
            data = engine_for(element.family).check_axial(
                AxialRequest(
                    designation=element.section,
                    grade=element.grade,
                    force_n=axial,
                    sense="compression",
                    unbraced_length_m=length,
                    method=element.design_method,
                    load_cases=frozenset(combo_cases.get(combo_result.combo, set())),
                    reinforcement=_reinforcement(element),
                )
            )
            checks.append(_design_check(element, combo_result.combo, data, "gravity_load_path"))
    return checks


def _close(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(a[i] - b[i]) < 1e-6 for i in range(3))


def _intent_ref(element: Element, category: str) -> IntentRef:
    if any(instance.category == category for instance in element.intent):
        return IntentRef(carrier=element.eid, category=category)
    # every checked member carries its intent; a miss is a derivation bug
    raise AssertionError(f"{element.eid} carries no {category} intent to cite")
