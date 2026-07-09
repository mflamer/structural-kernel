# 0012 — Cost basis as a versioned decision; priced evaluation layered over reused physics

**Status:** Accepted (2026-07-08, product owner directed). Implements the vision's
item 2 ("cost as the ranking variable, honestly modeled") and its standing
requirements: cost assumptions are decisions; derivation emits countables;
evaluation is a distinct layer from solving (re-ranking must not re-solve);
rankings carry their basis and an uncertainty statement. Builds on ADR 0002
(tagged quantities at every boundary), ADR 0007 (the material-engine registry as
the quantity source), and the exploration/evaluation split from design doc 0001
§8 (evaluations keyed by `(result set, cost_basis)`, already in `explorations.py`).

## Context

The evaluation layer was already shaped for this: `Evaluation` is keyed by
`(result_set, cost_basis)`, `evaluate` reads *stored* solve results and never
solves, and the only metric was `total_member_mass_kg`. What was missing was the
cost model itself — and the charter's hard rules constrain how it may be built:
no bare float crosses an interface, and no price may be hardcoded or live inside a
derivation rule. Cost had to enter as unit-tagged money on a committed decision,
consumed by the evaluation layer, with physics untouched.

Four domain calls (Mark, a licensed PE) fixed the model:

1. **Material rate per family** — steel priced by weight (`$/lb`), sawn lumber by
   *nominal* board-feet (`$/BF`), the two units the trades actually quote.
2. **Installation model** — `connection_count × conn_cost` plus erection hours
   costed at a crew rate, where `erection_hours = piece_count × hrs/piece +
   crane_picks × hrs/pick`. Installation is *not* a fraction of material — that
   divergence is the whole point of item 2.
3. **Crane picks** — one pick per primary steel member; hand-set lumber picks
   zero. A phase-2 family-level simplification (glulam-vs-sawn refinement later).
4. **Uncertainty band** — a fixed percentage committed on the basis (default 4%,
   the vision's "a 4% spread is a coin flip"), never hardcoded.

## Decision

- **Money is unit-tagged like everything else** (`units.py`). New dimensions:
  `MONEY` (`USD`), `VOLUME` (`m3`/`ft3`/`in3`/`BF`/`MBF` — a board-foot is 144
  nominal cubic inches), and the rate dimensions `MONEY_PER_MASS` (`USD/kg`,
  `USD/lb`), `MONEY_PER_VOLUME` (`USD/m3`, `USD/BF`, `USD/MBF`), `MONEY_PER_TIME`
  (`USD/s`, `USD/hr`), plus `hr`/`week` for TIME. Single currency (USD) in phase
  2. Every spelling is NIST-anchored and tested, the same posture as `LINE_LOAD`
  and `MOMENT`. **A rate's *dimension* is the switch** that selects the priced
  quantity — a `USD/lb` rate prices mass, a `USD/BF` rate prices nominal volume —
  so nothing anywhere says "steel is priced by weight"; the unit tag carries it.

- **`cost_basis` is a decision kind** (`objects.py`, `decisions.py`).
  `CostBasisParams` carries: `material_rates` (one unit-tagged rate per family,
  validated money-per-mass-or-volume), `connection_cost`, `crew_rate`,
  `hours_per_piece`, `hours_per_pick`, `lead_times` (per family, in weeks),
  `region`, `as_of`, and `uncertainty_pct`. It **derives no geometry** — the
  `derive` rules ignore it — so it is pure data the evaluation layer reads; the
  only wiring is `parse_params` + `line_refs` (empty; it is global). A revised
  basis (the fabricator's re-quote) is a *new* `cost_basis` decision, so every
  ranking cites exactly what it was priced under.

- **Derivation emits the installation countables** (`derivation.py`). `crane_picks`
  is now populated — `sum(engine.crane_picks_per_member())` over catalog members —
  joining the piece and connection counts already in the bill. Two family facts
  land on the `MaterialEngine` registry (ADR 0007), alongside `section_properties`
  and `mass_density`: `crane_picks_per_member()` (steel 1, wood 0) and
  `nominal_volume_m3()` (lumber's board-foot volume from the designation; steel,
  priced by weight, returns `None`). Counts are geometry; productivities and rates
  are the *basis's*, so nothing about erection method is baked into physics.

- **Priced evaluation is layered over stored results** (`explorations.py`).
  `evaluate(store, exploration, cost_basis)` computes, per candidate,
  `material_cost_usd` (family rate × the quantity its dimension selects) +
  `installation_cost_usd` (the countable model above) = `installed_cost_usd`, all
  in canonical USD, added to `metrics` beside mass and unity. `run_exploration`
  threads the basis; an `installed_cost_usd` objective ranks the heterogeneous
  wood-vs-steel slate by installed cost through the ordinary `_rank`. Lead times
  become per-candidate `flags` that annotate but never price in; the ranking's
  notes cite the basis and state whether the top comparison is "inside the noise"
  (`uncertainty_note`, a pure function of the ranked costs and the band).

- **Re-ranking cannot re-solve, by construction.** `evaluate` takes no engine —
  it structurally cannot solve. Re-pricing under a revised basis is the same call
  with a different `cost_basis` decision: it re-derives (pure, cheap) to read
  quantities and countables, reuses each candidate's stored `SolveResult` for the
  design checks, and appends an `Evaluation` over the *same* `result_set`. The
  vision's "erected steel up 20% — re-ranking, no re-solving needed" is a test:
  only steel's material cost moves, wood's installed cost is byte-identical, and
  every stored solve result is reused verbatim.

## Consequences

- **Cost is a first-class metric, physics is untouched.** Wood's byte-identical
  mass path proves the addition is purely additive; the existing physics-only
  (null-basis) evaluation still runs during the mass-ranked sweeps.

- **The rate-dimension-as-switch keeps the model honest.** Pricing wood by weight
  or steel by volume is a schema decision the PO makes by choosing a unit, not a
  code change; a misconfigured basis (a volume rate for a family with no volume
  basis) is recorded as a note and omitted, never a fabricated price.

- CI stays deterministic and secret-free (the reference engine solves; no LLM,
  no live prices). All gates green (pyright strict, ruff, full pytest).

- **The seeded regional default is an illustrative placeholder.** The numbers in
  the test basis (`$/lb`, `$/BF`, crew rate, productivities) await PO
  verification, flagged like the dressed-size table — the *mechanism* is what
  ships, not the prices.

- **Deferred:** `cost_basis` as a *project constraint* (the vision's cost-budget
  constraint, its own standing requirement); `cost_basis`-keyed evaluation as a
  first-class object separate from the exploration's evaluation list; glulam and
  other families (so lead time bites — sawn lumber stands in for the 14-week
  glulam flag today); erection method as a richer basis/decision concern than a
  family fact (a craned timber, a bundled joist pick); staged detail-derivation of
  connections/bolts so connection counts come from real connection geometry rather
  than load-path edges; multi-currency.

Supersedes nothing. Establishes cost as a committed, versioned assumption and
priced evaluation as a re-rankable layer strictly above reused physics.
