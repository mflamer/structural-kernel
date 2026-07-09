# Decision log (ADRs)

This project's canonical model is a graph of design decisions — so is the project
itself. Every significant, settled choice gets a numbered ADR here. Choices still under
review live in `docs/design/` as proposals and graduate to ADRs when they survive.

Format: one file per decision, `NNNN-short-title.md`, containing **Status**,
**Context**, **Decision**, **Consequences**. Superseded ADRs are never deleted; their
status changes and they link forward.

| # | Title | Status |
|---|---|---|
| [0001](0001-repo-and-toolchain.md) | Repository layout and toolchain | Accepted |
| [0002](0002-canonical-units.md) | Canonical SI units with tagged quantities at every boundary | Accepted 2026-07-07 |
| [0003](0003-solver-agnostic-xara-first.md) | Solver-agnostic kernel; xara as the first engine | Accepted 2026-07-07 |
| [0004](0004-intent-registry-and-two-site-enforcement.md) | Intent: kernel-fixed shape, open category registry, two-site enforcement | Accepted 2026-07-07 |
| [0005](0005-eid-identity-scheme.md) | Deterministic element identity: rule-relative eids with per-consumer correspondence | Accepted 2026-07-07 |
| [0006](0006-ndswood-as-nds-engine.md) | ndswood as the NDS calculation engine behind the design-check adapter | Accepted 2026-07-08 |
| [0007](0007-multi-material-design-engines.md) | Multi-material design-check engines behind a common adapter (wood/steel/concrete + ASCE 7 loads) | Accepted 2026-07-08 |
| [0008](0008-steel-framing-and-heterogeneous-exploration.md) | Steel framing decision kind (three-tier, AISC/LRFD) and heterogeneous exploration | Accepted 2026-07-08 |
| [0009](0009-llm-proposer.md) | The LLM proposer behind the Proposer seam (Anthropic client + fake, propose-only) | Accepted 2026-07-08 |
| [0010](0010-closed-loop-llm-refinement.md) | Closed-loop LLM refinement (feed prior results back; converge on budget or satisfaction) | Accepted 2026-07-08 |
| [0011](0011-spatial-structural-constraints.md) | Spatial structural constraints: a project-constraint primitive + predicate registry, conversationally captured | Accepted 2026-07-08 |
| [0012](0012-cost-basis-and-priced-evaluation.md) | Cost basis as a versioned decision (a table of priced factors over derived countables); priced evaluation layered over reused physics | Accepted 2026-07-08, revised 2026-07-09 (note 0003) |
| [0013](0013-ingestion-seam-referenced-geometry-and-inferred-provenance.md) | The ingestion seam: referenced geometry as a read-only external kind + inferred→ratify constraint provenance (inert until ratified); capture reads drawings, not just conversation | Accepted 2026-07-09 (note 0004; graduates design doc 0005) |
