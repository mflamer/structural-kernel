"""The material-engine registry: family name → engine (ADR 0007).

One blessed engine per material family, the same posture ADR 0003 gives the
solver. A decision records a ``member_family``; derivation and the design
checks resolve the engine from here. Adding steel framing to the kernel is
implementing the protocol (done, ``steel.py``) plus a framing decision kind
that names ``hot_rolled_steel`` — no change to this registry's shape.

Concrete is intentionally absent: it is not a catalog engine (``concrete.py``).
"""

from __future__ import annotations

from structural_kernel.materials.base import MaterialEngine
from structural_kernel.materials.steel import SteelEngine
from structural_kernel.materials.wood import WoodEngine

ENGINES: dict[str, MaterialEngine] = {
    engine.family: engine for engine in (WoodEngine(), SteelEngine())
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
