"""LLM request and response models."""

from dataclasses import dataclass, field
from typing import Any, Literal


MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class LLMToolCall:
    """One provider-neutral native function call requested by a model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str | None = None
    parse_error: str | None = None


@dataclass(slots=True)
class LLMToolDefinition:
    """JSON Schema definition for one function tool."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class LLMMessage:
    """A single message sent to or received from an LLM."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)


@dataclass(slots=True)
class TokenUsage:
    """Token accounting returned by an LLM provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class LLMRequest:
    """A provider-neutral LLM request."""

    messages: list[LLMMessage]
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    tools: list[LLMToolDefinition] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None


@dataclass(slots=True)
class LLMResponse:
    """A provider-neutral LLM response."""

    message: LLMMessage
    model: str | None = None
    usage: TokenUsage | None = None
    raw_id: str | None = None
