# 工程师接手指南

这份文档给后续开发者提供接手路线。当前项目已经有明确架构，但多数函数仍是接口契约，业务逻辑需要按阶段补上。

## 1. 接手时先读什么

建议阅读顺序：

1. `README.md`：确认项目定位。
2. `docs/architecture.md`：看总体架构。
3. `docs/core_logic.md`：理解核心约束和运行逻辑。
4. `docs/module_reference.md`：查每个模块负责什么。
5. `configs/page_index.example.yaml`：理解虚拟知识库索引格式。
6. `src/multi_agent_file_analysis/graph/state.py`：理解共享状态。

## 2. 当前代码状态

当前代码是“可导入的架构契约”，不是可运行产品。

已经具备：

- 清晰包结构。
- dataclass 类型模型。
- Protocol / interface 边界。
- Agent、VFS、Index、Graph、HITL、Audit、LLM、QA 等模块划分。
- 架构文档和示例配置。

尚未具备：

- YAML 加载实现。
- VFS 实际文件读取和搜索实现。
- LLM provider 实现。
- Agent prompt 和推理逻辑。
- Workflow 状态流转实现。
- CLI/API。
- 测试用例。

## 3. 推荐开发分支顺序

### 第一阶段：索引和 VFS 最小闭环

目标：不用 LLM，也能用 Python 调用 VFS 浏览知识库。

建议实现：

- `PageIndexLoader.load()`
- `PageIndexLoader.validate()`
- `PageIndexRepository.get_node()`
- `PageIndexRepository.list_children()`
- `PageIndexRepository.resolve_source_path()`
- `VirtualFileSystem.v_ls()`
- `VirtualFileSystem.v_grep()`
- `VirtualFileSystem.v_cat()`

验收标准：

- 示例 `page_index.example.yaml` 可以加载。
- `v_ls("/")` 能列出 `/examples`。
- `v_cat("/examples/README.md")` 能读取内容并报告是否截断。
- `v_grep("/examples/README.md", "Agent")` 能返回命中行。

### 第二阶段：审计和状态流转

目标：能记录系统每一步做了什么。

建议实现：

- 一个内存版或 JSONL 版 `AuditRecorder`。
- `ExplorerNode.run()`、`ReasonerNode.run()`、`CriticNode.run()` 的最小状态转移。
- `DiagnosisWorkflow.plan()` 和最小 `run()`。

验收标准：

- 每个阶段会更新 `DiagnosisState.stage`。
- 工具调用和阶段变化能写入审计事件。
- Workflow 可以停在 `WAITING_FOR_HUMAN` 或 `COMPLETED`。

### 第三阶段：Agent 最小智能

目标：接入 LLM，跑通 Explorer -> Reasoner -> Critic。

建议实现：

- 一个具体 `LLMClient`。
- Explorer 的关键词规划和证据抽取 prompt。
- Reasoner 的诊断草案 prompt。
- Critic 的证据一致性审查 prompt。

验收标准：

- 最终回答能引用证据来源。
- Critic 能驳回没有证据支持的草案。
- 缺少运行时信息时能生成 `HumanRequest`。

### 第四阶段：HITL 和产品入口

目标：用户可以完成一次交互式问答。

建议实现：

- `HITLSession.suspend()`
- `HITLSession.apply_response()`
- `QAService.ask()`
- `QAService.resume()`
- 简单 CLI。

验收标准：

- 系统可以暂停并提示用户补充信息。
- 用户输入回填后可以恢复同一份 `DiagnosisState`。
- 最终回答中包含证据和安全建议。

## 4. 开发约定

1. 保持 `src/` 包内只放可复用代码。
2. 示例知识库放 `knowledge_base/`，私有资料放 `.gitignore` 已忽略的目录。
3. 不要让 Agent 直接读真实路径。
4. 不要在 Workflow 中写 prompt。
5. 不要在 `QAService` 中写底层检索逻辑。
6. 新增模块时同步更新 `docs/module_reference.md`。
7. 新增状态字段时同步解释 `docs/core_logic.md`。

## 5. 测试建议

建议按风险从低到高补测试：

- `tests/index/`：索引加载、路径规范化、越界路径拦截。
- `tests/vfs/`：目录浏览、文件截断、grep 上下文。
- `tests/graph/`：状态转移、HITL 暂停恢复。
- `tests/agents/`：使用 fake LLM 验证 prompt 输入输出结构。
- `tests/e2e/`：用小型知识库跑完整 QA。

## 6. 容易踩坑的点

- 不要把 `knowledge_base/` 当普通文件夹递归喂给模型。
- 不要用向量相似度替代 `v_grep` 的精确证据。
- 不要把用户回填日志直接当成可信结论，仍要经过 Reasoner 和 Critic。
- 不要让 Critic 只做文字润色，它必须审查证据一致性。
- 不要让 `v_cat` 返回超长文件，长文档应引导 Agent 使用 `v_grep`。
