"""structural-kernel: AI-native structural building model kernel.

The canonical model is a versioned graph of design decisions; everything else
is derived. See docs/kickoff.md (charter) and docs/design/0001 (architecture).
"""

from structural_kernel.canonical import canonical_bytes, content_hash, model_document
from structural_kernel.decisions import DecisionParams, parse_params
from structural_kernel.derivation import (
    DERIVATION_VERSION,
    AnalysisModel,
    DerivationError,
    DerivedModel,
    OverrideAttachment,
    derive,
)
from structural_kernel.design_checks import (
    DesignCheck,
    DesignCheckReport,
    run_design_checks,
)
from structural_kernel.eids import render_eid
from structural_kernel.explorations import (
    Exploration,
    ExplorationBudget,
    GridSweepProposer,
    Objective,
    Proposer,
    StubLLMProposer,
    evaluate,
    run_exploration,
)
from structural_kernel.ids import Did, LineId, ObjectHash, new_line_id, new_ulid
from structural_kernel.intents import REGISTRY, IntentViolation, check_intent
from structural_kernel.kernel import ProposeResult, load_snapshot, propose
from structural_kernel.materials import (
    ENGINES,
    MaterialEngine,
    MemberCheckData,
    engine_for,
    families,
)
from structural_kernel.objects import (
    Author,
    Changeset,
    ChangesetOp,
    Commit,
    Decision,
    DecisionKind,
    IntentInstance,
    Override,
    OverrideSet,
    Snapshot,
)
from structural_kernel.queries import best_variant, header_for_opening, what_carries, why
from structural_kernel.solver import (
    EngineAdapter,
    EngineInfo,
    LocalSolverService,
    SolveFailure,
    SolveResult,
)
from structural_kernel.store import FileStore, StaleBaseError, StoreError
from structural_kernel.units import Dimension, DimensionError, Quantity, convert, parse_quantity
from structural_kernel.validation import ValidationIssue, ValidationReport
from structural_kernel.xara_adapter import XaraEngine, xara_available

__version__ = "0.0.1"

__all__ = [
    "DERIVATION_VERSION",
    "ENGINES",
    "REGISTRY",
    "AnalysisModel",
    "Author",
    "Changeset",
    "ChangesetOp",
    "Commit",
    "Decision",
    "DecisionKind",
    "DecisionParams",
    "DerivationError",
    "DerivedModel",
    "DesignCheck",
    "DesignCheckReport",
    "Did",
    "Dimension",
    "DimensionError",
    "EngineAdapter",
    "EngineInfo",
    "Exploration",
    "ExplorationBudget",
    "FileStore",
    "GridSweepProposer",
    "IntentInstance",
    "IntentViolation",
    "LineId",
    "LocalSolverService",
    "MaterialEngine",
    "MemberCheckData",
    "ObjectHash",
    "Objective",
    "Override",
    "OverrideAttachment",
    "OverrideSet",
    "ProposeResult",
    "Proposer",
    "Quantity",
    "Snapshot",
    "SolveFailure",
    "SolveResult",
    "StaleBaseError",
    "StoreError",
    "StubLLMProposer",
    "ValidationIssue",
    "ValidationReport",
    "XaraEngine",
    "__version__",
    "best_variant",
    "canonical_bytes",
    "check_intent",
    "content_hash",
    "convert",
    "derive",
    "engine_for",
    "evaluate",
    "families",
    "header_for_opening",
    "load_snapshot",
    "model_document",
    "new_line_id",
    "new_ulid",
    "parse_params",
    "parse_quantity",
    "propose",
    "render_eid",
    "run_design_checks",
    "run_exploration",
    "what_carries",
    "why",
    "xara_available",
]
