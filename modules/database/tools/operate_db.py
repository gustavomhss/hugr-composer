"""
SKILL-001 Database Tool: Operate a real PostgreSQL database — diagnostics & tuning.

Functions for connecting to a live PostgreSQL instance and extracting
actionable operational intelligence:

- check_pool_health(db_url)    -- pg_stat_activity: active, idle, waiting connections
- find_slow_queries(db_url)    -- pg_stat_statements: top N by total_time
- analyze_query(db_url, sql)   -- EXPLAIN ANALYZE with plan interpretation
- check_table_bloat(db_url)    -- dead tuples, last vacuum, autovacuum config
- suggest_indexes(db_url)      -- tables with high seq_scan ratio + suggestions

All functions accept a standard PostgreSQL connection string
(``postgresql://user:pass@host:5432/db``) and return structured dicts.
They use psycopg (sync) for simplicity — these are operational tools
run from CLI or MCP, not inside the async FastAPI event loop.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_db_health',
    'description': 'Check PostgreSQL connection pool health: active/idle/waiting connections, pool utilization.',
    'tags': ['database', 'operate'],
    'entry': 'check_pool_health',
    'annotations': {'readOnlyHint': True},
}

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

_HAS_PSYCOPG = False
try:
    import psycopg  # type: ignore[import-untyped]

    _HAS_PSYCOPG = True
except ImportError:
    pass

_HAS_PSYCOPG2 = False
if not _HAS_PSYCOPG:
    try:
        import psycopg2  # type: ignore[import-untyped]
        import psycopg2.extras  # type: ignore[import-untyped]

        _HAS_PSYCOPG2 = True
    except ImportError:
        pass


def _connect(db_url: str):
    """Create a database connection using psycopg or psycopg2.

    Returns a connection object. Caller must close it.

    Raises:
        ImportError: If neither psycopg nor psycopg2 is installed.
        ConnectionError: If the database is unreachable.
    """
    if not _HAS_PSYCOPG and not _HAS_PSYCOPG2:
        raise ImportError(
            "Database operations require psycopg (3.x) or psycopg2. "
            "Install one: pip install psycopg[binary] or pip install psycopg2-binary"
        )

    # Normalize URL: remove +asyncpg suffix if present
    url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg://", "postgresql://")

    try:
        if _HAS_PSYCOPG:
            conn = psycopg.connect(url, autocommit=True)
        else:
            conn = psycopg2.connect(url)
            conn.autocommit = True
        return conn
    except Exception as exc:
        raise ConnectionError(f"Cannot connect to database: {exc}") from exc


def _execute(conn, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Execute a query and return results as list of dicts."""
    if _HAS_PSYCOPG:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    else:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# 1. Pool Health (pg_stat_activity)
# ---------------------------------------------------------------------------


