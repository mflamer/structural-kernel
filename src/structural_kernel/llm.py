"""The LLM seam: a provider-neutral structured-tool client (ADR 0009).

An LLM proposer needs exactly one thing from a model: given a prompt and a set
of tool schemas, return the tool calls the model chose. That is the whole
``LLMClient`` protocol — one method, ``invoke_tools``. Two implementations sit
behind it:

- ``AnthropicClient`` (``llm_anthropic.py``) — the real, Anthropic-backed client
  (an optional ``llm`` extra, the same posture as the xara engine); the model
  defaults to ``claude-opus-4-8``. Its SDK contact is isolated in that module so
  this seam stays pyright-strict.
- ``FakeLLMClient`` — a deterministic stand-in that returns canned tool calls,
  so the proposer, the pipeline, and CI never touch the network or a key.

The kernel's "AI never edits state directly" rule holds by construction: this
client only *returns tool calls*. The proposer turns them into ordinary
changeset proposals, and the ordinary validate pipeline is the only writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pydantic import JsonValue

DEFAULT_MODEL = "claude-opus-4-8"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model may call — name, description, and a JSON Schema for its
    input. Kernel vocabulary; nothing provider-typed crosses this boundary."""

    name: str
    description: str
    input_schema: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """One tool call the model chose: the tool name and its validated input."""

    name: str
    input: dict[str, JsonValue]


class LLMClient(Protocol):
    """A model that, given a prompt and tool schemas, returns the tool calls it
    chose. Forcing tool use and collecting every tool_use block is the adapter's
    job; the proposer sees only invocations."""

    @property
    def descriptor(self) -> str: ...

    def invoke_tools(
        self, *, system: str, user: str, tools: list[ToolSpec]
    ) -> list[ToolInvocation]: ...


@dataclass
class FakeLLMClient:
    """Deterministic stand-in: returns its canned invocations and records the
    prompts it was asked (for test assertions). No network, no key — this is the
    path CI and the property tests take."""

    invocations: list[ToolInvocation]
    descriptor: str = "fake-llm"
    calls: list[tuple[str, str, tuple[str, ...]]] = field(
        default_factory=list[tuple[str, str, tuple[str, ...]]]
    )

    def invoke_tools(
        self, *, system: str, user: str, tools: list[ToolSpec]
    ) -> list[ToolInvocation]:
        self.calls.append((system, user, tuple(t.name for t in tools)))
        return list(self.invocations)
