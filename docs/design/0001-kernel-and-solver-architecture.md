# 0001 — Kernel and Solver Architecture

**Status:** Draft, awaiting product-owner review. No implementation until reviewed.
**Scope:** The decision-graph data model, derivation contract, changeset/validation
lifecycle, override semantics, the structural intent type system, the analysis-model
artifact format, the solver service interface, the exploration object lifecycle, the
solver recommendation, and open questions.

This document proposes; the charter (`docs/kickoff.md`) governs. Where this doc makes a
choice the charter left open, the choice is flagged and justified, and an ADR will be cut
when it survives review.

---

## 1. The shape of the system

Four layers, each speaking only to its neighbors through typed, versioned schemas:

```
┌─────────────────────────────────────────────────────────────┐
│  AI surface (API → MCP later): query / explain / propose /  │
│  explore. Speaks changesets and queries, never raw state.   │
├─────────────────────────────────────────────────────────────┤
│  Kernel: decision graph + intent + overrides, versioned in  │
│  a content-addressed store. Validates and commits           │
│  changesets. Owns explorations.                             │
├─────────────────────────────────────────────────────────────┤
│  Derivation: pure functions decision-snapshot → derived     │
│  model (members, connections, intents, analysis artifacts,  │
│  bills of elements). Deterministic, cacheable by hash.      │
├─────────────────────────────────────────────────────────────┤
│  Solver service: stateless, batch-oriented, cloud-shaped.   │
│  Accepts self-contained analysis artifacts, fans out,       │
│  returns structured results keyed by artifact hash.         │
└─────────────────────────────────────────────────────────────┘
```

The persisted schema is the source of truth. Everything in storage is
language-neutral, versioned JSON in the content-addressed store; the Python kernel is one
replaceable implementation of that schema.

## 2. Decision-graph data model

### 2.1 Two kinds of identity

The single most consequential modeling choice. Everything in the store has both:

- **A stable identity** (`did` for decisions, `eid` for derived elements): what a thing
  *is* across time, the anchor for diffs, blame, overrides, and intent references.
  Decision IDs are opaque ULIDs assigned at creation. Derived-element IDs are
  **deterministically computed** from the derivation path (§3.3), so "joist J5" survives
  re-derivation and means the same thing on every branch that shares its provenance.
- **A content address** (`hash`): what a thing *says* right now. SHA-256 over the
  canonical JSON encoding (sorted keys, no insignificant whitespace, UTF-8). Two
  identical decision payloads share a hash; storage deduplicates for free.

Git terms map directly: `did` ≈ file path, `hash` ≈ blob hash, snapshot ≈ tree,
commit ≈ commit, branch ≈ ref.

### 2.2 Objects in the store

All persisted objects carry `schema_version` (integer, per object type) and are
immutable once written. Object kinds:

| Kind | Contents |
|---|---|
| `decision` | One versioned decision payload (§2.3). |
| `snapshot` | Sorted map `did → decision hash`, plus the override set hash. The complete canonical model at an instant. |
| `commit` | Snapshot hash, parent commit hash(es), author (human/AI/proposer ref), timestamp, message, and the changeset hash that produced it. |
| `changeset` | A proposed diff: base commit hash + list of decision add/modify/remove operations + override operations (§5). Persisted even when rejected — the record of what was attempted is part of the audit trail. |
| `override-set` | The reality override layer for a snapshot (§5). |
| `artifact` | Derived outputs: analysis models, bills of elements, solve results. Stored by hash, keyed from a derivation index, always reproducible — deletable cache, never source. |
| `exploration` | The first-class exploration object (§8). |

Branches are named refs (`refs/main`, `refs/option-b-moment-frame`) pointing at commits,
stored outside the content-addressed space, updated transactionally.

### 2.3 Decisions

A decision is the unit of design meaning: small, declarative, inspectable.

