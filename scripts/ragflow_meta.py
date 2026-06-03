#!/usr/bin/env python3
"""Update document metadata (meta_fields) in RAGFlow datasets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragflow_sync import (
    config_datasets,
    get_credentials,
    list_remote_docs,
    load_config,
    pick_datasets,
    request_json,
    sha256_file,
    source_key,
    iter_source_files,
)
from state import SyncState

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_URL_PREFIX = "http://mock.abc.com/"


def open_state(config: dict) -> SyncState:
    from ragflow_sync import open_state as _open_state
    return _open_state(config)


def doc_label(doc: dict) -> str:
    return doc.get("location") or doc.get("name") or doc["id"][:12]


def build_doc_index(state: SyncState, source_dir: str) -> dict[str, dict]:
    """Build a mapping of document_id -> state row for a source dir."""
    idx: dict[str, dict] = {}
    for row in state.files_by_source(source_dir):
        did = row.get("document_id", "")
        if did:
            idx[did] = row
    return idx


def patch_document_meta(
    base_url: str,
    api_key: str,
    dataset_id: str,
    document_id: str,
    meta_fields: dict,
) -> dict:
    """PATCH a single document's meta_fields via RAGFlow SDK API."""
    return request_json(
        "PATCH",
        base_url,
        api_key,
        f"/datasets/{dataset_id}/documents/{document_id}",
        json_body={"meta_fields": meta_fields},
    )


def cmd_set_source_url(args: argparse.Namespace) -> int:
    """Set source_url = MOCK_URL_PREFIX + sha256 for every matching document."""
    config = load_config()
    base_url, api_key = get_credentials(config)
    state = open_state(config)
    try:
        target_datasets = pick_datasets(config, args.dataset)
        doc_ids_set: set[str] | None = set(args.doc_ids) if args.doc_ids else None

        total_ok = 0
        total_skip = 0
        total_fail = 0

        for dataset in target_datasets:
            docs = list_remote_docs(base_url, api_key, dataset)
            state_index = build_doc_index(state, dataset.source_dir)

            if doc_ids_set:
                docs = [d for d in docs if d["id"] in doc_ids_set]

            print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents to process")

            for doc in docs:
                doc_id = doc["id"]
                state_row = state_index.get(doc_id)

                if not state_row:
                    print(f"  SKIP {doc_label(doc)}: not tracked in local state (no sha256)")
                    total_skip += 1
                    continue

                sha = state_row.get("sha256", "")
                if not sha:
                    print(f"  SKIP {doc_label(doc)}: empty sha256 in state")
                    total_skip += 1
                    continue

                source_url = f"{MOCK_URL_PREFIX}{sha}"
                meta_fields = {"source_url": source_url}

                if args.dry_run:
                    print(f"  [dry-run] {doc_label(doc)}: source_url={source_url}")
                    total_ok += 1
                    continue

                try:
                    patch_document_meta(base_url, api_key, dataset.dataset_id, doc_id, meta_fields)
                    print(f"  OK   {doc_label(doc)}: source_url={source_url}")
                    total_ok += 1
                except Exception as exc:
                    print(f"  FAIL {doc_label(doc)}: {exc}")
                    total_fail += 1

        print(f"\nSummary: ok={total_ok} skip={total_skip} fail={total_fail}")
        return 1 if total_fail else 0
    finally:
        state.close()


