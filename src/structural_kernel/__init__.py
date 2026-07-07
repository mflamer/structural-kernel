"""structural-kernel: AI-native structural building model kernel.

The canonical model is a versioned graph of design decisions; everything else
is derived. See docs/kickoff.md (charter) and docs/design/0001 (architecture).
"""

from structural_kernel.canonical import canonical_bytes, content_hash, model_document
from structural_kernel.ids import Did, ObjectHash, new_ulid
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

__version__ = "0.0.1"

__all__ = [
    "Author",
    "Changeset",
    "ChangesetOp",
    "Commit",
    "Decision",
    "DecisionKind",
    "Did",
    "Dimension",
    "DimensionError",
    "FileStore",
    "IntentInstance",
    "ObjectHash",
    "Override",
    "OverrideSet",
    "Quantity",
    "Snapshot",
    "StaleBaseError",
    "StoreError",
    "__version__",
    "canonical_bytes",
    "content_hash",
    "convert",
    "model_document",
    "new_ulid",
    "parse_quantity",
]
