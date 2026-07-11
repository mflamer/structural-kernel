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

from structural_kernel.ids import Did, LineId, ObjectHash
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

# Closed union (design doc 0001 §2.3): adding a kind means adding derivation
# logic anyway. `steel_framing_strategy` is the first phase-2 kind (ADR 0008) —
# the sibling of `gravity_framing_strategy` that heterogeneous exploration ranks
# against it; `concrete_framing_strategy` (ADR 0014) is the third sibling, whose
# members are dimensioned (b, h, reinforcement), not catalog picks. `cost_basis`
# (standing req. 3, ADR 0012) is the versioned cost assumption exploration
# rankings cite; it derives no geometry — it is pure data the evaluation layer
# reads — so it has no rule in derivation.
DecisionKind = Literal[
    "grid",
    "levels",
    "load_assumptions",
    "gravity_framing_strategy",
    "steel_framing_strategy",
    "concrete_framing_strategy",
    "lateral_strategy",
    "opening",
    "exception",
    "cost_basis",
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


# -- referenced geometry (design doc 0005 §3; ADR 0013) -----------------------
#
# The architect's geometry as *read-only external context* structural constraints
# anchor to — never a `Decision`. Content-addressed and versioned: a re-issued
# model lands a new version at the same `ref_id` lineage, and the displaced/
# dangling machinery (ADR 0005) surfaces affected constraints. Light-typed for the
# entities IFC gives cleanly (grids, storeys); everything about *how* it was read
# stays behind the importer adapter — no IFC/DWG/vision type crosses into here.


class ExternalProvenance(KernelModel):
    """Where a referenced-geometry version came from — the parallel to a surveyed
    override's `measured` provenance. Stamps the source file, its content hash,
    the importer that read it, and when."""

    source_file: Annotated[str, StringConstraints(min_length=1)]
    file_hash: Annotated[str, StringConstraints(min_length=1)]  # sha256 hex of the source bytes
    importer: Annotated[str, StringConstraints(min_length=1)]  # importer name + version
    imported_at: IsoDate


class ReferencedGrid(KernelModel):
    """A grid line read from the architect's model (an IfcGridAxis): a stable id
    from the source, a display name, the axis it holds constant, and its offset in
    canonical units. The kernel vocabulary — the IFC entity does not cross over."""

    grid_id: Annotated[str, StringConstraints(min_length=1)]
    name: Annotated[str, StringConstraints(min_length=1)]
    axis: Literal["x", "y"]
    offset: LengthQuantity


class ReferencedLevel(KernelModel):
    """A storey read from the architect's model (an IfcBuildingStorey)."""

    level_id: Annotated[str, StringConstraints(min_length=1)]
    name: Annotated[str, StringConstraints(min_length=1)]
    elevation: LengthQuantity


class ReferencedGeometry(KernelModel):
    """A read-only, versioned import of external architectural geometry. `ref_id`
    is the stable lineage (constant across re-issues); `version` bumps on re-issue.
    Never consumed by derivation — only referenced by a `ReferencedRegion`."""

    schema_version: Literal[1] = 1
    ref_id: Did
    version: int = Field(ge=1)
    provenance: ExternalProvenance
    grids: list[ReferencedGrid] = Field(default_factory=list[ReferencedGrid])
    levels: list[ReferencedLevel] = Field(default_factory=list[ReferencedLevel])

    @model_validator(mode="after")
    def _ids_unique(self) -> ReferencedGeometry:
        for label, ids in (
            ("grid", [g.grid_id for g in self.grids]),
            ("level", [lv.level_id for lv in self.levels]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"referenced geometry {self.ref_id}: duplicate {label} ids")
        return self


# -- spatial structural constraints (ADR 0011; PO note 0002) ------------------
#
# A *project-level* constraint: a typed predicate over a spatially-anchored
# region, standing independently of the structural system — which may still be an
# *open* decision when the constraint is captured (the vision's "west 40 ft
# column-free", stated before any system exists). It is deliberately neither a
# `Decision` (it derives no geometry) nor element `intent` (there is no element to
# hang it on at capture time): it is a first-class committed graph object that the
# validator and the exploration both read. The predicate *meaning* lives in an
# open registry (`constraints.py`) — a third predicate kind is a registration,
# zero kernel edits — and the region in the ADR 0005 anchor vocabulary below.

# A constraint id shares the ULID identity scheme decisions use.
Cid = Did


class OffsetBand(KernelModel):
    """A band measured perpendicular off a stable anchor grid line. ADR 0005
    anchors are names, never coordinates: "the west 40 feet" is an offset band
    off the west line, rendered from it, and it tracks when the line moves."""

    kind: Literal["offset_band"] = "offset_band"
    anchor: LineId
    extent: LengthQuantity
    # The protected side, in the anchor line's own axis coordinate: `greater` =
    # the higher-coordinate side, `less` = the lower.
    side: Literal["greater", "less"]


class GridBoundedRegion(KernelModel):
    """A rectangle bounded by four stable grid line-ids (the framing-region shape,
    reused as a constraint region)."""

    kind: Literal["grid_bounded"] = "grid_bounded"
    x_from: LineId
    x_to: LineId
    y_from: LineId
    y_to: LineId


class WholePlan(KernelModel):
    """The entire plan — an unbounded region (e.g. a model-wide minimum bay)."""

    kind: Literal["whole_plan"] = "whole_plan"


class ReferencedRegion(KernelModel):
    """A band measured off a grid line in *referenced geometry* (design doc 0005
    §3) — the outside-world analog of `OffsetBand`. Anchors by (referenced-geometry
    lineage, grid id), never coordinates, so it tracks the architect's grid when a
    re-issue moves it; a re-issue that moves or removes the anchor surfaces the
    constraint for re-confirmation (ADR 0005 displaced/dangling)."""

    kind: Literal["referenced_region"] = "referenced_region"
    ref_id: Did  # the ReferencedGeometry lineage this reads from
    anchor_grid: Annotated[str, StringConstraints(min_length=1)]  # a grid_id within it
    extent: LengthQuantity
    side: Literal["greater", "less"]


# A referenced-geometry region (design doc 0005) joins the ADR 0005 anchor
# vocabulary as one more variant — no predicate need change.
Region = Annotated[
    OffsetBand | GridBoundedRegion | WholePlan | ReferencedRegion,
    Field(discriminator="kind"),
]


# The provenance taxonomy (design doc 0005 §5, ADR 0013). A constraint is either
# *authored* — the engineer's design will, or an LLM proposal that only reaches
# state through the human/pipeline writer — or *inferred* — proposed by the
# ingestion AI from referenced geometry or a drawing. The backbone distinction:
# an inferred reading may never enforce or bind an exploration until an engineer
# ratifies it. `is_binding` encodes exactly that, and stage 5 + the exploration
# binding both read it, so a low-confidence machine reading can never masquerade
# as authored intent.


class AuthoredConstraintProvenance(KernelModel):
    """The engineer's design will (a spoken constraint), or an LLM proposal that
    only reaches state through the human/pipeline writer. Always binding."""

    source: Literal["authored"] = "authored"
    captured_by: Annotated[str, StringConstraints(min_length=1)]  # LLM descriptor or "human"

    @property
    def is_binding(self) -> bool:
        return True


class InferredBasis(KernelModel):
    """What the ingestion AI read to propose the constraint (design doc 0005 §5):
    the referenced-geometry version it read, the sheet/region/line reference, and
    the model's stated reason. The persisted record of the machine reading, kept
    for the audit trail even after ratification."""

    referenced_geometry: ObjectHash | None = None  # the ReferencedGeometry read (ADR 0013)
    region_ref: Annotated[str, StringConstraints(min_length=1)] | None = None
    reason: Annotated[str, StringConstraints(min_length=1)]


class RatificationRecord(KernelModel):
    """The engineer's ratification event (design doc 0005 §5): who confirmed the
    inferred reading, when, and whether they modified it on the way in. The kernel
    fills this on a ``RatifyConstraint`` op; its *presence* is what makes an
    inferred constraint binding — the audit trail keeps "the AI read this and the
    engineer agreed" distinct from "the engineer authored this outright"."""

    ratified_by: Annotated[str, StringConstraints(min_length=1)]
    ratified_at: Timestamp
    modified: bool  # did the engineer change the reading when ratifying?


class InferredConstraintProvenance(KernelModel):
    """A constraint the ingestion AI proposed from a drawing/model (design doc
    0005 §5). **Inert by type until ratified**: ``is_binding`` is False while
    ``ratified`` is None, so stage 5 and the exploration binding both skip it. A
    bad reading yields an unratified proposal, never corrupt authored intent."""

    source: Literal["inferred"] = "inferred"
    captured_by: Annotated[str, StringConstraints(min_length=1)]  # the vision/LLM descriptor
    basis: InferredBasis
    confidence: Literal["high", "medium", "low"]  # machine-reading scale (ADR 0013)
    ratified: RatificationRecord | None = None

    @property
    def is_binding(self) -> bool:
        return self.ratified is not None


ConstraintProvenance = Annotated[
    AuthoredConstraintProvenance | InferredConstraintProvenance,
    Field(discriminator="source"),
]


class ProjectConstraint(KernelModel):
    """A typed predicate over a spatially-anchored region, enforced on every
    changeset and every exploration candidate (note 0002)."""

    schema_version: Literal[1] = 1
    cid: Cid
    predicate: Annotated[str, StringConstraints(min_length=1)]  # constraints.py registry key
    region: Region
    payload: dict[str, JsonValue] = Field(default_factory=dict)  # predicate-specific params
    statement: Annotated[str, StringConstraints(min_length=1)]  # the constraint as captured
    provenance: ConstraintProvenance


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


class AddConstraint(KernelModel):
    op: Literal["add_constraint"] = "add_constraint"
    constraint: ProjectConstraint


class RemoveConstraint(KernelModel):
    op: Literal["remove_constraint"] = "remove_constraint"
    cid: Cid


class RatifyConstraint(KernelModel):
    """Promote an inferred, unratified constraint to binding strength — a
    human-authored event (design doc 0005 §5, ADR 0013). The kernel fills the
    ``RatificationRecord`` from ``ratified_by``/``ratified_at``; ``edited``, when
    present, carries the engineer's correction of the reading (its ``cid`` must
    equal ``cid``), and a real change records ``modified=True``. The inferred
    basis and confidence are preserved on the promoted constraint — the read is
    never lost, only ratified."""

    op: Literal["ratify_constraint"] = "ratify_constraint"
    cid: Cid
    ratified_by: Annotated[str, StringConstraints(min_length=1)]
    ratified_at: Timestamp
    edited: ProjectConstraint | None = None


class AddReferencedGeometry(KernelModel):
    """Import a new referenced-geometry lineage (design doc 0005 §3). The
    ``ref_id`` must be new; ``version`` is the initial version (1)."""

    op: Literal["add_referenced_geometry"] = "add_referenced_geometry"
    geometry: ReferencedGeometry


class ReissueReferencedGeometry(KernelModel):
    """Land a re-issued architectural model at an existing lineage: same
    ``ref_id``, a strictly higher ``version`` (design doc 0005 §3). The commit
    diffs old vs new and surfaces affected constraints for re-confirmation."""

    op: Literal["reissue_referenced_geometry"] = "reissue_referenced_geometry"
    geometry: ReferencedGeometry


ChangesetOp = Annotated[
    AddDecision
    | ModifyDecision
    | RemoveDecision
    | AddOverride
    | RemoveOverride
    | AddConstraint
    | RemoveConstraint
    | RatifyConstraint
    | AddReferencedGeometry
    | ReissueReferencedGeometry,
    Field(discriminator="op"),
]


class Changeset(KernelModel):
    """A proposed diff. Persisted even when rejected — the audit trail of attempts."""

    schema_version: Literal[1] = 1
    base_commit: ObjectHash | None  # None only for the genesis changeset
    ops: list[ChangesetOp] = Field(min_length=1)


# -- snapshots and commits ------------------------------------------------------


class Snapshot(KernelModel):
    """The complete canonical model at an instant: did → decision hash, plus the
    standing project constraints (cid → constraint hash) that bind every future
    changeset and exploration candidate, and the referenced geometry (ref_id →
    referenced-geometry hash) constraints may anchor to."""

    schema_version: Literal[1] = 1
    decisions: dict[Did, ObjectHash] = Field(default_factory=dict)
    constraints: dict[Cid, ObjectHash] = Field(default_factory=dict)
    referenced_geometry: dict[Did, ObjectHash] = Field(default_factory=dict)
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
