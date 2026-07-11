"""Material design-check engines behind a common adapter (ADR 0006 → 0007).

The kernel is code-agnostic the same way it is solver-agnostic: verified
code-calculation libraries (NDS/AISC/ACI) are *engines* behind a common
``MaterialEngine`` adapter, one per material family, resolved from a registry
by the ``member_family`` a decision records. Every engine speaks the kernel's
neutral check vocabulary (``MemberCheckData`` with demand/capacity as tagged SI
quantities, unity, provision citation, factor audit trail); no library type
ever crosses this boundary. The three libraries deliberately share a
``Factor``/``CheckResult`` shape, which is what lets one vocabulary serve all.
"""

from structural_kernel.materials.base import (
    AxialRequest,
    FlexureRequest,
    MaterialEngine,
    MemberCheckData,
    ProvisionFactor,
    ReinforcementData,
    SectionProperties,
)
from structural_kernel.materials.registry import ENGINES, engine_for, families

__all__ = [
    "ENGINES",
    "AxialRequest",
    "FlexureRequest",
    "MaterialEngine",
    "MemberCheckData",
    "ProvisionFactor",
    "ReinforcementData",
    "SectionProperties",
    "engine_for",
    "families",
]
