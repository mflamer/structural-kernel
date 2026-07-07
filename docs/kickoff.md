# Project Kickoff: AI-Native Structural Building Model

## What we're building

A cloud-native building information system designed from scratch with AI as the primary interface, attacking structural engineering first. This is not an IFC successor, not a plugin for any existing CAD/BIM tool, and not a file format. It is a new answer to the question "what is a building, informationally?" — designed so that a language model can read, reason about, and safely modify a building model at the level of design decisions, and so that a cloud solver fleet can evaluate many design variants in parallel.

**Clean slate:** This project inherits nothing from any of my existing tools, schemas, or integrations. No prior conventions, formats, or architectural choices carry over. Every decision gets made fresh on its own merits and documented.

I am a licensed structural engineer (PE, Washington State). I will act as domain expert and product owner. You are the architect and implementer. Push back on my ideas when the engineering says otherwise.

## Strategic focus

The kernel is structural-native. Decisions are framing strategies, lateral systems, and load assumptions; elements are members, connections, and assemblies; derived artifacts are analysis models, design checks, and schedules. We are building the system of record for structural engineering, not a general building platform that happens to do structural first. The wedge: an AI-native structural design record where design intent maps to code provisions and load paths, derivation produces analysis models and design checks, and parallel cloud solving makes design-space exploration cheap. Structural is the right domain because engineering design is constraint satisfaction — verifiable against physical law and building code — which is exactly what makes AI-driven design trustworthy. If broader ambitions ever revive, that is a future problem; do not pay a generality tax for it now.

## Core representational principles

These are the load-bearing ideas. Everything else is negotiable.

1. **Intent is first-class data — structural intent.** Every element carries *why* it exists structurally, not just what it is. A beam exists *to carry a wall above, per specific load combinations*; a header exists *to redirect gravity load around an opening below it*; a retrofit frame exists *to restore lateral capacity removed by an alteration*. Intent is structured — typed relationships to loads, load paths, and code provisions — not freetext. This is what lets an AI evaluate whether a proposed change breaks the design, not just the geometry. The AI interface captures intent conversationally during design; the human never fills in intent forms. Structural intent is already plural — gravity load path, lateral capacity, serviceability, retrofit rationale in phase 1; vibration, fatigue, fire-structural, progressive collapse later — so the intent type system must accept new structural categories without kernel changes. Don't hardcode the enum. Non-structural intent (egress, daylight, program) is out of scope entirely.

2. **Derivation over storage.** The canonical model is the minimal set of design decisions: grids, load assumptions, structural strategy, framing rules, exceptions. Geometry, analysis models, design checks, schedules, and drawings are *derived artifacts* computed by pure functions over the decision graph. The building is closer to source code than to a database of shapes. This gives us diffs, bisection, reproducibility, decision-level editing — and, critically, cheap branching: N variants of the decision graph derive N analysis models that can be solved concurrently.

3. **Reality override layer.** Real buildings are full of exceptions, and as-built/surveyed conditions don't derive from anything clean. An explicit override layer lets surveyed reality pin or replace derived values, with provenance (who measured it, when, confidence). Derivation and overrides must compose predictably. This is essential for retrofit and alteration work, which is a core target use case.

4. **Transactional, validated mutation.** The AI never edits state directly. It proposes a changeset; the kernel validates it (schema, constraints, intent consistency) and commits or rejects with structured, actionable errors. Every commit is versioned with git semantics: branches for design options, merges, history, blame.

5. **AI-native surface.** The external interface is an API designed for LLM consumption (eventually an MCP server): queryable ("all beams supporting level 2"), explainable ("why does this member exist?"), diff-oriented, and exploration-oriented ("solve these 40 variants and rank by steel tonnage"). No GUI in scope for now.

6. **Solver as a horizontally scalable service.** Analysis is a stateless cloud service, not a desktop process. A derived analysis model is a self-contained, serializable artifact; the solver service accepts a batch of them, fans out across workers (containers), and returns structured results keyed to the originating decision-graph branch. Design-space exploration — parameter sweeps, option studies, optimization loops driven by the AI — is a first-class workflow, not an afterthought. Individual linear-elastic building models solve in milliseconds; the value of parallelism is breadth (hundreds of variants) and depth (nonlinear/dynamic runs), so the architecture must make dispatching 500 solves as easy as dispatching one.

7. **The exploration loop is a first-class idiom.** Propose → derive → solve → evaluate → propose again is the fundamental unit of AI-driven design in this system, not an application built on top of it. The kernel provides it as a named, persistent, versioned object: an *exploration* has objectives (minimize steel weight, maximize opening size), hard constraints (all members under unity, drift limits, intent preserved), generations of candidate branches, solve results, and — critically — the proposer's recorded rationale for each candidate. The proposer is a pluggable strategy: a parameter sweep, a numeric optimizer, or an LLM. Every exploration is fully auditable and replayable, because an engineer of record must be able to show not just the chosen design but the space that was searched and why. Convergence criteria, budget limits (max solves, max generations), and early termination are kernel concerns, not caller concerns.

