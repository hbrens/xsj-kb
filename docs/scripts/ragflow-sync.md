# ragflow-sync 数据同步脚本

将本地 `sources/<source_dir>/` 文件夹内容同步到 RAGFlow 数据集。支持增量上传、SHA-256 变更检测、断点续传和文档替换。

## 文件位置

```
scripts/ragflow_sync.py        # 主脚本
scripts/ragflow_sources.json   # 数据集映射配置
scripts/state.py               # 同步状态 DB（详见 state-management.md）
```

## 工作原理

1. 读取 `ragflow_sources.json` 获取数据集映射关系（`source_dir` -> `dataset_id`）
2. 遍历本地文件，计算 SHA-256 哈希
3. 与 `var/ragflow-sync-state.db` 中的已同步记录对比：
   - **same** — 哈希一致且已有 `document_id`，跳过
   - **new** — 本地存在但 DB 中无记录，需要上传
   - **changed** — 本地哈希与 DB 不同，默认跳过（除非 `--replace-changed`）
   - **missing_local** — DB 有记录但本地文件已删除
4. 上传前先调用 `verify_remote` 检查远端文档是否存在，缺失的标记为 `missing` 后会重新上传
5. 每完成一个文件写入 state DB，支持中断后重跑自动续传

## 命令参考

### `status` — 查看同步状态

```bash
uv run scripts/ragflow_sync.py status
uv run scripts/ragflow_sync.py status --verify
uv run scripts/ragflow_sync.py status --dataset 04_harmonyos-docs
```

| 参数 | 说明 |
|------|------|
| `--dataset` | 指定 source_dir / dataset_name / dataset_id，可重复 |
| `--verify` | 同时查询 RAGFlow 远端，更新 remote_status（parse_done / parse_error / missing 等） |

输出示例：

```
04_harmonyos-docs -> 04_harmonyos-docs (29c76db...): new=3 same=142 changed=0 missing_local=0
```

### `upload` — 上传文件

```bash
uv run scripts/ragflow_sync.py upload
uv run scripts/ragflow_sync.py upload --dry-run
uv run scripts/ragflow_sync.py upload --replace-changed --parse
uv run scripts/ragflow_sync.py upload --dataset 06_harmonyos-samples --verbose
```

| 参数 | 说明 |
|------|------|
| `--dataset` | 只同步指定的数据集 |
| `--replace-changed` | 哈希变更的文件先删除远端旧文档再重新上传 |
| `--parse` | 上传完成后自动触发 RAGFlow 文档解析 |
| `--dry-run` | 只打印计划操作，不实际执行 |
| `--verbose` | 打印每个跳过的 same 文件 |

**断点续传**：上传过程中按 `Ctrl+C` 中断后重新运行同一命令，已成功的文件会跳过。

**变更检测**：默认只上传 new 文件。changed 文件（哈希不同）需要 `--replace-changed` 才会先删后传，避免在 RAGFlow 产生重复文档。

### `list-remote` — 列出远端文档

```bash
uv run scripts/ragflow_sync.py list-remote
uv run scripts/ragflow_sync.py list-remote --limit 5
uv run scripts/ragflow_sync.py list-remote --dataset 06_harmonyos-samples
```

### `delete-all` — 清空数据集

```bash
uv run scripts/ragflow_sync.py delete-all --dataset 06_harmonyos-samples --yes
```

删除指定数据集中的**全部**远端文档并清除本地 state DB 中对应记录。需要 `--yes` 确认。

## 配置说明

`scripts/ragflow_sources.json` 结构：

```jsonc
{
  "base_url_env": "RAGFLOW_MCP_BASE_URL",   // .env 中读取 RAGFlow 地址
  "api_key_env": "RAGFLOW_MCP_HOST_API_KEY", // .env 中读取 API Key
  "state_path": "var/ragflow-sync-state.db", // 本地状态 DB 路径
  "sources_root": "sources",                 // 数据源根目录
  "default_include_extensions": [".md", ".ets", ".json5", ...],
  "exclude_dirs": [".git", "node_modules", "build", ...],
  "exclude_files": [".DS_Store", ".gitkeep"],
  "datasets": [
    {
      "source_dir": "04_harmonyos-docs",
      "dataset_id": "29c76db0585a11f1ae6e4fbffc0cb4e8",
      "dataset_name": "04_harmonyos-docs"
    }
  ]
}
```

### 支持的文件类型

脚本区分两种上传方式：

- **直接上传**：`.md`, `.pdf`, `.docx`, `.csv`, `.json`, `.py`, `.ts` 等 RAGFlow 原生支持的格式
- **文本包装上传**：`.ets`, `.json5`, `.xml`, `.yaml` 等格式会被包装为 `.txt` 文件，附加原始路径和后缀信息

### 环境变量

在项目根目录 `.env` 文件中配置：

```
RAGFLOW_MCP_BASE_URL=http://127.0.0.1:59380
RAGFLOW_MCP_HOST_API_KEY=your-ragflow-api-key-here
```

## 进度显示

上传过程在 stderr 显示实时进度：

```
[42/150] 28% upload=38 skip=4
```

完成后输出汇总：

```
04_harmonyos-docs -> 04_harmonyos-docs: done (12.3s) [changed=2, skip=138, upload=10]
```

失败的文件会在最后列出具体错误。
