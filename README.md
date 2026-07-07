# structural-kernel

An AI-native building information system for structural engineering, built from
a clean slate. The canonical model is a versioned graph of *design decisions*;
geometry, analysis models, design checks, and schedules are *derived artifacts*
computed by pure functions over that graph. Every element carries structured
structural intent — why it exists, tied to loads, load paths, and code
provisions — so an AI can evaluate whether a proposed change breaks the design,
not just the geometry.

This is not an IFC successor, not a plugin, and not a file format.

## Orientation

| Document | What it is |
|---|---|
| [`docs/kickoff.md`](docs/kickoff.md) | The project charter: principles, non-goals, phase 1 milestone. Read this first. |
| [`docs/design/0001-kernel-and-solver-architecture.md`](docs/design/0001-kernel-and-solver-architecture.md) | The kernel + solver architecture design doc (under review). |
| [`docs/decisions/`](docs/decisions/) | ADR log. This project is itself decision-derived; we eat the dog food. |

## Status

**Pre-implementation.** The design document is drafted and awaiting review by
the product owner (a licensed PE acting as domain expert). Per the charter, no
kernel code lands until the design doc is reviewed.

## Toolchain

- Python 3.14, strict typing (`pyright` strict mode must be clean)
- `pydantic` v2 for schema; discriminated unions for sum types
- `pytest` + `hypothesis` for tests; derivation functions property-tested
- `ruff` for lint + format
- `uv` for environment and lockfile management

```sh
uv sync          # create the environment
uv run pytest    # run tests
uv run pyright   # type-check (strict)
uv run ruff check && uv run ruff format --check
```
