"""LLM client boundary.

This protocol lets agents depend on a provider-neutral model interface. Concrete
OpenAI, local model, or test fake clients can be added later without changing
agent contracts.
"""

from typing import Protocol

from .messages import LLMRequest, LLMResponse


class LLMClient(Protocol):
    """Model gateway used by agents."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a model response for one agent step."""
        ...
