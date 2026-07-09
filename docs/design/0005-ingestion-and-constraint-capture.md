# 0005 — Ingestion and Constraint Capture: The Outside-World Seam

**Status:** Proposal, awaiting product-owner review. Companion to 0004
(outputs); this is the *input* seam. Graduates to an ADR if accepted; the
ingestion, capture, and provenance pieces would then land as separate
increments. **Nothing here is phase-2 exploration work** — it is the layer that
feeds the graph the exploration then operates on.
**Scope:** how architectural constraints (drawings, BIM models, conversation)
become referenced geometry and authored structural intent *without* corrupting
the "the model is the reasoning" thesis; the provenance taxonomy that keeps
inferred, authored, referenced, and derived facts distinguishable; and the
human-ratified capture loop. Out of scope: the specific vision models or CAD
parsers used (engine detail, behind adapters); output projection (0004);
structural authoring itself (already built).

## 1. The problem this seam exists to solve

The vision demo (`vision.md`) begins "120' × 80' shell, west 40 feet
column-free" — text, already abstracted into structural terms. Real projects do
not begin there. **Structural constraints always arrive from someone else, as
architectural drawings, a BIM model, and a conversation — none of it structural.**
The gap between "here is the architect's floor plan" and "here is a decision
graph of framing strategies and load paths" is the real front-end product
problem, and it is currently hand-waved.

The naive approach — parse the architect's model *into* our decision graph — is
the lossy, non-invertible direction 0001's non-goals and the output discussion
already warned against. A finished model is derived geometry with the reasoning
stripped out; inferring the decisions that produced it manufactures intent that
was never there. Done silently, it yields a graph of "as-explicit" geometry with
fake intent — a worse IFC — and it quietly kills the one property that makes this
system trustworthy.

## 2. The reframe: ingest architecture as *constraints*, author structure against them

The resolution is a change of verb. **We do not parse architecture into
structure. We ingest architecture as the constraint surface, and conduct a
structured conversation — over the drawings — in which the engineer authors
structural intent against it.** The drawing is never the source of decisions; it
is the shared reference the human and the AI point at while the human decides.

The reasoning still originates with the engineer. The AI makes capturing it fast;
the drawings make it concrete. That is what keeps the thesis intact.

Three layers, and only the middle one is new research-grade work:

```
architect's DWG / IFC / Revit  +  kickoff conversation  +  sketches
          │
          ▼
[A] Geometry ingestion ─────► referenced geometry (read-only, external provenance)
          │                     grids, levels, slab edges, envelope, shafts, no-go zones
          ▼
[B] Constraint capture ─────► PROPOSED structural constraints & intent
      (multimodal AI proposes; the engineer ratifies)   ← the new seam
          │
          ▼
[C] Structural authoring ──► committed decisions → derivation → exploration
      (already built)
```

## 3. Layer A — geometry ingestion (facts, not inference)

The architect's geometry enters as **referenced geometry**: read-only context
the structural decisions attach to, never structural decisions themselves. This
is the "external geometry referencing" 0001 marked *deferred, not dropped*, and
the authority boundary is exactly as framed — **we own structure, we consume
everything else.**

- Mostly deterministic, not AI: IFC carries grids, levels, storeys, and spaces as
  real entities; a Revit/IFC import maps those to referenced-geometry objects
  directly. DWG is messier (lines and text, little semantics) and needs more
  interpretation — but interpretation of *shape*, not of structural intent.
- Referenced geometry is its own persisted kind, content-addressed, versioned,
  and stamped with **external** provenance (source file, its hash, importer
  version, import date). It never becomes a `Decision`. Structural decisions
  *reference* it (a framing strategy declares the referenced region it frames,
  the grid it borrows), the same declared-dependency discipline derivation
  already enforces.
- When the referenced model is re-issued (architecture always changes), a new
  referenced-geometry version lands; decisions referencing the changed parts
  surface for re-confirmation — the same displaced/dangling machinery overrides
  already use (ADR 0005), now at the architecture boundary. "The architect moved
  grid C" becomes a tracked, reasoned event, not a silent divergence.

## 4. Layer B — constraint capture (the new seam; propose-then-ratify)

This is where multimodal AI earns its place, and the literal answer to "text,
sketches, or a combination?": **combination — drawings, marked-up sketches, the
referenced geometry, and the conversation all feed it — and the output is
*proposed* structural constraints the engineer ratifies.** Never intent silently
extracted from a drawing.

The loop, which is the same propose→validate→commit posture as the whole system:

1. The vision-capable LLM reads the actual sheets, the referenced geometry, and
   the kickoff conversation, and **proposes candidate structural constraints and
   intent**: "this ~40' zone reads as column-free," "these appear to be the
   gravity-bearing lines," "this shaft interrupts framing here," "this dimension
   suggests a transfer condition."
2. Each proposal is surfaced to the engineer **anchored to the geometry it came
   from** (this callout, this region, this line), with the AI's stated basis.
3. The engineer **confirms, corrects, or rejects** each — and adds what only the
   conversation carries and no drawing shows ("owner wants exposed timber,"
   "budget rules out a transfer slab," "this wall is coming out in phase 2").
4. Confirmed constraints commit as **authored** intent/decisions through the
   ordinary pipeline. They are now first-class structural facts, and layer C
   proceeds.

