# 0006 — ndswood as the NDS calculation engine behind the design-check adapter

**Status:** Accepted (2026-07-08, product owner confirmed in session; carve-out to
the charter's clean-slate clause)

## Context

Phase-1 design checks are NDS 2024 sawn-lumber ASD (review Q1/Q2) with L/360 and
L/240 deflection limits (Q3), and every check must cite the provision and the
intent instance it enforces (ADR 0004). The product owner maintains **ndswood** —
a standalone, zero-dependency, pure-Python NDS 2024 member-design library whose
design values are verified against the AWC NDS 2024 Supplement, and whose
``CheckResult`` carries a full factor audit trail (each factor's symbol, value,
and NDS reference).

The charter's clean-slate clause says the project inherits nothing from existing
tools. Re-implementing NDS checks, however, means re-transcribing verified design
values — the highest-risk, lowest-value work available — and the audit-trail
structure ndswood returns is exactly what the kernel's provision citations need.

## Decision

- **The clean-slate clause governs schemas and architecture, not verified
  domain-calculation libraries.** Implementations of code provisions (NDS
  equations, design-value tables) may be engines behind kernel adapters, the
  same posture ADR 0003 gives the solver.
- **ndswood is the NDS engine for phase 1**, behind a kernel-side design-check
  adapter:
  - Kernel check schemas speak *our* vocabulary — demand, capacity, DCR,
    provision citations, the intent instance enforced. **No ndswood type ever
    appears in a persisted schema.**
  - The adapter converts at the boundary: kernel canonical SI ⇄ ndswood's
    lb/in/psi floats (the same one-conversion-per-boundary rule as the
    authoring register, ADR 0002).
  - Provision citations come from ``CheckResult.ref`` and the factor trail —
    real NDS references, not hand-typed strings.
- **Distribution:** ndswood lives at `github.com/mflamer/ndswood` (private, its
  own history); structural-kernel depends on it as a git source. CI
  authenticates with a read-only deploy key (`NDSWOOD_DEPLOY_KEY` secret).
- ndswood remains Python-3.10+/zero-dependency for its Vectorworks consumers;
  structural-kernel imposes nothing back on it.

## Consequences

- Supersedes the hand-built tables in `sections.py` (note 0003 item 1): section
  geometry and reference values come from ndswood's verified data. `sections.py`
  is retired when the design-check increment lands.
- The exit stays cheap: replacing ndswood is an adapter rewrite, not a schema
  migration.
- Later phases get SDPWS 2021 shear-wall/diaphragm checks from the same library
  when lateral analysis arrives.
