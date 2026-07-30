# 模块参考

## `app.py` / `config.py`

`ApplicationFactory` 校验配置并装配 Index、VFS、LLM、Agent、HITL、Workflow、Audit 和 QA Service。`AppConfig` 集中定义目录分页、文件大小、搜索文件数、模型轮次、审查重试和用户输入等预算。

## `ingestion/`

- `DocumentSource`：本地 Markdown/text 来源与元数据；
- `KnowledgeBaseBuilder`：规划、归一化、复制文档并生成 Page Index；
- 当前仅支持本地文件，远程抓取和 PDF 转换属于后续离线扩展。

## `index/`

- `PageIndexLoader`：加载、校验和扫描目录；
- `PageIndexRepository`：查询节点、迭代文件并解析安全真实路径；
- `IndexNode.metadata`：保存版本、产品、权威级别和校验和。

## `vfs/`

- `v_ls`：分页单层目录；
- `v_search`：元数据感知词法召回；
- `v_grep`：文件或目录字面搜索；
- `v_cat` / `v_read_range`：有界范围读取；
- `verify_quote`：把引句绑定到路径、行号、章节和哈希。

## `agents/`

- `ExplorerAgent`：使用 VFS，提交可验证 EvidenceItem；
- `ReasonerAgent`：生成 DiagnosisDraft 或 HumanRequest；
- `CriticAgent`：确定性预检、语义审查和最终渲染；
- `AgentContext`：注入 LLM 与审计器。

## `graph/`

- `DiagnosisState`：单次 run 的类型化状态；
- `DiagnosisWorkflow`：执行预算、状态转移、回退、挂起与终止；
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

`QAService` 提供 `ask`、`resume` 和按 run ID 恢复。CLI 支持 `index`、`ask`、交互模式、dry-run 和旧式省略 `ask` 的快捷写法。
