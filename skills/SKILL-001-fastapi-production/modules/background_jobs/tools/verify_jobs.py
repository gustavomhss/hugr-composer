"""
SKILL-001 Background Jobs Tool: Static analysis of background task configuration.

Performs AST-based and regex analysis on a FastAPI project to detect 8 common
background job anti-patterns: missing retry config, no DLQ, missing idempotency,
no task timeout, blocking calls in async tasks, no health monitoring, missing
error handling, and unbounded task results.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "site-packages",
}

# Sync blocking calls that should never appear inside async task functions
_BLOCKING_CALLS: set[str] = {
    "time.sleep", "os.system", "subprocess.run", "subprocess.call",
    "subprocess.check_output", "requests.get", "requests.post",
    "requests.put", "requests.delete", "requests.patch",
    "open",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_python_files(root: Path) -> list[Path]:
    """Walk *root* and return .py files not in excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDE_DIRS]
        dp = Path(dirpath)
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(dp / fn)
    return files


def _resolve_call_name(node: ast.Call) -> str | None:
    """Resolve a dotted call name like ``time.sleep``."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return None


def _has_pattern(source: str, pattern: str) -> bool:
    """Case-insensitive check for a pattern in source."""
    return pattern.lower() in source.lower()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_jobs01_retry_config(source: str, filepath: Path) -> Finding | None:
    """JOBS-01: Tasks have retry configuration (max_tries or Retry)."""
    has_task_defs = bool(re.search(r"async\s+def\s+\w+\(ctx", source))
    if not has_task_defs:
        return None

    has_retry = (
        "max_tries" in source
        or "Retry" in source
        or "retry" in source.lower()
    )

    if not has_retry:
        return Finding(
            rule_id="JOBS-01",
            severity=Severity.HIGH,
            title="No retry configuration for background tasks",
            description=(
                "Task definitions found but no retry mechanism (max_tries in "
                "WorkerSettings, or arq.Retry exception). Tasks that fail will "
                "be silently dropped without retry."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add max_tries=3 to WorkerSettings, or raise arq.Retry(defer=delay) "
                "in task functions for custom retry logic with exponential backoff."
            ),
        )
    return None


def _check_jobs02_dlq(all_sources: str) -> Finding | None:
    """JOBS-02: Dead letter queue exists for permanently failed tasks."""
    has_tasks = bool(re.search(r"async\s+def\s+\w+\(ctx", all_sources))
    if not has_tasks:
        return None

    has_dlq = (
        "dlq" in all_sources.lower()
        or "dead_letter" in all_sources.lower()
        or "dead letter" in all_sources.lower()
    )

    if not has_dlq:
        return Finding(
            rule_id="JOBS-02",
            severity=Severity.MEDIUM,
            title="No dead letter queue for failed tasks",
            description=(
                "Background tasks found but no dead letter queue (DLQ). "
                "Tasks that exhaust all retries are silently dropped. "
                "Without a DLQ, permanently failed tasks are lost with no "
                "way to inspect, debug, or replay them."
            ),
            fix_suggestion=(
                "Implement a DLQ using Redis Streams (XADD). Capture task name, "
                "args, error, and attempt count. Add inspect and replay functions."
            ),
        )
    return None


def _check_jobs03_idempotency(source: str, filepath: Path) -> Finding | None:
    """JOBS-03: Tasks use idempotency keys for critical operations."""
    has_task_defs = bool(re.search(r"async\s+def\s+\w+\(ctx", source))
    if not has_task_defs:
        return None

    # Check for payment/order/charge related tasks without idempotency
    has_critical_task = bool(
        re.search(r"(payment|order|charge|invoice|refund|transfer)", source, re.IGNORECASE)
    )
    if not has_critical_task:
        return None

    has_idempotency = (
        "idempotency" in source.lower()
        or "idempotent" in source.lower()
        or "idem_key" in source
        or "already_processed" in source
    )

    if not has_idempotency:
        return Finding(
            rule_id="JOBS-03",
            severity=Severity.HIGH,
            title="Critical task without idempotency protection",
            description=(
                "A task handling payments, orders, or financial operations "
                "was found without idempotency key checking. If this task "
                "is retried (worker crash, network timeout), the operation "
                "may execute multiple times (e.g., double charge)."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add idempotency: check Redis SET NX before processing, "
                "mark as completed after success. Use deterministic keys "
                "derived from business data (e.g., order_id)."
            ),
        )
    return None


def _check_jobs04_timeout(source: str, filepath: Path) -> Finding | None:
    """JOBS-04: Worker has explicit job timeout configuration."""
    has_worker_settings = "WorkerSettings" in source or "worker_settings" in source.lower()
    if not has_worker_settings:
        return None

    has_timeout = (
        "job_timeout" in source
        or "timeout=" in source
        or "func(" in source  # arq.func() can set per-task timeout
    )

    if not has_timeout:
        return Finding(
            rule_id="JOBS-04",
            severity=Severity.MEDIUM,
            title="No explicit job timeout in worker settings",
            description=(
                "WorkerSettings found but no job_timeout configured. "
                "ARQ defaults to 300 seconds, but tasks that can hang "
                "(HTTP calls, DB queries) should have explicit timeouts. "
                "A hung task blocks a worker slot indefinitely."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add job_timeout=300 to WorkerSettings for default, and use "
                "arq.func(task_fn, timeout=60) for per-task overrides."
            ),
        )
    return None


def _check_jobs05_blocking_in_async(
    tree: ast.AST, source: str, filepath: Path,
) -> list[Finding]:
    """JOBS-05: No sync blocking calls inside async task functions."""
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        # Check if this looks like a task function (has 'ctx' parameter)
        args = node.args
        arg_names = [a.arg for a in args.args]
        if "ctx" not in arg_names:
            continue

        # Walk the function body for blocking calls
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            call_name = _resolve_call_name(child)
            if call_name and call_name in _BLOCKING_CALLS:
                findings.append(Finding(
                    rule_id="JOBS-05",
                    severity=Severity.HIGH,
                    title=f"Blocking call '{call_name}' in async task '{node.name}'",
                    description=(
                        f"Sync blocking call {call_name}() found inside async task "
                        f"function '{node.name}'. This blocks the event loop and "
                        f"prevents other tasks from running concurrently. "
                        f"With max_jobs=50, one blocking call can freeze the worker."
                    ),
                    file_path=str(filepath),
                    line_number=child.lineno,
                    fix_suggestion=(
                        f"Replace {call_name}() with its async equivalent. "
                        f"time.sleep -> await asyncio.sleep, "
                        f"requests.get -> httpx.AsyncClient().get, "
                        f"open -> aiofiles.open."
                    ),
                ))
    return findings


def _check_jobs06_health_monitoring(all_sources: str) -> Finding | None:
    """JOBS-06: Queue health monitoring endpoint exists."""
    has_tasks = bool(re.search(r"WorkerSettings|arq|create_pool", all_sources))
    if not has_tasks:
        return None

    has_health = (
        "queue_metrics" in all_sources.lower()
        or "queue_health" in all_sources.lower()
        or "/health/queue" in all_sources
        or "queue_depth" in all_sources
        or "zcard" in all_sources
    )

    if not has_health:
        return Finding(
            rule_id="JOBS-06",
            severity=Severity.LOW,
            title="No queue health monitoring",
            description=(
                "ARQ task queue found but no health monitoring endpoint. "
                "Without monitoring, you cannot detect queue backpressure "
                "(growing depth), stuck workers, or DLQ growth until "
                "users report issues."
            ),
            fix_suggestion=(
                "Add a /health/queue endpoint that reports queue_depth, "
                "in_progress count, DLQ depth, and a healthy boolean. "
                "Alert when queue_depth > 500 for 5+ minutes."
            ),
        )
    return None


def _check_jobs07_error_handling(source: str, filepath: Path) -> Finding | None:
    """JOBS-07: Task functions have proper error handling."""
    # Find async task functions (with ctx parameter)
    task_fns = re.findall(
        r"async\s+def\s+(\w+)\(ctx[^)]*\).*?(?=\nasync\s+def|\nclass\s|\Z)",
        source,
        re.DOTALL,
    )
    if not task_fns:
        return None

    has_try_except = bool(re.search(
        r"async\s+def\s+\w+\(ctx.*?try:.*?except",
        source,
        re.DOTALL,
    ))

    if not has_try_except:
        return Finding(
            rule_id="JOBS-07",
            severity=Severity.MEDIUM,
            title="Task functions without error handling",
            description=(
                "Task functions found without try/except blocks. Unhandled "
                "exceptions in ARQ tasks cause the task to fail and retry "
                "(if configured), but without proper error handling you cannot "
                "log the error context, clean up resources, or decide whether "
                "to retry or send to DLQ."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Wrap task logic in try/except. Log the error with context. "
                "For transient errors, raise arq.Retry(defer=backoff). "
                "For permanent errors, send to DLQ."
            ),
        )
    return None


def _check_jobs08_result_ttl(source: str, filepath: Path) -> Finding | None:
    """JOBS-08: Task result TTL is bounded (not keep_result_forever)."""
    has_worker_settings = "WorkerSettings" in source
    if not has_worker_settings:
        return None

    if "keep_result_forever" in source and "True" in source:
        return Finding(
            rule_id="JOBS-08",
            severity=Severity.MEDIUM,
            title="Task results stored forever (keep_result_forever=True)",
            description=(
                "keep_result_forever=True in WorkerSettings. Task results "
                "are stored in Redis indefinitely. For a system processing "
                "1000 tasks/hour, this can consume gigabytes of Redis memory. "
                "Large results (reports, data exports) are especially dangerous."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Set keep_result=3600 (1 hour) or an appropriate TTL. "
                "For large results, store output in S3/filesystem and "
                "keep only the URL in the Redis result."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_job_config(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI project for background job anti-patterns.

    Scans all Python files for 8 common background job issues using AST
    analysis and regex matching. Returns a list of Finding objects, one
    per detected issue, sorted by severity (critical first).

    Checks:
        JOBS-01: Retry configuration exists
        JOBS-02: Dead letter queue for failed tasks
        JOBS-03: Idempotency keys on critical tasks
        JOBS-04: Explicit job timeout configuration
        JOBS-05: No blocking calls in async tasks
        JOBS-06: Queue health monitoring
        JOBS-07: Error handling in task functions
        JOBS-08: Bounded task result TTL

    Args:
        project_path: Root directory of the FastAPI project to analyze.

    Returns:
        List of Finding objects for each detected issue.

    Example::

        findings = verify_job_config("/path/to/my-fastapi-project")
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {root}")

    py_files = _collect_python_files(root)
    findings: list[Finding] = []
    all_sources_parts: list[str] = []

    for filepath in py_files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        all_sources_parts.append(source)

        # Parse AST (best-effort)
        tree: ast.AST | None = None
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            pass

        # --- Per-file checks ---

        # JOBS-01: Retry configuration
        finding = _check_jobs01_retry_config(source, filepath)
        if finding:
            findings.append(finding)

        # JOBS-03: Idempotency keys
        finding = _check_jobs03_idempotency(source, filepath)
        if finding:
            findings.append(finding)

        # JOBS-04: Timeout configuration
        finding = _check_jobs04_timeout(source, filepath)
        if finding:
            findings.append(finding)

        # JOBS-05: Blocking calls in async tasks
        if tree is not None:
            findings.extend(_check_jobs05_blocking_in_async(tree, source, filepath))

        # JOBS-07: Error handling
        finding = _check_jobs07_error_handling(source, filepath)
        if finding:
            findings.append(finding)

        # JOBS-08: Result TTL
        finding = _check_jobs08_result_ttl(source, filepath)
        if finding:
            findings.append(finding)

    # --- Project-wide checks ---
    all_sources = "\n".join(all_sources_parts)

    # JOBS-02: Dead letter queue
    finding = _check_jobs02_dlq(all_sources)
    if finding:
        findings.append(finding)

    # JOBS-06: Health monitoring
    finding = _check_jobs06_health_monitoring(all_sources)
    if finding:
        findings.append(finding)

    # Sort by severity (critical first)
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
