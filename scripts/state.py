#!/usr/bin/env python3
"""SQLite-backed state store for RAGFlow sync."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path            TEXT PRIMARY KEY,
    source_dir      TEXT NOT NULL,
    dataset_id      TEXT NOT NULL,
    dataset_name    TEXT NOT NULL DEFAULT '',
    document_id     TEXT NOT NULL DEFAULT '',
    document_name   TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    sha256          TEXT NOT NULL DEFAULT '',
    size            INTEGER NOT NULL DEFAULT 0,
    local_status    TEXT NOT NULL DEFAULT '',
    remote_status   TEXT NOT NULL DEFAULT '',
    remote_msg      TEXT NOT NULL DEFAULT '',
    last_verified   TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_files_source_dir   ON files(source_dir);
CREATE INDEX IF NOT EXISTS idx_files_dataset_id   ON files(dataset_id);
CREATE INDEX IF NOT EXISTS idx_files_local_status ON files(local_status);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyncState:
    """Thin wrapper around a SQLite database for sync state."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    @contextmanager
    def transaction(self):
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            yield cur
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()

    def upsert_file(self, rec: dict[str, Any]) -> None:
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO files (path, source_dir, dataset_id, dataset_name,
                               document_id, document_name, location,
                               sha256, size, local_status, remote_status,
                               remote_msg, last_verified, updated_at)
            VALUES (:path, :source_dir, :dataset_id, :dataset_name,
                    :document_id, :document_name, :location,
                    :sha256, :size, :local_status, :remote_status,
                    :remote_msg, :last_verified, :updated_at)
            ON CONFLICT(path) DO UPDATE SET
                document_id   = excluded.document_id,
                document_name = excluded.document_name,
                location      = excluded.location,
                sha256        = excluded.sha256,
                size          = excluded.size,
                local_status  = excluded.local_status,
                remote_status = CASE WHEN excluded.remote_status != ''
                                     THEN excluded.remote_status
                                     ELSE files.remote_status END,
                remote_msg    = CASE WHEN excluded.remote_msg != ''
                                     THEN excluded.remote_msg
                                     ELSE files.remote_msg END,
                last_verified = CASE WHEN excluded.last_verified != ''
                                     THEN excluded.last_verified
                                     ELSE files.last_verified END,
                updated_at    = :updated_at
            """,
            {**rec, "updated_at": now},
        )
        self._conn.commit()

    def get_file(self, path: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM files WHERE path = ?", (path,),
        ).fetchone()
        return dict(row) if row else None

    def remove_file(self, path: str) -> None:
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.commit()

    def remove_dataset(self, source_dir: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM files WHERE source_dir = ?", (source_dir,),
        )
        self._conn.commit()
        return cur.rowcount

    _UPSERT_SQL = """
        INSERT INTO files (path, source_dir, dataset_id, dataset_name,
                           document_id, document_name, location,
                           sha256, size, local_status, remote_status,
                           remote_msg, last_verified, updated_at)
        VALUES (:path, :source_dir, :dataset_id, :dataset_name,
                :document_id, :document_name, :location,
                :sha256, :size, :local_status, :remote_status,
                :remote_msg, :last_verified, :updated_at)
        ON CONFLICT(path) DO UPDATE SET
            document_id   = excluded.document_id,
            document_name = excluded.document_name,
            location      = excluded.location,
            sha256        = excluded.sha256,
            size          = excluded.size,
            local_status  = excluded.local_status,
            remote_status = CASE WHEN excluded.remote_status != ''
                                 THEN excluded.remote_status
                                 ELSE files.remote_status END,
            remote_msg    = CASE WHEN excluded.remote_msg != ''
                                 THEN excluded.remote_msg
                                 ELSE files.remote_msg END,
            last_verified = CASE WHEN excluded.last_verified != ''
                                 THEN excluded.last_verified
                                 ELSE files.last_verified END,
            updated_at    = :updated_at
    """

    def upsert_many(self, records: list[dict[str, Any]]) -> int:
        now = _now_iso()
        with self.transaction() as cur:
            for rec in records:
                cur.execute(self._UPSERT_SQL, {**rec, "updated_at": now})
        return len(records)

    def files_by_source(self, source_dir: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM files WHERE source_dir = ? ORDER BY path",
            (source_dir,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_by_local_status(self, source_dir: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT local_status, COUNT(*) AS cnt FROM files "
            "WHERE source_dir = ? GROUP BY local_status",
            (source_dir,),
        ).fetchall()
        return {r["local_status"]: r["cnt"] for r in rows}

    def count_by_remote_status(self, source_dir: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT remote_status, COUNT(*) AS cnt FROM files "
            "WHERE source_dir = ? GROUP BY remote_status",
            (source_dir,),
        ).fetchall()
        return {r["remote_status"]: r["cnt"] for r in rows}

    def doc_ids_for_source(self, source_dir: str) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT document_id, path FROM files "
            "WHERE source_dir = ? AND document_id != ''",
            (source_dir,),
        ).fetchall()
        return {r["document_id"]: r["path"] for r in rows}

    def update_remote_status(
        self, source_dir: str, doc_id: str, status: str, msg: str = "",
    ) -> None:
        self._conn.execute(
            "UPDATE files SET remote_status = ?, remote_msg = ?, last_verified = ? "
            "WHERE source_dir = ? AND document_id = ?",
            (status, msg, _now_iso(), source_dir, doc_id),
        )
        self._conn.commit()

    def update_remote_batch(
        self, source_dir: str, updates: list[tuple[str, str, str]],
    ) -> None:
        now = _now_iso()
        with self.transaction() as cur:
            for doc_id, status, msg in updates:
                cur.execute(
                    "UPDATE files SET remote_status = ?, remote_msg = ?, last_verified = ? "
                    "WHERE source_dir = ? AND document_id = ?",
                    (status, msg, now, source_dir, doc_id),
                )

    def mark_remote_missing(self, source_dir: str, live_doc_ids: set[str]) -> int:
        all_docs = self.doc_ids_for_source(source_dir)
        missing = [
            (doc_id, "missing", "document not found in RAGFlow")
            for doc_id in all_docs
            if doc_id not in live_doc_ids
        ]
        if missing:
            self.update_remote_batch(source_dir, missing)
        return len(missing)
