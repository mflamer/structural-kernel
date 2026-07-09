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
  Retires note 0003 item 1 (sections.py deleted; ndswood is the sections/grade
  source).
- **Increment 6 done** (2026-07-08): the intent registry (`intents.py` — four
  phase-1 categories as (name, payload schema, roles, checker) registrations;
  adding `vibration` later = one registration) wired as validation stage 4, with
  the opening-interruption checker realizing the charter's "delete the header
  while the opening remains" rejection (structured error: category, broken load
  path, opening did). Solve-time design checks (`design_checks.py` via `nds.py`,
  the ADR 0006 adapter): NDS 2024 ASD bending/shear/post-compression + L/360–L/240
  deflection, every check citing its NDS provision (ndswood factor trail) and the
  intent instance it enforces; verification-grade results required. The §6
  validation pipeline is complete.
- **Increment 7 done (2026-07-08): THE PHASE-1 MILESTONE IS COMPLETE — all 7
  acceptance tests green.** `explorations.py`: the first-class Exploration object
  (candidates carry physics only; evaluations a separate collection keyed by
  (result set, cost_basis) per PO reply item 3), kernel-owned lifecycle (real
  branches through the ordinary pipeline, rejected candidates recorded and never
  solved, one batch submit per generation, every generation persisted, replayable),
  grid-sweep + stub LLM proposers behind one protocol. `queries.py`: what_carries /
  why / header_for_opening / best_variant. Mass metric uses ndswood G with a
  documented 0.5 fallback (noted in evaluations).
- **Multi-material engine preparation done (2026-07-08, PO-directed): ADR 0007.**
  The ndswood boundary is generalized to a `materials/` engine registry keyed by
  `member_family`. `MemberCheckData` now carries demand/capacity as tagged SI with
  a *dimension* (stress for wood, moment/force for steel/concrete). Registered
  catalog engines: `WoodEngine` (sawn_lumber, ndswood) and a real, unit-tested
  `SteelEngine` (hot_rolled_steel, aiscsteel). Concrete (`materials/concrete.py`)
  proves the vocabulary spans the dimensional+reinforced case but is *not* a
  catalog engine — it registers when the phase-2 concrete framing decision kind
  exists. `loads.py` is the ASCE 7 combo-set seam (built-in phase-1 set; the ASCE 7
  library plugs in there — repo not found as of this work). aiscsteel/aciconcrete
  are core git deps (pure-python, install everywhere); CI reads all three private
  libs via per-repo deploy keys (`.github/deploy-keys.sh`). All 129 tests green.
  **This is preparation only** — no steel/concrete *framing decision kind* exists
  yet; wiring steel into derivation + heterogeneous exploration remains the
  representation-gated phase-2 lift.
- **Phase-2 sprint 1 done (2026-07-08, PO-directed): ADR 0008 — steel framing +
  heterogeneous exploration.** The PO directed the sprint forward, *deliberately
  crossing* the charter's phase-1 halt (chose "proceed to steel" over "review
  first"). **The PO has since approved the representation (2026-07-08)** — the
  gate is lifted; see below. Added the
  `steel_framing_strategy` decision kind (three-tier beams→girders→columns, A992,
  AISC 360-22 **LRFD**, continuously braced Lb=0 — PO domain calls). Wood and
  steel share one geometry rule (`_derive_three_tier`), so steel inherits the
  ADR 0005 eid grammar; new roles girder/column, tokens gdr/col. Steel members
  carry `design_method` and earn AISC checks automatically (checks resolve the
  engine by family, ADR 0007). `loads.py` grew a combo **purpose** (strength |
  service): LRFD sizes on §2.3 factored combos but deflection stays a service-
  level check — wood (ASD, service-level) is byte-identical. `SystemChoiceProposer`
  ranks candidates of *different kinds* (a wood scheme vs a steel scheme) on the
  method-neutral member-mass metric through the ordinary pipeline (standing
  req. 1, now exercised end to end). All gates green.
