# MultiAgentFileAnalysis
基于 Agentic RAG 的知识库构建以及智能 QA。项目抛弃传统 embedding 向量检索路线，改用“虚拟文件系统 + 精确检索工具 + 多智能体协作”的方式，让模型像工程师一样按目录、文件和关键词逐步查证知识。

## 当前阶段

本仓库当前先搭建项目的大致架构，不包含完整业务实现。核心目标是先明确模块边界、数据流和 Agent 职责，后续再逐步补充索引加载、虚拟工具、图状态机编排和问答执行逻辑。

## 架构文档

- [项目架构说明](docs/architecture.md)
- [示例 Page Index](configs/page_index.example.yaml)

## 顶层模块

```text
src/multi_agent_file_analysis/
  agents/      多智能体角色定义：Explorer、Reasoner、Critic
  graph/       图状态机、共享状态与流程编排
  hitl/        Human-in-the-Loop 人在回路交互边界
  index/       Page Index 静态索引结构与加载入口
  vfs/         虚拟文件系统浏览协议：v_ls、v_cat、v_grep
```
