"""Reference: Event-Driven System built entirely via SKILL-001.

Generates a production-ready event-driven API with:
- Event-driven architecture (Redis Streams broker, producer + consumer)
- Saga orchestration (distributed transaction coordination)
- Long-running tasks (async job queue with progress SSE)
- Webhook sender (outbound delivery with retry + HMAC signing)
- Webhook receiver (inbound with Stripe + GitHub + internal providers)
- Outbox pattern (transactional event publishing)
- Connection pool monitor (Prometheus metrics + Grafana dashboard)
- Error rate analyzer (ring-buffer aggregation + alert rules)

Run:
    PYTHONPATH=. python3 docs/examples/event_driven.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT))

from adapt.contracts import ToolInput
from adapt.evolve.add_event_driven import add_event_driven
from adapt.extend.infrastructure.add_saga import add_saga
from adapt.extend.api_design.add_long_running_task import add_long_running_task
from adapt.extend.realtime.add_webhook_sender import add_webhook_sender
from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
from adapt.operate.connection_pool_monitor import connection_pool_monitor
from adapt.operate.error_rate_analyzer import error_rate_analyzer
from adapt.proactive.fastapi_doctor import fastapi_doctor
from generators.orchestrator import generate_project


def _parse_all_py(project_dir: Path) -> tuple[int, list[str]]:
    """Parse every .py under project_dir; return (ok_count, errors)."""
    errors: list[str] = []
    ok = 0
    for path in sorted(project_dir.rglob("*.py")):
        try:
            ast.parse(path.read_text())
            ok += 1
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(project_dir)}: {exc}")
    return ok, errors


def main() -> None:
    print("=" * 60)
    print("SKILL-001 Reference: Event-Driven System")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="skill001_event_driven_") as tmp:
        project_dir = Path(tmp)
        inp = ToolInput(project_dir=str(project_dir))

        # ------------------------------------------------------------------
        # Step 1: Generate base project
        # ------------------------------------------------------------------
        print("\n[1/12] Generating base project...")
        result = generate_project(
            output_dir=str(project_dir),
            name="event-driven",
            prefix="/api/v1",
            models={
                "Shipment": {
                    "order_id": "uuid",
                    "carrier": "str",
                    "tracking_number": "str",
                    "status": "str",
                    "estimated_delivery": "datetime",
                },
                "Notification": {
                    "recipient_id": "uuid",
                    "channel": "str",
                    "payload": "str",
                    "sent_at": "datetime",
                    "status": "str",
                },
                "Job": {
                    "type": "str",
                    "status": "str",
                    "payload": "str",
                    "result": "str",
                    "progress": "int",
                },
            },
            with_auth=True,
            with_redis=True,
            with_docker_compose=True,
            with_ci=True,
        )
        print(f"    Generated {result['total_files']} files across {len(result['phases'])} phases")

        # ------------------------------------------------------------------
        # Step 2: Apply event-driven adapt tools
        # ------------------------------------------------------------------
        steps = [
            (
                "[2/12]  add_event_driven (redis_streams)",
                add_event_driven,
                {
                    "broker": "redis_streams",
                    "events": ["ShipmentCreated", "ShipmentUpdated", "NotificationRequested"],
                    "generate_consumer": True,
                    "generate_producer": True,
                },
            ),
            ("[3/12]  add_saga",                add_saga,                {}),
            ("[4/12]  add_long_running_task",   add_long_running_task,   {}),
            (
                "[5/12]  add_webhook_sender",
                add_webhook_sender,
                {"max_attempts": 7, "http_timeout_seconds": 10.0},
            ),
            (
                "[6/12]  add_webhook_receiver",
                add_webhook_receiver,
                {"providers": ["stripe", "github", "internal"]},
            ),
            ("[7/12]  add_outbox_pattern",      add_outbox_pattern,      {}),
            (
                "[8/12]  connection_pool_monitor",
                connection_pool_monitor,
                {"pool_size": 20, "max_overflow": 10, "alert_threshold_pct": 80.0},
            ),
            (
                "[9/12]  error_rate_analyzer",
                error_rate_analyzer,
                {
                    "lookback_hours": 24,
                    "group_by": ["route", "status_class"],
                    "threshold_5xx_pct": 1.0,
                    "sink": "prometheus",
                },
            ),
        ]

        all_ok = True
        tool_results: list[dict] = []
        for label, tool_fn, kwargs in steps:
            print(f"\n{label}...")
            r = tool_fn(inp, **kwargs)  # type: ignore[arg-type]
            status_icon = "OK" if r.status in ("success", "no_op") else "FAIL"
            print(f"    [{status_icon}] status={r.status}  "
                  f"created={len(r.files_created)}  modified={len(r.files_modified)}")
            if r.warnings:
                for w in r.warnings:
                    print(f"    WARN: {w}")
            if r.status == "error":
                print(f"    ERROR: {r.error}")
                all_ok = False
            tool_results.append({
                "tool": label.split("]")[1].strip(),
                "status": r.status,
                "files_created": len(r.files_created),
            })

        # ------------------------------------------------------------------
        # Step 3: fastapi_doctor
        # ------------------------------------------------------------------
        print("\n[10/12] Running fastapi_doctor...")
        dr = fastapi_doctor(inp)
        print(f"    [{('OK' if dr.status in ('success', 'no_op') else 'FAIL')}] "
              f"status={dr.status}  findings={len(dr.notes)}")
        for note in dr.notes[:5]:
            print(f"    NOTE: {note}")

        # ------------------------------------------------------------------
        # Step 4: Validate all .py files parse
        # ------------------------------------------------------------------
        print("\n[11/12] Validating Python syntax...")
        ok_count, parse_errors = _parse_all_py(project_dir)
        if parse_errors:
            all_ok = False
            print(f"    FAIL: {len(parse_errors)} parse error(s):")
            for e in parse_errors[:10]:
                print(f"      {e}")
        else:
            print(f"    OK: {ok_count} .py files parse cleanly")

        # ------------------------------------------------------------------
        # Final report
        # ------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("EVENT-DRIVEN REFERENCE REPORT")
        print("=" * 60)
        print(f"Base project files : {result['total_files']}")
        print(f"Adapt tools applied: {len(steps)}")
        print(f"Python files parsed: {ok_count}")
        print(f"Parse errors       : {len(parse_errors)}")
        print(f"Overall status     : {'PASS' if all_ok else 'FAIL'}")
        print()
        print("Tool summary:")
        for t in tool_results:
            icon = "+" if t["status"] in ("success", "no_op") else "x"
            print(f"  [{icon}] {t['tool']:<40} status={t['status']}  created={t['files_created']}")

        if not all_ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