- **Representation review: APPROVED by the PO 2026-07-08.** The phase-1 decision
  graph, the ADR 0005 eid scheme, and the two-site intent split are the accepted
  representation for phase 2 (the charter's halt gate is lifted). Approval covers
  the *structure*, not the flagged domain-value items below, which stay open. See
  the closing note of `docs/kernel-internals.md`. Continuous bracing (Lb=0) for
  steel confirmed correct-for-now by the PO (2026-07-08, ADR 0008).
- **Phase-2 sprint 2 done (2026-07-08, PO-directed): ADR 0009 — the LLM
  proposer.** A real LLM now drives exploration behind the existing `Proposer`
  seam. `llm.py` is the provider-neutral `LLMClient` protocol (`invoke_tools`:
  prompt + tool schemas → the tool calls the model chose) with a deterministic
  `FakeLLMClient` (tests/CI) and, in `llm_anthropic.py`, the real
  `AnthropicClient` (optional `llm` extra, model `claude-opus-4-8`,
  `tool_choice=any`, SDK-isolated). `LLMProposer` prompts a propose_wood /
  propose_steel tool pair and emits a single **heterogeneous slate** — the KIND
  is chosen by which tool the model calls. Propose-only: the model's tool calls
  become ordinary changeset proposals, malformed/intent-violating ones are
  recorded rejections (never committed) — the charter's "AI never edits state
  directly" holds by construction. Replay reads the recorded slate, never
  re-calls the model; the model identity is on the `ProposerRef`. CI is
  deterministic and secret-free (fake client only). All gates green.
- **Phase-2 sprint 3 done (2026-07-08, PO-directed): ADR 0010 — closed-loop LLM
  refinement.** `LLMProposer` gains a `refine` flag (default single-slate is the
  ADR 0009 behavior). In refine mode each later generation feeds the prior
  round's results back — per candidate: kind, member sizes, feasible?, mass,
  worst unity; rejected → reason; plus the best feasible so far — and prompts for
  an improved slate (heavier where a check governs, lighter where there is
  margin). The loop ends when the model proposes nothing or the kernel's
  convergence/budget stops it; no new stopping machinery (the lifecycle already
  looped generations). Still propose-only, still replay-by-record; the mode is on
  the `ProposerRef`. `ScriptedLLMClient` (slate-per-call) drives the deterministic
  closed-loop tests. All gates green.
- **Phase-2 sprint 4 done (2026-07-08, PO-directed): ADR 0011 — spatial
  structural constraints (the vision's item 3).** The PO's note 0002 reframed the
  "capture the west 40 ft as a clear-span intent" increment into the general
  primitive: a first-class **`ProjectConstraint`** graph object (a *third* fact
  category beside decisions and overrides — not a Decision, not element intent,
  because the constraint precedes the structural system), a region in the ADR 0005
  anchor vocabulary (`OffsetBand`/`GridBoundedRegion`/`WholePlan`), and an **open
  predicate registry** (`constraints.py`: `register_predicate` = the whole
  extension surface, the ADR 0004 move applied to constraints). Two instances:
  `no_vertical_support_within` (clear-span, open-band — boundary supports allowed
  so the span can be carried) and `min_bay_spacing`. Enforced as `propose` stage 5
  on *every* changeset; since exploration candidates are ordinary changesets, a
  candidate with a post in a protected region is rejected pre-solve
  (`SpatialConstraintsPreservedConstraint` makes the binding explicit). Capture
  (`capture.py`) reuses the ADR 0009 LLM seam: an utterance → `capture_*` tool
  calls → `AddConstraint` ops → the ordinary pipeline; propose-only, authored
  provenance, model identity recorded; malformed captures are recorded rejections;
  `FakeLLMClient` drives CI. **The extensibility proof is a real test:** a third
  predicate `clear_height_below` registers and enforces with zero kernel change.
  `Snapshot` gained `constraints`; the write path gained
  `AddConstraint`/`RemoveConstraint`. All gates green.
- **Deferred (phase-2 continues):** the `inferred`→ratify ingestion seam (design
  doc 0005) that would let capture propose from drawings, not just author from
  conversation; min-bay region scoping ("everywhere *else*" relative to the clear
  zone); solve-site spatial predicates; referenced-geometry regions;
  governing-member feedback (name the check, not just max_unity) and loop-until-dry
  diversity for the refinement loop; steel headers (openings don't yet induce over
  steel); interior/multi-bay columns; true LTB with a real Lb; HSS/A500 columns;
  lateral analysis; cost_basis evaluation; concrete framing kind.
- Domain items awaiting PO check (flagged, not blocking): sawn-lumber dressed-size
  table and DF-L No.2 reference E in `src/structural_kernel/sections.py`;
  `member_grade` as a framing param; header bearing 3 in each side, section =
  beam_section; gravity-slice ASD combo subset in `derivation._asd_combos`;
  clear-span as the *open* band (supports on the bounding line allowed so the span
  can be carried — ADR 0011). Min-bay counts bearing walls as bay lines alongside
  columns (PO-confirmed 2026-07-08): a wall defines a bay line on the axis it runs
  across.
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
