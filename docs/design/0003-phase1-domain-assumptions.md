# 0003 — Phase-1 Domain Assumptions Awaiting PO Confirmation

**Status:** Awaiting product-owner review. None of these block implementation;
each is cheap to change while phase 1 is young and gets expensive once the
verification suite and exploration evaluations consume it. Confirm or correct
item by item — a one-line reply per item suffices ("1 ok, 2 ok, 3: bearing
should be X, 4 ok").

## 1. Sawn-lumber reference tables (`src/structural_kernel/sections.py`)

Dressed sizes assumed per NDS Supplement (2x: 1.5" breadth; 4x: 3.5"; 6x6:
5.5×5.5; depths 3.5 / 5.5 / 7.25 / 9.25 / 11.25). Reference modulus of
elasticity for **DF-L No.2 taken as E = 1.6×10⁶ psi**. These are code-side
lookup tables (same posture as unit-conversion constants); the *choice* of
section and grade stays in the decision graph.

- Confirm the E value and the dressed-size table.
- Say which additional grades phase 1 should carry (the table is one entry
  today), and whether Emin will be wanted alongside E when NDS checks arrive.

## 2. `member_grade` as a framing-strategy parameter

One grade per gravity framing strategy, applying to joists, beams, and posts
alike (`GravityFramingStrategyParams.member_grade`). Is one grade per strategy
the right granularity for phase 1, or do you want grade per member class
(joist/beam/post) from the start?

## 3. The header rule (opening derivation)

- Header span = opening rough width + **3 in bearing each side**, treated as
  center-to-center of bearing.
- Header **section = the framing strategy's `beam_section`** (placeholder rule
  until NDS sizing checks exist).
- Header tributary width = half the joist span it picks up; header elevation
  taken at the opening head height.
- Joists whose layout position falls within the opening extent (inclusive of
  edges) reroute: they bear on the header, the header bears on the wall-line
  beam.

Confirm, or state the rule you'd rather see (e.g. trimmer/king-stud modeling
depth, bearing length, a distinct `header_section` parameter).

## 4. Phase-1 analysis idealization and combo subset

- Flexural members (joists, beams, headers) enter the analysis artifact as
  **independent simply-supported spans** under tributary line loads — the
  decomposition that matches the hand-calc verification fixtures. No frame
  action, no continuity.
- Posts are in the derived model and bill, but their axial demands come from
  tributary areas, not a solve.
- ASD combos generated (gravity slice of ASCE 7-22 §2.4, limited to load
  cases the snapshot defines): `D`, `D+L`, `D+S`, `D+0.75L+0.75S`.

Confirm this idealization is acceptable for the phase-1 milestone and that
the combo subset is the right gravity slice (notably: is D+0.75L+0.75S wanted
in phase 1, and should Lr be treated like S?).
