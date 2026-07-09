# 0011 — Spatial structural constraints: a project-constraint primitive with a predicate registry

**Status:** Accepted (2026-07-08, product owner directed; reframed by note 0002).
Implements the vision's item 3 (conversational intent capture) and its standing
requirement ("intent must be capturable from conversation by the AI surface and
enforceable against all future changesets"). Relates to ADR 0004 (open registry
posture), ADR 0005 (anchor vocabulary), ADR 0009 (the LLM propose-only seam), and
design doc 0005 (the ingestion/ratification seam, still under review).

## Context

The increment began as "capture *the west 40 feet must be column-free* as a typed,
enforced intent." The PO's note 0002 rejected reasoning backward from that one
demo beat — a hand-fitted `clear_span` intent would do the demo and calcify, the
IFC failure mode in miniature. "The west 40 feet must be column-free" is not a
thing to encode; it is **one instance of a general class: a spatial structural
constraint.** The correct deliverable is the primitive, with clear-span and
min-bay as its first two instances — and the proof it is a primitive and not a
special case is that a third, unplanned predicate drops in as data.

Three findings from the note fixed the shape:

1. **The constraint precedes the structural system.** It constrains *whichever*
   system is chosen, so it cannot hang off a framing decision or an element that
   does not exist yet. It is a standing *project constraint* the exploration is
   searched against.
2. **A region is spatial reference, not a new coordinate scheme.** It belongs in
   the ADR 0005 anchor vocabulary (names, never coordinates): "the west 40 feet"
   is an offset band anchored to a stable line-id, which tracks when the line
   moves.
3. **"Forbidden support" is a predicate over derived elements**, the general
   shape of a checker with the same two-site treatment intent already has
   (commit-time topology where decidable; solve-time demand where not).

## Decision

- **A new first-class graph object, `ProjectConstraint`** (`objects.py`) — neither
  a `Decision` (it derives no geometry) nor element `intent` (no element to hang
  it on at capture time). It carries a `cid`, a `predicate` name, a `region`, a
  predicate `payload`, the natural-language `statement`, and `provenance`. It is
  committed and versioned: `Snapshot` gains a `constraints: {cid → hash}`
  collection, and the write path gains `AddConstraint` / `RemoveConstraint` ops.

- **The region is the ADR 0005 anchor vocabulary**, a discriminated union:
  `OffsetBand` (anchor line-id + extent + side — "the west 40 feet"),
  `GridBoundedRegion` (four line-ids), and `WholePlan` (unbounded). Extensible by
  construction — a referenced-geometry region (design doc 0005) is a future
  variant, no predicate changes.

- **An open predicate registry** (`constraints.py`), the ADR 0004 move applied to
  constraints: `(name, payload schema, check site, checker)`. `register_predicate`
  is the whole extension surface. Two phase-2 instances ship:
  `no_vertical_support_within` (clear-span — no post/column/bearing-wall inside
  the region) and `min_bay_spacing` (no two column/post lines closer than the
  minimum). A predicate declares its **check site**: `commit` (topology/geometry
  over the dry-run derived model) or `solve` (demand-dependent, reserved).

- **Enforced identically on every changeset**, as `propose` stage 5: after intent
  checks, every commit-site predicate runs over the derived model; a violation
  rejects the changeset with a structured `constraint_violation` citing the
  constraint (cid, predicate, the offending supports). Because exploration
  candidates are ordinary changesets, a candidate that puts a support in a
  protected region is rejected by the same stage and **never solved** — the
  vision's "41 rejected pre-solve, most put a column line in the protected zone."
  `SpatialConstraintsPreservedConstraint` makes that binding explicit and
  auditable in the exploration's constraint set, beside `IntentPreservedConstraint`;
  enforcement needs no exploration-side code.

- **Clear-span geometry is the *open* band.** A support exactly on a bounding line
  — the anchored perimeter, or the far line the clear span bears onto — is
  allowed; only supports interior to the protected strip are forbidden. Otherwise
  the span could never be carried. (This refines the literal "all vertical
  supports" scoping question toward buildability; flagged for PO confirmation.)

- **Conversational capture is the AI surface** (`capture.py`), reusing the ADR
  0009 LLM seam: given the utterance and the grid vocabulary, an `LLMClient`
  chooses `capture_clear_span` / `capture_min_bay` tool calls, which become
  ordinary `AddConstraint` ops through the normal validate pipeline. Propose-only
  by construction — a malformed capture (missing spacing, unknown predicate) is a
  recorded rejection, never a silent write. The captured constraint records its
  `statement` and `captured_by` (the client descriptor — the ADR 0009 model
  identity). Capture commits **authored** provenance; the `inferred`→ratify path
  is design doc 0005's separate ingestion workstream.

- **An unresolved anchor is inert, not fatal.** A constraint whose region line was
  deleted goes inert with a `constraint_inert` warning on the commit — the
  override-like posture (ADR 0005 dangling), never a hard error. The constraint
  persists until a human resolves it. (Project constraints are deliberately *not*
  wired into the E3 referential hard-fail that binds decisions.)

## Consequences

- **The extensibility test is a real test.** A third predicate, `clear_height_below`,
  written only as a test fixture, registers via `register_predicate` with its own
  payload schema and checker and is enforced by the unchanged pipeline. That is
  the acceptance signal the note calls the real proof the primitive generalizes.

- CI stays deterministic and secret-free: the `FakeLLMClient` drives capture in
  tests; the real `AnthropicClient` is the optional `llm` extra. All gates green
  (pyright strict, ruff, full pytest).

- `resolved_snapshot_hash` deliberately excludes constraints: they bind
  validation, not geometry, so two snapshots differing only in constraints share
  a derived model and its cache key. The committed `Snapshot` hash still covers
  them (commit identity is complete).

- **Deferred:** min-bay region scoping ("everywhere *else*", relative to the
  clear zone — today min-bay is whole-plan or an explicit region); the
  `inferred`→ratify ingestion seam (design doc 0005); solve-site spatial
  predicates; referenced-geometry regions; the cost-basis constraint from the
  vision (its own standing requirement). Domain items flagged for PO check: the
  open-band clear-span semantics above; min-bay over point supports only.

Supersedes nothing. Establishes the project-constraint object as a third fact
category in the graph (alongside decisions and overrides) and the predicate
registry as the open enforcement surface for spatial requirements.
