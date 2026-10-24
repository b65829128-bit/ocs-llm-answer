from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._db() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    answer TEXT NOT NULL,
                    confidence REAL,
                    model TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    hits INTEGER DEFAULT 0,
                    last_used INTEGER
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    request_id TEXT,
                    site TEXT,
                    qtype TEXT,
                    question TEXT,
                    options_json TEXT,
                    raw_answer TEXT,
                    answer TEXT,
                    confidence REAL,
                    model TEXT,
                    latency_ms INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    cache_hit INTEGER DEFAULT 0,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
                """
            )

    def get_cache(self, key: str) -> dict | None:
        now = int(time.time())
        with self._db() as conn:
            row = conn.execute(
                "SELECT answer, confidence, model, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if int(row["expires_at"]) < now:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            conn.execute(
                "UPDATE cache SET hits = hits + 1, last_used = ? WHERE key = ?",
                (now, key),
            )
            return {
                "answer": row["answer"],
                "confidence": row["confidence"],
                "model": row["model"],
            }

    def set_cache(self, key: str, answer: str, confidence: float, model: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        now = int(time.time())
        with self._db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache
                    (key, answer, confidence, model, created_at, expires_at, hits, last_used)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (key, answer, confidence, model, now, now + ttl_seconds, now),
            )

    def clear_cache(self) -> int:
        with self._db() as conn:
            cursor = conn.execute("DELETE FROM cache")
            return int(cursor.rowcount or 0)

    def log(
        self,
        *,
        ts: int,
        request_id: str,
        site: str | None,
        qtype: str,
        question: str,
        options_json: str,
        raw_answer: str | None,
        answer: str | None,
        confidence: float | None,
        model: str | None,
        latency_ms: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit: int = 0,
        error: str | None = None,
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO logs
                    (ts, request_id, site, qtype, question, options_json, raw_answer, answer,
                     confidence, model, latency_ms, prompt_tokens, completion_tokens, cache_hit, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    request_id,
                    site,
                    qtype,
                    question,
                    options_json,
                    raw_answer,
                    answer,
                    confidence,
                    model,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    cache_hit,
                    error,
                ),
            )

    def stats(self) -> dict:
        with self._db() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0])
            cache_hits = int(conn.execute("SELECT COUNT(*) FROM logs WHERE cache_hit = 1").fetchone()[0])
            errors = int(conn.execute("SELECT COUNT(*) FROM logs WHERE error IS NOT NULL").fetchone()[0])
            avg_row = conn.execute("SELECT AVG(latency_ms) FROM logs WHERE cache_hit = 0").fetchone()
            avg_latency = round(float(avg_row[0] or 0), 1)
            by_type = {
                row["qtype"] or "unknown": int(row["count"])
                for row in conn.execute("SELECT qtype, COUNT(*) AS count FROM logs GROUP BY qtype")
            }
            cache_size = int(conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0])
        return {
            "total_requests": total,
            "cache_hits": cache_hits,
            "errors": errors,
            "avg_latency_ms": avg_latency,
            "by_type": by_type,
            "cache_entries": cache_size,
        }
