# 0009 — The LLM proposer behind the Proposer seam

**Status:** Accepted (2026-07-08, product owner directed; builds on ADR 0008)

## Context

Increment 7 built the `Proposer` protocol and a `StubLLMProposer` as the seam an
LLM would slot into, and ADR 0008 proved that candidates of *different decision
kinds* rank together through the ordinary pipeline. This ADR wires a real LLM in
— the first AI that actually drives the exploration engine.

The charter's hard rule governs the design: **the AI never edits state
directly — changesets only, propose → validate → commit/reject.** The LLM must
sit strictly outside the write path.

Product-owner choices for this increment: an Anthropic client behind a
deterministic fake seam; a single heterogeneous slate (not yet closed-loop);
default model `claude-opus-4-8`.

## Decision

- **A provider-neutral `LLMClient` seam** (`llm.py`). One method —
  `invoke_tools(system, user, tools) → [ToolInvocation]` — plus the neutral
  `ToolSpec` / `ToolInvocation` vocabulary. Nothing provider-typed crosses it,
  the same posture the solver and material engines have. Two implementations:
  - `FakeLLMClient` — deterministic, returns canned tool calls and records the
    prompts it was asked. This is the path the tests and **CI** take: no network,
    no key.
  - `AnthropicClient` (`llm_anthropic.py`) — the real client, the one module
    that imports the `anthropic` SDK. It forces tool use
    (`tool_choice={"type": "any"}`) and collects every `tool_use` block from the
    single response (parallel tool use returns the whole slate in one call). The
    model defaults to `claude-opus-4-8`; Opus 4.8 rejects sampling and
    thinking-budget parameters, so none are sent. It is an optional `llm` extra
    (the same posture as xara), and its SDK contact is pyright-isolated so the
    seam stays strict.

- **`LLMProposer` behind the existing `Proposer` protocol** (`explorations.py`).
  It reads the base geometry and loads, prompts the model with a
  `propose_wood_framing` / `propose_steel_framing` tool pair (LLM-friendly
  schemas — spacing as an inches/feet number, sections as designation strings;
  the framed region is fixed by the exploration and injected by the proposer),
  and turns each tool call into an ordinary changeset proposal. **The decision
  *kind* is chosen by which tool the model calls** — a wood
  `gravity_framing_strategy` or a steel `steel_framing_strategy` — so the slate
  is heterogeneous by construction (standing requirement 1). A steel candidate
  additionally restates the load decision onto the ASCE 7-22 §2.3 LRFD combos
  (ADR 0008).

- **Propose-only; the pipeline is the sole writer.** The client returns tool
  calls; the proposer turns them into `Proposal`s; the ordinary validate pipeline
  commits or rejects. Malformed inputs (a bad section, a missing field) and
  intent-violating candidates become **recorded rejections**, never commits —
  the validation pipeline is the guardrail, so the model need not be perfect, and
  the charter's "AI never edits state directly" holds by construction.

- **Replayability over determinism.** An LLM is non-deterministic, so the
  proposer records its emitted slate in the exploration; replay reads the record
  and never re-calls the model (this is what keeps LLM-driven explorations
  replayable — the record is the artifact, not the model). The model identity
  (the client descriptor, e.g. `anthropic/claude-opus-4-8`) rides on the
  `ProposerRef` for the engineer-of-record audit trail.

- **Single slate this increment.** One generation of candidates, then converge.
  The generation history is already carried on the `Exploration`, so
  closed-loop refinement (feeding prior solve results and rankings back into the
  prompt) is a later increment, not a re-architecture.

## Consequences

- **CI is deterministic and secret-free.** The fake client drives every test;
  the real client is exercised locally with `uv sync --extra llm` and an API key
  or `ant` profile. No LLM call runs in CI.

- Adding the LLM proposer touched no kernel invariant — it is one more
  `Proposer`. The seam the charter demanded ("an LLM proposer slots in without
  kernel changes") is now met by a real one, not a stub.

- **Deferred:** closed-loop refinement (propose → see results → propose better);
  conversational intent capture (the vision's "the west 40 feet needs to be
  column-free" becoming a typed, enforced intent); glulam and other families;
  and cost-basis-aware proposals once priced evaluation exists.

- One blessed provider client for now (Anthropic); the `LLMClient` protocol
  admits others without touching the proposer.

Supersedes nothing; realizes the seam ADR 0001/§8 reserved and the
`StubLLMProposer` stood in for, and composes with ADR 0008's heterogeneous
exploration.
