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
3. Explorer 是唯一使用 VFS 的 Agent；
4. 模型生成的引句必须逐字存在于来源文件；
5. Reasoner 不能修改原始证据；
6. Critic 解析失败必须保持未批准；
7. 最终回答只能由已批准草案确定性生成；
8. 工作流失败、放弃和等待状态不能被覆盖成完成；
9. HITL 恢复必须回到 Reasoner；
10. 模型建议的命令必须通过只读门禁，系统永不自动执行。

## 3. 无命中与冲突

“精确搜索无命中”不等于“知识库没有该规则”。Explorer 应先使用元数据和词法搜索扩大召回，再对候选使用 grep 和范围读取核验。

遇到多个版本或冲突规则时，证据必须保留版本、作用域和适用条件。缺少环境标识时，Reasoner 应请求补充信息或给出条件化结论。

## 4. 审查回退

- `NEEDS_MORE_EVIDENCE`：携带缺失主题返回 Explorer；
- `NEEDS_REVISION`：携带不支持的结论返回 Reasoner；
- `REJECTED`：立即失败；
- 超出审查预算：进入 `ABSTAINED`，不生成伪完成答案。

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

## 6. 审计

审计日志记录工作流启停、状态转移、Agent 启停、工具调用、HITL 请求与恢复。日志表示决策和工具轨迹，不声称保存或公开模型内部思维链。
