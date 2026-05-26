#!/usr/bin/env python3
"""Delete documents from RAGFlow datasets with various filters."""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragflow_sync import (
    DatasetConfig,
    config_datasets,
    delete_docs,
    get_credentials,
    list_remote_docs,
    load_config,
    open_state,
    pick_datasets,
    request_json,
)
from state import SyncState


def doc_label(doc: dict) -> str:
    return doc.get("location") or doc.get("name") or doc["id"][:12]


def confirm_action(prompt: str, auto_yes: bool, dry_run: bool) -> bool:
    if dry_run:
        print(f"[dry-run] {prompt}")
        return False
    if auto_yes:
        print(f"{prompt} --yes")
        return True
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def remove_doc_from_state(state: SyncState, dataset: DatasetConfig, doc_name: str) -> bool:
    """Remove a document from local state by matching its name/location."""
    for row in state.files_by_source(dataset.source_dir):
        state_name = row.get("document_name") or row.get("location") or ""
        if state_name == doc_name or row["path"].endswith(doc_name):
            state.remove_file(row["path"])
            return True
    return False


def cmd_all(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    state = open_state(config)
    try:
        for dataset in pick_datasets(config, args.dataset):
            docs = list_remote_docs(base_url, api_key, dataset)
            print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents")
            if not docs:
                print("  (empty, nothing to delete)")
                continue
            prompt = f"Delete ALL {len(docs)} documents from {dataset.dataset_name}?"
            if not confirm_action(prompt, args.yes, args.dry_run):
                print("  skipped.")
                continue
            try:
                request_json(
                    "DELETE",
                    base_url,
                    api_key,
                    f"/datasets/{dataset.dataset_id}/documents",
                    json_body={"delete_all": True},
                )
            except RuntimeError as e:
                # RAGFlow may return error code even when delete partially succeeds
                # (e.g. "Document not found" for already-deleted docs). Continue cleanup.
                print(f"  warning: {e}")
            state.remove_dataset(dataset.source_dir)
            print(f"  deleted {len(docs)} documents.")
    finally:
        state.close()
    return 0


def cmd_by_pattern(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    state = open_state(config)
    try:
        for dataset in pick_datasets(config, args.dataset):
            docs = list_remote_docs(base_url, api_key, dataset)
            matched = [d for d in docs if fnmatch.fnmatch(doc_label(d), args.pattern)]
            print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(matched)}/{len(docs)} match '{args.pattern}'")
            if not matched:
                continue
            for doc in matched:
                print(f"  {doc_label(doc)}")
            prompt = f"Delete {len(matched)} documents?"
            if not confirm_action(prompt, args.yes, args.dry_run):
                print("  skipped.")
                continue
            ids = [d["id"] for d in matched]
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                batch = ids[i : i + batch_size]
                delete_docs(base_url, api_key, dataset, batch)
            removed = 0
            for doc in matched:
                if remove_doc_from_state(state, dataset, doc_label(doc)):
                    removed += 1
            print(f"  deleted {len(matched)} documents, cleared {removed} local state entries.")
    finally:
        state.close()
    return 0


def cmd_by_status(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    state = open_state(config)
    try:
        status_map = {
            "fail": "FAIL",
            "done": "DONE",
            "running": "RUNNING",
            "pending": "UNSTART",
        }
        target_run = status_map.get(args.status.lower())
        if not target_run:
            print(f"Unknown status: {args.status}. Choose from: {', '.join(status_map)}")
            return 1

        for dataset in pick_datasets(config, args.dataset):
            docs = list_remote_docs(base_url, api_key, dataset)
            if target_run == "UNSTART":
                matched = [d for d in docs if d.get("run", "") in ("", "UNSTART")]
            else:
                matched = [d for d in docs if d.get("run") == target_run]
            print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(matched)}/{len(docs)} with status={args.status}")
            if not matched:
                continue
            for doc in matched[:20]:
                print(f"  {doc_label(doc)}")
            if len(matched) > 20:
                print(f"  ... and {len(matched) - 20} more")
            prompt = f"Delete {len(matched)} documents?"
            if not confirm_action(prompt, args.yes, args.dry_run):
                print("  skipped.")
                continue
            ids = [d["id"] for d in matched]
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                batch = ids[i : i + batch_size]
                delete_docs(base_url, api_key, dataset, batch)
            removed = 0
            for doc in matched:
                if remove_doc_from_state(state, dataset, doc_label(doc)):
                    removed += 1
            print(f"  deleted {len(matched)} documents, cleared {removed} local state entries.")
    finally:
        state.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete documents from RAGFlow datasets.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_all = sub.add_parser("all", help="Delete ALL documents in selected datasets.")
    p_all.add_argument("--dataset", action="append")
    p_all.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    p_all.add_argument("--dry-run", action="store_true")
    p_all.set_defaults(func=cmd_all)

    p_pat = sub.add_parser("by-pattern", help="Delete documents matching a filename glob pattern.")
    p_pat.add_argument("--dataset", action="append")
    p_pat.add_argument("--pattern", required=True, help="Glob pattern to match document name/location.")
    p_pat.add_argument("--yes", action="store_true")
    p_pat.add_argument("--dry-run", action="store_true")
    p_pat.set_defaults(func=cmd_by_pattern)

    p_stat = sub.add_parser("by-status", help="Delete documents by parsing status.")
    p_stat.add_argument("--dataset", action="append")
    p_stat.add_argument("--status", required=True, choices=["fail", "done", "running", "pending"])
    p_stat.add_argument("--yes", action="store_true")
    p_stat.add_argument("--dry-run", action="store_true")
    p_stat.set_defaults(func=cmd_by_status)

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
