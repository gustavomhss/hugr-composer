"""Reference: SaaS B2B API built entirely via SKILL-001.

Generates a production-ready multi-tenant SaaS platform with:
- Multi-tenancy (tenant isolation at DB and middleware layers)
- Feature flags (per-tenant rollout + kill switches)
- RBAC (roles: owner, admin, member, viewer)
- OAuth2 provider (SSO integration)
- Data export (GDPR/CCPA CSV + JSON)
- API versioning (v1/v2 header + URL strategies)
- Circuit breaker (resilience for downstream services)
- Outbox pattern (at-least-once event delivery)
- SLA reporter (contract-grade SLO tracking)

Run:
    PYTHONPATH=. python3 docs/examples/saas_b2b.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_SKILL_ROOT))

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
from adapt.extend.auth_access.add_feature_flags import add_feature_flags
from adapt.extend.auth_access.add_rbac import add_rbac
from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
from adapt.extend.crud_data.add_data_export import add_data_export
from adapt.extend.api_design.add_api_versioning import add_api_versioning
from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker
from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
from adapt.operate.sla_reporter import sla_reporter
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
    print("SKILL-001 Reference: SaaS B2B Platform")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="skill001_saas_b2b_") as tmp:
        project_dir = Path(tmp)
        inp = ToolInput(project_dir=str(project_dir))

        # ------------------------------------------------------------------
        # Step 1: Generate base project
        # ------------------------------------------------------------------
        print("\n[1/13] Generating base project...")
        result = generate_project(
            output_dir=str(project_dir),
            name="saas-b2b",
            prefix="/api/v1",
            models={
                "Workspace": {
                    "name": "str",
                    "slug": "str",
                    "plan": "str",
                    "owner_id": "uuid",
                },
                "Membership": {
                    "workspace_id": "uuid",
                    "user_id": "uuid",
                    "role": "str",
                    "invited_by": "uuid",
                },
                "Integration": {
                    "workspace_id": "uuid",
                    "provider": "str",
                    "config": "str",
                    "enabled": "bool",
                },
                "AuditEvent": {
                    "workspace_id": "uuid",
                    "actor_id": "uuid",
                    "action": "str",
                    "resource_type": "str",
                    "resource_id": "uuid",
                },
            },
            owner_models={"Workspace": "user"},
            with_auth=True,
            with_redis=True,
            with_docker_compose=True,
            with_ci=True,
        )
        print(f"    Generated {result['total_files']} files across {len(result['phases'])} phases")

        # ------------------------------------------------------------------
        # Step 2: Apply SaaS-specific adapt tools
        # ------------------------------------------------------------------
        steps = [
            ("[2/13]  add_multi_tenancy",  add_multi_tenancy,  {}),
            ("[3/13]  add_feature_flags",  add_feature_flags,  {}),
            ("[4/13]  add_rbac",           add_rbac,           {}),
            ("[5/13]  add_oauth2_provider",add_oauth2_provider,{}),
            ("[6/13]  add_data_export",    add_data_export,    {}),
            ("[7/13]  add_api_versioning", add_api_versioning, {}),
            ("[8/13]  add_circuit_breaker",add_circuit_breaker,{}),
            ("[9/13]  add_outbox_pattern", add_outbox_pattern, {}),
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
        # Step 3: SLA reporter (operate tool — reads project, emits report)
        # ------------------------------------------------------------------
        print("\n[10/13] Running sla_reporter...")
        sr = sla_reporter(
            inp,
            report_period="month",
            availability_target_pct=99.9,
            output_format="markdown",
        )
        status_icon = "OK" if sr.status in ("success", "no_op") else "FAIL"
        print(f"    [{status_icon}] status={sr.status}  created={len(sr.files_created)}")
        if sr.status == "error":
            print(f"    ERROR: {sr.error}")
            # sla_reporter may be offline — treat as non-fatal warning
            print("    NOTE: SLA reporter requires live Prometheus; continuing.")

        # ------------------------------------------------------------------
        # Step 4: fastapi_doctor
        # ------------------------------------------------------------------
        print("\n[11/13] Running fastapi_doctor...")
        dr = fastapi_doctor(inp)
        print(f"    [{('OK' if dr.status in ('success', 'no_op') else 'FAIL')}] "
              f"status={dr.status}  findings={len(dr.notes)}")
        for note in dr.notes[:5]:
            print(f"    NOTE: {note}")

        # ------------------------------------------------------------------
        # Step 5: Validate all .py files parse
        # ------------------------------------------------------------------
        print("\n[12/13] Validating Python syntax...")
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
        print("SAAS B2B REFERENCE REPORT")
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
