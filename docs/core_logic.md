# 核心逻辑说明

这份文档面向后续接手工程师，解释 MultiAgentFileAnalysis 的核心运行逻辑。当前代码只实现架构契约，不实现具体业务函数；因此这里描述的是后续实现时应遵守的系统行为。

## 1. 这个项目解决什么问题

项目目标是做一个面向知识库问答和排错诊断的 Agentic RAG 框架。它不走传统向量库路线，而是把知识库变成一个受控的虚拟文件系统，让模型按“看目录 -> 读文件 -> 精确搜索 -> 提取证据 -> 推理 -> 审查”的方式工作。

传统 RAG 的主要风险是语义相似度会把名字相近、语义相近但规则不同的内容混在一起。这个项目更重视符号级准确性，尤其适合配置项、日志、错误码、命令参数、版本差异等场景。

## 2. 核心不变量

后续实现时应尽量保护这些不变量：

1. Agent 不能直接读真实文件系统中的知识库文件。
2. Explorer 是唯一允许使用 VFS 工具的 Agent。
3. Reasoner 不直接检索知识库，只基于共享状态中的证据推理。
4. Critic 必须根据证据审查草案，不应凭空相信 Reasoner。
5. 系统不能直接操作用户真实环境，需要真实环境信息时只能触发 HITL。
6. 每次工具调用、Agent 运行、HITL 暂停和恢复都应进入审计事件。
7. 最终回答必须能追溯到 `DiagnosisState.evidence` 中的证据。

## 3. 两条主流程

### 3.1 离线知识库构建流程

离线流程由 `ingestion` 和 `index` 两层负责，产物供在线问答使用。

```text
DocumentSource
  -> KnowledgeBaseBuilder.plan()
  -> KnowledgeBaseBuilder.ingest()
  -> IngestedDocument
  -> KnowledgeBaseBuilder.build_index()
  -> PageIndex + Markdown Knowledge Base
```

关键点：

- `DocumentSource` 描述原始资料来源，可以是本地文件、远端文档、导出的 Markdown、PDF 转换结果等。
- `IngestedDocument` 是已经归一化后的知识库文档，后续应尽量统一为 Markdown。
- `PageIndex` 是虚拟文件系统地图，定义虚拟路径、摘要、标签、真实源文件映射。
- `KnowledgeBaseBuilder` 不参与在线推理，它只负责把资料整理成可被 VFS 安全读取的形式。

### 3.2 在线 QA / 排错流程

在线流程由 `qa`、`graph`、`agents`、`vfs`、`hitl`、`audit` 协作完成。

```text
QARequest
  -> QAService.ask()
  -> DiagnosisWorkflow.run()
  -> ExplorerAgent
  -> VirtualFileSystem
  -> DiagnosisState.evidence
  -> ReasonerAgent
  -> DiagnosisState.diagnosis_draft
  -> CriticAgent
  -> DiagnosisState.critic_report
  -> final_answer 或 human_request
```

关键点：

- `QAService` 是外部入口，后续 CLI、API Server、测试都应该优先调它。
- `DiagnosisWorkflow` 负责状态流转，不应直接写检索、推理或审查细节。
- `DiagnosisState` 是所有节点共享的唯一状态容器，后续不要在 Agent 内部维护隐式全局状态。
- `ExplorerAgent` 将 VFS 返回的内容压缩为证据，不应直接生成最终答案。
- `ReasonerAgent` 生成草案，如果缺少真实运行时状态，则写入 `human_request`。
- `CriticAgent` 根据证据做一致性审查，决定通过、补证或修改草案。

## 4. 为什么需要虚拟文件系统

虚拟文件系统层承担三个职责：

1. 限制可见范围：Agent 只看到 Page Index 暴露的虚拟目录和文件。
2. 限制读取方式：长文件读取、精确搜索、目录浏览都可以统一做截断和审计。
3. 保持可解释性：每次 `v_ls`、`v_cat`、`v_grep` 都可以记录到审计日志和探索轨迹。

后续实现中，`VirtualFileSystem` 不应该绕过 `PageIndexRepository` 直接扫描 `knowledge_base/`。真实路径解析应集中在 `PageIndexRepository.resolve_source_path()`。

## 5. 多 Agent 分工

### ExplorerAgent

Explorer 的任务是找证据，不是回答问题。它应该：

- 根据用户问题提取关键词、错误码、配置项、日志片段。
- 调用 `v_ls` 找到可能相关的文档区域。
- 调用 `v_grep` 做精确匹配。
- 必要时调用 `v_cat` 阅读短文档或命中片段附近内容。
- 将规则、配置说明、日志解释等写入 `DiagnosisState.evidence`。
- 将每次工具调用写入 `DiagnosisState.exploration_log`。

### ReasonerAgent

Reasoner 的任务是基于证据推理。它应该：

- 读取用户问题、用户上下文、运行时上下文和 Explorer 提供的证据。
- 生成 `DiagnosisDraft`，包括概要、可能原因、建议动作和引用证据。
- 如果缺少真实环境状态，生成 `HumanRequest`，让流程进入 HITL。
- 不应该调用 VFS，也不应该声称证据中不存在的事实。

### CriticAgent

Critic 的任务是审查。它应该：

- 检查草案中每条判断是否能在 `evidence` 中找到依据。
- 检查建议动作是否越权、危险或没有前置确认。
- 输出 `CriticReport`，决定 `APPROVED`、`NEEDS_MORE_EVIDENCE`、`NEEDS_REVISION` 或 `REJECTED`。

## 6. 人在回路

HITL 是安全边界，不是用户体验点缀。任何需要真实环境状态的操作都应该通过 HITL 完成。

例如系统需要知道某个配置项当前值时，Reasoner 不应该猜测，也不应该自动 SSH 到服务器。它应该写入：

- `HumanRequest.prompt`：告诉用户为什么需要这项信息。
- `HumanRequest.suggested_command`：给出建议运行的只读命令。
- `HumanRequest.expected_input`：说明希望用户贴回什么格式的结果。

用户回填后，`HITLSession.apply_response()` 将结果归入 `DiagnosisState.runtime_context`，再由 workflow 恢复 Reasoner。

## 7. 审计与可追溯性

审计层后续应记录至少这些事件：

- 工作流开始、阶段变化、结束。
- Agent 开始和结束。
- VFS 工具调用及结果摘要。
- HITL 请求和用户响应。
- Critic 审查决策。

审计日志不是可选装饰。这个项目的一个核心价值就是回答可以解释：系统看了哪些目录、搜了哪些关键词、证据来自哪些文件、为什么最后通过或驳回。

## 8. 推荐实现顺序

1. 实现 `PageIndexLoader`，让示例 YAML 能加载成 `PageIndex`。
2. 实现 `PageIndexRepository`，支持虚拟路径查询和真实路径解析。
3. 实现 `VirtualFileSystem`，先做 `v_ls` 和 `v_grep`，再做 `v_cat` 截断。
4. 实现一个最小 `AuditRecorder`，先输出到内存或本地 JSONL。
5. 实现 `ExplorerAgent` 的规则抽取最小闭环。
6. 实现 `DiagnosisWorkflow` 的阶段流转。
7. 接入 `ReasonerAgent` 和 `CriticAgent` 的 LLM prompt。
8. 补 HITL 暂停与恢复。
9. 最后再做 CLI/API、测试样例和更复杂的知识库构建。
