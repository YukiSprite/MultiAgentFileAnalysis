"""LLM client implementations — provider-neutral and concrete adapters."""

import json
import os
from typing import Protocol

from multi_agent_file_analysis.core import ConfigError

from .messages import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    TokenUsage,
)


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
        default_temperature: float | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._default_model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._default_temperature = self._parse_temperature(
            default_temperature
            if default_temperature is not None
            else os.environ.get("OPENAI_TEMPERATURE", "0.0")
        )
        configured_reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT")
        if not configured_reasoning_effort:
            raise ConfigError(
                "OPENAI_REASONING_EFFORT is required; set it in .env to "
                "low, high, or max"
            )
        self._reasoning_effort = self._parse_reasoning_effort(
            configured_reasoning_effort
        )
        self._tool_mode = os.environ.get("OPENAI_TOOL_MODE", "auto").casefold()
        if self._tool_mode not in {"auto", "native", "text"}:
            raise ConfigError("OPENAI_TOOL_MODE must be auto, native, or text")
        self._native_tools_supported: bool | None = {
            "native": True,
            "text": False,
        }.get(self._tool_mode)
        self._client = None
        if not self._api_key and not self._base_url:
            raise ConfigError(
                "OPENAI_API_KEY is required unless OPENAI_BASE_URL points to "
                "a local compatible endpoint"
            )

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self._client is None:
            from openai import OpenAI

            client_kwargs: dict = {
                "api_key": self._api_key or "local-endpoint"
            }
            if self._base_url:
                client_kwargs["base_url"] = self._base_url
            self._client = OpenAI(**client_kwargs)

        messages = [self._serialize_message(msg) for msg in request.messages]

        params: dict = {
            "model": request.model or self._default_model,
            "messages": messages,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self._default_temperature
            ),
            "reasoning_effort": self._reasoning_effort,
        }
        if request.max_output_tokens is not None:
            params["max_tokens"] = request.max_output_tokens

        send_tools = bool(request.tools) and self._native_tools_supported is not False
        if send_tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            params["tool_choice"] = request.tool_choice or "auto"

        try:
            response = self._client.chat.completions.create(**params)
        except Exception as exc:
            if not (
                send_tools
                and self._tool_mode == "auto"
                and self._looks_like_unsupported_tools(exc)
            ):
                raise
            self._native_tools_supported = False
            params.pop("tools", None)
            params.pop("tool_choice", None)
            response = self._client.chat.completions.create(**params)
        else:
            if send_tools and self._tool_mode == "auto":
                self._native_tools_supported = True

        choice = response.choices[0]
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        tool_calls: list[LLMToolCall] = []
        for index, call in enumerate(
            getattr(choice.message, "tool_calls", None) or []
        ):
            raw_arguments = call.function.arguments or "{}"
            parse_error = None
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must decode to an object")
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = {}
                parse_error = str(exc)
            tool_calls.append(
                LLMToolCall(
                    id=call.id or f"tool_call_{index}",
                    name=call.function.name or "",
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    parse_error=parse_error,
                )
            )

        return LLMResponse(
            message=LLMMessage(
                role="assistant",
                content=choice.message.content or "",
                tool_calls=tool_calls,
            ),
            model=response.model,
            usage=usage,
            raw_id=response.id,
        )

    @staticmethod
    def _serialize_message(message: LLMMessage) -> dict:
        payload: dict = {"role": str(message.role), "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            payload["content"] = message.content or None
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments
                        or json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            if not message.tool_call_id:
                raise ConfigError("Tool messages require tool_call_id")
            payload["tool_call_id"] = message.tool_call_id
        elif message.name:
            payload["name"] = message.name
        return payload

    @staticmethod
    def _looks_like_unsupported_tools(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status not in {400, 404, 422}:
            return False
        message = str(exc).casefold()
        return any(
            marker in message
            for marker in ("tool", "function calling", "function_call", "tools")
        )

    @staticmethod
    def _parse_temperature(value: float | str) -> float:
        try:
            temperature = float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                "OPENAI_TEMPERATURE must be a number between 0 and 2"
            ) from exc
        if not 0.0 <= temperature <= 2.0:
            raise ConfigError(
                "OPENAI_TEMPERATURE must be between 0 and 2"
            )
        return temperature

    @staticmethod
    def _parse_reasoning_effort(value: str) -> str:
        reasoning_effort = str(value).strip().casefold()
        if reasoning_effort not in {"low", "high", "max"}:
            raise ConfigError(
                "OPENAI_REASONING_EFFORT must be low, high, or max"
            )
        return reasoning_effort
