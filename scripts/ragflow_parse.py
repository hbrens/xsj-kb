#!/usr/bin/env python3
"""Parse documents in RAGFlow datasets and track progress."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow importing from the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragflow_sync import (
    DatasetConfig,
    config_datasets,
    get_credentials,
    list_remote_docs,
    load_config,
    pick_datasets,
    request_json,
)

RUN_STATUS_LABELS = {
    "DONE": "done",
    "FAIL": "fail",
    "RUNNING": "running",
    "UNSTART": "pending",
    "": "pending",
}


def trigger_parse(base_url: str, api_key: str, dataset: DatasetConfig, doc_ids: list[str]) -> None:
    if not doc_ids:
        return
    request_json(
        "POST",
        base_url,
        api_key,
        f"/datasets/{dataset.dataset_id}/documents/parse",
        json_body={"document_ids": doc_ids},
    )


def refresh_docs(base_url: str, api_key: str, dataset: DatasetConfig, doc_ids: set[str]) -> list[dict]:
    """Re-fetch only the documents we care about."""
    all_docs = list_remote_docs(base_url, api_key, dataset)
    return [d for d in all_docs if d["id"] in doc_ids]


def doc_label(doc: dict) -> str:
    return doc.get("location") or doc.get("name") or doc["id"][:12]


def progress_bar(ratio: float, width: int = 20) -> str:
    filled = int(width * max(0.0, min(1.0, ratio)))
    return f"[{'#' * filled}{'.' * (width - filled)}]"


def summarize_docs_status(docs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in docs:
        label = RUN_STATUS_LABELS.get(doc.get("run", ""), "unknown")
        counts[label] = counts.get(label, 0) + 1
    return counts


def print_status_table(docs: list[dict], limit: int = 0) -> None:
    if not docs:
        print("  (no documents)")
        return
    show = docs[:limit] if limit > 0 else docs
    for doc in show:
        run = doc.get("run", "")
        progress = doc.get("progress", 0) or 0
        chunks = doc.get("chunk_count", 0)
        label = RUN_STATUS_LABELS.get(run, run or "unknown")
        pct = f"{progress * 100:.0f}%" if progress >= 0 else "n/a"
        name = doc_label(doc)
        line = f"  {label:8s} {pct:>5s}  chunks={chunks:<5d} {name}"
        if run == "FAIL":
            msg = (doc.get("progress_msg") or "").strip().split("\n")
            err = msg[-1][:120] if msg else ""
            line += f"\n           {err}"
        print(line)
    if limit > 0 and len(docs) > limit:
        print(f"  ... and {len(docs) - limit} more")


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    for dataset in pick_datasets(config, args.dataset):
        docs = list_remote_docs(base_url, api_key, dataset)
        summary = summarize_docs_status(docs)
        parts = ", ".join(f"{v} {k}" for k, v in sorted(summary.items()))
        print(f"{dataset.source_dir} -> {dataset.dataset_name}: {len(docs)} documents ({parts})")
        print_status_table(docs, limit=args.limit)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config()
    base_url, api_key = get_credentials(config)
    dataset_by_id = {ds.dataset_id: ds for ds in config_datasets(config)}
    target_datasets = pick_datasets(config, args.dataset)
    deadline = time.time() + args.timeout

    # Collect documents to parse
    targets: dict[str, list[str]] = {}  # dataset_id -> doc_ids
    for dataset in target_datasets:
        docs = list_remote_docs(base_url, api_key, dataset)
        if args.only_failed:
            ids = [d["id"] for d in docs if d.get("run") == "FAIL"]
        else:
            ids = [d["id"] for d in docs if d.get("run") != "DONE"]
        if ids:
            targets[dataset.dataset_id] = ids
            print(f"{dataset.dataset_name}: {len(ids)} documents to parse")
        else:
            print(f"{dataset.dataset_name}: nothing to parse")

    if not targets:
        print("All documents already parsed.")
        return 0

    # Trigger parsing
    for dataset_id, ids in targets.items():
        ds = dataset_by_id[dataset_id]
        print(f"Triggering parse for {ds.dataset_name} ({len(ids)} docs)...")
        trigger_parse(base_url, api_key, ds, ids)

    # Poll loop
    all_doc_ids: dict[str, set[str]] = {did: set(ids) for did, ids in targets.items()}
    start_time = time.time()

    print()
    while True:
        total_done = 0
        total_docs = 0
        any_running = False

        for dataset_id, doc_ids in all_doc_ids.items():
            ds = dataset_by_id[dataset_id]
            docs = refresh_docs(base_url, api_key, ds, doc_ids)
            summary = summarize_docs_status(docs)
            done_count = summary.get("done", 0)
            fail_count = summary.get("fail", 0)
            running_count = summary.get("running", 0)
            pending_count = summary.get("pending", 0)
            total_done += done_count
            total_docs += len(docs)

            if running_count > 0 or pending_count > 0:
                any_running = True

            # Show per-document progress for running items
            for doc in docs:
                run = doc.get("run", "")
                if run in ("RUNNING", ""):
                    progress = doc.get("progress", 0) or 0
                    chunks = doc.get("chunk_count", 0)
                    print(f"  {progress_bar(progress)} {progress * 100:5.1f}%  chunks={chunks:<5d} {doc_label(doc)}")

            # Dataset summary
            elapsed = time.time() - start_time
            print(
                f"  [{ds.dataset_name}] done={done_count} running={running_count} "
                f"pending={pending_count} failed={fail_count}  ({elapsed:.0f}s)"
            )

        # Overall summary
        overall_pct = (total_done / total_docs * 100) if total_docs else 0
        elapsed = time.time() - start_time
        print(f"  Overall: {total_done}/{total_docs} done ({overall_pct:.0f}%)  elapsed={elapsed:.0f}s")
        print()

        # Check completion
        if not any_running:
            break
        if time.time() >= deadline:
            print("Timeout reached. Some documents may still be processing.")
            return 1

        time.sleep(args.interval)

    # Final summary
    print("=== Parse Complete ===")
    for dataset_id, doc_ids in all_doc_ids.items():
        ds = dataset_by_id[dataset_id]
        docs = refresh_docs(base_url, api_key, ds, doc_ids)
        summary = summarize_docs_status(docs)
        print(f"  {ds.dataset_name}: {summary}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse documents in RAGFlow datasets.")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show parsing status of remote documents.")
    status.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id.")
    status.add_argument("--limit", type=int, default=0, help="Max docs to show per dataset (0=all).")
    status.set_defaults(func=cmd_status)

    run = sub.add_parser("run", help="Trigger parsing and poll until completion.")
    run.add_argument("--dataset", action="append", help="Source dir, dataset name, or dataset id.")
    run.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds (default: 5).")
    run.add_argument("--timeout", type=float, default=600.0, help="Max wait time in seconds (default: 600).")
    run.add_argument("--only-failed", action="store_true", help="Only re-parse documents that previously failed.")
    run.set_defaults(func=cmd_run)

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
