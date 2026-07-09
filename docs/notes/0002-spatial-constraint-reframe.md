# Note 0002 — Reframe the "clear-span" increment as a general spatial constraint

**Kind:** Design-steer note (product-owner reframe of an increment's scope before
it is specced). Companion input to whichever design doc/ADR the increment cuts.
**Raised:** 2026-07-08, PO review of the increment's four scoping questions.
**Concerns:** the spatial-constraint increment; ADR 0005 (anchors); ADR 0004
(intent shape); `explorations.py` (exploration constraints).
**Status:** Applied — ADR 0011 (2026-07-08) cuts the spatial-structural-constraint
primitive exactly as reframed here: a first-class `ProjectConstraint` graph object,
region in the ADR 0005 anchor vocabulary, an open predicate registry
(`constraints.py`) with `no_vertical_support_within` and `min_bay_spacing` as its
first two instances, enforced on every changeset and every exploration candidate,
with a `clear_height_below` test fixture as the "third predicate, no kernel change"
generalization proof. The `inferred`→ratify provenance seam (§5) remains design doc
0005's separate workstream.

## The problem with the four questions as posed

The four scoping questions ("how to encode *the west 40 feet*", "what counts as a
forbidden support *here*", "which decision does *the clear-span intent* attach
to", "scope = clear-span + min-bay") are all reasoning **backward from the
demo**. They design a bespoke clear-span feature shaped to one vision beat.

That is the IFC failure mode in miniature: enumerating cases instead of finding
the primitive. A kernel that grows a hand-fitted "clear-span intent" will do the
demo and calcify; the next spatial requirement needs another bespoke feature.
"The west 40 feet must be column-free" is not a thing to encode — it is **one
instance of a general class**: a spatial structural constraint.

The reframe: **design the general primitive; make clear-span its first instance
and min-bay its second.** Two instances prove the primitive without designing to
one. The acceptance test that it is right: **a third constraint type nobody
planned for — e.g. `clear_height_below` — drops in as data, no kernel change.**
Same move that made intent *categories* a registry instead of an enum (ADR 0004),
and material engines a registry instead of a wood special-case (ADR 0007).

## What each question is really deciding (generalized)

1. **Region encoding** is not "offset band vs. grid-ids." It is: *what is the
   general spatial-reference vocabulary* for anchoring any constraint to space?
   It must cover grid-bounded regions, offset bands from an anchor line,
   referenced-geometry regions (the architect's zone, 0005), and points/lines —
   and it must survive re-derivation. **Therefore it belongs in the ADR 0005
   anchor system, not invented in this increment.** A spatial constraint's region
   is expressed in the same rule-relative anchor vocabulary eids already use;
   "west 40 feet" is an offset band anchored to a stable line-id, rendered from
   it, never a raw coordinate.

2. **"Forbidden support"** is not about this constraint. It is: *how does any
   constraint predicate over derived elements* — by role, by family, by
   load-carrying behavior? That is the general shape of a **constraint checker**,
   and it wants the same two-site treatment intent already has (commit-time
   topological check where decidable; solve-time demand check where not — the
   item-1 finding). "No vertical support in region R" is a commit-time
   topological predicate: does any derived element of role ∈ {post, column,
   bearing wall} intersect R?

3. **Attachment is the deep one, and the demo obscures it.** The constraint
   exists **before the structural system does** — it constrains *whichever*
   system is chosen. It therefore **cannot attach to a framing decision**; it is
   a **standing project constraint that the exploration is searched against, and
   that every candidate system must satisfy.** The Code session's own instinct
   ("new standalone constraint kind") is correct — and the reason is the general
   point: this is a first-class *project constraint* that outlives and governs
   the decisions, not intent hanging off an element that does not exist yet. That
   is a real representational gap, and it generalizes far past clear-span.

4. **Scope** is not "clear-span + min-bay" as two features. It is "**the spatial
   constraint primitive, exercised by two instances.**" The primitive is the
   deliverable; the two instances are its tests.

## Proposed primitive

A **spatial structural constraint**: a typed predicate over a spatially-anchored
region, evaluated at the correct site, bindable as an exploration constraint
independently of the structural system.

- **Region** — expressed in the ADR 0005 anchor vocabulary (grid-bounded, offset
  band, referenced-geometry region, point/line). Stable under re-derivation by
  construction. No new coordinate scheme.
- **Predicate** — a typed, registry-backed kind (like intent categories,
  ADR 0004). First entries: `no_vertical_support_within` (clear-span),
  `min_bay_spacing` (min-bay). The predicate declares its **check site**
  (commit-time topological / solve-time demand) and how it predicates over
  elements (by role/family/behavior). New predicate kinds are registry entries,
  not kernel edits.
- **Binding** — a spatial constraint is a **project-level constraint** that (a)
  is a hard exploration constraint: every candidate is checked against it, and a
  violating candidate is infeasible — slotting in beside `MetricConstraint` and
  `IntentPreservedConstraint` in `explorations.py`, the existing hard-constraint
  set; and (b) is enforced on ordinary changesets too, so a violating edit
  outside an exploration is rejected the same way. It does **not** require a
  resolved structural system to exist; it is satisfiable-in-principle against an
  open decision and actually checked against each derived candidate.

## Where it lives (representational placement)

- A spatial constraint is **not** an `IntentInstance` on an element (no element to
  hang it on at capture time) and **not** a `Decision` that derives geometry. It
  is a **project constraint**: a first-class, committed, versioned graph object
  that the exploration and the validator both read. This is the standalone kind
  the Code session reached for — recorded here as a deliberate new object
  category, not an ad-hoc addition.
- It is authored (ADR 0004 provenance) or, per 0005, **ratified from an
  `inferred` proposal** — "the AI read the west zone as column-free, the engineer
  confirmed." The provenance seam and this primitive meet here: a captured
  architectural constraint *becomes* a project constraint on ratification.
- Its region uses ADR 0005 anchors; when a gridline it anchors to moves, it
  tracks; when deleted, it dangles with a warning — the machinery already exists.

## Suggested increment scope (corrected)

Deliver the **spatial structural constraint primitive**: the project-constraint
object, the region vocabulary (reusing ADR 0005 anchors), the predicate registry
with its check-site declaration, and the exploration + changeset binding —
**proven by two registered instances, `no_vertical_support_within` and
`min_bay_spacing`.**

**Acceptance signals:**
- The vision's clear-span and min-bay both express as instances of the one
  primitive (demo still works).
- A candidate placing a post in the protected region is infeasible in the
  exploration *and* a changeset doing so outside an exploration is rejected —
  both citing the violated project constraint.
- The constraint is captured/committed while the structural system is an **open**
  decision, and correctly governs every candidate the exploration later proposes.
- **A third predicate kind (`clear_height_below`, written as a test fixture)
  registers and enforces with no kernel change** — the real proof the primitive
  generalizes.

## Answers to the original four (reframed)

1. Region → ADR 0005 anchor vocabulary (offset band on a stable line-id for "west
   40 ft"); not a new scheme.
2. Forbidden support → a registry predicate over element role/family, commit-time
   topological site; not hard-coded to this constraint.
3. Attaches to → nothing element-level; it is a **standalone project constraint**
   bound to the exploration and validator, precisely because the system is still
   open. (Confirms the session's instinct, for the general reason.)
4. Scope → the **primitive**, exercised by clear-span + min-bay as its first two
   registered instances, with a third unplanned kind as the generalization test.
