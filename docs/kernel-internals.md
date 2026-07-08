# Kernel Internals: Data Structures and Algorithms

*A summary of the decision graph as implemented, for the phase-1
representation review. Status as of 2026-07-08. Governing documents: the
charter (`kickoff.md`), design doc 0001 (as revised), ADRs 0001–0006, and the
eid design doc 0002. File references point into `src/structural_kernel/`.*

---

## 1. Identity: three id kinds, two notions of "same"

| Id | Form | Minted | Meaning |
|---|---|---|---|
| `did` | 26-char ULID (`01JXF…`) | at decision creation (`ids.new_ulid`) | what a decision *is* across time |
| `hash` | `sha256:<64 hex>` | computed from content | what an object *says* right now |
| `line_id` | `L` + 8 Crockford chars | at grid-line creation (`ids.new_line_id`) | stable identity of one grid line; display names ("B") are presentation only |
| `eid` | grammar, §3 below | **computed** by derivation, never minted | stable identity of a derived element |

The git analogy holds exactly: `did` ≈ file path, `hash` ≈ blob hash,
snapshot ≈ tree, commit ≈ commit, branch ≈ ref.

**Content addressing** (`canonical.py`): every persisted object is serialized
to *canonical JSON* — sorted keys, minimal separators, UTF-8, NaN/Infinity
rejected — and its address is the SHA-256 of those bytes. Two structurally
identical objects therefore share one address (free deduplication), and any
tampering is detectable (reads re-hash and compare). Floats use Python's
shortest-round-trip representation; a reimplementation in another language
must match it or hashes diverge (documented in the module).

## 2. The store (`store.py`)

Git-like, on disk, behind an interface a cloud database can implement later:

```
<root>/objects/<2 hex>/<62 hex>    immutable canonical bytes of one object
<root>/refs/<name>                 mutable pointer: one object hash per line
```

- `put(doc)` is idempotent: hash, write-if-absent (atomic temp-file +
  rename). `get(hash)` verifies integrity before returning.
- **Refs are the only mutable state in the system.** They advance by
  compare-and-swap under a lock file: `compare_and_swap(name, expected, new)`
  fails with `StaleBaseError` if the ref moved — first commit wins, the loser
  rebases. Branching is literally a ref copy.

Persisted object kinds (`objects.py`), all with `schema_version`, all
immutable, all `extra="forbid"`:

| Kind | Contents |
|---|---|
| `Decision` | did, kind (closed union of 7), title, `state: resolved\|open`, kind-specific `params`, declared `deps`, attached intent |
| `Snapshot` | sorted map `did → decision hash` + override-set hash — the complete model at an instant |
| `Commit` | snapshot hash, parent hashes, author (human/ai/proposer), timestamp, message, changeset hash |
| `Changeset` | base commit + op list (discriminated union: add/modify/remove decision, add/remove override). **Persisted even when rejected** |
| `ValidationReport` | changeset hash, outcome, issues — the judgment record for every proposal |
| `OverrideSet` / `Override` | target (eid, field), value, surveyed anchor, provenance (who/how/when/confidence) |
| `AnalysisModel`, `SolveResult`, `DerivedModel` | derived artifacts — reproducible cache, never source |
| `Exploration` | §8 below |

**Units** (`units.py`, ADR 0002): no bare float crosses any interface. A
value is `{mag, unit}` with the unit spelling from a curated whitelist
(28 spellings, 9 dimensions); conversion factors derive from four NIST-exact
primitives. Schema fields are *dimension-constrained types* — a psf value in
a length slot is a validation failure, not a latent bug. Canonical internal
system is SI; ft-in/kip/psf/ksi live only at the authoring/display boundary.

## 3. Element identity: the eid grammar (`eids.py`, ADR 0005)

An eid is a `/`-separated path of `{role}:{inducer}:{anchor}` segments:

```
jst:01JXF…:L000000B1-L000000B2.L000000A1+006
│   │      └ anchor: span lines (sorted), counting-origin line, ordinal
│   └ the decision whose rule emitted this element
└ role (jst/bm/pst/hdr/wallseg; connections and bolts extend the path later)
```

The load-bearing properties, each held by a property test:

