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
  `docs/design/0002-review.md`; graduated to ADR 0005) — the R1 gate is lifted.
- **Increments 1–3 done** (2026-07-07): units/canonical/store/object schemas;
  decision-kind param schemas + the propose → validate → commit pipeline; derivation
  (ADR 0005 eid grammar + property tests, members/load-path/header-with-derived-intent,
  bill with countables, §7.1 analysis artifact as decoupled simple spans — documented
  idealization) wired in as validation stage 3, with `dangling_exception` and
  `derivation_failure` as structured rejections. Stage 4 (intent checkers) is the
  remaining seam. Milestone acceptance tests 2 of 7 earned.
- **Increment 4 done** (2026-07-07): solver service (`solver.py` — cloud-shaped
  interface, SolveResult with engine class/fidelity, failure taxonomy), shared planar
  idealization (`planar.py`), the xara adapter (`xara_adapter.py`, import-guarded),
  and the hand-calc verification suite (4 fixtures at 0.5%/0.1% tolerances) proven
  against the ADR 0003 direct-stiffness cross-check (`tests/reference_solver.py`),
  including an end-to-end derive→solve→hand-calc test.
- **CI live (GitHub Actions, 2026-07-08): acceptance test 3 earned on Linux.** The
  verification suite runs through the real xara engine on every push (89 passed
  there; Windows runs the reference engine only, 1 skip). Milestone acceptance:
  3 of 7. Engine platform facts, learned the hard way: xara needs CPython ≤ 3.13
  (opensees wheels top out at cp313 — hence the 3.13 floor), Linux-only wheels,
  and a Tcl 8.6 runtime (uv-managed CPython bundles Tcl 9; CI takes its
  interpreter from actions/setup-python). Revisit when xara ships cp314/Windows
  wheels.
- **Increment 5 done** (2026-07-08): reality overrides — the §5 composition rule
  (derive on decisions → override substitution → downstream artifacts), ADR 0005
  re-attachment states (attached / displaced / dangling with candidate re-targets),
  confidence-bucketed tolerances (measured 25mm / estimated 150mm / assumed
  advisory), provenance on every overridden field flowing into bill + analysis,
  and displaced/dangling surfaced as commit *warnings* (never rejections, never
  dropped). Milestone acceptance: 4 of 7.
- **ADR 0006** (2026-07-08): ndswood (the PO's verified NDS 2024 library, now at
  github.com/mflamer/ndswood, private) is the NDS engine behind the design-check
  adapter — a deliberate carve-out to the clean-slate clause for verified
  domain-calculation libraries. No ndswood type in persisted schemas; SI⇄lb-in
  conversion at the adapter; CI reads it via deploy key (NDSWOOD_DEPLOY_KEY).
  Retires note 0003 item 1 (sections.py goes away with the design-check work).
  Next: increment 6, intent checkers + solve-time design checks (NDS ASD unity +
  L/360–L/240 deflection via ndswood, both citing intent per ADR 0004) — earns
  acceptance test 5.
- Domain items awaiting PO check (flagged, not blocking): sawn-lumber dressed-size
  table and DF-L No.2 reference E in `src/structural_kernel/sections.py`;
  `member_grade` as a framing param; header bearing 3 in each side, section =
  beam_section; gravity-slice ASD combo subset in `derivation._asd_combos`.
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
