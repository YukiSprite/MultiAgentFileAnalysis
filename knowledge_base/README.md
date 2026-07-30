# Knowledge Base

这里存放映射进虚拟文件系统的 Markdown 知识库文档。

Agent 不应直接访问这一层的真实文件路径，而应通过 `page_index.yaml` 和 VFS 浏览协议读取内容。

- `service_guide.md`：单文件入门示例；
- `ops_demo/`：多层级、跨版本、带覆盖关系的结构化测试基准。

`ops_demo/` 是虚构测试语料，不是 Ubuntu、systemd 或 OpenSSH 的生产操作手册。
