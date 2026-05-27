# MCP Server 实现详解

## 文件位置

```
mcp/server/server.py    # 主文件，约 600 行
```

## 整体结构

`server.py` 包含以下核心组件：

1. **RAGFlowConnector** — 与 RAGFlow REST API 交互的异步客户端，含缓存
2. **MCP Server** — 基于 `mcp` SDK 的 low-level Server，注册 `list_tools` 和 `call_tool`
3. **认证层** — `with_api_key` 装饰器 + host 模式的 AuthMiddleware
4. **Starlette 应用** — 组合 SSE 和 Streamable HTTP 两种传输

## RAGFlowConnector

### 初始化

```python
connector = RAGFlowConnector(base_url="http://127.0.0.1:9380")
```

内部使用 `httpx.AsyncClient` 进行异步 HTTP 调用，base_url 指向 RAGFlow 后端。

### 缓存机制

RAGFlowConnector 维护两个 LRU + TTL 缓存：

| 缓存 | 键 | 值 | TTL | 最大条目 |
|------|----|----|-----|---------|
| Dataset 元数据 | dataset_id | `{name, description}` | 300s ± 30s 随机抖动 | 32 |
| Document 元数据 | dataset_id | `[(doc_id, doc_meta), ...]` | 同上 | 32 |

缓存抖动（±30s）用于防止缓存击穿。

`force_refresh=True` 参数可跳过缓存直接查询 RAGFlow。

### 核心方法

#### `list_datasets(api_key, page, page_size, ...)`

返回可访问数据集的 JSON 字符串，格式为换行分隔的 JSON，每行一个数据集（description + id）。嵌入到 tool description 中让 AI 了解可用数据集。

#### `resolve_dataset_ids(api_key)`

分页遍历所有可访问数据集，返回 dataset_id 列表。当客户端不指定 dataset_ids 时自动调用，实现"搜索全部数据集"功能。

#### `retrieval(api_key, dataset_ids, question, ...)`

核心检索方法，参数包括：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `dataset_ids` | (空=全部) | 要搜索的数据集 ID 列表 |
| `document_ids` | (空) | 限定搜索的文档 ID 列表 |
| `question` | | 搜索问题 |
| `page` | 1 | 分页页码 |
| `page_size` | 30 | 每页结果数 |
| `similarity_threshold` | 0.2 | 最低相似度阈值 |
| `vector_similarity_weight` | 0.3 | 向量相似度权重 |
| `keyword` | false | 是否启用关键词搜索 |
| `top_k` | 1024 | 排序前考虑的最大结果数 |
| `rerank_id` | null | 重排序模型 ID |
| `force_refresh` | false | 是否跳过缓存 |
| `audit_hook` | null | 审计钩子，传入 retrieval 请求摘要 |

返回格式化的 MCP `TextContent`，内含结构化 JSON：

```json
{
  "chunks": [...],
  "pagination": {
    "page": 1, "page_size": 10,
    "total_chunks": 42, "total_pages": 5
  },
  "query_info": {
    "question": "...",
    "similarity_threshold": 0.2,
    "dataset_count": 2
  }
}
```

#### `_map_chunk_fields(chunk_data, dataset_cache, document_cache)`

对 RAGFlow 返回的每个 chunk 补充字段：

- `dataset_name` — 从缓存中查找
- `document_name` — 使用 `document_keyword` 字段
- `document_metadata` — 附加完整的文档元数据（name, location, type, size, chunk_count 等）

## 认证机制

### `with_api_key` 装饰器

```python
@app.call_tool()
@with_api_key(required=True)
async def call_tool(name, arguments, *, connector, api_key):
    ...
```

自动注入 `connector` 和 `api_key` 参数：

- **self-host 模式**：使用启动时配置的全局 `HOST_API_KEY`
- **host 模式**：从请求上下文中提取 `Authorization: Bearer <token>` 或 `api_key` 头

### AuthMiddleware（仅 host 模式）

Starlette ASGI 中间件，对 `/messages/`, `/sse`, `/mcp` 路径的请求强制要求认证头。缺少认证时返回 401。

支持的认证头格式：

- `Authorization: Bearer <api_key>`
- `api_key: <api_key>`
- `X-API-Key: <api_key>`

