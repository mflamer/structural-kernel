"""The only write path: propose → validate → commit | reject (design doc 0001 §6).

The AI (or any client) never touches state. Commits are atomic — objects
written, then the ref advanced by compare-and-swap, or nothing — and every
changeset persists with a ``ValidationReport``, rejected ones included: the
record of what was attempted is part of the audit trail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from structural_kernel.constraints import check_project_constraints
from structural_kernel.derivation import (
    DanglingExceptionError,
    DerivationError,
    OverrideAttachment,
    derive,
)
from structural_kernel.ids import ObjectHash
from structural_kernel.intents import check_intent
from structural_kernel.objects import (
    Author,
    Changeset,
    Commit,
    Decision,
    KernelModel,
    OverrideSet,
    ProjectConstraint,
    Snapshot,
    Timestamp,
)
from structural_kernel.store import StaleBaseError
from structural_kernel.validation import (
    ResolvedSnapshot,
    ValidationIssue,
    ValidationReport,
    apply_changeset,
    check_referential,
    check_schema,
    resolved_snapshot_hash,
)

if TYPE_CHECKING:
    from structural_kernel.store import FileStore


class ProposeResult(KernelModel):
    outcome: Literal["committed", "rejected"]
    changeset: ObjectHash
    report: ObjectHash
    commit: ObjectHash | None = None
    issues: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])


def propose(
    store: FileStore,
    changeset: Changeset,
    *,
    author: Author,
    message: str,
    timestamp: Timestamp,
    ref: str = "main",
) -> ProposeResult:
    """Validate a changeset against the current tip of ``ref`` and commit it,
    or persist the rejection. Stages run fail-fast: schema, op application,
    referential, derivation dry-run, intent checks — the full §6 pipeline."""
    current = store.read_ref(ref)
    if changeset.base_commit != current:
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="stale_base",
                    severity="error",
                    message=f"changeset bases on {changeset.base_commit!r} but "
                    f"{ref!r} is at {current!r}; rebase and repropose",
                    detail={"ref": ref, "base_commit": changeset.base_commit, "tip": current},
                )
            ],
        )

    base = load_snapshot(store, current)

    issues = check_schema(changeset)
    if issues:
        return _reject(store, changeset, issues)

    result, issues = apply_changeset(base, changeset)
    if result is None:
        return _reject(store, changeset, issues)

    issues = check_referential(result)
    if issues:
        return _reject(store, changeset, issues)

    # Stage 3: derivation dry-run — nothing that cannot derive ever commits.
    try:
        derived = derive(result, snapshot_hash=resolved_snapshot_hash(result))
    except DanglingExceptionError as exc:
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="dangling_exception",
                    severity="error",
                    message=str(exc),
                    detail={
                        "did": exc.did,
                        "target_eid": exc.target_eid,
                        "candidates": list(exc.candidates),
                    },
                )
            ],
        )
    except DerivationError as exc:
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="derivation_failure",
                    severity="error",
                    message=str(exc),
                    detail={},
                )
            ],
        )

    # Stage 4: intent checks — every registered checker over the dry-run
    # derived model. The charter's "delete the header while the opening
    # remains" case dies here with a machine-actionable error.
    violations = check_intent(derived, result)
    if violations:
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="intent_violation",
                    severity="error",
                    message=v.message,
                    detail={
                        "category": v.category,
                        "carrier": v.carrier,
                        "violated": v.violated,
                        **v.detail,
                    },
                )
                for v in violations
            ],
        )

    # Stage 5: project constraints (ADR 0011) — the standing spatial constraints
    # bind every changeset, including every exploration candidate. A violation
    # (a support in a clear-span region, a bay under the minimum) is rejected
    # citing the constraint; a constraint whose region anchor no longer resolves
    # goes inert with a warning, the override-like posture (note 0002).
    constraint_violations, inert = check_project_constraints(derived, result)
    if constraint_violations:
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="constraint_violation",
                    severity="error",
                    message=v.message,
                    detail={"cid": v.cid, "predicate": v.predicate, **v.detail},
                )
                for v in constraint_violations
            ],
        )

    # Overrides that no longer attach cleanly are warnings on the commit —
    # never rejections, never silently dropped (§5). They recompute on every
    # commit, so they persist until a human resolves them.
    warnings = [
        _attachment_warning(a) for a in derived.override_attachments if a.state != "attached"
    ]
    warnings += [
        ValidationIssue(
            code="constraint_inert",
            severity="warning",
            message=w.message,
            detail={"cid": w.cid, "predicate": w.predicate, **w.detail},
        )
        for w in inert
    ]

    return _commit(store, changeset, result, author, message, timestamp, ref, current, warnings)


def _attachment_warning(attachment: OverrideAttachment) -> ValidationIssue:
    target = attachment.target
    provenance = attachment.provenance
    surveyed = (
        f"surveyed by {provenance.observed_by} ({provenance.method}, "
        f"{provenance.observed_at}, {provenance.confidence})"
    )
    if attachment.state == "dangling":
        hint = (
            f"; candidate re-targets: {', '.join(attachment.candidates)}"
            if attachment.candidates
            else ""
        )
        message = (
            f"override on {target.eid}.{target.field} is dangling — the element no "
            f"longer exists; {surveyed}{hint}"
        )
        code: Literal["dangling_override", "displaced_override"] = "dangling_override"
    else:
        assert attachment.distance_m is not None
        message = (
            f"override on {target.eid}.{target.field} is displaced — the member is "
            f"{attachment.distance_m:.3f} m from the surveyed anchor (it moved with "
            f"the model; the surveyed member did not); {surveyed}"
        )
        code = "displaced_override"
    return ValidationIssue(
        code=code,
        severity="warning",
        message=message,
        detail={
            "eid": target.eid,
            "field": target.field,
            "state": attachment.state,
            "distance_m": attachment.distance_m,
            "candidates": list(attachment.candidates),
        },
    )


def load_snapshot(store: FileStore, commit_hash: str | None) -> ResolvedSnapshot:
    """Resolve a commit's snapshot into its decision payloads and overrides."""
    if commit_hash is None:
        return ResolvedSnapshot()
    commit = store.get_model(commit_hash, Commit)
    snapshot = store.get_model(commit.snapshot, Snapshot)
    decisions = {
        did: store.get_model(decision_hash, Decision)
        for did, decision_hash in snapshot.decisions.items()
    }
    constraints = {
        cid: store.get_model(constraint_hash, ProjectConstraint)
        for cid, constraint_hash in snapshot.constraints.items()
    }
    overrides = (
        store.get_model(snapshot.override_set, OverrideSet)
        if snapshot.override_set is not None
        else OverrideSet()
    )
    return ResolvedSnapshot(decisions=decisions, constraints=constraints, overrides=overrides)