- **Anchors are names, never coordinates.** Line-ids, topological names,
  ordinals — so *moving* a gridline changes geometry but no eids, and
  *renaming* one changes literally nothing (byte-identical derived model).
- **Ordinal origin = the bounding line whose id token sorts first**
  (lexicographic), a key invariant under every geometric edit — a line moved
  spatially past its neighbor cannot flip the counting origin.
- **Honest renumbering:** eids survive everything except changes to the
  output structure of the rule that emits them (a respacing produces
  *different members* and says so). Locality: an edit inside one rule
  instance perturbs no eids outside it.
- **Per-consumer correspondence:** diffs and rankings use the eid alone
  (rule-relative space); overrides additionally carry a surveyed world-space
  anchor (absolute space) — §6.
- Every prefix of an eid is its parent element's eid; deeper level-of-detail
  extends paths, never rewrites them (reserved for phase 2+).
- The rendered form (display names substituted) exists only in
  `render_eid()` and is never persisted.

## 4. The write path (`kernel.propose`) — the only way state changes

```
propose(changeset)
  ├─ base check          changeset.base == ref tip, else stale_base (a
  │                      rejection, not an exception — callers rebase)
  ├─ stage 1  schema     kind params validate (incl. dimensional checks);
  │                      authored intent: category registered, payload
  │                      validates, relation roles declared
  ├─ apply ops           duplicate/unknown targets collected as errors
  ├─ stage 2  referential GLOBAL over the resulting snapshot: deps resolve,
  │                      dependency DAG acyclic (iterative DFS, 3-color),
  │                      line-id refs resolve THROUGH DECLARED DEPS ONLY,
  │                      intent load/decision targets exist
  ├─ stage 3  derivation dry-run — derive the whole resulting snapshot in
  │                      memory; DerivationError → rejection; a dangling
  │                      exception → hard error (retarget or delete)
  ├─ stage 4  intent     every registered checker over the dry-run model;
  │                      violations reject with the structured error shape
  ├─ override warnings   displaced/dangling overrides → commit WARNINGS
  │                      (never rejections, never dropped) — recomputed on
  │                      every commit until a human resolves them
  └─ commit              write decision/snapshot/commit objects, then CAS
                         the ref: atomic — everything or nothing. A lost
                         race is one more stale_base rejection.
```

Fail-fast between stages, collect-all within a stage. Every rejection
persists the changeset and a `ValidationReport` with machine-actionable
issues (each has a code from a closed union, a message, and structured
detail). Stage 2 being *global* is what makes ADR 0005 E3 work: deleting a
grid line out from under an untouched framing decision fails referential
validation without any special casing.

## 5. Derivation (`derivation.py`) — pure functions over the snapshot

`derive(snapshot) → DerivedModel`, deterministic (no clock, randomness, or
I/O; property-tested byte-identical), total over valid snapshots (anything
that can't derive was rejected at stage 3), versioned (`DERIVATION_VERSION`
stamps every artifact).

**Rule order and context discipline.** Rules run by kind, decisions sorted
by did: framing strategies → openings → lateral → exceptions → overrides.
Each rule resolves context **strictly through its declared deps** (a framing
strategy sees only the grids/levels/loads it declares), which makes "reads ⊆
declared dependencies" true by construction instead of by audit.

**The framing rule** computes joist positions along the layout axis
(`k·spacing` plus a closing position), tributary width per joist as the
half-gap to each neighbor (property test: tributaries tile the region width
exactly, for any spacing × width), beams on the bearing lines with
half-span tributary, posts at region corners when the level elevation is
positive, and attaches derived intent (`gravity_load_path` with `carries`
relations to the load decisions; `serviceability` with the L/360–L/240
payload) to every member.

**The opening rule** finds the enclosing framing (a declared-dep strategy
bearing on the opening's wall line), emits the header (span = rough width +
3" bearing each side), computes the redirected joist set (layout positions
within the opening extent), rewires their support edges joist→header→beam,
and writes the header's intent: `redirects_load_around → opening decision`,
`carries → each redirected joist` — the machine-readable "why".

**Load-path graph**: edges `bearing → on`, derived from each element's
support list; doubles as the substrate for queries and intent checking.

