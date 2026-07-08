# 0008 — Steel framing decision kind and heterogeneous exploration

**Status:** Accepted (2026-07-08, product owner directed; first phase-2 kind,
builds on ADR 0007)

## Context

ADR 0007 generalized the design-check boundary to a material-engine registry and
shipped a real, tested `SteelEngine` (AISC 360-22) — but no steel *framing
decision kind* existed, so nothing derived steel members and nothing exercised
the vision's first ambition: **system selection as exploration over
heterogeneous branches** (candidates of different decision *kinds*, not one
strategy's parameters — standing requirement 1). That was named the
representation-gated phase-2 lift.

The product owner directed this sprint forward, deliberately crossing the
charter's phase-1 halt for a representation review (choosing "proceed to steel"
over "review first"). The domain choices below are the PO's, a licensed PE:
three-tier framing, continuous top-flange bracing, and AISC **LRFD**.

## Decision

- **A `steel_framing_strategy` decision kind**, sibling to
  `gravity_framing_strategy` in the closed kind union. Its params: `region`,
  `system="beams_on_girders_on_columns"`, `beam_axis`, `beam_spacing`,
  `member_family` (validated against the ADR 0007 registry, not steel-locked —
  the *kind*, not the field, is what makes it steel), `member_grade` (A992), and
  a W-shape `beam_section` / `girder_section` / `column_section` per tier.

- **Three-tier topology: infill beams → girders → columns**, which is
  topologically identical to wood's joists → beams → posts. So one shared
  geometry rule, `_derive_three_tier(vocab)`, derives both kinds; steel inherits
  wood's proven ADR 0005 eid grammar and exact tributary tiling rather than
  duplicating them. New roles `girder`/`column` with eid tokens `gdr`/`col`; a
  steel infill member is a `beam` (token `bm`), the role shared with wood's mid
  tier. Columns sit at the four region corners (one rectangular bay, as wood).

- **Steel is designed AISC 360-22 LRFD** (the PO's call). The derived `Element`
  carries `design_method` (`ASD` for wood, `LRFD` for steel). Because the
  solve-time checks resolve their engine by `element.family` (ADR 0007), steel
  members earn AISC flexure/shear/compression automatically; the checks pass the
  member's method to the engine.

- **Continuous bracing.** The roof deck braces the beam compression flange
  continuously (Lb = 0, Cb = 1.0), so flexure reaches the full plastic moment.
  A domain assumption, PO-chosen and **confirmed correct for now (2026-07-08)**;
  revisit when a real bracing model (spandrels, Lb at framing points) exists.
  Flagged, not a code constant — realized by the flexure check's default
  `unbraced_length_m = 0`, the same posture wood takes for sheathed members.

- **Load combinations carry a `purpose` (strength | service).** LRFD needs ASCE
  7-22 §2.3 strength combinations, and deflection — a serviceability limit — is
  a load-level check under *service* (unfactored) loads regardless of the
  member-design method (IBC 1604.3). So `loads.py` tags combos: the ASD §2.4 set
  is service-level and serves both stress and deflection; the LRFD §2.3 set
  carries factored strength combos (member design) plus unfactored service
  combos (deflection). Strength checks consume the demand combos of the member's
  method; deflection always consumes service combos. Each candidate's
  `load_assumptions` selects its `combo_set`.

- **Heterogeneous exploration.** `SystemChoiceProposer` emits a fixed slate of
  candidate systems — possibly of different kinds — ranked as one generation on
  the method-neutral **member-mass** metric. The proposer is the only place
  kinds are chosen; validation, derivation, the batch solve, the metric, and the
  ranking already treat each candidate as an ordinary branch and assume nothing
  about a shared strategy. Each candidate is designed to its own code (NDS/ASD
  wood, AISC/LRFD steel) and compared on mass.

## Consequences

- Adding steel framing was a **decision kind + derivation rule + the LRFD
  combo/purpose split** — the material engine (ADR 0007) was already done and
  tested. Concrete remains gated on its own decision kind.

- **Wood is byte-identical.** ASD combos are service-level, so wood stress and
  deflection are unchanged, and `design_method` defaults to `ASD`. The
  wood-vs-steel geometry share is covered by wood's existing property tests.

- **The charter's phase-1 representation-review gate was crossed deliberately**
  by PO direction. The shape questions in `docs/kernel-internals.md` remain
  open; this ADR extends the graph that review will examine rather than
  answering it.

- **Deferred, honestly:** steel does not yet participate in the opening rule
  (steel headers), interior columns and multi-bay frames are unmodeled (one
  rectangular bay, four corner columns — the same limit as wood), true LTB with
  a real Lb, HSS/A500 columns, and `cost_basis` ranking. One blessed method per
  material for now (steel LRFD, wood ASD); the seam admits others.

- The first heterogeneous ranking is real: over a small bay wood wins on mass
  with steel far under-stressed — the honest outcome when the smallest practical
  W-shapes are overkill for a short span. Cost (a later sprint) is where steel's
  installation economics would actually compete.

Supersedes nothing; extends ADR 0007 (the steel engine) and ADR 0005 (the eid
grammar the shared geometry rule preserves).
