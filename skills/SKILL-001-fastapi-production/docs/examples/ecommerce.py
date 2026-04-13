"""Reference: E-commerce API built entirely via SKILL-001.

Generates a production-ready e-commerce API with:
- Product catalog (search, pagination, soft delete)
- Order management (bulk operations, audit log)
- Auth (OAuth2 + MFA + API keys + RBAC)
- Payments (webhook receiver for Stripe)
- Real-time (SSE for order status updates)
- Caching (Redis cache layer)
- Doctor audit at the end

Run:
    PYTHONPATH=. python3 docs/examples/ecommerce.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

# Make the skill importable from its own root when called as a script.
_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT))

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import add_soft_delete
from adapt.extend.crud_data.add_search import add_search
from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination
from adapt.extend.crud_data.add_audit_log import add_audit_log
from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
from adapt.extend.auth_access.add_mfa import add_mfa
from adapt.extend.auth_access.add_rbac import add_rbac
from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth
from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
from adapt.extend.realtime.add_sse import add_sse
from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
from adapt.extend.infrastructure.add_cache_layer import add_cache_layer
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
    print("SKILL-001 Reference: E-commerce API")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="skill001_ecommerce_") as tmp:
        project_dir = Path(tmp)
        inp = ToolInput(project_dir=str(project_dir))

        # ------------------------------------------------------------------
        # Step 1: Generate base project
        # ------------------------------------------------------------------
        print("\n[1/15] Generating base project...")
        result = generate_project(
            output_dir=str(project_dir),
            name="ecommerce",
            prefix="/api/v1",
            models={
                "Product": {
                    "name": "str",
                    "description": "str",
                    "price": "Decimal",
                    "stock": "int",
                    "sku": "str",
                    "category": "str",
                },
                "Order": {
                    "user_id": "uuid",
                    "status": "str",
                    "total": "Decimal",
                    "shipping_address": "str",
                },
                "Payment": {
                    "order_id": "uuid",
                    "amount": "Decimal",
                    "provider": "str",
                    "status": "str",
                    "provider_ref": "str",
                },
            },
            owner_models={"Order": "user"},
            with_auth=True,
            with_redis=True,
            with_docker_compose=True,
            with_ci=True,
        )
        print(f"    Generated {result['total_files']} files across {len(result['phases'])} phases")

        # ------------------------------------------------------------------
        # Step 2: Apply adapt tools in dependency order
        # ------------------------------------------------------------------
        steps = [
            ("[2/15]  add_soft_delete",       add_soft_delete,       {}),
            ("[3/15]  add_search",             add_search,            {}),
            ("[4/15]  add_cursor_pagination",  add_cursor_pagination, {}),
            ("[5/15]  add_audit_log",          add_audit_log,         {}),
            ("[6/15]  add_bulk_operations",    add_bulk_operations,   {}),
            ("[7/15]  add_oauth2_provider",    add_oauth2_provider,   {}),
            ("[8/15]  add_mfa",                add_mfa,               {}),
            ("[9/15]  add_rbac",               add_rbac,              {}),
            ("[10/15] add_api_key_auth",       add_api_key_auth,      {}),
            ("[11/15] add_sse",                add_sse,               {"heartbeat_seconds": 20}),
            (
                "[12/15] add_webhook_receiver (Stripe)",
                add_webhook_receiver,
                {"providers": ["stripe"]},
            ),
            ("[13/15] add_cache_layer",        add_cache_layer,       {}),
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
        # Step 3: fastapi_doctor — holistic audit
        # ------------------------------------------------------------------
        print("\n[14/15] Running fastapi_doctor...")
        dr = fastapi_doctor(inp)
        print(f"    [{('OK' if dr.status in ('success', 'no_op') else 'FAIL')}] "
              f"status={dr.status}  findings={len(dr.notes)}")
        for note in dr.notes[:5]:
            print(f"    NOTE: {note}")

        # ------------------------------------------------------------------
        # Step 4: Validate all .py files parse
        # ------------------------------------------------------------------
        print("\n[15/15] Validating Python syntax...")
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
        print("E-COMMERCE REFERENCE REPORT")
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
            print(f"  [{icon}] {t['tool']:<35} status={t['status']}  created={t['files_created']}")

        if not all_ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
