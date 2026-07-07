"""Persisted object envelopes: validation, store round trips, hash stability."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from structural_kernel.canonical import content_hash, model_document
from structural_kernel.ids import new_ulid
from structural_kernel.objects import (
    AddDecision,
    Author,
    Changeset,
    Commit,
    Decision,
    IntentInstance,
    IntentProvenance,
    IntentRelation,
    Override,
    OverrideProvenance,
    OverrideSet,
    OverrideTarget,
    ProvisionTarget,
    Snapshot,
    SurveyedAnchor,
)
from structural_kernel.store import FileStore
from structural_kernel.units import Quantity


def _decision(**overrides: object) -> Decision:
    base: dict[str, object] = {
        "did": new_ulid(),
        "kind": "opening",
        "title": "Door D1 in wall W2",
        "params": {"width": {"mag": 0.9144, "unit": "m"}},
        "intent": [
            IntentInstance(
                category="gravity_load_path",
                relations=[
                    IntentRelation(
                        role="governed_by",
                        target=ProvisionTarget(provision="IBC 2021 §2308.4.1"),
                    )
                ],
                provenance=IntentProvenance(source="authored"),
            )
        ],
    }
    base.update(overrides)
    return Decision.model_validate(base)


def test_decision_store_round_trip_preserves_hash(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    decision = _decision()
    h = store.put_model(decision)
    loaded = store.get_model(h, Decision)
    assert loaded == decision
    assert store.put_model(loaded) == h  # re-persisting changes nothing


def test_resolved_decision_requires_params() -> None:
    with pytest.raises(ValidationError, match="resolved decision must carry params"):
        _decision(params=None)


def test_open_decision_may_omit_params() -> None:
    open_decision = _decision(state="open", params=None)
    assert open_decision.state == "open"


def test_derived_intent_requires_inducer() -> None:
    with pytest.raises(ValidationError, match="inducer"):
        IntentProvenance(source="derived")


def test_did_and_hash_formats_are_enforced() -> None:
    with pytest.raises(ValidationError):
        _decision(did="not-a-ulid")
    with pytest.raises(ValidationError):
        Snapshot(decisions={new_ulid(): "sha1:abc"})


def test_schema_version_is_pinned() -> None:
    with pytest.raises(ValidationError):
        _decision(schema_version=2)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _decision(color="red")


def test_override_with_surveyed_anchor_enforces_dimensions() -> None:
    override = Override(
        target=OverrideTarget(eid="jst:01JXF:LN4QF2-LN4QG8.LN4QHC+03", field="section"),
        value={"family": "sawn_lumber", "designation": "4x10"},
        surveyed_anchor=SurveyedAnchor(
            x=Quantity(mag=1.2, unit="m"),
            y=Quantity(mag=0.0, unit="m"),
            z=Quantity(mag=3.0, unit="m"),
        ),
        provenance=OverrideProvenance(
            observed_by="M. Flamer",
            method="site_survey_tape",
            observed_at="2026-06-30",
            confidence="measured",
        ),
    )
    assert OverrideSet(overrides=[override]).overrides[0].provenance.confidence == "measured"

    with pytest.raises(ValidationError):
        SurveyedAnchor(
            x=Quantity(mag=1.0, unit="kip"),  # force where length is required
            y=Quantity(mag=0.0, unit="m"),
            z=Quantity(mag=0.0, unit="m"),
        )


def test_changeset_commit_snapshot_chain(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    decision = _decision()

    changeset = Changeset(base_commit=None, ops=[AddDecision(decision=decision)])
    changeset_hash = store.put_model(changeset)

    decision_hash = store.put_model(decision)
    snapshot = Snapshot(decisions={decision.did: decision_hash})
    snapshot_hash = store.put_model(snapshot)

    commit = Commit(
        snapshot=snapshot_hash,
        author=Author(kind="human", id="mark"),
        timestamp="2026-07-07T21:00:00Z",
        message="genesis",
        changeset=changeset_hash,
    )
    commit_hash = store.put_model(commit)
    store.compare_and_swap("main", None, commit_hash)

    loaded = store.get_model(commit_hash, Commit)
    assert store.get_model(loaded.snapshot, Snapshot) == snapshot
    assert content_hash(model_document(commit)) == commit_hash


def test_changeset_requires_ops_and_discriminates_them() -> None:
    with pytest.raises(ValidationError):
        Changeset(base_commit=None, ops=[])
    changeset = Changeset.model_validate(
        {
            "base_commit": None,
            "ops": [{"op": "remove_decision", "did": new_ulid()}],
        }
    )
    assert changeset.ops[0].op == "remove_decision"


def test_bad_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        Commit(
            snapshot="sha256:" + "0" * 64,
            author=Author(kind="ai", id="claude"),
            timestamp="2026-07-07 21:00:00",  # not RFC 3339 Z form
            message="x",
        )
