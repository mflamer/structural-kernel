# 0001 — Repository layout and toolchain

**Status:** Accepted (2026-07-07)

## Context

The charter (`docs/kickoff.md`) fixes Python 3.14, strict typing, pydantic schemas,
and pytest, but leaves the surrounding tooling and repo shape open. These choices are
low-stakes individually and expensive to churn, so they get settled once, here, before
any code.

## Decision

- **Layout:** `src/` layout with a single package `structural_kernel`; tests outside
  the package in `tests/`. Docs in `docs/` (`design/` for proposals under review,
  `decisions/` for this log).
- **Environment/lock:** `uv` (`uv sync`, `uv run`). One lockfile committed.
- **Type checking:** `pyright` in **strict** mode is the gate ("pyright/mypy clean" per
  charter — pyright is the one wired into CI first; mypy may be added as a second
  opinion later, not as a second gate).
- **Lint/format:** `ruff` for both (rule set in `pyproject.toml`); no black, no isort —
  ruff subsumes them.
- **Tests:** `pytest` + `hypothesis`. Property tests are the default posture for
  derivation functions (determinism, composition laws), example tests for everything
  else.
- **Schema:** pydantic v2. Discriminated unions for sum types; exhaustiveness of
  `match` over unions enforced by pyright strict (a non-exhaustive match is a type
  error via `assert_never`).
- **Single distribution:** kernel, derivation, solver client, and the phase-1 local
  solver live in one package with clear module boundaries; splitting into separate
  distributions is deferred until something (the solver worker image) actually needs to
  deploy separately.

## Consequences

- Contributors need `uv` installed; everything else bootstraps from the lockfile.
- Strict pyright from day one means schema/typing friction is paid immediately, which
  is the point — the persisted schema is the source of truth and the types must track it.
- CI (when added) runs exactly what the README shows: `pytest`, `pyright`,
  `ruff check`, `ruff format --check`. No hidden gates.