## Explicit non-goals (for now)

- No 3D viewer, no rendering, no GUI.
- No IFC import/export in phase 1 (interop later; don't let IFC's ontology contaminate the kernel).
- No integration with any existing CAD/BIM product.
- No multi-tenant cloud deployment yet — but the solver service and storage layer are designed cloud-first from day one (stateless, containerized, queue-friendly) and run locally in phase 1 via the same interfaces (e.g., local container or process pool standing in for the fleet).
- No attempt to cover all building types or all of the code. Validate with simple structures and a narrow slice of provisions first.
- **Deferred, not dropped:** referencing external geometry. A structural system of record lives downstream of someone else's architecture — eventually we need a way to *reference* the architect's model or surveyed as-built geometry as read-only context (the authority boundary: we own structure, we consume everything else). Not in phase 1, but no kernel decision should make it impossible.

## Technical decisions

- **Language:** Python 3.14, strict typing (pyright/mypy clean), pydantic for schema. Use discriminated unions for sum types (intent categories, decision kinds) and `match` statements checked for exhaustiveness — treat a non-exhaustive match over a union as a bug.
- **The persisted schema is the source of truth, not the Python code.** Everything in storage is language-neutral, versioned JSON in the content-addressed store — no pickle, no Python-specific serialization, nothing another language couldn't read and validate against the schema alone. The Python kernel is one implementation of the schema, deliberately replaceable (e.g., by Rust) once the representation is proven, without any migration of stored data.
- **Schema:** Versioned from day one (`schema_version` on every persisted artifact). Migrations explicit.
- **Units:** Explicit at every boundary — no bare floats crossing an interface without declared units. Propose an internal canonical unit system and justify it in the design doc.
- **Solver:** Do not pre-commit. Evaluate candidates (OpenSees, CalculiX, code_aster, or a purpose-built linear solver) against: headless/container-friendly, permissive licensing for commercial use, robustness for frame/wall building structures, and a clean path to nonlinear and dynamic analysis. Recommend one in the design doc with rationale. The solver sits behind an interface so it is replaceable.
- **Persistence (phase 1):** Content-addressed object store on disk (git-like), behind a storage interface that a cloud database can later implement.
- **Testing:** pytest; derivation functions property-tested where practical; solver results verified against hand calculations and published benchmark problems. Every kernel invariant gets a test.

## Phase 1 milestone (concrete and verifiable)

Model a small structural problem end-to-end through the decision → derivation → parallel solve → query loop:

- A one-story structure defined only by decisions: a grid, a gravity framing strategy (joists/beams/posts with spacing and bearing rules), one lateral strategy decision, and one wall opening (dimensions given as a decision, no reason modeled) whose derivation induces a header — and the header carries structured structural intent: it exists to redirect the gravity load path around the opening.
- Derivation produces: explicit member instances with spans and tributary widths, a self-contained analysis model artifact, and a bill of elements.
- The solver service (running locally behind the cloud-shaped interface) solves the analysis model; results are verified against hand calcs to defined tolerances.
- **Exploration via the first-class idiom:** run an `Exploration` object with an objective (minimize total material weight), hard constraints (all members under unity), and a sweep proposer (e.g., joist spacing at 12"/16"/19.2"/24" crossed with two or three beam layout options). All candidate branches dispatch to the solver service concurrently; the exploration record persists every generation, result, and ranking, and is replayable. The proposer interface must be demonstrably pluggable — include a stub showing where an LLM proposer slots in (the real LLM proposer is phase 2).
- Queries work: "what carries joist J5?", "why does opening D1 have a header?", "which variant minimizes steel weight while keeping all members under unity?"
- One override: pin a surveyed member size that differs from the derived value and show it flowing through derivation and analysis with provenance intact.
- A changeset that violates structural intent (e.g., deleting the header while the opening remains, or removing a member whose intent says it carries load) is rejected with a structured error citing the violated intent and the broken load path.

When this milestone passes its tests, we stop and review the representation before adding scope.

## How to start

1. Before writing code, produce a short design document (`docs/design/0001-kernel-and-solver-architecture.md`): the decision-graph data model, the derivation function contract, the changeset/validation lifecycle, override semantics, the structural intent type system (open to new structural categories — vibration, fatigue, fire-structural — without kernel changes), the analysis-model artifact format, the solver service interface (batch dispatch, result schema, failure handling), the exploration object lifecycle (proposer contract, objective/constraint schema, generation semantics, persistence), and your solver recommendation. Include the questions you think are unresolved. I'll review before implementation.
2. Propose the repository structure and tooling setup.
3. Then implement toward the phase 1 milestone in small, reviewable increments.

## Working conventions

- Keep a running `docs/decisions/` log (ADR style) — this project is itself decision-derived; eat the dog food.
- When domain questions arise (structural behavior, code requirements, how engineers actually think), ask me rather than guessing.
- Prefer boring, inspectable implementations in the kernel. Cleverness goes in derivation functions and solver adapters, behind tests.
