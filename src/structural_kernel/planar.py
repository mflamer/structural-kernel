"""Planar idealization of the §7.1 artifact, shared by engine adapters.

Phase-1 artifacts contain axis-aligned horizontal members under vertical
loads (derivation's documented idealization). This module maps an artifact
into connected planar components — subdivided member chains with loads and
supports in (s, z) coordinates — which each engine then solves in its own
idiom. Artifacts outside these patterns raise ``UnsupportedArtifactError``,
which adapters map to the ``invalid_artifact`` failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from structural_kernel.derivation import AnalysisElement, AnalysisModel

# Segments per member. Nodal displacements are exact for cubic-Hermite
# elements with consistent fixed-end forces; subdivision exists purely so
# deflection *extrema* are sampled densely enough — 16 keeps the worst-case
# sampling error (peak between nodes) inside the 0.5% verification tolerance.
NSEG = 16
_EPS = 1e-9


class UnsupportedArtifactError(Exception):
    """The artifact uses patterns this planar idealization cannot represent."""


@dataclass
class Segment:
    element: AnalysisElement
    index: int  # 0-based within the element
    node_a: int  # plane-node indices
    node_b: int
    length: float
    w_by_case: dict[str, float] = field(default_factory=dict[str, float])


@dataclass
class PlanarComponent:
    axis: str  # "x" or "y": the global axis members run along
    node_index: dict[str, int]  # artifact node id -> plane-node index
    coords: list[float]  # s-coordinate per plane node
    segments: list[Segment]
    fixed_dofs: set[int]  # 3 DOFs per plane node: (u, v, theta)
    point_loads: dict[str, list[tuple[int, float]]]  # case -> [(dof, value)]


def build_components(artifact: AnalysisModel) -> list[PlanarComponent]:
    xyz = {node.id: node.xyz_m for node in artifact.nodes}

    parent: dict[str, str] = {e.id: e.id for e in artifact.elements}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    by_node: dict[str, list[str]] = {}
    for element in artifact.elements:
        for node in element.nodes:
            by_node.setdefault(node, []).append(element.id)
    for element_ids in by_node.values():
        root = find(element_ids[0])
        for other in element_ids[1:]:
            parent[find(other)] = root

    grouped: dict[str, list[AnalysisElement]] = {}
    for element in artifact.elements:
        grouped.setdefault(find(element.id), []).append(element)

    return [_build_component(artifact, elements, xyz) for elements in grouped.values()]


def _build_component(
    artifact: AnalysisModel,
    elements: list[AnalysisElement],
    xyz: dict[str, tuple[float, float, float]],
) -> PlanarComponent:
    axis = ""
    for element in elements:
        a, b = (xyz[n] for n in element.nodes)
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        if abs(dz) > _EPS or (abs(dx) > _EPS and abs(dy) > _EPS):
            raise UnsupportedArtifactError(f"element {element.id}: not axis-aligned horizontal")
        element_axis = "x" if abs(dx) > _EPS else "y"
        direction = dx if element_axis == "x" else dy
        if direction <= 0:
            raise UnsupportedArtifactError(f"element {element.id}: must run low-to-high")
        if axis and element_axis != axis:
            raise UnsupportedArtifactError("component mixes member axes")
        axis = element_axis

    def s_of(node: str) -> float:
        p = xyz[node]
        return p[0] if axis == "x" else p[1]

    node_index: dict[str, int] = {}
    coords: list[float] = []

    def plane_node(s: float) -> int:
        for i, existing in enumerate(coords):
            if abs(existing - s) < _EPS:
                return i
        coords.append(s)
        return len(coords) - 1

    segments: list[Segment] = []
    for element in sorted(elements, key=lambda e: e.id):
        node_i, node_j = element.nodes
        s_i, s_j = s_of(node_i), s_of(node_j)
        node_index[node_i] = plane_node(s_i)
        node_index[node_j] = plane_node(s_j)
        length = (s_j - s_i) / NSEG
        previous = node_index[node_i]
        for k in range(NSEG):
            nxt = node_index[node_j] if k == NSEG - 1 else plane_node(s_i + (k + 1) * length)
            segments.append(
                Segment(element=element, index=k, node_a=previous, node_b=nxt, length=length)
            )
            previous = nxt

    point_loads: dict[str, list[tuple[int, float]]] = {}
    segment_by_element: dict[str, list[Segment]] = {}
    for segment in segments:
        segment_by_element.setdefault(segment.element.id, []).append(segment)
    element_ids = {e.id for e in elements}
    for load in artifact.loads:
        if load.element not in element_ids:
            continue
        if load.kind == "line":
            wx, wy, wz = load.w_n_per_m
            if abs(wx) > _EPS or abs(wy) > _EPS:
                raise UnsupportedArtifactError("only vertical line loads are supported")
            for segment in segment_by_element[load.element]:
                segment.w_by_case[load.case] = segment.w_by_case.get(load.case, 0.0) + wz
        else:
            px, py, pz = load.p_n
            if abs(px) > _EPS or abs(py) > _EPS:
                raise UnsupportedArtifactError("only vertical point loads are supported")
            slot = load.position * NSEG
            if abs(slot - round(slot)) > 1e-6:
                raise UnsupportedArtifactError(
                    f"point load at position {load.position} does not land on a "
                    f"subdivision node (NSEG={NSEG})"
                )
            chain = sorted(segment_by_element[load.element], key=lambda s: s.index)
            slot_index = round(slot)
            node = chain[0].node_a if slot_index == 0 else chain[slot_index - 1].node_b
            point_loads.setdefault(load.case, []).append((3 * node + 1, pz))

    # supports: map the global 6-DOF fix array into the plane (u, v, theta)
    fixed: set[int] = set()
    for support in artifact.supports:
        if support.node not in node_index:
            continue
        n = node_index[support.node]
        fix = support.fix
        u_fixed = fix[0] if axis == "x" else fix[1]
        rot_fixed = fix[4] if axis == "x" else fix[3]
        if u_fixed:
            fixed.add(3 * n)
        if fix[2]:
            fixed.add(3 * n + 1)
        if rot_fixed:
            fixed.add(3 * n + 2)

    return PlanarComponent(
        axis=axis,
        node_index=node_index,
        coords=coords,
        segments=segments,
        fixed_dofs=fixed,
        point_loads=point_loads,
    )


def combo_w(segment: Segment, factors: dict[str, float]) -> float:
    """The factored uniform load on a segment for one combo."""
    return sum(factors.get(case, 0.0) * w for case, w in segment.w_by_case.items())
