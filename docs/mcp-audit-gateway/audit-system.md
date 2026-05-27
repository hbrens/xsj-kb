# 审计系统设计

## 文件位置

```
mcp/server/audit.py              # MCPAuditStore 实现
var/mcp_audit.sqlite3            # 审计数据库（运行时生成）
```

## 设计目标

1. **零性能开销** — 异步写入（`asyncio.to_thread`），不阻塞 MCP 请求处理
2. **完整性** — 记录每次 tool 调用的输入、输出、延迟、错误
3. **隐私保护** — API Key 只存哈希，文本内容有截断上限
4. **容错** — 审计写入失败只 log warning，不影响正常服务

## 核心组件

### MCPAuditConfig

审计配置数据类：

```python
@dataclass
class MCPAuditConfig:
    enabled: bool = True           # 总开关
    db_path: str = "var/mcp_audit.sqlite3"
    log_question: bool = True      # 是否记录 question 原文（False 则只记 hash）
    max_text: int = 1000           # 通用文本截断长度
    max_input_text: int = 8000     # 输入参数截断长度
    max_chunk_text: int = 4000     # chunk 内容截断长度
    max_chunks: int = 100          # 单次记录的最大 chunk 数
```

### MCPAuditCall

单次 tool 调用的审计上下文对象，在请求开始时创建，贯穿整个请求生命周期：

```python
@dataclass
class MCPAuditCall:
    request_id: str        # UUID hex，唯一标识
    started: float         # time.perf_counter() 开始时间
    mode: str              # "self-host" 或 "host"
    tool_name: str         # "ragflow_retrieval"
    api_key_hash: str      # API Key 的 SHA-256 前 16 位
    input_arguments: dict  # 截断后的原始参数
    arguments: dict        # 摘要参数（question_hash, dataset_ids 等）
    question: str | None   # 截断后的问题文本
    question_hash: str     # question 的 SHA-256 前 16 位
    retrieval: dict | None # RAGFlow 请求摘要（由 audit_hook 回填）
```

### MCPAuditStore

审计存储引擎，管理 SQLite 连接和写入逻辑。

## 数据库 Schema

### mcp_tool_calls 表

记录每次 MCP tool 调用：

```sql
CREATE TABLE mcp_tool_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,     -- UUID hex
    created_at      TEXT NOT NULL,     -- UTC ISO 8601
    mode            TEXT,              -- "self-host" / "host"
    tool_name       TEXT NOT NULL,     -- "ragflow_retrieval"
    api_key_hash    TEXT,              -- SHA-256 前 16 位
    status          TEXT NOT NULL,     -- "success" / "error"
    latency_ms      INTEGER NOT NULL,  -- 请求耗时（毫秒）
    question        TEXT,              -- 截断后的问题文本
    question_hash   TEXT,              -- question SHA-256 前 16 位
    arguments_json  TEXT NOT NULL,     -- 摘要参数 JSON
    input_json      TEXT,              -- 截断后的原始参数 JSON
    retrieval_json  TEXT,              -- RAGFlow 请求摘要
    result_json     TEXT,              -- 结果摘要
    response_json   TEXT,              -- 完整响应（截断后）
    error_message   TEXT               -- 错误消息
);

CREATE INDEX idx_mcp_tool_calls_created_at ON mcp_tool_calls(created_at);
CREATE INDEX idx_mcp_tool_calls_tool_status ON mcp_tool_calls(tool_name, status);
```

### mcp_retrieval_chunks 表

记录每次检索返回的 chunks，用于分析检索质量：

```sql
CREATE TABLE mcp_retrieval_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,     -- 关联 mcp_tool_calls.request_id
    chunk_index     INTEGER NOT NULL,  -- chunk 在结果中的序号
    dataset_id      TEXT,
    dataset_name    TEXT,
    document_id     TEXT,
    document_name   TEXT,
    chunk_id        TEXT,
    similarity      REAL,              -- 综合相似度
    vector_similarity REAL,            -- 向量相似度
    term_similarity  REAL,             -- 关键词相似度
    content         TEXT,              -- 截断后的 chunk 内容
    content_hash    TEXT,              -- content SHA-256 前 16 位
    chunk_json      TEXT NOT NULL      -- 完整 chunk 数据（截断后）
);

CREATE INDEX idx_mcp_retrieval_chunks_request_id ON mcp_retrieval_chunks(request_id);
CREATE INDEX idx_mcp_retrieval_chunks_dataset_doc ON mcp_retrieval_chunks(dataset_id, document_id);
```

## 事件生命周期

```
1. start_call()
   ├── 生成 request_id (UUID)
   ├── 记录 started 时间戳
   ├── 截断并记录 input_arguments
   └── 提取 question, 计算 question_hash

2. attach_retrieval()（可选）
   └── 回填 RAGFlow 请求摘要（dataset_ids, 分页参数等）

3. record_success() / record_error()
   ├── 准备 result 摘要
   ├── 提取 chunks 记录
   ├── 计算 latency_ms = (now - started) * 1000
   └── 异步写入 SQLite（asyncio.to_thread）
```

## 文本截断策略

所有文本字段在写入前都经过截断处理，防止过大的内容撑爆数据库：

| 字段类型 | 配置项 | 默认截断长度 |
|----------|--------|-------------|
| question | `max_text` | 1000 字符 |
| input_arguments | `max_input_text` | 8000 字符 |
| chunk content | `max_chunk_text` | 4000 字符 |
| 错误消息 | `max_text` | 1000 字符 |

截断方式：超过长度后截取前 N-3 个字符并附加 `...`。

## API Key 隐私

API Key 不以明文存储。使用 SHA-256 哈希后取前 16 位十六进制字符。这足以做关联查询（同一个 key 的所有调用），但无法反推出原始 key。

```python
def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
```

## 查询示例

```sql
-- 最近 1 小时的调用统计
SELECT tool_name, status, COUNT(*), AVG(latency_ms)
FROM mcp_tool_calls
WHERE created_at > datetime('now', '-1 hour')
GROUP BY tool_name, status;

-- 最慢的 10 次调用
SELECT request_id, tool_name, latency_ms, question
FROM mcp_tool_calls
ORDER BY latency_ms DESC
LIMIT 10;

-- 某个请求的检索 chunks
SELECT chunk_index, dataset_name, document_name, similarity, content
FROM mcp_retrieval_chunks
WHERE request_id = 'abc123...'
ORDER BY chunk_index;

-- 统计各数据集被检索的频率
SELECT dataset_name, COUNT(*) as hits, AVG(similarity) as avg_sim
FROM mcp_retrieval_chunks
GROUP BY dataset_name
ORDER BY hits DESC;

-- 检索质量分析：高相似度 vs 低相似度 chunk 分布
SELECT
    CASE
        WHEN similarity >= 0.8 THEN 'high (>=0.8)'
        WHEN similarity >= 0.5 THEN 'medium (0.5-0.8)'
        ELSE 'low (<0.5)'
    END as quality,
    COUNT(*)
FROM mcp_retrieval_chunks
GROUP BY quality;
```

## 故障排查

### 审计 DB 不存在

首次调用时自动创建，无需手动初始化。确保 `var/` 目录可写。

### 审计写入失败

审计失败只会输出 warning 日志，不影响 MCP 服务。常见原因：

- 磁盘满
- SQLite 被其他进程锁死（WAL 模式下极少发生）

### Schema 升级

`audit.py` 中的 `_ensure_schema` 和 `_ensure_column` 方法支持增量升级。新增列时通过 `ALTER TABLE ADD COLUMN` 追加，不会破坏已有数据。
