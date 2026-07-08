# 0007 — Multi-material design-check engines behind a common adapter

**Status:** Accepted (2026-07-08, product owner directed; generalizes ADR 0006)

## Context

ADR 0006 wired ndswood (NDS 2024) as *the* NDS engine behind the design-check
adapter. The product owner maintains sibling libraries built to the same
pattern: **aiscsteel** (AISC 360-22 steel) and **aciconcrete** (ACI 318-19
concrete), and an ASCE 7 load library. All three member-design libraries are
pure-Python, zero-dependency, and — by deliberate design — share a
`Factor`/`CheckResult` result shape: `demand, capacity, ref, factors`, with
`ratio`/`passes` properties and a per-factor code reference.

Phase 1 is wood-only, but the kernel should be ready for steel and concrete so
that adding a material is implementing an adapter, not restructuring the kernel.
Investigating the libraries surfaced real divergences that any uniform boundary
must absorb (see Consequences).

## Decision

- **The kernel is code-agnostic the way it is solver-agnostic (ADR 0003).**
  Verified code libraries are *engines* behind a common `MaterialEngine`
  adapter — one per material family — resolved from a registry
  (`materials/registry.py`) by the `member_family` a decision records. This
  generalizes ADR 0006: ndswood is now one registered engine, not the boundary.
- **The neutral result vocabulary is `MemberCheckData`**: demand and capacity
  as tagged SI magnitudes *with a dimension* (stress for wood member checks,
  moment/force for steel and concrete — the wood-only `demand_pa` assumption is
  removed), plus unity, pass/fail, the provision citation, and the factor audit
  trail (`ProvisionFactor` with its code reference). No library type crosses
  this boundary; units convert once per adapter.
- **Registered catalog engines (phase 1): wood and steel.** `WoodEngine`
  (`sawn_lumber`) and `SteelEngine` (`hot_rolled_steel`) both implement the
  protocol — a member is a catalog designation plus a grade. The steel adapter
  is real and unit-tested against aiscsteel (W-shape flexure/shear/axial, real
  AISC provisions), proving the vocabulary is material-neutral, not wood-shaped.
- **Concrete is deliberately not a catalog engine.** A concrete member is
  geometry (b, h) plus reinforcement, not a designation — aciconcrete reflects
  this with `Beam`/`Column` classes, LRFD-only, `informational` results and an
  `extra` bag. `materials/concrete.py` proves the neutral vocabulary carries
  concrete results (moment-dimensioned, informational skipped, provisions
  intact) but does not register; concrete becomes a full engine when the
  phase-2 concrete framing decision kind exists to describe its members.
- **`member_family` is validated against the registry**, not a closed literal,
  so a steel framing decision kind needs no schema change here — only its own
  kind and derivation rule.
- **Load combinations are the ASCE 7 seam** (`loads.py`): `combos_for(combo_set,
  cases)` is where the ASCE 7 library plugs in as the combination engine, keyed
  by the `combo_set` a `load_assumptions` decision selects. Today it carries the
  built-in phase-1 set (ASCE 7-22 §2.4 ASD, gravity slice); the library was not
  found in the repos as of this ADR, so the seam ships with the built-in and
  delegates when the library lands.
- **Distribution:** aiscsteel and aciconcrete are core dependencies (pure-Python,
  zero-dep, install everywhere — unlike xara), git sources like ndswood, with
  per-repo read-only CI deploy keys.

## Consequences

- **Divergences the adapter absorbs**, found in the libraries and handled at
  each adapter, never leaked: steel's `method`/`limit_states`/`governing` fields
  (governing is captured onto `MemberCheckData.governing`); concrete's
  `extra`/`informational` (informational results treated as passing
  annotations); differing native units (wood psi/lb-in, steel kip/kip-ft,
  concrete lb/in-lb); differing construction (steel/wood catalog `Member`,
  concrete `Beam`/`Column`); and the fact that a flexure check's demand is a
  stress in wood but a moment in steel/concrete.
- Adding steel framing to the kernel is now: a `steel_framing_strategy` decision
  kind + its derivation rule (heterogeneous exploration, per the vision) — the
  material engine is already done and tested. That decision-kind work is the
  representation-gated phase-2 lift, not this ADR.
- The exit stays cheap: replacing any engine is an adapter rewrite, never a
  schema migration; one blessed engine per family.
- Supersedes nothing; extends ADR 0006 (wood remains exactly as specified there,
  now expressed as the first registered engine).