Nothing an LLM proposes reaches the graph as authored intent without the
engineer's ratification. The AI is a fast draftsman of structural reading; the
PE is the sole authority. Identical in spirit to the LLM *proposer* in the
exploration loop (ADR 0009) — propose-only, human/pipeline is the writer — moved
to the front of the process.

## 5. The provenance taxonomy (the backbone)

The seam lives or dies on one distinction: **a low-confidence machine inference
must never be indistinguishable from an engineer's authored decision.** The
kernel already has the beginning of this — `IntentProvenance.source` is today a
closed `authored | derived` union (`objects.py`). This seam adds a third origin
and a ratification record.

Proposed extension:

- **`IntentProvenance.source` becomes `authored | derived | inferred`.**
  - `derived` — produced by a derivation rule from its inducer (unchanged;
    undanglable, regenerates with the model).
  - `authored` — committed by a human as design will (unchanged).
  - `inferred` — proposed by the ingestion AI from referenced geometry or
    drawings. **An `inferred` instance may never be enforced or exploration-
    binding until it is ratified into `authored`.** It carries, additionally:
    `basis` (what the AI read — sheet + region + reasoning), `confidence`, and
    `ratified` (`null` until an engineer acts).
- **Ratification is a recorded event, not a silent promotion.** When the engineer
  confirms an inferred constraint, the commit records who ratified it, when, and
  whether they modified it — the audit trail distinguishes "the AI read this and
  the engineer agreed" from "the engineer authored this outright." Both end as
  `authored`-strength facts; the *record* remembers the difference.
- **Referenced geometry carries `external` provenance** (source, file hash,
  importer) — parallel to how a surveyed override carries `measured` provenance.
  A model now has four honestly-distinguished fact origins: **external** (the
  architect's, read-only), **inferred** (machine-proposed, unratified),
  **authored** (engineer's will, incl. ratified inferences), **derived** (the
  kernel's own). Each is queryable; none can masquerade as another.

This is the exact discipline that already keeps a surveyed override from
masquerading as a derived value — extended to the messy front door. It is the
non-negotiable core of this doc.

## 6. Honest limits

- **Layer B is genuinely research-grade.** Reading a real architectural set well
  enough to propose good structural constraints is hard; early versions will be a
  heavily human-driven markup conversation, not magic. **That is acceptable** —
  the value is in the structured capture and the audit trail even when the human
  does most of the interpreting. The system should be useful when the AI proposes
  little and the engineer authors most, and get more helpful as the proposing
  improves. Design for the human-heavy case first.
- **The seam must not leak upstream.** No drawing/DWG/IFC concept and no vision-
  model type crosses into the kernel; ingestion and capture live behind adapters
  (the posture of solver, material, and LLM engines). The kernel receives
  referenced geometry and ratified decisions — nothing about *how* they were
  read.
- **Garbage-in is bounded by ratification, not by parser quality.** Because
  nothing inferred is enforced until ratified, a bad AI reading produces
  rejected proposals, never corrupt authored intent. The parser can be
  imperfect; the graph stays clean by construction.

## 7. Sequencing

Independent of, and parallel to, the 0004 output work; both are phase-2+.

1. **Provenance taxonomy first (§5).** Extend `IntentProvenance` to
   `authored | derived | inferred` with the ratification record, and add the
   `external` provenance for referenced geometry. Cheap, pure-schema, and it is
   the foundation everything else leans on — land it before any ingestion code so
   nothing inferred can ever be born without the right stamp.
2. **Referenced geometry as a kind (§3).** The read-only external object,
   content-addressed and versioned, with the re-issue/re-confirm machinery.
   Deterministic IFC grid/level ingestion first (highest signal, real
   semantics); DWG later.
3. **The capture loop (§4).** The propose→ratify UI/flow over referenced
   geometry, starting human-heavy: the engineer marks up, the AI assists;
   increase AI proposing as it earns trust.
4. **Richer multimodal reading.** Better sheet understanding, sketch ingestion,
   conversation-to-constraint — the research-grade end, built on a foundation
   that is already sound without it.

## 8. Open questions for review

1. **Referenced-geometry granularity** — is it opaque geometry with tagged
   regions/lines, or a light typed model (grids, levels, spaces, walls-as-
   context)? Proposed: light typed for the entities IFC gives cleanly (grids,
   levels, storeys), opaque geometry for the rest, extended as needs appear.
2. **Does `inferred` intent live in the graph before ratification, or in a
   staging area outside it?** Tension: in-graph gives one model and natural diff,
   but risks an unratified inference being read as real. Proposed: in-graph but
   *inert by type* — the validator refuses to let any `inferred`, unratified
   instance be enforcement- or exploration-binding — mirroring how a displaced
   override stays inert in-place rather than being removed.
3. **Ratification granularity** — per constraint, or batched per review session?
   Likely per constraint for the audit trail, with a batch-confirm affordance.
4. **How much conversation is itself captured?** The owner's "exposed timber"
   preference is a real constraint with no drawing. Does the conversation become
   referenced provenance too (a captured, timestamped source), or only its
   ratified structural conclusions? Proposed: capture the ratified conclusion,
   reference the conversation as its basis — decide the retention detail in
   review.
