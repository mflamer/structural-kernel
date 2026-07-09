"""Referenced geometry: the ingestion read surface (design doc 0005 §3, ADR 0013).

The architect's model enters as *referenced geometry* — read-only external context
a constraint anchors to, never a decision. This module is the **adapter boundary**
(the posture of the solver, material, and LLM engines): the importer maps an
IFC-shaped extract to :class:`ReferencedGeometry`, and nothing about *how* the
model was read — no IFC/DWG/vision type — crosses into the kernel. The phase-1
importer is deterministic and secret-free (an IFC grid/storey fixture); a real
``ifcopenshell``-backed importer plugs in at this same seam later.

Re-issue reconciliation lives here too: when an architectural model is re-issued
(a strictly higher version at the same ``ref_id`` lineage), :func:`reconfirmations`
diffs old vs new and surfaces every constraint whose referenced anchor *moved* or
was *removed* — the ADR 0005 displaced/dangling machinery, now at the architecture
boundary. A moved anchor keeps binding (the region tracks the grid to its new
position, the whole point of anchoring by name not coordinate); the warning is the
"re-confirm this reading" signal, so a re-issue never silently diverges.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from structural_kernel.objects import (
    ExternalProvenance,
    KernelModel,
    ReferencedGeometry,
    ReferencedGrid,
    ReferencedLevel,
    ReferencedRegion,
)
from structural_kernel.units import LengthQuantity

if TYPE_CHECKING:
    from structural_kernel.ids import Did
    from structural_kernel.validation import ResolvedSnapshot

_EPS = 1e-6

# The importer's identity, stamped into every import's provenance. Bump when the
# mapping changes so a model's read is reproducible from its stamp.
IMPORTER_VERSION = "ifc-grid-fixture/1"


# -- the importer adapter (IFC-shaped extract -> referenced geometry) ----------------
#
# The input schema is the *IFC* vocabulary (grid axes, storeys); it is adapter-local
# and never persisted. `import_ifc_grids_and_levels` maps it to the kernel's
# `ReferencedGeometry`, converting to canonical units and adopting the source tags
# as stable ids. Only the kernel type leaves this module.


class _IfcGridAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str  # IfcGridAxis.AxisTag — the stable source id
    name: str
    axis: Literal["x", "y"]
    offset: LengthQuantity


class _IfcStorey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str  # IfcBuildingStorey GlobalId
    name: str
    elevation: LengthQuantity


class _IfcExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grids: list[_IfcGridAxis] = Field(default_factory=list[_IfcGridAxis])
    storeys: list[_IfcStorey] = Field(default_factory=list[_IfcStorey])


def import_ifc_grids_and_levels(
    source: Path | str, *, ref_id: Did, imported_at: str, version: int = 1
) -> ReferencedGeometry:
    """Read an IFC grid/storey extract (a JSON fixture in phase 1) into a
    ``ReferencedGeometry`` version. Deterministic: same bytes → same object,
    including the ``file_hash`` provenance. ``imported_at`` is supplied by the
    caller (no wall-clock in the kernel). No IFC type crosses out of this call."""
    path = Path(source)
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest()
    extract = _IfcExtract.model_validate_json(raw)
    return ReferencedGeometry(
        ref_id=ref_id,
        version=version,
        provenance=ExternalProvenance(
            source_file=path.name,
            file_hash=file_hash,
            importer=IMPORTER_VERSION,
            imported_at=imported_at,
        ),
        grids=[
            ReferencedGrid(grid_id=g.tag, name=g.name, axis=g.axis, offset=g.offset)
            for g in extract.grids
        ],
        levels=[
            ReferencedLevel(level_id=s.tag, name=s.name, elevation=s.elevation)
            for s in extract.storeys
        ],
    )


# -- re-issue reconciliation (ADR 0005 displaced/dangling at the arch boundary) ------


class ReconfirmationWarning(KernelModel):
    """A constraint whose referenced anchor changed on re-issue. ``moved`` = the
    grid shifted (the region still binds, tracking it — re-confirm the reading);
    ``removed`` = the grid is gone in the new version (the region also goes inert
    dangling at stage 5). Surfaced on the re-issue commit, never dropped."""

    cid: str
    ref_id: str
    anchor_grid: str
    change: Literal["moved", "removed"]
    message: str
    detail: dict[str, JsonValue] = Field(default_factory=dict)


def reconfirmations(
    base: ResolvedSnapshot, result: ResolvedSnapshot
) -> list[ReconfirmationWarning]:
    """Diff each re-issued referenced-geometry lineage (a strictly higher version
    at the same ``ref_id``) old vs new, and flag every constraint anchored to a
    grid that moved or was removed. Pure over (base, result)."""
    warnings: list[ReconfirmationWarning] = []
    for ref_id, new_geo in sorted(result.referenced_geometry.items()):
        old_geo = base.referenced_geometry.get(ref_id)
        if old_geo is None or new_geo.version <= old_geo.version:
            continue  # newly imported, or not a re-issue: nothing to reconcile
        old_grids = {g.grid_id: g for g in old_geo.grids}
        new_grids = {g.grid_id: g for g in new_geo.grids}
        for constraint in sorted(result.constraints.values(), key=lambda c: c.cid):
            region = constraint.region
            if not isinstance(region, ReferencedRegion) or region.ref_id != ref_id:
                continue
            old = old_grids.get(region.anchor_grid)
            new = new_grids.get(region.anchor_grid)
            if new is None:
                warnings.append(
                    ReconfirmationWarning(
                        cid=constraint.cid,
                        ref_id=ref_id,
                        anchor_grid=region.anchor_grid,
                        change="removed",
                        message=(
                            f"constraint {constraint.cid} ({constraint.statement!r}) anchors to "
                            f"grid {region.anchor_grid!r}, removed when {ref_id} was re-issued "
                            f"(v{old_geo.version}→v{new_geo.version}); the region is now inert — "
                            "re-confirm against the new model"
                        ),
                        detail={"old_version": old_geo.version, "new_version": new_geo.version},
                    )
                )
            elif old is not None and (
                new.axis != old.axis or abs(new.offset.si_mag - old.offset.si_mag) > _EPS
            ):
                warnings.append(
                    ReconfirmationWarning(
                        cid=constraint.cid,
                        ref_id=ref_id,
                        anchor_grid=region.anchor_grid,
                        change="moved",
                        message=(
                            f"constraint {constraint.cid} ({constraint.statement!r}) anchors to "
                            f"grid {region.anchor_grid!r}, moved when {ref_id} was re-issued "
                            f"(v{old_geo.version}→v{new_geo.version}); it still binds at the new "
                            "position — re-confirm the reading"
                        ),
                        detail={
                            "old_version": old_geo.version,
                            "new_version": new_geo.version,
                            "from_axis": old.axis,
                            "to_axis": new.axis,
                            "from_m": old.offset.si_mag,
                            "to_m": new.offset.si_mag,
                        },
                    )
                )
    return warnings
