"""E2E Agent Simulation: uses the skill exactly as an LLM agent would.

Simulates a real user scenario:
  "Build me an e-commerce API with products, orders, and reviews.
   Products have categories. Orders belong to users. Reviews belong to users.
   Add Stripe integration, background job for order confirmation email,
   WebSocket for real-time order status. Make it production-ready."

Measures: time per tool, files created, benchmark score, endpoint tests.
Produces a professional report.

Usage:
    python benchmark/test_e2e_agent.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("ENVIRONMENT", "local")

SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT))


@dataclass
class ToolCall:
    name: str
    args: dict
    duration_ms: float
    files_created: int
    files_modified: int
    success: bool
    notes: str = ""


@dataclass
class AgentReport:
    scenario: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    total_files: int = 0
    benchmark_score: str = ""
    endpoint_results: list[dict] = field(default_factory=list)
    total_duration_ms: float = 0

    def print_report(self) -> None:
        print()
        print("╔" + "═" * 70 + "╗")
        print("║" + "  E2E AGENT SIMULATION REPORT".center(70) + "║")
        print("╠" + "═" * 70 + "╣")
        print("║" + f"  Scenario: {self.scenario}".ljust(70) + "║")
        print("║" + f"  Total duration: {self.total_duration_ms:.0f}ms".ljust(70) + "║")
        print("║" + f"  Total files: {self.total_files}".ljust(70) + "║")
        print("║" + f"  Benchmark: {self.benchmark_score}".ljust(70) + "║")
        print("╚" + "═" * 70 + "╝")
        print()

        # Tool calls
        print("  TOOL CALLS")
        print("  " + "─" * 68)
        for tc in self.tool_calls:
            status = "✅" if tc.success else "❌"
            print(f"  {status} {tc.name:<40s} {tc.duration_ms:>6.0f}ms  +{tc.files_created} files")
            if tc.notes:
                print(f"     {tc.notes}")
        print("  " + "─" * 68)
        total_tool_time = sum(tc.duration_ms for tc in self.tool_calls)
        print(f"  Total tool time: {total_tool_time:.0f}ms across {len(self.tool_calls)} calls")

        # Endpoints
        if self.endpoint_results:
            print()
            print("  ENDPOINT VERIFICATION")
            print("  " + "─" * 68)
            for ep in self.endpoint_results:
                status = "✅" if ep["pass"] else "❌"
                print(f"  {status} {ep['method']:6s} {ep['path']:<35s} → {ep['status']}")
            passed = sum(1 for ep in self.endpoint_results if ep["pass"])
            print(f"  {passed}/{len(self.endpoint_results)} endpoints pass")

        print()


def call_tool(tool_name: str, fn, **kwargs) -> ToolCall:
    """Call a tool function and measure it."""
    start = time.perf_counter()
    try:
        result = fn(**kwargs)
        duration = (time.perf_counter() - start) * 1000
        files_created = len(result.get("files_created", []))
        files_modified = len(result.get("files_modified", []))
        notes = "; ".join(result.get("notes", [])[:2])
        return ToolCall(tool_name, kwargs, duration, files_created, files_modified, True, notes)
    except Exception as e:
        duration = (time.perf_counter() - start) * 1000
        return ToolCall(tool_name, kwargs, duration, 0, 0, False, f"ERROR: {e}")


def run_simulation() -> AgentReport:
    """Run the full E2E agent simulation."""
    report = AgentReport(
        scenario="E-commerce API: products, orders, reviews + Stripe + WebSocket + background jobs"
    )
    start_total = time.perf_counter()

    project_dir = tempfile.mkdtemp(prefix="skill-e2e-")

    # ================================================================
    # STEP 1: Agent calls generate_project (the main orchestrator)
    # ================================================================
    from generators.orchestrator import generate_project

    tc = call_tool("fastapi_generate_project", generate_project,
        output_dir=project_dir,
        name="ecommerce",
        prefix="/api/v1",
        models={
            "Product": {"name": "str", "price": "Decimal", "stock": "int", "description": "text"},
            "Order": {"status": "str", "total": "Decimal"},
        },
        owner_models={"Order": "user"},
        with_auth=True,
        with_docker_compose=True,
        with_ci=True,
        cors_origins=["https://shop.example.com"],
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 2: Agent adds Review model (not in initial spec)
    # ================================================================
    from generators.tools.add_model import add_model

    tc = call_tool("fastapi_add_model", add_model,
        project_dir=project_dir,
        name="Review",
        fields={"rating": "int", "comment": "text", "product_id": "uuid"},
        owner_field="user",
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 3: Agent adds Category model
    # ================================================================
    tc = call_tool("fastapi_add_model (Category)", add_model,
        project_dir=project_dir,
        name="Category",
        fields={"name": "str", "slug": "str", "description": "text"},
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 4: Agent adds custom business endpoints
    # ================================================================
    from generators.tools.add_endpoint import add_endpoint

    tc = call_tool("fastapi_add_endpoint (checkout)", add_endpoint,
        project_dir=project_dir,
        route_file="api/routes/order.py",
        method="post",
        path="/{id}/checkout",
        name="checkout_order",
        auth="required",
        request_body={"payment_method": "str", "shipping_address": "str"},
        description="Process order checkout with payment",
    )
    report.tool_calls.append(tc)

    tc = call_tool("fastapi_add_endpoint (search)", add_endpoint,
        project_dir=project_dir,
        route_file="api/routes/product.py",
        method="get",
        path="/search",
        name="search_products",
        auth="none",
        request_body=None,
        description="Search products by query string",
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 5: Agent adds Stripe integration
    # ================================================================
    from generators.tools.add_integration import add_integration

    tc = call_tool("fastapi_add_integration (stripe)", add_integration,
        project_dir=project_dir,
        service="stripe",
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 6: Agent adds background job for order confirmation
    # ================================================================
    from generators.tools.add_background_job import add_background_job

    tc = call_tool("fastapi_add_background_job", add_background_job,
        project_dir=project_dir,
        name="send_order_confirmation",
        retry_max=3,
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 7: Agent adds WebSocket for order status
    # ================================================================
    from generators.tools.add_websocket import add_websocket

    tc = call_tool("fastapi_add_websocket", add_websocket,
        project_dir=project_dir,
        name="order_status",
        path="/ws/orders",
        auth=True,
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 8: Agent adds Redis cache for product listings
    # ================================================================
    tc = call_tool("fastapi_add_integration (redis)", add_integration,
        project_dir=project_dir,
        service="redis",
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 9: Agent generates migration helper
    # ================================================================
    from generators.tools.migrate_db import generate_migration

    tc = call_tool("fastapi_migrate_db", generate_migration,
        project_dir=project_dir,
        message="add review, category, and order tables",
    )
    report.tool_calls.append(tc)

    # ================================================================
    # STEP 10: Agent runs the analyzer to verify quality
    # ================================================================
    from benchmark.analyzer import analyze

    start = time.perf_counter()
    result = analyze(project_dir)
    duration = (time.perf_counter() - start) * 1000
    report.benchmark_score = f"{result.passed}/{result.total} ({result.score:.0f}%)"
    report.tool_calls.append(ToolCall(
        "fastapi_analyze", {}, duration, 0, 0,
        result.passed == result.total,
        f"Score: {result.passed}/{result.total}",
    ))

    # ================================================================
    # STEP 11: Boot the app and hit endpoints (SQLite for speed)
    # ================================================================
    import importlib.util
    spec = importlib.util.spec_from_file_location("tf", str(SKILL_ROOT / "benchmark" / "test_functional.py"))
    tf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tf)
    tf.patch_for_sqlite(Path(project_dir))

    # New layout: project_dir already has an app/ subdirectory.
    # Just add project_dir to sys.path so `import app` resolves natively.
    project_path = Path(project_dir)
    if (project_path / "app").is_dir():
        sys.path.insert(0, str(project_path))
        test_root = None  # no symlink needed
    else:
        # Legacy fallback: symlink project_dir as 'app'
        test_root = Path(tempfile.mkdtemp())
        os.symlink(project_dir, str(test_root / "app"))
        sys.path.insert(0, str(test_root))

    import logging
    logging.disable(logging.CRITICAL)

    try:
        # Import and boot
        from app.models.base import Base
        from app.core.db import engine
        import asyncio

        async def setup():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        asyncio.run(setup())

        from app.main import app
        from app.core.security import get_password_hash
        from app.core.session import async_session
        from app.models.user import User
        import uuid as _uuid

        # Seed superuser
        async def seed():
            async with async_session() as session:
                admin = User(
                    id=_uuid.uuid4(), email="admin@shop.com",
                    hashed_password=get_password_hash("AdminPass1!"),
                    is_active=True, is_superuser=True, full_name="Admin",
                )
                session.add(admin)
                await session.commit()
        asyncio.run(seed())

        from httpx import AsyncClient, ASGITransport

        async def test_endpoints():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                API = "/api/v1"

                # Login
                r = await client.post(f"{API}/login/access-token",
                    data={"username": "admin@shop.com", "password": "AdminPass1!"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                token = r.json().get("access_token", "")
                headers = {"Authorization": f"Bearer {token}"}
                report.endpoint_results.append({"method": "POST", "path": "/login/access-token", "status": r.status_code, "pass": r.status_code == 200})

                # Health (mounted at ROOT, NOT under /api/v1)
                r = await client.get("/healthz")
                report.endpoint_results.append({"method": "GET", "path": "/healthz (root)", "status": r.status_code, "pass": r.status_code == 200})

                r = await client.get("/readyz")
                report.endpoint_results.append({"method": "GET", "path": "/readyz (root)", "status": r.status_code, "pass": r.status_code in (200, 503)})

                # Signup
                r = await client.post(f"{API}/users/signup", json={"email": "buyer@shop.com", "password": "BuyerPass1!", "full_name": "Buyer"})
                report.endpoint_results.append({"method": "POST", "path": "/users/signup", "status": r.status_code, "pass": r.status_code == 201})
                no_hash = "hashed_password" not in r.text
                report.endpoint_results.append({"method": "CHECK", "path": "no hashed_password in response", "status": "safe" if no_hash else "LEAKED", "pass": no_hash})

                # User login
                r2 = await client.post(f"{API}/login/access-token",
                    data={"username": "buyer@shop.com", "password": "BuyerPass1!"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                user_headers = {"Authorization": f"Bearer {r2.json().get('access_token', '')}"}

                # Product CRUD — note: strict schema needs Decimal as number, not string
                r = await client.post(f"{API}/products/", json={"name": "Widget", "price": 29.99, "stock": 100, "description": "A widget"}, headers=headers)
                if r.status_code not in (200, 201):
                    # Strict mode rejects float — need string representation parsed by Decimal
                    r = await client.post(f"{API}/products/", json={"name": "Widget", "price": "29.99", "stock": 100, "description": "A widget"}, headers=headers)
                report.endpoint_results.append({"method": "POST", "path": "/products/", "status": r.status_code, "pass": r.status_code in (200, 201)})
                pid = r.json().get("id", "")

                r = await client.get(f"{API}/products/", headers=headers)
                has_data = "data" in r.json() and "count" in r.json()
                report.endpoint_results.append({"method": "GET", "path": "/products/ (list)", "status": r.status_code, "pass": r.status_code == 200 and has_data})

                # Order CRUD
                r = await client.post(f"{API}/orders/", json={"status": "pending", "total": 29.99}, headers=user_headers)
                if r.status_code not in (200, 201):
                    r = await client.post(f"{API}/orders/", json={"status": "pending", "total": "29.99"}, headers=user_headers)
                report.endpoint_results.append({"method": "POST", "path": "/orders/", "status": r.status_code, "pass": r.status_code in (200, 201)})

                # Users management
                r = await client.get(f"{API}/users/me", headers=user_headers)
                report.endpoint_results.append({"method": "GET", "path": "/users/me", "status": r.status_code, "pass": r.status_code == 200})

                r = await client.get(f"{API}/users/", headers=user_headers)
                report.endpoint_results.append({"method": "GET", "path": "/users/ (regular→403)", "status": r.status_code, "pass": r.status_code == 403})

                r = await client.get(f"{API}/users/", headers=headers)
                report.endpoint_results.append({"method": "GET", "path": "/users/ (admin→200)", "status": r.status_code, "pass": r.status_code == 200})

                # Security
                r1 = await client.post(f"{API}/password-recovery/admin@shop.com")
                r2 = await client.post(f"{API}/password-recovery/nobody@nowhere.com")
                same = r1.json().get("message") == r2.json().get("message")
                report.endpoint_results.append({"method": "POST", "path": "/password-recovery (enumeration)", "status": "same msg" if same else "DIFFERENT", "pass": same})

                # Headers
                r = await client.get("/healthz")
                h_count = sum(1 for h in ["x-content-type-options", "x-frame-options", "strict-transport-security", "referrer-policy", "content-security-policy"] if h in {k.lower(): v for k, v in r.headers.items()})
                report.endpoint_results.append({"method": "CHECK", "path": f"security headers ({h_count}/5)", "status": h_count, "pass": h_count >= 4})

        asyncio.run(test_endpoints())

    except Exception as e:
        report.endpoint_results.append({"method": "ERROR", "path": "boot failed", "status": str(e)[:80], "pass": False})

    finally:
        # Cleanup sys.path and (legacy) symlink
        for p in [str(project_path), str(test_root) if test_root else ""]:
            if p and p in sys.path:
                sys.path.remove(p)
        shutil.rmtree(str(test_root), ignore_errors=True)

    # Count total files
    report.total_files = sum(1 for _ in Path(project_dir).rglob("*") if _.is_file())

    report.total_duration_ms = (time.perf_counter() - start_total) * 1000

    # Cleanup
    shutil.rmtree(project_dir)

    return report


if __name__ == "__main__":
    report = run_simulation()
    report.print_report()

    # Exit code
    all_tools_ok = all(tc.success for tc in report.tool_calls)
    all_endpoints_ok = all(ep["pass"] for ep in report.endpoint_results) if report.endpoint_results else False
    sys.exit(0 if all_tools_ok and all_endpoints_ok else 1)