```jsonc
{
  "schema_version": 1,
  "did": "01JXF...",                 // stable ULID
  "kind": "gravity_framing_strategy", // discriminator
  "title": "Level 2 floor framing",   // short human/AI label
  "params": { /* kind-specific, schema-validated */ },
  "deps": ["01JXA...", "01JXB..."],   // dids this decision reads
  "intent": [ /* structural intent records, §4 */ ]
}
```

`kind` is a **closed discriminated union in phase 1** (unlike intent categories, which
are open — §4). Adding a decision kind means adding derivation logic anyway, so an open
registry buys nothing yet; revisit if third-party derivation plugins ever exist. Phase 1
kinds:

- `grid` — named axes with spacings; the coordinate backbone.
- `levels` — story elevations.
- `load_assumptions` — dead/live/snow/etc. by area or line, plus load combination set
  selection (which code slice — open question §10).
- `gravity_framing_strategy` — a *rule*, not a member list: region (grid extent), system
  (e.g. joists bearing on beams bearing on posts), spacing, direction, bearing rules,
  member family/material.
- `lateral_strategy` — one lateral system decision for phase 1 (e.g. designated
  shear-wall lines) — enough to prove the intent category, not full lateral design.
- `opening` — dimensions and location in a named wall/region. No reason modeled
  (charter). Derivation of the enclosing framing induces the header.
- `exception` — a targeted rule override of another decision's output at a specific
  location, when the reason is *design* ("use a doubled joist under the tub"). Distinct
  from reality overrides (§5), which record *measurement*, not preference.

`deps` are the edges of the decision DAG. They are declared, validated (§6: no dangling
refs, no cycles), and are what makes decision-level diffs meaningful — but derivation
does not trust them for correctness; it computes over the whole snapshot and *checks*
that reads match declared deps (a derivation that reads an undeclared dep is a kernel
bug caught in tests).

### 2.4 Units

**Canonical unit system: SI base — newtons, meters, seconds, kilograms; derived Pa,
N·m.** Every number that crosses any interface travels as a tagged quantity:

```jsonc
{ "mag": 4448.22, "unit": "N" }
```

Rationale:

- SI is unambiguous. US customary force/mass (lbf vs lbm) and the kip-in vs kip-ft split
  inside a single calc are classic silent-error factories; the kernel should not host
  them.
- The solver, derivation math, and stored artifacts all use canonical SI floats
  internally — one conversion in at the authoring boundary, one out at the display
  boundary, and *nowhere else*.
- Authoring and display are US customary (the product owner practices in ft-in, kips,
  psf, ksi). The unit layer accepts `"16 in"`, `"40 psf"`, `"50 ksi"` at the API
  boundary and renders results back in the same register. Unit preferences are a
  presentation concern, never stored in the model.
- The `unit` tag on persisted values is not decoration: schema validation checks
  dimensional correctness (a `load_assumptions` area load must be Pa-dimensioned), so a
  bare or mis-dimensioned float is a *rejected changeset*, not a latent bug.

The tag is restricted to a curated whitelist of unit spellings (no free-form unit
expression parser in the kernel). Conversion tables are code, tested against known
constants (1 kip = 4448.2216152605 N, exactly, per NIST).

## 3. Derivation

### 3.1 Contract

```
derive : (snapshot, derivation_version) → DerivedModel     [pure]
```

- **Deterministic**: same snapshot hash + same derivation version ⇒ byte-identical
  output. No clock, no randomness, no I/O, no environment reads. This is enforceable and
  property-tested (derive twice, compare hashes).
- **Total over valid snapshots**: any snapshot that passed commit-time validation must
  derive without raising. Conditions the derivation cannot honor (a framing region with
  no support line) are *validation* failures at changeset time, not derivation crashes —
  the validator runs a derivation dry-run precisely so nothing invalid ever commits (§6).
- **Versioned**: `derivation_version` is a monotonically increasing integer over the
  derivation ruleset. Artifacts record it. Changing derivation logic never mutates old
  artifacts; it produces new ones alongside, which is what makes "re-derive the whole
  history under the new rules and diff" a supported operation rather than an archaeology
  project.
