"""The direct-stiffness cross-check engine (ADR 0003: a test fixture, not a
service implementation).

A minimal 2D Euler-Bernoulli direct-stiffness solver over the shared planar
idealization (``structural_kernel.planar``). Members are exact cubic-Hermite
segments with consistent fixed-end forces, so nodal displacements are exact
and member extrema are recovered analytically per segment. It refuses what it
cannot do exactly — that refusal is what makes it a trustworthy second
opinion on the hand-calc fixtures.
"""

from __future__ import annotations

from structural_kernel.derivation import AnalysisElement, AnalysisModel
from structural_kernel.planar import (
    NSEG,
    PlanarComponent,
    Segment,
    UnsupportedArtifactError,
    build_components,
    combo_w,
)
from structural_kernel.solver import (
    ComboResult,
    EndForces,
    EngineInfo,
    MemberForces,
    NodalDisplacement,
    Reaction,
    SolveFailure,
    SolveResult,
)


class _Singular(Exception):
    pass


class ReferenceEngine:
    """EngineAdapter implementation used only by the verification suite."""

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(name="direct-stiffness-fixture", version="1", fidelity="verification")

    def solve(self, artifact: AnalysisModel) -> SolveResult:
        combos = [
            ComboResult(combo=combo.name, displacements=[], reactions=[], members=[])
            for combo in artifact.combos
        ]
        try:
            components = build_components(artifact)
            for component in components:
                for combo, combo_result in zip(artifact.combos, combos, strict=True):
                    _solve_component(component, combo.factors, combo_result)
        except UnsupportedArtifactError as exc:
            return _failed(self.info, "invalid_artifact", str(exc))
        except _Singular as exc:
            return _failed(self.info, "singular_system", str(exc))
        return SolveResult(artifact="unset", engine=self.info, status="solved", combos=combos)


def _failed(info: EngineInfo, code: str, message: str) -> SolveResult:
    return SolveResult(
        artifact="unset",
        engine=info,
        status="failed",
        failure=SolveFailure.model_validate({"code": code, "message": message}),
    )


def _segment_stiffness(e: AnalysisElement, length: float) -> list[list[float]]:
    ea = e.E_pa * e.A_m2 / length
    ei = e.E_pa * e.I_strong_m4
    l1, l2, l3 = length, length**2, length**3
    return [
        [ea, 0.0, 0.0, -ea, 0.0, 0.0],
        [0.0, 12 * ei / l3, 6 * ei / l2, 0.0, -12 * ei / l3, 6 * ei / l2],
        [0.0, 6 * ei / l2, 4 * ei / l1, 0.0, -6 * ei / l2, 2 * ei / l1],
        [-ea, 0.0, 0.0, ea, 0.0, 0.0],
        [0.0, -12 * ei / l3, -6 * ei / l2, 0.0, 12 * ei / l3, -6 * ei / l2],
        [0.0, 6 * ei / l2, 2 * ei / l1, 0.0, -6 * ei / l2, 4 * ei / l1],
    ]


def _segment_dofs(segment: Segment) -> list[int]:
    a, b = segment.node_a, segment.node_b
    return [3 * a, 3 * a + 1, 3 * a + 2, 3 * b, 3 * b + 1, 3 * b + 2]


