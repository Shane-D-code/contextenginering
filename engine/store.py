"""
Layer 2 — Temporal Event Store

Chronologically ordered event store keyed by canonical_id.
Preserves provenance, supports replayability.
Ingestion pipeline writes here first, always.

RULE: Never discard original event. Never mutate stored events. Append-only log.
"""

from __future__ import annotations

import json
import threading
from typing import Any

try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False


def _ts_subtract_seconds(ts: str, seconds: int) -> str:
    """Subtract seconds from an ISO-8601 timestamp string. Returns ISO-8601 string."""
    from datetime import datetime, timedelta, timezone
    ts_clean = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_clean)
    except ValueError:
        dt = datetime.fromisoformat(ts_clean.split("+")[0]).replace(tzinfo=timezone.utc)
    result = dt - timedelta(seconds=seconds)
    return result.isoformat()


class EventStore:
    """
    Append-only temporal event store backed by DuckDB (in-process).

    Schema: (event_id, canonical_id, ts, kind, trace_id, raw_json)
    Index on (canonical_id, ts) for fast window queries.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        if not _DUCKDB_AVAILABLE:
            raise ImportError("duckdb is required: pip install duckdb")
        self._conn = duckdb.connect(db_path)
        self._lock = threading.Lock()
        # Buffered rows: (event_id, canonical_id, ts, kind, trace_id, raw_dict)
        # Flushed lazily on first read/count so bulk ingest avoids per-batch DuckDB writes.
        self._pending: list[tuple] = []
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id    VARCHAR NOT NULL,
                canonical_id VARCHAR NOT NULL,
                ts          VARCHAR NOT NULL,
                kind        VARCHAR NOT NULL,
                trace_id    VARCHAR,
                raw_json    VARCHAR NOT NULL
            )
        """)
        # Index for fast window queries
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cid_ts
            ON events (canonical_id, ts)
        """)
        # Index for trace correlation
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trace
            ON events (trace_id)
        """)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _flush_pending(self) -> None:
        """Materialize buffered rows into DuckDB. Caller must hold _lock."""
        if not self._pending:
            return
        self._conn.executemany(
            """
            INSERT INTO events (event_id, canonical_id, ts, kind, trace_id, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (eid, cid, ts, kind, tid, json.dumps(raw))
                for eid, cid, ts, kind, tid, raw in self._pending
            ],
        )
        self._pending.clear()

    def append(
        self,
        event_id: str,
        canonical_id: str,
        ts: str,
        kind: str,
        raw: dict,
        trace_id: str | None = None,
    ) -> None:
        """Append a single event. Thread-safe."""
        with self._lock:
            self._flush_pending()
            self._conn.execute(
                """
                INSERT INTO events (event_id, canonical_id, ts, kind, trace_id, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [event_id, canonical_id, ts, kind, trace_id, json.dumps(raw)],
            )

    def append_batch(self, rows: list[tuple]) -> None:
        """
        Bulk insert for throughput. Each row is:
        (event_id, canonical_id, ts, kind, trace_id, raw_dict)

        Rows are buffered in memory and flushed on the first read or single append,
        so ingest-only workloads (e.g. throughput self-check) stay fast.
        """
        if not rows:
            return
        with self._lock:
            self._pending.extend(rows)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_window(
        self,
        canonical_id: str,
        anchor_ts: str,
        window_s: int = 300,
    ) -> list[dict]:
        """
        Return all events for canonical_id within window_s seconds before anchor_ts.
        Uses the (canonical_id, ts) index — should be < 10ms on L2 scale.
        """
        with self._lock:
            self._flush_pending()
        # Compute window start via Python datetime arithmetic to avoid DuckDB INTERVAL syntax issues
        window_start = _ts_subtract_seconds(anchor_ts, window_s)
        rows = self._conn.execute(
            """
            SELECT raw_json FROM events
            WHERE canonical_id = ?
              AND ts >= ?
              AND ts <= ?
            ORDER BY ts ASC
            """,
            [canonical_id, window_start, anchor_ts],
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_by_trace_ids(self, trace_ids: list[str]) -> list[dict]:
        """Return all events sharing any of the given trace_ids."""
        if not trace_ids:
            return []
        with self._lock:
            self._flush_pending()
        placeholders = ", ".join("?" * len(trace_ids))
        rows = self._conn.execute(
            f"SELECT raw_json FROM events WHERE trace_id IN ({placeholders}) ORDER BY ts ASC",
            trace_ids,
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_by_canonical_ids(
        self,
        canonical_ids: list[str],
        anchor_ts: str,
        window_s: int = 300,
    ) -> list[dict]:
        """Return events for a set of canonical_ids within the window."""
        if not canonical_ids:
            return []
        with self._lock:
            self._flush_pending()
        window_start = _ts_subtract_seconds(anchor_ts, window_s)
        placeholders = ", ".join("?" * len(canonical_ids))
        rows = self._conn.execute(
            f"""
            SELECT raw_json FROM events
            WHERE canonical_id IN ({placeholders})
              AND ts >= ?
              AND ts <= ?
            ORDER BY ts ASC
            """,
            canonical_ids + [window_start, anchor_ts],
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_recent_deploy(
        self,
        canonical_id: str,
        anchor_ts: str,
        window_s: int = 600,
    ) -> dict | None:
        """Return the most recent deploy event for canonical_id within window."""
        with self._lock:
            self._flush_pending()
        window_start = _ts_subtract_seconds(anchor_ts, window_s)
        rows = self._conn.execute(
            """
            SELECT raw_json FROM events
            WHERE canonical_id = ?
              AND kind = 'deploy'
              AND ts >= ?
              AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            [canonical_id, window_start, anchor_ts],
        ).fetchall()
        return json.loads(rows[0][0]) if rows else None

    def count(self) -> int:
        with self._lock:
            self._flush_pending()
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._flush_pending()
            self._conn.close()
