from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from multi_agent_file_analysis.core import ConfigError
from multi_agent_file_analysis.llm import (
    LLMMessage,
    LLMRequest,
    LLMToolCall,
    LLMToolDefinition,
    OpenAICompatibleClient,
)


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class UnsupportedToolsError(Exception):
    status_code = 400


def response_with_tool_call() -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="ls", arguments='{"path":"/"}'),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=None,
        model="test-model",
        id="response-1",
    )


def plain_response(content: str = "done") -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=None,
        model="test-model",
        id="response-2",
    )


class OpenAICompatibleToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = LLMToolDefinition(
            name="ls",
            description="List files",
            parameters={"type": "object", "properties": {}},
        )

    def test_serializes_native_tools_and_parses_tool_calls(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_TOOL_MODE": "native",
                "OPENAI_REASONING_EFFORT": "max",
            },
            clear=False,
        ):
            client = OpenAICompatibleClient(api_key="test")
        completions = FakeCompletions([response_with_tool_call()])
        client._client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        response = client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content="list files")],
                tools=[self.definition],
                tool_choice="auto",
            )
        )

        self.assertEqual("ls", completions.calls[0]["tools"][0]["function"]["name"])
        self.assertEqual("auto", completions.calls[0]["tool_choice"])
        self.assertEqual("ls", response.message.tool_calls[0].name)
        self.assertEqual({"path": "/"}, response.message.tool_calls[0].arguments)

    def test_serializes_assistant_and_tool_result_messages(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_TOOL_MODE": "native",
                "OPENAI_REASONING_EFFORT": "max",
            },
            clear=False,
        ):
            client = OpenAICompatibleClient(api_key="test")
        completions = FakeCompletions([plain_response()])
        client._client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        call = LLMToolCall(id="call_1", name="pwd", arguments={})

        client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="assistant", content="", tool_calls=[call]),
                    LLMMessage(
                        role="tool",
                        content=json.dumps({"stdout": "/"}),
                        name="pwd",
                        tool_call_id="call_1",
                    ),
                ],
                tools=[self.definition],
            )
        )

        sent = completions.calls[0]["messages"]
        self.assertEqual("call_1", sent[0]["tool_calls"][0]["id"])
        self.assertEqual("call_1", sent[1]["tool_call_id"])

    def test_auto_mode_falls_back_when_provider_rejects_tools(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_TOOL_MODE": "auto",
                "OPENAI_REASONING_EFFORT": "max",
            },
            clear=False,
        ):
            client = OpenAICompatibleClient(api_key="test")
        error = UnsupportedToolsError("tools are not supported")
        completions = FakeCompletions([error, plain_response("fallback")])
        client._client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        response = client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content="list files")],
                tools=[self.definition],
            )
        )

        self.assertEqual("fallback", response.message.content)
        self.assertIn("tools", completions.calls[0])
        self.assertNotIn("tools", completions.calls[1])
        self.assertFalse(client._native_tools_supported)

    def test_low_default_temperature_is_sent_and_request_can_override(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_TOOL_MODE": "native",
                "OPENAI_TEMPERATURE": "0.0",
                "OPENAI_REASONING_EFFORT": "max",
            },
            clear=True,
        ):
            client = OpenAICompatibleClient(api_key="test")
        completions = FakeCompletions([plain_response(), plain_response()])
        client._client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        client.complete(
            LLMRequest(messages=[LLMMessage(role="user", content="default")])
        )
        client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content="override")],
                temperature=0.25,
            )
        )

        self.assertEqual(0.0, completions.calls[0]["temperature"])
        self.assertEqual(0.25, completions.calls[1]["temperature"])
        self.assertEqual("max", completions.calls[0]["reasoning_effort"])
        self.assertEqual("max", completions.calls[1]["reasoning_effort"])

    def test_temperature_must_be_in_supported_range(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_TOOL_MODE": "native",
                    "OPENAI_TEMPERATURE": "not-a-number",
                    "OPENAI_REASONING_EFFORT": "max",
                },
                clear=True,
            ),
            self.assertRaises(ConfigError),
        ):
            OpenAICompatibleClient(api_key="test")

    def test_reasoning_effort_is_required(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"OPENAI_TOOL_MODE": "native"},
                clear=True,
            ),
            self.assertRaisesRegex(
                ConfigError,
                "OPENAI_REASONING_EFFORT is required",
            ),
        ):
            OpenAICompatibleClient(api_key="test")

    def test_reasoning_effort_must_be_supported(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_TOOL_MODE": "native",
                    "OPENAI_REASONING_EFFORT": "extreme",
                },
                clear=True,
            ),
            self.assertRaises(ConfigError),
        ):
            OpenAICompatibleClient(api_key="test")


if __name__ == "__main__":
    unittest.main()