def cmd_set_meta(args: argparse.Namespace) -> int:
    """Set arbitrary key=value pairs on document metadata."""
    config = load_config()
    base_url, api_key = get_credentials(config)
    state = open_state(config)
    try:
        target_datasets = pick_datasets(config, args.dataset)
        doc_ids_set: set[str] | None = set(args.doc_ids) if args.doc_ids else None

        kv: dict[str, str] = {}
        for item in args.set:
            if "=" not in item:
                print(f"Error: --set expects key=value, got: {item}")
                return 1
            k, v = item.split("=", 1)
            kv[k.strip()] = v.strip()

        total_ok = 0
        total_fail = 0

        for dataset in target_datasets:
            docs = list_remote_docs(base_url, api_key, dataset)
            if doc_ids_set:
                docs = [d for d in docs if d["id"] in doc_ids_set]

            print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents to process")

            for doc in docs:
                doc_id = doc["id"]
                if args.dry_run:
                    print(f"  [dry-run] {doc_label(doc)}: {kv}")
                    total_ok += 1
                    continue
                try:
                    patch_document_meta(base_url, api_key, dataset.dataset_id, doc_id, kv)
                    print(f"  OK   {doc_label(doc)}: {kv}")
                    total_ok += 1
                except Exception as exc:
                    print(f"  FAIL {doc_label(doc)}: {exc}")
                    total_fail += 1

        print(f"\nSummary: ok={total_ok} fail={total_fail}")
        return 1 if total_fail else 0
    finally:
        state.close()


def cmd_show(args: argparse.Namespace) -> int:
    """Show current metadata of remote documents."""
    config = load_config()
    base_url, api_key = get_credentials(config)

    for dataset in pick_datasets(config, args.dataset):
        docs = list_remote_docs(base_url, api_key, dataset)
        print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents")
        for doc in docs[: args.limit]:
            name = doc_label(doc)
            meta = doc.get("meta_fields") or doc.get("meta") or {}
            run = doc.get("run", "")
            print(f"  [{run:7s}] {name}  meta={json.dumps(meta, ensure_ascii=False) if meta else '{}'}")
        if args.limit and len(docs) > args.limit:
            print(f"  ... and {len(docs) - args.limit} more")
    return 0


def cmd_hash_source(args: argparse.Namespace) -> int:
    """Compute and show sha256 for local source files."""
    config = load_config()
    state = open_state(config)
    try:
        for dataset in pick_datasets(config, args.dataset):
            files = iter_source_files(config, dataset)
            print(f"{dataset.source_dir}: {len(files)} files")
            for fp in files[: args.limit]:
                key = source_key(dataset, fp, config)
                sha = sha256_file(fp)
                print(f"  {sha[:16]}...  {key}")
            if args.limit and len(files) > args.limit:
                print(f"  ... and {len(files) - args.limit} more")
    finally:
        state.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage document metadata (meta_fields) in RAGFlow datasets."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ssu = sub.add_parser(
        "set-source-url",
        help="Set source_url = http://mock.abc.com/<sha256> for documents.",
    )
    p_ssu.add_argument("--dataset", action="append", help="Filter by source dir / dataset name / id.")
    p_ssu.add_argument("--doc-ids", nargs="*", help="Only update these document IDs.")
    p_ssu.add_argument("--dry-run", action="store_true", help="Print planned updates without calling API.")
    p_ssu.set_defaults(func=cmd_set_source_url)

    p_sm = sub.add_parser(
        "set-meta",
        help="Set arbitrary key=value metadata fields on documents.",
    )
    p_sm.add_argument("--dataset", action="append")
    p_sm.add_argument("--doc-ids", nargs="*", help="Only update these document IDs.")
    p_sm.add_argument("--set", required=True, nargs="+", metavar="KEY=VALUE", help="Metadata key=value pairs.")
    p_sm.add_argument("--dry-run", action="store_true")
    p_sm.set_defaults(func=cmd_set_meta)

    p_show = sub.add_parser("show", help="Show current document metadata from RAGFlow.")
    p_show.add_argument("--dataset", action="append")
    p_show.add_argument("--limit", type=int, default=20)
    p_show.set_defaults(func=cmd_show)

    p_hash = sub.add_parser("hash-source", help="Show sha256 of local source files.")
    p_hash.add_argument("--dataset", action="append")
    p_hash.add_argument("--limit", type=int, default=20)
    p_hash.set_defaults(func=cmd_hash_source)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
