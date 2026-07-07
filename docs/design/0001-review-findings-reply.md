# Product-Owner Reply: Review Findings on 0001-review-response

All three collisions are confirmed as real. Decisions follow. Proceed with the revision work, ADRs, CLAUDE.md update, xara email draft, and commit.

**Item 1 (R2 vs Q3) — resolution approved, generalized.** Adopt the two-site principle, not just the deflection instance: intent enforcement is split between (a) commit-time intent checkers, restricted to what is decidable from the dry-run derived model and snapshot — topology, load-path connectivity, referential shape — under the R2 purity tuple unchanged; and (b) solve-time design checks, which verify demand-dependent limits (deflection L/360 live / L/240 total, unity) as hard exploration constraints. Both sites must cite the intent instance they enforce, so a failed deflection check traces to the serviceability intent in the audit trail. That linkage is the substance of the "not a placeholder" requirement. Word §4.2 accordingly.

**Item 2 (unresolved decisions vs totality) — approved.** A partial derived model is a defined, first-class derivation outcome: an open decision derives to everything derivable, with openness explicitly represented — never an error. Two consequences for the derivation ADR: (a) a partial model may legitimately produce no solvable analysis artifact; absence is a valid state, not a failure; (b) queries must operate on partial models — the vision demo queries a model whose structural system is still open. Add this to the standing-requirements list as its own entry.

**Item 3 (exploration schema) — approved.** Restructure §8: candidates carry changeset, branch, rationale, artifact, and solve-result references only; evaluations become a separate collection on the exploration keyed by (result set, cost_basis), each with its own ranking. Re-ranking under a revised basis appends an evaluation; it never re-solves and never mutates candidates.

**R3 guidance.** Verify before reusing the override dangling mechanism, as you proposed — and treat the cases asymmetrically. A dangling override is stale measurement (warn, persist, inert). A dangling exception is deliberate design will whose target vanished: distinct error code, and explicit human resolution required (retarget or delete) rather than quiet inertness. If that asymmetry makes reuse awkward, separate mechanisms are acceptable.

**Housekeeping.** vision.md moves to `docs/vision.md` — a standing north star does not live in a proposals-in-review directory. The review-response reference is corrected to match.
