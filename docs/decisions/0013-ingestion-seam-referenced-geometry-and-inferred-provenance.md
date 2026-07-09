# 0013 — The ingestion seam: referenced geometry and inferred→ratify provenance

**Status:** Accepted (2026-07-09, product owner directed; steered by note 0004,
graduates design doc 0005 for the scope delivered). Realizes the vision's "real
constraints arrive as drawings/models, not just conversation" and widens ADR
0011's standing requirement ("intent capturable by the AI surface, enforceable
against all future changesets") from *conversation* to *drawings/models*. Relates
to ADR 0004 (open-registry posture), ADR 0005 (anchor vocabulary; displaced/
dangling), ADR 0009 (the LLM propose-only seam), ADR 0011 (`ProjectConstraint`,
the predicate registry, `check_project_constraints` as stage 5), and design doc
0005 (the ingestion proposal this graduates).

## Context

Everything upstream begins where the vision demo cheats: from already-abstracted
structural text ("west 40 ft column-free"). Real projects begin with an
architect's drawings and a BIM model — none of it structural. The naive move,
parsing the architect's model *into* our decision graph, is the lossy,
intent-manufacturing direction the charter's non-goals warn against: it yields a
graph of as-explicit geometry with fake intent, a worse IFC, and it kills the
trust property everything else earns (design doc 0005 §1–2).

Note 0004 fixed the shape: **ingest architecture as constraints; never parse it
into decisions.** The AI proposes a structural *reading* of the drawing; the
engineer *ratifies*. Nothing a reading produces may enforce or bind an exploration
until a human confirms it. The sprint's backbone is therefore not a vision model
but a **provenance taxonomy** — the discipline that already keeps a surveyed
override from masquerading as a derived value (ADR 0005), extended to the messy
front door. Design for the human-heavy case first: the seam is a success even when
the AI proposes little and the engineer authors most; the value is structured
capture, referenced geometry, and the ratification audit trail.

The taxonomy lands on **`ConstraintProvenance`**, not `IntentProvenance` (PO call).
Design doc 0005 §5 predates ADR 0011 and speaks of intent; note 0004 grounds the
sprint in `capture.py`, which emits `ProjectConstraint`s. This sprint infers
*constraints*; inferred *intent* (from reading a drawing directly onto elements)
is a later workstream, and `IntentProvenance` is left `authored | derived`.

## Decision

