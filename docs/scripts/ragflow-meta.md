# ragflow-meta 文档元数据管理脚本

通过 RAGFlow SDK API 批量管理文档的 `meta_fields`（元数据字段），主要用于为文档设置 `source_url` 等溯源信息。

## 文件位置

```
scripts/ragflow_meta.py     # 主脚本
```

依赖 `ragflow_sync.py` 中的公共函数（`list_remote_docs`, `pick_datasets`, `sha256_file` 等）和 `state.py` 中的本地状态数据库。

## 命令参考

### `set-source-url` — 批量设置 source_url

```bash
uv run scripts/ragflow_meta.py set-source-url --dry-run
uv run scripts/ragflow_meta.py set-source-url
uv run scripts/ragflow_meta.py set-source-url --dataset 04_harmonyos-docs
uv run scripts/ragflow_meta.py set-source-url --doc-ids id1 id2
```

为每个文档设置 `meta_fields.source_url = http://mock.abc.com/<sha256>`，其中 `<sha256>` 取自本地同步状态数据库（即上传时计算的文件哈希）。

| 参数 | 说明 |
|------|------|
| `--dataset` | 按数据集名/ID 过滤，可重复指定 |
| `--doc-ids` | 只更新指定的文档 ID |
| `--dry-run` | 只打印计划操作，不调用 API |

> 未在本地状态中追踪到 sha256 的文档会被跳过（SKIP），不会报错。

### `set-meta` — 设置任意元数据字段

```bash
uv run scripts/ragflow_meta.py set-meta --set author=team --set version=1.0
uv run scripts/ragflow_meta.py set-meta --set category=sdk --dataset 04_harmonyos-docs --dry-run
```

通过 `PATCH /api/v1/datasets/{id}/documents/{id}` 设置任意 `meta_fields` 键值对。

| 参数 | 说明 |
|------|------|
| `--set` | **必填**，`key=value` 格式的元数据字段，可指定多个 |
| `--dataset` | 按数据集过滤 |
| `--doc-ids` | 只更新指定文档 |
| `--dry-run` | 只打印不执行 |

### `show` — 查看远端文档元数据

```bash
uv run scripts/ragflow_meta.py show
uv run scripts/ragflow_meta.py show --dataset 04_harmonyos-docs --limit 10
```

列出远端文档及其当前的 `meta_fields`。

| 参数 | 说明 |
|------|------|
| `--dataset` | 按数据集过滤 |
| `--limit` | 每个数据集最多显示的文档数，默认 20 |

### `hash-source` — 预览本地文件哈希

```bash
uv run scripts/ragflow_meta.py hash-source
uv run scripts/ragflow_meta.py hash-source --dataset 04_harmonyos-docs --limit 5
```

计算并显示本地源文件的 SHA-256 哈希（与上传时一致），用于预览 `set-source-url` 将生成的 URL。

| 参数 | 说明 |
|------|------|
| `--dataset` | 按数据集过滤 |
| `--limit` | 最多显示文件数，默认 20 |

## API 接口

脚本通过 RAGFlow SDK API（`/api/v1/...`）操作文档元数据：

- **单文档更新** — `PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}`，body 中传 `meta_fields` 字典
- **远端文档列表** — `GET /api/v1/datasets/{dataset_id}/documents`（复用 `ragflow_sync.list_remote_docs`）

`meta_fields` 是 RAGFlow 文档级别的元数据存储，存储在 ES/Infinity 的独立元数据索引中，可用于检索时的条件过滤。

## 典型用例

```bash
# 为所有已上传文档添加 mock source_url
uv run scripts/ragflow_meta.py set-source-url --dry-run   # 先预览
uv run scripts/ragflow_meta.py set-source-url              # 再执行

# 验证结果
uv run scripts/ragflow_meta.py show --limit 5

# 为特定数据集补充自定义元数据
uv run scripts/ragflow_meta.py set-meta --set project=harmony --dataset 04_harmonyos-docs
```
