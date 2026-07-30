# 结构化运维排错基准语料

> 状态：测试基准，不是 Ubuntu、systemd 或 OpenSSH 的官方操作手册。

该语料用于验证 MultiAgentFileAnalysis 是否能够处理以下复杂性：

- 同一配置符号在不同版本、作用域和文件中重复出现；
- 全局规则、条件块、站点策略和运行时状态共同决定结果；
- vendor unit、完整覆盖文件和 drop-in 片段之间存在优先级；
- 故障案例只描述症状，需要跨文档定位规范参数；
- 问题缺少环境版本或用户分组时，系统必须请求补充信息；
- 最终结论必须引用版本化原文，不能只引用故障案例标题。

语料定义了两个虚构环境：

- `legacy-lab`：旧版测试环境；
- `current-lab`：当前测试环境。

所有规则仅用于本项目测试。真实排错必须换成对应发行版的官方文档快照。

## 推荐测试问题

1. current-lab 中 `alice` 属于 `contractors`，为什么全局允许转发但隧道仍被拒绝？
2. 只知道“SSH 隧道不可用”，还缺少哪些环境信息？
3. `web-api.service` 在 current-lab 中为什么只重启两次？
4. vendor unit 设置了 `Restart=always`，为什么最终配置却是 `on-failure`？
5. legacy-lab 的转发规则能否直接用于 current-lab？
