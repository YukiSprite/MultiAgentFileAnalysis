# observability/run-metrics Specification

## Purpose
为一次诊断 run 提供可离线统计的用量与耗时账本，使成本、延迟与预算调优不再依赖猜测，
并让不同检索与 Agent 配置可以在同一口径下比较。

## Requirements

### Requirement: 用量按角色累积

每个 run SHALL 维护一份按 agent 角色分组的用量记录，包含 prompt tokens、
completion tokens、total tokens 与模型调用次数。

#### Scenario: 多轮 Explorer 汇总

- **WHEN** Explorer 在一次 run 中依次完成多次模型调用
- **THEN** 账本中 Explorer 的调用次数等于实际调用次数，token 数为各次之和

#### Scenario: 三阶段分别计数

- **WHEN** 一次 run 依次经过 Explorer、Reasoner、Critic 并各自调用模型
- **THEN** 账本按三个角色分别保留计数，且合计等于三者之和

#### Scenario: 多轮审查回退

- **WHEN** Critic 退回后 Reasoner 或 Explorer 再次调用模型
- **THEN** 追加的调用计入对应角色，不覆盖此前的计数

### Requirement: 调用失败也记账

模型调用失败时系统 SHALL 在对应角色上记一次失败，MUST NOT 因异常丢失已累计的用量。

#### Scenario: 单次调用抛错

- **WHEN** 某角色的模型调用抛出异常
- **THEN** 该角色失败计数加一，此前累计的 token 与调用次数保持不变

### Requirement: 分阶段耗时

每个工作流阶段 SHALL 记录进入与离开之间的单调时钟耗时，并可汇总为本次 run 的总耗时。

#### Scenario: 阶段耗时可见

- **WHEN** 一次 run 结束
- **THEN** 每个实际执行过的阶段都带有非负耗时，且总耗时不小于任一单阶段耗时

#### Scenario: 时钟回退不计负值

- **WHEN** 阶段结束时读取到的时钟值小于进入时的值
- **THEN** 该阶段耗时记为 0 而不是负数

### Requirement: 各执行路径账本结构一致

dry-run、文本协议回退与原生工具调用三种路径 SHALL 产出结构相同的账本；无法获取
用量的路径 MUST 记为 0，而不是省略字段。

#### Scenario: dry-run 账本存在

- **WHEN** 一次 dry-run run 结束
- **THEN** 结果仍带完整账本结构，全部 token 计数为 0，阶段耗时正常记录

#### Scenario: 文本回退有真实用量

- **WHEN** 端点不支持原生工具调用而回退到文本 JSON 协议
- **THEN** 该次调用的用量仍计入账本，与原生路径字段一致

### Requirement: 度量随运行结果对外暴露

系统 SHALL 通过命令行摘要、QA 响应与 web run 查询暴露同一份度量，三者数值一致。

#### Scenario: 命令行摘要

- **WHEN** 通过命令行完成一次 run
- **THEN** 输出包含阶段耗时与 token 合计的一行摘要

#### Scenario: web 查询一致

- **WHEN** 客户端查询已结束的 run
- **THEN** 返回的 token 与阶段耗时与命令行摘要一致

#### Scenario: 运行中不伪造

- **WHEN** 客户端查询仍在执行的 run
- **THEN** 只返回截至当前已发生的度量，不给出未发生阶段的耗时

### Requirement: 审计可离线统计

终止审计记录 SHALL 携带度量摘要，使其可以仅凭审计日志计算单次 run 的 token 与
阶段耗时。

#### Scenario: 从日志统计

- **WHEN** 只读取一次 run 的终止审计记录
- **THEN** 能从中得到该 run 的分角色 token 合计与各阶段耗时

### Requirement: 不内置价格换算

系统 SHALL 只输出 token 计数与耗时，MUST NOT 将用量换算为货币金额。

#### Scenario: 输出不含金额

- **WHEN** 任一执行路径返回度量
- **THEN** 度量中不包含货币字段或硬编码单价
