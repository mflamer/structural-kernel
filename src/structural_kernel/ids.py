"""Stable identities: ULID decision ids and sha256 content addresses.

Design doc 0001 §2.1: everything in the store has both a stable identity
(``did`` for decisions) and a content address (``sha256:...`` over canonical
JSON). Both travel as validated strings — opaque, language-neutral, greppable.
"""

from __future__ import annotations

import os
import time
from typing import Annotated, Final

from pydantic import StringConstraints

# Crockford base32, as used by ULID (no I, L, O, U).
_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

ULID_PATTERN: Final = r"^[0-9A-HJKMNP-TV-Z]{26}$"
HASH_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
LINE_ID_PATTERN: Final = r"^L[0-9A-HJKMNP-TV-Z]{8}$"

Did = Annotated[str, StringConstraints(pattern=ULID_PATTERN)]
ObjectHash = Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
# Stable grid-line identity (ADR 0005): minted when the line is created, never
# renamed, and the only thing an eid anchor may embed. Display names live
# beside it as mutable presentation fields.
LineId = Annotated[str, StringConstraints(pattern=LINE_ID_PATTERN)]


def new_ulid(timestamp_ms: int | None = None) -> str:
    """Mint a ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32.

    Only *kernel* code mints ids (decisions are created through changesets);
    derivation never calls this — derived identity is computed, not minted
    (ADR 0005).
    """
    ts = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
    if not 0 <= ts < 1 << 48:
        raise ValueError(f"timestamp out of ULID range: {ts}")
    value = (ts << 80) | int.from_bytes(os.urandom(10))
    return "".join(_CROCKFORD[(value >> (i * 5)) & 0x1F] for i in range(125, -1, -5))


def new_line_id() -> str:
    """Mint a stable grid-line id. Kernel-side only, like ``new_ulid``."""
    return "L" + "".join(_CROCKFORD[b % 32] for b in os.urandom(8))
