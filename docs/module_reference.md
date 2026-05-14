# 模块参考

这份文档按代码目录解释每个模块的职责、重要类型和后续实现位置。接手工程师可以用它快速判断“这个逻辑应该写在哪里”。

## `src/multi_agent_file_analysis/app.py`

应用装配层。

- `ApplicationFactory.build()`：后续负责读取 `AppConfig`，创建 `PageIndexLoader`、`PageIndexRepository`、`VirtualFileSystem`、三个 Agent、`DiagnosisWorkflow` 和 `QAService`。
- `ApplicationServices`：装配完成后的服务集合，便于 CLI、API 或测试一次性拿到所有入口。

不要在这里写业务算法。这里只做对象创建、依赖注入和配置校验。

## `config.py`

应用配置。

- `page_index_path`：Page Index 文件路径。
- `knowledge_base_root`：真实知识库根目录。
- `run_mode`：交互、批处理或 dry-run。
- `model_name`：默认模型名。
- `audit_log_path`：审计日志输出路径。
- `max_file_chars`、`grep_context_lines`、`max_grep_hits`：VFS 预算配置。

后续如果配置项变多，可以增加 `from_env()` 或 `from_yaml()`，但不要让业务模块直接读环境变量。

## `core/`

跨模块共享的领域语言。

- `types.py`：放枚举，例如 `WorkflowStage`、`AgentRole`、`ReviewDecision`。
- `errors.py`：放项目级异常边界。

实现建议：业务层应该抛这里定义的异常，CLI/API 再把异常转换成用户可读错误。

## `ingestion/`

知识库构建流程。

- `DocumentSource`：原始资料。
- `IngestedDocument`：归一化后的文档。
- `IngestionPlan`：入库计划。
- `KnowledgeBaseBuilder`：构建管线。

这里处理离线数据清洗、格式转换和索引生成。在线问答流程不应该调用这里的重型处理逻辑。

## `index/`

虚拟文件系统的地图。

- `IndexNode`：虚拟目录或文件节点。
- `SourceDocument`：真实文档元数据。
- `PageIndex`：整棵虚拟树。
- `PageIndexLoader`：加载和校验 YAML。
- `PageIndexRepository`：按虚拟路径查节点、列目录、解析真实文件路径。

实现重点：

- 严格校验 `source` 不允许逃出 `knowledge_base_root`。
- 虚拟路径应规范化，避免 `..`、重复斜杠和大小写混乱。
- 目录节点不能映射真实 `source`，文件节点必须能解析到真实文档。

## `vfs/`

Agent 访问知识库的唯一工具层。

- `VirtualFileSystem.v_ls()`：列出一级目录。
- `VirtualFileSystem.v_cat()`：读取一个虚拟文件。
- `VirtualFileSystem.v_grep()`：精确搜索。
- `VfsAccessPolicy`：访问控制边界。

实现重点：

- 不允许递归暴露整棵树。
- `v_cat` 必须做长度截断，并告诉调用方是否截断。
- `v_grep` 应返回命中行和上下文行，不应返回整篇文档。
- 所有工具调用都应写审计事件。

## `llm/`

模型供应商隔离层。

- `LLMClient.complete()`：统一模型调用接口。
- `LLMRequest` / `LLMResponse`：统一消息结构。

后续可以实现 `OpenAIClient`、`LocalModelClient` 等 provider，但 Agent 层只依赖 `LLMClient`。

## `agents/`

多智能体角色边界。

- `ExplorerAgent`：只负责检索和提炼证据。
- `ReasonerAgent`：只负责诊断推理和 HITL 判断。
- `CriticAgent`：只负责证据一致性和安全审查。
- `AgentContext`：注入 run id、LLM、审计器等运行期依赖。

实现时不要让 Reasoner 或 Critic 接触 VFS。这个限制是项目减少幻觉的重要设计。

## `graph/`

状态机和共享状态。

- `DiagnosisState`：所有节点共享的状态容器。
- `WorkflowPlan`：静态流程图声明。
- `ExplorerNode`、`ReasonerNode`、`CriticNode`、`HITLNode`：节点适配器。
- `DiagnosisWorkflow`：负责编排节点。

实现重点：

- Workflow 负责“下一步去哪”，Agent 负责“这一步产出什么”。
- Workflow 不应该解析文档、不应该写 prompt 细节。
- 每次阶段变化都应该更新 `state.stage` 和 `state.status`。

## `hitl/`

人在回路。

- `HumanRequest` 在 `graph.state` 中定义，表示系统需要用户补充的信息。
- `HumanResponse` 表示用户回填结果。
- `HITLSession` 负责挂起和恢复状态。
- `HumanChannel` 是后续 CLI、WebSocket、HTTP 等交互通道的抽象。

实现时要优先保证安全：建议命令应尽量只读，且不要自动执行。

## `audit/`

审计与追踪。

- `AuditEvent`：结构化事件。
- `AuditEventType`：事件类型。
- `AuditRecorder`：事件输出接口。

推荐先实现 JSONL 文件记录器，后续再接数据库或观测平台。

## `qa/`

对外应用服务。

- `QAService.ask()`：开始一次新诊断。
- `QAService.resume()`：恢复一次等待用户输入的诊断。
- `QARequest` / `QAResponse`：外部接口数据结构。

CLI/API 不应该直接操作底层 Agent，优先通过 `QAService` 保持入口统一。
