# xsj-kb

新视界鸿蒙知识库。

## 结构

- `scripts/` — RAGFlow 数据管理脚本（同步/删除/解析/元数据）
- `sources/` — 数据源，按数据集分目录存放
- `mcp/` — MCP 审计网关
- `docs/` — 项目文档
- `var/` — 运行时数据（状态数据库、审计库，git-ignored）

## 数据集

| 目录 | 内容 |
|------|------|
| `01_xsj-internal-guides` | 团队规范、FAQ、踩坑记录 |
| `02_deveco-sdk-api` | DevEco SDK API |
| `03_project-code` | 项目代码、组件库 |
| `04_harmonyos-docs` | HarmonyOS 官方文档 |
| `05_openharmony-docs` | OpenHarmony 开源文档 |
| `06_harmonyos-samples` | 官方样例代码 |

## 常用命令

```bash
uv sync                               # 创建虚拟环境并安装依赖
uv run python mcp/server/server.py    # 启动 MCP 网关

# 数据同步
uv run scripts/ragflow_sync.py status
uv run scripts/ragflow_sync.py upload --parse
uv run scripts/ragflow_parse.py run

# 文档删除
uv run scripts/ragflow_delete.py by-status --status fail --yes

# 文档元数据
uv run scripts/ragflow_meta.py set-source-url --dry-run
uv run scripts/ragflow_meta.py set-source-url
```

## MCP 审计

MCP tool 调用会默认写入 SQLite 审计库，数据库位置为 `var/mcp_audit.sqlite3`。审计范围只包含 MCP 网关在 `ragflow_retrieval` 调用中天然收到和返回的内容：tool 入参、实际发给 RAGFlow 的 retrieval payload、自动解析后的 dataset IDs、返回给 Agent 的检索结果与 chunk 来源信息。不会额外采集最终 Agent 回复或额外用户身份信息。

可用环境变量：

```bash
RAGFLOW_MCP_AUDIT_ENABLED=true
RAGFLOW_MCP_AUDIT_DB_PATH=var/mcp_audit.sqlite3
RAGFLOW_MCP_AUDIT_LOG_QUESTION=true
RAGFLOW_MCP_AUDIT_MAX_TEXT=1000
RAGFLOW_MCP_AUDIT_MAX_INPUT_TEXT=8000
RAGFLOW_MCP_AUDIT_MAX_CHUNK_TEXT=4000
RAGFLOW_MCP_AUDIT_MAX_CHUNKS=100
```
