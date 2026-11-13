# hitl/runtime-trust

## Purpose

定义人工回填内容的信任边界：它可以支撑用户自己环境中的事实，但不得成为文档规则；
同时保证追问次数有界、命令建议被拒时可见，使 HITL 流程可收敛、可解释。

## Requirements

### Requirement: 运行时上下文带信任等级

系统 SHALL 为每条运行时上下文记录信任等级；由人机回填产生的内容 MUST 标记为
`user_asserted`，且 MUST 保留其所属请求标识。

#### Scenario: 回填落库

- **WHEN** 用户对等待中的 run 提交非空补充内容
- **THEN** 该内容以 `user_asserted` 记入运行时上下文，并携带原请求标识

#### Scenario: 非 HITL 输入

- **WHEN** 工作流在未配置 HITL 会话时收到用户补充
- **THEN** 该内容同样标记为 `user_asserted`，不默认为已核验事实

### Requirement: 用户回填可用于条件化结论

Reasoner SHALL 能使用 `user_asserted` 内容作为用户环境的运行时事实；该内容 MUST NOT
被用作文档规则或配置含义的依据。

#### Scenario: 端口值来自用户

- **WHEN** 用户回填 `Port 22` 且文档未声明端口
- **THEN** 系统可以给出「按你提供的端口为 22」的条件化结论，并说明文档未声明该值

#### Scenario: 用户声称文档规则

- **WHEN** 用户回填内容声称“手册规定 X 应开启”
- **THEN** 该陈述不得作为文档规则证据，仍须由已核验引句支撑规则含义

### Requirement: 审查能看到运行时依据

Critic SHALL 收到本次 run 的运行时上下文及其信任等级；依赖 `user_asserted` 的断言
MUST 在草稿中显式标注来源，未标注的运行时断言视为未支持。

#### Scenario: 未标注的运行时断言

- **WHEN** 草稿使用用户回填的端口值但未标注来自用户
- **THEN** Critic 要求补充标注，不因该值来自用户而直接批准

#### Scenario: 显式标注

- **WHEN** 草稿写明该值由用户提供且未验证
- **THEN** 该断言可随结论一起进入最终答案

### Requirement: 最终输出区分运行时依据

最终答案 SHALL 在存在 `user_asserted` 内容时输出独立的运行时依据段，标注「用户提供，
未验证」，并 MUST NOT 将其混入文档证据来源。

#### Scenario: 带运行时依据的答案

- **WHEN** 最终答案使用了用户回填的运行时事实
- **THEN** 答案包含运行时依据段，逐条列出请求标识与内容摘要

#### Scenario: 无运行时依据

- **WHEN** 本次 run 未收到任何用户回填
- **THEN** 不输出空的运行时依据段

### Requirement: 追问次数有上限

系统 SHALL 限制同一 run 的人工回填恢复次数；达到上限后 MUST 终止为放弃状态并输出
阶段性答案，MUST NOT 继续要求用户补充同一事实。

#### Scenario: 达到上限

- **WHEN** 恢复次数达到配置上限后系统仍需要运行时事实
- **THEN** run 以放弃结束，阶段性答案写明「缺少运行时事实」，不再发起新的追问

#### Scenario: 暂停不计数

- **WHEN** 工作流暂停等待用户输入但用户尚未回复
- **THEN** 暂停本身不计入恢复次数

#### Scenario: 上限可配置为零

- **WHEN** 配置将恢复上限设为 0
- **THEN** 任何需要人工事实的场景直接以放弃结束，不发起追问

### Requirement: 被拒命令可见

安全门禁拒绝模型建议的命令时，系统 SHALL 保留拒绝原因与被拒命令的可读预览，供用户
判断；该预览 MUST NOT 被任何执行路径使用。

#### Scenario: 命令因管道被拒

- **WHEN** 建议命令为 `sshd -T | grep -i port`
- **THEN** 请求中显示拒绝原因与被拒命令预览，且不提供可执行命令

#### Scenario: 预览仅展示

- **WHEN** 客户端或工作流读取被拒命令预览
- **THEN** 该内容只用于展示，不进入命令执行或审计 payload
