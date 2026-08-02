# Knowledge Base

这里存放映射进虚拟文件系统的 Markdown 知识库文档。

Agent 不应直接访问这一层的真实文件路径，而应通过 `page_index.yaml` 和 VFS 浏览协议读取内容。

- `service_guide.md`：单文件入门示例；
- `ops_demo/`：多层级、跨版本、带覆盖关系的结构化测试基准。

`ops_demo/` 是虚构测试语料，不是 Ubuntu、systemd 或 OpenSSH 的生产操作手册。

无参数运行 `mafa` 时，菜单由这里的实际内容动态生成：包含 Markdown 的普通顶层
目录会自动出现，转换后的 CHM 目录通过 `manifest.json` 自动出现。如果一个顶层
目录包含多个应彼此隔离的知识库，可在各知识库根目录放置
`.mafa-corpus.yaml`，例如：

```yaml
id: openssh
name: OpenSSH
description: OpenSSH 配置与排错文档。
```

标记文件不配置路径；目录位置本身就是边界。新增或删除知识库后，无需维护中央
清单，下次启动会重新扫描。
