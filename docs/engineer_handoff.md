# 工程师接手指南

## 当前状态

仓库已经具备可运行 MVP，不再只是接口骨架：

- 索引、VFS、词法搜索和证据验证已实现；
- 三 Agent、有界工作流和 HITL 已实现；
- OpenAI 兼容网关、CLI、审计和本地入库已实现；
- 主入口语料选择、选中目录隔离与多问题连续会话已实现；
- CHM 的有界解包、目录/编码恢复、HTML 与表格规范化、来源元数据和缓存已实现；
- 复杂结构化测试语料已加入；
- 自动化测试覆盖关键安全边界。

首先运行：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
mafa --dry-run "GW-004 错误是什么原因？"
```

## 推荐阅读顺序

1. `README.md`
2. `docs/architecture.md`
3. `docs/core_logic.md`
4. `src/multi_agent_file_analysis/graph/state.py`
5. `src/multi_agent_file_analysis/vfs/protocol.py`
6. `src/multi_agent_file_analysis/graph/workflow.py`
7. `tests/`

## 下一阶段优先级

### P0：真实评测

- 固定官方 Ubuntu、OpenSSH 和 systemd 文档快照；
- 建立带标准证据和拒答标签的排错问题集；
- 比较 exact-only、当前词法搜索、BM25、混合召回、单 Agent 和多 Agent；
- 报告证据召回、诊断正确率、误放行率、Token、费用和延迟。

### P1：检索升级

- 用持久化 SQLite FTS5/BM25 替换当前懒构建的内存倒排目录和轻量正文计数；
- 增加标题/章节索引和冲突来源检测；
- 支持可选语义召回，但保持最终原文核验；
- 为大目录和搜索结果增加游标而不只是 offset。

### P1：服务化

- 把会话状态从进程内字典迁移到持久化存储；
- 增加 tenant/session/run 隔离；
- 给 HITL 请求增加过期时间、目标环境摘要和响应 schema；
- 增加 HTTP API、认证、速率限制和日志脱敏。

### P2：入库扩展

- PDF 与独立 HTML 结构化转换；
- 为 CHM 增加 CSS/专有控件降级报告、表格黄金样本和超大语料性能基准；
- 来源白名单、签名、发布日期和版本回滚；
- 自动生成目录摘要并由人工审核；
- 对更新后的文件进行增量索引。

## 修改约定

- 新证据字段必须保持可序列化并补测试；
- 新 VFS 工具必须同时定义输入上限、输出上限和审计字段；
- 任何审批异常都应 fail-closed；
- 不允许 Finalizer 在 Critic 后新增模型内容；
- 不允许把用户日志标成知识库规则；
- 不要把复杂测试语料描述为官方生产手册。
