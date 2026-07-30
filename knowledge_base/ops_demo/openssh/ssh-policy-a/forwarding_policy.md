# ssh-policy-a：转发规则

## 适用范围

本文件仅适用于 `legacy-lab`，站点策略版本为 `site-policy-2024`。

## 全局规则

```text
AllowTcpForwarding yes
```

在该测试 profile 中，`yes` 表示允许本地和远程 TCP 转发。全局规则不能单独证明某个
用户的连接一定被允许，还必须检查条件块。

## 条件规则

```text
Match Group restricted
    AllowTcpForwarding local
```

`restricted` 组只能进行本地转发。该 profile 没有定义 `contractors` 组的额外
转发限制。

## 诊断要求

如果用户只报告“隧道不可用”，必须区分本地转发与远程转发，并确认用户是否属于
`restricted`。不得把本文件用于 `current-lab`。