- **Cacheable**: the derivation index maps `(snapshot_hash, derivation_version) →
  artifact hashes`. A cache hit is a lookup; the store never recomputes silently
  different answers.

### 3.2 Outputs (`DerivedModel`)

- **Element instances** — members (joists, beams, posts, headers), each with: `eid`,
  geometry (span line, section orientation), resolved section + material, tributary
  width, support references (which `eid`s carry it), and **attached intent instances**
  (§4) — the derived record of *why this element exists*, e.g. the header's
  gravity-load-path-redirect intent induced by the opening decision.
- **The load-path graph** — directed edges `eid → eid` ("J5 bears on B2 bears on P1"),
  the substrate for "what carries joist J5?" and for intent-violation detection.
- **Analysis model artifacts** — §7.1. One or more per snapshot (phase 1: one).
- **Bill of elements** — flat, sorted, unit-tagged; the schedule precursor.

### 3.3 Deterministic element identity

`eid = f(inducing decision did, rule instance, ordinal within rule)` — e.g. the 5th
joist generated by framing strategy `01JXF...` in bay B is the same `eid` on every
branch until a decision that feeds it changes in a way that renumbers the rule's output.
Renumbering hazards (inserting a joist shifts ordinals) are contained by keying ordinals
to *stable geometric anchors* (grid-line offsets) rather than array position, so local
edits perturb local `eid`s only. Overrides and intents reference `eid`s; this scheme is
what keeps a surveyed override pinned to *that joist* across re-derivations. The exact
anchor scheme per rule type gets its own ADR during implementation — it is fiddly and
load-bearing.

## 4. Structural intent

### 4.1 Shape (kernel-fixed) vs categories (open)

The charter requires new structural categories — vibration, fatigue, fire-structural —
to land *without kernel changes*. So the kernel fixes the **shape** of intent and stays
agnostic about **categories**:

```jsonc
{
  "schema_version": 1,
  "category": "gravity_load_path",      // registry key, not an enum
  "payload": { /* category-schema-validated */ },
  "relations": [
    { "role": "redirects_load_around", "target": { "eid": "..." } },
    { "role": "governed_by", "target": { "provision": "IBC 2021 §2308.4.1" } },
    { "role": "carries", "target": { "load": "01JLD..." } }
  ],
  "provenance": { "source": "derived", "inducer": "01JOP..." }  // or "authored"
}
```

The kernel validates: the envelope schema, that `category` is registered, that the
payload validates against the registered category schema, and that every relation target
resolves (referential integrity). What it does **not** know is what any category
*means*.

### 4.2 Category registry

A category registration = `(name, payload schema, relation roles, checker)`. The
checker is the semantic half: a function `(derived model, intent instance, proposed
snapshot) → violations` that answers "does this model still honor this intent?" —
e.g. the `gravity_load_path` checker walks the load-path graph and reports a broken
path if the header is gone while the opening remains. Registrations live in versioned
registry modules; phase 1 ships `gravity_load_path`, `lateral_capacity`,
`serviceability`, `retrofit_rationale`. Adding `vibration` later is a new registry
module + schema + checker — no kernel edit, which is the charter's test.

