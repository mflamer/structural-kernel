# 0005 — Deterministic element identity: rule-relative eids with per-consumer correspondence

**Status:** Accepted (2026-07-07; design proposal `docs/design/0002-eid-identity-scheme.md`
as revised per review E1–E3, `docs/design/0002-review.md`). Resolves review R1 and
lifts its gate on derivation implementation. Full detail lives in the design doc;
this record distills the decision.

## Context

Design doc 0001 §3.3 required deterministic eids but anchored ordinals to grid-line
*offsets* — colliding with the gridline-move scenario (review R1): moving a line would
renumber the bay and destroy cross-branch correspondence, while for overrides,
dangling on a grid move is arguably correct (the surveyed member didn't move when the
grid abstraction did). Granular component identity (bolt under connection under
member) also had to nest in one scheme (standing requirement 8).

## Decision

- **Eids live entirely in rule-relative space.** An eid is a `/`-separated path of
  `{role}:{inducer}:{anchor}` segments. Anchors are names, never coordinates, in
  preference order: stable sub-identities of referenced decisions (grid lines carry
  stable line-ids; display names are presentation only), named topological positions,
  and — last resort — ordinals counted from a bounding line chosen by lexicographic
  order of **the line-id token itself** (E2), a key invariant under every geometric
  or presentation edit.
- **The canonical, persisted, hashed, diffed eid embeds stable identities only** (E1).
  Display names appear solely in a human-rendering transform at the presentation
  boundary. Gridline moves and renames therefore change no eids.
- **Identity is one scheme; correspondence semantics differ per consumer.** Diffs,
  queries, and exploration rankings correspond in rule-relative space via the eid
  alone. Overrides additionally record a world-space **surveyed anchor** with
  confidence-bucketed tolerance, checked at re-attachment: eid gone ⇒ *dangling*
  (warning, inert, candidate re-targets where a near-match exists); eid present but
  geometry diverged ⇒ *displaced* (warning, inert — applying the measurement could
  attribute it to the wrong physical member). Exceptions and authored intent
  hard-dangle: a distinct validation error the orphaning changeset must resolve by
  retarget or delete. Derived intent re-derives with the model and cannot dangle.
- **Hierarchy is prefix-based.** Every prefix of an eid is the parent element's eid;
  deeper level-of-detail derivation extends paths and never rewrites them, so
  member-level identity is byte-identical across LOD levels.
- **Gridline deletion is a referential-validation concern, not eid machinery** (E3):
  deleting a line-id still referenced by any decision fails 0001 §6 stage-2
  validation unless the same changeset updates the referencing decisions — which then
  renumbers their outputs honestly. An unreferenced line anchors no eids and deletes
  freely.
- **The honest renumbering boundary:** eids survive everything except changes to the
  output structure of the very rule that emits them (spacing changes, region splits,
  inducer removal). Cross-*kind* correspondence (steel vs. wood variants) is
  explicitly not an eid concern — the evaluation layer compares aggregates.

## Consequences

- Property tests 1–8 (design doc §6: determinism, move invariance incl. reordering
  moves, rename invariance, locality, LOD prefix stability, cross-branch
  correspondence, honest renumbering, deletion) are written before the derivation
  code that must uphold them.
- The `grid` decision schema must assign stable line-ids at creation, with display
  names as mutable presentation fields.
- The override schema gains the surveyed anchor and the `displaced` state alongside
  `dangling`; the exception/authored-intent path gains `dangling_exception` with
  candidate re-targets.
- Derivation implementation for the milestone structure is unblocked.
