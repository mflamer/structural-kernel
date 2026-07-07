# Product-Owner Review: 0002 — Deterministic Element Identity

**Status:** Approved contingent on revisions E1–E3 below. Upon revision, graduate to ADR 0005 and lift the R1 gate on derivation implementation.

Accepted as proposed: the rule-relative identity scheme with per-consumer correspondence semantics; the eid grammar with prefix-hierarchy for components; anchors as names never coordinates; the four-state override re-attachment table, including **displaced → inert** (rationale for the record: once geometry diverges from the surveyed anchor beyond tolerance, correspondence between model element and physical member is in doubt, and applying the measurement would risk attributing it to the wrong member — inert with a persistent warning is the conservative truth); confidence-bucketed tolerances; hard-dangling exceptions and authored intent with candidate re-targets; derived intent as undanglable; §5 LOD prefix semantics; and §7's refusal to bend eids toward cross-kind correspondence.

## Required revisions

**E1 — Specify the canonical persisted eid form.** §3 says anchors reference stable line-ids; §2's examples (`B-C.g2+03`) read as display names. State explicitly: the canonical, persisted, hashed, diffed eid embeds line-ids (and other stable sub-identities) only; display names appear solely in a separate human-rendering transform. Relabel the §2 examples as rendered form and show one canonical-form example alongside. If display names were persisted, rename invariance (test 3) and content-address stability would both fail.

**E2 — Fix the ordinal sort key.** "Counted from the lower-sorted bounding line-id" must define the sort key as the line-id itself (or another key invariant under geometric edits) — never spatial position, never display name. If "lower" meant coordinates, a gridline move that reorders lines (B moved east past C) would flip the counting origin and renumber the bay, violating test 2. State the key; add the reordering move as an explicit case under test 2.

**E3 — State gridline-deletion semantics and add property test 8.** Moves and renames are covered; deletion of a line-id that anchors eids is not. If the intended mechanism is 0001 stage-2 referential validation — any decision referencing the deleted line-id fails, so the orphaning changeset cannot commit without also updating the referencing decisions, which then renumbers honestly per §3 — say so explicitly, including the case of a line no decision references. Add **test 8: gridline deletion** — deleting a referenced line without updating referencing decisions is rejected at validation; deleting it with the referencing decisions updated renumbers exactly the affected rule instances and dangles/errors their overrides and exceptions per §4; nothing else moves.

## For the record

The four-probe agenda from pre-review is resolved: displacement tolerance keyed to provenance confidence (§4, accepted); displaced-override applicability (explicitly inert, accepted with rationale above); anchor deletion (E3, the one gap); bay renumbering under output-structure change (test 7, accepted).