## MCP Tool 定义

当前只注册了一个 tool：`ragflow_retrieval`

### inputSchema

```json
{
  "required": ["question"],
  "properties": {
    "question": { "type": "string" },
    "dataset_ids": { "type": "array", "items": { "type": "string" } },
    "document_ids": { "type": "array", "items": { "type": "string" } },
    "page": { "type": "integer", "default": 1, "minimum": 1 },
    "page_size": { "type": "integer", "default": 10, "minimum": 1, "maximum": 100 },
    "similarity_threshold": { "type": "number", "default": 0.2 },
    "vector_similarity_weight": { "type": "number", "default": 0.3 },
    "keyword": { "type": "boolean", "default": false },
    "top_k": { "type": "integer", "default": 1024 },
    "rerank_id": { "type": "string" },
    "force_refresh": { "type": "boolean", "default": false }
  }
}
```

tool description 中会动态嵌入当前可访问数据集的列表和描述，帮助 AI 选择合适的 dataset。

## Starlette 应用组装

`create_starlette_app()` 根据配置组合路由：

| 传输协议 | 路由 | 说明 |
|----------|------|------|
| SSE | `GET /sse` | SSE 连接端点 |
| SSE | `POST /messages/` | SSE 消息发送 |
| Streamable HTTP | `GET/POST/DELETE /mcp` | Streamable HTTP 端点 |

两种传输可以同时启用，也可以单独禁用。如果都被禁用，会自动重新启用 Streamable HTTP。

## CLI 参数

```bash
uv run mcp/server/server.py [OPTIONS]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `http://127.0.0.1:9380` | RAGFlow 后端地址 |
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `9382` | 监听端口 |
| `--mode` | `self-host` | 部署模式：`self-host` 或 `host` |
| `--api-key` | (空) | self-host 模式的 RAGFlow API Key |
| `--transport-sse-enabled` | `true` | 启用 SSE 传输 |
| `--transport-streamable-http-enabled` | `true` | 启用 Streamable HTTP 传输 |
| `--json-response` | `true` | Streamable HTTP 使用 JSON 响应模式 |

## 环境变量

所有 CLI 参数都有对应的环境变量（优先级更高）：

| 环境变量 | 对应参数 |
|----------|---------|
| `RAGFLOW_MCP_BASE_URL` | `--base-url` |
| `RAGFLOW_MCP_HOST` | `--host` |
| `RAGFLOW_MCP_PORT` | `--port` |
| `RAGFLOW_MCP_LAUNCH_MODE` | `--mode` |
| `RAGFLOW_MCP_HOST_API_KEY` | `--api-key` |
| `RAGFLOW_MCP_TRANSPORT_SSE_ENABLED` | `--transport-sse-enabled` |
| `RAGFLOW_MCP_TRANSPORT_STREAMABLE_ENABLED` | `--transport-streamable-http-enabled` |
| `RAGFLOW_MCP_JSON_RESPONSE` | `--json-response` |
| `RAGFLOW_MCP_AUDIT_ENABLED` | 审计开关 |
| `RAGFLOW_MCP_AUDIT_DB_PATH` | 审计数据库路径 |
| `RAGFLOW_MCP_AUDIT_LOG_QUESTION` | 是否记录 question 原文 |
| `RAGFLOW_MCP_AUDIT_MAX_TEXT` | 文本截断长度 |
| `RAGFLOW_MCP_AUDIT_MAX_INPUT_TEXT` | 输入文本截断长度 |
| `RAGFLOW_MCP_AUDIT_MAX_CHUNK_TEXT` | chunk 文本截断长度 |
| `RAGFLOW_MCP_AUDIT_MAX_CHUNKS` | 最大 chunk 记录数 |

## 启动示例

```bash
# 单租户，双传输
uv run mcp/server/server.py \
    --mode=self-host \
    --api-key=ragflow-xxxxx

# 多租户，只启用 Streamable HTTP
uv run mcp/server/server.py \
    --mode=host \
    --no-transport-sse-enabled \
    --host=0.0.0.0

# 自定义 RAGFlow 后端地址
uv run mcp/server/server.py \
    --base-url=http://192.168.1.100:9380 \
    --mode=self-host \
    --api-key=ragflow-xxxxx
```
