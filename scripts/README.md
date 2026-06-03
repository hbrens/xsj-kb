# RAGFlow 数据管理脚本

管理和同步本地 `sources/` 目录到 RAGFlow 数据集的工具集。

> 详细文档见 [`docs/scripts/`](../docs/scripts/)

## 脚本一览

| 脚本 | 说明 | 详细文档 |
|------|------|---------|
| `ragflow_sync.py` | 数据同步（上传/状态/替换/清空） | [ragflow-sync.md](../docs/scripts/ragflow-sync.md) |
| `ragflow_delete.py` | 文档删除（按全部/模式/状态） | [ragflow-delete.md](../docs/scripts/ragflow-delete.md) |
| `ragflow_parse.py` | 文档解析（批量触发/轮询进度） | [ragflow-parse.md](../docs/scripts/ragflow-parse.md) |
| `ragflow_meta.py` | 文档元数据管理（source_url等） | [ragflow-meta.md](../docs/scripts/ragflow-meta.md) |
| `state.py` | 同步状态管理（SQLite） | [state-management.md](../docs/scripts/state-management.md) |
| `ragflow_sources.json` | 数据集映射配置 | — |

## 快速上手

```bash
# 查看同步状态
uv run scripts/ragflow_sync.py status
uv run scripts/ragflow_sync.py status --verify

# 上传文件到 RAGFlow
uv run scripts/ragflow_sync.py upload --dry-run
uv run scripts/ragflow_sync.py upload --dataset 06_harmonyos-samples
uv run scripts/ragflow_sync.py upload --replace-changed --parse

# 删除文档
uv run scripts/ragflow_delete.py by-status --status fail --yes
uv run scripts/ragflow_delete.py by-pattern --pattern "*.pdf" --dry-run

# 触发解析
uv run scripts/ragflow_parse.py run
uv run scripts/ragflow_parse.py run --only-failed

# 列出远端文档
uv run scripts/ragflow_sync.py list-remote

# 清空数据集
uv run scripts/ragflow_sync.py delete-all --dataset 06_harmonyos-samples --yes

# 文档元数据
uv run scripts/ragflow_meta.py set-source-url --dry-run
uv run scripts/ragflow_meta.py set-source-url
uv run scripts/ragflow_meta.py set-meta --set author=team --set version=1.0
uv run scripts/ragflow_meta.py hash-source --limit 5
```

## 配置

`ragflow_sources.json` 定义数据集映射和文件过滤规则。环境变量在项目根目录 `.env` 中配置。

## 状态数据库

同步状态存储在 `var/ragflow-sync-state.db`（SQLite，git-ignored）。`upload` 命令支持中断后自动续传，通过 SHA-256 哈希检测文件变更。
