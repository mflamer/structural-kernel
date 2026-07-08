"""Xara adapter: the blessed engine behind the solver seam (ADR 0003).

Translates the §7.1 artifact into a xara (OpenSeesRT) model via the shared
planar idealization and translates results and engine noise back into our
schemas and failure taxonomy. Import-guarded: xara ships no Windows binaries
as of 2026-07, so ``xara_available()`` gates construction and the
verification suite skips these paths where the native runtime is absent.

xara publishes no type stubs; the unknown-type strictness relaxations below
are scoped to this adapter boundary only (the rest of the kernel stays fully
strict), and everything crossing back out is validated into our schemas.
"""

# pyright: reportMissingImports=false, reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING, Any

from structural_kernel.planar import (
    PlanarComponent,
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

if TYPE_CHECKING:
    from structural_kernel.derivation import AnalysisModel


def xara_available() -> bool:
    try:
        import xara
    except Exception:
        return False
    return callable(getattr(xara, "Model", None))


class XaraEngine:
    """EngineAdapter backed by xara's OpenSeesPy-compatible API."""

    def __init__(self) -> None:
        if not xara_available():
            raise RuntimeError(
                "xara's native runtime is not available on this platform "
                "(install the 'xara' extra on Linux, or run in a container)"
            )
        import xara

        self._xara = xara

    @property
    def info(self) -> EngineInfo:
        try:
            version = importlib.metadata.version("xara")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return EngineInfo(name="xara", version=version, fidelity="verification")

    def solve(self, artifact: AnalysisModel) -> SolveResult:
        combos = [
            ComboResult(combo=combo.name, displacements=[], reactions=[], members=[])
            for combo in artifact.combos
        ]
        try:
            components = build_components(artifact)
            for component in components:
                for combo, combo_result in zip(artifact.combos, combos, strict=True):
                    self._solve_component(component, combo.factors, combo_result)
        except UnsupportedArtifactError as exc:
            return self._failed("invalid_artifact", str(exc))
        except _AnalysisFailed as exc:
            return self._failed("singular_system", str(exc))
        return SolveResult(artifact="unset", engine=self.info, status="solved", combos=combos)

    def _failed(self, code: str, message: str) -> SolveResult:
        return SolveResult(
            artifact="unset",
            engine=self.info,
            status="failed",
            failure=SolveFailure.model_validate({"code": code, "message": message}),
        )

    def _solve_component(
        self, component: PlanarComponent, factors: dict[str, float], out: ComboResult
    ) -> None:
        model: Any = self._xara.Model(ndm=2, ndf=3)
        for index, s in enumerate(component.coords):
            model.node(index + 1, (s, 0.0))
        fixes: dict[int, list[int]] = {}
        for dof in component.fixed_dofs:
            fixes.setdefault(dof // 3, [0, 0, 0])[dof % 3] = 1
        for node_index_, fix in sorted(fixes.items()):
            model.fix(node_index_ + 1, tuple(fix))

        model.geomTransf("Linear", 1)
        for tag, segment in enumerate(component.segments, start=1):
            element = segment.element
            model.element(
                "ElasticBeamColumn",
                tag,
                (segment.node_a + 1, segment.node_b + 1),
                element.A_m2,
                element.E_pa,
                element.I_strong_m4,
                transform=1,
            )

        model.pattern("Plain", 1, "Constant")
        for tag, segment in enumerate(component.segments, start=1):
            w = combo_w(segment, factors)
            if w:
                model.eleLoad("-ele", tag, "-type", "-beamUniform", w, pattern=1)
        for case, loads in component.point_loads.items():
            factor = factors.get(case, 0.0)
            for dof, value in loads:
                if factor and dof % 3 == 1:
                    model.load(dof // 3 + 1, (0.0, factor * value, 0.0), pattern=1)

        model.system("BandGen")
        model.numberer("RCM")
        model.constraints("Plain")
        model.integrator("LoadControl", 1.0)
        model.algorithm("Linear")
        model.analysis("Static")
        if model.analyze(1) != 0:
            raise _AnalysisFailed("xara static analysis did not converge (analyze != 0)")
        model.reactions()

        id_by_index = {index: node_id for node_id, index in component.node_index.items()}
        for node_index_, node_id in sorted(id_by_index.items()):
            du, dv, dr = model.nodeDisp(node_index_ + 1)
            u_m = (du, 0.0, dv) if component.axis == "x" else (0.0, du, dv)
            r_rad = (0.0, dr, 0.0) if component.axis == "x" else (dr, 0.0, 0.0)
            out.displacements.append(NodalDisplacement(node=node_id, u_m=u_m, r_rad=r_rad))
            if node_index_ in fixes:
                f_u, f_v, m = model.nodeReaction(node_index_ + 1)
                f_n = (f_u, 0.0, f_v) if component.axis == "x" else (0.0, f_u, f_v)
                m_nm = (0.0, m, 0.0) if component.axis == "x" else (m, 0.0, 0.0)
                out.reactions.append(Reaction(node=node_id, f_n=f_n, m_nm=m_nm))

        self._recover_members(model, component, factors, out)

    def _recover_members(
        self,
        model: Any,
        component: PlanarComponent,
        factors: dict[str, float],
        out: ComboResult,
    ) -> None:
        from structural_kernel.planar import NSEG

        segments_by_element: dict[str, list[tuple[int, Any]]] = {}
        for tag, segment in enumerate(component.segments, start=1):
            segments_by_element.setdefault(segment.element.id, []).append((tag, segment))

        for element_id, tagged in sorted(segments_by_element.items()):
            tagged.sort(key=lambda pair: pair[1].index)
            source_eid = tagged[0][1].element.source_eid
            max_abs_m = 0.0
            max_abs_v = 0.0
            max_defl = 0.0
            end_i: EndForces | None = None
            end_j: EndForces | None = None
            for tag, segment in tagged:
                forces = model.eleForce(tag)  # (Fxa, Fya, Ma, Fxb, Fyb, Mb)
                fya, ma = forces[1], forces[2]
                w = combo_w(segment, factors)
                length = segment.length
                # portion equilibrium: M(x) = -Ma + Fya x + w x^2/2
                candidates_m = [abs(ma), abs(-ma + fya * length + w * length**2 / 2)]
                if w:
                    x_star = -fya / w
                    if 0.0 < x_star < length:
                        candidates_m.append(abs(-ma + fya * x_star + w * x_star**2 / 2))
                max_abs_m = max(max_abs_m, *candidates_m)
                max_abs_v = max(max_abs_v, abs(fya), abs(fya + w * length))
                for node in (segment.node_a, segment.node_b):
                    max_defl = max(max_defl, abs(model.nodeDisp(node + 1)[1]))
                if segment.index == 0:
                    end_i = EndForces(axial_n=forces[0], shear_n=forces[1], moment_nm=forces[2])
                if segment.index == NSEG - 1:
                    end_j = EndForces(axial_n=forces[3], shear_n=forces[4], moment_nm=forces[5])
            assert end_i is not None and end_j is not None
            out.members.append(
                MemberForces(
                    element=element_id,
                    source_eid=source_eid,
                    end_i=end_i,
                    end_j=end_j,
                    max_abs_moment_nm=max_abs_m,
                    max_abs_shear_n=max_abs_v,
                    max_deflection_m=max_defl,
                )
            )


class _AnalysisFailed(Exception):
    pass
