"""Content-addressed object store and transactional refs (design doc 0001 §2.2).

Objects are immutable JSON documents keyed by the sha256 of their canonical
bytes; writing the same content twice is a no-op (deduplication is free).
Branches are named refs living *outside* the content-addressed space, updated
by compare-and-swap: first commit wins, the second gets ``StaleBaseError`` and
rebases. On-disk layout is deliberately git-like and inspectable:

    <root>/objects/<2-hex>/<62-hex>   canonical bytes of one object
    <root>/refs/<name>                current object hash, one line

The kernel's storage interface is this class's public surface; a cloud
database implements the same surface later (charter non-goal: no multi-tenant
deploy yet, but stay cloud-shaped).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

from structural_kernel.canonical import canonical_bytes, hash_bytes, model_document

if TYPE_CHECKING:
    from pydantic import BaseModel, JsonValue


class StoreError(Exception):
    """Base for storage failures."""


class ObjectNotFoundError(StoreError):
    pass


class CorruptObjectError(StoreError):
    """Stored bytes no longer hash to their address — storage integrity failure."""


class StaleBaseError(StoreError):
    """Compare-and-swap lost: the ref moved since the expected value was read."""


class RefLockTimeoutError(StoreError):
    pass


_HASH_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
# Ref names: git-like path segments; no empty segments, no dot-prefixed
# segments (which also rules out "." and ".." traversal).
_REF_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_REF_NAME_RE = re.compile(rf"^{_REF_SEGMENT}(/{_REF_SEGMENT})*$")


def _hex_of(object_hash: str) -> str:
    m = _HASH_RE.match(object_hash)
    if m is None:
        raise ValueError(f"not a valid object hash: {object_hash!r}")
    return m.group(1)


class FileStore:
    """Phase-1 on-disk implementation of the storage interface."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._objects = root / "objects"
        self._refs = root / "refs"
        self._ref_lock = root / "refs.lock"
        self._objects.mkdir(parents=True, exist_ok=True)
        self._refs.mkdir(parents=True, exist_ok=True)

    # -- objects (immutable, content-addressed) -----------------------------

    def put(self, doc: JsonValue) -> str:
        """Write a JSON document; returns its content address. Idempotent."""
        data = canonical_bytes(doc)
        object_hash = hash_bytes(data)
        path = self._object_path(object_hash)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_atomic(path, data)
        return object_hash

    def get(self, object_hash: str) -> JsonValue:
        """Read a document by content address, verifying integrity."""
        path = self._object_path(object_hash)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ObjectNotFoundError(object_hash) from None
        if hash_bytes(data) != object_hash:
            raise CorruptObjectError(f"{object_hash}: stored bytes do not hash to their address")
        return cast("JsonValue", json.loads(data))

    def __contains__(self, object_hash: str) -> bool:
        return self._object_path(object_hash).exists()

    def put_model(self, model: BaseModel) -> str:
        return self.put(model_document(model))

    def get_model[M: BaseModel](self, object_hash: str, model_type: type[M]) -> M:
        return model_type.model_validate(self.get(object_hash))

    # -- refs (mutable names, compare-and-swap) ------------------------------

    def read_ref(self, name: str) -> str | None:
        path = self._ref_path(name)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if _HASH_RE.match(value) is None:
            raise CorruptObjectError(f"ref {name!r} does not hold an object hash: {value!r}")
        return value

    def compare_and_swap(self, name: str, expected: str | None, new: str) -> None:
        """Advance a ref atomically. ``expected is None`` means 'must not exist'.

        Raises ``StaleBaseError`` if the ref moved — the caller rebases and
        retries; nothing is ever half-written.
        """
        _hex_of(new)  # validate format before taking the lock
        path = self._ref_path(name)
        self._acquire_ref_lock()
        try:
            current = self.read_ref(name)
            if current != expected:
                raise StaleBaseError(f"ref {name!r}: expected {expected!r}, found {current!r}")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_atomic(path, (new + "\n").encode("utf-8"))
        finally:
            self._release_ref_lock()

    # -- internals ------------------------------------------------------------

    def _object_path(self, object_hash: str) -> Path:
        hex_digest = _hex_of(object_hash)
        return self._objects / hex_digest[:2] / hex_digest[2:]

    def _ref_path(self, name: str) -> Path:
        if _REF_NAME_RE.match(name) is None:
            raise ValueError(f"invalid ref name: {name!r}")
        return self._refs.joinpath(*name.split("/"))

    def _write_atomic(self, path: Path, data: bytes) -> None:
        tmp = path.parent / f".tmp-{uuid.uuid4().hex}"
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _acquire_ref_lock(self, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fd = os.open(self._ref_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RefLockTimeoutError(str(self._ref_lock)) from None
                time.sleep(0.01)
            else:
                os.close(fd)
                return

    def _release_ref_lock(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._ref_lock)
