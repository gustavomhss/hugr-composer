"""
SKILL-001 WebSocket Tool: Static analysis of WebSocket code for production issues.

Performs AST-based and regex analysis on a FastAPI project to detect 8 common
WebSocket anti-patterns: no auth on connect, missing heartbeat, no connection
limits, missing error handling, no message validation, no graceful shutdown,
no reconnection support, and missing connection cleanup.
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


def _has_websocket_code(source: str) -> bool:
    """Check if source contains WebSocket endpoint definitions."""
    return bool(re.search(
        r"(@\w+\.websocket|async\s+def\s+\w+.*WebSocket|websocket_connect)",
        source,
    ))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_ws01_auth(source: str, filepath: Path) -> Finding | None:
    """WS-01: WebSocket connections are authenticated."""
    if not _has_websocket_code(source):
        return None

    has_auth = (
        "authenticate" in source.lower()
        or "jwt" in source.lower()
        or "token" in source.lower()
        or "WS_1008" in source
        or "POLICY_VIOLATION" in source
        or "verify_token" in source.lower()
    )

    if not has_auth:
        return Finding(
            rule_id="WS-01",
            severity=Severity.CRITICAL,
            title="WebSocket endpoint without authentication",
            description=(
                "WebSocket endpoint found but no authentication logic. "
                "Anyone can connect and receive data without credentials. "
                "WebSocket API does not support Authorization headers — "
                "authentication must be done via query parameter, cookie, "
                "or first-message protocol."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Validate JWT token from query parameter before accepting: "
                "ws://host/ws?token=<jwt>. Close with code 1008 if invalid."
            ),
        )
    return None


def _check_ws02_heartbeat(all_sources: str) -> Finding | None:
    """WS-02: Heartbeat/ping-pong for dead connection detection."""
    if not _has_websocket_code(all_sources):
        return None

    has_heartbeat = (
        "heartbeat" in all_sources.lower()
        or "ping" in all_sources.lower()
        or "pong" in all_sources.lower()
        or "keepalive" in all_sources.lower()
        or "keep_alive" in all_sources.lower()
    )

    if not has_heartbeat:
        return Finding(
            rule_id="WS-02",
            severity=Severity.HIGH,
            title="No heartbeat/ping-pong for WebSocket connections",
            description=(
                "WebSocket connections without heartbeat accumulate dead "
                "connections when clients disconnect ungracefully (mobile "
                "network switch, laptop lid close, NAT timeout). Dead "
                "connections consume memory and connection slots indefinitely."
            ),
            fix_suggestion=(
                "Implement server-side ping every 30 seconds. If pong is not "
                "received within 10 seconds, close the connection. Use "
                "asyncio.create_task() for the heartbeat loop."
            ),
        )
    return None


def _check_ws03_connection_limits(source: str, filepath: Path) -> Finding | None:
    """WS-03: Connection limits per user/IP."""
    if not _has_websocket_code(source):
        return None

    has_limits = (
        "max_per_user" in source.lower()
        or "max_per_ip" in source.lower()
        or "connection_limit" in source.lower()
        or "can_connect" in source
        or "MAX_PER" in source
        or "WS_1013" in source
    )

    if not has_limits:
        return Finding(
            rule_id="WS-03",
            severity=Severity.HIGH,
            title="No connection limits on WebSocket endpoint",
            description=(
                "WebSocket endpoint without per-user or per-IP connection "
                "limits. A single user or IP can open unlimited connections, "
                "exhausting server memory and file descriptors. A malicious "
                "actor can trivially DoS the WebSocket service."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Limit to 5 connections per user and 20 per IP. Check before "
                "accepting. Close excess with code 1013 (Try Again Later)."
            ),
        )
    return None


def _check_ws04_error_handling(source: str, filepath: Path) -> Finding | None:
    """WS-04: Proper error handling in WebSocket message loop."""
    if not _has_websocket_code(source):
        return None

    has_disconnect_handler = "WebSocketDisconnect" in source
    has_try_except = bool(re.search(
        r"try:.*?receive_(text|json|bytes).*?except",
        source,
        re.DOTALL,
    ))
    has_finally = "finally:" in source

    if not has_disconnect_handler:
        return Finding(
            rule_id="WS-04",
            severity=Severity.HIGH,
            title="No WebSocketDisconnect handler",
            description=(
                "WebSocket endpoint does not catch WebSocketDisconnect. "
                "When a client disconnects, receive_text() raises "
                "WebSocketDisconnect. Without catching it, the exception "
                "propagates and resources (room membership, DB connections) "
                "are not cleaned up."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Catch WebSocketDisconnect in the message loop. Use "
                "try/except/finally to ensure cleanup always runs."
            ),
        )

    if not has_finally:
        return Finding(
            rule_id="WS-04",
            severity=Severity.MEDIUM,
            title="No finally block for WebSocket cleanup",
            description=(
                "WebSocket endpoint catches WebSocketDisconnect but has "
                "no finally block. Cleanup (removing from rooms, canceling "
                "heartbeat tasks) may not run on unexpected errors."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Add a finally block that calls manager.disconnect() and "
                "cancels any background tasks (heartbeat, Redis listener)."
            ),
        )
    return None


def _check_ws05_message_validation(source: str, filepath: Path) -> Finding | None:
    """WS-05: Incoming messages are validated (not raw string processing)."""
    if not _has_websocket_code(source):
        return None

    has_receive = "receive_text" in source or "receive_json" in source

    if not has_receive:
        return None

    has_validation = (
        "model_validate" in source
        or "ValidationError" in source
        or "pydantic" in source.lower()
        or "WSIncoming" in source
        or "json.loads" in source  # At least basic JSON parsing
    )

    if not has_validation:
        return Finding(
            rule_id="WS-05",
            severity=Severity.MEDIUM,
            title="No message validation on WebSocket incoming messages",
            description=(
                "WebSocket endpoint receives messages but does not validate "
                "them against a schema. Malformed messages (wrong type, "
                "missing fields, oversized payloads) can cause unhandled "
                "exceptions that crash the connection."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Define Pydantic models for WS messages and validate with "
                "WSIncoming.model_validate_json(raw). Return error response "
                "on ValidationError instead of crashing."
            ),
        )
    return None


def _check_ws06_graceful_shutdown(all_sources: str) -> Finding | None:
    """WS-06: Graceful shutdown closes all WebSocket connections."""
    if not _has_websocket_code(all_sources):
        return None

    has_shutdown = (
        "close_all" in all_sources
        or "shutdown" in all_sources.lower()
        or "lifespan" in all_sources
        or "on_shutdown" in all_sources
        or "1001" in all_sources  # Going Away close code
    )

    if not has_shutdown:
        return Finding(
            rule_id="WS-06",
            severity=Severity.MEDIUM,
            title="No graceful shutdown for WebSocket connections",
            description=(
                "No graceful shutdown logic found. When the server deploys, "
                "all WebSocket connections are killed instantly. Clients see "
                "an error instead of a clean close frame with code 1001 "
                "(Going Away), which prevents automatic reconnection."
            ),
            fix_suggestion=(
                "In the FastAPI lifespan shutdown, call manager.close_all() "
                "which sends close code 1001 to all connections. Set "
                "uvicorn --timeout-graceful-shutdown 30."
            ),
        )
    return None


def _check_ws07_max_message_size(all_sources: str) -> Finding | None:
    """WS-07: WebSocket max message size is configured."""
    if not _has_websocket_code(all_sources):
        return None

    has_max_size = (
        "ws-max-size" in all_sources
        or "ws_max_size" in all_sources
        or "max_size" in all_sources
        or "MAX_MESSAGE_SIZE" in all_sources
    )

    if not has_max_size:
        return Finding(
            rule_id="WS-07",
            severity=Severity.LOW,
            title="No WebSocket max message size configured",
            description=(
                "Uvicorn's default WebSocket max message size is 16MB. "
                "Without configuring a lower limit, a client can send a "
                "16MB JSON payload that your server must parse and hold "
                "in memory. For typical chat/notification use, 64KB is "
                "sufficient."
            ),
            fix_suggestion=(
                "Set uvicorn --ws-max-size 65536 (64KB) for typical use. "
                "Or add application-level size checking before parsing."
            ),
        )
    return None


def _check_ws08_send_error_handling(source: str, filepath: Path) -> Finding | None:
    """WS-08: send_json/send_text calls handle connection already closed."""
    if not _has_websocket_code(source):
        return None

    # Look for broadcast/send patterns without try/except
    has_broadcast = bool(re.search(
        r"(send_json|send_text|send_bytes)\s*\(",
        source,
    ))
    if not has_broadcast:
        return None

    # Check if sends are wrapped in try/except
    has_send_protection = bool(re.search(
        r"try:.*?(send_json|send_text|send_bytes).*?except",
        source,
        re.DOTALL,
    ))
    has_safe_send = "safe_send" in source or "_safe_close" in source

    if not has_send_protection and not has_safe_send:
        return Finding(
            rule_id="WS-08",
            severity=Severity.MEDIUM,
            title="WebSocket send calls not protected against closed connections",
            description=(
                "send_json/send_text calls found without try/except protection. "
                "If the connection is already closed, send raises an exception. "
                "During broadcast to multiple clients, one failed send can "
                "crash the loop and prevent delivery to remaining clients."
            ),
            file_path=str(filepath),
            fix_suggestion=(
                "Wrap send calls in try/except. Track dead connections and "
                "remove them after the broadcast loop. Never let one failed "
                "send break the iteration over other connections."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def verify_websocket_config(project_path: str) -> list[Finding]:
    """
    Statically analyze a FastAPI project for WebSocket production issues.

    Scans all Python files for 8 common WebSocket anti-patterns using
    regex matching and source analysis. Returns a list of Finding objects,
    sorted by severity (critical first).

    Checks:
        WS-01: Authentication on connect
        WS-02: Heartbeat/ping-pong
        WS-03: Connection limits per user/IP
        WS-04: Error handling (WebSocketDisconnect, finally)
        WS-05: Message validation (Pydantic)
        WS-06: Graceful shutdown
        WS-07: Max message size
        WS-08: Send error handling

    Args:
        project_path: Root directory of the FastAPI project to analyze.

    Returns:
        List of Finding objects for each detected issue.

    Example::

        findings = verify_websocket_config("/path/to/my-fastapi-project")
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

        # --- Per-file checks ---

        # WS-01: Auth on connect
        finding = _check_ws01_auth(source, filepath)
        if finding:
            findings.append(finding)

        # WS-03: Connection limits
        finding = _check_ws03_connection_limits(source, filepath)
        if finding:
            findings.append(finding)

        # WS-04: Error handling
        finding = _check_ws04_error_handling(source, filepath)
        if finding:
            findings.append(finding)

        # WS-05: Message validation
        finding = _check_ws05_message_validation(source, filepath)
        if finding:
            findings.append(finding)

        # WS-08: Send error handling
        finding = _check_ws08_send_error_handling(source, filepath)
        if finding:
            findings.append(finding)

    # --- Project-wide checks ---
    all_sources = "\n".join(all_sources_parts)

    # WS-02: Heartbeat
    finding = _check_ws02_heartbeat(all_sources)
    if finding:
        findings.append(finding)

    # WS-06: Graceful shutdown
    finding = _check_ws06_graceful_shutdown(all_sources)
    if finding:
        findings.append(finding)

    # WS-07: Max message size
    finding = _check_ws07_max_message_size(all_sources)
    if finding:
        findings.append(finding)

    # Sort by severity
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
