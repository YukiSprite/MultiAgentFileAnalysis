# web-console/run

## Purpose

让一次证据约束的诊断 run 可以在浏览器端异步提交、查询结果并响应现场信息请求，
而不需要 HTTP 连接等待整个多阶段工作流完成。

## Requirements

### Requirement: 异步提交

提交问题 SHALL 立即返回 run 标识，实际诊断在后台执行，HTTP 响应 MUST NOT 等待
工作流结束。

#### Scenario: 提交后立即返回

- **WHEN** 客户端在一个有效会话中提交非空问题
- **THEN** 立即收到 run 标识和初始状态，诊断在后台继续

#### Scenario: 空问题被拒绝

- **WHEN** 客户端提交空白或缺失的问题
- **THEN** 请求被拒绝并返回明确错误，不创建 run

#### Scenario: 会话不存在

- **WHEN** 客户端向不存在的会话提交问题
- **THEN** 返回会话不存在，不创建 run

### Requirement: 并发与串行

同一会话内的 run SHALL 顺序执行；不同会话的 run MAY 并行执行，且不得共享诊断状态。

#### Scenario: 同会话排队

- **WHEN** 同一会话已有 run 正在执行时又提交新问题
- **THEN** 新 run 排队并保持可查询状态，不并发修改同一会话

#### Scenario: 跨会话并行

- **WHEN** 两个不同会话同时提交问题
- **THEN** 两者各自独立执行，结果与证据互不影响

### Requirement: run 状态查询

查询 SHALL 返回 run 的生命周期状态，并在结束时返回答案文本、是否为阶段性答案、
终止原因的机器可读信息，以及该次 run 的用量与分阶段耗时度量。

#### Scenario: 运行中查询

- **WHEN** 客户端查询仍在执行的 run
- **THEN** 返回运行中状态与当前阶段，不返回伪造答案

#### Scenario: 完成查询

- **WHEN** run 以通过审查结束
- **THEN** 返回完成状态、最终答案，且阶段性标记为假

#### Scenario: 未通过查询

- **WHEN** run 以放弃、失败或等待人工输入结束
- **THEN** 返回对应状态、阶段性答案，且阶段性标记为真

#### Scenario: 结束时返回度量

- **WHEN** 客户端查询一个已结束的 run
- **THEN** 响应中包含分角色 token 合计与各阶段耗时

#### Scenario: 运行中不给出未发生阶段的耗时

- **WHEN** 客户端查询仍在执行的 run
- **THEN** 度量只覆盖已发生的阶段，未执行阶段不出现耗时数值

### Requirement: 现场信息恢复

当 run 处于等待人工输入状态时，客户端 SHALL 能提交一段补充内容使流程继续进行，
且恢复后 MUST 从推理阶段继续而不是重新检索。run 查询响应中的现场信息请求 SHALL
包含命令审批状态、拒绝原因与被拒命令预览，使客户端能解释命令缺失的原因；被拒命令
预览 MUST NOT 可执行。

#### Scenario: 恢复等待中的 run

- **WHEN** 客户端对等待人工输入的 run 提交非空补充内容
- **THEN** run 回到运行状态并从推理阶段继续

#### Scenario: 非等待状态恢复

- **WHEN** 客户端对不处于等待人工输入的 run 提交补充内容
- **THEN** 请求被拒绝并返回当前状态

#### Scenario: 命令被安全门禁拒绝

- **WHEN** 模型建议的命令未通过只读白名单
- **THEN** 查询响应包含审批为假的标记、拒绝原因与被拒命令预览，且不提供可执行命令

#### Scenario: 命令通过门禁

- **WHEN** 建议命令通过只读白名单
- **THEN** 查询响应包含审批为真的标记与可直接展示的命令

### Requirement: 会话级 dry-run

会话 SHALL 在创建时确定是否使用 dry-run；dry-run 会话 MUST NOT 调用外部模型，
并 SHALL 在其所有响应中标明该模式。

#### Scenario: dry-run 不调用模型

- **WHEN** 会话以 dry-run 创建并提交问题
- **THEN** 不发起任何模型请求，run 仍返回确定性检索结果

#### Scenario: dry-run 标识随响应返回

- **WHEN** 客户端查询 dry-run 会话下的 run
- **THEN** 响应中包含 dry-run 标识