Intent is attached at two sites: on decisions (authored intent, captured
conversationally by the AI surface) and on derived elements (derived intent, emitted by
derivation rules — the header's reason-for-being is *computed*, not typed in).

## 5. Reality override layer

Overrides record **measurement, not preference** (design preferences are `exception`
decisions — §2.3). An override pins a specific field of a specific derived element:

```jsonc
{
  "schema_version": 1,
  "target": { "eid": "...", "field": "section" },
  "value": { "family": "sawn_lumber", "designation": "4x10" },
  "provenance": {
    "observed_by": "M. Flamer",
    "method": "site_survey_tape",
    "observed_at": "2026-06-30",
    "confidence": "measured"        // measured | estimated | assumed
  }
}
```

**Composition rule — the part that must be boringly predictable:** derivation runs
entirely on decisions, *then* the override set is applied as a final substitution pass,
*then* downstream artifacts (analysis model, BOM, load-path graph re-check) are computed
from the overridden model. So an overridden section flows into member stiffness and
design checks exactly as if derived, and every overridden value carries its provenance
into every artifact that consumed it. Overrides never edit decisions and derivation
never reads overrides — the two compose by ordering, not by entanglement.

An override whose `target.eid` no longer exists after a re-derivation is a **dangling
override** — surfaced as a validation warning on commit, never silently dropped. The
model with unresolved dangling overrides still derives (the override is inert), but the
warning persists until a human resolves it: reality that no longer attaches to the model
is exactly the situation a retrofit engineer needs shoved in their face.

## 6. Changeset and validation lifecycle

The AI (or any client) never touches state. The only write path:

```
propose(changeset) → validate → commit | reject(structured errors)
```

Validation stages, in order, fail-fast per stage but collecting all errors within one:

1. **Schema** — every object validates against its versioned schema, units
   dimensionally correct.
2. **Referential** — `deps` resolve, no cycles, relation targets exist, override
   targets checked (dangling ⇒ warning, not rejection).
3. **Derivation dry-run** — apply the changeset to the base snapshot in memory, derive.
   A derivation failure here is a rejection with the failing rule and inputs named.
4. **Intent checks** — run every registered checker over the dry-run derived model.
   Violations name the intent instance, the violated relation, and the broken load-path
   edge(s): the charter's "delete the header while the opening remains" case dies here
   with a machine-actionable error, e.g.:

```jsonc
{
  "code": "intent_violation",
  "intent": { "eid": "hdr-...", "category": "gravity_load_path" },
  "violated": "redirects_load_around",
  "detail": { "broken_path": ["jst-...", "hdr-⊘", "pst-..."], "opening": "01JOP..." },
  "message": "Removing header hdr-… leaves opening D1 with no gravity load path from J3/J4 to P2."
}
```

Commit is atomic: new objects written, ref advanced, or nothing. Concurrent proposals
against the same ref use compare-and-swap on the ref (first commit wins, second gets a
`stale_base` rejection and rebases — mechanical for non-overlapping decision sets).
Branching is a ref copy; merging is three-way at decision granularity (same `did`
modified on both sides ⇒ conflict surfaced to the caller; no silent merges of decision
payloads).

Rejected changesets persist (§2.2) with their structured errors — the exploration audit
trail and the AI's own learning loop both want "what was tried and why it failed."

## 7. Analysis artifacts and the solver service

### 7.1 The analysis-model artifact

Self-contained, solvable by a worker with no store access:

```jsonc
{
  "schema_version": 1,
  "provenance": { "snapshot": "sha256:...", "derivation_version": 3, "branch_hint": "opt-b" },
  "nodes":    [ { "id": "n1", "xyz_m": [0.0, 0.0, 0.0] }, ... ],
  "elements": [ { "id": "e1", "type": "frame", "nodes": ["n1","n2"],
                  "E_pa": 1.1e10, "A_m2": ..., "I_m4": {...}, "releases": {...},
                  "source_eid": "jst-..." }, ... ],
  "supports": [ { "node": "n1", "fix": [true,true,true,false,false,false] }, ... ],
  "loads":    [ { "case": "D", "kind": "line", "element": "e1", "w_n_per_m": [...] }, ... ],
  "combos":   [ { "name": "1.2D+1.6L", "factors": { "D": 1.2, "L": 1.6 } }, ... ]
}
```

All values canonical SI, all IDs local to the artifact, `source_eid` mapping analysis
elements back to model elements so results re-attach to the derived model (and design
checks can cite members, not matrix rows). The artifact is the *entire* solver contract:
if it ever needs to reach back to the store, the design has failed.

### 7.2 Solver service interface

Cloud-shaped from day one, local behind the same interface in phase 1:

```
submit(batch: [artifact_hash | inline artifact], options) → job_id
status(job_id) → { pending, running, done, failed:  per-artifact }
results(job_id) → [ SolveResult ]           # keyed by artifact hash
```

- **Stateless workers**: a worker receives one artifact, returns one result, holds
  nothing. Phase 1 implementation: a local `ProcessPoolExecutor` behind the interface;
  the cloud implementation is a queue + container fleet with the identical schema.
  Dispatching 500 is the same call as dispatching 1.
- **`SolveResult`** (per artifact, per combo): nodal displacements, reactions, member
  end forces + interpolated extrema, solver diagnostics (condition warnings, iteration
  counts later), wall time — or a **structured failure**: `mechanism_detected`
  (with the free DOF set), `singular_system`, `invalid_artifact`, `worker_crash`. A
  failed solve is data, not an exception; explorations must rank around failures.
- **Determinism note**: linear-elastic solves are reproducible to floating-point
  tolerance, not bit-exactness, across BLAS builds. Result artifacts therefore record
  solver build fingerprints, and verification tests use tolerances (§9), never hash
  equality on results.

### 7.3 Solver posture and first engine

*(Re-cut 2026-07-07 after product-owner review — supersedes the first draft's
"purpose-built solver for phase 1" recommendation. What changed: (1) the first draft
misread the OpenSees license — its clause (b) permits commercial entities internal
use, reserving only incorporation into distributed products; (2) xara exists — a
BSD-licensed Berkeley refactoring of the OpenSees engine — which removes the licensing
question from the critical path entirely.)*

**Position: the kernel is solver-agnostic by design. The value of this system is the
decision graph and what surrounds the solve — derivation, intent, design checks,
explorations — not the solver, which is commodity physics behind §7.2's interface.
Engine choice is therefore an adapter decision, not an architecture decision.
First engine: xara, from phase 1, pending one licensing confirmation.**

Solver-agnosticism is won or lost in the schemas, not at the API layer:

- **The artifact (§7.1) and `SolveResult` schemas are the real contract.** They speak
  *our* vocabulary — releases, sections, loads, combos, end forces — and never bend
  toward an engine's idioms. Adapters translate in both directions; an engine-ism
  leaking into the schema is solver lock-in wearing an API costume.
- **The failure taxonomy is ours.** Adapters map engine noise (return codes, stderr,
  non-convergence chatter) into the structured failures of §7.2. Callers and
  explorations never see engine-specific errors.
- **Design checks live kernel-side.** Unity, deflection limits, provision citations —
  these consume solve results but are not engine output. They are part of the moat, not
  part of the solver.
- **Replaceable ≠ plural.** Every adapter carries the full hand-calc verification
  suite (§9), so the policy is one blessed engine at a time. Agnosticism is an exit
  option we keep cheap, not a backend matrix we maintain.

Engine survey against the charter's criteria (headless/container-friendly, permissive
commercial licensing, frame/wall robustness, path to nonlinear/dynamic):