def _solve_component(
    component: PlanarComponent, factors: dict[str, float], out: ComboResult
) -> None:
    n_dofs = 3 * len(component.coords)
    stiffness = [[0.0] * n_dofs for _ in range(n_dofs)]
    force = [0.0] * n_dofs

    for segment in component.segments:
        k = _segment_stiffness(segment.element, segment.length)
        dofs = _segment_dofs(segment)
        for i in range(6):
            for j in range(6):
                stiffness[dofs[i]][dofs[j]] += k[i][j]
        w = combo_w(segment, factors)
        if w:
            length = segment.length
            force[dofs[1]] += w * length / 2
            force[dofs[2]] += w * length**2 / 12
            force[dofs[4]] += w * length / 2
            force[dofs[5]] -= w * length**2 / 12
    for case, loads in component.point_loads.items():
        factor = factors.get(case, 0.0)
        for dof, value in loads:
            force[dof] += factor * value

    free = [d for d in range(n_dofs) if d not in component.fixed_dofs]
    reduced_k = [[stiffness[i][j] for j in free] for i in free]
    reduced_f = [force[i] for i in free]
    solution = _gauss_solve(reduced_k, reduced_f)
    u = [0.0] * n_dofs
    for dof, value in zip(free, solution, strict=True):
        u[dof] = value

    # reactions: R = K u - F at fixed DOFs
    reactions_by_node: dict[int, list[float]] = {}
    for dof in sorted(component.fixed_dofs):
        r = sum(stiffness[dof][j] * u[j] for j in range(n_dofs)) - force[dof]
        reactions_by_node.setdefault(dof // 3, [0.0, 0.0, 0.0])[dof % 3] = r

    id_by_index = {index: node_id for node_id, index in component.node_index.items()}
    for node_index_, values in sorted(reactions_by_node.items()):
        node_id = id_by_index.get(node_index_)
        if node_id is None:
            continue  # internal subdivision node (never supported)
        f_u, f_v, m = values
        f_n = (f_u, 0.0, f_v) if component.axis == "x" else (0.0, f_u, f_v)
        m_nm = (0.0, m, 0.0) if component.axis == "x" else (m, 0.0, 0.0)
        out.reactions.append(Reaction(node=node_id, f_n=f_n, m_nm=m_nm))

    for node_id, index in sorted(component.node_index.items()):
        du, dv, dr = u[3 * index], u[3 * index + 1], u[3 * index + 2]
        u_m = (du, 0.0, dv) if component.axis == "x" else (0.0, du, dv)
        r_rad = (0.0, dr, 0.0) if component.axis == "x" else (dr, 0.0, 0.0)
        out.displacements.append(NodalDisplacement(node=node_id, u_m=u_m, r_rad=r_rad))

    _recover_members(component, factors, u, out)


def _recover_members(
    component: PlanarComponent, factors: dict[str, float], u: list[float], out: ComboResult
) -> None:
    by_element: dict[str, list[Segment]] = {}
    for segment in component.segments:
        by_element.setdefault(segment.element.id, []).append(segment)

    for element_id, chain in sorted(by_element.items()):
        chain.sort(key=lambda s: s.index)
        element = chain[0].element
        max_abs_m = 0.0
        max_abs_v = 0.0
        max_defl = 0.0
        end_i: EndForces | None = None
        end_j: EndForces | None = None

        for segment in chain:
            dofs = _segment_dofs(segment)
            u_e = [u[d] for d in dofs]
            k = _segment_stiffness(segment.element, segment.length)
            w = combo_w(segment, factors)
            length = segment.length
            equivalent = [
                0.0,
                w * length / 2,
                w * length**2 / 12,
                0.0,
                w * length / 2,
                -(w * length**2) / 12,
            ]
            f = [sum(k[i][j] * u_e[j] for j in range(6)) - equivalent[i] for i in range(6)]
            # portion equilibrium: V(x) = -(Fya + w x); M(x) = -Ma + Fya x + w x^2/2
            fya, ma = f[1], f[2]
            candidates_v = [abs(fya), abs(fya + w * length)]
            candidates_m = [abs(ma), abs(-ma + fya * length + w * length**2 / 2)]
            if w:
                x_star = -fya / w
                if 0.0 < x_star < length:
                    candidates_m.append(abs(-ma + fya * x_star + w * x_star**2 / 2))
            max_abs_v = max(max_abs_v, *candidates_v)
            max_abs_m = max(max_abs_m, *candidates_m)
            max_defl = max(max_defl, abs(u_e[1]), abs(u_e[4]))

            if segment.index == 0:
                end_i = EndForces(axial_n=f[0], shear_n=f[1], moment_nm=f[2])
            if segment.index == NSEG - 1:
                end_j = EndForces(axial_n=f[3], shear_n=f[4], moment_nm=f[5])

        assert end_i is not None and end_j is not None
        out.members.append(
            MemberForces(
                element=element_id,
                source_eid=element.source_eid,
                end_i=end_i,
                end_j=end_j,
                max_abs_moment_nm=max_abs_m,
                max_abs_shear_n=max_abs_v,
                max_deflection_m=max_defl,
            )
        )


def _gauss_solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    a = [[*row, rhs[i]] for i, row in enumerate(matrix)]
    scale = max((abs(v) for row in matrix for v in row), default=1.0) or 1.0
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot_row][col]) < 1e-12 * scale:
            raise _Singular(f"singular stiffness matrix (pivot at DOF {col})")
        a[col], a[pivot_row] = a[pivot_row], a[col]
        pivot = a[col][col]
        for row in range(col + 1, n):
            factor = a[row][col] / pivot
            if factor:
                for j in range(col, n + 1):
                    a[row][j] -= factor * a[col][j]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (a[row][n] - sum(a[row][j] * x[j] for j in range(row + 1, n))) / a[row][row]
    return x
