import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "var" / "mcp_audit.sqlite3"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _truncate_text(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None

    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class MCPAuditConfig:
    enabled: bool = True
    db_path: str = str(DEFAULT_DB_PATH)
    log_question: bool = True
    max_text: int = 1000


@dataclass
class MCPAuditCall:
    request_id: str
    started: float
    mode: str
    tool_name: str
    api_key_hash: str | None
    arguments: dict
    question: str | None
    question_hash: str | None


class MCPAuditStore:
    def __init__(self, config: MCPAuditConfig | None = None) -> None:
        self.config = config or MCPAuditConfig()
        self._initialized = False

    def configure(self, config: MCPAuditConfig) -> None:
        self.config = config
        self._initialized = False

    def start_call(self, *, mode: str, tool_name: str, arguments: dict, api_key: str) -> MCPAuditCall:
        arguments = arguments or {}
        argument_summary = self._summarize_arguments(tool_name, arguments)
        return MCPAuditCall(
            request_id=uuid4().hex,
            started=time.perf_counter(),
            mode=mode,
            tool_name=tool_name,
            api_key_hash=_sha256_short(api_key) if api_key else None,
            arguments=argument_summary,
            question=argument_summary.get("question"),
            question_hash=argument_summary.get("question_hash"),
        )

    async def record_success(self, call: MCPAuditCall, result: Any) -> None:
        await self._record_call(call, status="success", result=self._summarize_result(result), error=None)

    async def record_error(self, call: MCPAuditCall, exc: Exception) -> None:
        await self._record_call(call, status="error", result=None, error=_truncate_text(exc, self.config.max_text))

    async def _record_call(self, call: MCPAuditCall, *, status: str, result: dict | None, error: str | None) -> None:
        if not self.config.enabled:
            return

        event = {
            "request_id": call.request_id,
            "created_at": _utc_now_iso(),
            "mode": call.mode,
            "tool_name": call.tool_name,
            "api_key_hash": call.api_key_hash,
            "status": status,
            "latency_ms": int((time.perf_counter() - call.started) * 1000),
            "question": call.question,
            "question_hash": call.question_hash,
            "arguments_json": _json_dumps(call.arguments),
            "result_json": _json_dumps(result) if result is not None else None,
            "error_message": error,
        }

        try:
            self._record_sync(event)
        except Exception as exc:
            logging.warning("Failed to write MCP audit event: %s", exc)

    def _connect(self) -> sqlite3.Connection:
        db_path = Path(self.config.db_path).expanduser()
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=3)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._initialized:
            return

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                mode TEXT,
                tool_name TEXT NOT NULL,
                api_key_hash TEXT,
                status TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                question TEXT,
                question_hash TEXT,
                arguments_json TEXT NOT NULL,
                result_json TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_created_at ON mcp_tool_calls(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_tool_status ON mcp_tool_calls(tool_name, status)")
        conn.commit()
        self._initialized = True

    def _record_sync(self, event: dict) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO mcp_tool_calls (
                    request_id,
                    created_at,
                    mode,
                    tool_name,
                    api_key_hash,
                    status,
                    latency_ms,
                    question,
                    question_hash,
                    arguments_json,
                    result_json,
                    error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["request_id"],
                    event["created_at"],
                    event.get("mode"),
                    event["tool_name"],
                    event.get("api_key_hash"),
                    event["status"],
                    event["latency_ms"],
                    event.get("question"),
                    event.get("question_hash"),
                    event["arguments_json"],
                    event.get("result_json"),
                    event.get("error_message"),
                ),
            )
            conn.commit()

    def _summarize_arguments(self, name: str, arguments: dict) -> dict:
        summary = {"tool_name": name}
        if name != "ragflow_retrieval":
            summary["argument_keys"] = sorted(arguments.keys())
            return summary

        question = arguments.get("question", "")
        summary.update(
            {
                "dataset_ids": arguments.get("dataset_ids", []),
                "document_ids": arguments.get("document_ids", []),
                "question_hash": _sha256_short(question) if question else None,
                "page": arguments.get("page", 1),
                "page_size": arguments.get("page_size", 10),
                "similarity_threshold": arguments.get("similarity_threshold", 0.2),
                "vector_similarity_weight": arguments.get("vector_similarity_weight", 0.3),
                "keyword": arguments.get("keyword", False),
                "top_k": arguments.get("top_k", 1024),
                "rerank_id": arguments.get("rerank_id"),
                "force_refresh": arguments.get("force_refresh", False),
            }
        )
        if self.config.log_question:
            summary["question"] = _truncate_text(question, self.config.max_text)
        return summary

    def _summarize_result(self, result: Any) -> dict:
        summary = {"content_items": len(result) if isinstance(result, list) else None}
        if not isinstance(result, list):
            return summary

        for item in result:
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                data = json.loads(text)
            except Exception:
                summary["first_text_length"] = len(text)
                return summary

            chunks = data.get("chunks", [])
            pagination = data.get("pagination", {})
            query_info = data.get("query_info", {})
            summary.update(
                {
                    "chunk_count": len(chunks) if isinstance(chunks, list) else None,
                    "total_chunks": pagination.get("total_chunks"),
                    "total_pages": pagination.get("total_pages"),
                    "dataset_count": query_info.get("dataset_count"),
                }
            )
            return summary

        return summary


audit_store = MCPAuditStore()
