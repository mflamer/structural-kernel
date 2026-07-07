# 0002 — Deterministic Element Identity: Anchors, Correspondence, and Hierarchy

**Status:** Proposal, awaiting product-owner review. Graduates to ADR 0005 if it
survives. Per review R1, **derivation implementation for the milestone structure is
gated on this document being accepted.**
**Scope:** the eid grammar, the anchor scheme that keeps eids stable under edits, the
gridline-move resolution R1 requires, split correspondence semantics for overrides vs.
diffs, dangling behavior for each eid consumer, and hierarchical component identity
(standing requirements 8 and, by extension, 10).

## 1. The problem, restated

Design doc 0001 §3.3 requires `eid = f(inducing decision, rule instance, ordinal)` with
ordinals keyed to stable anchors. The review (R1) exposed the collision: if anchors are
grid-line *offsets* (coordinates), moving gridline B 2 ft east renumbers every eid in
the bay, and "J5 got heavier in variant 3" becomes unanswerable — yet for overrides,
dangling on a grid move is arguably *correct*, because the surveyed member didn't move
when the grid abstraction did. Two consumers, two different notions of "same element."
Additionally, granular eids (bolt under connection under member) must nest in one
identity system (standing requirement 8).

The resolution: **eids live entirely in rule-relative space** (names and ordinals,
never coordinates), which makes them stable under geometric edits — and the consumer
that genuinely cares about absolute space (overrides) carries a **surveyed anchor** in
addition to the eid, checked at re-attachment. Identity is one scheme; correspondence
semantics differ per consumer, exactly as R1 anticipated.

## 2. Eid grammar

An eid is a `/`-separated path of segments; each segment is
`{role}:{inducer}:{anchor}`:

```
jst:01JXF:B-C.g2+03          the 4th joist (ordinal 03, zero-based) in bay B-C,
                             counted from grid line g2, induced by decision 01JXF
jst:01JXF:B-C.g2+03/conn:br0:end-g2     that joist's connection at its g2 end
jst:01JXF:B-C.g2+03/conn:br0:end-g2/fst:nl1:02   the 3rd fastener in that connection
```

- **`role`** — a short kind tag from the derivation vocabulary (`jst`, `bm`, `pst`,
  `hdr`, `wallseg`, `conn`, `fst`, ...). Adding roles is a derivation-rule concern,
  not a kernel schema change.
- **`inducer`** — the `did` of the decision (or, for child segments, the derivation
  rule id) whose rule emitted this element. This is what ties every element to its
  provenance and makes "why does this exist?" answerable from the eid alone.
- **`anchor`** — a rule-relative name (§3), never a coordinate.

The full path is the eid; every prefix of a valid eid is itself a valid eid (the
parent element). Eids are strings in persisted artifacts — ordinary, diffable,
greppable — with a validated grammar (curated, like unit spellings; no free-form
parser creep).

## 3. Anchors are names, not coordinates

The anchor vocabulary, in order of preference per rule type:

1. **Stable sub-identities of referenced decisions.** A `grid` decision assigns each
   axis a stable line-id at creation (ULID-suffixed, like dids); *display names*
   ("B", "B.5") are presentation fields on the line, renameable at will. Anchors
   reference line-ids, rendered with display names for humans. Consequence: neither
   **moving** a gridline (geometry change) nor **renaming** it (presentation change)
   perturbs any eid.
2. **Named topological positions** — `end-g2`, `mid`, `over-pst:...` — for children
   whose position is defined by the parent's topology.
3. **Ordinals from a named edge**, only where nothing better exists: joists within a
   bay are counted from the lower-sorted bounding line-id, in layout order. Ordinals
   are the weakest anchor and are deliberately scoped: an ordinal appears only in the
   final position of a segment's anchor, so its blast radius is one rule instance in
   one bay.

**What stays stable:** gridline moves and renames, load changes, section changes,
edits in other bays or other rule instances, re-derivation at any level of detail,
and — because anchors are provenance-relative, not coordinate-relative — the same
element corresponds across branches that share the inducing decision and rule
instance ("J5" *is* J5 in variant 3, so "J5 got heavier" is answerable).

**What legitimately renumbers:** changing the rule's own output structure within a
bay — a spacing change from 16" to 19.2" produces *different members*, and pretending
otherwise would be false correspondence. Region splits and removal of the inducing
decision likewise. This is the honest boundary: eids survive everything except changes
to the very rule that defines them.

## 4. Split correspondence semantics (the R1 resolution)

Identity is one scheme; each consumer declares which space it corresponds in.

