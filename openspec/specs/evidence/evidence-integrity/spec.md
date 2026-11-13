# evidence/evidence-integrity

## Purpose

约束证据摘要与逐字引句的范围一致性，使「引句已核验」不会被下游误读为「摘要中的
全部主张已核验」，并在越界时把流程送回补证而不是让推理与审查空转。

## Requirements

### Requirement: 摘要不得超出引文范围

`record_evidence` SHALL 在接受证据前比较摘要与引句中的配置值类 token；引句未包含的
摘要 token MUST 导致该条证据被拒绝，并向 Explorer 说明缺失内容。

token 规则只覆盖可判定的技术值：ASCII 字母数字串长度不小于 2，且包含 `=`、`.`、
`:`、`/`、`-`、`_` 之一或包含数字。

#### Scenario: 摘要包含引句外配置值

- **WHEN** Explorer 提交的摘要提到 `Restart=always`，而引句只覆盖「drop-in 把最终
  `Restart=` 改为 `on-failure`」两行
- **THEN** 证据不被写入，返回信息指出 `Restart=always` 未出现在引句中，并提示扩大
  引文范围或从摘要中移除该主张

#### Scenario: 摘要与引句一致

- **WHEN** 摘要中的全部配置值类 token 都出现在引句内
- **THEN** 证据按现有逐字核验流程写入，`verified` 语义保持不变

#### Scenario: 纯中文改写

- **WHEN** 摘要使用中文复述引句含义且不含技术值 token
- **THEN** 包含校验不拒绝该证据，交由审查阶段判断语义是否越界

### Requirement: 摘要在下游显式降级

Reasoner 与 Critic 的证据上下文中，摘要 SHALL 标注为模型摘要而非证据；最终答案
MUST 使用引句渲染证据来源，不得使用摘要。

#### Scenario: 推理上下文标注

- **WHEN** Reasoner 收到带摘要与引句的证据
- **THEN** prompt 中摘要被标记为模型生成、非证据，并要求以引句为准

#### Scenario: 最终答案证据来源

- **WHEN** Critic 批准草稿并渲染最终答案
- **THEN** 「证据来源」行的内容取自引句首句，而不是摘要

#### Scenario: CLI 展示

- **WHEN** 命令行输出“已记录证据”
- **THEN** 摘要带有「模型摘要，未逐字核验」标注

### Requirement: 摘要越界可归因并改道

当 Critic 返回 `needs_revision` 且列出的全部无依据主张都能归因为「某条摘要包含该
token、而对应引句不包含」时，系统 SHALL 将决策归一为 `needs_more_evidence` 并路由
到 Explorer；不可归因时 MUST 保持原有 `needs_revision` 路由。

#### Scenario: 全部主张可归因

- **WHEN** Critic 三次指出的无依据主张都来自摘要超出引句的部分
- **THEN** 第一次即改道 Explorer 补引文范围，不再回 Reasoner 重写

#### Scenario: 主张与证据无关

- **WHEN** Critic 列出的无依据主张无法由任何摘要 token 归因（例如草稿自造的因果句）
- **THEN** 保持 `needs_revision` 并返回 Reasoner 修改表达

#### Scenario: 部分可归因

- **WHEN** 无依据主张中一部分可归因、一部分不可
- **THEN** 不强制改道，保持 Reasoner 路径，并在审查说明中保留两类主张

### Requirement: 越界证据不被删除

摘要越界的证据 SHALL 保留在运行状态中；系统 MUST NOT 因摘要问题删除已逐字核验的
引句。

#### Scenario: 补证后复用

- **WHEN** Explorer 因摘要越界被要求扩大引文范围
- **THEN** 原证据仍可被引用，新增或替换的证据独立记录