**Exceptions then overrides** apply as substitution passes in that order
(design preference first, measured reality last — reality wins a conflict).

**Partial models** (standing req. 10): open decisions derive to their
explicit absence; a model with no flexural members has `analysis = None` —
a valid state, not an error.

**Outputs:** element list (geometry, section, grade, tributary, supports,
intent, override provenance), load-path edges, open-decision list, bill of
elements grouped by role/section with countables (piece count, connection
count; crane picks reserved), and the self-contained analysis artifact
(§7.1 shape: SI values, `source_eid` back-references, ASD combo subset
generated from the cases actually present).

## 6. Override re-attachment (`derivation._apply_overrides`, ADR 0005)

For each override, in deterministic (eid, field) order:

```
target eid exists?
  no  → DANGLING: warn, stay inert; propose up to 3 candidate re-targets
        by anchor proximity (point-to-segment distance ≤ 1 m)
  yes → surveyed anchor present?
          no  → attach by eid alone
          yes → d = point-to-segment distance(anchor, member axis)
                d ≤ tolerance → ATTACHED: substitute value, record
                                provenance on the element field
                d > tolerance → DISPLACED: warn, stay inert (the member
                                moved with the model; the surveyed one
                                didn't — applying the measurement could
                                attribute it to the wrong physical member)
```

Tolerance = the anchor's explicit tolerance, else bucketed by provenance
confidence: measured 25 mm, estimated 150 mm, `assumed` = ∞ (advisory —
an assumption is not a measurement of position). The completion of eid
property test 2 lives here: a gridline move changes no eids and transitions
the affected overrides to *displaced*, never silently re-attached.

## 7. Intent checking (`intents.py`, ADR 0004) and design checks

**The registry** is the open/closed boundary the charter demanded: the
kernel fixes intent *shape* (envelope, relations, provenance); categories
are data — `(name, payload schema, relation roles, checker)` entries in
`REGISTRY`. Adding `vibration` later is one new entry, zero kernel edits.
Checkers are pure functions of `(derived model, instance, carrier,
snapshot)` — property-tested deterministic.

Commit-time algorithms (stage 4):

- **Support-chain walk**: from each gravity-intent carrier, BFS down the
  load-path graph; every terminal must be grounded (a post, a wall segment,
  or at grade).
- **Opening interruption**: for each opening on a wall that *something bears
  on* (beams/wall segments geometrically on that line), every joist bearing
  there inside the opening extent must route through a header whose intent
  redirects around *that* opening — else the structured violation with the
  broken-path listing. This is "delete the header while the opening remains"
  as an enforced invariant.
- **Authored eid-target resolution**: eids exist only after derivation, so
  authored intent pinning an eid resolves here, against the dry-run model.

**Solve-time design checks** (`design_checks.py`, the other half of the
two-site split): NDS 2024 ASD bending/shear (via the ndswood adapter,
ADR 0006 — all library contact confined to `nds.py`, SI ⇄ lb/in/psi
converted once at that boundary), post compression with axial demand summed
from the reactions of the members the *load-path graph* says bear on the
post (location-proximity summation double-counts — found by hand calc), and
kernel-side deflection: live = total-combo minus dead-only deflection
(linear superposition), limits span/360 and span/240. Every check carries
demand, capacity, unity, the governing provision, the full factor trail
(CD/CF/Cr… each with its NDS reference), and the intent instance it
enforces. Only verification-grade solve results are accepted.

## 8. Solving (`solver.py`, `planar.py`, adapters)

The artifact is the entire solver contract — self-contained, no store
access. The service interface (`submit(batch) → job`, `status`, `results`)
is cloud-shaped; phase 1 runs engines in-process behind it. Failures are
data (`mechanism_detected`, `singular_system`, `invalid_artifact`,
`worker_crash`), never exceptions — explorations rank around them. Every
result carries its engine's name/version/**fidelity class** (standing
req. 9: only verification-grade feeds checks and the record).

