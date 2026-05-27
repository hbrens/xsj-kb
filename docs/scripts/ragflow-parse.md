# ragflow-parse 文档解析脚本

触发 RAGFlow 对已上传文档的解析（embedding + 索引），支持批量执行和轮询进度。

## 文件位置

```
scripts/ragflow_parse.py     # 主脚本
```

## 命令参考

### `status` — 查看解析状态

```bash
uv run scripts/ragflow_parse.py status
uv run scripts/ragflow_parse.py status --dataset 04_harmonyos-docs --limit 20
```

输出每个数据集的文档总数和按状态分类的计数：

```
04_harmonyos-docs -> 04_harmonyos-docs: 150 documents (80 done, 50 pending, 20 fail)
  done      100%  chunks=3240  04_harmonyos-docs/quickStart/ets/概述.md
  fail        0%  chunks=0     04_harmonyos-docs/JsEtsAPIReference/some-file.md
           Error: unsupported file type
```

| 参数 | 说明 |
|------|------|
| `--dataset` | 指定数据集，可重复 |
| `--limit` | 每个数据集最多显示多少条（0=全部） |

### `run` — 触发解析并轮询

```bash
uv run scripts/ragflow_parse.py run
uv run scripts/ragflow_parse.py run --dataset 04_harmonyos-docs
uv run scripts/ragflow_parse.py run --only-failed
uv run scripts/ragflow_parse.py run --batch-size 50 --batch-interval 60
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset` | 全部 | 指定目标数据集 |
| `--only-failed` | false | 只重新解析之前失败的文档 |
| `--interval` | 5.0 | 轮询间隔（秒） |
| `--timeout` | 600.0 | 单批无新进展的超时时间（秒） |
| `--batch-size` | 100 | 每批触发解析的文档数 |
| `--batch-interval` | 120.0 | 批次之间的等待时间（秒） |

## 工作流程

```
1. 查询 RAGFlow 获取所有文档的 run 状态
2. 过滤出需要解析的文档（非 DONE，或 --only-failed 只选 FAIL）
3. 按 batch-size 分批：
   a. 调用 POST /datasets/{id}/documents/parse 触发解析
   b. 轮询文档状态，显示进度条
   c. 等待 batch-interval 秒后进入下一批
4. 输出最终汇总
```

## 进度显示

解析过程中显示实时进度条：

```
[1/3] 04_harmonyos-docs: triggering 80 docs...
  [########################........................] 60.0%  done=48/80 fail=2 running=30  (120s)
```

超时后自动跳过仍在运行的文档：

```
  No progress for 600.0s, moving on. 3 docs still processing.
```

## 与 upload 的关系

`ragflow_sync.py upload --parse` 会在上传完成后自动触发解析（一次性，不轮询）。`ragflow_parse.py run` 则是独立的解析触发器，适合以下场景：

- 上传时忘了加 `--parse`
- 部分文档解析失败需要重跑
- 手动上传了文档后需要触发解析

## 典型用例

```bash
# 日常：上传 + 解析
uv run scripts/ragflow_sync.py upload --parse

# 修复失败文档
uv run scripts/ragflow_parse.py run --only-failed

# 全量重建后批量解析（控制节奏避免后端压力过大）
uv run scripts/ragflow_parse.py run --batch-size 30 --batch-interval 180
```
