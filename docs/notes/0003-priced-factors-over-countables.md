# Note 0003 — Steer the cost increment toward priced factors over countables

**Kind:** Design-steer note (product-owner reframe, ahead of the increment).
**Raised:** 2026-07-08, PO review of the cost design direction.
**Concerns:** the (unbuilt) cost increment; `explorations.py` (`Evaluation`,
`cost_basis`); `derivation.py` (`BillOfElements`, `Countables`, `BillLine`);
vision.md; standing requirements 3–6.
**Status:** Applied 2026-07-09 (ADR 0012 revised to the priced-factor model
before it settled — the note reached Code just after the first, named-field cut
was pushed; the rework superseded it same-day).

## Current state (nothing to walk back)

Cost is **not implemented**. What exists is only the *seam*: `Evaluation` is keyed
by `(result_set, cost_basis)`, `cost_basis` is a nullable `Did` that is always
null today, and evaluation ranks on mass. The re-rank-without-re-solve pathway is
wired; no pricing model, cost-basis schema, or line items are committed. The whole
cost design is ahead of us — which is why this steer lands *now*, before the
increment reasons backward from the demo.

## The risk (same shape as the spatial-constraint over-fit)

The vision dialogue names very specific things: "$/lb erected steel," "crew
rates," "crane picks," "14-week lead time," "installed cost, not material." An
increment that reasons backward from those produces a bespoke schema with named
fields (`erected_steel_usd_per_lb`, `lumber_usd_per_bf`, …). Then the next cost
driver — formwork, shoring, union vs. non-union labor, a carbon price, a
regional multiplier — needs a **schema change**. Same calcification as a bespoke
clear-span constraint, in a different corner.

The generalizing question is identical in shape: *what is the general class of
which "erected steel $/lb" is one instance?*

## The primitive

A **cost basis is a table of priced factors over countable quantities the
derivation emits** — not a record of named price fields.

- A **factor** is `(quantity_kind, unit_price, source)`:
  - `quantity_kind` — a countable the bill already emits or will: member weight,
    board-feet, `piece_count`, `connection_count`, `crane_picks`, and later
    lead-time-days, formwork-area, rebar-tonnage, CO₂e, … Each keys to a real
    emitted quantity.
  - `unit_price` — a tagged quantity (canonical units, ADR 0002), e.g. USD/lb,
    USD/pick, USD/day.
  - `source` — provenance for the number (regional table + date, a quoted
    fabricator, an assumption), so a ranking can cite what it was priced under.
- A **cost basis** (`cost_basis` decision) carries a **list of factors**, not
  named columns. Adding a cost driver is appending a factor row — **no kernel
  change.** This is the registry-not-enum test again (ADR 0004, ADR 0007): a cost
  model nobody anticipated drops in as data.
- **Material vs. installed cost is not two schemas** — it is *which countables the
  active factors key against.* Material-only = weight/volume factors; installed =
  those plus `connection_count`, `piece_count`, `crane_picks`, labor. Same
  primitive, different factor set.
- **Lead time and carbon are just factors** over their own countables
  (days, CO₂e) — priced into the ranking, or surfaced as an annotation/secondary
  objective, without a bespoke mechanism. (Vision already treats lead time as an
  annotation, not a dollar; a factor whose contribution is flagged-not-summed
  covers that.)

## The one boundary that must stay strict

**Derivation emits quantities; the cost basis prices them. Pricing never invents
quantities.**

- Derivation owns *physics and geometry* — board-feet, weights, `piece_count`,
  `connection_count`, `crane_picks`. These are already in `Countables` /
  `BillLine` (`derivation.py`), with `crane_picks` reserved — the substrate
  exists.
- The cost basis owns *prices applied to those quantities* — and nothing else.
- If pricing ever estimates a quantity (guesses a connection count, infers
  board-feet), the two layers have bled together and reproducibility suffers.
  Keeping "quantities are derived, prices are a decision applied to them" strict
  is precisely what makes the re-rank-without-re-solve promise (standing req 5)
  actually hold: re-ranking changes *factors*, never *quantities*, so stored
  physics is reused untouched.
- Corollary: if a factor needs a countable derivation does not yet emit (e.g.
  formwork area), the work is **adding that countable to derivation**, not letting
  cost compute it. New cost driver ⇒ maybe a new derived countable + a factor
  row; never a quantity synthesized in the pricing layer.

## Honest cost (standing req 6, keep it)

Rankings carry their basis and an **uncertainty statement**; the evaluator must be
able to report a close ranking as within the noise. A cost estimate is an
estimate — false precision would undercut the audit-trail credibility everything
else earns. "A beats B by 4%" and "by 40%" are different claims; the system must
know the difference. This is a property of the *evaluation*, independent of the
factor model, and survives this reframe unchanged.

## Suggested increment scope (when cost is picked up)

Deliver the **priced-factor cost model**: the `cost_basis` decision as a factor
table, the evaluation summing active factors over the bill's countables keyed by
`(result_set, cost_basis)`, and the uncertainty statement — **proven by pricing
the existing wood-vs-steel exploration on material-only and installed bases and
re-ranking between them without re-solving.**

**Acceptance signals:**
- Material-only and installed bases are the *same schema*, differing only in
  which factors are present.
- Re-ranking the stored exploration under a revised basis (the vision's "steel up
  20%" beat) changes the ranking and **runs no solve** — verified by asserting
  the solver is not called.
- A factor kind nobody planned for (a **carbon price over a CO₂e countable**,
  as a test fixture) prices and ranks with **no kernel change** — the
  generalization proof.
- A basis that references a countable derivation does not emit fails cleanly with
  a message pointing at the missing countable — never by inventing the quantity.

## Answers to the framing the increment will likely raise

- "How do we store $/lb for steel and $/bf for wood?" → not as fields; as two
  factor rows in the basis table, each `(quantity_kind, unit_price, source)`.
- "Material or installed cost?" → one schema; installed adds labor/count factors.
- "Where do crane picks / connection counts come from?" → derivation
  (`Countables`, already emitted/reserved), never the cost layer.
- "How is lead time priced?" → a factor over a lead-time countable, summed or
  flagged; not a special case.

## Applied resolution (2026-07-09, PO-confirmed)

The one fork the rework raised — where crew rate and productivity live in a flat
factor table — the PO resolved: **keep crew rate + productivity as explicit basis
data.** Labor is a factor variant carrying `(crew_rate, productivity)`;
productivity is a means-and-methods assumption on the *basis*, never in
derivation, so re-ranking under a revised rate still touches no stored physics.
See ADR 0012 (revised).
