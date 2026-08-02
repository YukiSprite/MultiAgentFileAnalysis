from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multi_agent_file_analysis.agents import ExplorerAgent
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import AgentResultStatus
from multi_agent_file_analysis.graph import DiagnosisState
from multi_agent_file_analysis.index import (
    IndexNode,
    NodeKind,
    PageIndex,
    PageIndexRepository,
)
from multi_agent_file_analysis.llm import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
)
from multi_agent_file_analysis.vfs import VirtualFileSystem


class SequenceLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class ExplorerNativeToolTests(unittest.TestCase):
    def test_explorer_uses_native_unix_tools_and_records_verified_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "kb"
            root.mkdir()
            document = root / "rule.md"
            document.write_text(
                "# Rule\n\nAllowTcpForwarding yes\n",
                encoding="utf-8",
            )
            index_path = base / "index.yaml"
            index_path.write_text(
                "version: '0.2'\nroot:\n  path: /\n",
                encoding="utf-8",
            )
            index = PageIndex(
                version="0.2",
                root=IndexNode(
                    path="/",
                    kind=NodeKind.DIRECTORY,
                    description="root",
                    children=[
                        IndexNode(
                            path="/rule.md",
                            kind=NodeKind.FILE,
                            description="OpenSSH rule",
                            source="rule.md",
                        )
                    ],
                ),
            )
            config = AppConfig(
                page_index_path=index_path,
                knowledge_base_root=root,
            )
            vfs = VirtualFileSystem(PageIndexRepository(index, root), config)

            llm = SequenceLLM(
                [
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content=(
                                '{"evidence_obligations":["forwarding rule"],'
                                '"exact_literals":["AllowTcpForwarding"],'
                                '"search_queries":["TCP forwarding"]}'
                            ),
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                LLMToolCall(
                                    id="grep-1",
                                    name="grep",
                                    arguments={
                                        "pattern": "AllowTcpForwarding",
                                        "path": "/",
                                    },
                                )
                            ],
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                LLMToolCall(
                                    id="evidence-1",
                                    name="record_evidence",
                                    arguments={
                                        "source_path": "/rule.md",
                                        "summary": "TCP forwarding is enabled",
                                        "kind": "config_reference",
                                        "quote": "AllowTcpForwarding yes",
                                        "retrieval_query": "AllowTcpForwarding",
                                        "supports_obligations": [
                                            "forwarding rule"
                                        ],
                                    },
                                )
                            ],
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content="Evidence collection complete.",
                        )
                    ),
                ]
            )
            state = DiagnosisState(user_query="Is TCP forwarding enabled?")

            result = ExplorerAgent(vfs=vfs, llm_client=llm).run(state)

            self.assertEqual(AgentResultStatus.SUCCEEDED, result.status)
            self.assertEqual(1, len(state.evidence))
            self.assertTrue(state.evidence[0].verified)
            self.assertEqual(
                ["forwarding rule"],
                state.evidence[0].supports_obligations,
            )
            self.assertEqual([], state.uncovered_evidence_obligations)
            tool_names = {tool.name for tool in llm.requests[1].tools}
            self.assertIn("grep", tool_names)
            self.assertIn("record_evidence", tool_names)
            second_messages = llm.requests[2].messages
            tool_messages = [message for message in second_messages if message.role == "tool"]
            self.assertEqual("grep-1", tool_messages[0].tool_call_id)
            self.assertIn('"exit_code": 0', tool_messages[0].content)

    def test_explorer_prompt_requires_body_text_for_each_evidence_obligation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "kb"
            root.mkdir()
            (root / "spells.md").write_text("# 法术\n", encoding="utf-8")
            index_path = base / "index.yaml"
            index = PageIndex(
                version="0.2",
                root=IndexNode(
                    path="/",
                    kind=NodeKind.DIRECTORY,
                    description="root",
                    children=[
                        IndexNode(
                            path="/spells.md",
                            kind=NodeKind.FILE,
                            description="Spell reference",
                            source="spells.md",
                        )
                    ],
                ),
            )
            index_path.write_text("version: '0.2'\n", encoding="utf-8")
            config = AppConfig(index_path, root)
            vfs = VirtualFileSystem(PageIndexRepository(index, root), config)
            llm = SequenceLLM(
                [
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content=(
                                '{"evidence_obligations":["法术正文","区域规则"],'
                                '"exact_literals":["油腻术"],'
                                '"search_queries":["法术区域 方格 生物"]}'
                            ),
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content='{"action":"done","summary":"none"}',
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                LLMToolCall(
                                    id="grep-required",
                                    name="grep",
                                    arguments={"pattern": "油腻术", "path": "/"},
                                )
                            ],
                        )
                    ),
                ]
            )
            state = DiagnosisState(
                user_query="一个大型生物有部分方格处于油腻术范围内吗？"
            )

            result = ExplorerAgent(vfs=vfs, llm_client=llm, max_turns=2).run(
                state
            )

            system_message = llm.requests[1].messages[0].content
            first_user_message = llm.requests[1].messages[1].content
            self.assertIn("Decompose the question into evidence obligations", system_message)
            self.assertIn("bare heading", system_message)
            self.assertIn("use cat", system_message)
            self.assertIn("paste documentation", system_message)
            self.assertIn("Model-generated retrieval plan", first_user_message)
            self.assertIn("油腻术", first_user_message)
            self.assertIn("$ grep '油腻术' /", first_user_message)
            self.assertIn('"matches": 1', first_user_message)
            retry_messages = llm.requests[2].messages
            self.assertTrue(
                any(
                    "Still uncovered: 法术正文; 区域规则" in message.content
                    for message in retry_messages
                    if message.role == "user"
                )
            )
            self.assertTrue(
                any(
                    step.tool_name.value == "grep" and step.query == "油腻术"
                    for step in state.exploration_log
                )
            )
            self.assertEqual(AgentResultStatus.NEEDS_MORE_CONTEXT, result.status)
            self.assertEqual("reason", result.next_stage.value)

    def test_model_plan_seeds_body_results_and_requires_obligation_coverage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "kb"
            root.mkdir()
            grease_text = (
                "# 法术\n\n**油腻术 (Grease)**\n\n"
                "施放法术时，任何在此区域的生物都必须进行一次反射豁免。\n"
            )
            area_text = (
                "# 区域\n\n法术区域中的方格决定一个生物是否位于区域内。\n"
                "如果方格的远边在区域内，格内所有事物都在法术区域内。\n"
            )
            (root / "spell.md").write_text(grease_text, encoding="utf-8")
            (root / "area.md").write_text(area_text, encoding="utf-8")
            index_path = base / "index.yaml"
            index_path.write_text("version: '0.2'\n", encoding="utf-8")
            index = PageIndex(
                version="0.2",
                root=IndexNode(
                    path="/",
                    kind=NodeKind.DIRECTORY,
                    description="root",
                    children=[
                        IndexNode(
                            path="/spell.md",
                            kind=NodeKind.FILE,
                            description="spell rules",
                            source="spell.md",
                        ),
                        IndexNode(
                            path="/area.md",
                            kind=NodeKind.FILE,
                            description="area rules",
                            source="area.md",
                        ),
                    ],
                ),
            )
            config = AppConfig(index_path, root)
            vfs = VirtualFileSystem(PageIndexRepository(index, root), config)
            spell_obligation = "油腻术对区域内生物的效果"
            area_obligation = "法术区域按方格判定生物是否在区域内的规则"
            llm = SequenceLLM(
                [
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content=(
                                '{"evidence_obligations":['
                                f'"{spell_obligation}","{area_obligation}"],'
                                '"exact_literals":["油腻术"],'
                                '"search_queries":["法术区域 方格 生物"]}'
                            ),
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                LLMToolCall(
                                    id="record-spell",
                                    name="record_evidence",
                                    arguments={
                                        "source_path": "/spell.md",
                                        "summary": "区域内生物进行反射豁免",
                                        "quote": (
                                            "施放法术时，任何在此区域的生物都必须"
                                            "进行一次反射豁免。"
                                        ),
                                        "supports_obligations": [spell_obligation],
                                    },
                                ),
                                LLMToolCall(
                                    id="record-area",
                                    name="record_evidence",
                                    arguments={
                                        "source_path": "/area.md",
                                        "summary": "区域按方格边界判定",
                                        "quote": (
                                            "法术区域中的方格决定一个生物是否位于"
                                            "区域内。\n如果方格的远边在区域内，格内"
                                            "所有事物都在法术区域内。"
                                        ),
                                        "supports_obligations": [area_obligation],
                                    },
                                ),
                            ],
                        )
                    ),
                    LLMResponse(
                        message=LLMMessage(
                            role="assistant",
                            content='{"action":"done","summary":"complete"}',
                        )
                    ),
                ]
            )
            state = DiagnosisState(user_query="大型生物部分方格在油腻术内吗？")

            result = ExplorerAgent(vfs=vfs, llm_client=llm).run(state)

            self.assertEqual(AgentResultStatus.SUCCEEDED, result.status)
            seed_prompt = llm.requests[1].messages[1].content
            self.assertIn("任何在此区域的生物", seed_prompt)
            self.assertIn("方格决定一个生物是否位于区域内", seed_prompt)
            self.assertEqual(2, len(state.evidence))
            self.assertEqual([], state.uncovered_evidence_obligations)


if __name__ == "__main__":
    unittest.main()
