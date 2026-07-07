# structural-kernel

AI-native building information system for structural engineering, built clean-slate.
Canonical model = a versioned graph of *design decisions*; geometry, analysis models,
design checks, schedules are *derived artifacts* (pure functions over the graph).
Every element carries structured *structural intent* (why it exists — loads, load
paths, code provisions), so an AI can tell whether a change breaks the design, not
just the geometry. Not an IFC successor, not a plugin, not a file format.

The product owner is a licensed PE (WA) acting as domain expert. When domain questions
arise (structural behavior, code requirements, how engineers think), ASK — don't guess.
Push back when the engineering says otherwise.

## Where truth lives — read in this order
- `docs/kickoff.md` — the charter: principles, non-goals, phase 1 milestone. Governs.
- `docs/vision.md` — the north-star demo; its standing requirements (enumerated in
  `docs/design/0001-review-response.md`, items 1–10) must be visible in every ADR.
- `docs/design/0001-kernel-and-solver-architecture.md` — the architecture, approved
  and revised (decision graph, derivation contract, changesets, overrides, intent
  registry + two-site enforcement, analysis artifacts, solver service, explorations
  with evaluations as a separate layer). Review record:
  `0001-review-response.md` + `0001-review-findings-reply.md` alongside it.
- `docs/decisions/` — ADR log. Settled choices only; proposals live in docs/design/
  until they survive review. This project is itself decision-derived; eat the dog food.

## Current status / gates (update this section as things change)
- **Design doc 0001 approved 2026-07-07** (revisions R1–R3 applied same day per the
  PO reply, `docs/design/0001-review-findings-reply.md`). All §10 questions answered:
  **phase-1 domain is wood** — sawn lumber, NDS ASD checks, ASCE 7-22 §2.4 combos,
  with L/360 live and L/240 total deflection as hard constraints alongside unity.
- ADRs 0002–0005 cut (SI units, solver-agnostic/xara-first, intent registry +
  two-site enforcement, eid identity scheme). Index: `docs/decisions/README.md`.
- **Eid scheme accepted 2026-07-07** (revisions E1–E3 applied per
  `docs/design/0002-review.md`; graduated to ADR 0005) — **the R1 gate is lifted;
  implementation is unblocked.** Next: increment 1, store + schemas.
- Open action (PO, non-blocking): send the xara license-confirmation email
  (`docs/xara-license-email-draft.md`).
- Increment order: store + schemas → decisions + validation
  → derivation for the milestone structure → xara adapter + verification → overrides
  → intent checkers + solve-time design checks (serviceability is real in phase 1,
  citing intent instances) → exploration loop (evaluations keyed by
  (result set, cost_basis), separate from solving). Small, reviewable increments;
  milestone criteria in the charter are the acceptance tests, written early, red
  until earned.

## Hard rules from the charter
- **The persisted schema is the source of truth, not the Python code.** Storage is
  language-neutral versioned JSON in a content-addressed store — no pickle, nothing
  another language couldn't validate. `schema_version` on every persisted artifact.
- **No bare floats across interfaces** — every boundary value is unit-tagged.
  Canonical internal units: SI (N, m, s, kg → Pa). Authoring/display: ft-in/kip/psf.
- **The AI never edits state directly** — changesets only: propose → validate →
  commit/reject with structured errors.
- **Intent categories are an open registry** — adding vibration/fatigue/fire-structural
  must require zero kernel changes. Kernel fixes intent *shape*, not categories.
- **Solver-agnostic at the schema level**: artifact/result schemas speak our
  vocabulary, never an engine's. One blessed engine at a time (xara). Failure
  taxonomy and design checks are kernel-side.
- Boring, inspectable kernel code; cleverness goes in derivation functions and solver
  adapters, behind tests. Every kernel invariant gets a test.
- Non-exhaustive `match` over a union is a bug (`assert_never`).

## Toolchain
Python 3.14 · pydantic v2 · pyright **strict** (must be clean) · ruff (lint+format) ·
pytest + hypothesis (property tests for derivation: determinism, composition laws) ·
uv for env/lock.

```sh
uv sync
uv run pytest
uv run pyright
uv run ruff check && uv run ruff format --check
```

## Repo conventions
- `src/` layout, single package `structural_kernel`; tests in `tests/`.
- ADRs: `docs/decisions/NNNN-short-title.md` (Status/Context/Decision/Consequences);
  never delete superseded ADRs — restatus and link forward. Keep the index table in
  `docs/decisions/README.md` current.
- Design proposals: `docs/design/NNNN-*.md`, graduate to ADRs when they survive review.
- Phase 1 non-goals (charter): no GUI/viewer, no IFC, no CAD/BIM integration, no
  multi-tenant deploy — but solver + storage stay cloud-shaped behind local
  implementations. Don't pay a generality tax.
