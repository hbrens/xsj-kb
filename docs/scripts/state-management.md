# 同步状态管理 (state.py)

RAGFlow 同步脚本使用 SQLite 数据库跟踪每个文件的上传和解析状态，支持断点续传和变更检测。

## 文件位置

```
scripts/state.py              # SyncState 类实现
var/ragflow-sync-state.db     # 运行时数据库（git-ignored）
```

## 数据库 Schema

```sql
CREATE TABLE files (
    path            TEXT PRIMARY KEY,   -- 相对于 source_dir 的路径（posix 风格）
    source_dir      TEXT NOT NULL,      -- 数据源目录名，如 "04_harmonyos-docs"
    dataset_id      TEXT NOT NULL,      -- RAGFlow dataset ID
    dataset_name    TEXT NOT NULL DEFAULT '',
    document_id     TEXT NOT NULL DEFAULT '',  -- RAGFlow 文档 ID（上传后回填）
    document_name   TEXT NOT NULL DEFAULT '',  -- RAGFlow 中的文档名
    location        TEXT NOT NULL DEFAULT '',  -- RAGFlow 中的文档路径
    sha256          TEXT NOT NULL DEFAULT '',  -- 本地文件 SHA-256
    size            INTEGER NOT NULL DEFAULT 0,
    local_status    TEXT NOT NULL DEFAULT '',  -- 本地操作状态标记
    remote_status   TEXT NOT NULL DEFAULT '',  -- 远端解析状态
    remote_msg      TEXT NOT NULL DEFAULT '',  -- 远端错误消息
    last_verified   TEXT NOT NULL DEFAULT '',  -- 最后一次验证时间 (ISO 8601)
    updated_at      TEXT NOT NULL DEFAULT ''   -- 记录更新时间 (ISO 8601)
);

CREATE INDEX idx_files_source_dir   ON files(source_dir);
CREATE INDEX idx_files_dataset_id   ON files(dataset_id);
CREATE INDEX idx_files_local_status ON files(local_status);
```

## 字段说明

### path

相对于 `source_dir` 的路径，使用 posix 分隔符（`/`）。例如 `quickStart/ets/概述.md`。这是主键，唯一标识一个文件。

### sha256

本地文件内容的 SHA-256 哈希值。`ragflow_sync.py` 每次运行时重新计算并与 DB 中的值对比，决定文件是 new / same / changed。

### document_id

上传成功后由 RAGFlow API 返回的文档 ID。空字符串表示尚未上传。`ragflow_sync.py` 通过 `--verify` 选项检查此 document_id 在远端是否存在，不存在则标记 remote_status 为 `missing`。

### remote_status

远端文档的解析状态，由 `verify_remote` 写入：

| 值 | 含义 |
|----|------|
| `parse_done` | 解析完成 |
| `parse_error` | 解析失败 |
| `running` | 正在解析 |
| `pending` | 尚未解析 |
| `missing` | 远端文档已不存在 |

### local_status

本地操作状态标记，用于辅助排查。例如 `deleted_before_replace` 表示在 `--replace-changed` 流程中先删除了旧文档。

## SyncState API

```python
from state import SyncState
from pathlib import Path

state = SyncState(Path("var/ragflow-sync-state.db"))

# 单条操作
state.upsert_file(rec)       # 插入或更新一条记录
state.get_file(path)         # 查询一条记录，返回 dict 或 None
state.remove_file(path)      # 删除一条记录

# 批量操作
state.upsert_many(records)   # 批量 upsert，事务内执行
state.remove_dataset(source_dir)  # 删除某个数据源的全部记录

# 查询
state.files_by_source(source_dir)         # 某数据源的所有文件
state.count_by_local_status(source_dir)   # 按 local_status 分组计数
state.count_by_remote_status(source_dir)  # 按 remote_status 分组计数
state.doc_ids_for_source(source_dir)      # {document_id: path} 映射

# 远端状态更新
state.update_remote_status(source_dir, doc_id, status, msg)
state.update_remote_batch(source_dir, [(doc_id, status, msg), ...])
state.mark_remote_missing(source_dir, live_doc_ids)  # 标记已消失的文档

state.close()
```

## 并发与性能

- 使用 **WAL 模式**（`PRAGMA journal_mode=WAL`），允许读写并发
- `synchronous=NORMAL`，牺牲少量持久性换取写入性能
- 所有时间使用 UTC ISO 8601 格式

## 运维操作

### 查看数据库内容

```bash
sqlite3 var/ragflow-sync-state.db "SELECT COUNT(*) FROM files;"
sqlite3 var/ragflow-sync-state.db "SELECT source_dir, local_status, COUNT(*) FROM files GROUP BY 1, 2;"
sqlite3 var/ragflow-sync-state.db "SELECT path, remote_status FROM files WHERE remote_status = 'missing';"
```

### 清理状态

```bash
# 清除某个数据集的全部状态（下次 upload 会重新上传所有文件）
sqlite3 var/ragflow-sync-state.db "DELETE FROM files WHERE source_dir = '04_harmonyos-docs';"

# 重置远端状态（下次 status --verify 会重新检查）
sqlite3 var/ragflow-sync-state.db "UPDATE files SET remote_status = '', last_verified = '';"
```

### 备份

```bash
sqlite3 var/ragflow-sync-state.db ".backup var/ragflow-sync-state-backup.db"
```

## 注意事项

- 数据库文件 `var/ragflow-sync-state.db` 被 `.gitignore` 排除，不进入版本控制
- `upsert_file` 和 `upsert_many` 中的 `ON CONFLICT` 逻辑：`remote_status` 和 `remote_msg` 只在新值非空时覆盖，避免覆盖已有的验证结果
- 如果数据库损坏，删除 `.db` 文件后重新运行 `upload` 即可重建（代价是全量重新上传）
