"""Command-line interface for indexing and diagnosis."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from multi_agent_file_analysis.app import ApplicationFactory, mount_corpus
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
    if args.command == "ingest-chm":
        return _cmd_ingest_chm(args)
    if args.command == "web":
        return _cmd_web(args)
    if args.command == "chat":
        return _cmd_chat(args)
    if args.command == "ask":
        return _cmd_ask(args)
    parser.print_help()
    return 0


def _normalize_argv(args: list[str]) -> list[str]:
    """Keep the documented `mafa [flags] question` shorthand working."""
    if not args:
        return ["web"]
    first = args[0]
    if first in {"ask", "chat", "web", "index", "ingest-chm", "-h", "--help"}:
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

    chm_parser = sub.add_parser(
        "ingest-chm",
        help="Safely convert a local CHM archive into indexed Markdown",
    )
    chm_parser.add_argument("source", type=Path, help="Local .chm archive")
    chm_parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Knowledge-base root receiving chm_imports/<mount>",
    )
    chm_parser.add_argument(
        "--output",
        type=Path,
        default=Path("configs/page_index.chm.yaml"),
        help="Page Index rebuilt after conversion",
    )
    chm_parser.add_argument(
        "--mount-name",
        default=None,
        help="Safe directory name below knowledge_base/chm_imports",
    )
    chm_parser.add_argument(
        "--extractor",
        default="extract_chmLib",
        help="Path or command name for the chmlib extractor",
    )
    chm_parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Do not copy local images referenced by converted pages",
    )
    chm_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing mount when source or conversion settings changed",
    )
    chm_parser.add_argument(
        "--max-archive-mb",
        type=int,
        default=512,
        help="Maximum accepted CHM archive size in MiB",
    )
    chm_parser.add_argument(
        "--max-extracted-mb",
        type=int,
        default=2048,
        help="Maximum total extracted size in MiB",
    )
    chm_parser.add_argument(
        "--max-extracted-files",
        type=int,
        default=50_000,
        help="Maximum extracted file count",
    )
    chm_parser.add_argument(
        "--max-page-mb",
        type=int,
        default=10,
        help="Maximum size of one HTML page, TOC, or copied image in MiB",
    )
    chm_parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Extraction timeout in seconds",
    )

    chat_parser = sub.add_parser(
        "chat",
        help="Choose one corpus and keep asking questions in an isolated session",
    )
    chat_parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Root scanned dynamically for selectable corpus directories",
    )
    chat_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run bounded lexical retrieval without calling an LLM",
    )
    chat_parser.add_argument(
        "--audit-log",
        type=Path,
        default=None,
        help="Append all questions in this session to one JSONL audit log",
    )
    chat_parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Load model configuration without overriding shell variables",
    )
    chat_parser.add_argument(
        "--max-chars",
        type=int,
        default=12_000,
        help="Maximum characters returned by one file read",
    )

    web_parser = sub.add_parser(
        "web",
        help="Open the browser console (default when run without arguments)",
    )
    web_parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=Path("knowledge_base"),
        help="Root scanned dynamically for selectable corpus directories",
    )
    web_parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Load model configuration without overriding shell variables",
    )
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument("--max-sessions", type=int, default=8)
    web_parser.add_argument("--idle-minutes", type=float, default=30.0)
    web_parser.add_argument("--max-events", type=int, default=200)

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
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Load model configuration from this file without overriding shell variables",
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


def _cmd_ingest_chm(args: argparse.Namespace) -> int:
    from multi_agent_file_analysis.ingestion import (
        ChmExtractor,
        ChmImporter,
        ChmImportLimits,
    )

    mib = 1024 * 1024
    limits = ChmImportLimits(
        max_archive_bytes=args.max_archive_mb * mib,
        max_extracted_bytes=args.max_extracted_mb * mib,
        max_extracted_files=args.max_extracted_files,
        max_page_bytes=args.max_page_mb * mib,
        extraction_timeout_seconds=args.timeout,
    )
    try:
        limits.validate()
        extractor = ChmExtractor(binary=args.extractor, limits=limits)
        result = ChmImporter(extractor=extractor, limits=limits).import_archive(
            args.source,
            args.knowledge_base,
            args.output,
            mount_name=args.mount_name,
            copy_assets=not args.no_assets,
            force=args.force,
        )
    except Exception as exc:
        print(f"CHM ingestion failed: {exc}", file=sys.stderr)
        return 2

    mode = "cache hit" if result.cache_hit else "converted"
    print(f"CHM ingestion complete ({mode})")
    print(f"Markdown root: {result.output_directory}")
    print(f"Page Index: {result.index_path}")
    print(f"Pages converted: {result.pages_converted}")
    print(f"Assets copied: {result.assets_copied}")
    print(f"TOC entries: {result.toc_entries}")
    print(f"Missing TOC targets: {result.missing_toc_pages}")
    print(f"Indexed documents: {result.indexed_documents}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:20]:
            print(f"  - {warning}")
        if len(result.warnings) > 20:
            print(f"  - ... {len(result.warnings) - 20} more in manifest.json")
    return 0


WEB_DEPENDENCIES = ("fastapi", "uvicorn")


def _missing_web_dependency(
    probe: Callable[[str], object] | None = None,
) -> str | None:
    """Return the first missing import needed by the browser console."""
    find = probe or importlib.util.find_spec
    for name in WEB_DEPENDENCIES:
        try:
            if find(name) is None:
                return name
        except (ImportError, ValueError):
            return name
    return None


def _cmd_web(args: argparse.Namespace) -> int:
    missing = _missing_web_dependency()
    if missing is not None:
        print(f"控制台需要 Web 依赖，当前环境缺少：{missing}", file=sys.stderr)
        print(
            "请先运行：python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    from multi_agent_file_analysis.web import WebSettings, serve

    settings = WebSettings(
        idle_ttl_seconds=max(1.0, args.idle_minutes * 60.0),
        max_sessions=max(1, args.max_sessions),
        max_events_per_run=max(1, args.max_events),
    )
    return serve(
        knowledge_root=args.knowledge_base,
        env_file_path=args.env_file,
        host=args.host,
        port=args.port,
        settings=settings,
    )


def _cmd_chat(args: argparse.Namespace) -> int:
    from multi_agent_file_analysis.corpora import CorpusCatalog

    knowledge_root = args.knowledge_base.resolve()
    try:
        catalog = CorpusCatalog.discover(knowledge_root)
        available = catalog.available(knowledge_root)
    except Exception as exc:
        print(f"知识库发现失败：{exc}", file=sys.stderr)
        return 2

    if not available:
        print(
            "没有发现可用的知识库目录；请加入 Markdown 文件、"
            "CHM 导入结果或 .mafa-corpus.yaml 标记。",
            file=sys.stderr,
        )
        return 2

    try:
        selected = _select_corpus(available)
    except (EOFError, KeyboardInterrupt):
        print()
        return 130
    if selected is None:
        return 0
    corpus, _corpus_root = selected

    print(f"\n正在挂载知识库：{corpus.name}……")
    try:
        mount = mount_corpus(
            corpus,
            knowledge_root,
            run_mode=(
                RunMode.DRY_RUN if args.dry_run else RunMode.INTERACTIVE
            ),
            env_file_path=args.env_file.resolve(),
            audit_log_path=(
                args.audit_log.resolve() if args.audit_log else None
            ),
            max_file_chars=args.max_chars,
        )
    except Exception as exc:
        print(f"知识库初始化失败：{exc}", file=sys.stderr)
        return 2

    try:
        print(f"已选择：{corpus.name}（{mount.document_count} 篇文档）")
        print("当前会话中，Agent 只能看到这个知识库。")
        return _interactive_loop(
            mount.services.qa_service,
            corpus_name=corpus.name,
        )
    finally:
        mount.close()


def _select_corpus(options):
    print("可用知识库：")
    for number, (corpus, _) in enumerate(options, start=1):
        description = f" — {corpus.description}" if corpus.description else ""
        print(f"  {number}. {corpus.name} [{corpus.corpus_id}]{description}")
    while True:
        choice = input("请选择知识库编号（输入 /quit 退出）：").strip()
        if choice.casefold() in {"/quit", "/exit", "/q"}:
            return None
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(options):
                return options[index]
        folded = choice.casefold()
        for option in options:
            corpus, _ = option
            if folded in {corpus.corpus_id.casefold(), corpus.name.casefold()}:
                return option
        print("选择无效，请输入列表中的编号或知识库 ID。")


def _cmd_ask(args: argparse.Namespace) -> int:
    if not args.interactive and not (args.query and args.query.strip()):
        print("Provide a question or use --interactive.", file=sys.stderr)
        return 2

    config = AppConfig(
        page_index_path=args.page_index.resolve(),
        knowledge_base_root=args.knowledge_base.resolve(),
        run_mode=RunMode.DRY_RUN if args.dry_run else RunMode.INTERACTIVE,
        env_file_path=args.env_file.resolve(),
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
        if response.answer:
            print(f"\n{response.answer}")
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


def _interactive_loop(qa_service, *, corpus_name: str | None = None) -> int:
    label = corpus_name or "knowledge-base"
    print("已进入连续问答；每次回答后可继续提问，输入 /quit 退出。")
    state = None
    while True:
        try:
            line = input(f"[{label}] >>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.casefold() in {"/quit", "/exit", "/q"}:
            return 0

        try:
            if state is not None:
                response = qa_service.resume(state, line)
            else:
                response = qa_service.ask(QARequest(query=line))
        except Exception as exc:
            print(f"问题处理失败：{exc}", file=sys.stderr)
            continue

        if response.needs_human_input:
            state = response.state
            if response.answer:
                print(f"\n{response.answer}")
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
    answer = response.answer or state.final_answer or state.partial_answer
    if answer:
        print(f"\n{answer}")
    if state.errors:
        print("\n运行说明：")
        for error in state.errors:
            print(f"- {error}")
    if state.status == WorkflowStatus.COMPLETED:
        return 0
    if state.critic_report is not None:
        report = state.critic_report
        print("\n最后一次 Critic 审查：")
        print(f"- 决策：{report.decision}")
        for note in report.notes:
            print(f"- 说明：{note}")
        for item in report.missing_evidence:
            print(f"- 缺少证据：{item}")
        for item in report.unsupported_claims:
            print(f"- 无依据主张：{item}")
    if state.retrieval_plan is not None:
        plan = state.retrieval_plan
        print("\n最后一次 Explorer 检索计划：")
        for index, obligation in enumerate(plan.evidence_obligations, start=1):
            marker = (
                "未覆盖"
                if obligation in state.uncovered_evidence_obligations
                else "已绑定证据"
            )
            print(f"- E{index} [{marker}]：{obligation}")
        if plan.exact_literals:
            print(f"- 精确检索词：{'; '.join(plan.exact_literals)}")
        if plan.search_queries:
            print(f"- 发现检索词：{'; '.join(plan.search_queries)}")
    if state.exploration_log:
        print("\n最近的检索轨迹：")
        recent_steps = state.exploration_log[-20:]
        if len(state.exploration_log) > len(recent_steps):
            print(f"- ……省略较早的 {len(state.exploration_log) - len(recent_steps)} 步")
        for step in recent_steps:
            query = f" query={step.query!r}" if step.query else ""
            summary = f" -> {step.result_summary}" if step.result_summary else ""
            print(f"- {step.tool_name} {step.path}{query}{summary}")
    if state.evidence:
        print("\n已记录证据：")
        for item in state.evidence[-12:]:
            print(f"- {item.citation_key}：{item.summary}")
    print(
        "\n执行次数："
        f"Explorer {state.exploration_attempts} / "
        f"Reasoner {state.reasoning_attempts} / "
        f"Critic {state.review_attempts}"
    )
    if state.run_id:
        print(f"Run ID: {state.run_id}")
    print(f"\nWorkflow status: {state.status}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
