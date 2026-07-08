"""The Anthropic-backed LLM client (ADR 0009): the one module that imports the
anthropic SDK.

Isolated from ``llm.py`` so the seam (protocol, tool types, fake) stays
pyright-strict while this adapter absorbs the SDK's untyped surface — the same
split ``materials/base.py`` and ``materials/steel.py`` use. The ``anthropic``
package is the optional ``llm`` extra; nothing here is imported unless a caller
constructs an ``AnthropicClient``, so the fake path and CI never require it.
"""

# pyright: reportMissingImports=false, reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false

from __future__ import annotations

from typing import Any

from structural_kernel.llm import DEFAULT_MODEL, ToolInvocation, ToolSpec


class AnthropicClient:
    """Forces tool use (``tool_choice={"type": "any"}``) and collects every
    ``tool_use`` block from the one response — parallel tool use lets a single
    call return the whole slate. Opus 4.8 rejects sampling and thinking-budget
    parameters, so none are sent."""

    def __init__(self, *, model: str = DEFAULT_MODEL, max_tokens: int = 8192) -> None:
        self._model = model
        self._max_tokens = max_tokens

    @property
    def descriptor(self) -> str:
        return f"anthropic/{self._model}"

    def invoke_tools(
        self, *, system: str, user: str, tools: list[ToolSpec]
    ) -> list[ToolInvocation]:
        from anthropic import Anthropic

        client = Anthropic()
        message = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            tools=[
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
            tool_choice={"type": "any"},  # must call at least one tool
            messages=[{"role": "user", "content": user}],
        )
        invocations: list[ToolInvocation] = []
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                block_input: dict[str, Any] = dict(block.input)
                invocations.append(ToolInvocation(name=str(block.name), input=block_input))
        return invocations
