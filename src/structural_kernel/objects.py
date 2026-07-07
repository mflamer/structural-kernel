"""Persisted object schemas: the language-neutral source of truth (design doc 0001 §2).

Every persisted object carries ``schema_version`` and is immutable once
written. These pydantic models *define* the schema in phase 1; the JSON in the
store is the truth, and the Python kernel is one replaceable implementation.

Increment 1 scope: envelopes only. Decision ``params`` and intent ``payload``
are structurally arbitrary JSON here; kind-specific and category-specific
validation land with increment 2 (decisions + validation) and the intent
registry. Eids are opaque strings until derivation implements the ADR 0005
grammar.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from structural_kernel.ids import Did, ObjectHash
from structural_kernel.units import LengthQuantity

# RFC 3339 UTC instants, 'Z' suffix required — one spelling, boringly diffable.
Timestamp = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"),
]
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]

Eid = Annotated[str, StringConstraints(min_length=1)]


class KernelModel(BaseModel):
    """Base for persisted objects: immutable, closed schemas."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# -- structural intent (envelope; categories are an open registry) -----------


class EidTarget(KernelModel):
    eid: Eid


class ProvisionTarget(KernelModel):
    provision: Annotated[str, StringConstraints(min_length=1)]


class LoadTarget(KernelModel):
    load: Did


class DecisionTarget(KernelModel):
    decision: Did


IntentTarget = EidTarget | ProvisionTarget | LoadTarget | DecisionTarget


class IntentRelation(KernelModel):
    role: Annotated[str, StringConstraints(min_length=1)]
    target: IntentTarget


class IntentProvenance(KernelModel):
    source: Literal["authored", "derived"]
    inducer: Did | None = None

    @model_validator(mode="after")
    def _derived_has_inducer(self) -> IntentProvenance:
        if self.source == "derived" and self.inducer is None:
            raise ValueError("derived intent must name its inducer")
        return self


class IntentInstance(KernelModel):
    """The kernel-fixed intent shape (ADR 0004). Category meaning lives in the registry."""

    schema_version: Literal[1] = 1
    category: Annotated[str, StringConstraints(min_length=1)]
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    relations: list[IntentRelation] = Field(default_factory=list[IntentRelation])
    provenance: IntentProvenance


# -- decisions ----------------------------------------------------------------

# Closed union in phase 1 (design doc 0001 §2.3): adding a kind means adding
# derivation logic anyway. `cost_basis` (standing req. 3) joins when priced
# evaluation does.
DecisionKind = Literal[
    "grid",
    "levels",
    "load_assumptions",
    "gravity_framing_strategy",
    "lateral_strategy",
    "opening",
    "exception",
]


class Decision(KernelModel):
    """The unit of design meaning: small, declarative, inspectable."""

    schema_version: Literal[1] = 1
    did: Did
    kind: DecisionKind
    title: Annotated[str, StringConstraints(min_length=1)]
    # Standing requirement 2/10: a decision may be held explicitly open in a
    # committed model ("structural system: unresolved") and derives partially.
    state: Literal["resolved", "open"] = "resolved"
    params: dict[str, JsonValue] | None = None
    deps: list[Did] = Field(default_factory=list)
    intent: list[IntentInstance] = Field(default_factory=list[IntentInstance])

    @model_validator(mode="after")
    def _resolved_has_params(self) -> Decision:
        if self.state == "resolved" and self.params is None:
            raise ValueError("a resolved decision must carry params")
        return self


# -- reality overrides (design doc 0001 §5; ADR 0005 correspondence) ----------


class OverrideTarget(KernelModel):
    eid: Eid
    field: Annotated[str, StringConstraints(min_length=1)]


class SurveyedAnchor(KernelModel):
    """World-space reference geometry captured at attach time (ADR 0005).

    Re-attachment checks the target eid still exists *and* its geometry
    matches this anchor within a confidence-bucketed tolerance; divergence is
    the `displaced` state, never a silent re-attach.
    """

    x: LengthQuantity
    y: LengthQuantity
    z: LengthQuantity
    tolerance: LengthQuantity | None = None  # None: bucketed from confidence


class OverrideProvenance(KernelModel):
    observed_by: Annotated[str, StringConstraints(min_length=1)]
    method: Annotated[str, StringConstraints(min_length=1)]
    observed_at: IsoDate
    confidence: Literal["measured", "estimated", "assumed"]


class Override(KernelModel):
    """Measurement, not preference — design preferences are `exception` decisions."""

    schema_version: Literal[1] = 1
    target: OverrideTarget
    value: JsonValue
    surveyed_anchor: SurveyedAnchor | None = None
    provenance: OverrideProvenance


class OverrideSet(KernelModel):
    schema_version: Literal[1] = 1
    overrides: list[Override] = Field(default_factory=list[Override])


# -- changesets (the only write path) -----------------------------------------


class AddDecision(KernelModel):
    op: Literal["add_decision"] = "add_decision"
    decision: Decision


class ModifyDecision(KernelModel):
    op: Literal["modify_decision"] = "modify_decision"
    decision: Decision  # replaces the payload at decision.did


class RemoveDecision(KernelModel):
    op: Literal["remove_decision"] = "remove_decision"
    did: Did


class AddOverride(KernelModel):
    op: Literal["add_override"] = "add_override"
    override: Override


class RemoveOverride(KernelModel):
    op: Literal["remove_override"] = "remove_override"
    target: OverrideTarget


ChangesetOp = Annotated[
    AddDecision | ModifyDecision | RemoveDecision | AddOverride | RemoveOverride,
    Field(discriminator="op"),
]


class Changeset(KernelModel):
    """A proposed diff. Persisted even when rejected — the audit trail of attempts."""

    schema_version: Literal[1] = 1
    base_commit: ObjectHash | None  # None only for the genesis changeset
    ops: list[ChangesetOp] = Field(min_length=1)


# -- snapshots and commits ------------------------------------------------------


class Snapshot(KernelModel):
    """The complete canonical model at an instant: did → decision hash."""

    schema_version: Literal[1] = 1
    decisions: dict[Did, ObjectHash] = Field(default_factory=dict)
    override_set: ObjectHash | None = None


class Author(KernelModel):
    kind: Literal["human", "ai", "proposer"]
    id: Annotated[str, StringConstraints(min_length=1)]


class Commit(KernelModel):
    schema_version: Literal[1] = 1
    snapshot: ObjectHash
    parents: list[ObjectHash] = Field(default_factory=list)
    author: Author
    timestamp: Timestamp
    message: str
    changeset: ObjectHash | None = None
