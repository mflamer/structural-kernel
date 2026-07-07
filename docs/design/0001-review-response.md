# Product-Owner Review: 0001 — Kernel and Solver Architecture

**Status:** Approved with three required revisions and answers to all open questions below. Revise §3.3, §4.2, and §2.3 per items R1–R3, then cut the ADRs and begin implementation in the increment order proposed.

The SI-canonical unit decision (§2.4) is accepted as proposed, including the rejection of a kip-inch internal convention. US customary remains the authoring and display register.

## Required revisions

**R1 — The eid anchor ADR must resolve the gridline-move scenario.** Element identity anchored to grid-line offsets collides with the milestone's own "move gridline B 2 feet east and diff" query: moving the anchor may renumber every eid in the bay. Note the two consumers want different things — for overrides, dangling on a grid move is arguably *correct* (the surveyed member didn't move when the grid abstraction did); for diffs and exploration rankings, cross-branch eid correspondence must survive the move or "J5 got heavier in variant 3" is unanswerable. The ADR must explicitly define behavior for this scenario, and may define different correspondence semantics for overrides (absolute/surveyed space) vs. diffs (rule-relative space). Do not implement derivation for the milestone structure until this ADR exists.

**R2 — Extend the purity contract to intent checkers (§4.2).** Checkers run inside validation; a checker that reads anything outside `(derived model, intent instance, proposed snapshot)` — clock, filesystem, environment, network — silently breaks determinism and replayability. State the contract in §4.2 and property-test it the same way derivation determinism is tested.

**R3 — Define dangling semantics for `exception` decisions (§2.3).** An exception targets another decision's output at a specific location; if that reference is by eid, it dangles under re-derivation exactly like an override, but decisions currently have no dangling-warning machinery. Specify how exceptions reference their targets and what happens when the target ceases to exist. Reusing the override dangling-warning mechanism is acceptable if the semantics genuinely match.

## Answers to open questions (§10)

1. **Material domain:** Wood. Sawn-lumber joists/beams/posts; NDS-style ASD checks. First design-check module and section/property tables are sawn lumber.
2. **Code slice:** ASCE 7-22 §2.4 ASD load combinations. "Unity" = ASD demand/capacity per the NDS check set implemented in phase 1.
3. **Serviceability:** Yes — include L/360 live-load and L/240 total-load deflection checks as hard constraints in phase 1. Wood floor design is frequently deflection-governed; a weight-minimizing exploration constrained only by strength will produce unrealistic winners in the first demo.
4. **Sizing vs checking:** Confirmed as proposed — sizes are decision parameters in phase 1; explorations vary them; auto-sizing is a later derivation rule.
5. **Tributary rules:** Confirmed — half-span each side, simple-span, no continuity effects.
6. **Authoring units register:** Confirmed — ft-in, kips, psf, ksi at the boundary; canonical SI internally per §2.4.
7. **Lateral depth:** Confirmed — representational only in phase 1 (derived shear-wall segments + `lateral_capacity` intent instance, no lateral analysis or checks). Understood that the retrofit validation case waits.
8. **Provision references:** Confirmed — opaque validated strings now; a provisions table with stable IDs when checks start consuming them.
9. **Exploration intent constraint:** Confirmed — `intent_preserved` is hard in phase 1; intent edits are human-reviewed changesets only. Explorations may not propose intent changes.
10. **Xara license:** Proceed with xara as the first engine. Draft the confirmation email to the maintainer (whole-tree BSD-2-Clause relicensing, inherited OpenSees core included); I will send it as the commercial entity. Do not block implementation on the reply — the adapter interface makes the exit cheap if the answer disappoints.

## Note for the record

Deflection constraints (Q3) add a `serviceability` checker consuming solve-result displacements in phase 1 — which means the `serviceability` intent category ships with a real checker, not a placeholder. Adjust the increment plan if that changes the ordering.

## Standing requirements from the vision document

`docs/vision.md` (committed at the repo docs root — it is a standing north star, not a proposal in review) is the north-star demo. It is not phase 1 scope, but the following requirements it imposes must be visible when cutting ADRs, because they are cheap to accommodate now and expensive to retrofit:

1. **Heterogeneous exploration candidates.** Explorations must eventually rank branches that differ in decision *kind* (e.g., steel frame vs. wood framing), not only in parameters. No exploration or evaluation schema decision may assume all candidates share a strategy.
2. **Unresolved decisions.** A decision must be able to exist in a committed model in an explicitly *open* state ("structural system: unresolved"), later resolved by an exploration whose record attaches to it permanently.
3. **`cost_basis` as a decision kind.** Cost assumptions (unit material costs, crew rates, regional factors, lead times, as-of date) are versioned decisions in the graph — never constants in code, never inputs to derivation rules. Rankings cite the basis they were computed under.
4. **Countables in the derived model.** Derivation must emit installation-cost drivers — connection counts, piece counts, crane picks — alongside member quantities in `DerivedModel` and the bill of elements. The phase 1 bill-of-elements schema should reserve room for these even if phase 1 populates only material quantities.
5. **Evaluation as a layer distinct from solving.** Ranking/evaluation consumes solve results plus a cost basis; re-ranking an exploration under a revised basis must not require re-solving. The exploration schema should key evaluations by `(result set, cost_basis)` rather than baking a single evaluation into each candidate.
6. **Honest cost uncertainty.** Cost comparisons carry their basis and an uncertainty statement; the evaluation layer must be able to report a close ranking as within the noise.
7. **Staged derivation.** The system ultimately derives granular components — connections, bolts, reinforcing — from rules applied to geometry *and solve-result demands*. The derivation contract (§3.1) must therefore accommodate multiple pure stages, where later stages take solve results as inputs (derive → solve → detail-derive → re-solve where detailing changes stiffness), rather than assuming a single snapshot-to-model pass. Phase 1 implements one stage; the contract's type signature should not foreclose more.
8. **Level of detail as a derivation parameter.** The same snapshot must be derivable at different resolutions (members-only for explorations; full component detail for fabrication), each a cached artifact. The eid scheme (R1's ADR) should anticipate hierarchical component identity — bolt under connection under member — so granular eids nest rather than requiring a second identity system.
9. **Engines of different fidelity, with declared accuracy contracts.** The solver interface and exploration/evaluation schemas must permit multiple engines distinguished by fidelity — e.g., a fast surrogate (screening-grade, trained on our own accumulated solve artifacts) alongside true FEA (verification-grade) — with each result carrying its engine's accuracy contract. Explorations may screen with low fidelity and verify finalists with high fidelity; only verification-grade results feed design checks and the stamped record. Phase 1 ships one engine (xara); the `SolveResult` schema should carry a fidelity/engine-class field from day one so tiered screening arrives later without schema surgery.

10. **Partial derived models.** *(Added per the product-owner reply on review findings, 2026-07-07.)* A decision may be explicitly unresolved in a committed model (item 2); derivation of such a snapshot is a defined, first-class outcome, never an error: everything derivable derives, with the openness explicitly represented in the output. A partial model may legitimately produce no solvable analysis artifact — absence is a valid state, not a failure — and queries must operate on partial models (the vision demo queries a model whose structural system is still open).
