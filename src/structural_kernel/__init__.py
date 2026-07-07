"""structural-kernel: AI-native structural building model kernel.

The canonical model is a versioned graph of design decisions; everything else
is derived. See docs/kickoff.md (charter) and docs/design/0001 (architecture).
"""

from structural_kernel.canonical import canonical_bytes, content_hash, model_document
from structural_kernel.decisions import DecisionParams, parse_params
from structural_kernel.ids import Did, LineId, ObjectHash, new_line_id, new_ulid
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
from structural_kernel.store import FileStore, StaleBaseError, StoreError
from structural_kernel.units import Dimension, DimensionError, Quantity, convert, parse_quantity
from structural_kernel.validation import ValidationIssue, ValidationReport

__version__ = "0.0.1"

__all__ = [
    "Author",
    "Changeset",
    "ChangesetOp",
    "Commit",
    "Decision",
    "DecisionKind",
    "DecisionParams",
    "Did",
    "Dimension",
    "DimensionError",
    "FileStore",
    "IntentInstance",
    "LineId",
    "ObjectHash",
    "Override",
    "OverrideSet",
    "ProposeResult",
    "Quantity",
    "Snapshot",
    "StaleBaseError",
    "StoreError",
    "ValidationIssue",
    "ValidationReport",
    "__version__",
    "canonical_bytes",
    "content_hash",
    "convert",
    "model_document",
    "new_line_id",
    "new_ulid",
    "parse_params",
    "parse_quantity",
    "propose",
]
