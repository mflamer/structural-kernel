# A Building Model That Shows Its Work

*An overview of the structural-kernel project for structural engineers.
Status as of July 8, 2026.*

---

## The problem

Every structural model you have ever opened stores *what* — members, sizes,
geometry. None of them store *why*. The reasoning that actually constitutes the
design — which loads a beam was sized for, why a header exists, what a wall is
protecting, which code provision governed — lives in the engineer's head, in a
calc package that drifts out of date, and in RFI threads. When the model
changes hands (a new EOR, a retrofit engineer twenty years later, or an AI
assistant), the reasoning has to be reconstructed from artifacts that were
never designed to carry it.

That gap is why handing design work to software has always been dangerous:
a tool that doesn't know why a member exists can't tell a safe change from an
unsafe one. It can check geometry. It cannot check *meaning*.

This project is a new kind of structural model, built from scratch, where the
reasoning is the model.

## The core ideas, in engineering terms

**1. The model is the decisions, not the members.**
You don't draw 19 joists; you record the decision — *"2x10 DF-L No.2 joists at
16" o.c., spanning grid A to B, bearing on beams at A and B"* — and the joists,
their tributary widths, the analysis model, and the material takeoff are all
*generated* from it, the way a framing plan follows from a framing rule. Change
the spacing to 19.2" and every downstream artifact regenerates consistently:
member list, analysis, schedule, checks. Nothing is ever manually kept in sync,
so nothing can silently disagree. It is the difference between a stack of
drawings and the reasoning that produced them.

**2. Every member knows why it exists — and the model enforces it.**
When you record a door opening in a bearing wall, the system derives the header
*and* the reason for it: "redirects the gravity load path around opening D1;
carries joists J6, J7, J8." That reason isn't a note. It's enforced. Today, in
the working system, a proposed change that would eliminate the header while the
opening remains is **rejected**, with an error a person (or an AI) can act on:

> *opening D1 interrupts a bearing line, and no header redirects the gravity
> load path around it: joists J6, J7, J8 bear inside the opening*

Ask the model "why does opening D1 have a header?" and it answers from the
recorded load path — not from anyone's memory.

**3. Nothing changes silently, and the record keeps everything.**
Every change — human or AI — is a *proposal* that passes through checks before
it is accepted: units are dimensionally consistent (a psf value can never land
where a length belongs), references resolve, the framing can actually be
generated, and no recorded design intent is violated. Accepted or rejected,
every proposal is kept, permanently, with who made it, when, and why — the way
a drawing revision log works, except it also keeps the rejected attempts. An
engineer of record can show not just the design, but everything that was tried.

**4. As-built reality is first-class.**
Retrofit work runs on surveyed conditions that don't match any clean rule. The
model supports pinning a surveyed value onto a generated member — *"this joist
is actually a 4x10; taped by M. Flamer, 6/30/2026, measured"* — and that
surveyed size flows into the analysis stiffness and the takeoff exactly as if
designed, carrying its provenance the whole way. If the model later moves out
from under the survey point (say a gridline shifts), the pin doesn't silently
follow: it flags itself — *the surveyed member didn't move when the grid did* —
and keeps flagging on every change until an engineer resolves it.

**5. Design-space exploration is a native operation, not 40 file copies.**
Instead of checking the one scheme you had time for, you sweep: joist spacing
12/16/19.2/24" crossed with beam options — every combination becomes a real,
fully checked model variant, all solved in parallel, ranked by material weight
(cost comes later), with hard constraints: every member passing strength *and*
L/360 live / L/240 total deflection. Variants that violate a recorded
constraint are rejected before wasting a solve — and the rejection is kept in
the record. In today's working system, a 12-variant sweep of a 12'x8' bay
correctly picks 24" spacing with a 4x10 beam as the lightest passing scheme,
ranks the 4x4-beam variants as failing (unity > 1.0), and can re-rank from the
stored results without re-running a single analysis.

**6. Code checks that read like a calc package.**
Member checks are NDS 2024 ASD, and every check carries its full factor trail —
CD = 1.00 (ten years), CF = 1.1 (Table 4A), Cr = 1.15 (repetitive member) —
each with its NDS reference, plus the deflection limits per IBC Table 1604.3.
The values come from a verified design library (the same one behind the
Vectorworks calc sheets), not from anything transcribed by hand. A failed check
names the member, the combo, the provision, and the design intent it was
enforcing.