**Planar idealization** (shared by all adapters): artifact elements group
into connected components by shared nodes (union–find); each component must
be axis-aligned and horizontal (phase-1 pattern, enforced); members
subdivide into 16 exact cubic-Hermite segments with consistent fixed-end
forces, so nodal displacements are exact and the subdivision exists only to
sample deflection extrema densely enough for the 0.5% tolerance. Member
force extrema are recovered analytically per segment (moment vertex where
shear crosses zero).

Two engines answer to the same hand-calc fixtures (simply-supported UDL,
midspan point load, two-span continuous, cantilever): the **xara adapter**
(the blessed engine, ADR 0003) and the **direct-stiffness cross-check** — a
pure-Python exact-stiffness solver living in the test suite as the
independent second opinion. It has already paid for itself twice (a segment
moment-recovery sign error; the post double-count).

## 9. Explorations (`explorations.py`) and queries (`queries.py`)

The generation loop, kernel-owned:

```
for each generation (≤ max_generations):
    proposals ← proposer.propose(exploration, store)     # [] ⇒ converged
    for each proposal:
        branch ref  ← CAS-create as a copy of the base commit
        propose()   ← the ORDINARY pipeline; rejections recorded, not solved
        derive; store the analysis artifact           (if within max_solves)
    one service.submit() for the whole generation        # batch dispatch
    store every SolveResult; append the Generation
    evaluation ← evaluate(stored results only)           # see below
    persist the exploration object + advance its ref     # resumable record
    convergence / budget checks
```

**The evaluation layer is deliberately separate** (PO reply, item 3):
candidates carry physics references only; an `Evaluation` is keyed by
`(result-set hash, cost_basis)` and computes metrics (member mass from
verified section areas × specific gravity), feasibility (all design checks
pass + metric constraints), and ranking (feasible first, objective order).
Re-ranking — today with a null cost basis, later under a revised priced
basis — appends an evaluation from *stored* results and never re-solves.
Replay is exact: same base + same proposer ⇒ identical changeset hashes and
rankings (proposers are deterministic; the sweep's rationale is mechanical
but mandatory).

Proposers are the pluggable seam (`Proposer` protocol): `GridSweepProposer`
(spacing × layout cross product, one generation) and `StubLLMProposer` (the
charter's proof that an LLM slots in without kernel changes).

**Queries** are thin pure reads: `what_carries` (load-path edges), `why`
(an element's intent instances), `header_for_opening` (resolve through
`redirects_load_around` relations), `best_variant` (top feasible entry of
the latest ranking).

## 10. Invariants under test

Every kernel invariant has a test (charter rule); the property-based ones:

| Invariant | Where proven |
|---|---|
| Canonical encoding deterministic; key-order invariant | hypothesis, `test_canonical` |
| SI round-trip lossless across the whole unit whitelist | hypothesis, `test_units` |
| Derivation byte-identical on repeat | `test_derivation` |
| Gridline move: eids unchanged, geometry changed, overrides → displaced | eid tests 2 + overrides |
| Gridline rename: byte-identical derived model | eid test 3 |
| Edit locality; cross-branch eid correspondence; honest renumbering | eid tests 4, 6, 7 |
| Joist tributaries tile the region exactly (any spacing × width) | hypothesis |
| Intent checkers pure/deterministic | `test_intents` |
| Solver vs hand calcs: 0.5% displacement / 0.1% reactions, two engines | verification suite |
| Exploration replay reproduces the searched space | `test_exploration` |

Scale note: phase-1 algorithms are linear scans and small dense solves —
correct first, indexed later. The places that will want indices (eid lookup,
derivation caching by `(snapshot, version)`) are localized behind pure
functions, so adding them is an optimization, not a redesign.

---

*Everything above described the phase-1 `main` at the representation review.
**The product owner approved the representation on 2026-07-08** — the shape
questions (is the decision graph, the eid scheme, and the two-site intent split
the right representation?) are answered yes; the graph, eids, and two-site
intent split are the accepted foundation for phase 2. Still open, and separate
from the representation: the domain-value assumptions in
`docs/design/0003-phase1-domain-assumptions.md` (dressed-size tables, reference
E, header bearing, combo subsets). Phase 2 has since added steel framing +
heterogeneous exploration (ADR 0008), which the approval covers as an extension
of the same representation.*
