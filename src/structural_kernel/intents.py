"""Structural intent: the open category registry and commit-time checkers (ADR 0004).

The kernel fixes intent *shape*; categories are registrations —
``(name, payload schema, relation roles, checker)`` — living here. Adding
``vibration`` later is a new registration, zero kernel edits: that is the
charter's extensibility test.

Checker purity contract (review R2): a checker is a pure function of exactly
``(derived model, intent instance, carrier, proposed snapshot)`` — no clock,
filesystem, environment, or network. Property-tested like derivation
determinism.

Two-site enforcement (ADR 0004): checkers here decide only what the dry-run
derived model and snapshot can decide — topology, load-path connectivity,
referential shape. Demand-dependent limits (unity, deflection) are solve-time
design checks (``design_checks.py``), which cite the same intent instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field, JsonValue

from structural_kernel.decisions import GridParams, OpeningParams, parse_params
from structural_kernel.objects import (
    Decision,
    DecisionTarget,
    EidTarget,
    IntentInstance,
    KernelModel,
)

if TYPE_CHECKING:
    from structural_kernel.derivation import DerivedModel, Element
    from structural_kernel.validation import ResolvedSnapshot

_EPS = 1e-6


class IntentViolation(KernelModel):
    """The machine-actionable error shape from design doc 0001 §6."""

    code: Literal["intent_violation"] = "intent_violation"
    category: str
    carrier: str  # eid or did the intent instance lives on
    violated: str  # the relation role (or invariant) that broke
    message: str
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class Checker(Protocol):
    def __call__(
        self,
        model: DerivedModel,
        instance: IntentInstance,
        carrier: str,
        snapshot: ResolvedSnapshot,
    ) -> list[IntentViolation]: ...


# -- category payload schemas -------------------------------------------------------


class GravityLoadPathPayload(KernelModel):
    redirects_around: str | None = None  # did of the interrupting decision


class LateralCapacityPayload(KernelModel):
    pass


class ServiceabilityPayload(KernelModel):
    live: str = "L/360"
    total: str = "L/240"


class RetrofitRationalePayload(KernelModel):
    narrative: str | None = None


# -- checkers ------------------------------------------------------------------------


def _no_violations(
    model: DerivedModel,
    instance: IntentInstance,
    carrier: str,
    snapshot: ResolvedSnapshot,
) -> list[IntentViolation]:
    """Shape-only category: envelope and referential integrity say everything
    decidable at commit time (serviceability's semantics are solve-time)."""
    return []


def _check_gravity_support_chain(
    model: DerivedModel,
    instance: IntentInstance,
    carrier: str,
    snapshot: ResolvedSnapshot,
) -> list[IntentViolation]:
    """The element carrying gravity intent must reach ground through the
    load-path graph: every terminal in its support chain is a post, a wall
    segment, or sits at grade."""
    elements = {e.eid: e for e in model.elements}
    start = elements.get(carrier)
    if start is None:
        return []  # authored intent on a decision; nothing to walk

    seen: set[str] = set()
    frontier = [start]
    while frontier:
        element = frontier.pop()
        if element.eid in seen:
            continue
        seen.add(element.eid)
        if not element.supports:
            if not _grounded(element):
                return [
                    IntentViolation(
                        category=instance.category,
                        carrier=carrier,
                        violated="carries",
                        message=(
                            f"{carrier} carries gravity load but its load path "
                            f"terminates at {element.eid}, which does not reach ground"
                        ),
                        detail={
                            "terminates_at": element.eid,
                            "path_seen": list[JsonValue](sorted(seen)),
                        },
                    )
                ]
            continue
        frontier.extend(elements[s] for s in element.supports if s in elements)
    return []


def _grounded(element: Element) -> bool:
    if element.role in ("post", "wall_segment"):
        return True
    return abs(element.start.z.si_mag) < _EPS and abs(element.end.z.si_mag) < _EPS


def check_intent(model: DerivedModel, snapshot: ResolvedSnapshot) -> list[IntentViolation]:
    """Validation stage 4: run every registered checker over the dry-run
    derived model, plus the global invariants (eid-target resolution and
    opening interruption)."""
    violations: list[IntentViolation] = []

    for element in model.elements:
        for instance in element.intent:
            registration = REGISTRY.get(instance.category)
            if registration is not None:
                violations += registration.checker(model, instance, element.eid, snapshot)
    for decision in snapshot.decisions.values():
        for instance in decision.intent:
            registration = REGISTRY.get(instance.category)
            if registration is not None:
                violations += registration.checker(model, instance, decision.did, snapshot)

    violations += _check_authored_eid_targets(model, snapshot)
    violations += _check_opening_interruption(model, snapshot)
    return violations


def _check_authored_eid_targets(
    model: DerivedModel, snapshot: ResolvedSnapshot
) -> list[IntentViolation]:
    """Authored intent may pin derived elements by eid; stage 2 cannot resolve
    those (eids exist only after derivation) — this is where they resolve."""
    eids = {e.eid for e in model.elements}
    violations: list[IntentViolation] = []
    for decision in snapshot.decisions.values():
        for instance in decision.intent:
            for relation in instance.relations:
                if isinstance(relation.target, EidTarget) and relation.target.eid not in eids:
                    violations.append(
                        IntentViolation(
                            category=instance.category,
                            carrier=decision.did,
                            violated=relation.role,
                            message=(
                                f"intent on {decision.did} targets {relation.target.eid}, "
                                "which the proposed model does not derive"
                            ),
                            detail={"eid": relation.target.eid},
                        )
                    )
    return violations


def _check_opening_interruption(
    model: DerivedModel, snapshot: ResolvedSnapshot
) -> list[IntentViolation]:
    """The charter's signature case: an opening in a load-bearing wall must
    have its gravity load path redirected — joists bearing on the wall inside
    the opening's extent must route through a header whose intent redirects
    around that opening. 'Deleting the header while the opening remains' is
    exactly a proposal that leaves this invariant broken."""
    violations: list[IntentViolation] = []
    elements = {e.eid: e for e in model.elements}

    for decision in snapshot.decisions.values():
        if decision.kind != "opening" or decision.state != "resolved":
            continue
        params = parse_params(decision)
        assert isinstance(params, OpeningParams)
        lines = _grid_lines_in_deps(decision, snapshot.decisions)
        if params.wall_line not in lines or params.offset_from not in lines:
            continue  # unresolvable refs are stage-2 territory
        wall_axis, wall_offset = lines[params.wall_line]
        start_m = lines[params.offset_from][1] + params.offset.si_mag
        end_m = start_m + params.width.si_mag

        bearing_eids = {
            e.eid
            for e in model.elements
            if e.role in ("beam", "wall_segment") and _lies_on(e, wall_axis, wall_offset)
        }
        if not bearing_eids:
            continue  # nothing bears on this wall; no path to interrupt

        broken: list[str] = []
        for element in model.elements:
            if element.role != "joist" or not (set(element.supports) & bearing_eids):
                continue
            position = element.start.x.si_mag if wall_axis == "y" else element.start.y.si_mag
            if not (start_m - _EPS <= position <= end_m + _EPS):
                continue
            redirected = any(
                _redirects_around(elements[s], decision.did)
                for s in element.supports
                if s in elements
            )
            if not redirected:
                broken.append(element.eid)

        if broken:
            violations.append(
                IntentViolation(
                    category="gravity_load_path",
                    carrier=decision.did,
                    violated="redirects_load_around",
                    message=(
                        f"opening {decision.did} ({decision.title}) interrupts a bearing "
                        f"line, and no header redirects the gravity load path around it: "
                        f"joists {', '.join(broken)} bear inside the opening"
                    ),
                    detail={
                        "opening": decision.did,
                        "broken_path": [*broken, "∅", *sorted(bearing_eids)],
                    },
                )
            )
    return violations


def _redirects_around(element: Element, opening_did: str) -> bool:
    return element.role == "header" and any(
        relation.role == "redirects_load_around"
        and isinstance(relation.target, DecisionTarget)
        and relation.target.decision == opening_did
        for instance in element.intent
        for relation in instance.relations
    )


def _lies_on(element: Element, axis: str, offset: float) -> bool:
    start = element.start.x.si_mag if axis == "x" else element.start.y.si_mag
    end = element.end.x.si_mag if axis == "x" else element.end.y.si_mag
    return abs(start - offset) < _EPS and abs(end - offset) < _EPS


def _grid_lines_in_deps(
    decision: Decision, decisions: dict[str, Decision]
) -> dict[str, tuple[str, float]]:
    lines: dict[str, tuple[str, float]] = {}
    for dep in decision.deps:
        dep_decision = decisions.get(dep)
        if dep_decision is None or dep_decision.kind != "grid":
            continue
        params = parse_params(dep_decision)
        if isinstance(params, GridParams):
            for line in params.lines:
                lines[line.line_id] = (line.axis, line.offset.si_mag)
    return lines


# -- the registry ---------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryRegistration:
    name: str
    payload_model: type[KernelModel]
    relation_roles: frozenset[str]
    checker: Checker


REGISTRY: dict[str, CategoryRegistration] = {
    registration.name: registration
    for registration in (
        CategoryRegistration(
            name="gravity_load_path",
            payload_model=GravityLoadPathPayload,
            relation_roles=frozenset({"carries", "redirects_load_around", "governed_by"}),
            checker=_check_gravity_support_chain,
        ),
        CategoryRegistration(
            name="lateral_capacity",
            payload_model=LateralCapacityPayload,
            relation_roles=frozenset({"governed_by"}),
            checker=_no_violations,
        ),
        CategoryRegistration(
            name="serviceability",
            payload_model=ServiceabilityPayload,
            relation_roles=frozenset({"governed_by"}),
            checker=_no_violations,  # semantics are solve-time (design_checks.py)
        ),
        CategoryRegistration(
            name="retrofit_rationale",
            payload_model=RetrofitRationalePayload,
            relation_roles=frozenset({"governed_by", "carries"}),
            checker=_no_violations,
        ),
    )
}