def _commit(
    store: FileStore,
    changeset: Changeset,
    result: ResolvedSnapshot,
    author: Author,
    message: str,
    timestamp: Timestamp,
    ref: str,
    parent: str | None,
    warnings: list[ValidationIssue],
) -> ProposeResult:
    changeset_hash = store.put_model(changeset)
    snapshot = Snapshot(
        decisions={
            did: store.put_model(decision) for did, decision in sorted(result.decisions.items())
        },
        constraints={
            cid: store.put_model(constraint)
            for cid, constraint in sorted(result.constraints.items())
        },
        override_set=(store.put_model(result.overrides) if result.overrides.overrides else None),
    )
    commit = Commit(
        snapshot=store.put_model(snapshot),
        parents=[parent] if parent is not None else [],
        author=author,
        timestamp=timestamp,
        message=message,
        changeset=changeset_hash,
    )
    commit_hash = store.put_model(commit)
    try:
        store.compare_and_swap(ref, parent, commit_hash)
    except StaleBaseError:
        # A concurrent commit won the ref between our read and the CAS. The
        # objects we wrote are harmless orphans (content-addressed, reproducible);
        # the proposal is rejected exactly like any other stale base.
        return _reject(
            store,
            changeset,
            [
                ValidationIssue(
                    code="stale_base",
                    severity="error",
                    message=f"ref {ref!r} advanced concurrently; rebase and repropose",
                    detail={"ref": ref, "base_commit": changeset.base_commit},
                )
            ],
        )
    report = ValidationReport(changeset=changeset_hash, outcome="committed", issues=warnings)
    return ProposeResult(
        outcome="committed",
        changeset=changeset_hash,
        report=store.put_model(report),
        commit=commit_hash,
        issues=warnings,
    )


def _reject(store: FileStore, changeset: Changeset, issues: list[ValidationIssue]) -> ProposeResult:
    changeset_hash = store.put_model(changeset)
    report = ValidationReport(changeset=changeset_hash, outcome="rejected", issues=issues)
    return ProposeResult(
        outcome="rejected",
        changeset=changeset_hash,
        report=store.put_model(report),
        issues=issues,
    )
