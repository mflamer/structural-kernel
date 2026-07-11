"""The material-engine registry: family name → engine (ADR 0007).

One blessed engine per material family, the same posture ADR 0003 gives the
solver. A decision records a ``member_family``; derivation and the design
checks resolve the engine from here. Adding steel framing to the kernel was
implementing the protocol plus a framing decision kind that names
``hot_rolled_steel`` — no change to this registry's shape. Concrete (ADR 0014)
cashed the check ADR 0007 wrote: the dimensioned family registers here exactly
like the catalog ones, its designations parseable geometry rather than table
rows — the registry's shape again unchanged.
"""

from __future__ import annotations

from structural_kernel.materials.base import MaterialEngine
from structural_kernel.materials.concrete import ConcreteEngine
from structural_kernel.materials.steel import SteelEngine
from structural_kernel.materials.wood import WoodEngine

ENGINES: dict[str, MaterialEngine] = {
    engine.family: engine for engine in (WoodEngine(), SteelEngine(), ConcreteEngine())
}


def engine_for(family: str) -> MaterialEngine:
    engine = ENGINES.get(family)
    if engine is None:
        raise KeyError(
            f"no design-check engine registered for material family {family!r}; "
            f"registered: {sorted(ENGINES)}"
        )
    return engine


def families() -> frozenset[str]:
    return frozenset(ENGINES)