def check_pool_health(db_url: str) -> dict[str, Any]:
    """
    Analyze connection pool health via pg_stat_activity.

    Queries PostgreSQL's pg_stat_activity view to provide a real-time
    snapshot of all backend connections: how many are active, idle,
    idle in transaction, and waiting on locks.

    Args:
        db_url: PostgreSQL connection string.

    Returns:
        Dict with connection counts by state, long-running queries,
        and a health assessment.

    Example::

        health = check_pool_health("postgresql://user:pass@localhost/mydb")
        print(health["summary"])
        # {"total": 15, "active": 3, "idle": 10, "idle_in_transaction": 2,
        #  "waiting": 0}
        print(health["assessment"])
        # "HEALTHY" or "WARNING: 5 idle-in-transaction connections"
    """
    conn = _connect(db_url)
    try:
        # Connection counts by state
        rows = _execute(conn, """
            SELECT
                state,
                count(*) AS count,
                coalesce(max(extract(epoch FROM now() - state_change)), 0) AS max_duration_sec
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid != pg_backend_pid()
            GROUP BY state
            ORDER BY count DESC
        """)

        summary: dict[str, int] = {
            "total": 0,
            "active": 0,
            "idle": 0,
            "idle_in_transaction": 0,
            "idle_in_transaction_aborted": 0,
            "waiting": 0,
        }
        for row in rows:
            state = row.get("state") or "unknown"
            count = int(row.get("count", 0))
            summary["total"] += count

            if state == "active":
                summary["active"] = count
            elif state == "idle":
                summary["idle"] = count
            elif state == "idle in transaction":
                summary["idle_in_transaction"] = count
            elif state == "idle in transaction (aborted)":
                summary["idle_in_transaction_aborted"] = count

        # Count waiting connections
        waiting_rows = _execute(conn, """
            SELECT count(*) AS count
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid != pg_backend_pid()
              AND wait_event_type = 'Lock'
        """)
        if waiting_rows:
            summary["waiting"] = int(waiting_rows[0].get("count", 0))

        # Long-running queries (> 30 seconds)
        long_running = _execute(conn, """
            SELECT
                pid,
                state,
                round(extract(epoch FROM now() - query_start)::numeric, 1) AS duration_sec,
                left(query, 200) AS query_preview,
                wait_event_type,
                wait_event,
                usename,
                client_addr::text
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid != pg_backend_pid()
              AND state = 'active'
              AND query_start < now() - interval '30 seconds'
            ORDER BY query_start
        """)

        # Max connections config
        max_conn_rows = _execute(conn, "SHOW max_connections")
        max_connections = int(max_conn_rows[0].get("max_connections", 100))

        # Connection utilization
        utilization_pct = round(
            100 * summary["total"] / max_connections, 1,
        ) if max_connections > 0 else 0

        # Assessment
        issues: list[str] = []
        if summary["idle_in_transaction"] > 3:
            issues.append(
                f"WARNING: {summary['idle_in_transaction']} idle-in-transaction "
                f"connections (holding locks, blocking autovacuum)"
            )
        if summary["waiting"] > 0:
            issues.append(
                f"WARNING: {summary['waiting']} connections waiting on locks"
            )
        if utilization_pct > 80:
            issues.append(
                f"CRITICAL: {utilization_pct}% connection utilization "
                f"({summary['total']}/{max_connections})"
            )
        if long_running:
            issues.append(
                f"WARNING: {len(long_running)} queries running > 30 seconds"
            )

        assessment = "HEALTHY" if not issues else "; ".join(issues)

        return {
            "summary": summary,
            "max_connections": max_connections,
            "utilization_pct": utilization_pct,
            "long_running_queries": long_running,
            "assessment": assessment,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Slow Queries (pg_stat_statements)
# ---------------------------------------------------------------------------


def find_slow_queries(
    db_url: str,
    min_ms: float = 100,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Find the slowest queries via pg_stat_statements.

    Requires the pg_stat_statements extension to be enabled
    (``shared_preload_libraries = 'pg_stat_statements'`` in postgresql.conf).

    Returns queries sorted by total execution time, filtered to those
    with mean execution time above *min_ms* milliseconds.

    Args:
        db_url: PostgreSQL connection string.
        min_ms: Minimum mean execution time in milliseconds to include.
        limit: Maximum number of queries to return.

    Returns:
        List of dicts with query text, call count, total/mean/max time,
        and rows returned.

    Example::

        slow = find_slow_queries("postgresql://user:pass@localhost/mydb")
        for q in slow[:3]:
            print(f"{q['mean_ms']:.0f}ms avg, {q['calls']} calls: {q['query'][:80]}")
    """
    conn = _connect(db_url)
    try:
        # Check if pg_stat_statements is available
        ext_check = _execute(conn, """
            SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
        """)
        if not ext_check:
            return [{
                "error": (
                    "pg_stat_statements extension is not installed. "
                    "Add to postgresql.conf: "
                    "shared_preload_libraries = 'pg_stat_statements' "
                    "and restart PostgreSQL, then: "
                    "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
                ),
            }]

        # Query pg_stat_statements (compatible with PG13+ column names)
        rows = _execute(conn, """
            SELECT
                left(query, 500) AS query,
                calls,
                round((total_exec_time)::numeric, 2) AS total_ms,
                round((mean_exec_time)::numeric, 2) AS mean_ms,
                round((max_exec_time)::numeric, 2) AS max_ms,
                round((stddev_exec_time)::numeric, 2) AS stddev_ms,
                rows,
                round(
                    (shared_blks_hit::numeric /
                     nullif(shared_blks_hit + shared_blks_read, 0)) * 100,
                    1
                ) AS cache_hit_pct
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND mean_exec_time > %(min_ms)s
              AND query NOT LIKE '%%pg_stat%%'
            ORDER BY total_exec_time DESC
            LIMIT %(limit)s
        """, {"min_ms": min_ms, "limit": limit})

        return rows

    except Exception as exc:
        # Handle older PG versions with different column names
        if "total_exec_time" in str(exc):
            return [{
                "error": (
                    "pg_stat_statements column names differ in your PG version. "
                    "PG13+ uses total_exec_time; older versions use total_time. "
                    f"Details: {exc}"
                ),
            }]
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Query Analysis (EXPLAIN ANALYZE)
# ---------------------------------------------------------------------------


def analyze_query(db_url: str, sql: str) -> dict[str, Any]:
    """
    Run EXPLAIN ANALYZE on a query and interpret the execution plan.

    Wraps the query in a transaction and rolls back after analysis, so
    it is safe to use with SELECT, UPDATE, INSERT, and DELETE statements.

    Args:
        db_url: PostgreSQL connection string.
        sql: SQL query to analyze. Parameters should be replaced with
            literal values since EXPLAIN does not support bind parameters.

    Returns:
        Dict with the raw plan text, extracted metrics (execution time,
        rows, scan types), and actionable findings.

    Example::

        result = analyze_query(
            "postgresql://user:pass@localhost/mydb",
            "SELECT * FROM orders WHERE user_id = 42 AND status = 'active'",
        )
        print(result["execution_time_ms"])  # 1847.4
        print(result["findings"])  # [{severity: "high", ...}]
    """
    conn = _connect(db_url)
    try:
        # Disable autocommit for transactional safety
        if _HAS_PSYCOPG:
            conn.autocommit = False
        else:
            conn.autocommit = False

        try:
            plan_rows = _execute(conn, f"""
                EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
                {sql}
            """)

            plan_text = "\n".join(
                row.get("QUERY PLAN", row.get("query plan", str(row)))
                for row in plan_rows
            )

            # Extract metrics from plan
            metrics = _interpret_plan(plan_text)

            return {
                "plan": plan_text,
                **metrics,
            }
        finally:
            # Always rollback -- EXPLAIN ANALYZE executes the query
            if _HAS_PSYCOPG:
                conn.rollback()
            else:
                conn.rollback()

            # Restore autocommit
            if _HAS_PSYCOPG:
                conn.autocommit = True
            else:
                conn.autocommit = True
    finally:
        conn.close()


def _interpret_plan(plan_text: str) -> dict[str, Any]:
    """Extract actionable metrics from an EXPLAIN ANALYZE plan."""
    findings: list[dict[str, str]] = []

    # Execution time
    exec_match = re.search(r"Execution Time:\s+([\d.]+)\s+ms", plan_text)
    execution_time_ms = float(exec_match.group(1)) if exec_match else None

    planning_match = re.search(r"Planning Time:\s+([\d.]+)\s+ms", plan_text)
    planning_time_ms = float(planning_match.group(1)) if planning_match else None

    # Scan types
    seq_scans = re.findall(
        r"Seq Scan on (\w+).*?actual time=[\d.]+\.\.[\d.]+ rows=(\d+)",
        plan_text,
    )
    index_scans = re.findall(r"Index (?:Only )?Scan", plan_text)
    bitmap_scans = re.findall(r"Bitmap (?:Heap|Index) Scan", plan_text)

    # Rows removed by filter (sign of missing or bad index)
    rows_removed = re.findall(
        r"Rows Removed by Filter:\s+(\d+)", plan_text,
    )

    # Buffer usage
    shared_read_match = re.search(r"shared read=(\d+)", plan_text)
    shared_hit_match = re.search(r"shared hit=(\d+)", plan_text)
    shared_read = int(shared_read_match.group(1)) if shared_read_match else 0
    shared_hit = int(shared_hit_match.group(1)) if shared_hit_match else 0

    # Sort spill to disk
    has_disk_sort = "Sort Method: external merge" in plan_text

    # Nested loop with high loops count
    nested_loops = re.findall(r"loops=(\d+)", plan_text)
    max_loops = max((int(l) for l in nested_loops), default=0)

    # --- Generate findings ---

    for table, row_count in seq_scans:
        row_count_int = int(row_count)
        if row_count_int > 10_000:
            findings.append({
                "severity": "high",
                "issue": f"Sequential scan on '{table}' returned {row_count_int:,} rows",
                "fix": f"Add index on filter columns for table '{table}'",
            })
        elif row_count_int > 1_000:
            findings.append({
                "severity": "medium",
                "issue": f"Sequential scan on '{table}' ({row_count_int:,} rows)",
                "fix": f"Consider index on '{table}' if table will grow",
            })

    for removed in rows_removed:
        removed_int = int(removed)
        if removed_int > 10_000:
            findings.append({
                "severity": "high",
                "issue": f"Filter removed {removed_int:,} rows after scan",
                "fix": (
                    "The index is not selective enough or is missing. "
                    "Create a composite or partial index matching the WHERE clause."
                ),
            })

    if has_disk_sort:
        findings.append({
            "severity": "medium",
            "issue": "Sort spilled to disk (external merge)",
            "fix": (
                "Increase work_mem for this query or add an index on "
                "the ORDER BY columns. Current work_mem may be too small."
            ),
        })

    if max_loops > 1000:
        findings.append({
            "severity": "high",
            "issue": f"Nested loop with {max_loops:,} iterations",
            "fix": (
                "Consider rewriting the query to use a hash join or "
                "adding indexes to reduce loop iterations."
            ),
        })

    cache_hit_pct = (
        round(100 * shared_hit / (shared_hit + shared_read), 1)
        if (shared_hit + shared_read) > 0
        else None
    )

    return {
        "execution_time_ms": execution_time_ms,
        "planning_time_ms": planning_time_ms,
        "scan_types": {
            "sequential": len(seq_scans),
            "index": len(index_scans),
            "bitmap": len(bitmap_scans),
        },
        "buffer_cache_hit_pct": cache_hit_pct,
        "buffers_read": shared_read,
        "buffers_hit": shared_hit,
        "disk_sort": has_disk_sort,
        "max_nested_loops": max_loops,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# 4. Table Bloat (dead tuples, vacuum status)
# ---------------------------------------------------------------------------


def check_table_bloat(
    db_url: str,
    table: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Check table bloat via dead tuples and vacuum status.

    Queries pg_stat_user_tables for dead tuple counts, last vacuum
    times, and autovacuum configuration. A healthy table should have
    dead tuple percentage well under 10%.

    Args:
        db_url: PostgreSQL connection string.
        table: Specific table to check, or None for all tables.
        limit: Max tables to return (sorted by dead_pct desc).

    Returns:
        Dict with table stats and overall assessment.

    Example::

        bloat = check_table_bloat("postgresql://user:pass@localhost/mydb")
        for t in bloat["tables"]:
            print(f"{t['table']}: {t['dead_pct']}% dead tuples")
    """
    conn = _connect(db_url)
    try:
        where_clause = ""
        params: dict[str, Any] = {"limit_val": limit}
        if table:
            where_clause = "WHERE relname = %(table_name)s"
            params["table_name"] = table

        rows = _execute(conn, f"""
            SELECT
                schemaname,
                relname AS table_name,
                n_live_tup AS live_rows,
                n_dead_tup AS dead_rows,
                round(
                    100.0 * n_dead_tup /
                    nullif(n_live_tup + n_dead_tup, 0),
                    2
                ) AS dead_pct,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                vacuum_count,
                autovacuum_count,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size
            FROM pg_stat_user_tables
            {where_clause}
            ORDER BY n_dead_tup DESC
            LIMIT %(limit_val)s
        """, params)

        tables: list[dict[str, Any]] = []
        issues: list[str] = []

        for row in rows:
            table_info: dict[str, Any] = {
                "schema": row.get("schemaname"),
                "table": row.get("table_name"),
                "live_rows": int(row.get("live_rows", 0)),
                "dead_rows": int(row.get("dead_rows", 0)),
                "dead_pct": float(row.get("dead_pct") or 0),
                "total_size": row.get("total_size"),
                "last_vacuum": str(row.get("last_vacuum") or "never"),
                "last_autovacuum": str(row.get("last_autovacuum") or "never"),
                "last_analyze": str(row.get("last_analyze") or "never"),
                "vacuum_count": int(row.get("vacuum_count", 0)),
                "autovacuum_count": int(row.get("autovacuum_count", 0)),
            }
            tables.append(table_info)

            dead_pct = table_info["dead_pct"]
            tname = table_info["table"]
            dead_rows = table_info["dead_rows"]

            if dead_pct > 50:
                issues.append(
                    f"CRITICAL: {tname} has {dead_pct}% dead tuples "
                    f"({dead_rows:,} dead rows). VACUUM immediately."
                )
            elif dead_pct > 20:
                issues.append(
                    f"WARNING: {tname} has {dead_pct}% dead tuples "
                    f"({dead_rows:,} dead rows). Check autovacuum config."
                )

            if (
                table_info["last_autovacuum"] == "never"
                and table_info["live_rows"] > 10_000
            ):
                issues.append(
                    f"WARNING: {tname} has {table_info['live_rows']:,} rows "
                    f"but has NEVER been autovacuumed."
                )

        assessment = "HEALTHY" if not issues else "; ".join(issues)

        return {
            "tables": tables,
            "assessment": assessment,
            "recommendation": (
                "Tables with >10% dead tuples: consider running VACUUM ANALYZE "
                "manually or tuning autovacuum_vacuum_scale_factor (default 0.2). "
                "For hot tables, set per-table: ALTER TABLE <t> SET "
                "(autovacuum_vacuum_scale_factor = 0.05, "
                "autovacuum_vacuum_threshold = 100);"
            ),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Index Suggestions (based on seq scan stats)
# ---------------------------------------------------------------------------


def suggest_indexes(
    db_url: str,
    table: str | None = None,
    min_seq_scan_pct: float = 50.0,
    min_size_rows: int = 1_000,
) -> list[dict[str, Any]]:
    """
    Suggest missing indexes based on sequential scan statistics.

    Analyzes pg_stat_user_tables for tables with high sequential scan
    ratios relative to index scans. A table with >50% sequential scans
    and >1K rows likely needs an index.

    Also checks pg_stat_user_indexes for unused indexes that waste disk
    space and slow down writes.

    Args:
        db_url: PostgreSQL connection string.
        table: Specific table, or None for all tables.
        min_seq_scan_pct: Minimum sequential scan percentage to flag.
        min_size_rows: Minimum table size (rows) to consider.

    Returns:
        List of dicts with table name, scan statistics, and index
        suggestions.

    Example::

        suggestions = suggest_indexes("postgresql://user:pass@localhost/mydb")
        for s in suggestions:
            print(f"{s['table']}: {s['seq_scan_pct']}% seq scans")
            print(f"  Suggestion: {s['suggestion']}")
    """
    conn = _connect(db_url)
    try:
        where_clause = ""
        params: dict[str, Any] = {}
        if table:
            where_clause = "AND relname = %(table_name)s"
            params["table_name"] = table

        # Tables with high sequential scan ratio
        missing_rows = _execute(conn, f"""
            SELECT
                schemaname,
                relname AS table_name,
                seq_scan,
                idx_scan,
                CASE
                    WHEN (seq_scan + coalesce(idx_scan, 0)) > 0
                    THEN round(
                        100.0 * seq_scan /
                        (seq_scan + coalesce(idx_scan, 0)),
                        1
                    )
                    ELSE 0
                END AS seq_scan_pct,
                seq_tup_read,
                idx_tup_fetch,
                n_live_tup AS row_count,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size
            FROM pg_stat_user_tables
            WHERE (seq_scan + coalesce(idx_scan, 0)) > 0
              AND n_live_tup >= %(min_rows)s
              {where_clause}
            ORDER BY seq_tup_read DESC
        """, {"min_rows": min_size_rows, **params})

        # Existing indexes (for cross-reference)
        existing_indexes = _execute(conn, """
            SELECT
                schemaname,
                relname AS table_name,
                indexrelname AS index_name,
                idx_scan AS index_scans,
                pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_stat_user_indexes
            ORDER BY relname, indexrelname
        """)

        # Build index map: table -> list of indexes
        index_map: dict[str, list[dict]] = {}
        for idx_row in existing_indexes:
            tname = idx_row.get("table_name", "")
            index_map.setdefault(tname, []).append(idx_row)

        # Unused indexes (0 scans)
        unused_indexes = _execute(conn, """
            SELECT
                schemaname,
                relname AS table_name,
                indexrelname AS index_name,
                idx_scan AS index_scans,
                pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_stat_user_indexes
            WHERE idx_scan = 0
              AND indexrelname NOT LIKE '%%_pkey'
              AND indexrelname NOT LIKE '%%_unique'
            ORDER BY pg_relation_size(indexrelid) DESC
            LIMIT 10
        """)

        suggestions: list[dict[str, Any]] = []

        for row in missing_rows:
            seq_pct = float(row.get("seq_scan_pct", 0))
            tname = row.get("table_name", "")
            row_count = int(row.get("row_count", 0))

            if seq_pct < min_seq_scan_pct:
                continue

            existing = index_map.get(tname, [])
            existing_names = [
                idx.get("index_name", "") for idx in existing
            ]

            severity = "high" if seq_pct > 90 else "medium"

            suggestion: dict[str, Any] = {
                "table": tname,
                "schema": row.get("schemaname"),
                "row_count": row_count,
                "total_size": row.get("total_size"),
                "seq_scans": int(row.get("seq_scan", 0)),
                "idx_scans": int(row.get("idx_scan", 0)),
                "seq_scan_pct": seq_pct,
                "seq_tuples_read": int(row.get("seq_tup_read", 0)),
                "existing_indexes": existing_names,
                "severity": severity,
                "suggestion": (
                    f"Table '{tname}' ({row_count:,} rows, {row.get('total_size')}) "
                    f"has {seq_pct}% sequential scans "
                    f"({int(row.get('seq_tup_read', 0)):,} tuples read). "
                    f"Run EXPLAIN ANALYZE on frequent queries against this table "
                    f"to identify which columns need indexes."
                ),
            }
            suggestions.append(suggestion)

        # Add unused index warnings
        if unused_indexes:
            for idx in unused_indexes:
                suggestions.append({
                    "table": idx.get("table_name"),
                    "severity": "low",
                    "type": "unused_index",
                    "index_name": idx.get("index_name"),
                    "index_size": idx.get("index_size"),
                    "suggestion": (
                        f"Index '{idx.get('index_name')}' on table "
                        f"'{idx.get('table_name')}' has never been used "
                        f"(0 scans) and consumes {idx.get('index_size')}. "
                        f"Consider dropping it to save disk space and speed "
                        f"up writes. Verify it is not needed for unique "
                        f"constraints or foreign keys before dropping."
                    ),
                })

        return suggestions
    finally:
        conn.close()
