# xsj-kb 文档目录

新视界鸿蒙知识库项目的运维与开发文档。

## 目录结构

```
docs/
├── scripts/                     # RAGFlow 数据管理脚本文档
│   ├── ragflow-sync.md          # 数据同步脚本（upload / status / replace）
│   ├── ragflow-delete.md        # 文档删除脚本（按全部 / 模式 / 状态）
│   ├── ragflow-parse.md         # 文档解析脚本（批量触发 + 轮询进度）
│   └── state-management.md      # SQLite 同步状态管理
├── mcp-audit-gateway/           # MCP 审计网关方案与文档
│   ├── overview.md              # 整体架构与部署模式概述
│   ├── server.md                # MCP Server 实现与配置详解
│   ├── audit-system.md          # 审计存储系统设计
│   └── client-guide.md          # 客户端接入指南（SSE / Streamable HTTP）
└── README.md                    # 本文件
```

## 快速导航

### 脚本运维

| 文档 | 说明 |
|------|------|
| [ragflow-sync](scripts/ragflow-sync.md) | 将本地 `sources/` 文件上传到 RAGFlow 数据集，支持增量、断点续传、变更替换 |
| [ragflow-delete](scripts/ragflow-delete.md) | 按全部、文件名模式、解析状态批量删除 RAGFlow 文档 |
| [ragflow-parse](scripts/ragflow-parse.md) | 触发 RAGFlow 文档解析并轮询进度，支持批量与超时控制 |
| [state-management](scripts/state-management.md) | 同步状态 DB 的 schema、字段说明与运维操作 |

### MCP 审计网关

| 文档 | 说明 |
|------|------|
| [overview](mcp-audit-gateway/overview.md) | 架构总览、两种部署模式、数据流与安全边界 |
| [server](mcp-audit-gateway/server.md) | Server 实现细节、环境变量、CLI 参数、RAGFlowConnector 缓存策略 |
| [audit-system](mcp-audit-gateway/audit-system.md) | 审计事件模型、SQLite schema、字段截断策略、查询示例 |
| [client-guide](mcp-audit-gateway/client-guide.md) | SSE / Streamable HTTP 客户端接入方式与认证说明 |
