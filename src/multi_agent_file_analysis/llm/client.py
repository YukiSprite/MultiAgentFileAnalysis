"""LLM client boundary."""

from typing import Protocol

from .messages import LLMRequest, LLMResponse


class LLMClient(Protocol):
    """Model gateway used by agents."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a model response for one agent step."""
        ...
