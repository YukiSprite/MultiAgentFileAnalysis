# 模块参考

## `app.py` / `config.py`

`ApplicationFactory` 先从当前工作目录的 `.env`（或 `AppConfig.env_file_path` 指定文件）加载模型配置，再校验配置并装配 Index、VFS、LLM、Agent、HITL、Workflow、Audit 和 QA Service。加载遵循 `override=False`，不会覆盖现有进程环境变量。`AppConfig` 集中定义目录分页、文件大小、搜索文件数、单文件与跨文件搜索字符数、候选文档数、模型轮次、审查重试和用户输入等预算。单文件搜索上限与可接受源文件上限一致，避免大文件尾部不可检索；跨文件总预算负责限制整体开销。`mount_corpus` 把"扫描一个语料 → 生成临时 Page Index → 装配服务"封装成 `CorpusMount`，索引目录由挂载对象持有并在 `close()` 时删除；CLI 与控制台共用该入口。`ApplicationFactory.build` 也接受外部注入的 `audit_recorder`，供控制台把审计事件扇出到事件总线。

## `corpora.py` / `.mafa-corpus.yaml`

- `CorpusCatalog`：扫描实际目录，动态发现 CHM mount、顶层 Markdown 目录和显式的
  嵌套知识库边界；
- `.mafa-corpus.yaml`：可选的就地边界和展示元数据，不保存路径，也不是中央清单；
- `CorpusDefinition.resolve_root`：拒绝绝对路径、根目录逃逸和语料根符号链接；
- `mafa chat`：提示用户选择一个可用语料，为其生成会话级 Page Index，并把 VFS
  真实根锁定到该语料目录。

## `ingestion/`

- `DocumentSource`：本地 Markdown/text 来源与元数据；
- `KnowledgeBaseBuilder`：规划、归一化、复制文档并生成 Page Index；
- `ChmExtractor`：校验 ITSF 魔数，在独立进程组中运行 `extract_chmLib`，并持续执行
  超时、文件数、总字节、符号链接和路径边界检查；
- `ChmImporter`：解析 `.hhc`、转换页面、复制图片、生成来源 frontmatter、目录与
  manifest，并通过暂存目录原子发布后重建 Page Index；
- `HtmlToMarkdownConverter`：以确定性方式处理 legacy/Word HTML、列表、代码、链接、
  图片和表格；`rowspan`/`colspan` 被扩展为 GFM 矩形网格；
- 远程抓取和 PDF 转换属于后续离线扩展。

## `index/`

- `PageIndexLoader`：加载、校验和扫描目录；
- `PageIndexRepository`：查询节点、迭代文件并解析安全真实路径；
- `IndexNode.metadata`：保存版本、产品、权威级别和校验和。

## `vfs/`

- `UnixFileSystemSession`：为单次 Explorer 运行提供 `/` 根目录、相对路径和 `cd`；
- `pwd/cd/ls/find/stat/cat/head/tail/grep/search`：模型可见的 Unix 风格函数工具；
- `v_ls`：分页单层目录；
- `v_search`：懒构建倒排目录、有界候选筛选、元数据感知召回和查询词局部共现摘要；
- `v_grep`：文件或目录字面搜索，可限制返回命中数；
- `v_find` / `v_stat`：节点 glob 查找和索引元数据读取；
- `v_cat` / `v_read_range`：有界范围读取；
- `verify_quote`：把引句绑定到路径、行号、章节和哈希。

## `llm/`

- `LLMToolDefinition` / `LLMToolCall`：供应商中立的原生工具定义与调用对象；
- `OpenAICompatibleClient`：序列化 `tools/tool_choice/tool_calls/tool_call_id`；
- `OPENAI_TEMPERATURE`：所有 Agent 共用的默认采样温度，默认 `0.0`，请求级参数可覆盖；
- `OPENAI_REASONING_EFFORT`：所有 Agent 共用的必填推理强度，没有代码默认值，
  可取 `low/high/max`；
- `OPENAI_TOOL_MODE=auto|native|text`：控制原生调用和文本回退策略。

## `agents/`

- `ExplorerAgent`：先让模型生成有界检索计划，通过 VFS 预执行计划种子，再使用原生
  Unix 工具或 JSON 回退；每条 EvidenceItem 必须绑定其直接支持的证据义务，全部
  义务覆盖后才能结束；
- `ReasonerAgent`：生成 DiagnosisDraft 或 HumanRequest；
- `CriticAgent`：确定性预检、语义审查和最终渲染；模型错误地同时返回
  `needs_revision` 与非空 `missing_evidence` 时，客户端会归一为补证并路由 Explorer；
- `AgentContext`：注入 LLM 与审计器。

## `graph/`

- `DiagnosisState`：单次 run 的类型化状态；
- `DiagnosisWorkflow`：执行预算、状态转移、回退、挂起与终止；
- `partial.py`：为等待、失败或放弃状态确定性渲染带警示的阶段性断言与证据；
- `nodes.py`：Agent 与工作流之间的薄适配层。

## `hitl/`

- `HITLSession`：校验、保存和恢复用户输入；
- `SafeCommandBroker`：只读命令形态白名单；
- `HumanRequest`：带 request ID、审批状态和未展示原因的信息请求。

## `audit/`

- `MemoryAuditRecorder`：测试与调试；
- `JsonlAuditRecorder`：追加式本地审计；
- `AuditEventType`：覆盖开始、恢复、阶段、工具、HITL、完成和失败。

## `qa/` / `cli.py`

`QAService` 提供 `ask`、`resume` 和按 run ID 恢复。CLI 支持 `web`、`index`、
`ingest-chm`、`chat`、`ask`、dry-run 和旧式省略 `ask` 的快捷写法。不带参数运行
`mafa` 等价于 `mafa web`：启动控制台并打印可点击链接；`mafa chat` 进入终端连续
问答，每次回答后继续接收新问题。

## `web/`

- `sessions.py`：`SessionRegistry` 持有 `sid → WebSession`，每个会话绑定一个
  `CorpusMount`，独占其临时索引；滑动空闲 TTL、会话数上限和显式关闭都在这里；
- `jobs.py`：`JobRunner` 用线程池执行同步的 `QAService.ask/resume`，同一会话用
  `WebSession.lock` 串行，不同会话并行；等待人工输入发布 `pause`，真正结束才发布
  唯一的 `terminal`；
- `events.py`：`EventBus` 为每个 run 保留有界事件环，订阅时先回放快照再接收实时
  增量；`FanoutAuditRecorder` 把同一条审计事件同时写入内存、可选 JSONL 和事件总线，
  单个接收端失败不会中断诊断；
- `serializers.py`：只输出可呈现内容。阶段性结果不带未批准的操作建议，未通过门禁的
  建议命令不出现，证据标记"草稿引用 / 未引用"；
- `server.py`：FastAPI 路由（语料、会话、run、SSE、静态页），错误统一为
  `{"error": {"code", "message"}}`；
- `static/`：无构建单页，`is_partial` 使用警示样式并常驻"未通过最终审查"标记。

会话只存在于创建它的进程内，因此部署时必须单 worker。
