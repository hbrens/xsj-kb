# 客户端接入指南

## 概述

MCP 审计网关同时暴露两个传输端点，客户端根据自身支持情况选择一种即可：

| 传输协议 | 端点 | 特点 |
|----------|------|------|
| SSE (Server-Sent Events) | `/sse` | 传统方式，兼容性好 |
| Streamable HTTP | `/mcp` | 新标准，支持 JSON 响应模式 |

## 前提条件

- Python 3.13+
- 已安装 `mcp` 包：`uv add "mcp[cli]>=1.0.0"`
- 网关已启动（见 [server.md](server.md)）

## 方式一：SSE 客户端

适用于使用 SSE 传输的场景。

```python
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

# self-host 模式：无需认证头
async def example_self_host():
    async with sse_client("http://127.0.0.1:9382/sse") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            # 列出可用 tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")
            # 调用检索
            response = await session.call_tool(
                name="ragflow_retrieval",
                arguments={
                    "question": "如何创建 HarmonyOS 应用?",
                    "dataset_ids": ["29c76db0585a11f1ae6e4fbffc0cb4e8"],
                    "page_size": 5,
                },
            )
            print(f"Result: {response.model_dump()}")

# host 模式：需要传认证头
async def example_host():
    async with sse_client(
        "http://127.0.0.1:9382/sse",
        headers={"Authorization": "Bearer ragflow-your-api-key"},
    ) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            tools = await session.list_tools()
```

## 方式二：Streamable HTTP 客户端

适用于使用 Streamable HTTP 传输的场景。默认使用 JSON 响应模式。

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# self-host 模式
async def example_self_host():
    async with streamablehttp_client("http://127.0.0.1:9382/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            response = await session.call_tool(
                name="ragflow_retrieval",
                arguments={"question": "HarmonyOS 应用模型有哪些?"},
            )
            print(response.model_dump())

# host 模式
async def example_host():
    async with streamablehttp_client(
        "http://127.0.0.1:9382/mcp",
        headers={"Authorization": "Bearer ragflow-your-api-key"},
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
```

## 认证说明

### self-host 模式

服务端已持有 API Key，客户端无需任何认证信息。

### host 模式

客户端必须在连接时提供 RAGFlow API Key。支持以下头格式：

```
Authorization: Bearer ragflow-xxxxx
```

或

```
api_key: ragflow-xxxxx
```

缺少认证的请求会收到 401 响应。

## Tool 参数详解

### `ragflow_retrieval`

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `question` | string | 是 | — | 搜索查询 |
| `dataset_ids` | string[] | 否 | (全部) | 指定搜索的数据集，为空则搜索所有 |
| `document_ids` | string[] | 否 | (全部) | 限定搜索的文档 |
| `page` | int | 否 | 1 | 页码 |
| `page_size` | int | 否 | 10 | 每页结果数 (1-100) |
| `similarity_threshold` | float | 否 | 0.2 | 最低相似度 (0-1) |
| `vector_similarity_weight` | float | 否 | 0.3 | 向量权重 (0-1) |
| `keyword` | bool | 否 | false | 启用关键词搜索 |
| `top_k` | int | 否 | 1024 | 排序前最大候选数 |
| `rerank_id` | string | 否 | null | 重排序模型 ID |
| `force_refresh` | bool | 否 | false | 跳过元数据缓存 |

### 返回结构

```json
{
  "chunks": [
    {
      "content": "...",
      "dataset_id": "...",
      "dataset_name": "04_harmonyos-docs",
      "document_id": "...",
      "document_name": "概述.md",
      "document_metadata": {
        "name": "概述.md",
        "location": "04_harmonyos-docs/quickStart/ets/概述.md",
        "type": "md",
        "chunk_count": 12
      },
      "similarity": 0.85,
      "vector_similarity": 0.78,
      "term_similarity": 0.92
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 10,
    "total_chunks": 42,
    "total_pages": 5
  },
  "query_info": {
    "question": "如何创建 HarmonyOS 应用?",
    "similarity_threshold": 0.2,
    "vector_weight": 0.3,
    "keyword_search": false,
    "dataset_count": 2
  }
}
```

## 常见问题

### 连接被拒绝

确认网关正在运行并且端口正确。默认监听 `127.0.0.1:9382`。

### 401 Unauthorized

host 模式下必须携带认证头。检查 API Key 是否正确，格式是否为 `Bearer <key>`。

### 空结果

检查 `dataset_ids` 是否正确，或尝试不传 `dataset_ids` 让网关搜索所有可访问数据集。也可能是 `similarity_threshold` 设置过高。

### Timeout

RAGFlow 后端处理耗时可能较长，特别是首次检索或大知识库场景。httpx 客户端默认超时 60 秒。如需调整需修改 `RAGFlowConnector` 中的超时配置。
