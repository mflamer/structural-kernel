# 0014 — Concrete framing: the dimensioned member description (cashing ADR 0007's check)

**Status:** Accepted (2026-07-10, product owner directed; steered by note 0006).
Registers cast-in-place concrete as a real material family — the one deferred
item that could *falsify* a past architectural decision rather than merely
extend it. Relates to ADR 0007 (the material-engine registry and its deliberate
concrete carve-out — the boundary this sprint tests), ADR 0008 (the three-tier
framing pattern and heterogeneous exploration concrete rides), ADR 0011
(role-predicated spatial constraints), ADR 0012 (priced factors over derived
countables), and note 0006 (the sprint steer; its acceptance signals are this
ADR's tests).

## Context

ADR 0007 proved the neutral result vocabulary (`MemberCheckData`) carries
concrete results, then **deliberately did not register** the concrete engine,
stating the reason precisely: *a concrete member is geometry (b, h) plus
reinforcement, not a catalog designation*, and naming the unblock condition —
concrete registers **when a phase-2 concrete framing decision kind exists to
describe its members**. Note 0006 scheduled that sprint and framed the real
acceptance: the boundary is validated iff registering concrete requires a new
framing decision kind and member description **and nothing else** — no change to
`MemberCheckData`, the registry protocol, or how checks are consumed. A forced
change would be a first-class finding, not a nuisance.

The one representational question: **what describes a concrete member in the
decision graph, given it is not a catalog pick?**

## Decision

- **The staging decision (the genuinely new representational choice, made
  explicitly): single-pass, authored-and-checked** (PO call). Reinforcement is
  an *authored parameter* on the member description; the engine **checks** it
  against demand — the same derive→solve→check flow wood and steel use. This is
  the smaller, honest first step: it registers a complete, checkable concrete
  family now. Reinforcement **sized to demand** (derive section → solve →
  detail-derive bars from demands — the staged derivation the charter reserved)
  is the deferred next lift, deliberately not bundled; the description below is
  built to survive that change (the authored spec becomes the staged rule's
  output vocabulary).

- **The member description** (`ConcreteMemberSpec`, `decisions.py`): per tier,
  section geometry `breadth × depth` as tagged lengths plus structured
  reinforcement — longitudinal `bars × bar` (a count and an opaque bar
  designation, "#8", persisted exactly as "W10x12"/"2x10" are), `cover` measured
  **to the tension-steel centroid** so d = depth − cover (PO call; bar-layout
  detailing stays out of scope), optional two-leg stirrups (`stirrup_bar` +
  `stirrup_spacing`, both-or-neither), and `ties | spirals` for columns. Never a
  string schedule. `ConcreteFramingStrategyParams` = region + the three-tier
  system + `concrete_mix` (the mix designation, e.g. "4000psi" — the grade key
  Ec and density resolve from) + `rebar_grade` + beam/girder/column specs.

- **The dimensioned "catalog": a parseable designation.** A rectangular concrete
  section is a *systematic* catalog — `section_designation()` renders the one
  canonical format ("304.8x609.6" = b×h in mm) and the engine parses it back. So
  `section_properties` (gross A, Ig), `elastic_modulus_pa` (Ec = 57000·√f′c,
  ACI 19.2.2.1, from the mix designation), `mass_density_kg_m3` (2400 kg/m³
  normalweight RC), and `nominal_volume_m3` (placed volume — concrete's trade
  pricing basis, the same protocol fact lumber uses for board-feet) all serve
  the **unchanged** `MaterialEngine` protocol; the mass metric, the analysis
  artifact, and `member_weight` costing work with zero site changes.

- **The boundary finding (note 0006 demanded it surfaced loudly):** the
  boundary held **except in one place** — reinforcement, the member fact a
  designation cannot carry, could not ride the catalog-shaped check requests
  without string-encoding. Resolution: `FlexureRequest`/`AxialRequest` gained
  **one additive, family-neutral optional field** (`reinforcement:
  ReinforcementData | None`, the authored vocabulary — bar count + designation +
  cover; the engine resolves areas and depths, bar tables staying behind the
  adapter). Catalog engines ignore it. **`MemberCheckData`, the registry
  protocol methods, and check consumption are untouched** — the boundary was
  drawn correctly where it matters most (results and registry shape); the
  request vocabulary was one notch too catalog-shaped, and the fix was additive,
  not a redraw.

- **Derivation**: `_derive_concrete_framing` rides the *same* `_FramingVocab`
  three-tier geometry rule as wood and steel (roles beam/girder/column, tokens
  bm/gdr/col, ADR 0005 eids for free), designed ACI/LRFD. The vocab gained
  optional per-tier reinforcement; the persisted `Element` gained the optional
  `ElementReinforcement` the checks and takeoff read (catalog members leave it
  None). Openings do not yet induce over concrete (like steel — later).

- **Checks** (aciconcrete, ACI 318-19, all imports behind the adapter): beam
  flexure + shear (two-leg stirrups or Vc alone); column **concentric φPn,max**
  (ACI 22.4.2, tied) — deliberate parity with the axial-only gravity
  idealization wood posts and steel columns get today (PO call); P-M interaction
  (already in aciconcrete: `check_axial_moment`, Bresler biaxial) lands when the
  framing idealization delivers column moments. LRFD-only, guarded. Deflection
  stays the kernel's service-level L/360–L/240 check on the **gross-Ig,
  uncracked idealization** (PO call, documented like phase 1's decoupled simple
  spans; effective-inertia Ie is the deferred refinement — aciconcrete's
  informational Ie results are the hook).

- **Family identity and takeoff facts** (PO calls): family
  `cast_in_place_concrete` (naming the product form, like `sawn_lumber` /
  `hot_rolled_steel`; precast would be another registry row);
  `crane_picks_per_member() = 0` (formed, not picked); formwork contact area by
  role — beams/girders 3 formed sides (b + 2h), columns 4 (2(b + h)).

- **Countables** (note 0003's strict boundary held: derivation emits, pricing
  never invents): three new registered quantity kinds — `concrete_volume`
  (VOLUME, placed volume via the engine fact), `formwork_area` (AREA),
  `rebar_mass` (MASS, longitudinal bars via the adapter's bar table; stirrup
  runs deferred with detailing). Units grew `CY`/`USD/CY` (the trade volume
  unit), `MONEY_PER_AREA` + `USD/m2`/`USD/ft2`, and the price-dimension switch
  maps AREA → MONEY_PER_AREA — additive, the same move ADR 0012 made.
  **`CostFactor`/`DirectPrice` schemas untouched**: the concrete cost drivers
  are appended factor rows, and by the dimension split volume + rebar price as
  material, formwork as installation. One regional basis prices all three
  families; on a model with no concrete the rows resolve to zero.

## Consequences

- **The ADR 0007 boundary is confirmed under a real decision kind** — the
  sprint's purpose. Proven by tests: concrete members earn ACI checks through
  the ordinary engine-by-family path with unchanged result vocabulary; a
  concrete column violates a clear-span constraint **by role**, byte-identical
  to wood/steel; concrete is a candidate family in a wood-vs-steel-vs-concrete
  exploration ranked on the method-neutral mass metric with **no new
  exploration mechanism**; and a formwork-only re-rank moves only the concrete
  candidate over the same stored result set, with no solve.
- The registry's promise strengthened: `MaterialFamily` validates against
  `families()`, so registering the engine made the params schema accept the
  family with zero schema edit — and the note-0003 prediction cashed literally
  (the test suite's example of an *unknown* countable was `formwork_area`; it
  is now a real derived countable).
- **Honest limits, deliberately deferred:** reinforcement sized to demand
  (staged derivation); detailing (development, hooks, bar spacing, stirrup-run
  takeoff); P-M interaction + slenderness (when column moments exist); cracked
  (Ie) deflection; concrete headers over openings; prestressed/post-tensioned,
  two-way slabs, concrete lateral systems. Domain values flagged, not blocking:
  the illustrative member sizes/bars and the seeded concrete prices in
  `tests/conftest.py` (like the other seeded numbers, the mechanism is what
  ships); density 2400 kg/m³; the 3-side/4-side forming rule.