| Candidate | Headless | License for commercial use | Frame/wall fit | Nonlinear path | Verdict |
|---|---|---|---|---|---|
| **xara** (STAIRLab/Berkeley refactoring of OpenSees, a.k.a. OpenSeesRT) | Excellent — pip-installable, drop-in OpenSeesPy replacement, faster | **BSD-2-Clause** in-repo, no UC use restriction; published by the copyright-holding institution's own lab under PEER's open-source org. One open item: confirm with the maintainer that the whole-tree relicensing (not just new contributions) is intended and authorized | Excellent — the OpenSees engine, built for building frames | Excellent (best-in-class EQ/nonlinear, arrives with no phase-2 cliff) | **First engine, phase 1** |
| **OpenSees upstream** | Excellent (OpenSeesPy) | Clause (a): edu/research/non-profit, noncommercial. Clause (b): other entities, *internal purposes only* — a server-side SaaS reading is plausible but unlitigated; UC OTL license required to ship it inside distributed products | Excellent | Excellent | Superseded by xara (same engine, cleaner license) |
| **CalculiX** | Good | GPL-2 — server-side in-house use is fine, but copyleft constrains future packaging/embedding | Weak for buildings: continuum-first; beam elements internally expanded to solids with known quirks | Good (general FEA) | Wrong element technology for frames |
| **code_aster** | Poor-to-fair (notorious to build/drive; containers exist) | GPL-2 | Strong FEA, not building-frame-idiomatic; French-first docs | Excellent | Ops burden out of proportion |
| **Purpose-built linear** | Trivial | Ours | Exact fit for phase-1 scope | None — by design | **Demoted to test fixture**: a minimal direct-stiffness cross-check inside the verification suite (an independent second opinion on the hand-calc fixtures), *not* a service implementation and not on the critical path |

