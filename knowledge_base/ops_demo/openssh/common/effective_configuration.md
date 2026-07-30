# OpenSSH 有效配置判定流程

## 前置条件

在分析转发、认证或监听问题前，必须先确定：

1. 环境对应的 OpenSSH profile；
2. 目标用户及其分组；
3. 连接来源地址；
4. 问题属于客户端配置还是服务端配置。

缺少任一会改变条件匹配结果的信息时，应进入人在回路。

## 证据层级

该测试语料把服务端转发判定拆成三层：

1. profile 的全局默认值；
2. `Match` 条件下的站点策略；
3. 目标主机输出的有效配置观察。

配置文件中出现某个参数名，不代表该值适用于目标用户。诊断必须同时引用 profile
规则和匹配条件。

## 只读现场确认

基准允许建议以下只读命令形态：

```text
sshd -T
```

需要条件展开时，用户应根据实际环境补充目标用户、主机和来源地址。模型不得自行连接
服务器，也不得建议重启服务来“验证”配置。

## 相关文档

- `/openssh/ssh-policy-a/forwarding_policy.md`
- `/openssh/ssh-policy-b/forwarding_policy.md`
- `/safety/diagnostic_commands.md`
