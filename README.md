# MultiAgentFileAnalysis
基于 Agentic RAG 的知识库构建以及智能 QA。项目抛弃传统 embedding 向量检索路线，改用“虚拟文件系统 + 精确检索工具 + 多智能体协作”的方式，让模型像工程师一样按目录、文件和关键词逐步查证知识。

## 当前阶段

本仓库当前已进入“具体架构”阶段：代码中已经定义应用层、Agent 层、图状态机、虚拟文件系统、索引、审计、LLM 网关和人在回路等模块的接口契约，但仍不包含具体函数实现。后续可以按模块逐步填充索引加载、虚拟工具、图状态机编排和问答执行逻辑。

## 架构文档

- [项目架构说明](docs/architecture.md)
- [核心逻辑说明](docs/core_logic.md)
- [模块参考](docs/module_reference.md)
- [工程师接手指南](docs/engineer_handoff.md)
- [示例 Page Index](configs/page_index.example.yaml)

建议后续工程师按 `README -> architecture -> core_logic -> module_reference -> engineer_handoff` 的顺序阅读。

## 顶层模块

```text
src/multi_agent_file_analysis/
  app.py       应用装配入口：把配置、索引、VFS、Agent、Workflow 和 QA Service 串起来
  agents/      多智能体角色定义：Explorer、Reasoner、Critic
  audit/       审计事件与记录器接口
  core/        领域枚举和异常边界
  graph/       图状态机、共享状态与流程编排
  hitl/        Human-in-the-Loop 人在回路交互边界
  ingestion/   知识库构建和 Page Index 生成管线
  index/       Page Index 静态索引结构与加载入口
  llm/         模型网关的 provider-neutral 接口
  qa/          对外 QA 服务门面
  vfs/         虚拟文件系统浏览协议：v_ls、v_cat、v_grep
```