**7. AI-native, engineer-controlled.**
The point of all this structure is that an AI assistant can *safely* work on
the model — because it can only propose, never edit; because every proposal
passes the same checks a human's would; and because the recorded intent gives
it (and rejects for it) the same guardrails a senior engineer would apply.
"The west 40 feet must stay column-free" becomes an enforced constraint, not a
hope. The AI's suggestions get rejected by the same machinery that would reject
anyone's bad idea — with reasons.

## Where this is going: the north-star demo

The project's fixed reference point is a conversation (written out in full in
`docs/vision.md`). The short version:

An engineer starts a new single-story commercial shell — 120' x 80', 25 psf
ground snow — with **no structural system chosen**. They tell the assistant the
west 40 feet must be column-free and that installed cost matters more than
depth. The system holds "structural system" as an explicitly open decision,
records the clear-span requirement as enforced intent, and commits a *cost
basis* — unit costs, crew rates, lead times, as-of date — as a recorded
assumption, never a buried constant.

Then it explores: steel wide-flange, open-web joists, glulam, and a hybrid —
hundreds of candidates, every one a real model variant passing through the same
validation (41 die immediately for putting a column in the protected zone).
Ranked by installed cost — material *plus* connection counts, piece counts,
crane picks — the joist scheme wins. The engineer asks why glulam lost, and the
answer comes from physics and the record: deflection governed, the extra depth
priced out. The fabricator re-quotes steel 20% higher; the system re-ranks in
seconds *without re-solving anything*, because prices changed and physics
didn't — and now glulam is within the noise, so the decision honestly turns on
lead time. The engineer picks the joists, and the model permanently records:
the winning scheme, all candidates searched, both rankings under both cost
bases, the schedule rationale for passing on glulam, and the clear-span
protection that will reject any future column proposal — from anyone — with a
citation back to this conversation.

That is the deliverable this system exists for: **the audit trail as a
first-class engineering product.**

## Status today (July 8, 2026)

**The phase-1 milestone is complete.** Phase 1 built the kernel — the machinery
under everything above — and proved it end-to-end on a small structure: one
bay of wood floor framing (grid, loads, joists/beams/posts rule, one shear-wall
line, one door opening). All seven acceptance criteria, written before the code
and held fixed, now pass:

1. The structure is defined *only* by decisions, committed through the
   validated pipeline.
2. Generation produces the members (with spans and tributary widths), a
   self-contained analysis model, and a bill of materials with piece and
   connection counts — and the opening induces its header with computed,
   machine-readable intent.
3. The analysis engine (xara, the Berkeley-lineage OpenSees runtime) solves
   that model and matches hand calculations within 0.5% on deflections and
   0.1% on reactions — cross-checked by a second, independent solver written
   for exactly that purpose.
4. A surveyed member size pins onto the model and flows through analysis with
   its provenance intact.
5. The header-deletion change is rejected with the structured error quoted
   above.
6. The spacing-by-layout sweep runs as real variants, solved in one parallel
   batch, fully recorded, and exactly reproducible after the fact.
7. The questions answer: *what carries joist J5?* — *why does opening D1 have
   a header?* — *which variant is lightest with every member passing?*

Every one of these re-verifies automatically on every change to the codebase,
including the hand-calc comparisons through the real solver.

**Honest limits of phase 1** (scope, not defects): one framing system (sawn
lumber joists/beams/posts), gravity only — the shear-wall line is recorded but
not analyzed; members are checked as simple spans under tributary loads (no
continuity or frame action); the gravity slice of ASCE 7-22 ASD combinations;
weight, not cost, as the ranking metric; and no drawings or graphical interface
— the model is exercised through code and its records. A handful of embedded
engineering assumptions (header bearing length, grade granularity, the
simple-span idealization) are written up in
`docs/design/0003-phase1-domain-assumptions.md` awaiting the product owner's
confirmation.

**What happens next.** Per the project charter, work is deliberately paused for
a review of the representation itself — is the decision-graph the right shape?
— before phase 2 adds scope: the conversational interface, a real AI proposer
in the exploration loop, broader NDS coverage, lateral analysis, and cost-based
ranking with recorded cost bases.

---

*The project is itself run the way it proposes buildings should be: every
architectural choice is a recorded, reviewed decision (`docs/decisions/`),
proposals live in `docs/design/` until they survive review, and the acceptance
tests were written red, before the code, and earned one increment at a time.*
