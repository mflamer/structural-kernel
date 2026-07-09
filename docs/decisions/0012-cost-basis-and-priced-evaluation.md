# 0012 — Cost basis as a versioned decision; priced evaluation as a table of factors over derived countables

**Status:** Accepted (2026-07-08, product owner directed), **revised 2026-07-09
per PO note 0003** — the first cut modelled the basis as named price fields
(`connection_cost`, `crew_rate`, per-family `material_rates`); note 0003 landed
just after it was pushed and reframed the basis as a *table of priced factors over
countables*, which this ADR now records. Implements the vision's item 2 ("cost as
the ranking variable, honestly modeled") and standing requirements: cost
assumptions are decisions; derivation emits countables; evaluation is a distinct
layer from solving (re-ranking must not re-solve); rankings carry their basis and
an uncertainty statement. Builds on ADR 0002 (tagged quantities), ADR 0004/0007
(registry-not-enum), and the exploration/evaluation split from design doc 0001 §8.

## Context

The evaluation layer was already shaped for this: `Evaluation` is keyed by
`(result_set, cost_basis)`, `evaluate` reads *stored* solve results and never
solves. What was missing was the cost model — and note 0003 fixed its shape before
it could calcify. The vision names specific things ("$/lb erected steel", "crew
rates", "crane picks", "14-week lead time"); a schema of named fields for each
would need a schema change for the next driver (formwork, a carbon price, a
regional multiplier) — the IFC failure mode again. The general class of which
"erected steel $/lb" is one instance is **a priced factor over a countable the
derivation emits**. So the basis is a *list of factors*, not named columns — the
same registry move ADR 0004 made for intent categories and ADR 0007 for material
engines.

The charter's hard rules still bind: no bare float crosses the cost interface, and
no price is hardcoded or lives inside a derivation rule. And note 0003's one
boundary: **derivation emits quantities; the basis prices them; pricing never
invents a quantity** — which is exactly what makes re-rank-without-re-solve hold.

## Decision

- **Money is unit-tagged like everything else** (`units.py`). New dimensions:
  `MONEY` (`USD`), `VOLUME` (`m3`/`ft3`/`in3`/`BF`/`MBF` — a board-foot is 144
  nominal cubic inches), and the rate dimensions `MONEY_PER_MASS` (`USD/kg`,
  `USD/lb`), `MONEY_PER_VOLUME` (`USD/m3`, `USD/BF`, `USD/MBF`), `MONEY_PER_TIME`
  (`USD/s`, `USD/hr`), plus `hr`/`week` for TIME. Single currency (USD) in phase
  2, NIST-anchored and tested, the same posture as `LINE_LOAD` / `MOMENT`.

- **Quantity kinds are an open registry** (`costing.py`), the ADR 0004/0007 move
  applied to cost. `register_quantity_kind(QuantityKind(name, dimension, resolve))`
  is the whole extension surface; a resolver reads a derived model + optional
  `(family, role)` scope and returns the aggregate's canonical-SI magnitude.
  Built-ins read what derivation already emits: `member_weight` (MASS),
  `board_feet` (VOLUME, lumber's nominal board-foot volume), `piece_count`,
  `connection_count`, `crane_picks` (dimensionless counts). A kind's `dimension`
  is what a factor's price unit is validated against.

- **`cost_basis` is a decision whose params are a factor table**
  (`objects.py`, `decisions.py`). `CostBasisParams` = `region`, `as_of`,
  `factors: list[CostFactor]`, `uncertainty_pct`. A `CostFactor` is
  `(quantity_kind, scope?, pricing, source)`, where `pricing` is a discriminated
  union: `DirectPrice(unit_price)` (summed; the rate's dimension must match the
  kind — MASS→`USD/kg`, VOLUME→`USD/m3`, count→`USD`), `LaborPrice(crew_rate,
  productivity)` (summed; `count × productivity × crew_rate` — **crew rate and
  productivity stay explicit basis data, Mark's call**; productivity is a
  means-and-methods assumption on the *basis*, never in derivation), and
  `FlagAnnotation(note_value)` (never summed — the vision's lead-time flag).
  "$/lb steel" and "$/bf wood" are two factor rows, not two fields. The kind is
  derived-data, not geometry, so `cost_basis` derives nothing — the only wiring is
  `parse_params` + `line_refs` (empty; it is global). A revised basis is a *new*
  `cost_basis` decision, so every ranking cites what it was priced under.

- **The clean-failure boundary is enforced at validation.** A factor naming a
  `quantity_kind` no resolver provides is a rejected changeset naming the missing
  countable — never invented. A `DirectPrice` whose unit dimension disagrees with
  the kind, or `LaborPrice` over a non-count kind, is likewise rejected at schema
  time.

- **Derivation emits the countables** (`derivation.py`). `crane_picks` is now
  populated (`sum(engine.crane_picks_per_member())` over catalog members) beside
  the piece and connection counts. Two family facts land on the ADR 0007 material
  engines: `crane_picks_per_member()` (steel 1, wood 0) and `nominal_volume_m3()`
  (lumber board-foot volume; steel, priced by weight, returns `None`). Counts are
  geometry; productivities and prices are the *basis's*.

- **Priced evaluation sums factors over stored results** (`explorations.py`).
  `evaluate(store, exploration, cost_basis)` prices each candidate by summing its
  basis's factors over the (re-derived, pure) model: `material_cost_usd` (factors
  whose kind is MASS/VOLUME) + `installation_cost_usd` (counts + labor) =
  `installed_cost_usd`, the ranking metric. `flag` factors become per-candidate
  annotations; the notes cite the basis and state whether the top comparison is
  "inside the noise" (`uncertainty_note`, a pure function of the ranked costs and
  the band). Material-only vs installed is one schema differing only in which
  factors are present.

- **Re-ranking cannot re-solve, by construction.** `evaluate` takes no engine.
  Re-pricing under a revised basis re-derives (pure, cheap) to read countables,
  reuses each candidate's stored `SolveResult`, and appends an `Evaluation` over
  the *same* `result_set`. Because a factor only *prices* a derived quantity, a
  re-quote changes factors, never physics.

## Consequences

- **The generalization is a real test.** A carbon price over a `co2e` quantity
  kind — registered only as a test fixture — prices and re-ranks the stored
  exploration with **zero kernel change** (mirrors ADR 0011's `clear_height_below`
  proof); a factor over an unregistered kind fails cleanly; material-only and
  installed bases re-rank over the same physics with no solve; the vision's steel
  +20% re-quote moves only steel's material cost.

- **Cost is a first-class metric, physics untouched.** Wood's byte-identical mass
  path proves the addition is purely additive; the null-basis (mass-only)
  evaluation still runs the mass-ranked sweeps.

- CI stays deterministic and secret-free (reference engine solves; no LLM, no live
  prices). All gates green (pyright strict, ruff, full pytest).

- **The seeded regional basis is an illustrative placeholder.** The factor numbers
  (`$/lb`, `$/BF`, crew rate, productivities, uncertainty %) await PO verification,
  flagged like the dressed-size table — the *primitive* ships, not the prices.

- **Deferred:** a real derived `co2e` countable (material carbon intensity as an
  engine fact) so carbon is production, not a fixture; lead time as a genuine
  derived countable rather than a family-presence flag (lead time is regional
  market data, so it currently rides as a `FlagAnnotation` over the family's
  presence); `cost_basis` as a cost-*budget* project constraint; glulam and other
  families; erection method richer than a family fact; detail-derived connection
  geometry; multi-currency.

Supersedes nothing. Establishes cost as a committed, versioned assumption modelled
as a table of priced factors over derived countables, and priced evaluation as a
re-rankable layer strictly above reused physics.