The phase-1 solver work is therefore the **xara adapter**: artifact → xara model,
xara results → `SolveResult`, engine errors → the failure taxonomy, all exercised by
the hand-calc verification suite. That suite validates the adapter and the schema
mapping — the two places bugs can actually live — rather than a solver of our own.

## 8. Explorations

The propose → derive → solve → evaluate loop as a persistent kernel object:

```jsonc
{
  "schema_version": 1,
  "exploration_id": "01JEX...",
  "base_commit": "sha256:...",
  "objectives":  [ { "metric": "total_steel_mass", "direction": "min" } ],
  "constraints": [ { "metric": "max_unity", "op": "<=", "value": 1.0 },
                   { "kind": "intent_preserved" } ],
  "proposer": { "strategy": "grid_sweep", "params": { ... }, "version": 1 },
  "budget": { "max_solves": 200, "max_generations": 10 },
  "convergence": { "no_improvement_generations": 3 },
  "status": "running | converged | budget_exhausted | terminated",
  "generations": [ {
      "n": 0,
      "candidates": [ {
          "changeset": "sha256:...",       // may be a *rejected* changeset — recorded
          "branch": "refs/expl/01JEX/g0/c3",
          "rationale": "joist spacing 19.2in × beam layout B: trades ...",
          "artifact": "sha256:...",
          "result":   "sha256:...",
          "evaluation": { "total_steel_mass": {...}, "max_unity": 0.87, "feasible": true }
      } ],
      "ranking": ["c3", "c1", ...]
  } ]
}
```

