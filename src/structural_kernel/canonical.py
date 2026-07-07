"""Canonical JSON encoding and content addressing (design doc 0001 §2.1).

Two identical documents must share one content address: sorted keys, minimal
separators, UTF-8, no NaN/Infinity. The persisted schema is language-neutral —
nothing here another language couldn't reproduce from this docstring.

Float note: Python's ``json`` emits the shortest round-tripping decimal
representation (IEEE-754 double). Any reimplementation must match that
(Ryū/Grisu "shortest repr"), or hashes diverge.
"""

from __future__ import annotations

import hashlib
import json
from typing import cast

from pydantic import BaseModel, JsonValue


def canonical_bytes(doc: JsonValue) -> bytes:
    """Encode a JSON document to its single canonical byte representation."""
    return json.dumps(
        doc,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def content_hash(doc: JsonValue) -> str:
    """The content address of a JSON document."""
    return hash_bytes(canonical_bytes(doc))


def model_document(model: BaseModel) -> dict[str, JsonValue]:
    """A persisted object's JSON document form — what gets encoded and hashed."""
    return cast("dict[str, JsonValue]", model.model_dump(mode="json"))
