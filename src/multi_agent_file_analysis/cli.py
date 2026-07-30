"""Command-line interface for indexing and diagnosis."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from multi_agent_file_analysis.app import ApplicationFactory
from multi_agent_file_analysis.config import AppConfig
from multi_agent_file_analysis.core import RunMode, WorkflowStatus
from multi_agent_file_analysis.qa import QARequest


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    normalized = _normalize_argv(raw_args)
    parser = _build_parser()
    if not normalized:
        parser.print_help()
        return 0
    args = parser.parse_args(normalized)

    if args.command == "index":
        return _cmd_index(args)
    if args.command == "ask":
        return _cmd_ask(args)
    parser.print_help()
    return 0


def _normalize_argv(args: list[str]) -> list[str]:
    """Keep the documented `mafa [flags] question` shorthand working."""
    if not args:
        return args
    first = args[0]
    if first in {"ask", "index", "-h", "--help"}:
        return args
    return ["ask", *args]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MultiAgentFileAnalysis — evidence-grounded operations QA"
    )
    sub = parser.add_subparsers(dest="command")

    index_parser = sub.add_parser(
        "index",
        help="Generate a Page Index from Markdown files",
    )
    index_parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Directory containing Markdown files",
    )
    index_parser.add_argument(
        "--output",
        type=Path,
        default=Path("configs/page_index.yaml"),
        help="Generated Page Index path",
    )

    ask_parser = sub.add_parser("ask", help="Ask the indexed knowledge base")
    ask_parser.add_argument("query", nargs="?", help="Question to diagnose")
    _add_ask_flags(ask_parser)
    return parser


def _add_ask_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--page-index",
        type=Path,
        default=Path("configs/page_index.example.yaml"),
        help="Path to Page Index YAML",
    )
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Root used to resolve Page Index source paths",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run bounded lexical retrieval without calling an LLM",
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help="Append structured audit events to this JSONL file",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=12_000,
        help="Maximum characters returned by one file read",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Keep accepting questions and HITL responses",
    )


def _cmd_index(args: argparse.Namespace) -> int:
    from multi_agent_file_analysis.index import PageIndexLoader

    kb_root = args.knowledge_base.resolve()
    output = args.output.resolve()
    try:
        index = PageIndexLoader.scan_directory(kb_root, output)
    except Exception as exc:
        print(f"Index generation failed: {exc}", file=sys.stderr)
        return 2

    print(f"Page Index generated: {output}")
    print(f"Knowledge-base root: {kb_root}")
    print(f"Documents indexed: {len(index.documents)}")
    for document in index.documents:
        print(f"  - {document.source}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    if not args.interactive and not (args.query and args.query.strip()):
        print("Provide a question or use --interactive.", file=sys.stderr)
        return 2

    config = AppConfig(
        page_index_path=args.page_index.resolve(),
        knowledge_base_root=args.knowledge_base.resolve(),
        run_mode=RunMode.DRY_RUN if args.dry_run else RunMode.INTERACTIVE,
        audit_log_path=args.audit_log.resolve() if args.audit_log else None,
        max_file_chars=args.max_chars,
    )
    try:
        services = ApplicationFactory().build(config)
    except Exception as exc:
        print(f"Initialization failed: {exc}", file=sys.stderr)
        return 2

    if args.interactive:
        return _interactive_loop(services.qa_service)
    return _single_query(services.qa_service, args.query)


def _single_query(qa_service, query: str) -> int:
    response = qa_service.ask(QARequest(query=query))
    while response.needs_human_input:
        request = response.state.human_request
        if request is None:
            break
        _print_human_request(request)
        try:
            user_input = input("Your response: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if not user_input:
            print("No input supplied; workflow remains suspended.")
            return 3
        response = qa_service.resume(response.state, user_input)
    return _print_response(response)


def _interactive_loop(qa_service) -> int:
    print("Interactive mode. Type /quit to exit.")
    state = None
    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.casefold() in {"/quit", "/exit", "/q"}:
            return 0

        if state is not None:
            response = qa_service.resume(state, line)
        else:
            response = qa_service.ask(QARequest(query=line))

        if response.needs_human_input:
            state = response.state
            request = state.human_request
            if request:
                _print_human_request(request)
            continue

        state = None
        _print_response(response)


def _print_human_request(request) -> None:
    print("\n[需要补充现场信息]")
    print(request.prompt)
    if request.reason:
        print(f"原因：{request.reason}")
    if request.suggested_command and request.command_approved:
        print(f"已通过只读门禁的建议命令：{request.suggested_command}")
    elif request.command_warning:
        print(f"命令未展示：{request.command_warning}")
    print(f"期望输入：{request.expected_input}")
    print(f"请求 ID：{request.request_id}")


def _print_response(response) -> int:
    state = response.state
    if response.answer:
        print(f"\n{response.answer}")
    if state.errors:
        print("\n运行说明：")
        for error in state.errors:
            print(f"- {error}")
    if state.status == WorkflowStatus.COMPLETED:
        return 0
    print(f"\nWorkflow status: {state.status}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
