# RAGFlow source sync

These scripts sync local `sources/<source_dir>` folders into RAGFlow datasets.

Configuration lives in `scripts/ragflow_sources.json`. The current mapping was read from the local RAGFlow MySQL database:

| source dir | RAGFlow dataset |
| --- | --- |
| `04_harmonyos-docs` | `04_harmonyos-docs` (`29c76db0585a11f1ae6e4fbffc0cb4e8`) |
| `06_harmonyos-samples` | `harmonyos-samples` (`3a529d12585a11f1ae6e4fbffc0cb4e8`) |

## Commands

```bash
.venv/bin/python scripts/ragflow_sync.py status
.venv/bin/python scripts/ragflow_sync.py status --verify
.venv/bin/python scripts/ragflow_sync.py upload --dry-run
.venv/bin/python scripts/ragflow_sync.py upload --dataset 06_harmonyos-samples
.venv/bin/python scripts/ragflow_sync.py upload --replace-changed --parse
.venv/bin/python scripts/ragflow_sync.py list-remote
.venv/bin/python scripts/ragflow_sync.py delete-all --dataset 06_harmonyos-samples --yes
```

`upload` is serial and resumable. After each batch it writes state to `var/ragflow-sync-state.db` (SQLite), which is git-ignored. Re-running the same command skips files whose SHA-256 hash is unchanged.

`status` compares local files against the local state DB. Add `--verify` to also query RAGFlow and update remote status (parse done, error, missing, etc.).

Changed files are detected but skipped by default to avoid creating duplicates. Use `--replace-changed` to delete the old RAGFlow document and upload the changed file again.

`delete-all` deletes every remote document in the selected dataset and clears local sync state for that source directory. It requires `--yes`.
