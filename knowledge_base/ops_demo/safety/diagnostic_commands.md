# 只读诊断命令策略

## 原则

模型只负责说明缺少的现场事实。命令必须通过确定性的白名单检查后才能展示给用户，
用户仍需确认目标主机和数据敏感性。

## 允许的示例形态

```text
systemctl status web-api.service --no-pager
systemctl cat web-api.service
systemctl show web-api.service --no-pager
journalctl -u web-api.service -n 100 --no-pager
sshd -T
```

## 禁止自动建议的操作

- 启动、停止、重启、启用或禁用服务；
- 修改配置文件、权限、防火墙或软件包；
- 使用管道、重定向、命令替换或网络外传；
- 无边界读取全部日志；
- 使用 `sudo` 提升权限。

需要变更系统状态时，必须进入独立的人工变更流程，并包含备份、影响评估、回滚和二次确认。
