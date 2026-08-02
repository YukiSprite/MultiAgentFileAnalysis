# 核心逻辑与不变量

## 1. 在线诊断

```text
QARequest
  → bounded lexical retrieval
  → verified EvidenceItem[]
  → DiagnosisDraft 或 HumanRequest
  → deterministic critic preflight
  → semantic critic review（非 dry-run）
  → deterministic final answer
```

Dry-run 不执行因果推理，只展示检索到的可验证证据。

## 2. 必须保持的不变量

1. Agent 不能绕过 Page Index 读取知识库；
2. 真实路径必须位于配置的知识库根目录；
3. Explorer 是唯一使用 Unix 工具门面和 VFS 的 Agent；
4. 模型生成的引句必须逐字存在于来源文件；
5. Reasoner 不能修改原始证据；
6. Critic 解析失败必须保持未批准；
7. 最终回答只能由已批准草案确定性生成；
8. 工作流失败、放弃和等待状态不能被覆盖成完成；
9. HITL 恢复必须回到 Reasoner；
10. 模型建议的命令必须通过只读门禁，系统永不自动执行。
11. `ls/grep/cat` 等名称只能映射到结构化 VFS 操作，不能调用真实 Shell。
12. 对文档事实和规则，已逐字核验的索引原文优先于用户问题、描述、假设和回忆；
    冲突必须显式保留，不能默认按用户说法消解。
13. 交互入口选中一个语料后，Page Index 与知识库根目录都必须限定在该语料；
    未选择目录不能只靠提示词隐藏。
14. 单文件检索预算不得低于系统允许读取的源文件上限，否则一个已成功索引的文档
    会出现“文件存在但尾部永远搜不到”的假阴性；跨文件检索另设总字符预算，并在
    达到预算时明确返回 `truncated`。

## 3. 无命中与冲突

“精确搜索无命中”不等于“知识库没有该规则”。Explorer 应先使用元数据和词法搜索扩大召回，再对候选使用 grep 和范围读取核验。
模型生成的检索计划不是证据。系统可以用它驱动 VFS 预检索，但只有逐字核验的正文
引文才能覆盖证据义务；标题、目录和主题相关但不陈述规则的片段不得用于满足门禁。

遇到多个版本或冲突规则时，证据必须保留版本、作用域和适用条件。缺少环境标识时，Reasoner 应请求补充信息或给出条件化结论。

## 4. 审查回退

- `NEEDS_MORE_EVIDENCE`：携带缺失主题返回 Explorer；
- `NEEDS_REVISION`：携带不支持的结论返回 Reasoner；
- `REJECTED`：立即失败；
- 超出审查预算：进入 `ABSTAINED`，不生成伪完成答案，但必须返回明确标注为未批准
  的阶段性断言、已核验原文、证据缺口与停止原因。

## 5. 离线入库

`KnowledgeBaseBuilder` 支持本地 Markdown 和文本：

```text
DocumentSource
  → IngestionPlan
  → normalized Markdown
  → versioned IndexNode tree
  → Page Index YAML
```

生成索引会记录相对 source 路径、SHA-256 和内容类型。生产环境还应增加来源签名、发布日期、官方版本及更新回滚策略。

`ChmImporter` 为 CHM 增加一条先规范化、后索引的管线：

```text
CHM archive
  → bounded extraction
  → encoding + .hhc TOC recovery
  → deterministic HTML/GFM conversion
  → expanded table grid + rewritten local links/assets
  → provenance frontmatter + manifest
  → atomic mount publication
  → Page Index rebuild
```

CHM 原文件不会成为 VFS 节点，在线 Agent 只看到规范化后的 Markdown。缓存必须同时
匹配归档名称与哈希、manifest/转换器版本、资源复制选项和单页上限；`--force`
替换时先保留备份，只有新暂存目录发布成功后才删除旧目录。

## 6. 审计

审计日志记录工作流启停、状态转移、Agent 启停、工具调用、HITL 请求与恢复。日志表示决策和工具轨迹，不声称保存或公开模型内部思维链。
