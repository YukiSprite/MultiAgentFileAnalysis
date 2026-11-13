# MultiAgentFileAnalysis

面向版本化、跨文档、具有配置覆盖关系的运维知识库，提供受控检索、证据绑定、多阶段诊断、审查与人在回路能力。

项目当前是一个可运行的 MVP。它不把精确检索和语义检索视为二选一：当前实现提供元数据感知的词法检索、目录导航和字符级核验，并为后续接入 BM25 或语义召回保留 VFS 接口。任何进入推理阶段的证据都必须能够逐字回查到已登记的 Markdown 源文件。

## 已实现能力

- Page Index YAML 加载、校验、目录扫描和路径隔离；
- 启动时知识库菜单、单语料 VFS 挂载和连续问答会话；
- 模型原生 function calling，以及不支持时的 JSON 文本回退；
- `pwd/cd/ls/find/stat/cat/head/tail/grep/search` Unix 风格只读工具；
- 元数据、别名和正文联合排序的词法 `search`；
- Explorer、Reasoner、Critic 三阶段工作流；
- 原文引句、行号、版本、章节和内容哈希组成的证据包；
- Critic fail-closed、审查回退预算和确定性最终渲染；
- HITL 暂停/恢复及只读诊断命令白名单；
- 内存与 JSONL 审计日志；
- 本地 Markdown/text 入库管线；
- CHM 安全解包、目录解析、编码识别、HTML/表格到 Markdown 的离线预处理；
- 单文件入门语料和多版本复杂运维基准语料；
- FastAPI + 单页 H5 控制台：语料选择、异步诊断、SSE 进度、证据抽屉与轨迹面板；
- 自动化测试。

## 安装

需要 Python 3.11 以上。三个平台一致，不要求虚拟环境、PATH 配置或安装本包：

```bash
python -m pip install -r requirements.txt
python mafa.py
```

macOS 和 Ubuntu 通常写成 `python3`。`mafa.py` 会把 `src/` 加入模块搜索路径，因此
不执行 `pip install -e .` 也能运行；不带参数时启动控制台并打印地址。

如果希望全局使用 `mafa` 命令（可选）：

```bash
python -m pip install -e .
mafa
```

Conda 用户也可以：

```bash
conda create -n mafa python=3.12 -y
conda activate mafa
pip install -r requirements.txt
python mafa.py
```

下文命令中的 `mafa` 都可以等价写成 `python mafa.py`。

## 快速验证

Dry-run 不调用模型，只完成词法检索、证据绑定、规则审查和确定性输出：

```bash
mafa --dry-run "GW-004 错误是什么原因？"
```

也可以使用显式子命令：

```bash
mafa ask --dry-run "RATE_LIMIT_RPS 的默认值是什么？"
```

## 主入口

直接运行 `mafa`，不带参数，会启动浏览器控制台并在终端打印可点击链接：

```bash
mafa
```

```text
MAFA 控制台：http://127.0.0.1:8765/
会话只存在于当前进程；按 Ctrl+C 停止。
```

浏览器打开该地址，选择一个语料即可开始。端口和会话上限可以显式指定：

```bash
mafa web --port 8765 --max-sessions 8 --idle-minutes 30
```

终端问答仍然保留，用 `mafa chat` 进入：

```bash
mafa chat
```

```text
可用知识库：
  1. DND [dnd]
  2. OpenSSH [openssh]
  3. systemd [systemd]
  ...
请选择知识库编号（输入 /quit 退出）：
```

选中后，系统只扫描对应的实际目录，把该目录重新挂载成 Agent 所见的 `/`。例如
选择 DND 后，OpenSSH 目录不会进入本次 Page Index；选择 OpenSSH 后，DND 文件也
无法通过 `find`、`grep`、`search` 或 `cat` 访问。这是路径与索引级隔离，不依赖
模型自行遵守提示词。

回答完成后进程会继续等待下一个问题，模型客户端、索引和检索缓存都在该会话中
复用。输入 `/quit`、`/exit` 或 `/q` 才退出。可用以下命令测试而不调用模型：

