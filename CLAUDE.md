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
- `docs/design/0001-kernel-and-solver-architecture.md` — architecture proposal
  (decision graph, derivation contract, changesets, overrides, intent registry,
  analysis artifacts, solver service, explorations, xara-first solver posture).
- `docs/decisions/` — ADR log. Settled choices only; proposals live in docs/design/
  until they survive review. This project is itself decision-derived; eat the dog food.

## Current status / gates (update this section as things change)
- **Pre-implementation.** Design doc drafted, §7.3 re-cut in review 2026-07-07
  (solver-agnostic; xara is the first engine; purpose-built solver demoted to a
  test-fixture cross-check). Awaiting product-owner review of the rest.
- **Implementation is gated on open questions 1–2** (design doc §10): material domain
  for the phase-1 structure (wood/NDS vs steel/AISC) and which load combinations
  define unity (ASD vs LRFD). Do not start kernel code until the PO answers.
- One open action: email xara's maintainer (STAIRLab) to confirm whole-tree
  BSD-2-Clause relicensing covers the inherited OpenSees core.
- Increment order after review: store + schemas → decisions + validation → derivation
  for the milestone structure → xara adapter + verification → overrides → intent
  checkers → exploration loop. Small, reviewable increments; milestone criteria in
  the charter are the acceptance tests, written early, red until earned.

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
