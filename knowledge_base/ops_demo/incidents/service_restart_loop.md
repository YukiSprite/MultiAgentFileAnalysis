# 事故案例：web-api 重启次数少于预期

## 症状

值班人员在 vendor unit 中看到 `Restart=always`，但服务停止自动重启，并且不同环境
观察到的最大尝试次数不同。

## 易错结论

直接引用 vendor unit 会遗漏完整站点覆盖和 drop-in。直接把 legacy-lab 的
`StartLimitBurst=3` 用于 current-lab 也属于版本适用错误。

## 调查路径

1. 通过环境矩阵选择 systemd profile；
2. 按 unit 解析规则检查主 unit 与 drop-in；
3. 对照 profile 的重启策略和限制窗口；
4. 获取退出原因、当前状态和 unit 展开结果；
5. 区分正常退出、失败退出和达到启动限制。

## 证据要求

最终结论必须同时引用公共 unit 解析规则和对应版本的 restart policy。
