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


def refresh_docs(base_url: str, api_key: str, dataset: DatasetConfig, doc_ids: set[str]) -> list[dict]:
    """Re-fetch only the documents we care about."""
    all_docs = list_remote_docs(base_url, api_key, dataset)
    return [d for d in all_docs if d["id"] in doc_ids]


def doc_label(doc: dict) -> str:
    return doc.get("location") or doc.get("name") or doc["id"][:12]


def progress_bar(ratio: float, width: int = 40) -> str:
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

    # Query remote status — skips DONE docs automatically (resumable on restart)
    targets: dict[str, list[str]] = {}
    all_doc_ids: dict[str, set[str]] = {}  # all doc ids for final summary
    for dataset in target_datasets:
        docs = list_remote_docs(base_url, api_key, dataset)
        all_doc_ids[dataset.dataset_id] = {d["id"] for d in docs}
        if args.only_failed:
            ids = [d["id"] for d in docs if d.get("run") == "FAIL"]
        else:
            ids = [d["id"] for d in docs if d.get("run") != "DONE"]
        if ids:
            targets[dataset.dataset_id] = ids
            done_count = sum(1 for d in docs if d.get("run") == "DONE")
            print(f"{dataset.dataset_name}: {len(ids)} to parse, {done_count} already done")
        else:
            print(f"{dataset.dataset_name}: all done")

    if not targets:
        print("All documents already parsed.")
        return 0

    # Flatten all doc ids for cross-dataset progress tracking
    batch_size = args.batch_size
    batch_interval = args.batch_interval
    global_start = time.time()
    total_batches = sum((len(ids) + batch_size - 1) // batch_size for ids in targets.values())
    batch_num = 0

    for dataset_id, ids in targets.items():
        ds = dataset_by_id[dataset_id]
        # Split into batches
        batches = [ids[i : i + batch_size] for i in range(0, len(ids), batch_size)]
        for batch_idx, batch_ids in enumerate(batches):
            batch_num += 1
            print(f"\n[{batch_num}/{total_batches}] {ds.dataset_name}: triggering {len(batch_ids)} docs...")

            try:
                request_json(
                    "POST", base_url, api_key,
                    f"/datasets/{ds.dataset_id}/documents/parse",
                    json_body={"document_ids": batch_ids},
                )
            except Exception as e:
                print(f"  ERROR triggering parse: {e}")
                continue

            # Poll until this batch is all DONE/FAIL
            batch_doc_set = set(batch_ids)
            batch_start = time.time()
            last_progress = batch_start
            prev_done = 0

            while True:
                docs = refresh_docs(base_url, api_key, ds, batch_doc_set)
                summary = summarize_docs_status(docs)
                done = summary.get("done", 0)
                fail = summary.get("fail", 0)
                running = summary.get("running", 0) + summary.get("pending", 0)
                elapsed = time.time() - batch_start
                pct = (done / len(batch_ids)) if batch_ids else 0

                status_parts = f"done={done}/{len(batch_ids)}"
                if fail:
                    status_parts += f" fail={fail}"
                if running:
                    status_parts += f" running={running}"
                print(f"\r  [{progress_bar(pct)}] {pct*100:5.1f}%  {status_parts}  ({elapsed:.0f}s)", end="", flush=True)

                if done > prev_done:
                    last_progress = time.time()
                    prev_done = done

                if running == 0:
                    break
                if time.time() - last_progress >= args.timeout:
                    print(f"\n  No progress for {args.timeout:.0f}s, moving on. {running} docs still processing.")
                    break

                time.sleep(args.interval)

            print()  # newline after progress bar

            # Interval between batches (skip after last batch)
            if batch_num < total_batches:
                print(f"  Waiting {batch_interval}s before next batch...")
                time.sleep(batch_interval)

    # Final summary
    elapsed = time.time() - global_start
    print(f"\n=== Parse Complete ({elapsed:.0f}s) ===")
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
    run.add_argument("--timeout", type=float, default=600.0, help="Stop if no new documents finish for this many seconds (default: 600).")
    run.add_argument("--only-failed", action="store_true", help="Only re-parse documents that previously failed.")
    run.add_argument("--batch-size", type=int, default=100, help="Documents per parse batch (default: 100).")
    run.add_argument("--batch-interval", type=float, default=120.0, help="Seconds to wait between batches (default: 120).")
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
