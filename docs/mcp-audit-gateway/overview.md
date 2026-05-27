# MCP 审计网关 — 架构概述

## 什么是 MCP 审计网关

MCP 审计网关是介于 MCP 客户端（如 AI IDE / Agent）和 RAGFlow 后端之间的代理层。它将 RAGFlow 的 retrieval API 包装为标准的 MCP Tool，同时在每次调用时记录完整的审计日志。

```
┌──────────────┐     MCP 协议      ┌────────────────────┐    REST API    ┌──────────┐
│  MCP Client  │ ───────────────── │  MCP Audit Gateway │ ───────────── │ RAGFlow  │
│ (IDE/Agent)  │  SSE / StreamHTTP │  (server.py)       │  /api/v1/...  │ Backend  │
└──────────────┘                   └────────────────────┘               └──────────┘
                                           │
                                           │ 写入审计事件
                                           ▼
                                   ┌────────────────────┐
                                   │  SQLite 审计 DB    │
                                   │ (mcp_audit.sqlite3)│
                                   └────────────────────┘
```

## 核心能力

- **协议转换** — 将 RAGFlow REST API 转换为 MCP 标准 Tool
- **双传输支持** — 同时支持 SSE (`/sse`) 和 Streamable HTTP (`/mcp`) 两种 MCP 传输协议
- **审计记录** — 每次 tool 调用记录请求参数、返回结果摘要、检索 chunks、延迟、错误
- **元数据缓存** — dataset 和 document 的元数据使用 LRU + TTL 缓存，减少对 RAGFlow 的请求
- **多租户认证** — 支持 self-host 和 host 两种模式

## 部署模式

### self-host 模式（单租户）

适用于个人或团队内部使用。网关启动时通过 `--api-key` 指定 RAGFlow API Key，所有请求共享同一个身份。

```bash
uv run mcp/server/server.py \
    --mode=self-host \
    --api-key=ragflow-xxxxx \
    --port=9382
```

- 客户端连接时**无需**携带认证信息
- API Key 由服务端管理，不暴露给客户端
- 适合内网部署、个人开发环境

### host 模式（多租户）

适用于为多个用户提供 MCP 服务。每个客户端请求必须携带自己的 RAGFlow API Key。

```bash
uv run mcp/server/server.py \
    --mode=host \
    --port=9382
```

- 客户端必须在请求头中携带 `Authorization: Bearer <api_key>` 或 `api_key` 头
- 缺少认证的请求返回 401
- 每个请求使用调用方自己的 API Key 访问 RAGFlow，权限隔离
- 适合团队共享、对外服务

## 数据流

以 `ragflow_retrieval` tool 为例：

```
1. 客户端发送 MCP call_tool 请求（含 question, dataset_ids 等参数）
2. 认证层提取 API Key（host 模式从请求头，self-host 模式从启动参数）
3. 审计层创建 audit_call 记录（request_id, 参数, 开始时间）
4. RAGFlowConnector 将参数组装为 RAGFlow retrieval 请求
5. 调用 RAGFlow POST /api/v1/retrieval
6. RAGFlow 返回检索结果（chunks）
7. 后处理：补充 dataset_name, document_name 等元数据字段
8. 审计层记录成功结果（chunks 摘要, 延迟, 分页信息）
9. 返回结构化的 MCP tool result 给客户端
```

## 安全边界

| 层面 | 措施 |
|------|------|
| 传输 | SSE/HTTP 均可配合 TLS 反向代理 |
| 认证 | host 模式强制 Authorization 头；self-host 模式服务端持有 key |
| 审计 | API Key 仅存储 SHA-256 前 16 位哈希，不记录原文 |
| 文本截断 | question、chunk content 等敏感文本有长度上限 |
| 审计开关 | 可通过环境变量完全关闭审计（`RAGFLOW_MCP_AUDIT_ENABLED=false`） |

## 文件结构

```
mcp/
├── server/
│   ├── server.py       # MCP Server 主体 + RAGFlowConnector + Starlette 应用
│   └── audit.py        # 审计存储层（MCPAuditStore + SQLite）
├── client/
│   ├── client.py       # SSE 客户端示例
│   └── streamable_http_client.py  # Streamable HTTP 客户端示例
└── __init__.py         # SDK 路径扩展
```

## 技术栈

| 组件 | 技术 |
|------|------|
| MCP Server | `mcp` Python SDK (Server low-level API) |
| HTTP 框架 | Starlette + uvicorn |
| HTTP 客户端 | httpx (async) |
| 审计存储 | SQLite (WAL mode) |
| 配置 | click CLI + dotenv |
