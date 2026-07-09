"""Spatial structural constraints: the project-constraint primitive (ADR 0011).

Per the PO reframe (note 0002), a clear-span requirement is not a bespoke
feature — it is one instance of a general class: a **typed predicate over a
spatially-anchored region**, standing independently of the structural system
(which may still be an *open* decision when the constraint is captured), enforced
identically on every ordinary changeset and every exploration candidate.

The kernel fixes the constraint *shape* (``ProjectConstraint`` in ``objects.py``:
a region in the ADR 0005 anchor vocabulary + a predicate name + a payload); the
predicate *meaning* is an open registry here — ``(name, payload schema, check
site, checker)``. Adding ``clear_height_below`` later is one ``register_predicate``
call, zero kernel edits: the same extensibility move that made intent categories
a registry (ADR 0004) and material engines a registry (ADR 0007). That a third,
unplanned predicate drops in as data is the acceptance test that this is a
primitive and not a demo-shaped special case.

Two-site enforcement, the intent posture (ADR 0004): a predicate declares whether
it is decided at **commit** (topology/geometry over the dry-run derived model —
"is any post inside region R?") or at **solve** (demand-dependent — reserved).
Commit-site predicates run in ``propose``'s stage 5; a violation rejects the
changeset citing the constraint, and — since exploration candidates are ordinary
changesets — a candidate that places a support in a protected region dies
pre-solve, exactly the vision's "41 rejected pre-solve, most put a column line in
the protected zone."

A constraint whose region anchor no longer resolves (its grid line was deleted)
goes **inert with a warning**, never a hard error — the override-like posture the
note calls for; the constraint persists until a human resolves it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field, JsonValue

from structural_kernel.decisions import GridParams, parse_params
from structural_kernel.objects import (
    KernelModel,
    OffsetBand,
    ProjectConstraint,
    Region,
    WholePlan,
)
from structural_kernel.units import LengthQuantity

if TYPE_CHECKING:
    from structural_kernel.derivation import DerivedModel, Element
    from structural_kernel.validation import ResolvedSnapshot

_EPS = 1e-6

# Vertical gravity supports: discrete posts/columns and bearing wall segments
# alike. Both predicates range over all three — a bearing wall defines a bay line
# just as a column does (Mark's call). Min-bay counts a support's coordinate on an
# axis only where the support is a *point* on that axis, so a wall contributes the
# line it runs along and not the span it covers.
_VERTICAL_SUPPORTS = ("post", "column", "wall_segment")


# -- results -------------------------------------------------------------------------


class ConstraintViolation(KernelModel):
    """A commit-time predicate rejection — the machine-actionable error shape."""

    code: Literal["constraint_violation"] = "constraint_violation"
    cid: str
    predicate: str
    message: str
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class ConstraintWarning(KernelModel):
    """An inert constraint — an unratified inferred reading (design doc 0005 §5),
    an unknown predicate, or an unresolved region anchor: surfaced as a commit
    warning, never dropped, never a rejection. ``inert_reason`` lets the caller
    distinguish an unratified reading (still inert *by design*) from a broken
    constraint (dangling anchor / unregistered predicate)."""

    cid: str
    predicate: str
    message: str
    inert_reason: Literal["unratified", "dangling_anchor", "unregistered_predicate"]
    detail: dict[str, JsonValue] = Field(default_factory=dict)


# -- predicate payload schemas -------------------------------------------------------


class NoPayload(KernelModel):
    """No parameters beyond the region (e.g. ``no_vertical_support_within``)."""


class MinBaySpacingPayload(KernelModel):
    min_spacing: LengthQuantity


# -- region resolution ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedRegion:
    """A region reduced to open/closed plan intervals per axis. ``None`` bounds =
    unbounded on that axis (an offset band spans the full perpendicular depth; the
    whole plan is unbounded on both)."""

    x_bounds: tuple[float, float] | None
    y_bounds: tuple[float, float] | None

    def footprint_intrudes(self, x0: float, x1: float, y0: float, y1: float) -> bool:
        """Does a plan footprint enter the *open* region? Open on purpose: a
        support exactly on a bounding line — the anchored perimeter, or the far
        line the clear span bears onto — is allowed; only supports interior to the
        protected strip are forbidden (else the span could never be carried)."""
        return self._axis_open(self.x_bounds, x0, x1) and self._axis_open(self.y_bounds, y0, y1)

    def contains_point_closed(self, x: float, y: float) -> bool:
        """Is a point within the *closed* region (boundary included)? Used to
        scope which supports a minimum-bay predicate ranges over."""
        return self._axis_closed(self.x_bounds, x) and self._axis_closed(self.y_bounds, y)

    @staticmethod
    def _axis_open(bounds: tuple[float, float] | None, a: float, b: float) -> bool:
        if bounds is None:
            return True  # unbounded axis: any coordinate overlaps
        lo, hi = bounds
        if b - a < _EPS:  # a point footprint on this axis
            return lo + _EPS < a < hi - _EPS
        return min(b, hi) - max(a, lo) > _EPS  # positive interior overlap

    @staticmethod
    def _axis_closed(bounds: tuple[float, float] | None, v: float) -> bool:
        if bounds is None:
            return True
        lo, hi = bounds
        return lo - _EPS <= v <= hi + _EPS

    def describe(self) -> dict[str, JsonValue]:
        return {
            "x_bounds": list(self.x_bounds) if self.x_bounds else None,
            "y_bounds": list(self.y_bounds) if self.y_bounds else None,
        }


def resolve_region(region: Region, lines: dict[str, tuple[str, float]]) -> ResolvedRegion | None:
    """Resolve a region's ADR 0005 anchors to SI plan intervals. ``None`` when an
    anchor line does not resolve — the caller treats that as an inert constraint."""
    if isinstance(region, WholePlan):
        return ResolvedRegion(x_bounds=None, y_bounds=None)
    if isinstance(region, OffsetBand):
        anchor = lines.get(region.anchor)
        if anchor is None:
            return None
        axis, offset = anchor
        extent = region.extent.si_mag
        lo, hi = (offset - extent, offset) if region.side == "less" else (offset, offset + extent)
        band = (min(lo, hi), max(lo, hi))
        return (
            ResolvedRegion(x_bounds=band, y_bounds=None)
            if axis == "x"
            else ResolvedRegion(x_bounds=None, y_bounds=band)
        )
    # The union is exhausted: region is a GridBoundedRegion.
    try:
        x0 = lines[region.x_from][1]
        x1 = lines[region.x_to][1]
        y0 = lines[region.y_from][1]
        y1 = lines[region.y_to][1]
    except KeyError:
        return None
    return ResolvedRegion(x_bounds=(min(x0, x1), max(x0, x1)), y_bounds=(min(y0, y1), max(y0, y1)))


def _grid_lines(snapshot: ResolvedSnapshot) -> dict[str, tuple[str, float]]:
    """Every grid line in the snapshot: line-id → (axis it holds constant, SI offset)."""
    lines: dict[str, tuple[str, float]] = {}
    for decision in snapshot.decisions.values():
        if decision.kind != "grid":
            continue
        params = parse_params(decision)
        if isinstance(params, GridParams):
            for line in params.lines:
                lines[line.line_id] = (line.axis, line.offset.si_mag)
    return lines


def _footprint(element: Element) -> tuple[float, float, float, float]:
    xs = sorted((element.start.x.si_mag, element.end.x.si_mag))
    ys = sorted((element.start.y.si_mag, element.end.y.si_mag))
    return xs[0], xs[1], ys[0], ys[1]


# -- predicate checkers --------------------------------------------------------------


class PredicateChecker(Protocol):
    def __call__(
        self,
        model: DerivedModel,
        constraint: ProjectConstraint,
        region: ResolvedRegion,
        snapshot: ResolvedSnapshot,
    ) -> list[ConstraintViolation]: ...


def _no_vertical_support_within(
    model: DerivedModel,
    constraint: ProjectConstraint,
    region: ResolvedRegion,
    snapshot: ResolvedSnapshot,
) -> list[ConstraintViolation]:
    """Clear-span (the vision's "west 40 ft column-free"): no vertical support may
    land inside the region. "A column at gridline C.5 west of line 4 gets a
    structured rejection" — enforced against every future changeset, human or AI."""
    intruders = sorted(
        e.eid
        for e in model.elements
        if e.role in _VERTICAL_SUPPORTS and region.footprint_intrudes(*_footprint(e))
    )
    if not intruders:
        return []
    return [
        ConstraintViolation(
            cid=constraint.cid,
            predicate=constraint.predicate,
            message=(
                f"constraint {constraint.cid} ({constraint.statement!r}) forbids vertical "
                f"supports in its region; found: {', '.join(intruders)}"
            ),
            detail={"supports": list[JsonValue](intruders), "region": region.describe()},
        )
    ]


def _min_bay_spacing(
    model: DerivedModel,
    constraint: ProjectConstraint,
    region: ResolvedRegion,
    snapshot: ResolvedSnapshot,
) -> list[ConstraintViolation]:
    """Minimum bay (the vision's "let's not go tighter than 25 foot bays"):
    adjacent support lines along each plan axis must be at least ``min_spacing``
    apart, within the region the constraint scopes. Posts, columns, and bearing
    walls all define bay lines (Mark's call); a support contributes a line on an
    axis only where it is a point on that axis, so a wall counts on the axis it
    runs across and is skipped on the axis it spans."""
    payload = MinBaySpacingPayload.model_validate(constraint.payload)
    minimum = payload.min_spacing.si_mag

    violations: list[ConstraintViolation] = []
    for axis in ("x", "y"):
        coords: set[float] = set()
        for element in model.elements:
            if element.role not in _VERTICAL_SUPPORTS:
                continue
            near = element.start.x.si_mag if axis == "x" else element.start.y.si_mag
            far = element.end.x.si_mag if axis == "x" else element.end.y.si_mag
            if abs(near - far) > _EPS:
                continue  # the support spans this axis (a wall running along it)
            if not region.contains_point_closed(element.start.x.si_mag, element.start.y.si_mag):
                continue
            coords.add(near)
        for lower, upper in itertools.pairwise(sorted(coords)):
            gap = upper - lower
            if gap < minimum - _EPS:
                violations.append(
                    ConstraintViolation(
                        cid=constraint.cid,
                        predicate=constraint.predicate,
                        message=(
                            f"constraint {constraint.cid} ({constraint.statement!r}) requires "
                            f"bays ≥ {minimum:g} m; a {gap:g} m bay along {axis} (between "
                            f"{lower:g} m and {upper:g} m) is tighter"
                        ),
                        detail={
                            "axis": axis,
                            "from_m": lower,
                            "to_m": upper,
                            "gap_m": gap,
                            "min_m": minimum,
                        },
                    )
                )
    return violations


# -- the predicate registry ----------------------------------------------------------


@dataclass(frozen=True)
class PredicateRegistration:
    name: str
    payload_model: type[KernelModel]
    check_site: Literal["commit", "solve"]
    checker: PredicateChecker


PREDICATES: dict[str, PredicateRegistration] = {}


def register_predicate(registration: PredicateRegistration) -> None:
    """Register a predicate kind. This is the whole extension surface: a new
    spatial constraint type — ``clear_height_below``, ``no_transfer_within`` — is
    one call with its payload schema and checker, no kernel edit (note 0002)."""
    PREDICATES[registration.name] = registration


register_predicate(
    PredicateRegistration(
        name="no_vertical_support_within",
        payload_model=NoPayload,
        check_site="commit",
        checker=_no_vertical_support_within,
    )
)
register_predicate(
    PredicateRegistration(
        name="min_bay_spacing",
        payload_model=MinBaySpacingPayload,
        check_site="commit",
        checker=_min_bay_spacing,
    )
)


# -- the enforcement entry point (propose stage 5) -----------------------------------


def check_project_constraints(
    model: DerivedModel, snapshot: ResolvedSnapshot
) -> tuple[list[ConstraintViolation], list[ConstraintWarning]]:
    """Run every commit-site project constraint over the dry-run derived model.
    Returns (violations to reject on, inert-constraint warnings to attach). Pure
    and deterministic — a function of exactly (derived model, snapshot)."""
    lines = _grid_lines(snapshot)
    violations: list[ConstraintViolation] = []
    warnings: list[ConstraintWarning] = []

    for constraint in sorted(snapshot.constraints.values(), key=lambda c: c.cid):
        # Inert by type until ratified (design doc 0005 §5): an inferred, unratified
        # reading can never reject a changeset or make an exploration candidate
        # infeasible. Checked first — an unratified reading does nothing at all,
        # regardless of predicate or region, until an engineer ratifies it.
        if not constraint.provenance.is_binding:
            warnings.append(
                ConstraintWarning(
                    cid=constraint.cid,
                    predicate=constraint.predicate,
                    message=(
                        f"constraint {constraint.cid} ({constraint.statement!r}) is an "
                        "unratified inferred reading; inert until an engineer ratifies it"
                    ),
                    inert_reason="unratified",
                )
            )
            continue
        registration = PREDICATES.get(constraint.predicate)
        if registration is None:
            warnings.append(
                ConstraintWarning(
                    cid=constraint.cid,
                    predicate=constraint.predicate,
                    message=(
                        f"constraint {constraint.cid}: predicate {constraint.predicate!r} is "
                        "no longer registered; constraint inert"
                    ),
                    inert_reason="unregistered_predicate",
                )
            )
            continue
        if registration.check_site != "commit":
            continue  # solve-site predicates enforce in the design-check stage (reserved)
        region = resolve_region(constraint.region, lines)
        if region is None:
            warnings.append(
                ConstraintWarning(
                    cid=constraint.cid,
                    predicate=constraint.predicate,
                    message=(
                        f"constraint {constraint.cid} ({constraint.statement!r}): its region "
                        "anchor no longer resolves; constraint inert (dangling)"
                    ),
                    inert_reason="dangling_anchor",
                )
            )
            continue
        violations += registration.checker(model, constraint, region, snapshot)

    return violations, warnings
