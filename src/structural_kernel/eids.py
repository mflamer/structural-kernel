"""The ADR 0005 eid grammar: rule-relative identity paths.

An eid is a ``/``-separated path of ``{role}:{inducer}:{anchor}`` segments.
Anchors embed stable identities only — line-ids, topological names, ordinals —
never coordinates and never display names (E1). The canonical form defined
here is what is persisted, hashed, and referenced; ``render_eid`` is the
human-rendering transform (display names substituted at the presentation
boundary, exactly like units).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from structural_kernel.ids import LINE_ID_PATTERN, ULID_PATTERN

_ROLE_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
_ANCHOR_RE: Final = re.compile(r"^[0-9A-Za-z._+-]+$")
_SEGMENT_RE: Final = re.compile(
    rf"^[a-z][a-z0-9_]{{0,15}}:({ULID_PATTERN[1:-1]}):[0-9A-Za-z._+-]+$"
)
_LINE_ID_RE: Final = re.compile(LINE_ID_PATTERN[1:-1])


def segment(role: str, inducer: str, anchor: str) -> str:
    """Compose one canonical eid segment. Raises on grammar violations —
    derivation code minting a malformed eid is a kernel bug, not user error."""
    if _ROLE_RE.match(role) is None:
        raise ValueError(f"invalid eid role: {role!r}")
    if _ANCHOR_RE.match(anchor) is None:
        raise ValueError(f"invalid eid anchor: {anchor!r}")
    eid = f"{role}:{inducer}:{anchor}"
    if _SEGMENT_RE.match(eid) is None:
        raise ValueError(f"invalid eid segment: {eid!r}")
    return eid


def child_eid(parent: str, role: str, inducer: str, anchor: str) -> str:
    """Extend a path: every prefix of a valid eid is the parent element's eid.
    (Deeper levels of detail extend paths; they never rewrite them.)"""
    return f"{parent}/{segment(role, inducer, anchor)}"


def render_eid(eid: str, display_names: Mapping[str, str]) -> str:
    """The rendered (human) form: line-id tokens replaced by display names.

    Presentation only — the result is never persisted and never referenced.
    Unknown tokens pass through unchanged.
    """
    return _LINE_ID_RE.sub(lambda m: display_names.get(m.group(0), m.group(0)), eid)
