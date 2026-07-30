# unit-policy-a：重启与启动限制

## 适用范围

本文件仅适用于 `legacy-lab`。

## 主 unit

```ini
[Service]
Restart=always
RestartSec=2s
```

## 站点 drop-in

`20-restart-policy.conf`：

```ini
[Service]
Restart=on-failure
```

`40-start-limit.conf`：

```ini
[Unit]
StartLimitIntervalSec=60s
StartLimitBurst=3
```

## 有效规则

在此 profile 中，drop-in 把最终 `Restart=` 改为 `on-failure`。在 60 秒窗口内，
测试基准最多允许 3 次启动尝试；超过后进入启动限制状态。
