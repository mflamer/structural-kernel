# Vision: The Demo This System Exists For

This is the conversation we are building toward. Every phase review answers one
question: did this get closer? Nothing here is phase 1 scope; it is the north star
that phase scoping is measured against.

**Setting:** A new single-story commercial building. The engineer has geometry and
loads — nothing else. No structural system has been chosen. The entire structural
concept emerges through conversation and solver-backed exploration.

---

**Engineer:** New project. Single-story shell, 120 ft × 80 ft footprint, 16 ft clear
height, flat roof. Ground snow 25 psf, wind and seismic per the site I'll give you.
No structural system yet — that's what I want to work out.

**System:** Model started. I have the envelope geometry, height, and roof loading as
decisions; the structural system is an open decision I'll hold unresolved. Before I
explore options — any constraints on the interior?

**Engineer:** The west 40 feet needs to be column-free, the tenant wants open space
there. Everywhere else, columns are fine but let's not go tighter than 25 foot bays.
Roof structure depth matters less than cost.

**System:** Captured: a clear-span requirement over the west 40 ft (recorded as
intent on that region — future changes that put a column there will be rejected,
not just flagged), a 25 ft minimum bay elsewhere, and cost as the primary
objective with structure depth unconstrained. For cost I need a basis. I have a
regional default from March — $/lb erected structural steel, $/BF framing lumber,
glulam premiums, crew rates, and lead times — or you can pin your own numbers.
Either way the basis is committed as a decision, so every ranking cites what it
was priced under.

**Engineer:** Use the default, but bump erected steel 10% — my fabricator's been
quoting hot lately. And installed cost, not material cost. Connections and picks
are where these comparisons go sideways.

**System:** Basis committed with your steel adjustment. Evaluation will be layered:
material cost from quantities, installation cost from countables — connection
count, crane picks, piece count, erection hours by crew rate — and lead-time flags
from the basis (glulam is quoting 14 weeks in this region; that won't price into
the ranking but will annotate it). Ranked comparisons carry an uncertainty note;
a 4% spread on installed cost is a coin flip, not a verdict. Ready to explore
structural systems?

**Engineer:** What are you going to try?

**System:** Four families, each as its own decision branch: (a) steel frame — wide-
flange girders and joists on HSS columns; (b) open-web steel joists on joist
girders; (c) glulam beams and purlins on timber columns; (d) a hybrid — long-span
steel over the clear-span zone, wood framing elsewhere. Within each family I'll
sweep bay spacing, framing direction, and member proportions. Every candidate is a
real branch through ordinary validation — anything that violates the clear-span
intent dies before it's solved. Budget: 400 solves.

**Engineer:** Go.

**System:** *(minutes later)* 312 candidates solved, 41 rejected pre-solve (most
put a column line in the protected zone). Ranked by installed cost under the
committed basis, all members passing strength and deflection: the open-web joist
scheme wins at 30 ft bays — about 12% cheaper installed than the best wide-flange
scheme, despite only a 6% material-cost edge; the joists win on piece count and
picks. Glulam ranked third on cost but carries the 14-week lead-time flag. The
hybrid ranked below pure steel joists: the clear span dominates the design either
way, so mixing systems bought connection complexity, not savings. Full ranking,
per-candidate cost breakdown (material / installation), and the load-path model
for the top three are attached.

**Engineer:** Why did glulam lose? I expected it closer.

**System:** Deflection governed, not strength. At the 40 ft clear span the glulam
candidates needed sections about 30% deeper than strength required to meet L/240
total-load; that depth cascades into volume, and glulam's unit premium prices the
extra volume painfully. With a cambered section it closes to within 7% installed —
inside the uncertainty band, honestly a coin flip on cost — so if the tenant
relationship favors exposed timber, cost no longer rules it out. Lead time would
be the real objection.

**Engineer:** My fabricator just re-quoted — erected steel is actually up 20%, not
10. Does that change anything?