- **Constraint provenance is a discriminated union `authored | inferred`**
  (`objects.py`). `authored` (the engineer's will, or an LLM proposal reaching
  state only through the human/pipeline writer) is always binding. `inferred` (an
  ingestion-AI reading) carries a `basis` (the referenced-geometry version read,
  the sheet/region reference, the model's stated reason), a machine-reading
  `confidence` (`high | medium | low` — a new scale, not the survey buckets), and a
  nullable `ratified` record. The single predicate `provenance.is_binding` is
  `True` for authored and for inferred-once-ratified; `False` for inferred-
  unratified.

- **Inert by type until ratified** (resolves design doc 0005 open q2 in favor of
  *in-graph but inert*, mirroring how a displaced override stays inert in place).
  `check_project_constraints` (stage 5) skips a non-binding constraint, surfacing a
  `constraint_unratified` warning distinct from the dangling/unregistered
  `constraint_inert`. Because exploration candidates flow through the same stage 5,
  **one inertness rule covers both the changeset check and the
  `SpatialConstraintsPreservedConstraint` binding** — an unratified reading can
  neither reject a changeset nor make a candidate infeasible.

- **Ratification is a recorded human-authored event, not a silent promotion.**
  `RatifyConstraint(cid, ratified_by, ratified_at, edited?)` (a changeset op)
  promotes an inferred, unratified constraint. The kernel fills the
  `RatificationRecord` (who/when/`modified`); an optional `edited` constraint
  carries the engineer's correction of the reading (records `modified=True`) while
  the inferred `basis` and `confidence` — the read — are preserved. `source` stays
  `inferred`, so the audit trail keeps "the AI read this and the engineer agreed"
  distinct from "the engineer authored this outright". Only inferred, unratified
  constraints are ratifiable.

- **Referenced geometry is a first-class read-only kind** (`objects.py`).
  `ReferencedGeometry` carries a `ref_id` lineage, a `version`, `external`
  provenance (source file, sha256 hash, importer name+version, import date), and
  light-typed IFC grids/storeys — the entities IFC gives cleanly (design doc 0005
  §3, open q1). It is never a `Decision` and is never consumed by derivation, so it
  is excluded from the derivation cache key (`resolved_snapshot_hash`) exactly as
  constraints are. `Snapshot.referenced_geometry` (ref_id → hash) carries it; the
  write path gains `AddReferencedGeometry` (new lineage) and
  `ReissueReferencedGeometry` (existing lineage, strictly higher version).

- **A `ReferencedRegion` joins the ADR 0005 `Region` union** — a band off a grid
  line in referenced geometry, anchored by `(ref_id, anchor_grid)`, never
  coordinates. It resolves against the snapshot's referenced geometry; an
  unresolved reference (un-imported lineage, or an anchor grid removed on re-issue)
  is inert with a warning, never fatal — the override-like posture ADR 0011
  already takes for a deleted decision grid line.

- **Re-issue reconciliation is a diff at the re-issue commit** (`referenced.py`,
  `reconfirmations`). Because `ReissueReferencedGeometry` lands with both the old
  geometry (base snapshot) and the new (the op) in hand, the commit diffs grids and
  flags precisely the constraints whose anchor **moved** or was **removed**, as
  `referenced_reissue` warnings — the ADR 0005 displaced/dangling machinery at the
  architecture boundary. A moved anchor **keeps binding** at its new position (the
  point of anchoring by name); the warning is the "re-confirm this reading" signal,
  so a re-issue never silently diverges. A removed anchor also goes inert dangling
  at stage 5. (PO call: keep-enforcing + warn, over go-inert-until-reconfirmed — a
  hard clear-span must never silently stop binding mid-churn.)

- **Capture reads referenced geometry behind the ADR 0009 LLM seam**
  (`capture.py`). The input grows from an utterance to an utterance *and/or*
  referenced geometry; the `capture_*` tool vocabulary is unchanged (the tools
  gained optional `reason`/`confidence` fields used only on the ingestion path).
  With referenced geometry the model reads its grids and proposes `inferred`
  constraints anchored to real referenced gridlines; without it, conversation
  authoring is byte-identical to ADR 0011 (`authored`, decision-grid `OffsetBand`).
  The importer is an **adapter boundary**: an IFC grid/storey extract (adapter-
  local schema, never persisted) maps deterministically to `ReferencedGeometry`;
  no IFC/DWG/vision type crosses into the kernel, and a real `ifcopenshell`
  importer plugs in at the same seam later. CI drives the whole path on
  `FakeLLMClient` — no vision model, no secrets.

## Consequences

- **Garbage-in is bounded by ratification, not parser quality.** A bad reading is
  an unratified (inert) or pipeline-rejected proposal; it can never become corrupt
  authored intent. The reader may be imperfect while the graph stays clean by
  construction. Propose-only holds (the pipeline is the sole writer; ratification
  is an ordinary human changeset), and replay-by-record holds (the inferred
  proposal and its ratification are persisted events; replay never re-calls the
  reader).
- **Four honestly-distinguished fact origins** now coexist and none can masquerade
  as another: `external` (referenced geometry), `inferred` (machine-proposed,
  unratified), `authored` (engineer's will, incl. ratified inferences), `derived`
  (the kernel's own). Each is queryable.
- **The design-for-the-human-heavy-case bet is honored:** even with the stub
  reader, the engineer can import a model, get a structured proposal to accept or
  correct, and carry a full audit trail of who read what and who agreed.
- **Deliberately out of scope this sprint** (design doc 0005 §6–7 futures): real
  sheet/raster/DWG understanding and multimodal reading; conversation-as-referenced
  -source (open q4); inferred *intent* over elements (this sprint infers
  constraints only); decisions declaring the referenced region they frame; and a
  re-confirm *action* that clears a `referenced_reissue` flag (today the engineer
  re-captures or re-authors). The seam and its provenance are proven on the
  cleanest input; the hard reading work lands later on a foundation already sound.
