"""Derivation: pure functions decision-snapshot → derived model (design doc 0001 §3).

Deterministic — no clock, no randomness, no I/O; same snapshot + same
derivation version ⇒ byte-identical output (property-tested). Rules resolve
context *strictly through declared deps* (a framing strategy sees only the
grids, levels, and loads it declares), which makes "reads ⊆ declared deps"
true by construction rather than by audit.

Totality: any snapshot that passed commit-time validation derives without
raising. Conditions a rule cannot honor (zero-extent region, unknown section
designation) raise ``DerivationError`` — caught by validation stage 3, so
nothing invalid ever commits. Partial models are first-class (standing
requirement 10): open decisions derive to their absence, explicitly listed,
and a partial model may legitimately produce no analysis artifact.

Phase-1 analysis idealization (documented, deliberate): flexural members
(joists, beams, headers) enter the analysis artifact as independent
simply-supported spans under tributary line loads — the decomposition that
matches the hand-calc verification fixtures. Posts appear in the derived
model and bill; their axial demands follow from tributary areas, not a frame
solve. The artifact schema (§7.1) uses SI-suffixed field names by design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Annotated, Final, Literal

from pydantic import Field

from structural_kernel.decisions import (
    ExceptionParams,
    GravityFramingStrategyParams,
    GridParams,
    GridRegion,
    LateralStrategyParams,
    Level,
    LevelsParams,
    LoadAssumptionsParams,
    OpeningParams,
    SteelFramingStrategyParams,
    parse_params,
)
from structural_kernel.eids import segment
from structural_kernel.loads import combos_for
from structural_kernel.materials import engine_for, families
from structural_kernel.objects import (
    Decision,
    DecisionKind,
    DecisionTarget,
    Eid,
    EidTarget,
    IntentInstance,
    IntentProvenance,
    IntentRelation,
    KernelModel,
    LoadTarget,
    Override,
    OverrideProvenance,
    OverrideSet,
    OverrideTarget,
    SurveyedAnchor,
)
from structural_kernel.units import Quantity
from structural_kernel.validation import ResolvedSnapshot

DERIVATION_VERSION = 1

_HEADER_BEARING_M = 0.0762  # 3 in each side, span taken center-to-center of bearing

# Re-attachment tolerance by provenance confidence (ADR 0005). "assumed" is
# advisory — an assumption is not a measurement of position, so it never
# displaces. An explicit tolerance on the anchor overrides the bucket.
_CONFIDENCE_TOLERANCE_M: Final[dict[str, float]] = {
    "measured": 0.025,  # ~1 in
    "estimated": 0.150,  # ~6 in
    "assumed": math.inf,
}
_CANDIDATE_RADIUS_M: Final = 1.0
_MAX_CANDIDATES: Final = 3


class DerivationError(Exception):
    """A rule cannot honor the snapshot's conditions — a validation stage-3
    rejection, never a crash after commit."""


class DanglingExceptionError(DerivationError):
    """An `exception` decision targets an eid that does not exist (ADR 0005:
    hard error; the orphaning changeset must retarget or delete it)."""

    def __init__(self, did: str, target_eid: str, candidates: list[str]) -> None:
        self.did = did
        self.target_eid = target_eid
        self.candidates = candidates
        hint = f" (candidates: {', '.join(candidates)})" if candidates else ""
        super().__init__(
            f"exception {did} targets {target_eid}, which no derived element carries{hint}"
        )


# -- derived model schema ---------------------------------------------------------

# joist/beam/post are the wood tiers; beam/girder/column the steel tiers (a steel
# infill member is a "beam", so that role is shared). header and wall_segment are
# induced elements. The two three-tier vocabularies share one geometry rule.
ElementRole = Literal["joist", "beam", "post", "header", "wall_segment", "girder", "column"]


def _length_m(mag: float) -> Quantity:
    return Quantity(mag=mag, unit="m")


class Point(KernelModel):
    x: Quantity
    y: Quantity
    z: Quantity


class Element(KernelModel):
    eid: Eid
    role: ElementRole
    family: str
    section: str
    grade: str | None = None  # material grade (None for non-lumber, e.g. wall panels)
    # How this member is designed — the method its material's code uses (ADR
    # 0008). Wood is NDS/ASD; steel is AISC/LRFD. The solve-time checks read it
    # to pick the demand combos (service vs factored) and the engine's method.
    design_method: Literal["ASD", "LRFD"] = "ASD"
    start: Point
    end: Point
    length: Quantity
    tributary_width: Quantity | None = None
    supports: list[Eid] = Field(default_factory=list[str])  # eids that carry this element
    intent: list[IntentInstance] = Field(default_factory=list[IntentInstance])
    # Reality override provenance, by overridden field (design doc §5): every
    # overridden value carries who measured it into every consuming artifact.
    overridden: dict[str, OverrideProvenance] = Field(default_factory=dict[str, OverrideProvenance])


class OverrideAttachment(KernelModel):
    """How one reality override attached to this derived model (ADR 0005)."""

    target: OverrideTarget
    state: Literal["attached", "displaced", "dangling"]
    provenance: OverrideProvenance
    distance_m: float | None = None  # anchor-to-member distance, when an anchor exists
    candidates: list[Eid] = Field(default_factory=list[str])  # re-target hints


class LoadPathEdge(KernelModel):
    bearing: Eid  # the carried element
    on: Eid  # what carries it


class OpenDecisionRef(KernelModel):
    did: str
    kind: DecisionKind
    title: str


class BillLine(KernelModel):
    role: ElementRole
    family: str
    section: str
    count: int
    total_length: Quantity


class Countables(KernelModel):
    """Installation-cost drivers (standing requirement 4; ADR 0012). Piece and
    connection counts are geometry; ``crane_picks`` sums each member's
    family-level pick count (steel members pick, hand-set lumber does not).
    ``None`` remains a valid legacy state (a model derived before picks were
    emitted); a present count is authoritative."""

    piece_count: int
    connection_count: int
    crane_picks: int | None = None


class BillOfElements(KernelModel):
    lines: list[BillLine]
    countables: Countables


class DerivationProvenance(KernelModel):
    snapshot: str
    derivation_version: int


class Releases(KernelModel):
    start: Literal["pin", "fixed"]
    end: Literal["pin", "fixed"]


class AnalysisNode(KernelModel):
    id: str
    xyz_m: tuple[float, float, float]


class AnalysisElement(KernelModel):
    id: str
    type: Literal["frame"]
    nodes: tuple[str, str]
    E_pa: float
    A_m2: float
    I_strong_m4: float
    I_weak_m4: float
    releases: Releases
    source_eid: Eid


class AnalysisSupport(KernelModel):
    node: str
    fix: tuple[bool, bool, bool, bool, bool, bool]


class AnalysisLineLoad(KernelModel):
    case: str
    kind: Literal["line"] = "line"
    element: str
    w_n_per_m: tuple[float, float, float]


class AnalysisPointLoad(KernelModel):
    case: str
    kind: Literal["point"] = "point"
    element: str
    position: float  # fraction of element length from the i-end, 0..1
    p_n: tuple[float, float, float]


AnalysisLoad = Annotated[AnalysisLineLoad | AnalysisPointLoad, Field(discriminator="kind")]


class Combo(KernelModel):
    name: str
    factors: dict[str, float]
    # Strength combos size members; service (unfactored) combos drive the
    # deflection limits (loads.py). Under ASD the §2.4 combos are service-level
    # and serve both; under LRFD the two diverge.
    purpose: Literal["strength", "service"] = "strength"


class AnalysisModel(KernelModel):
    """Self-contained and solvable with no store access (§7.1)."""

    schema_version: Literal[1] = 1
    provenance: DerivationProvenance
    nodes: list[AnalysisNode]
    elements: list[AnalysisElement]
    supports: list[AnalysisSupport]
    loads: list[AnalysisLoad]
    combos: list[Combo]


class DerivedModel(KernelModel):
    schema_version: Literal[1] = 1
    provenance: DerivationProvenance
    elements: list[Element]
    load_path: list[LoadPathEdge]
    open_decisions: list[OpenDecisionRef]
    bill: BillOfElements
    analysis: AnalysisModel | None  # absence is a valid state (partial models)
    override_attachments: list[OverrideAttachment] = Field(default_factory=list[OverrideAttachment])


# -- mutable working representation -----------------------------------------------


@dataclass
class _Member:
    eid: str
    role: ElementRole
    family: str
    section: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    tributary_m: float | None
    grade: str | None = None
    design_method: Literal["ASD", "LRFD"] = "ASD"
    supports: list[str] = field(default_factory=list[str])
    intent: list[IntentInstance] = field(default_factory=list[IntentInstance])
    line_load_by_case: dict[str, float] = field(default_factory=dict[str, float])
    flexural: bool = False
    e_pa: float | None = None
    overridden: dict[str, OverrideProvenance] = field(default_factory=dict[str, OverrideProvenance])


@dataclass
class _FramingContext:
    decision: Decision
    params: GravityFramingStrategyParams
    bearing_line_ids: tuple[str, str]
    joist_span_m: float
    beam_eid_by_line: dict[str, str]
    joists: list[tuple[str, float]]  # (eid, position along layout axis, m)
    loads_dids: list[str]


@dataclass(frozen=True)
class _FramingVocab:
    """The tier vocabulary a three-tier gravity frame is derived with. Wood and
    steel share the geometry rule (``_derive_three_tier``) and differ only here:
    which axis the infill members span, their spacing, the material engine and
    grade, the design method, and the role/eid-token/section of each of the
    three tiers (infill → mid → column)."""

    span_axis: Literal["x", "y"]
    spacing_m: float
    family: str
    grade: str
    design_method: Literal["ASD", "LRFD"]
    infill_role: ElementRole
    infill_token: str
    infill_section: str
    mid_role: ElementRole
    mid_token: str
    mid_section: str
    column_role: ElementRole
    column_token: str
    column_section: str


@dataclass
class _ThreeTier:
    """The tier-neutral result of the shared geometry rule (wood wraps it into a
    ``_FramingContext`` for the opening rule; steel discards it)."""

    bearing_line_ids: tuple[str, str]
    span_m: float
    mid_eid_by_line: dict[str, str]
    infills: list[tuple[str, float]]  # (eid, position along layout axis, m)
    loads_dids: list[str]


def derive(
    snapshot: ResolvedSnapshot,
    *,
    snapshot_hash: str,
    derivation_version: int = DERIVATION_VERSION,
) -> DerivedModel:
    if derivation_version != DERIVATION_VERSION:
        raise DerivationError(
            f"derivation version {derivation_version} is not available (have {DERIVATION_VERSION})"
        )

    decisions = dict(sorted(snapshot.decisions.items()))
    open_refs = [
        OpenDecisionRef(did=d.did, kind=d.kind, title=d.title)
        for d in decisions.values()
        if d.state == "open"
    ]
    resolved = [d for d in decisions.values() if d.state == "resolved"]

    members: dict[str, _Member] = {}
    framings: list[_FramingContext] = []

    for decision in resolved:
        if decision.kind == "gravity_framing_strategy":
            framings.append(_derive_framing(decision, decisions, members))
        elif decision.kind == "steel_framing_strategy":
            _derive_steel_framing(decision, decisions, members)
    for decision in resolved:
        if decision.kind == "opening":
            _derive_opening(decision, decisions, members, framings)
    for decision in resolved:
        if decision.kind == "lateral_strategy":
            _derive_lateral(decision, decisions, members)
    for decision in resolved:
        if decision.kind == "exception":
            _apply_exception(decision, members)

    # Composition rule (§5): derivation runs entirely on decisions, *then* the
    # override set is applied as a final substitution pass, *then* downstream
    # artifacts are computed from the overridden model.
    override_attachments = _apply_overrides(members, snapshot.overrides)

    ordered = [members[eid] for eid in sorted(members)]
    elements = [
        Element(
            eid=m.eid,
            role=m.role,
            family=m.family,
            section=m.section,
            grade=m.grade,
            design_method=m.design_method,
            start=Point(x=_length_m(m.start[0]), y=_length_m(m.start[1]), z=_length_m(m.start[2])),
            end=Point(x=_length_m(m.end[0]), y=_length_m(m.end[1]), z=_length_m(m.end[2])),
            length=_length_m(_dist(m.start, m.end)),
            tributary_width=None if m.tributary_m is None else _length_m(m.tributary_m),
            supports=sorted(m.supports),
            intent=m.intent,
            overridden=m.overridden,
        )
        for m in ordered
    ]
    load_path = sorted(
        (LoadPathEdge(bearing=m.eid, on=s) for m in ordered for s in m.supports),
        key=lambda e: (e.bearing, e.on),
    )
    provenance = DerivationProvenance(snapshot=snapshot_hash, derivation_version=derivation_version)
    return DerivedModel(
        provenance=provenance,
        elements=elements,
        load_path=load_path,
        open_decisions=open_refs,
        bill=_bill(elements, load_path),
        analysis=_analysis(ordered, provenance, _combo_set(resolved)),
        override_attachments=override_attachments,
    )


# -- rule: three-tier gravity framing (wood + steel share one geometry) ----------------


def _derive_framing(
    decision: Decision,
    decisions: dict[str, Decision],
    members: dict[str, _Member],
) -> _FramingContext:
    """Wood gravity framing: joists on beams on posts (design doc 0001 §3). The
    geometry is the shared three-tier rule; this wraps its result into the
    context the opening rule consumes (headers are induced over wood framing)."""
    params = parse_params(decision)
    assert isinstance(params, GravityFramingStrategyParams)
    vocab = _FramingVocab(
        span_axis=params.joist_axis,
        spacing_m=params.joist_spacing.si_mag,
        family=params.member_family,
        grade=params.member_grade,
        design_method="ASD",
        infill_role="joist",
        infill_token="jst",
        infill_section=params.joist_section,
        mid_role="beam",
        mid_token="bm",
        mid_section=params.beam_section,
        column_role="post",
        column_token="pst",
        column_section=params.post_section,
    )
    tier = _derive_three_tier(decision, decisions, members, params.region, vocab)
    return _FramingContext(
        decision=decision,
        params=params,
        bearing_line_ids=tier.bearing_line_ids,
        joist_span_m=tier.span_m,
        beam_eid_by_line=tier.mid_eid_by_line,
        joists=tier.infills,
        loads_dids=tier.loads_dids,
    )


def _derive_steel_framing(
    decision: Decision,
    decisions: dict[str, Decision],
    members: dict[str, _Member],
) -> None:
    """Steel gravity framing (ADR 0008): infill beams on girders on columns —
    the same three-tier geometry as wood, designed AISC/LRFD with the roof deck
    bracing the beams continuously. Not wrapped for the opening rule; steel
    headers are a later increment."""
    params = parse_params(decision)
    assert isinstance(params, SteelFramingStrategyParams)
    vocab = _FramingVocab(
        span_axis=params.beam_axis,
        spacing_m=params.beam_spacing.si_mag,
        family=params.member_family,
        grade=params.member_grade,
        design_method="LRFD",
        infill_role="beam",
        infill_token="bm",
        infill_section=params.beam_section,
        mid_role="girder",
        mid_token="gdr",
        mid_section=params.girder_section,
        column_role="column",
        column_token="col",
        column_section=params.column_section,
    )
    _derive_three_tier(decision, decisions, members, params.region, vocab)


def _derive_three_tier(
    decision: Decision,
    decisions: dict[str, Decision],
    members: dict[str, _Member],
    region: GridRegion,
    vocab: _FramingVocab,
) -> _ThreeTier:
    """Infill members span the bearing lines at a spacing, bearing on mid
    members that run along the perpendicular lines, bearing on columns at the
    region corners. Wood and steel differ only in ``vocab``; the eid grammar
    (ADR 0005) and tributary tiling are proven once, here."""
    lines = _grid_lines_in_deps(decision, decisions)
    for ref in (region.x_from, region.x_to, region.y_from, region.y_to):
        if ref not in lines:
            raise DerivationError(
                f"framing {decision.did}: line {ref} not defined by any grid among deps"
            )

    x0, x1 = sorted((lines[region.x_from][1], lines[region.x_to][1]))
    y0, y1 = sorted((lines[region.y_from][1], lines[region.y_to][1]))
    layout_axis: str
    if vocab.span_axis == "y":
        span_lines = (region.y_from, region.y_to)
        layout_lines = (region.x_from, region.x_to)
        span_m, layout_m = y1 - y0, x1 - x0
        layout_axis = "x"
    else:
        span_lines = (region.x_from, region.x_to)
        layout_lines = (region.y_from, region.y_to)
        span_m, layout_m = x1 - x0, y1 - y0
        layout_axis = "y"
    if span_m <= 0.0 or layout_m <= 0.0:
        raise DerivationError(f"framing {decision.did}: region has zero extent")
    spacing_m = vocab.spacing_m
    if spacing_m <= 0.0:
        raise DerivationError(f"framing {decision.did}: infill spacing must be positive")

    elevation_m = _elevation_in_deps(decision, decisions)
    loads = _area_loads_in_deps(decision, decisions)
    loads_dids = sorted(
        d.did
        for d in (decisions[dep] for dep in decision.deps if dep in decisions)
        if d.kind == "load_assumptions" and d.state == "resolved"
    )
    carries = [IntentRelation(role="carries", target=LoadTarget(load=did)) for did in loads_dids]
    e_pa = _grade_e(vocab.family, vocab.grade, decision.did)

    def gravity_intent() -> IntentInstance:
        return IntentInstance(
            category="gravity_load_path",
            relations=list(carries),
            provenance=IntentProvenance(source="derived", inducer=decision.did),
        )

    def serviceability_intent() -> IntentInstance:
        # Review Q3: L/360 live and L/240 total are hard limits; the solve-time
        # deflection checks cite this instance (ADR 0004).
        return IntentInstance(
            category="serviceability",
            payload={"live": "L/360", "total": "L/240"},
            provenance=IntentProvenance(source="derived", inducer=decision.did),
        )

    # ADR 0005 E2: the ordinal counting origin is the bounding line whose
    # line-id token sorts first — invariant under every geometric edit.
    origin_line = min(layout_lines)
    origin_m = lines[origin_line][1]
    far_m = lines[layout_lines[0] if layout_lines[1] == origin_line else layout_lines[1]][1]
    direction = 1.0 if far_m >= origin_m else -1.0

    positions = [i * spacing_m for i in range(int(layout_m / spacing_m) + 1)]
    if layout_m - positions[-1] > 1e-9:
        positions.append(layout_m)

    span_low = min(lines[span_lines[0]][1], lines[span_lines[1]][1])
    span_anchor = "-".join(sorted(span_lines))
    infills: list[tuple[str, float]] = []
    for ordinal, distance in enumerate(positions):
        left = distance - positions[ordinal - 1] if ordinal > 0 else 0.0
        right = positions[ordinal + 1] - distance if ordinal + 1 < len(positions) else 0.0
        tributary = (left + right) / 2.0
        coord = origin_m + direction * distance
        anchor = f"{span_anchor}.{origin_line}+{ordinal:03d}"
        eid = segment(vocab.infill_token, decision.did, anchor)
        if layout_axis == "x":
            start = (coord, span_low, elevation_m)
            end = (coord, span_low + span_m, elevation_m)
        else:
            start = (span_low, coord, elevation_m)
            end = (span_low + span_m, coord, elevation_m)
        members[eid] = _Member(
            eid=eid,
            role=vocab.infill_role,
            family=vocab.family,
            section=vocab.infill_section,
            grade=vocab.grade,
            design_method=vocab.design_method,
            start=start,
            end=end,
            tributary_m=tributary,
            intent=[gravity_intent(), serviceability_intent()],
            line_load_by_case={case: q * tributary for case, q in loads.items()},
            flexural=True,
            e_pa=e_pa,
        )
        infills.append((eid, coord))

    layout_low = min(origin_m, far_m)
    layout_anchor = "-".join(sorted(layout_lines))
    mid_eid_by_line: dict[str, str] = {}
    for bearing_line in span_lines:
        eid = segment(vocab.mid_token, decision.did, f"{bearing_line}.{layout_anchor}")
        bearing_m = lines[bearing_line][1]
        if layout_axis == "x":
            start = (layout_low, bearing_m, elevation_m)
            end = (layout_low + layout_m, bearing_m, elevation_m)
        else:
            start = (bearing_m, layout_low, elevation_m)
            end = (bearing_m, layout_low + layout_m, elevation_m)
        members[eid] = _Member(
            eid=eid,
            role=vocab.mid_role,
            family=vocab.family,
            section=vocab.mid_section,
            grade=vocab.grade,
            design_method=vocab.design_method,
            start=start,
            end=end,
            tributary_m=span_m / 2.0,
            intent=[gravity_intent(), serviceability_intent()],
            line_load_by_case={case: q * span_m / 2.0 for case, q in loads.items()},
            flexural=True,
            e_pa=e_pa,
        )
        mid_eid_by_line[bearing_line] = eid

    columns_by_corner: dict[tuple[str, str], str] = {}
    if elevation_m > 0.0:
        for span_line in span_lines:
            for layout_line in layout_lines:
                anchor = ".".join(sorted((span_line, layout_line)))
                eid = segment(vocab.column_token, decision.did, anchor)
                if layout_axis == "x":
                    xy = (lines[layout_line][1], lines[span_line][1])
                else:
                    xy = (lines[span_line][1], lines[layout_line][1])
                members[eid] = _Member(
                    eid=eid,
                    role=vocab.column_role,
                    family=vocab.family,
                    section=vocab.column_section,
                    grade=vocab.grade,
                    design_method=vocab.design_method,
                    start=(xy[0], xy[1], 0.0),
                    end=(xy[0], xy[1], elevation_m),
                    tributary_m=None,
                    intent=[gravity_intent()],
                    e_pa=e_pa,
                )
                columns_by_corner[(span_line, layout_line)] = eid
        for bearing_line, mid_eid in mid_eid_by_line.items():
            members[mid_eid].supports = sorted(
                columns_by_corner[(bearing_line, layout_line)] for layout_line in layout_lines
            )

    for infill_eid, _ in infills:
        members[infill_eid].supports = sorted(mid_eid_by_line.values())

    return _ThreeTier(
        bearing_line_ids=span_lines,
        span_m=span_m,
        mid_eid_by_line=mid_eid_by_line,
        infills=infills,
        loads_dids=loads_dids,
    )


# -- rule: opening induces a header ---------------------------------------------------


def _derive_opening(
    decision: Decision,
    decisions: dict[str, Decision],
    members: dict[str, _Member],
    framings: list[_FramingContext],
) -> None:
    params = parse_params(decision)
    assert isinstance(params, OpeningParams)
    lines = _grid_lines_in_deps(decision, decisions)
    for ref in (params.wall_line, params.offset_from):
        if ref not in lines:
            raise DerivationError(
                f"opening {decision.did}: line {ref} not defined by any grid among deps"
            )
    wall_axis, wall_offset_m = lines[params.wall_line]
    from_axis, from_offset_m = lines[params.offset_from]
    if from_axis == wall_axis:
        raise DerivationError(
            f"opening {decision.did}: offset_from must reference a line crossing the wall"
        )

    start_m = from_offset_m + params.offset.si_mag
    end_m = start_m + params.width.si_mag
    if params.width.si_mag <= 0.0:
        raise DerivationError(f"opening {decision.did}: width must be positive")

    # The enclosing framing: a declared-dep framing strategy bearing on this wall.
    framing = next(
        (
            f
            for f in framings
            if f.decision.did in decision.deps and params.wall_line in f.bearing_line_ids
        ),
        None,
    )
    if framing is None:
        return  # opening in a wall that carries no declared framing: no header induced

    loads = _area_loads_in_deps(decision, decisions)
    tributary = framing.joist_span_m / 2.0
    header_z = params.height.si_mag
    header_eid = segment("hdr", decision.did, params.wall_line)
    beam_eid = framing.beam_eid_by_line[params.wall_line]

    redirected = [
        joist_eid
        for joist_eid, position in framing.joists
        if start_m - 1e-9 <= position <= end_m + 1e-9
    ]
    relations: list[IntentRelation] = [
        IntentRelation(role="redirects_load_around", target=DecisionTarget(decision=decision.did))
    ]
    relations += [
        IntentRelation(role="carries", target=EidTarget(eid=eid)) for eid in sorted(redirected)
    ]

    span0 = start_m - _HEADER_BEARING_M
    span1 = end_m + _HEADER_BEARING_M
    if wall_axis == "y":  # wall holds y constant; runs along x
        start = (span0, wall_offset_m, header_z)
        end = (span1, wall_offset_m, header_z)
    else:
        start = (wall_offset_m, span0, header_z)
        end = (wall_offset_m, span1, header_z)

    members[header_eid] = _Member(
        eid=header_eid,
        role="header",
        family=framing.params.member_family,
        section=framing.params.beam_section,
        grade=framing.params.member_grade,
        start=start,
        end=end,
        tributary_m=tributary,
        supports=[beam_eid],
        intent=[
            IntentInstance(
                category="gravity_load_path",
                payload={"redirects_around": decision.did},
                relations=relations,
                provenance=IntentProvenance(source="derived", inducer=decision.did),
            ),
            IntentInstance(
                category="serviceability",
                payload={"live": "L/360", "total": "L/240"},
                provenance=IntentProvenance(source="derived", inducer=decision.did),
            ),
        ],
        line_load_by_case={case: q * tributary for case, q in loads.items()},
        flexural=True,
        e_pa=_grade_e(
            framing.params.member_family, framing.params.member_grade, framing.decision.did
        ),
    )

    for joist_eid in redirected:
        joist = members[joist_eid]
        joist.supports = sorted({header_eid, *(s for s in joist.supports if s != beam_eid)})


# -- rule: lateral strategy (representational, review Q7) ------------------------------


def _derive_lateral(
    decision: Decision, decisions: dict[str, Decision], members: dict[str, _Member]
) -> None:
    params = parse_params(decision)
    assert isinstance(params, LateralStrategyParams)
    lines = _grid_lines_in_deps(decision, decisions)
    for wall_line in params.wall_lines:
        if wall_line not in lines:
            raise DerivationError(
                f"lateral strategy {decision.did}: line {wall_line} not defined by any "
                "grid among deps"
            )
        axis, offset_m = lines[wall_line]
        crossing = sorted(m for (a, m) in lines.values() if a != axis)
        if len(crossing) < 2:
            raise DerivationError(
                f"lateral strategy {decision.did}: wall on {wall_line} cannot be bounded "
                "(fewer than two crossing lines)"
            )
        low, high = crossing[0], crossing[-1]
        eid = segment("wallseg", decision.did, wall_line)
        start = (low, offset_m, 0.0) if axis == "y" else (offset_m, low, 0.0)
        end = (high, offset_m, 0.0) if axis == "y" else (offset_m, high, 0.0)
        members[eid] = _Member(
            eid=eid,
            role="wall_segment",
            family="wood_structural_panel",
            section="shear_wall",
            start=start,
            end=end,
            tributary_m=None,
            intent=[
                IntentInstance(
                    category="lateral_capacity",
                    provenance=IntentProvenance(source="derived", inducer=decision.did),
                )
            ],
        )


# -- rule: exception (targeted design override of derived output) ----------------------


def _apply_exception(decision: Decision, members: dict[str, _Member]) -> None:
    params = parse_params(decision)
    assert isinstance(params, ExceptionParams)
    target = members.get(params.target_eid)
    if target is None:
        raise DanglingExceptionError(decision.did, params.target_eid, [])
    if params.field != "section":
        raise DerivationError(
            f"exception {decision.did}: field {params.field!r} is not overridable in phase 1"
        )
    if not isinstance(params.value, str):
        raise DerivationError(
            f"exception {decision.did}: a section exception's value must be a designation string"
        )
    target.section = params.value


# -- reality overrides: the final substitution pass (§5, ADR 0005) ----------------------


def _apply_overrides(
    members: dict[str, _Member], override_set: OverrideSet
) -> list[OverrideAttachment]:
    attachments: list[OverrideAttachment] = []
    for override in sorted(override_set.overrides, key=lambda o: (o.target.eid, o.target.field)):
        member = members.get(override.target.eid)
        if member is None:
            # Dangling: reality that no longer attaches to the model. Warn,
            # stay inert, propose near-matches when a surveyed anchor exists.
            attachments.append(
                OverrideAttachment(
                    target=override.target,
                    state="dangling",
                    provenance=override.provenance,
                    candidates=_near_candidates(members, override.surveyed_anchor),
                )
            )
            continue

        distance: float | None = None
        if override.surveyed_anchor is not None:
            distance = _point_segment_distance(
                _anchor_point(override.surveyed_anchor), member.start, member.end
            )
            if distance > _tolerance_m(override):
                # Displaced: the eid persists but the geometry moved out from
                # under the surveyed point — applying the measurement would
                # risk attributing it to the wrong physical member. Inert.
                attachments.append(
                    OverrideAttachment(
                        target=override.target,
                        state="displaced",
                        provenance=override.provenance,
                        distance_m=distance,
                    )
                )
                continue

        _substitute(member, override)
        attachments.append(
            OverrideAttachment(
                target=override.target,
                state="attached",
                provenance=override.provenance,
                distance_m=distance,
            )
        )
    return attachments


def _substitute(member: _Member, override: Override) -> None:
    if override.target.field != "section":
        raise DerivationError(
            f"override on {override.target.eid}: field {override.target.field!r} "
            "is not overridable in phase 1"
        )
    if not isinstance(override.value, str):
        raise DerivationError(
            f"override on {override.target.eid}: a section override's value must be "
            "a designation string"
        )
    member.section = override.value
    member.overridden[override.target.field] = override.provenance


def _tolerance_m(override: Override) -> float:
    anchor = override.surveyed_anchor
    assert anchor is not None
    if anchor.tolerance is not None:
        return anchor.tolerance.si_mag
    return _CONFIDENCE_TOLERANCE_M[override.provenance.confidence]


def _anchor_point(anchor: SurveyedAnchor) -> tuple[float, float, float]:
    return (anchor.x.si_mag, anchor.y.si_mag, anchor.z.si_mag)


def _near_candidates(members: dict[str, _Member], anchor: SurveyedAnchor | None) -> list[str]:
    if anchor is None:
        return []
    point = _anchor_point(anchor)
    scored = sorted(
        (distance, eid)
        for eid, member in members.items()
        if (distance := _point_segment_distance(point, member.start, member.end))
        <= _CANDIDATE_RADIUS_M
    )
    return [eid for _, eid in scored[:_MAX_CANDIDATES]]


def _point_segment_distance(
    p: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
    ab_sq = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
    t = (
        0.0
        if ab_sq == 0.0
        else max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / ab_sq))
    )
    closest = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
    return _dist(p, closest)


# -- shared context resolution (strictly through declared deps) -------------------------


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


def _elevation_in_deps(decision: Decision, decisions: dict[str, Decision]) -> float:
    elevations = [
        level.elevation.si_mag
        for dep in decision.deps
        if (d := decisions.get(dep)) is not None and d.kind == "levels" and d.state == "resolved"
        for level in _levels(d)
    ]
    return max(elevations, default=0.0)


def _levels(decision: Decision) -> list[Level]:
    params = parse_params(decision)
    assert isinstance(params, LevelsParams)
    return list(params.levels)


def _area_loads_in_deps(decision: Decision, decisions: dict[str, Decision]) -> dict[str, float]:
    loads: dict[str, float] = {}
    for dep in decision.deps:
        dep_decision = decisions.get(dep)
        if dep_decision is None or dep_decision.kind != "load_assumptions":
            continue
        params = parse_params(dep_decision)
        if isinstance(params, LoadAssumptionsParams):
            for area_load in params.area_loads:
                loads[area_load.case] = loads.get(area_load.case, 0.0) + area_load.magnitude.si_mag
    return loads


def _grade_e(family: str, grade: str, did: str) -> float:
    engine = engine_for(family)
    e_pa = engine.elastic_modulus_pa(grade)
    if e_pa is None:
        raise DerivationError(
            f"framing {did}: {engine.family} grade {grade!r} has no reference modulus"
        )
    return e_pa


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5


# -- bill of elements ---------------------------------------------------------------


def _bill(elements: list[Element], load_path: list[LoadPathEdge]) -> BillOfElements:
    grouped: dict[tuple[ElementRole, str, str], tuple[int, float]] = {}
    for element in elements:
        key = (element.role, element.family, element.section)
        count, total = grouped.get(key, (0, 0.0))
        grouped[key] = (count + 1, total + element.length.si_mag)
    lines = [
        BillLine(
            role=role,
            family=family,
            section=section,
            count=count,
            total_length=_length_m(total),
        )
        for (role, family, section), (count, total) in sorted(grouped.items())
    ]
    catalog = families()
    crane_picks = sum(
        engine_for(element.family).crane_picks_per_member()
        for element in elements
        if element.family in catalog  # induced non-catalog members (wall panels) do not pick
    )
    return BillOfElements(
        lines=lines,
        countables=Countables(
            piece_count=len(elements),
            connection_count=len(load_path),
            crane_picks=crane_picks,
        ),
    )


# -- analysis artifact (§7.1) ---------------------------------------------------------


def _combo_set(resolved: list[Decision]) -> str:
    """The combination set the load assumptions select (ADR 0007 / loads.py).
    Phase 1 has one load_assumptions decision; default if none is present."""
    for decision in resolved:
        if decision.kind == "load_assumptions":
            params = parse_params(decision)
            if isinstance(params, LoadAssumptionsParams):
                return params.combo_set
    return "ASCE7-22-2.4-ASD"


def _analysis(
    members: list[_Member], provenance: DerivationProvenance, combo_set: str
) -> AnalysisModel | None:
    flexural = [m for m in members if m.flexural]
    if not flexural:
        return None  # a valid state, not a failure (partial models)

    nodes: list[AnalysisNode] = []
    elements: list[AnalysisElement] = []
    supports: list[AnalysisSupport] = []
    loads: list[AnalysisLoad] = []
    cases: set[str] = set()

    for index, member in enumerate(flexural, start=1):
        section = engine_for(member.family).section_properties(member.section)
        if section is None:
            raise DerivationError(
                f"element {member.eid}: unknown section designation {member.section!r}"
            )
        assert member.e_pa is not None
        node_start, node_end = f"n{2 * index - 1}", f"n{2 * index}"
        element_id = f"e{index}"
        nodes.append(AnalysisNode(id=node_start, xyz_m=member.start))
        nodes.append(AnalysisNode(id=node_end, xyz_m=member.end))
        elements.append(
            AnalysisElement(
                id=element_id,
                type="frame",
                nodes=(node_start, node_end),
                E_pa=member.e_pa,
                A_m2=section.area_m2,
                I_strong_m4=section.i_strong_m4,
                I_weak_m4=section.i_weak_m4,
                releases=Releases(start="pin", end="pin"),
                source_eid=member.eid,
            )
        )
        fix = (True, True, True, False, False, False)
        supports.append(AnalysisSupport(node=node_start, fix=fix))
        supports.append(AnalysisSupport(node=node_end, fix=fix))
        for case in sorted(member.line_load_by_case):
            w = member.line_load_by_case[case]
            loads.append(
                AnalysisLineLoad(
                    case=case, kind="line", element=element_id, w_n_per_m=(0.0, 0.0, -w)
                )
            )
            cases.add(case)

    return AnalysisModel(
        provenance=provenance,
        nodes=nodes,
        elements=elements,
        supports=supports,
        loads=loads,
        combos=[
            Combo(name=c.name, factors=c.factors, purpose=c.purpose)
            for c in combos_for(combo_set, frozenset(cases))
        ],
    )
