# Decision log (ADRs)

This project's canonical model is a graph of design decisions — so is the project
itself. Every significant, settled choice gets a numbered ADR here. Choices still under
review live in `docs/design/` as proposals and graduate to ADRs when they survive.

Format: one file per decision, `NNNN-short-title.md`, containing **Status**,
**Context**, **Decision**, **Consequences**. Superseded ADRs are never deleted; their
status changes and they link forward.

| # | Title | Status |
|---|---|---|
| [0001](0001-repo-and-toolchain.md) | Repository layout and toolchain | Accepted |
| [0002](0002-canonical-units.md) | Canonical SI units with tagged quantities at every boundary | Accepted 2026-07-07 |
| [0003](0003-solver-agnostic-xara-first.md) | Solver-agnostic kernel; xara as the first engine | Accepted 2026-07-07 |
| [0004](0004-intent-registry-and-two-site-enforcement.md) | Intent: kernel-fixed shape, open category registry, two-site enforcement | Accepted 2026-07-07 |

Pending: the eid identity scheme (design-doc review R1) is proposed in
[`docs/design/0002-eid-identity-scheme.md`](../design/0002-eid-identity-scheme.md)
and becomes ADR 0005 when it survives product-owner review. Derivation
implementation is gated on it.