- **Proposer contract** (the pluggable seam):
  `propose(exploration state, generation history) → [ (changeset, rationale) ]`.
  Phase 1 ships the grid-sweep proposer (spacing × layout cross product) and a **stub
  LLM proposer** that satisfies the same protocol and returns a canned proposal — the
  demonstration that an LLM slots in without kernel changes. Rationale is mandatory on
  every candidate from every proposer (a sweep's rationale is mechanical but present);
  the engineer-of-record audit requirement makes this non-optional.
- **Candidates are real branches** produced through the *ordinary* changeset pipeline —
  same validation, same intent checks. A candidate the validator rejects is recorded
  with its structured error and never solved. No exploration side-door into state.
- **Lifecycle is kernel-owned**: the kernel runs the generation loop — call proposer,
  validate, derive, batch-dispatch all candidates concurrently to the solver service,
  evaluate, rank, persist the generation, check budget/convergence. Callers configure;
  they do not orchestrate. Every generation persists before the next begins, so a
  killed exploration resumes (or replays) from its record.
- **Replayability**: base commit + proposer version + recorded candidates + artifact and
  result hashes ⇒ an exploration can be re-executed and checked against its own record
  (modulo solver float tolerance, §7.2). For the sweep proposer this is exact; for a
  future LLM proposer, the recorded candidates and rationales *are* the replay (the
  charter's audit requirement is on the record, not on re-sampling the model).

## 9. Testing strategy (summary)

- Every kernel invariant in this doc gets a test: derivation determinism
  (property-based: derive twice ⇒ identical), override composition ordering,
  changeset atomicity, CAS on refs, intent-checker rejection cases, dangling-override
  warnings, eid stability under neighboring edits.
- Solver verification: hand-calc fixtures (simply-supported beam under UDL, point loads,
  two-span continuous, simple frame sway) at stated tolerances (proposal: 0.5% on
  displacements, 0.1% on reactions — review), plus at least one published benchmark
  problem. Tolerances, not hash equality (§7.2). The suite runs through the xara
  adapter — it validates the adapter and schema mapping (§7.3) — with the minimal
  direct-stiffness fixture solver as an independent cross-check on the same fixtures.
- The phase 1 milestone list in the charter is the acceptance test suite, written as
  tests early, red until earned.

## 10. Open questions for the product owner

Ordered by how much they block.

1. **Material domain for the phase 1 structure.** The milestone's joist spacings
   (12/16/19.2/24 in) read as wood floor framing. Confirm: sawn-lumber joists/beams/posts
   with NDS-style checks? Or steel (AISC unity checks) with those spacings anyway? This
   decides the first design-check module and the section-property tables.
2. **Code slice for combos and checks.** Which load combinations (ASCE 7-22 §2.3 LRFD
   vs §2.4 ASD?) and which narrow provision set for the unity checks? For wood, ASD is
   the natural register; for steel, LRFD. "All members under unity" needs a definition
   of unity.
3. **Deflection/serviceability limits in phase 1?** The intent category exists
   (`serviceability`); do phase 1 constraints include L/360-type checks or is unity
   (strength) the only hard constraint?
4. **Sizing vs checking.** Does derivation *select* member sizes from a family table
   (auto-size to pass), or are sizes decision parameters that checks pass/fail? Proposal:
   sizes are decision parameters in phase 1 (explorations vary them); auto-sizing is a
   later derivation rule. Confirm.
5. **Tributary width rules.** Phase 1 proposal: half-span each side, simple-span
   members, no continuity effects on tributary. Acceptable simplification?
6. **Authoring units register.** Confirm ft-in/kip/psf/ksi as the authoring and display
   register (internal canonical SI per §2.4 regardless).
7. **The lateral strategy decision's phase 1 depth.** Proposal: the decision exists,
   derives designated shear-wall segments into the model and an intent instance
   (`lateral_capacity`), but no lateral analysis or checks in phase 1 — the milestone's
   lateral content is representational only. Confirm this doesn't undercut the retrofit
   validation case you care about.
8. **Provision references.** Intent relations cite code provisions (`"IBC 2021
   §2308.4.1"`). Phase 1: opaque validated strings, or a provisions table with stable
   IDs? Proposal: opaque strings now, table when checks start consuming them.
9. **Exploration constraint on intent: hard or soft?** §8 treats `intent_preserved` as
   a hard constraint (violating candidates are rejected pre-solve). Should an
   exploration ever be allowed to *propose* intent changes (e.g. "remove the opening")?
   Proposal: no in phase 1 — intent edits are human-reviewed changesets only.
10. **Xara license confirmation** (§7.3, resolved in direction, one action open). The
    xara-first posture was settled in review on 2026-07-07. The remaining action: a
    short email to the xara maintainer (Claudio Perez, STAIRLab) confirming the
    whole-tree BSD-2-Clause relicensing — inherited OpenSees core included, not just
    new contributions — is intended and authorized. Cheap insurance before a
    commercial product depends on it; I'll draft it, you send it as the commercial
    entity. If real revenue ever rides on the answer, that's a
    lawyer-reads-it-once item.

---

*Next steps after review: cut ADRs for the decisions this doc survives with (identity
scheme, canonical units, phase-1 solver, intent registry shape), then implement toward
the milestone in the increment order: store + schemas → decisions + validation →
derivation for the milestone structure → solver + verification → overrides → intent
checkers → exploration loop.*
