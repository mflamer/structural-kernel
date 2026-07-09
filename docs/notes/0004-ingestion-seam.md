# Note 0004 — Sprint steer: the ingestion seam (drawings in, `inferred`→ratify)

**Kind:** Sprint-steer note (product-owner direction, ahead of the increment).
**Raised:** 2026-07-08, PO planning after sprints 4–5 (ADR 0011/0012).
**Realizes:** design doc 0005 (the deferred ingestion seam), now scheduled.
**Concerns:** `capture.py` (the conversation seam to extend), `objects.py` (`IntentProvenance`/constraint provenance), ADR 0009 (LLM seam), ADR 0011 (`ProjectConstraint`), ADR 0005 (anchors / referenced-geometry regions).
**Status:** Open — apply before speccing the sprint.

## Why this is the next sprint
Everything else deferred *deepens* what exists (more member types, lateral, concrete, richer feedback). This is the only direction that opens a **new capability surface** and closes the gap the PO raised directly: real structural constraints arrive as *drawings, models, and conversation* — and today capture can only take conversation (`capture.py` consumes an `utterance`, text only). Until drawings can come in, the system begins where the vision demo cheats: from already-abstracted text. This sprint is what makes it usable on a real project.

## The one principle that governs this sprint
**Ingest architecture as constraints; never parse it into decisions.** (Design doc 0005 §2.) The AI *proposes* structural readings of the drawing; the engineer *ratifies*. Nothing a drawing-reading produces may enforce or bind an exploration until a human confirms it. This is the propose-then-validate posture the whole system runs on (ADR 0009 proposer, ADR 0011 capture) — extended to the messy front door, with one addition: a provenance state for *unratified machine reading*. Get this wrong and low-confidence inferences masquerade as authored intent, which kills the trust property everything else earns. So the sprint's backbone is the provenance taxonomy, not the vision model.

## What extends, precisely (grounded in `capture.py`)
Capture today: `utterance: str` → LLM emits `capture_*` tool calls → each becomes an `AddConstraint` with `provenance = {"source": "authored", "captured_by": …}` → ordinary pipeline. Two precise extensions, nothing else structural:
1. **Input grows from text to text-plus-referenced-geometry.** The capture input becomes an utterance *and/or* referenced geometry (§ below). The tool vocabulary (`capture_clear_span`, `capture_min_bay`, and the registry behind them) is unchanged — the model still emits the same `capture_*` calls; it just now has a drawing/model to read them off of, not only a sentence.
2. **Provenance gains the `inferred`→ratify path.** A constraint proposed from a drawing commits with `source: "inferred"` plus `basis` (what was read — the referenced-geometry region / sheet reference + the model's stated reason), `confidence`, and `ratified: null`. **An `inferred`, unratified constraint is inert by type** — `propose` stage 5 (ADR 0011 enforcement) and the `SpatialConstraintsPreservedConstraint` binding both **skip** it; it cannot reject a changeset or make a candidate infeasible until ratified. Ratification is a recorded event (who, when, modified-or-not) that promotes it to `authored`-strength while the record keeps the distinction. (Design doc 0005 §5; resolves its open question 2 in favor of **in-graph but inert**, mirroring how a displaced override stays inert in place rather than vanishing.)
Conversation authoring is unchanged and stays `authored` — a spoken constraint is design will, not a reading. Only drawing/model-sourced proposals are `inferred`.

## Referenced geometry (the read surface)
To read a drawing into constraints, the drawing must first be *present* as referenced geometry (design doc 0005 §3): read-only, external-provenance context the constraints anchor to — **not** decisions.
- Start with the **cleanest real semantics**: IFC grids and levels/storeys import deterministically to referenced-geometry objects. That alone lets a captured region anchor to a real gridline-id (ADR 0005 anchors — a referenced-geometry region joins `OffsetBand`/`GridBoundedRegion`/`WholePlan`). DWG and raster sheets are a *later* step; do not lead with them.
- Referenced geometry is its own content-addressed, versioned kind stamped `external` (source file + hash + importer version + date). A constraint's region may reference it; a re-issued architectural model lands a new version and surfaces affected constraints for re-confirmation — the displaced/dangling machinery (ADR 0005), now at the architecture boundary.

## Design for the human-heavy case first (honest limits)
Reading a real sheet well enough to propose good constraints is research-grade (design doc 0005 §6). **The sprint is a success even if the AI proposes little and the engineer authors most** — the value is the structured capture, the referenced geometry, and the ratification audit trail. Sequence accordingly:
1. **Provenance first.** Extend constraint provenance to `authored | inferred` with the ratification record; make `inferred`+unratified inert in stage 5 and in the exploration binding. Pure-schema + validator; it is the foundation, and nothing inferred can be born without the right stamp. *(A `FakeLLMClient` returning a canned "inferred" proposal drives CI, exactly as capture and the proposer already do — no vision model in the test path.)*
2. **Referenced geometry as a kind**, IFC grids/levels first; the re-issue / re-confirm machinery.
3. **Capture reads referenced geometry**, still emitting the same `capture_*` ops, now `inferred`; the ratify action promoting to `authored`.
4. **Richer reading later** (DWG, raster sheets, sketch, full multimodal) — built on a foundation already sound without it.

## Scope guards (do not let the seam leak)
- **No vision-model or CAD/IFC/DWG type crosses into the kernel.** Reading lives behind the ADR 0009 LLM seam and an import adapter; the kernel receives referenced geometry + `capture_*` ops, never *how* they were read. (Mirror of the solver/material/renderer boundaries.)
- **Garbage-in is bounded by ratification, not parser quality.** A bad reading yields rejected/unratified proposals, never corrupt authored intent — so the reader may be imperfect while the graph stays clean by construction.
- **Still propose-only; the pipeline is the sole writer.** Ratification is a human-authored changeset like any other.
- **Replay-by-record holds:** the `inferred` proposal and its ratification are persisted events; replay reads them and never re-calls the vision model.

## Acceptance signals
- A constraint proposed from **referenced geometry** commits as `inferred`, is **inert** (a post in its region is *not* rejected, a candidate is *not* infeasible) until ratified, then enforces exactly as an authored one — proven by one test that a protected region does nothing before ratify and rejects after.
- Ratification records who/when/modified; the audit trail distinguishes "AI read it, engineer agreed" from "engineer authored it."
- An IFC grid/level import produces referenced geometry a captured region anchors to (a real gridline-id), stable under the ADR 0005 anchor rules.
- A re-issued referenced model surfaces an affected constraint for re-confirmation rather than silently diverging.
- **The whole path runs in CI on a `FakeLLMClient`** with no real vision model and no secrets — the ADR 0009/0011 discipline preserved.

## Deliberately out of scope this sprint
Real sheet/raster understanding, DWG semantics, sketch ingestion, and conversation-as-referenced-source (design doc 0005 open q4) — all later. This sprint delivers the *seam and its provenance*, proven on the cleanest input (IFC grids/levels) with a fake reader, so the hard multimodal work later lands on a foundation that is already trustworthy.
