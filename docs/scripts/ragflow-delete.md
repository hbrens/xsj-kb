# ragflow-delete 文档删除脚本

按不同维度批量删除 RAGFlow 数据集中的文档，支持按全部、文件名模式、解析状态三种筛选方式。

## 文件位置

```
scripts/ragflow_delete.py     # 主脚本
```

依赖 `ragflow_sync.py` 中的公共函数（`list_remote_docs`, `delete_docs`, `pick_datasets` 等）。

## 命令参考

### `all` — 删除全部文档

```bash
uv run scripts/ragflow_delete.py all --dataset 06_harmonyos-samples --yes
uv run scripts/ragflow_delete.py all --dataset 06_harmonyos-samples --dry-run
```

删除指定数据集中的所有远端文档，并清除本地 state DB 中的对应记录。

| 参数 | 说明 |
|------|------|
| `--dataset` | 指定目标数据集，可重复。不指定则操作全部 |
| `--yes` | 跳过交互确认 |
| `--dry-run` | 只打印计划操作 |

### `by-pattern` — 按文件名模式删除

```bash
uv run scripts/ragflow_delete.py by-pattern --pattern "*.pdf" --yes
uv run scripts/ragflow_delete.py by-pattern --pattern "04_harmonyos-docs/JsEtsAPI*" --dataset 04_harmonyos-docs
```

使用 Unix glob 模式匹配文档的 `name` 或 `location` 字段。匹配到的文档先列出来让你确认。

| 参数 | 说明 |
|------|------|
| `--pattern` | **必填**，glob 模式，匹配文档名/路径 |
| `--dataset` | 限定搜索范围 |
| `--yes` | 跳过确认 |
| `--dry-run` | 只打印 |

### `by-status` — 按解析状态删除

```bash
uv run scripts/ragflow_delete.py by-status --status fail --yes
uv run scripts/ragflow_delete.py by-status --status pending --dataset 04_harmonyos-docs --dry-run
```

按 RAGFlow 文档的 `run` 字段筛选。可选值：

| --status 值 | 对应 RAGFlow run 字段 | 说明 |
|-------------|----------------------|------|
| `fail` | `FAIL` | 解析失败的文档 |
| `done` | `DONE` | 已完成解析的文档 |
| `running` | `RUNNING` | 正在解析的文档 |
| `pending` | `UNSTART` 或空 | 尚未开始解析的文档 |

匹配结果会先展示前 20 条，超过部分显示 `... and N more`。

## 安全机制

1. **交互确认** — 默认需要用户输入 `y` 确认，`--yes` 跳过
2. **dry-run** — 所有子命令都支持 `--dry-run`，只打印不执行
3. **本地状态清理** — 删除远端文档后同步清除 `var/ragflow-sync-state.db` 中的记录
4. **批量分片** — `by-pattern` 和 `by-status` 以 100 条为一批调用删除 API，避免单次请求过大

## 典型用例

```bash
# 清理所有解析失败的文档后重新上传
uv run scripts/ragflow_delete.py by-status --status fail --yes
uv run scripts/ragflow_sync.py upload --dataset 04_harmonyos-docs
uv run scripts/ragflow_parse.py run --dataset 04_harmonyos-docs

# 彻底重建某个数据集
uv run scripts/ragflow_sync.py delete-all --dataset 06_harmonyos-samples --yes
uv run scripts/ragflow_sync.py upload --dataset 06_harmonyos-samples --parse
```
