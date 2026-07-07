# 0002 — Canonical SI units with tagged quantities at every boundary

**Status:** Accepted (2026-07-07, product-owner review of design doc 0001 §2.4)

## Context

The charter requires explicit units at every boundary — no bare floats crossing an
interface. A canonical internal system had to be chosen. US customary conventions
(lbf vs lbm ambiguity, the kip-in vs kip-ft split inside a single calc) are classic
silent-error factories, but US customary is the register the product owner practices
in (ft-in, kips, psf, ksi).

## Decision

- **Canonical internal system: SI base** — newtons, meters, seconds, kilograms;
  derived Pa, N·m. All derivation math, solver artifacts, and stored values are
  canonical SI floats. A kip-inch internal convention was considered and rejected.
- **Every value crossing any interface travels as a tagged quantity**:
  `{ "mag": 4448.22, "unit": "N" }`. The tag is not decoration — schema validation
  checks dimensional correctness (an area load must be Pa-dimensioned), so a bare or
  mis-dimensioned float is a *rejected changeset*, not a latent bug.
- **Unit spellings are a curated whitelist** — no free-form unit-expression parser in
  the kernel. Conversion tables are code, tested against known constants
  (1 kip = 4448.2216152605 N, per NIST).
- **Authoring and display register: US customary** (ft-in, kips, psf, ksi). The unit
  layer accepts `"16 in"`, `"40 psf"`, `"50 ksi"` at the API boundary and renders
  results back in the same register. One conversion in at the authoring boundary, one
  out at the display boundary, and nowhere else. Unit preferences are a presentation
  concern, never stored in the model.

## Consequences

- The kernel never hosts mixed-unit arithmetic; unit bugs are confined to the two
  conversion boundaries, which are exhaustively testable.
- Persisted artifacts are unambiguous to any future implementation language.
- Dimensional validation becomes part of changeset schema validation (design doc §6,
  stage 1).
