"""Solver service: stateless, batch-oriented, cloud-shaped (design doc 0001 §7.2).

The interface is the contract; the phase-1 implementation runs engines
in-process behind it, and a queue + container fleet implements the same
surface later. A failed solve is data, not an exception — explorations must
rank around failures — and every result carries its engine's class and
fidelity (ADR 0003 / standing requirement 9): only verification-grade results
may feed design checks and the engineer-of-record record.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field

from structural_kernel.canonical import content_hash, model_document
from structural_kernel.objects import KernelModel

if TYPE_CHECKING:
    from structural_kernel.derivation import AnalysisModel

FailureCode = Literal[
    "mechanism_detected",
    "singular_system",
    "invalid_artifact",
    "worker_crash",
]


class SolveFailure(KernelModel):
    code: FailureCode
    message: str


class EngineInfo(KernelModel):
    name: str
    version: str
    fidelity: Literal["verification", "screening"]


class NodalDisplacement(KernelModel):
    node: str
    u_m: tuple[float, float, float]  # global translations
    r_rad: tuple[float, float, float]


class Reaction(KernelModel):
    node: str
    f_n: tuple[float, float, float]
    m_nm: tuple[float, float, float]


class EndForces(KernelModel):
    axial_n: float
    shear_n: float
    moment_nm: float


class MemberForces(KernelModel):
    element: str
    source_eid: str
    end_i: EndForces
    end_j: EndForces
    max_abs_moment_nm: float  # interpolated extremum, not just end values
    max_abs_shear_n: float
    max_deflection_m: float  # peak transverse deflection along the member


class ComboResult(KernelModel):
    combo: str
    displacements: list[NodalDisplacement]
    reactions: list[Reaction]
    members: list[MemberForces]


class SolveResult(KernelModel):
    """Per artifact. ``artifact`` is the content address of the analysis model
    (§2.1), which is how results re-attach to the derived model."""

    schema_version: Literal[1] = 1
    artifact: str
    engine: EngineInfo
    status: Literal["solved", "failed"]
    failure: SolveFailure | None = None
    combos: list[ComboResult] = Field(default_factory=list[ComboResult])
    wall_time_s: float | None = None


class EngineAdapter(Protocol):
    """The pluggable engine seam. Adapters translate the artifact into engine
    idiom and engine output/noise back into our schemas and failure taxonomy —
    an engine-ism leaking past this boundary is a defect (ADR 0003)."""

    @property
    def info(self) -> EngineInfo: ...

    def solve(self, artifact: AnalysisModel) -> SolveResult: ...


JobState = Literal["pending", "running", "done", "failed"]


class JobStatus(KernelModel):
    job_id: str
    per_artifact: dict[str, JobState]  # keyed by artifact content address


class LocalSolverService:
    """Phase-1 stand-in for the fleet: same interface, in-process execution.

    ``submit`` solves eagerly (a local worker has no queue worth simulating);
    dispatching 500 artifacts is the same call as dispatching 1. An engine
    exception becomes a ``worker_crash`` result, never a raised error.
    """

    def __init__(self, engine: EngineAdapter) -> None:
        self._engine = engine
        self._jobs: dict[str, list[SolveResult]] = {}

    def submit(self, batch: Sequence[AnalysisModel]) -> str:
        job_id = f"job-{len(self._jobs) + 1}"
        results: list[SolveResult] = []
        for artifact in batch:
            artifact_hash = content_hash(model_document(artifact))
            started = time.perf_counter()
            try:
                result = self._engine.solve(artifact)
            except Exception as exc:
                result = SolveResult(
                    artifact=artifact_hash,
                    engine=self._engine.info,
                    status="failed",
                    failure=SolveFailure(
                        code="worker_crash", message=f"{type(exc).__name__}: {exc}"
                    ),
                )
            result = result.model_copy(
                update={
                    "artifact": artifact_hash,
                    "wall_time_s": time.perf_counter() - started,
                }
            )
            results.append(result)
        self._jobs[job_id] = results
        return job_id

    def status(self, job_id: str) -> JobStatus:
        results = self._require(job_id)
        return JobStatus(
            job_id=job_id,
            per_artifact={
                r.artifact: ("done" if r.status == "solved" else "failed") for r in results
            },
        )

    def results(self, job_id: str) -> list[SolveResult]:
        return list(self._require(job_id))

    def _require(self, job_id: str) -> list[SolveResult]:
        results = self._jobs.get(job_id)
        if results is None:
            raise KeyError(f"unknown job: {job_id}")
        return results
