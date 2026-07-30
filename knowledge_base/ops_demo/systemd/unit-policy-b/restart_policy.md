# unit-policy-b：重启与启动限制

## 适用范围

本文件仅适用于 `current-lab`。

## vendor unit

```ini
[Service]
Restart=always
RestartSec=1s
```

## 完整站点覆盖

`/etc/systemd/system/web-api.service`：

```ini
[Service]
ExecStart=/opt/web-api/bin/server
Restart=on-failure
RestartSec=5s
```

## drop-in

`50-site-limit.conf`：

```ini
[Unit]
StartLimitIntervalSec=120s
StartLimitBurst=2
```

## 有效规则

完整站点覆盖使 vendor unit 中的 `Restart=always` 不再是主配置；最终值为
`Restart=on-failure`。在 120 秒窗口内，测试基准最多允许 2 次启动尝试。

## 例外

正常退出不会触发 `on-failure` 重启。仅凭“进程停止”无法判断是否应该重启，还需要
退出原因或服务状态观察。
