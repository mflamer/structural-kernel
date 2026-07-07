# 0004 — Intent: kernel-fixed shape, open category registry, two-site enforcement

**Status:** Accepted (2026-07-07; design doc 0001 §4 as revised per review R2 and the
product-owner reply on review findings, item 1)

## Context

The charter requires new structural intent categories — vibration, fatigue,
fire-structural — to land without kernel changes, and requires phase 1's
`serviceability` category to ship with real semantics (deflection limits are hard
phase-1 constraints per review Q3). But intent checkers run at commit time against a
derivation dry-run, where no solve results exist — a deflection check literally cannot
run there. And an impure checker (clock, filesystem, network) silently breaks
determinism and replayability.

## Decision

- **The kernel fixes the intent envelope shape and stays agnostic about categories.**
  An intent instance = versioned envelope with `category` (registry key, not an enum),
  category-schema-validated `payload`, typed `relations` with resolvable targets, and
  `provenance` (authored vs derived). The kernel validates shape, registration,
  payload schema, and referential integrity — never category meaning.
- **A category registration** = `(name, payload schema, relation roles, checker)`,
  living in versioned registry modules. Adding a category is a new module + schema +
  checker — zero kernel edits. Phase 1 ships `gravity_load_path`, `lateral_capacity`,
  `serviceability`, `retrofit_rationale`.
- **Checker purity contract:** a checker is a pure function of exactly
  `(derived model, intent instance, proposed snapshot)` — no clock, filesystem,
  environment, or network access. Property-tested like derivation determinism.
- **Two-site enforcement.** Intent enforcement is split by what each site can decide:
  - *Commit-time intent checkers* — restricted to what is decidable from the dry-run
    derived model and snapshot: topology, load-path connectivity, referential shape.
  - *Solve-time design checks* — demand-dependent limits (deflection L/360 live,
    L/240 total; ASD unity) verified over `SolveResult`s and enforced as hard
    exploration constraints.
  Both sites must cite the intent instance they enforce, so a failed deflection check
  traces to the `serviceability` intent in the audit trail. That linkage is the
  substance of "ships real, not a placeholder."

## Consequences

- The charter's extensibility test holds: `vibration` later = one registry module.
- Commit-time validation stays pure, deterministic, and replayable; solve-dependent
  enforcement lives where solve results exist, without weakening either site.
- Design checks need a machine-readable way to reference the intent instances they
  enforce — a schema obligation on the design-check result format.
- Intent is attached both on decisions (authored, captured conversationally) and on
  derived elements (derived, emitted by derivation rules).
