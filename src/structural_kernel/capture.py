"""Conversational constraint capture (ADR 0011): a sentence becomes a typed,
enforced project constraint.

The vision's item 3 — "the west 40 feet needs to be column-free" becomes a
*typed, enforced* structural constraint without a form being filled in. This is
the AI surface for that: given the engineer's utterance and the model's grid
vocabulary, an :class:`LLMClient` (the ADR 0009 seam) chooses ``capture_*`` tool
calls, and this module turns each into an ordinary ``AddConstraint`` op that
authors a :class:`ProjectConstraint` — a standalone project-level constraint that
binds every future changeset and every exploration candidate, whether or not a
structural system has been chosen yet.

Propose-only, by construction (the charter's "AI never edits state directly"):
:meth:`ConstraintCapture.capture` returns *changeset ops*; the caller runs them
through the ordinary ``propose`` pipeline, where a malformed or non-registered
capture is a recorded rejection, never a silent write. The FakeLLMClient drives
tests/CI deterministically; the real AnthropicClient sits behind the same
protocol (the optional ``llm`` extra).

The captured constraint records the natural-language ``statement`` and the model
identity (``captured_by`` = the client descriptor) — the audit trail the vision
demands: "a structured rejection citing this conversation's decision". Capture
commits ``authored`` provenance; the ``inferred``→ratify ingestion seam is design
doc 0005's separate workstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import JsonValue

from structural_kernel.decisions import GridParams, parse_params
from structural_kernel.ids import new_ulid
from structural_kernel.llm import LLMClient, ToolInvocation, ToolSpec
from structural_kernel.objects import AddConstraint, ChangesetOp, Decision, ProjectConstraint

if TYPE_CHECKING:
    from structural_kernel.validation import ResolvedSnapshot


_CAPTURE_SYSTEM = (
    "You are the AI surface of a structural design tool. The engineer states a "
    "spatial constraint in plain language; your job is to capture it as a typed, "
    "enforceable project constraint by calling the capture_* tools — one call per "
    "distinct constraint. Do not invent constraints the engineer did not state, and "
    "do not capture geometry, loads, or a structural system (those are separate "
    "decisions). Reason about the grid you are given: each line has an axis (the "
    "coordinate it holds constant) and an offset. A clear-span region is a band "
    "measured off one anchor line; choose the anchor and the side so the protected "
    "strip matches what the engineer meant (e.g. 'the west 40 feet' is the 40 ft band "
    "on one side of the westmost line). If the engineer states nothing constraining, "
    "call no tools."
)

_CLEAR_SPAN_TOOL = ToolSpec(
    name="capture_clear_span",
    description=(
        "Capture a column-free / clear-span requirement over a band of the plan: no "
        "vertical support (post, column, or bearing wall) may land inside the band. The "
        "band is measured perpendicular from an anchor grid line and spans the full "
        "perpendicular depth of the building."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "statement": {
                "type": "string",
                "description": "The engineer's constraint, restated in one sentence.",
            },
            "anchor_line": {
                "type": "string",
                "description": "The grid line-id the band is measured from (the id, not the name).",
            },
            "extent_ft": {
                "type": "number",
                "description": "How far the protected band reaches from the anchor, in feet.",
            },
            "side": {
                "type": "string",
                "enum": ["greater", "less"],
                "description": (
                    "Which side of the anchor is protected: 'greater' = the higher-coordinate "
                    "side, 'less' = the lower-coordinate side (along the anchor line's axis)."
                ),
            },
        },
        "required": ["statement", "anchor_line", "extent_ft", "side"],
        "additionalProperties": False,
    },
)

_MIN_BAY_TOOL = ToolSpec(
    name="capture_min_bay",
    description=(
        "Capture a minimum bay dimension: column/post lines may not be spaced closer than "
        "the given distance anywhere in the plan."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "statement": {
                "type": "string",
                "description": "The engineer's constraint, restated in one sentence.",
            },
            "min_spacing_ft": {
                "type": "number",
                "description": "The minimum allowed bay dimension, in feet.",
            },
        },
        "required": ["statement", "min_spacing_ft"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True, slots=True)
class ConstraintCapture:
    """The capture surface. ``capture`` turns an utterance into ordinary changeset
    ops through the LLM seam; the caller proposes them. Replay-safe by the same
    posture as the LLM proposer: the emitted ops are recorded in the changeset the
    caller commits, so nothing re-calls the model to re-derive them."""

    client: LLMClient

    @property
    def capturer(self) -> str:
        """The model identity recorded on every captured constraint (ADR 0009)."""
        return self.client.descriptor

    def capture(self, *, utterance: str, snapshot: ResolvedSnapshot) -> list[ChangesetOp]:
        """Capture zero or more spatial constraints from ``utterance``. Returns the
        ``AddConstraint`` ops (empty when the model captured nothing usable — the
        caller must not build an empty changeset from that)."""
        grid = _single_grid(snapshot)
        user = _capture_prompt(utterance, grid)
        invocations = self.client.invoke_tools(
            system=_CAPTURE_SYSTEM, user=user, tools=[_CLEAR_SPAN_TOOL, _MIN_BAY_TOOL]
        )
        ops: list[ChangesetOp] = []
        for invocation in invocations:
            op = self._to_op(invocation, utterance)
            if op is not None:
                ops.append(op)
        return ops

    def _to_op(self, invocation: ToolInvocation, utterance: str) -> ChangesetOp | None:
        data = invocation.input
        statement = str(data.get("statement") or utterance).strip() or utterance
        if invocation.name == "capture_clear_span":
            region: dict[str, JsonValue] = {
                "kind": "offset_band",
                "anchor": data.get("anchor_line"),
                "extent": {"mag": data.get("extent_ft"), "unit": "ft"},
                "side": data.get("side"),
            }
            predicate = "no_vertical_support_within"
            payload: dict[str, JsonValue] = {}
        elif invocation.name == "capture_min_bay":
            region = {"kind": "whole_plan"}
            predicate = "min_bay_spacing"
            payload = {"min_spacing": {"mag": data.get("min_spacing_ft"), "unit": "ft"}}
        else:
            return None  # a tool we do not know how to realize; skip it

        constraint = ProjectConstraint.model_validate(
            {
                "cid": new_ulid(),
                "predicate": predicate,
                "region": region,
                "payload": payload,
                "statement": statement,
                "provenance": {"source": "authored", "captured_by": self.capturer},
            }
        )
        return AddConstraint(constraint=constraint)


def _single_grid(snapshot: ResolvedSnapshot) -> Decision:
    grids = [d for d in snapshot.decisions.values() if d.kind == "grid" and d.state == "resolved"]
    if len(grids) != 1:
        raise ValueError(f"conversational capture needs exactly one grid; found {len(grids)}")
    return grids[0]


def _capture_prompt(utterance: str, grid: Decision) -> str:
    params = parse_params(grid)
    assert isinstance(params, GridParams)
    lines = "; ".join(
        f"{line.name} (id {line.line_id}, {line.axis}={line.offset.mag:g} {line.offset.unit})"
        for line in sorted(params.lines, key=lambda ln: (ln.axis, ln.offset.si_mag))
    )
    return (
        f"Grid lines: {lines}.\n"
        f'The engineer says: "{utterance}"\n'
        "Capture every spatial constraint it states by calling the capture_* tools."
    )
