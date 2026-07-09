"""Changeset validation: staged, fail-fast per stage, collecting within one
(design doc 0001 §6).

Increment 2 implements stage 1 (schema) and stage 2 (referential). Stages 3
(derivation dry-run) and 4 (intent checks) are explicit seams that arrive with
derivation and the intent registry — override and exception dangling live
there too, since dangling is defined against a derived model's eids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pydantic
from pydantic import Field, JsonValue

from structural_kernel.canonical import content_hash, model_document
from structural_kernel.decisions import GridParams, line_refs, parse_params
from structural_kernel.ids import ObjectHash
from structural_kernel.objects import (
    AddConstraint,
    AddDecision,
    AddOverride,
    AddReferencedGeometry,
    Changeset,
    Decision,
    DecisionTarget,
    InferredConstraintProvenance,
    KernelModel,
    LoadTarget,
    ModifyDecision,
    Override,
    OverrideSet,
    ProjectConstraint,
    RatificationRecord,
    RatifyConstraint,
    ReferencedGeometry,
    ReissueReferencedGeometry,
    RemoveConstraint,
    RemoveDecision,
    RemoveOverride,
    Snapshot,
)

IssueCode = Literal[
    "schema_invalid",
    "duplicate_decision",
    "unknown_decision",
    "duplicate_override",
    "unknown_override",
    "duplicate_constraint",
    "unknown_constraint",
    "constraint_not_ratifiable",
    "duplicate_referenced_geometry",
    "unknown_referenced_geometry",
    "stale_referenced_version",
    "referenced_reissue",
    "missing_dep",
    "dependency_cycle",
    "unknown_line_ref",
    "unknown_load_ref",
    "unknown_decision_ref",
    "unknown_intent_category",
    "unknown_predicate",
    "intent_violation",
    "constraint_violation",
    "constraint_inert",
    "constraint_unratified",
    "derivation_failure",
    "dangling_exception",
    "dangling_override",
    "displaced_override",
    "stale_base",
]


class ValidationIssue(KernelModel):
    code: IssueCode
    severity: Literal["error", "warning"]
    message: str
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class ValidationReport(KernelModel):
    """Persisted alongside every changeset — the audit record of what was
    attempted and how validation judged it."""

    schema_version: Literal[1] = 1
    changeset: ObjectHash
    outcome: Literal["committed", "rejected"]
    issues: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])


@dataclass
class ResolvedSnapshot:
    """A snapshot with its decision payloads in hand — the runtime working set."""

    decisions: dict[str, Decision] = field(default_factory=dict[str, Decision])
    constraints: dict[str, ProjectConstraint] = field(default_factory=dict[str, ProjectConstraint])
    referenced_geometry: dict[str, ReferencedGeometry] = field(
        default_factory=dict[str, ReferencedGeometry]
    )
    overrides: OverrideSet = field(default_factory=OverrideSet)


def _error(code: IssueCode, message: str, **detail: JsonValue) -> ValidationIssue:
    return ValidationIssue(code=code, severity="error", message=message, detail=dict(detail))


# -- stage 1: schema -------------------------------------------------------------


def check_schema(changeset: Changeset) -> list[ValidationIssue]:
    """Every decision payload validates against its kind's param schema, units
    dimensionally correct (the envelope itself was validated at construction).
    Authored intent validates against the category registry: registered
    category, payload schema, declared relation roles (ADR 0004)."""
    from structural_kernel.intents import REGISTRY

    issues: list[ValidationIssue] = []
    for op in changeset.ops:
        if not isinstance(op, AddDecision | ModifyDecision):
            continue
        try:
            parse_params(op.decision)
        except pydantic.ValidationError as exc:
            issues.append(
                _error(
                    "schema_invalid",
                    f"decision {op.decision.did} ({op.decision.kind}): "
                    "params do not validate against the kind schema",
                    did=op.decision.did,
                    kind=op.decision.kind,
                    errors=[
                        f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}"
                        for e in exc.errors(include_url=False)
                    ],
                )
            )
        for intent in op.decision.intent:
            registration = REGISTRY.get(intent.category)
            if registration is None:
                issues.append(
                    _error(
                        "unknown_intent_category",
                        f"decision {op.decision.did}: intent category "
                        f"{intent.category!r} is not registered",
                        did=op.decision.did,
                        category=intent.category,
                    )
                )
                continue
            try:
                registration.payload_model.model_validate(intent.payload)
            except pydantic.ValidationError as exc:
                issues.append(
                    _error(
                        "schema_invalid",
                        f"decision {op.decision.did}: {intent.category} intent payload "
                        "does not validate against the category schema",
                        did=op.decision.did,
                        category=intent.category,
                        errors=[e["msg"] for e in exc.errors(include_url=False)],
                    )
                )
            for relation in intent.relations:
                if relation.role not in registration.relation_roles:
                    issues.append(
                        _error(
                            "schema_invalid",
                            f"decision {op.decision.did}: relation role {relation.role!r} "
                            f"is not declared by category {intent.category!r}",
                            did=op.decision.did,
                            category=intent.category,
                            role=relation.role,
                        )
                    )
    issues += _check_constraint_schema(changeset)
    return issues


def _check_constraint_schema(changeset: Changeset) -> list[ValidationIssue]:
    """Every added project constraint — and every engineer edit applied on ratify
    — names a registered predicate and its payload validates against that
    predicate's schema (ADR 0011). An unknown predicate is the constraint analog
    of an unknown intent category."""
    from structural_kernel.constraints import PREDICATES

    issues: list[ValidationIssue] = []
    for op in changeset.ops:
        if isinstance(op, AddConstraint):
            constraint = op.constraint
        elif isinstance(op, RatifyConstraint) and op.edited is not None:
            constraint = op.edited
        else:
            continue
        registration = PREDICATES.get(constraint.predicate)
        if registration is None:
            issues.append(
                _error(
                    "unknown_predicate",
                    f"constraint {constraint.cid}: predicate {constraint.predicate!r} "
                    "is not registered",
                    cid=constraint.cid,
                    predicate=constraint.predicate,
                )
            )
            continue
        try:
            registration.payload_model.model_validate(constraint.payload)
        except pydantic.ValidationError as exc:
            issues.append(
                _error(
                    "schema_invalid",
                    f"constraint {constraint.cid}: {constraint.predicate} payload does not "
                    "validate against the predicate schema",
                    cid=constraint.cid,
                    predicate=constraint.predicate,
                    errors=[e["msg"] for e in exc.errors(include_url=False)],
                )
            )
    return issues


# -- op application ----------------------------------------------------------------


def _ratify(existing: ProjectConstraint, op: RatifyConstraint) -> ProjectConstraint:
    """Promote an inferred, unratified constraint (design doc 0005 §5). The
    inferred basis and confidence are preserved — the read is never lost, only
    ratified. When the engineer edited the reading, the edit's predicate/region/
    payload/statement replace the inferred ones and ``modified`` records the
    change; the ratification record carries who/when either way."""
    assert isinstance(existing.provenance, InferredConstraintProvenance)  # apply_changeset guards
    base = op.edited if op.edited is not None else existing
    modified = op.edited is not None and (
        base.predicate != existing.predicate
        or base.region != existing.region
        or base.payload != existing.payload
        or base.statement != existing.statement
    )
    provenance = existing.provenance.model_copy(
        update={
            "ratified": RatificationRecord(
                ratified_by=op.ratified_by, ratified_at=op.ratified_at, modified=modified
            )
        }
    )
    return base.model_copy(update={"provenance": provenance})


def apply_changeset(
    base: ResolvedSnapshot, changeset: Changeset
) -> tuple[ResolvedSnapshot | None, list[ValidationIssue]]:
    """Apply ops to a copy of the base working set. Op-level integrity errors
    (unknown targets, duplicates) are collected; on any error the result is None."""
    issues: list[ValidationIssue] = []
    decisions = dict(base.decisions)
    constraints = dict(base.constraints)
    referenced = dict(base.referenced_geometry)
    overrides: dict[tuple[str, str], Override] = {
        (o.target.eid, o.target.field): o for o in base.overrides.overrides
    }

    for op in changeset.ops:
        match op:
            case AddDecision():
                if op.decision.did in decisions:
                    issues.append(
                        _error(
                            "duplicate_decision",
                            f"decision {op.decision.did} already exists",
                            did=op.decision.did,
                        )
                    )
                else:
                    decisions[op.decision.did] = op.decision
            case ModifyDecision():
                if op.decision.did not in decisions:
                    issues.append(
                        _error(
                            "unknown_decision",
                            f"cannot modify unknown decision {op.decision.did}",
                            did=op.decision.did,
                        )
                    )
                else:
                    decisions[op.decision.did] = op.decision
            case RemoveDecision():
                if op.did not in decisions:
                    issues.append(
                        _error(
                            "unknown_decision",
                            f"cannot remove unknown decision {op.did}",
                            did=op.did,
                        )
                    )
                else:
                    del decisions[op.did]
            case AddOverride():
                key = (op.override.target.eid, op.override.target.field)
                if key in overrides:
                    issues.append(
                        _error(
                            "duplicate_override",
                            f"an override already pins {key[0]}.{key[1]}",
                            eid=key[0],
                            field=key[1],
                        )
                    )
                else:
                    overrides[key] = op.override
            case RemoveOverride():
                key = (op.target.eid, op.target.field)
                if key not in overrides:
                    issues.append(
                        _error(
                            "unknown_override",
                            f"no override pins {key[0]}.{key[1]}",
                            eid=key[0],
                            field=key[1],
                        )
                    )
                else:
                    del overrides[key]
            case AddConstraint():
                if op.constraint.cid in constraints:
                    issues.append(
                        _error(
                            "duplicate_constraint",
                            f"constraint {op.constraint.cid} already exists",
                            cid=op.constraint.cid,
                        )
                    )
                else:
                    constraints[op.constraint.cid] = op.constraint
            case RemoveConstraint():
                if op.cid not in constraints:
                    issues.append(
                        _error(
                            "unknown_constraint",
                            f"cannot remove unknown constraint {op.cid}",
                            cid=op.cid,
                        )
                    )
                else:
                    del constraints[op.cid]
            case RatifyConstraint():
                existing = constraints.get(op.cid)
                if existing is None:
                    issues.append(
                        _error(
                            "unknown_constraint",
                            f"cannot ratify unknown constraint {op.cid}",
                            cid=op.cid,
                        )
                    )
                elif (
                    not isinstance(existing.provenance, InferredConstraintProvenance)
                    or existing.provenance.ratified is not None
                ):
                    issues.append(
                        _error(
                            "constraint_not_ratifiable",
                            f"constraint {op.cid} is not an unratified inferred reading; "
                            "only inferred, unratified constraints can be ratified",
                            cid=op.cid,
                        )
                    )
                elif op.edited is not None and op.edited.cid != op.cid:
                    issues.append(
                        _error(
                            "schema_invalid",
                            f"ratify edit targets cid {op.edited.cid} but ratifies {op.cid}",
                            cid=op.cid,
                        )
                    )
                else:
                    constraints[op.cid] = _ratify(existing, op)
            case AddReferencedGeometry():
                ref_id = op.geometry.ref_id
                if ref_id in referenced:
                    issues.append(
                        _error(
                            "duplicate_referenced_geometry",
                            f"referenced geometry {ref_id} already imported; re-issue instead",
                            ref_id=ref_id,
                        )
                    )
                else:
                    referenced[ref_id] = op.geometry
            case ReissueReferencedGeometry():
                ref_id = op.geometry.ref_id
                current = referenced.get(ref_id)
                if current is None:
                    issues.append(
                        _error(
                            "unknown_referenced_geometry",
                            f"cannot re-issue unknown referenced geometry {ref_id}; add it first",
                            ref_id=ref_id,
                        )
                    )
                elif op.geometry.version <= current.version:
                    issues.append(
                        _error(
                            "stale_referenced_version",
                            f"re-issue of {ref_id} must have a higher version than "
                            f"v{current.version}; got v{op.geometry.version}",
                            ref_id=ref_id,
                            current_version=current.version,
                            new_version=op.geometry.version,
                        )
                    )
                else:
                    referenced[ref_id] = op.geometry

    if issues:
        return None, issues
    return (
        ResolvedSnapshot(
            decisions=decisions,
            constraints=constraints,
            referenced_geometry=referenced,
            overrides=OverrideSet(overrides=list(overrides.values())),
        ),
        [],
    )


# -- stage 2: referential ------------------------------------------------------------


def check_referential(result: ResolvedSnapshot) -> list[ValidationIssue]:
    """Global integrity of the *resulting* snapshot: deps resolve, no cycles,
    line-id and load references resolve. Global on purpose — deleting a grid
    line out from under an untouched framing decision must fail here (E3)."""
    issues: list[ValidationIssue] = []
    decisions = result.decisions

    for decision in decisions.values():
        for dep in decision.deps:
            if dep not in decisions:
                issues.append(
                    _error(
                        "missing_dep",
                        f"decision {decision.did} depends on unknown decision {dep}",
                        did=decision.did,
                        dep=dep,
                    )
                )

    cycle = _find_cycle(decisions)
    if cycle is not None:
        issues.append(
            _error(
                "dependency_cycle",
                "decision deps form a cycle: " + " -> ".join(cycle),
                cycle=list(cycle),
            )
        )

    for decision in decisions.values():
        params = parse_params(decision)  # already schema-checked; cheap to re-parse
        refs = line_refs(params)
        if refs:
            available: set[str] = set()
            for dep in decision.deps:
                dep_decision = decisions.get(dep)
                if dep_decision is None or dep_decision.kind != "grid":
                    continue
                dep_params = parse_params(dep_decision)
                if isinstance(dep_params, GridParams):
                    available |= dep_params.line_ids()
            for ref in sorted(refs - available):
                issues.append(
                    _error(
                        "unknown_line_ref",
                        f"decision {decision.did} references line {ref}, which no "
                        "grid among its deps defines",
                        did=decision.did,
                        line_id=ref,
                    )
                )

        for intent in decision.intent:
            for relation in intent.relations:
                if (
                    isinstance(relation.target, LoadTarget)
                    and relation.target.load not in decisions
                ):
                    issues.append(
                        _error(
                            "unknown_load_ref",
                            f"intent on {decision.did} references unknown load "
                            f"decision {relation.target.load}",
                            did=decision.did,
                            load=relation.target.load,
                        )
                    )
                if (
                    isinstance(relation.target, DecisionTarget)
                    and relation.target.decision not in decisions
                ):
                    issues.append(
                        _error(
                            "unknown_decision_ref",
                            f"intent on {decision.did} references unknown "
                            f"decision {relation.target.decision}",
                            did=decision.did,
                            decision=relation.target.decision,
                        )
                    )

    return issues


def resolved_snapshot_hash(result: ResolvedSnapshot) -> str:
    """The content address of the derivation inputs — decisions and overrides,
    the only things derivation consumes. Project constraints (ADR 0011) and
    referenced geometry (ADR 0013) are deliberately excluded: they bind validation
    and anchor constraints, not geometry, so two snapshots differing only in those
    share a derived model and must share this hash (the derivation cache key).
    Computable before anything is written, so the dry-run's provenance matches the
    eventual commit's geometry exactly."""
    snapshot = Snapshot(
        decisions={
            did: content_hash(model_document(decision))
            for did, decision in sorted(result.decisions.items())
        },
        override_set=(
            content_hash(model_document(result.overrides)) if result.overrides.overrides else None
        ),
    )
    return content_hash(model_document(snapshot))


def _find_cycle(decisions: dict[str, Decision]) -> tuple[str, ...] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(decisions, WHITE)
    stack: list[str] = []

    def visit(did: str) -> tuple[str, ...] | None:
        color[did] = GRAY
        stack.append(did)
        for dep in decisions[did].deps:
            if dep not in decisions:
                continue  # reported as missing_dep, not a cycle
            if color[dep] == GRAY:
                return (*stack[stack.index(dep) :], dep)
            if color[dep] == WHITE:
                found = visit(dep)
                if found is not None:
                    return found
        stack.pop()
        color[did] = BLACK
        return None

    for did in sorted(decisions):
        if color[did] == WHITE:
            found = visit(did)
            if found is not None:
                return found
    return None