**System:** Re-ranking under a revised basis — no re-solving needed; the physics
didn't change, only the prices. *(seconds later)* The joist scheme still wins, but
its margin over glulam-with-camber collapses to 3% — well inside uncertainty. At
this basis, system selection is genuinely open between them; the decision now
rests on lead time and the exposed-structure question, and the record will show
exactly that.

**Engineer:** Interesting — but the schedule can't eat 14 weeks. Take the joist
scheme. Lock the west span as protected, and set up the model so the next engineer
sees why every major member is there.

**System:** Committed. The model now carries: the system decision with its
exploration attached (all 312 candidates, both rankings — original and re-ranked
bases — and rejection records: the audit trail of what was searched, what it cost
under which assumptions, and why the winner won), the schedule rationale for
passing on glulam, derived intent on every primary member (the 40-ft joist girders
each record the clear-span requirement they serve), and the clear-span protection
as a hard intent. Anyone — human or AI — who later proposes a column at gridline
C.5 west of line 4 gets a structured rejection citing this conversation's decision.

---

## What this demo proves, in order of ambition

1. **System selection as exploration** — the biggest structural decision made by
   ranked, solver-backed search over *heterogeneous* branches (different decision
   kinds, not one strategy's parameters), through the ordinary validation pipeline.
2. **Cost as the ranking variable, honestly modeled** — layered installed cost
   (material + installation from countables), priced under a committed, versioned
   basis, with lead-time flags and stated uncertainty; re-rankable under a new
   basis in seconds because evaluation is separate from solving.
3. **Conversational intent capture** — "the west 40 feet needs to be column-free"
   became a typed, enforced intent without a form being filled in.
4. **Explainability from the load path and the cost breakdown** — "why did glulam
   lose?" answered from governing checks and priced quantities, not hand-waving.
5. **The audit trail as a first-class deliverable** — the searched space, the
   rejections, the cost bases, and the rationale persist with the model; the
   engineer of record can show their work.
6. **Intent outlives the conversation** — the protection binds future proposers,
   human or AI.

## Standing requirements this vision imposes on the kernel

- Explorations must support candidates of different decision *kinds* in one
  ranked comparison (phase 1's sweep proposer does not exercise this — no kernel
  decision may foreclose it).
- A decision may be explicitly *unresolved* and held open in a committed model.
- **Cost assumptions are decisions**: a versioned `cost_basis` decision kind
  (unit costs, crew rates, lead times, as-of date) that rankings cite; never
  hardcoded prices, never prices inside derivation rules.
- **Derivation must emit countables**, not just member quantities: connection
  counts, piece counts, picks — the drivers of installation cost — in the
  derived model and bill of elements.
- **Evaluation is a distinct layer from solving**: re-ranking an exploration
  under a new cost basis must not require re-solving; solve results are physics
  and are reused.
- Cost rankings carry their basis and an uncertainty statement; the system must
  be able to say "inside the noise" about a close comparison.
- **Derivation is staged, and later stages may consume solve results.** Detailed
  components — connections, bolts, reinforcing — are derived from rules applied
  to member geometry *and demands*, so the pipeline is derive → solve →
  detail-derive (→ re-solve where detailing changes stiffness). Each stage stays
  pure and deterministic; solve results are simply inputs to later stages. The
  derivation contract must not assume a single pass.
- **Level of detail is a derivation parameter, not a model property.** The same
  snapshot derives at exploration resolution (members only) or fabrication
  resolution (every bolt and bar), cached by hash like any artifact. The decision
  graph never grows with detail — only derived artifacts do. Component identity
  is hierarchical (bolt eids nest under their connection under their member),
  which the eid scheme must anticipate.
- **Solve fidelity is tiered.** The solver interface admits engines of different
  fidelity with declared accuracy contracts — surrogates screen large design
  spaces cheaply; true FEA verifies finalists; hand calcs anchor the FEA. Only
  verification-grade results feed design checks and the engineer-of-record
  record. Every solve result carries its engine class.
- Intent must be capturable from conversation by the AI surface and enforceable
  against all future changesets.
- Exploration records attach to the decision they resolved, permanently.
