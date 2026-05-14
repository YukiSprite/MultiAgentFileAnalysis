"""LLM request and response models."""

from dataclasses import dataclass, field
from typing import Literal


MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class LLMMessage:
    """A single message sent to or received from an LLM."""

    role: MessageRole
    content: str
    name: str | None = None


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


@dataclass(slots=True)
class LLMResponse:
    """A provider-neutral LLM response."""

    message: LLMMessage
    model: str | None = None
    usage: TokenUsage | None = None
    raw_id: str | None = None
