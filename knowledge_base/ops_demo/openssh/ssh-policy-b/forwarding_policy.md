# ssh-policy-b：转发规则

## 适用范围

本文件仅适用于 `current-lab`，站点策略版本为 `site-policy-2026`。

## 全局规则

```text
AllowTcpForwarding yes
```

全局默认允许 TCP 转发，但后续匹配到的站点条件可能进一步限制特定用户组。

## contractors 条件

```text
Match Group contractors
    DisableForwarding yes
```

在该测试 profile 中，只要用户属于 `contractors`，`DisableForwarding yes`
就禁止该连接的所有转发能力。此时，全局的 `AllowTcpForwarding yes` 不能用来证明
隧道应当成功。

## automation 条件

```text
Match Group automation
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:5432
```

`automation` 组只允许本地转发，并把目标限制为测试数据库端点。目标地址不匹配时，
即使转发类型正确也应拒绝。

## 诊断要求

最终诊断至少需要环境、用户分组、转发方向和目标地址。任何一项未知时，都只能给出
条件化假设或请求补充信息。