- **Diffs, queries, exploration rankings — rule-relative space.** They use the eid
  alone. A gridline move changes derived geometry but no eids, so cross-branch and
  cross-commit diffs report "J5: span 14'-0" → 16'-0"" instead of a wall of
  deletes-and-adds. This is what makes the milestone diff query and "J5 got heavier
  in variant 3" work.
- **Overrides — surveyed/absolute space, via a surveyed anchor.** An override records,
  at attach time, in addition to `target.eid`: the element's world-space reference
  geometry (canonical SI, from the derived model it attached against) and a tolerance
  bucketed by the provenance `confidence` (`measured` tight, `estimated` loose,
  `assumed` advisory). On re-derivation, override re-attachment checks **both**: the
  eid still exists, *and* the element's geometry matches the surveyed anchor within
  tolerance. Four outcomes:

  | eid exists | geometry matches | state |
  |---|---|---|
  | yes | yes | attached (normal) |
  | yes | no | **displaced** — the grid moved, the surveyed member didn't; warning, override inert |
  | no | — | **dangling** — target vanished; warning, override inert |
  | no | near-match exists | dangling, with **candidate re-targets** listed in the warning |

  Displaced and dangling both surface as the §5 validation warning (never silently
  dropped, model still derives, human resolves) — this extends the design doc's
  dangling-override machinery with the `displaced` state rather than replacing it.
- **Exceptions — rule-relative space, hard-dangling.** An `exception` decision targets
  by eid and corresponds rule-relatively (a doubled joist under the tub should follow
  the framing rule's output, not a coordinate). Per R3 semantics (design doc §2.3, PO
  reply): when its target eid ceases to exist, it is a `dangling_exception` validation
  **error** — the orphaning changeset must retarget or delete it to commit. Because
  exceptions may also record an optional location hint, the error can propose
  candidate re-targets the same way displaced overrides do — but resolution is always
  explicit and human.
- **Intent relations — rule-relative space.** Derived intent re-derives with the model
  (its inducer regenerates it), so it cannot dangle. Authored intent targeting an eid
  that vanishes follows the exception rule: validation error, explicit resolution —
  design will, not measurement.

## 5. Hierarchy and level of detail

Children extend the parent's path (§2), which gives standing requirements 8 and 10
their identity substrate for free:

- Deriving the same snapshot at a deeper level of detail *extends* paths; it never
  rewrites them. Member-level eids are byte-identical across LOD levels, so an
  override or intent attached at member level binds regardless of the resolution any
  consumer derived at.
- A child's identity is stable iff its whole prefix is stable — a bolt's eid survives
  exactly what its connection and member survive. There is no second identity system
  to reconcile.
- Partial derived models (standing requirement 10) emit eids only for what derived;
  an unresolved decision induces nothing, and openness is represented on the model,
  not by placeholder eids.

## 6. Invariants and property tests

Each invariant below becomes a property test before the derivation code that must
uphold it is written (charter: acceptance tests red until earned):

1. **Determinism** — same snapshot, same derivation version, same LOD ⇒ identical eid
   set (subsumed by derivation determinism, asserted separately for eids).
2. **Gridline-move invariance** — moving any gridline: eid set unchanged; geometry
   changed; every override on affected members transitions to `displaced`, none
   dangle, none silently re-attach.
3. **Gridline-rename invariance** — renaming a line changes no eids and no override
   states.
4. **Locality** — an edit confined to one rule instance perturbs no eids outside that
   rule instance (property-tested across random neighboring edits).
5. **Prefix stability** — for any two LOD levels of the same snapshot, the shallower
   eid set is exactly the prefix set of the deeper one.
6. **Cross-branch correspondence** — two branches differing only in parameters of
   decisions that don't feed element X agree on X's eid.
7. **Honest renumbering** — a spacing change within a bay changes that bay's member
   eids and dangles that bay's exceptions (error) and overrides (warning); nothing
   outside the bay moves.

## 7. What this does *not* decide

- Cross-*kind* correspondence (steel variant vs. wood variant of the same bay —
  standing requirement 1): deliberately out of scope for eids. Heterogeneous branches
  correspond at the region/role level and are compared by the evaluation layer on
  aggregates, not element-by-element. No eid machinery should be bent toward this.
- The re-target *suggestion* heuristics (near-match distance metrics) — implementation
  detail behind the warning/error schema, tunable without schema change.
- Anchor vocabularies for future rule types (trusses, reinforcing) — each new
  derivation rule declares its anchor scheme against §3's preference order; the
  grammar (§2) doesn't change.
