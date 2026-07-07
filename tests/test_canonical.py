"""Canonical encoding: one document, one byte string, one hash."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from structural_kernel.canonical import canonical_bytes, content_hash


def test_known_encoding_vector() -> None:
    doc: JsonValue = {"b": 1, "a": [1, 2], "c": {"y": None, "x": True}}
    assert canonical_bytes(doc) == b'{"a":[1,2],"b":1,"c":{"x":true,"y":null}}'


def test_key_insertion_order_does_not_change_the_hash() -> None:
    forward: JsonValue = {"a": 1, "b": {"c": 2, "d": 3}}
    backward: JsonValue = {"b": {"d": 3, "c": 2}, "a": 1}
    assert content_hash(forward) == content_hash(backward)


def test_hash_format() -> None:
    h = content_hash({"schema_version": 1})
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_non_ascii_is_utf8_not_escaped() -> None:
    assert canonical_bytes({"note": "N·m"}) == '{"note":"N·m"}'.encode()


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_bytes({"x": float("nan")})


_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20)
)
_json_docs = st.recursive(
    _scalars,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=25,
)


@given(doc=_json_docs)
def test_encoding_is_deterministic(doc: JsonValue) -> None:
    assert canonical_bytes(doc) == canonical_bytes(doc)


def _reinsert_reversed(doc: JsonValue) -> JsonValue:
    if isinstance(doc, dict):
        return {k: _reinsert_reversed(doc[k]) for k in reversed(list(doc))}
    if isinstance(doc, list):
        return [_reinsert_reversed(v) for v in doc]
    return doc


@given(doc=_json_docs)
def test_encoding_is_insertion_order_invariant(doc: JsonValue) -> None:
    assert canonical_bytes(doc) == canonical_bytes(_reinsert_reversed(doc))
