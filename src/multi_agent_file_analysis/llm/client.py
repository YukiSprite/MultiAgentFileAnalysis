"""LLM client implementations — provider-neutral and concrete adapters."""

import os
from typing import Protocol

from multi_agent_file_analysis.core import ConfigError

from .messages import LLMMessage, LLMRequest, LLMResponse, TokenUsage


class LLMClient(Protocol):
    """Model gateway used by agents."""

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class DryRunLLMClient:
    """LLM client that returns empty responses for dry-run mode."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            message=LLMMessage(role="assistant", content="[dry_run] No model called."),
            model=request.model or "dry-run",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


class OpenAICompatibleClient:
    """LLM client backed by an OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._default_model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._client = None
        if not self._api_key and not self._base_url:
            raise ConfigError(
                "OPENAI_API_KEY is required unless OPENAI_BASE_URL points to "
                "a local compatible endpoint"
            )

    def complete(self, request: LLMRequest) -> LLMResponse:
        from openai import OpenAI

        if self._client is None:
            client_kwargs: dict = {
                "api_key": self._api_key or "local-endpoint"
            }
            if self._base_url:
                client_kwargs["base_url"] = self._base_url
            self._client = OpenAI(**client_kwargs)

        messages: list[dict] = []
        for msg in request.messages:
            msg_dict: dict = {"role": str(msg.role), "content": msg.content}
            if msg.name:
                msg_dict["name"] = msg.name
            messages.append(msg_dict)

        params: dict = {
            "model": request.model or self._default_model,
            "messages": messages,
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            params["max_tokens"] = request.max_output_tokens

        response = self._client.chat.completions.create(**params)

        choice = response.choices[0]
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return LLMResponse(
            message=LLMMessage(
                role="assistant",
                content=choice.message.content or "",
            ),
            model=response.model,
            usage=usage,
            raw_id=response.id,
        )
