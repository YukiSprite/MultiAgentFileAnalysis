# systemd unit 与 drop-in 解析规则

## 适用范围

本文件定义本测试语料的 unit 解析模型，适用于两个 systemd profile。

## 三类来源

测试环境包含以下来源：

1. `/usr/lib/systemd/system/web-api.service`：vendor unit；
2. `/etc/systemd/system/web-api.service`：可选的完整站点覆盖；
3. `/etc/systemd/system/web-api.service.d/*.conf`：drop-in 片段。

如果完整站点覆盖文件存在，测试基准选择它作为主 unit，而不是 vendor unit。
随后按文件名顺序应用 drop-in 片段。

## 标量与列表

`Restart=` 和 `StartLimitBurst=` 在本基准中按标量处理，后应用的值覆盖先前值。
列表型设置必须先查对应规则；不得把标量覆盖逻辑无条件推广到所有 directive。

## 诊断要求

只在 vendor unit 中找到 `Restart=always`，不能证明最终有效值是 `always`。
必须继续检查完整覆盖文件、drop-in 列表以及环境对应的 profile。

## 只读现场确认

允许通过以下命令形态让用户查看 unit 与 drop-in：

```text
systemctl cat web-api.service
systemctl show web-api.service --no-pager
```
