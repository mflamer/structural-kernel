# 0003 — Solver-agnostic kernel; xara as the first engine

**Status:** Accepted (2026-07-07; design doc 0001 §7.3 as re-cut in product-owner
review, confirmed in the review response, Q10)

## Context

The charter forbade pre-committing to a solver and set criteria: headless and
container-friendly, permissive commercial licensing, frame/wall robustness for
building structures, and a clean path to nonlinear/dynamic analysis. The first draft
of design doc 0001 recommended a purpose-built linear solver for phase 1, driven
partly by a misreading of the OpenSees license. Two facts changed the picture:
OpenSees's clause (b) permits internal commercial use (reserving only incorporation
into distributed products), and xara exists — STAIRLab's BSD-2-Clause Berkeley
refactoring of the OpenSees engine — removing licensing from the critical path.

## Decision

- **The kernel is solver-agnostic by design, won at the schema level.** The
  analysis-model artifact and `SolveResult` schemas speak the kernel's vocabulary —
  releases, sections, loads, combos, end forces — never an engine's idioms. Adapters
  translate in both directions.
- **The failure taxonomy is kernel-side.** Adapters map engine noise into structured
  failures (`mechanism_detected`, `singular_system`, `invalid_artifact`,
  `worker_crash`). Callers and explorations never see engine-specific errors.
- **Design checks are kernel-side** — unity, deflection limits, provision citations
  consume solve results but are never engine output.
- **First engine: xara** (OpenSeesRT), from phase 1. Phase-1 solver work is the xara
  adapter plus the hand-calc verification suite, which validates the adapter and the
  schema mapping — the two places bugs can actually live.
- **Replaceable ≠ plural: one blessed engine at a time.** Every adapter carries the
  full verification suite. Agnosticism is a cheap exit option, not a backend matrix.
- **Purpose-built solver demoted to test fixture**: a minimal direct-stiffness
  cross-check inside the verification suite, not a service implementation.
- **`SolveResult` carries an engine class / fidelity field from day one**
  (verification-grade xara in phase 1) so tiered screening engines arrive later
  without schema surgery; only verification-grade results feed design checks and the
  engineer-of-record record.

## Consequences

- Engine choice is an adapter decision, not an architecture decision; an engine-ism
  leaking into a schema is a defect.
- One open, non-blocking action: license-confirmation email to the xara maintainer
  (STAIRLab) on whole-tree BSD-2-Clause relicensing including the inherited OpenSees
  core. Drafted at `docs/xara-license-email-draft.md`; the product owner sends it as
  the commercial entity. The adapter interface keeps the exit cheap if the answer
  disappoints.