```bash
mafa chat --dry-run
```

这里没有需要同步维护的中央知识库清单。发现规则为：

- CHM 转换目录通过其 `manifest.json` 自动成为独立知识库；
- 顶层目录只要包含 Markdown 文件，就会自动成为独立知识库；
- 当一个顶层目录内包含多个知识库时，在各自目录放置 `.mafa-corpus.yaml` 作为
  边界标记。路径由标记文件所在位置推导，标记只提供可选的 `id`、`name` 和
  `description` 展示信息。

因此，新建或删除实际知识库目录后，下次启动菜单会直接反映变化；无需修改 Python
代码或中央 YAML。`mafa ask ...` 和旧式 `mafa "问题"` 仍保留为执行一次后退出的
脚本接口。

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

复制示例文件并填写 OpenAI 或兼容接口配置。CLI 默认自动加载当前工作目录的
`.env`，但不会覆盖已经由 shell 或进程管理器设置的环境变量：

```bash
cp .env.example .env
```

```dotenv
OPENAI_API_KEY="..."
OPENAI_MODEL="gpt-4o"
OPENAI_TEMPERATURE="0.0"
OPENAI_REASONING_EFFORT="max"
OPENAI_TOOL_MODE="auto"

# 本地兼容接口可选
OPENAI_BASE_URL="http://localhost:8000/v1"
```

从其他目录运行时，可以通过 `--env-file /path/to/.env` 指定配置文件。

`OPENAI_TOOL_MODE=auto` 默认先使用 OpenAI 兼容的原生 `tool_calls`；如果端点明确
拒绝工具参数，会在当前客户端实例中自动切换到文本 JSON 协议。可设置为 `native`
强制原生调用，或设置为 `text` 强制兼容模式。

`OPENAI_TEMPERATURE` 默认为 `0.0`，统一作用于 Explorer、Reasoner 和 Critic。
单次底层 `LLMRequest` 仍可显式覆盖该值。低温会减少随机发挥，但“来源文本优先于
用户描述”主要由来源核验、提示词中的证据优先级和 Critic 审查共同保证，并不只
依赖温度。

`OPENAI_REASONING_EFFORT` 是必填配置，没有代码默认值，可设置为 `low`、`high`
或 `max`，并统一作用于 Explorer、Reasoner 和 Critic。缺失或取值非法时，真实
模型模式会在启动阶段直接报配置错误。

运行：

```bash
mafa
mafa "GW-004 的原因和排查步骤是什么？"
mafa ask --interactive
mafa --audit-log runs/example.jsonl "问题内容"
```

如果 Reasoner 缺少现场事实，工作流会暂停。模型生成的命令只有通过只读白名单后才会显示；系统不会自动执行命令。

### Explorer 的 Unix 工作区

Explorer 看到的是根目录为 `/` 的只读虚拟工作区，可以像文件 Agent 一样调用：

```text
pwd
ls /openssh
find / -name "*forward*"
grep "DisableForwarding" /openssh
cat /openssh/current/forwarding.md
stat /openssh/current/forwarding.md
```

这些名字是原生 function tools，不会启动 Linux Shell。相对路径和 `cd` 只在单次
Explorer 会话内生效；所有路径最终仍由 Page Index 和 VFS 校验。`rm`、`mv`、
`bash`、重定向、管道以及宿主机路径均不可用。

每轮检索先由模型把问题拆成“证据义务、精确专名、通用规则短查询”。系统通过同一
VFS 预执行这些模型选择的 `grep/search`，把真实结果交回 Explorer。每条
`record_evidence` 引文还必须声明它直接支持哪些证据义务；只记录若干无关标题或
索引行不能通过结束门禁。失败输出会显示最后一次计划及仍未覆盖的义务，便于判断是
未找到原文、未读取正文，还是模型没有正确绑定证据。

等待现场信息、最终未通过 Critic 或工作流失败时，CLI 和 QA API 都不会返回空答案。
系统会确定性渲染一份醒目标记为“尚未/未通过最终审查”的阶段性回答，包含最后的
暂定断言、已逐字核验的来源片段、尚缺前提和停止原因。未批准草稿中的操作建议不会
进入这份阶段性输出。

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

