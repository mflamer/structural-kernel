# 0010 — Closed-loop LLM refinement

**Status:** Accepted (2026-07-08, product owner directed; extends ADR 0009)

## Context

ADR 0009 wired an LLM behind the `Proposer` seam and deliberately shipped a
*single slate*: one round of candidates, then converge. The vision's ambition is
larger — an AI-native optimizer that learns from what it tried and proposes
better, iterating to a good design under a solve budget. This ADR turns the
single-shot proposer into that closed loop.

The lifecycle already supported it. `run_exploration` loops over generations,
evaluates and persists each one, and passes the *growing* `Exploration` object
(all prior candidates, their solve results, and rankings) back into
`proposer.propose` before the next round. So closed-loop refinement is proposer
work, not a lifecycle change.

## Decision

- **`LLMProposer` gains a `refine` flag.** Default (single-slate) behavior is
  unchanged from ADR 0009 — one slate, one generation, then converge. In
  `refine` mode the proposer keeps proposing.

- **Each refinement round feeds the prior round's results back into the prompt.**
  The proposer reads them from the persisted exploration and summarizes, per
  candidate: its kind and member sizes, whether it was feasible, its total
  member mass and worst (governing) unity, or — for a rejected candidate — the
  rejection reason; plus the best feasible design found so far. The prompt then
  asks the model to *improve*: make an infeasible candidate work by enlarging the
  governing members, and lighten a feasible one that has unity margin.

- **The loop ends the way the kernel already ends explorations.** The model may
  propose nothing (it judges the best feasible design near-optimal), which the
  loop reads as convergence; otherwise the kernel's existing no-improvement
  convergence and `max_solves` / `max_generations` budget stop it. No new
  stopping machinery.

- **Still propose-only, still replay-by-record.** The feedback is *read* from the
  persisted exploration; the model only returns tool calls; the ordinary
  validate pipeline is the sole writer (ADR 0009's "AI never edits state
  directly"). The emitted slates are recorded per generation, so replay reads the
  record and never re-calls the model — the record, not the model, is the
  reproducible artifact of a non-deterministic loop. The proposer mode (`slate`
  or `refine`) rides on the `ProposerRef`.

## Consequences

- CI stays deterministic and secret-free: a `ScriptedLLMClient` (a sequence of
  slates, one per call, an empty final slate ending the search) drives the
  closed-loop tests; no LLM call runs in CI. A scripted run finds a lighter
  feasible design in the refinement round and converges on the empty slate.

- The feedback this round is the persisted evaluation metrics (feasibility,
  mass, worst unity) plus the candidate's own sizes — enough to steer heavier or
  lighter. Naming the *specific* governing member/check (deeper than `max_unity`)
  would tighten convergence and is a cheap follow-up (re-checking stored results,
  no re-solve); it is deliberately out of scope here to keep the change to the
  proposer.

- **Deferred, unchanged from ADR 0009:** conversational intent capture, glulam
  and other families, and cost-basis-aware proposals once priced evaluation
  exists. Multi-round *diversity* controls (loop-until-dry, dedup against prior
  rounds) are a later refinement if runs start re-proposing stale candidates.

Supersedes nothing; extends ADR 0009 (the single-slate LLM proposer) into the
closed loop it deferred, over the same lifecycle and the same guardrails.
