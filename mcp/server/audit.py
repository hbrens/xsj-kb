import asyncio
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
    max_input_text: int = 8000
    max_chunk_text: int = 4000
    max_chunks: int = 100


@dataclass
class MCPAuditCall:
    request_id: str
    started: float
    mode: str
    tool_name: str
    api_key_hash: str | None
    input_arguments: dict
    arguments: dict
    question: str | None
    question_hash: str | None
    retrieval: dict | None = None


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
            input_arguments=self._sanitize_json(arguments, self.config.max_input_text),
            arguments=argument_summary,
            question=argument_summary.get("question"),
            question_hash=argument_summary.get("question_hash"),
        )

    def attach_retrieval(self, call: MCPAuditCall, retrieval: dict | None) -> None:
        if retrieval:
            call.retrieval = self._sanitize_json(retrieval, self.config.max_input_text)

    async def record_success(self, call: MCPAuditCall, result: Any) -> None:
        result_record = self._prepare_result(result)
        await self._record_call(
            call,
            status="success",
            result=result_record["summary"],
            response=result_record["response"],
            chunks=result_record["chunks"],
            error=None,
        )

    async def record_error(self, call: MCPAuditCall, exc: Exception) -> None:
        await self._record_call(
            call,
            status="error",
            result=None,
            response=None,
            chunks=[],
            error=_truncate_text(exc, self.config.max_text),
        )

    async def _record_call(
        self,
        call: MCPAuditCall,
        *,
        status: str,
        result: dict | None,
        response: dict | None,
        chunks: list[dict],
        error: str | None,
    ) -> None:
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
            "input_json": _json_dumps(call.input_arguments),
            "retrieval_json": _json_dumps(call.retrieval) if call.retrieval is not None else None,
            "result_json": _json_dumps(result) if result is not None else None,
            "response_json": _json_dumps(response) if response is not None else None,
            "error_message": error,
        }

        try:
            await asyncio.to_thread(self._record_sync, event, chunks)
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
                input_json TEXT,
                retrieval_json TEXT,
                result_json TEXT,
                response_json TEXT,
                error_message TEXT
            )
            """
        )
        self._ensure_column(conn, "mcp_tool_calls", "input_json", "TEXT")
        self._ensure_column(conn, "mcp_tool_calls", "retrieval_json", "TEXT")
        self._ensure_column(conn, "mcp_tool_calls", "response_json", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_retrieval_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                dataset_id TEXT,
                dataset_name TEXT,
                document_id TEXT,
                document_name TEXT,
                chunk_id TEXT,
                similarity REAL,
                vector_similarity REAL,
                term_similarity REAL,
                content TEXT,
                content_hash TEXT,
                chunk_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_created_at ON mcp_tool_calls(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_tool_status ON mcp_tool_calls(tool_name, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_retrieval_chunks_request_id ON mcp_retrieval_chunks(request_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mcp_retrieval_chunks_dataset_doc ON mcp_retrieval_chunks(dataset_id, document_id)")
        conn.commit()
        self._initialized = True

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _record_sync(self, event: dict, chunks: list[dict]) -> None:
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
                    input_json,
                    retrieval_json,
                    result_json,
                    response_json,
                    error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.get("input_json"),
                    event.get("retrieval_json"),
                    event.get("result_json"),
                    event.get("response_json"),
                    event.get("error_message"),
                ),
            )
            if chunks:
                conn.executemany(
                    """
                    INSERT INTO mcp_retrieval_chunks (
                        request_id,
                        chunk_index,
                        dataset_id,
                        dataset_name,
                        document_id,
                        document_name,
                        chunk_id,
                        similarity,
                        vector_similarity,
                        term_similarity,
                        content,
                        content_hash,
                        chunk_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            event["request_id"],
                            chunk.get("chunk_index"),
                            chunk.get("dataset_id"),
                            chunk.get("dataset_name"),
                            chunk.get("document_id"),
                            chunk.get("document_name"),
                            chunk.get("chunk_id"),
                            chunk.get("similarity"),
                            chunk.get("vector_similarity"),
                            chunk.get("term_similarity"),
                            chunk.get("content"),
                            chunk.get("content_hash"),
                            _json_dumps(chunk.get("chunk_json", {})),
                        )
                        for chunk in chunks
                    ],
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

    def _prepare_result(self, result: Any) -> dict:
        response = self._response_for_audit(result)
        chunks = self._chunks_for_audit(response)
        summary = self._summarize_response(response)
        return {"summary": summary, "response": response, "chunks": chunks}

    def _response_for_audit(self, result: Any) -> dict:
        content_items = len(result) if isinstance(result, list) else None
        response = {"content_items": content_items, "items": []}
        if not isinstance(result, list):
            response["raw"] = self._sanitize_json(result, self.config.max_text)
            return response

        for item in result:
            text = getattr(item, "text", None)
            if text is None:
                response["items"].append({"type": getattr(item, "type", None)})
                continue

            try:
                data = json.loads(text)
            except Exception:
                response["items"].append(
                    {
                        "type": "text",
                        "text": _truncate_text(text, self.config.max_chunk_text),
                        "text_hash": _sha256_short(text),
                    }
                )
                continue

            response["items"].append({"type": "text", "json": self._sanitize_response_json(data)})

        return response

    def _sanitize_response_json(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return self._sanitize_json(data, self.config.max_chunk_text)

        safe = {}
        for key, value in data.items():
            if key == "chunks" and isinstance(value, list):
                safe["chunks"] = [self._sanitize_chunk_json(chunk) for chunk in value[: self.config.max_chunks]]
                if len(value) > self.config.max_chunks:
                    safe["chunks_truncated"] = {"total": len(value), "kept": self.config.max_chunks}
            else:
                safe[key] = self._sanitize_json(value, self.config.max_input_text)
        return safe

    def _sanitize_chunk_json(self, chunk: Any) -> Any:
        return self._sanitize_json(chunk, self.config.max_chunk_text)

    def _chunks_for_audit(self, response: dict) -> list[dict]:
        chunks: list[dict] = []
        for item in response.get("items", []):
            data = item.get("json")
            if not isinstance(data, dict):
                continue
            raw_chunks = data.get("chunks", [])
            if not isinstance(raw_chunks, list):
                continue
            for index, chunk in enumerate(raw_chunks):
                chunks.append(self._chunk_record(index, chunk))
        return chunks

    def _chunk_record(self, index: int, chunk: Any) -> dict:
        chunk_json = self._sanitize_chunk_json(chunk)
        if not isinstance(chunk, dict):
            return {"chunk_index": index, "chunk_json": chunk_json}

        content = self._first_text_field(chunk, ("content", "text", "chunk", "source", "document_content"))
        content_hash = _sha256_short(content) if content else None
        return {
            "chunk_index": index,
            "dataset_id": self._first_text_field(chunk, ("dataset_id", "kb_id")),
            "dataset_name": self._first_text_field(chunk, ("dataset_name", "kb_name")),
            "document_id": self._first_text_field(chunk, ("document_id", "doc_id")),
            "document_name": self._first_text_field(chunk, ("document_name", "document_keyword", "doc_name")),
            "chunk_id": self._first_text_field(chunk, ("chunk_id", "id")),
            "similarity": self._first_float_field(chunk, ("similarity", "score", "similarity_score")),
            "vector_similarity": self._first_float_field(chunk, ("vector_similarity", "vector_similarity_score")),
            "term_similarity": self._first_float_field(chunk, ("term_similarity", "term_similarity_score")),
            "content": _truncate_text(content, self.config.max_chunk_text) if content else None,
            "content_hash": content_hash,
            "chunk_json": chunk_json,
        }

    def _summarize_response(self, response: dict) -> dict:
        summary = {"content_items": response.get("content_items")}
        for item in response.get("items", []):
            data = item.get("json")
            if not isinstance(data, dict):
                text = item.get("text")
                if text:
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

    def _sanitize_json(self, value: Any, text_limit: int) -> Any:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return _truncate_text(value, text_limit)
        if isinstance(value, dict):
            return {str(key): self._sanitize_json(val, text_limit) for key, val in value.items()}
        if isinstance(value, list | tuple | set):
            return [self._sanitize_json(item, text_limit) for item in value]
        return _truncate_text(value, text_limit)

    def _first_text_field(self, data: dict, keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            text = str(value)
            if text:
                return text
        return None

    def _first_float_field(self, data: dict, keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None


audit_store = MCPAuditStore()