## 导入 CHM

CHM 不会直接交给在线 Agent。系统先在离线入库阶段解包，将其中的 HTML、目录和
图片规范化为普通 Markdown 语料，再沿用 Page Index、VFS、Unix 工具和证据核验
流程。

Python 依赖已包含在 `requirements.txt` 中；此外需要系统提供
`extract_chmLib`。Ubuntu 上通常可安装 `libchm-bin`，也可以通过
`--extractor /path/to/extract_chmLib` 显式指定可执行文件。

```bash
mafa ingest-chm knowledge_base/your-example.chm \
  --mount-name your-example \
  --knowledge-base knowledge_base \
  --output configs/page_index.chm.yaml
```

转换结果位于 `knowledge_base/chm_imports/your-example/`，包括：

- 每个 HTML 页面对应的 UTF-8 Markdown 文件；
- 从 `.hhc` 恢复的 `CONTENTS.md` 层级目录；
- 本地栅格图片资源及已重写的相对链接；
- 每页 YAML frontmatter 中的原始 CHM 名称、SHA-256、内部路径、源编码和目录路径；
- `manifest.json` 转换统计与告警。

HTML 表格会输出为 GFM 管道表格。由于 Markdown 没有 `rowspan`/`colspan`，合并
单元格的值会被重复填入其覆盖的格子，避免静默丢失表头或数据；脚本、隐藏元素和
危险 URL scheme 会被移除。

归档名称、哈希、转换器/manifest 版本、资源复制选项和单页上限均一致时，再次导入
会命中缓存。任一转换条件变化时使用 `--force` 原子替换原有 mount。导入过程限制
归档大小、解包后总大小、文件数、单页大小和超时，并拒绝符号链接、越界路径与可
携带主动内容的 SVG 资源。

可通过 `--max-archive-mb`、`--max-extracted-mb`、`--max-extracted-files`、
`--max-page-mb` 和 `--timeout` 收紧默认预算；使用 `--no-assets` 可完全跳过图片复制
及对应图片链接。

```bash
mafa ask \
  --page-index configs/page_index.chm.yaml \
  --knowledge-base knowledge_base \
  "在已导入手册中查询你的问题"
```

仓库默认忽略 `*.chm` 和 `knowledge_base/chm_imports/`。这意味着本地范例 CHM 与
批量转换结果不会被 Git 提交；如果未来确实要版本化某一份规范化语料，应先单独
审查许可、体积和内容，再有意调整忽略规则。

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

## H5 控制台

`mafa` 不带参数时就是控制台。也可以显式调用：

```bash
mafa web \
  --knowledge-base knowledge_base \
  --env-file .env \
  --host 127.0.0.1 \
  --port 8765
```

安装后直接运行 `mafa` 即可。打开 `http://127.0.0.1:8765/`，选择一个语料开始。

控制台会做三件命令行做不到的事：把阶段与工具调用实时推给页面；把回答拆成
"最终 / 阶段性"两种视觉状态；把已核验证据、检索义务覆盖和 Critic 决策放进可展开的
细节面板。

运行约束：

- **只支持单进程**。会话、索引目录和运行状态都在进程内存中，多 worker 下请求会
  落到没有该会话的进程并返回 `session_not_found`。
- **会话不持久化**。进程重启或会话空闲超时（默认 30 分钟）后需要重新选择语料。
- **`dry-run` 是会话级开关**，创建会话时决定。dry-run 不调用模型，只做确定性检索与
  证据核验，适合在无 API Key 时验证界面和检索链路。
- 界面仅面向本地或可信内网，不提供鉴权。

## 核心流程

```text
用户问题
  → Explorer：模型检索计划 → VFS 预检索 → Unix 工具 → 逐项原文证据绑定
  → Reasoner：基于已验证证据形成草案或请求现场信息
  → Critic：确定性检查 + 模型语义审查
  → 通过：确定性渲染最终回答
  → 不通过：有界返回 Explorer/Reasoner，超限后输出明确标注的阶段性回答
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
