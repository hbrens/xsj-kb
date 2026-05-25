# xsj-kb

新视界鸿蒙知识库。

## 结构

- `data/` — 数据源，按数据集分目录存放
- `sync/` — 数据同步脚本（Hash 比对 → RAGFlow API）
- `mcp/` — MCP 审计网关
- `skill/` — Skill 相关

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
uv sync                          # 创建虚拟环境并安装依赖（venv 在 .venv/ 下）
uv run python mcp/server/server.py  # 启动 MCP 网关（默认 self-host，读取 .env 中的 API key）
```

## MCP 审计

MCP tool 调用会默认写入 SQLite 审计库，数据库位置为 `var/mcp_audit.sqlite3`。`var/` 目录会提交到 git，实际数据库文件和 WAL/SHM 文件不会提交。

可用环境变量：

```bash
RAGFLOW_MCP_AUDIT_ENABLED=true
RAGFLOW_MCP_AUDIT_DB_PATH=var/mcp_audit.sqlite3
RAGFLOW_MCP_AUDIT_LOG_QUESTION=true
RAGFLOW_MCP_AUDIT_MAX_TEXT=1000
```
