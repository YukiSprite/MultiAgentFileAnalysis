# MultiAgentFileAnalysis

面向版本化、跨文档、具有配置覆盖关系的运维知识库，提供受控检索、证据绑定、多阶段诊断、审查与人在回路能力。

项目当前是一个可运行的 MVP。它不把精确检索和语义检索视为二选一：当前实现提供元数据感知的词法检索、目录导航和字符级核验，并为后续接入 BM25 或语义召回保留 VFS 接口。任何进入推理阶段的证据都必须能够逐字回查到已登记的 Markdown 源文件。

## 已实现能力

- Page Index YAML 加载、校验、目录扫描和路径隔离；
- 分页 `v_ls`、范围读取 `v_cat/v_read_range`；
- 文件或目录级 `v_grep`；
- 元数据、别名和正文联合排序的 `v_search`；
- Explorer、Reasoner、Critic 三阶段工作流；
- 原文引句、行号、版本、章节和内容哈希组成的证据包；
- Critic fail-closed、审查回退预算和确定性最终渲染；
- HITL 暂停/恢复及只读诊断命令白名单；
- 内存与 JSONL 审计日志；
- 本地 Markdown/text 入库管线；
- 单文件入门语料和多版本复杂运维基准语料；
- 自动化测试。

## 安装

```bash
conda create -n mafa python=3.12 -y
conda activate mafa
pip install -r requirements.txt
pip install -e .
```

## 快速验证

Dry-run 不调用模型，只完成词法检索、证据绑定、规则审查和确定性输出：

```bash
mafa --dry-run "GW-004 错误是什么原因？"
```

也可以使用显式子命令：

```bash
mafa ask --dry-run "RATE_LIMIT_RPS 的默认值是什么？"
```

## 复杂结构化语料

`configs/page_index.ops_demo.yaml` 对应一套多目录、跨版本、带作用域和覆盖关系的测试基准。它明确是测试语料，不是生产操作手册。

```bash
mafa ask \
  --dry-run \
  --page-index configs/page_index.ops_demo.yaml \
  --knowledge-base knowledge_base \
  "current-lab 中 alice 属于 contractors，为什么全局允许转发但隧道仍被拒绝？"
```

语料覆盖：

- `legacy-lab` 与 `current-lab` 的 profile 选择；
- OpenSSH 全局规则与条件规则冲突；
- systemd vendor unit、完整站点覆盖和 drop-in；
- 症状优先的事故案例；
- 信息不足时必须追问的答案边界；
- 只读诊断命令策略。

## 使用模型

配置 OpenAI 或兼容接口：

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o"

# 本地兼容接口可选
export OPENAI_BASE_URL="http://localhost:8000/v1"
```

运行：

```bash
mafa "GW-004 的原因和排查步骤是什么？"
mafa --interactive
mafa --audit-log runs/example.jsonl "问题内容"
```

如果 Reasoner 缺少现场事实，工作流会暂停。模型生成的命令只有通过只读白名单后才会显示；系统不会自动执行命令。

## 建立自己的索引

把 Markdown 文件放入 `knowledge_base/`，然后生成索引：

```bash
mafa index \
  --knowledge-base knowledge_base \
  --output configs/page_index.yaml
```

使用生成的索引：

```bash
mafa ask \
  --page-index configs/page_index.yaml \
  --knowledge-base knowledge_base \
  "你的问题"
```

手写 Page Index 时，`source` 必须相对于 `--knowledge-base`：

```yaml
- path: "/openssh/current/forwarding.md"
  kind: file
  description: "Current forwarding rules and scope conditions."
  source: "openssh/current/forwarding.md"
  tags: ["openssh", "forwarding"]
  aliases: ["AllowTcpForwarding", "SSH tunnel"]
  metadata:
    product: "openssh"
    version: "snapshot-id"
    authority: "official"
```

## 核心流程

```text
用户问题
  → Explorer：VFS 导航、搜索、原文证据绑定
  → Reasoner：基于已验证证据形成草案或请求现场信息
  → Critic：确定性检查 + 模型语义审查
  → 通过：确定性渲染最终回答
  → 不通过：有界返回 Explorer/Reasoner，超限后明确放弃
```

工作流是带有界回退和挂起/恢复能力的有限状态机，不是严格 DAG。

## 安全边界

当前代码可以强制：

- Agent 只能访问 Page Index 注册的文件；
- 真实路径解析后必须位于知识库根目录；
- 单次目录、文件、搜索结果和工作流迭代都有预算；
- 模型生成的证据引句必须在源文件中逐字存在；
- Critic 解析失败不会默认批准；
- 审查后的最终文本不会再交给模型自由改写；
- HITL 命令拒绝 shell 组合、重定向、提权和状态变更。

当前代码不能保证：

- 知识库内容本身正确或最新；
- 有原文出处的推理一定正确；
- 用户回填的日志来自正确主机；
- 人工不会执行系统之外的危险操作；
- 多 Agent 一定比单 Agent 更准确或更便宜。

这些能力需要版本化官方语料、威胁模型和基准评测继续验证。

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 文档

- [架构说明](docs/architecture.md)
- [核心逻辑](docs/core_logic.md)
- [模块参考](docs/module_reference.md)
- [工程师接手指南](docs/engineer_handoff.md)
- [简单索引示例](configs/page_index.example.yaml)
- [复杂运维索引示例](configs/page_index.ops_demo.yaml)
