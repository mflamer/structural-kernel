"""Content-addressed store: round trips, dedup, integrity, CAS refs."""

from pathlib import Path

import pytest
from pydantic import JsonValue

from structural_kernel.store import (
    CorruptObjectError,
    FileStore,
    ObjectNotFoundError,
    StaleBaseError,
)

DOC: JsonValue = {"schema_version": 1, "kind": "grid", "title": "test"}


def test_put_get_round_trip(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    h = store.put(DOC)
    assert store.get(h) == DOC
    assert h in store


def test_identical_content_deduplicates(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    h1 = store.put({"a": 1, "b": 2})
    h2 = store.put({"b": 2, "a": 1})  # same document, different insertion order
    assert h1 == h2
    object_files = [p for p in (tmp_path / "objects").rglob("*") if p.is_file()]
    assert len(object_files) == 1


def test_get_missing_raises(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        store.get("sha256:" + "0" * 64)


def test_tampered_object_is_detected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    h = store.put(DOC)
    [path] = [p for p in (tmp_path / "objects").rglob("*") if p.is_file()]
    path.write_bytes(b'{"tampered":true}')
    with pytest.raises(CorruptObjectError):
        store.get(h)


def test_invalid_hash_format_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    with pytest.raises(ValueError, match="not a valid object hash"):
        store.get("md5:abc")


def test_ref_lifecycle_and_cas(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    h1 = store.put({"n": 1})
    h2 = store.put({"n": 2})

    assert store.read_ref("main") is None
    store.compare_and_swap("main", None, h1)
    assert store.read_ref("main") == h1

    # stale expected value: first commit wins, second gets StaleBaseError
    with pytest.raises(StaleBaseError):
        store.compare_and_swap("main", None, h2)
    store.compare_and_swap("main", h1, h2)
    assert store.read_ref("main") == h2


def test_ref_names_are_pathlike_but_validated(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    h = store.put({"n": 1})
    store.compare_and_swap("expl/01JEX/g0", None, h)
    assert store.read_ref("expl/01JEX/g0") == h
    for bad in ("../evil", "a//b", "/abs", ".hidden", "a/../b", ""):
        with pytest.raises(ValueError, match="invalid ref name"):
            store.read_ref(bad)


def test_objects_are_stored_as_canonical_bytes(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    store.put({"b": 1, "a": 2})
    [path] = [p for p in (tmp_path / "objects").rglob("*") if p.is_file()]
    assert path.read_bytes() == b'{"a":2,"b":1}'
