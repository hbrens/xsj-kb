#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "scripts" / "ragflow_sources.json"
SUPPORTED_DIRECT_EXTENSIONS = {
    ".c",
    ".cpp",
    ".csv",
    ".doc",
    ".docx",
    ".eml",
    ".epub",
    ".go",
    ".h",
    ".html",
    ".htm",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".ldjson",
    ".md",
    ".mdx",
    ".pdf",
    ".php",
    ".ppt",
    ".pptx",
    ".py",
    ".rtf",
    ".sh",
    ".sql",
    ".ts",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".yml",
}
TEXT_WRAP_EXTENSIONS = {
    ".ets",
    ".json5",
    ".yaml",
}


@dataclass(frozen=True)
class DatasetConfig:
    source_dir: str
    dataset_id: str
    dataset_name: str


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing config: {CONFIG_PATH}")
    return load_json(CONFIG_PATH, {})


def get_credentials(config: dict[str, Any]) -> tuple[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    base_url = os.getenv(config.get("base_url_env", "RAGFLOW_MCP_BASE_URL"), "").rstrip("/")
    api_key = os.getenv(config.get("api_key_env", "RAGFLOW_MCP_HOST_API_KEY"), "")
    if not base_url:
        raise SystemExit("Missing RAGFlow base URL in .env")
    if not api_key:
        raise SystemExit("Missing RAGFlow API key in .env")
    return base_url, api_key


def request_json(
    method: str,
    base_url: str,
    api_key: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.request(
        method,
        f"{base_url}/api/v1{path}",
        headers=headers,
        params=params,
        json=json_body,
        files=files,
        data=data,
        timeout=120,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{method} {path} returned non-JSON HTTP {response.status_code}: {response.text[:300]}") from exc
    if response.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"{method} {path} failed: HTTP {response.status_code} {payload}")
    return payload


def config_datasets(config: dict[str, Any]) -> list[DatasetConfig]:
    return [
        DatasetConfig(
            source_dir=item["source_dir"],
            dataset_id=item["dataset_id"],
            dataset_name=item.get("dataset_name", item["source_dir"]),
        )
        for item in config.get("datasets", [])
    ]


def pick_datasets(config: dict[str, Any], names: list[str] | None) -> list[DatasetConfig]:
    datasets = config_datasets(config)
    if not names:
        return datasets
    wanted = set(names)
    selected = [ds for ds in datasets if ds.source_dir in wanted or ds.dataset_name in wanted or ds.dataset_id in wanted]
    missing = wanted - {x for ds in selected for x in (ds.source_dir, ds.dataset_name, ds.dataset_id)}
    if missing:
        known = ", ".join(ds.source_dir for ds in datasets)
        raise SystemExit(f"Unknown dataset/source: {', '.join(sorted(missing))}. Known: {known}")
    return selected


def normalize_rel(path: Path) -> str:
    return path.as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_source_files(config: dict[str, Any], dataset: DatasetConfig) -> list[Path]:
    sources_root = PROJECT_ROOT / config.get("sources_root", "sources")
    root = sources_root / dataset.source_dir
    if not root.exists():
        return []
    include_exts = {ext.lower() for ext in config.get("default_include_extensions", [])}
    exclude_dirs = set(config.get("exclude_dirs", []))
    exclude_files = set(config.get("exclude_files", []))
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in exclude_dirs for part in rel_parts[:-1]):
            continue
        if path.name in exclude_files:
            continue
        if include_exts and path.suffix.lower() not in include_exts:
            continue
        files.append(path)
    return sorted(files)


def source_key(dataset: DatasetConfig, file_path: Path, config: dict[str, Any]) -> str:
    sources_root = PROJECT_ROOT / config.get("sources_root", "sources")
    return normalize_rel(file_path.relative_to(sources_root))


def upload_name_and_path(file_path: Path, config: dict[str, Any], dataset: DatasetConfig) -> tuple[str, Path | None]:
    suffix = file_path.suffix.lower()
    sources_root = PROJECT_ROOT / config.get("sources_root", "sources")
    rel = normalize_rel(file_path.relative_to(sources_root))
    if suffix in SUPPORTED_DIRECT_EXTENSIONS:
        return rel, None
    if suffix in TEXT_WRAP_EXTENSIONS:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        wrapped = f"Original path: {rel}\nOriginal suffix: {suffix}\n\n{text}"
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
        with tmp:
            tmp.write(wrapped)
        return f"{rel}.txt", Path(tmp.name)
    raise RuntimeError(f"Unsupported extension after filtering: {file_path}")


def state_path(config: dict[str, Any]) -> Path:
    return PROJECT_ROOT / config.get("state_path", "var/ragflow-sync-state.json")


def initial_state() -> dict[str, Any]:
    return {"version": 1, "files": {}}


def get_file_state(state: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = state.get("files", {}).get(key)
    return value if isinstance(value, dict) else None


def put_file_state(state: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    state.setdefault("files", {})[key] = value


def remove_dataset_state(state: dict[str, Any], dataset: DatasetConfig) -> None:
    files = state.setdefault("files", {})
    for key in list(files):
        if key.startswith(dataset.source_dir + "/"):
            del files[key]


def list_remote_docs(base_url: str, api_key: str, dataset: DatasetConfig) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    page = 1
    page_size = 200
    while True:
        payload = request_json(
            "GET",
            base_url,
            api_key,
            f"/datasets/{dataset.dataset_id}/documents",
            params={"page": page, "page_size": page_size, "orderby": "create_time", "desc": False},
        )
        data = payload.get("data") or {}
        batch = data.get("docs") or []
        docs.extend(batch)
        total = int(data.get("total") or len(docs))
        if not batch or len(docs) >= total:
            break
        page += 1
    return docs


def upload_one(
    base_url: str,
    api_key: str,
    config: dict[str, Any],
    dataset: DatasetConfig,
    file_path: Path,
) -> dict[str, Any]:
    upload_name, tmp_path = upload_name_and_path(file_path, config, dataset)
    actual_path = tmp_path or file_path
    mime = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
    try:
        with actual_path.open("rb") as fh:
            payload = request_json(
                "POST",
                base_url,
                api_key,
                f"/datasets/{dataset.dataset_id}/documents",
                params={"return_raw_files": "true"},
                files={"file": (upload_name, fh, mime)},
            )
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
    docs = payload.get("data") or []
    if not docs:
        raise RuntimeError(f"Upload returned no document for {file_path}")
    return docs[0]


def delete_docs(base_url: str, api_key: str, dataset: DatasetConfig, ids: list[str]) -> None:
    if not ids:
        return
    request_json("DELETE", base_url, api_key, f"/datasets/{dataset.dataset_id}/documents", json_body={"ids": ids})


def parse_docs(base_url: str, api_key: str, dataset: DatasetConfig, ids: list[str]) -> None:
    if not ids:
        return
    request_json(
        "POST",
        base_url,
        api_key,
        f"/datasets/{dataset.dataset_id}/documents/parse",
        json_body={"document_ids": ids},
    )


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config()
    state = load_json(state_path(config), initial_state())
    for dataset in pick_datasets(config, args.dataset):
        files = iter_source_files(config, dataset)
        counts = {"new": 0, "same": 0, "changed": 0, "missing_local": 0}
        live_keys = set()
        for file_path in files:
            key = source_key(dataset, file_path, config)
            live_keys.add(key)
            digest = sha256_file(file_path)
            item = get_file_state(state, key)
            if not item:
                counts["new"] += 1
            elif item.get("sha256") == digest and item.get("document_id"):
                counts["same"] += 1
            else:
                counts["changed"] += 1
        for key, item in state.get("files", {}).items():
            if key.startswith(dataset.source_dir + "/") and key not in live_keys and item.get("document_id"):
                counts["missing_local"] += 1
        print(
            f"{dataset.source_dir} -> {dataset.dataset_name} ({dataset.dataset_id}): "
            f"new={counts['new']} same={counts['same']} changed={counts['changed']} missing_local={counts['missing_local']}"
        )
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    state_file = state_path(config)
    state = load_json(state_file, initial_state())
    uploaded_for_parse: dict[str, list[str]] = {}
    for dataset in pick_datasets(config, args.dataset):
        files = iter_source_files(config, dataset)
        print(f"{dataset.source_dir}: scanning {len(files)} files")
        for file_path in files:
            key = source_key(dataset, file_path, config)
            digest = sha256_file(file_path)
            item = get_file_state(state, key)
            if item and item.get("sha256") == digest and item.get("document_id"):
                if args.verbose:
                    print(f"skip same {key}")
                continue
            if item and item.get("document_id") and item.get("sha256") != digest:
                if not args.replace_changed:
                    print(f"changed {key} (use --replace-changed to replace remote document)")
                    continue
                if args.dry_run:
                    print(f"would replace {key}")
                    continue
                print(f"delete old {key} {item['document_id']}")
                delete_docs(base_url, api_key, dataset, [item["document_id"]])
                put_file_state(
                    state,
                    key,
                    {
                        "dataset_id": dataset.dataset_id,
                        "dataset_name": dataset.dataset_name,
                        "source_dir": dataset.source_dir,
                        "sha256": item.get("sha256", ""),
                        "size": item.get("size", 0),
                        "document_id": "",
                        "document_name": item.get("document_name", ""),
                        "location": item.get("location", ""),
                        "status": "deleted_before_replace",
                    },
                )
                save_json(state_file, state)
            if args.dry_run:
                print(f"would upload {key}")
                continue
            print(f"upload {key}")
            doc = upload_one(base_url, api_key, config, dataset, file_path)
            doc_id = doc["id"]
            put_file_state(
                state,
                key,
                {
                    "dataset_id": dataset.dataset_id,
                    "dataset_name": dataset.dataset_name,
                    "source_dir": dataset.source_dir,
                    "sha256": digest,
                    "size": file_path.stat().st_size,
                    "document_id": doc_id,
                    "document_name": doc.get("name") or file_path.name,
                    "location": doc.get("location", ""),
                },
            )
            save_json(state_file, state)
            uploaded_for_parse.setdefault(dataset.dataset_id, []).append(doc_id)
    if args.parse and not args.dry_run:
        dataset_by_id = {ds.dataset_id: ds for ds in config_datasets(config)}
        for dataset_id, ids in uploaded_for_parse.items():
            dataset = dataset_by_id[dataset_id]
            print(f"parse {dataset.source_dir}: {len(ids)} documents")
            parse_docs(base_url, api_key, dataset, ids)
    return 0


def cmd_delete_all(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    state_file = state_path(config)
    state = load_json(state_file, initial_state())
    for dataset in pick_datasets(config, args.dataset):
        if not args.yes:
            raise SystemExit("delete-all requires --yes")
        print(f"delete all remote documents: {dataset.source_dir} -> {dataset.dataset_name}")
        if not args.dry_run:
            request_json(
                "DELETE",
                base_url,
                api_key,
                f"/datasets/{dataset.dataset_id}/documents",
                json_body={"delete_all": True},
            )
            remove_dataset_state(state, dataset)
            save_json(state_file, state)
    return 0


def cmd_list_remote(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    for dataset in pick_datasets(config, args.dataset):
        docs = list_remote_docs(base_url, api_key, dataset)
        print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents")
        for doc in docs[: args.limit]:
            print(f"{doc.get('id')} {doc.get('run')} {doc.get('location') or doc.get('name')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync xsj-kb sources into RAGFlow datasets.")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show local files compared with the local upload state.")
    status.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id. Can be repeated.")
    status.set_defaults(func=cmd_status)

    upload = sub.add_parser("upload", help="Upload new files serially and resume from local state.")
    upload.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id. Can be repeated.")
    upload.add_argument("--replace-changed", action="store_true", help="Delete and reupload files whose sha256 changed.")
    upload.add_argument("--parse", action="store_true", help="Start RAGFlow parsing for uploaded documents.")
    upload.add_argument("--dry-run", action="store_true", help="Print planned uploads/deletes without changing RAGFlow.")
    upload.add_argument("--verbose", action="store_true", help="Print skipped unchanged files.")
    upload.set_defaults(func=cmd_upload)

    delete_all = sub.add_parser("delete-all", help="Delete all documents in selected RAGFlow datasets and clear local state.")
    delete_all.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id. Can be repeated.")
    delete_all.add_argument("--yes", action="store_true", help="Required confirmation.")
    delete_all.add_argument("--dry-run", action="store_true", help="Print planned deletes without changing RAGFlow.")
    delete_all.set_defaults(func=cmd_delete_all)

    list_remote = sub.add_parser("list-remote", help="List documents currently in RAGFlow.")
    list_remote.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id. Can be repeated.")
    list_remote.add_argument("--limit", type=int, default=20)
    list_remote.set_defaults(func=cmd_list_remote)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted. Re-run upload to resume from saved state.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
