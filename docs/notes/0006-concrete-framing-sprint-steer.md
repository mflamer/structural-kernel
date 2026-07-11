# Note 0006 — Sprint steer: concrete framing (cash the check ADR 0007 wrote)

**Kind:** Sprint-steer note (product-owner direction, ahead of the increment).
**Raised:** 2026-07-09, PO planning; sprint to run after the vision-demo close.
**Goal:** register concrete as a real material family — and in doing so, prove the
ADR 0007 material boundary was drawn in the right place.
**Concerns:** ADR 0007 (material engine registry; the deliberate concrete
carve-out), `materials/registry.py`, `materials/concrete.py` (the unregistered
proof engine), `MemberCheckData` (neutral vocabulary), the framing decision-kind
family (wood/steel today), `derivation.py` (member emission + countables),
ADR 0012 (cost keys on countables), ADR 0011 (constraints over derived elements).
**Status:** Open — apply before speccing the sprint.

## Why this sprint is different from the other domain items

Steel headers, HSS columns, LTB, interior columns — all pure throughput: the
representation already showed it absorbs new member types and checks without a
kernel change. Concrete is the **one deferred item that can falsify a past
architectural decision** rather than merely extend it. That makes it the most
valuable non-demo sprint: it is a test of the representation, not just more
coverage.

And it is a test ADR 0007 **set up on purpose**. That ADR already:

- proved `MemberCheckData` (the neutral result vocabulary) carries concrete
  results — moment-dimensioned, informational checks skipped, provisions intact —
  in `materials/concrete.py`;
- **deliberately did not register** the concrete engine, stating the reason
  precisely: *a concrete member is geometry (b, h) plus reinforcement, not a
  catalog designation*, so it cannot be described the way the wood/steel catalog
  engines describe a member (designation + grade);
- named the unblock condition: concrete becomes a full engine **when a phase-2
  concrete framing decision kind exists to describe its members.**

So the sprint is not "does the boundary hold?" — ADR 0007 already believes it
does. It is: **build the thing ADR 0007 said was the precondition, and let that
either confirm or expose the boundary.**

## The one representational question

**What describes a concrete member in the decision graph, given it is not a
catalog pick?**

The wood/steel framing kinds record, per member, a catalog designation plus a
grade; derivation emits members the catalog engine then checks. Concrete has no
designation. A concrete member is `(b, h, reinforcement)` — and reinforcement is
itself not a single value but a schedule (bar sizes, counts, layout, cover). This
is the crux, and the sprint must answer it explicitly, not by analogy to catalog
members.

Guidance for the answer (to be settled in the ADR, not presumed here):

- The concrete framing decision kind describes members by **section geometry +
  reinforcement**, not designation. Reinforcement is structured data
  (bars/layout/cover), reusing tagged units (ADR 0002); it is *not* a string.
- **Reinforcement is a design output, not only an input.** This is the sharp
  edge: wood/steel design *selects* a member from a catalog; concrete design
  *proportions* geometry and *then* sizes reinforcement to demand. That means
  concrete may want the **staged derivation** the charter reserved (derive
  section → solve → detail-derive reinforcement from demands) rather than the
  single-pass select-and-check wood/steel use. The sprint should decide whether
  phase-2 concrete sizes reinforcement to demand (staged) or takes reinforcement
  as an authored parameter and *checks* it (single-pass, catalog-like) — the
  latter is the smaller first step and likely the right one to register first.
  **State which, and why**; do not silently assume catalog-shaped.
- Whatever the choice, it flows through the **existing neutral vocabulary**
  (`MemberCheckData`, already proven for concrete) — the check results do not get
  a concrete special-case; only the *member description* is new.

## What the sprint proves about the boundary (the real acceptance)

The material boundary (ADR 0007) is validated **iff** registering concrete
requires:

- a new **framing decision kind** and its **member description** (expected — this
  is the thing ADR 0007 said was missing), and
- **no change to `MemberCheckData`**, the registry protocol, or how checks are
  consumed downstream (the boundary's promise).

If concrete registration forces a change to the neutral result vocabulary or the
registry protocol, **that is a finding, not a nuisance** — it means the boundary
was drawn one notch too far toward catalog materials, and the ADR should say so
rather than bending concrete to fit. Surface it loudly. (I do not expect this —
ADR 0007's proof engine suggests the vocabulary holds — but the sprint's job is to
*confirm* it under a real decision kind, so treat a forced change as a first-class
result.)

## Downstream touchpoints to check (not assume)

- **Countables / cost (ADR 0012).** Concrete's cost drivers are not piece-and-
  connection counts — they are **volume, formwork area, and rebar tonnage.** Per
  note 0003's strict boundary, these are **derived countables**, emitted by
  derivation, never invented by the cost layer. The sprint likely adds concrete
  countables to the bill; the priced-factor model then prices them with **no cost
  schema change** (a factor row per note 0003). Verify that holds; if a concrete
  cost driver needs a countable derivation cannot emit, that is derivation work,
  not cost work.
- **Constraints (ADR 0011).** Spatial constraints predicate over element
  role/family; confirm a concrete column satisfies `no_vertical_support_within`
  and counts as a bay line for min-bay exactly as steel/wood do — role-based
  predication should not care about material. If it does, the predicate is
  keying on the wrong attribute.
- **Heterogeneous exploration.** Once registered, concrete becomes a candidate
  *family* in the exploration alongside wood/steel/glulam — the reason it is worth
  doing after the vision-demo close, which establishes the third-family pattern.
  Concrete then rides that pattern; lead-time/cost behavior should need no new
  mechanism.

## Scope guards

- **Only the member *description* is new.** If anything concrete-specific appears
  in the result vocabulary, the check-consumption path, the registry protocol, or
  the constraint predicates, the boundary has leaked — stop and reconsider.
- **aciconcrete stays behind the engine adapter** (ADR 0007 distribution posture),
  exactly as aiscsteel/ndswood do; no ACI concept crosses into the kernel.
- **Register the smallest real concrete first.** A checked, authored-reinforcement
  beam/column (single-pass) is a complete, registerable increment; reinforcement-
  sized-to-demand (staged derivation) can be the *next* sprint if the sprint
  decides staging is too big to bundle. Do not let "concrete done properly" balloon
  into detailing.

## Acceptance signals

- A **concrete framing decision kind** describes members by section + structured
  reinforcement (tagged units), and derivation emits them.
- The concrete engine **registers** (`materials/registry.py`) and produces
  `MemberCheckData` results **with no change to that vocabulary** — the ADR 0007
  boundary confirmed under a real decision kind.
- Concrete **countables** (volume, formwork area, rebar tonnage) are **derived**,
  and the ADR 0012 cost model prices them with **no cost schema change** (factor
  rows only).
- A concrete column satisfies the spatial-constraint predicates by **role**,
  materially identical to steel/wood.
- Concrete appears as a **candidate family** in a heterogeneous exploration with
  no new exploration mechanism.
- The ADR **states the staging decision** (reinforcement to-demand vs. authored-
  and-checked) and its rationale — the one genuinely new representational choice,
  made explicitly.

## Deliberately out of scope

Reinforcement *detailing* (development length, hooks, bar spacing — the granular
staged-derivation depth the charter reserved), prestressed/post-tensioned
concrete, two-way slabs, and concrete lateral systems. This sprint registers
concrete as a **framing family with checkable members**, cashing ADR 0007's
check; detailing and staged reinforcement design are their own later work.
