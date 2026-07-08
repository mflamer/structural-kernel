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
from structural_kernel.ids import Did, LineId, ObjectHash, new_line_id, new_ulid
from structural_kernel.intents import REGISTRY, IntentViolation, check_intent
from structural_kernel.kernel import ProposeResult, propose
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
    "FileStore",
    "IntentInstance",
    "IntentViolation",
    "LineId",
    "LocalSolverService",
    "ObjectHash",
    "Override",
    "OverrideAttachment",
    "OverrideSet",
    "ProposeResult",
    "Quantity",
    "Snapshot",
    "SolveFailure",
    "SolveResult",
    "StaleBaseError",
    "StoreError",
    "ValidationIssue",
    "ValidationReport",
    "XaraEngine",
    "__version__",
    "canonical_bytes",
    "check_intent",
    "content_hash",
    "convert",
    "derive",
    "model_document",
    "new_line_id",
    "new_ulid",
    "parse_params",
    "parse_quantity",
    "propose",
    "render_eid",
    "run_design_checks",
    "xara_available",
]
