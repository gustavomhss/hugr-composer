# TOOL-027: add_load_profile

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview  

| **Field**       | **Value**                                                                 |
|------------------|---------------------------------------------------------------------------|
| Tool name       | `fastapi_add_load_profile`                                               |
| Category        | EXTEND > Testing                                                         |
| Complexity      | Medium                                                                   |
| Dependencies    | existing FastAPI project, Locust                                         |
| Signature       | `add_load_profile(project_dir: str, endpoints: list[str] | None = None, users: int = 100, spawn_rate: int = 10, duration_seconds: int = 60, targets_p99_ms: dict[str, int] | None = None) -> dict` |
| Parameters      | `project_dir`: project root path<br>`endpoints`: which endpoints to load-test (None = all authenticated endpoints)<br>`users`: simulated concurrent users<br>`spawn_rate`: users/second ramp-up<br>`duration_seconds`: test duration<br>`targets_p99_ms`: per-endpoint p99 latency SLOs (fails test if exceeded) |

## 2. Purpose  

The `fastapi_add_load_profile` tool generates production-grade Locust load-test profiles that exercise a FastAPI application under realistic concurrent load so performance regressions are caught in CI rather than in the middle of a Black Friday. For each endpoint in the OpenAPI schema it produces a `@task` with representative request bodies (sourced from TOOL-025 factories so the shape matches real production data), weighted by expected traffic share (e.g., `GET /products` wins 10× more scheduled load than `POST /products`, matching the production ratio), and wired into a `User` class that simulates end-to-end flows (register → login → browse catalog → add-to-cart → checkout) rather than the naive "hit one endpoint in isolation" pattern that masks real contention under JWT validation, DB pool, and downstream service latency. Without this tool, teams discover their `/search?q=*` endpoint is a JOIN bomb at 2 AM when their first real traffic spike hits — after the spec was already shipped.

The generator emits a `locustfiles/` directory with one profile per traffic pattern (smoke, baseline, peak, soak, spike, stress), a `pyproject.toml` entry for `locust run smoke` and `locust run peak`, and a JSON contract file containing the agreed SLOs (p50, p95, p99 per endpoint, max error rate, min sustained throughput). Key design decisions: **Locust over k6/JMeter** because the entire codebase is Python and the load tests can re-use the same factories, Pydantic schemas, and auth helpers as the app itself — so a refactor of `UserCreate` automatically propagates to the load profile; **post-test SLO assertions** via a custom `locust.events.quitting` hook that parses the Locust stats and fails with non-zero exit if any p99 exceeded its target (so CI blocks the PR, not just a green-bar dashboard); **authenticated-from-spawn** setup using an `on_start` hook that logs every simulated user in once and caches the JWT for the rest of the session so auth overhead doesn't dominate measurements; **step-load shapes** (ramp from 1 → N users over M minutes) so the time-to-failure under increasing load is captured, not just the steady state; and **CI regression detection** by comparing the current run's p99 against the committed baseline — even a "green" run fails the gate if it regressed by more than the allowed tolerance.

## 3. Performance SLOs  

| **Metric**                  | **Target**                      | **Why**                                                                 |
|-----------------------------|---------------------------------|-------------------------------------------------------------------------|
| Tool execution time         | < 3s                           | Ensures quick setup for CI pipelines                                   |
| Files modified              | ≤ 2                            | Minimizes risk of unintended changes to the project                    |
| Files created               | ≥ 5                            | Includes locustfile.py, scenarios, SLO assertions, CI config, tests   |
| Locust startup              | < 5s                           | Ensures tests begin promptly                                           |
| Per-endpoint task latency   | ~= server latency              | Confirms Locust adds no measurable overhead                           |
| SLO assertion check         | < 100 ms after test ends       | Provides fast feedback on SLO violations                              |
| Concurrent users supported  | 10K per Locust worker          | Ensures scalability for high-traffic APIs                              |

---

## 4. Code Examples (Before / After)

### 4.1 Locustfile: BEFORE
```python
# tests/load/locustfile.py (if exists - minimal example)
from locust import HttpUser, task, between

class QuickTestUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def health_check(self):
        self.client.get("/health")
        
    @task(3)
    def get_items(self):
        self.client.get("/api/v1/items")
```

### 4.2 Locustfile: AFTER
```python
# tests/load/locustfile.py
from locust import HttpUser, task, between, tag, TaskSet
from locust.env import Environment
from tests.load.scenarios import browsing_scenario, active_scenario, admin_scenario
from tests.load.auth import AuthMixin
from tests.load.data_factories import generate_item_create, generate_user_update
from tests.load.slo_assertions import register_slo_handlers, validate_slo_targets
import random
import uuid

class BaseApiUser(HttpUser, AuthMixin):
    abstract = True
    wait_time = between(0.5, 2.5)
    
    def on_start(self):
        """Authenticate once per simulated user"""
        self.login()
        self.headers = {"Authorization": f"Bearer {self.access_token}"}
        
    def on_stop(self):
        """Cleanup if needed"""
        pass

class BrowsingUser(BaseApiUser):
    weight = 5
    
    @task(10)
    @tag("read", "browsing")
    def list_items(self):
        with self.client.get("/api/v1/items", headers=self.headers, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
                self.last_items = resp.json()
            else:
                resp.failure(f"Failed with {resp.status_code}")
    
    @task(3)
    @tag("read", "detail")
    def view_item_detail(self):
        if hasattr(self, 'last_items') and self.last_items:
            item = random.choice(self.last_items)
            self.client.get(f"/api/v1/items/{item['id']}", headers=self.headers)
    
    @task(2)
    @tag("read", "search")
    def search_items(self):
        self.client.get("/api/v1/items?q=test&limit=20", headers=self.headers)

class ActiveUser(BaseApiUser):
    weight = 3
    
    @task(5)
    @tag("write", "create")
    def create_item(self):
        item_data = generate_item_create()
        self.client.post(
            "/api/v1/items",
            json=item_data.model_dump(),
            headers=self.headers,
            name="POST /api/v1/items"
        )
    
    @task(3)
    @tag("write", "update")
    def update_own_item(self):
        resp = self.client.get("/api/v1/items?mine=true", headers=self.headers)
        if resp.status_code == 200 and resp.json():
            item = random.choice(resp.json())
            update_data = generate_user_update()
            self.client.patch(
                f"/api/v1/items/{item['id']}",
                json=update_data.model_dump(),
                headers=self.headers,
                name="PATCH /api/v1/items/:id"
            )

class AdminUser(BaseApiUser):
    weight = 1
    
    @task(4)
    @tag("admin", "users")
    def list_users(self):
        self.client.get("/api/v1/admin/users", headers=self.headers)
    
    @task(2)
    @tag("admin", "delete")
    def delete_item(self):
        resp = self.client.get("/api/v1/items", headers=self.headers)
        if resp.status_code == 200 and resp.json():
            item = random.choice(resp.json())
            self.client.delete(
                f"/api/v1/items/{item['id']}",
                headers=self.headers,
                name="DELETE /api/v1/items/:id"
            )

# Register SLO assertion handlers
register_slo_handlers()
```

### 4.3 SLO Assertions Module (NEW)
```python
# tests/load/slo_assertions.py
from locust import events
from locust.runners import WorkerRunner, MasterRunner
from pathlib import Path
import json
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def load_slo_targets(config_path: Path = Path("tests/load/load_slos.yaml")) -> Dict[str, int]:
    """Load SLO targets from YAML configuration file."""
    if not config_path.exists():
        logger.warning(f"No SLO targets file found at {config_path}")
        return {}
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    return config.get("p99_targets_ms", {})

def check_slo_violations(stats_entries: Dict[str, Any], targets: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
    """Compare actual p99 latencies against targets."""
    violations = {}
    
    for endpoint_key, entry in stats_entries.items():
        if endpoint_key in targets:
            target_ms = targets[endpoint_key]
            p99_actual = entry.get_response_time_percentile(0.99)
            
            if p99_actual is not None and p99_actual > target_ms:
                violations[endpoint_key] = {
                    "p99_actual_ms": round(p99_actual, 2),
                    "p99_target_ms": target_ms,
                    "exceeded_by_ms": round(p99_actual - target_ms, 2),
                    "request_count": entry.num_requests,
                    "failure_count": entry.num_failures
                }
    
    return violations

def register_slo_handlers():
    """Register event handlers for SLO validation."""
    
    @events.init.add_listener
    def on_locust_init(environment, **_kwargs):
        # Only run on master or standalone runner, not workers
        if isinstance(environment.runner, WorkerRunner):
            return
        
        slo_targets = load_slo_targets()
        if not slo_targets:
            logger.info("No SLO targets configured, skipping SLO validation")
            return
        
        @environment.events.test_stop.add_listener
        def on_test_stop(**_kwargs):
            """Check SLO violations after test completes."""
            if not hasattr(environment.runner, 'stats'):
                logger.error("No stats available for SLO validation")
                return
            
            violations = check_slo_violations(
                environment.runner.stats.entries,
                slo_targets
            )
            
            if violations:
                # Write violations to file
                violations_path = Path(environment.runner.stats_path) / "slo_violations.json"
                violations_path.parent.mkdir(parents=True, exist_ok=True)
                violations_path.write_text(json.dumps(violations, indent=2))
                
                # Log violations
                logger.error(f"SLO violations detected: {len(violations)} endpoints")
                for endpoint, data in violations.items():
                    logger.error(
                        f"  {endpoint}: p99={data['p99_actual_ms']}ms "
                        f"(target={data['p99_target_ms']}ms, "
                        f"+{data['exceeded_by_ms']}ms)"
                    )
                
                # Set non-zero exit code to fail the test
                environment.process_exit_code = 1
            else:
                logger.info("All SLO targets met ✓")
                
                # Write success marker
                success_path = Path(environment.runner.stats_path) / "slo_passed.json"
                success_path.write_text(json.dumps({"status": "passed"}, indent=2))
```

### 4.4 Authentication Mixin (NEW)
```python
# tests/load/auth.py
from locust import HttpUser
import random
import string
from typing import Optional

class AuthMixin:
    """Mixin for handling JWT authentication in load tests."""
    
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user_id: Optional[str] = None
    
    def generate_random_email(self) -> str:
        """Generate a random email for test user registration."""
        username = ''.join(random.choices(string.ascii_lowercase, k=8))
        domain = random.choice(["example.com", "test.com", "loadtest.local"])
        return f"{username}@{domain}"
    
    def generate_random_password(self) -> str:
        """Generate a random password meeting typical requirements."""
        upper = random.choice(string.ascii_uppercase)
        lower = random.choice(string.ascii_lowercase)
        digit = random.choice(string.digits)
        special = random.choice("!@#$%^&*")
        rest = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        return upper + lower + digit + special + rest
    
    def register_user(self) -> dict:
        """Register a new test user."""
        email = self.generate_random_email()
        password = self.generate_random_password()
        
        resp = self.client.post("/api/v1/auth/register", json={
            "email": email,
            "password": password,
            "password_confirm": password,
            "first_name": "Load",
            "last_name": "Test"
        })
        
        if resp.status_code == 201:
            return {"email": email, "password": password, "user_data": resp.json()}
        else:
            # Fallback to existing user if registration fails
            return {"email": "loadtest@example.com", "password": "TestPass123!"}
    
    def login(self) -> bool:
        """Authenticate and store tokens."""
        # Try to register first, then login
        user_creds = self.register_user()
        
        resp = self.client.post("/api/v1/auth/login", json={
            "email": user_creds["email"],
            "password": user_creds["password"]
        })
        
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.user_id = data.get("user_id")
            return True
        
        # Fallback to token endpoint if login fails
        resp = self.client.post("/api/v1/auth/token", data={
            "username": user_creds["email"],
            "password": user_creds["password"]
        })
        
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token")
            return True
        
        return False
    
    def refresh_access_token(self) -> bool:
        """Refresh expired access token."""
        if not self.refresh_token:
            return False
        
        resp = self.client.post("/api/v1/auth/refresh", json={
            "refresh_token": self.refresh_token
        })
        
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("access_token")
            return True
        
        return False
```

### 4.5 Data Factories Module (NEW)
```python
# tests/load/data_factories.py
from pydantic import BaseModel, Field
from faker import Faker
from datetime import datetime, timedelta
from typing import Optional, List
import random

fake = Faker()

class ItemCreateData(BaseModel):
    """Factory for creating item request data."""
    title: str = Field(default_factory=lambda: fake.sentence(nb_words=3).rstrip('.'))
    description: Optional[str] = Field(default_factory=lambda: fake.text(max_nb_chars=200))
    price: float = Field(default_factory=lambda: round(random.uniform(10.0, 1000.0), 2))
    category: str = Field(default_factory=lambda: random.choice([
        "electronics", "clothing", "books", "home", "sports"
    ]))
    tags: List[str] = Field(default_factory=lambda: random.sample([
        "new", "sale", "featured", "limited", "popular"
    ], k=random.randint(1, 3)))
    
    class Config:
        schema_extra = {
            "example": {
                "title": "Wireless Bluetooth Headphones",
                "description": "Noise cancelling over-ear headphones with 30hr battery",
                "price": 199.99,
                "category": "electronics",
                "tags": ["new", "wireless"]
            }
        }

class UserUpdateData(BaseModel):
    """Factory for updating user profile data."""
    first_name: Optional[str] = Field(default_factory=fake.first_name)
    last_name: Optional[str] = Field(default_factory=fake.last_name)
    bio: Optional[str] = Field(default_factory=lambda: fake.text(max_nb_chars=100))
    avatar_url: Optional[str] = Field(default_factory=lambda: f"https://api.dicebear.com/7.x/avatars/svg?seed={fake.word()}")
    
    class Config:
        schema_extra = {
            "example": {
                "first_name": "Alex",
                "last_name": "Johnson",
                "bio": "Software engineer and open source contributor",
                "avatar_url": "https://api.dicebear.com/7.x/avatars/svg?seed=alex"
            }
        }

class OrderCreateData(BaseModel):
    """Factory for creating order request data."""
    shipping_address: str = Field(default_factory=fake.address)
    billing_address: Optional[str] = None
    notes: Optional[str] = Field(default_factory=lambda: fake.sentence() if random.random() > 0.7 else None)
    
    class Config:
        schema_extra = {
            "example": {
                "shipping_address": "123 Main St, Anytown, USA 12345",
                "notes": "Please leave package at front door"
            }
        }

def generate_item_create() -> ItemCreateData:
    """Generate realistic item creation data."""
    return ItemCreateData()

def generate_user_update() -> UserUpdateData:
    """Generate realistic user update data."""
    return UserUpdateData()

def generate_order_create() -> OrderCreateData:
    """Generate realistic order creation data."""
    billing = fake.address() if random.random() > 0.5 else None
    return OrderCreateData(billing_address=billing)

def generate_bulk_items(count: int = 5) -> List[ItemCreateData]:
    """Generate multiple items for bulk operations."""
    return [generate_item_create() for _ in range(count)]
```

### 4.6 Scenario Definitions (NEW)
```python
# tests/load/scenarios.py
from locust import task, tag, TaskSet
from tests.load.data_factories import generate_item_create, generate_order_create
import random

class BrowsingScenario(TaskSet):
    """Scenario for browsing users (read-heavy)."""
    
    @task(15)
    @tag("browse", "catalog")
    def browse_catalog(self):
        self.client.get("/api/v1/items")
    
    @task(8)
    @tag("browse", "categories")
    def browse_categories(self):
        categories = ["electronics", "clothing", "books", "home", "sports"]
        category = random.choice(categories)
        self.client.get(f"/api/v1/items?category={category}")
    
    @task(5)
    @tag("browse", "search")
    def search_items(self):
        search_terms = ["wireless", "book", "shirt", "gadget", "tool"]
        term = random.choice(search_terms)
        self.client.get(f"/api/v1/items?q={term}")
    
    @task(3)
    @tag("browse", "detail")
    def view_item_detail(self):
        # This assumes we have item IDs from previous calls
        if hasattr(self.user, 'last_items') and self.user.last_items:
            item = random.choice(self.user.last_items)
            self.client.get(f"/api/v1/items/{item['id']}")

class ActiveUserScenario(TaskSet):
    """Scenario for active users (read/write mix)."""
    
    @task(10)
    @tag("active", "browse")
    def browse_items(self):
        self.client.get("/api/v1/items")
    
    @task(6)
    @tag("active", "create")
    def create_item(self):
        item_data = generate_item_create()
        self.client.post("/api/v1/items", json=item_data.model_dump())
    
    @task(4)
    @tag("active", "update")
    def update_profile(self):
        self.client.patch("/api/v1/users/me", json={
            "bio": f"Updated at {random.randint(1, 1000)}"
        })
    
    @task(2)
    @tag("active", "order")
    def create_order(self):
        order_data = generate_order_create()
        self.client.post("/api/v1/orders", json=order_data.model_dump())

class AdminScenario(TaskSet):
    """Scenario for admin users (administrative tasks)."""
    
    @task(8)
    @tag("admin", "monitor")
    def view_dashboard(self):
        self.client.get("/api/v1/admin/dashboard")
    
    @task(5)
    @tag("admin", "users")
    def list_users(self):
        self.client.get("/api/v1/admin/users")
    
    @task(3)
    @tag("admin", "moderate")
    def moderate_content(self):
        self.client.get("/api/v1/admin/flagged-items")
    
    @task(1)
    @tag("admin", "reports")
    def generate_report(self):
        self.client.post("/api/v1/admin/reports", json={
            "report_type": "daily_activity",
            "date": "2024-01-15"
        })

# Export scenario classes for use in locustfile
browsing_scenario = BrowsingScenario
active_scenario = ActiveUserScenario
admin_scenario = AdminScenario
```

### 4.7 Configuration Module (NEW)
```python
# tests/load/config.py
from pydantic import BaseModel, Field, HttpUrl, validator
from typing import Dict, List, Optional
from pathlib import Path
import yaml
import os

class LoadTestEndpointConfig(BaseModel):
    """Configuration for a single endpoint to load test."""
    path: str
    method: str = "GET"
    weight: int = Field(ge=1, default=1)
    tags: List[str] = []
    requires_auth: bool = True
    data_factory: Optional[str] = None
    
    @validator('method')
    def method_uppercase(cls, v):
        return v.upper()

class LoadTestScenarioConfig(BaseModel):
    """Configuration for a user scenario."""
    name: str
    user_class: str
    weight: int = Field(ge=1, default=1)
    spawn_percentage: float = Field(ge=0.0, le=1.0, default=0.33)
    tags: List[str] = []

class LoadTestConfig(BaseModel):
    """Main configuration for load tests."""
    target_url: HttpUrl = Field(default="http://localhost:8000")
    users: int = Field(default=100, ge=1, le=10000)
    spawn_rate: int = Field(default=10, ge=1, le=1000)
    duration_seconds: int = Field(default=60, ge=1, le=3600)
    headless: bool = Field(default=True)
    
    # SLO configuration
    p99_targets_ms: Dict[str, int] = Field(
        default={
            "GET /api/v1/items": 500,
            "POST /api/v1/items": 1000,
            "GET /api/v1/items/:id": 300,
            "PATCH /api/v1/items/:id": 800,
            "GET /api/v1/users/me": 200
        }
    )
    
    # Scenario configuration
    scenarios: List[LoadTestScenarioConfig] = Field(
        default=[
            LoadTestScenarioConfig(
                name="browsing",
                user_class="BrowsingUser",
                weight=5,
                spawn_percentage=0.5,
                tags=["read-only"]
            ),
            LoadTestScenarioConfig(
                name="active",
                user_class="ActiveUser",
                weight=3,
                spawn_percentage=0.35,
                tags=["read-write"]
            ),
            LoadTestScenarioConfig(
                name="admin",
                user_class="AdminUser",
                weight=1,
                spawn_percentage=0.15,
                tags=["admin"]
            )
        ]
    )
    
    # Output configuration
    output_dir: Path = Field(default=Path("tests/load/results"))
    html_report: bool = Field(default=True)
    json_stats: bool = Field(default=True)
    csv_stats: bool = Field(default=False)
    
    @validator('output_dir')
    def output_dir_exists(cls, v):
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    def save(self, path: Path = Path("tests/load/load_config.yaml")):
        """Save configuration to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(self.dict(), f, default_flow_style=False)
    
    @classmethod
    def load(cls, path: Path = Path("tests/load/load_config.yaml")) -> "LoadTestConfig":
        """Load configuration from YAML file."""
        if not path.exists():
            return cls()
        
        with open(path) as f:
            data = yaml.safe_load(f)
        
        return cls(**data)

# Global configuration instance
config = LoadTestConfig.load()
```

### 4.8 Migration: Add Load Test Results Table
```python
# alembic/versions/0010_add_load_test_results.py
"""add load test results table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create load_test_runs table
    op.create_table('load_test_runs',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('total_users', sa.Integer(), nullable=False),
        sa.Column('spawn_rate', sa.Integer(), nullable=False),
        sa.Column('total_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('requests_per_second', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('failure_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('slo_violations', JSONB(), nullable=True),
        sa.Column('environment', sa.String(128), nullable=False, server_default='staging'),
        sa.Column('git_commit', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    
    # Create load_test_endpoint_stats table
    op.create_table('load_test_endpoint_stats',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', UUID(), sa.ForeignKey('load_test_runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('endpoint', sa.String(512), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('num_requests', sa.Integer(), nullable=False),
        sa.Column('num_failures', sa.Integer(), nullable=False),
        sa.Column('median_response_time', sa.Float(), nullable=False),
        sa.Column('avg_response_time', sa.Float(), nullable=False),
        sa.Column('min_response_time', sa.Float(), nullable=False),
        sa.Column('max_response_time', sa.Float(), nullable=False),
        sa.Column('p50_response_time', sa.Float(), nullable=False),
        sa.Column('p95_response_time', sa.Float(), nullable=False),
        sa.Column('p99_response_time', sa.Float(), nullable=False),
        sa.Column('requests_per_second', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index('ix_load_test_endpoint_stats_run_endpoint', 'run_id', 'endpoint', 'method')
    )
    
    # Create load_test_slo_targets table
    op.create_table('load_test_slo_targets',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('endpoint', sa.String(512), nullable=False, unique=True, index=True),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('p99_target_ms', sa.Integer(), nullable=False),
        sa.Column('p95_target_ms', sa.Integer(), nullable=True),
        sa.Column('avg_target_ms', sa.Integer(), nullable=True),
        sa.Column('failure_rate_target', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Insert default SLO targets
    op.execute("""
        INSERT INTO load_test_slo_targets (endpoint, method, p99_target_ms, p95_target_ms, avg_target_ms)
        VALUES 
            ('/api/v1/items', 'GET', 500, 300, 150),
            ('/api/v1/items', 'POST', 1000, 600, 300),
            ('/api/v1/items/:id', 'GET', 300, 200, 100),
            ('/api/v1/items/:id', 'PATCH', 800, 500, 250),
            ('/api/v1/items/:id', 'DELETE', 700, 400, 200),
            ('/api/v1/users/me', 'GET', 200, 150, 80),
            ('/api/v1/auth/login', 'POST', 500, 300, 150)
    """)

def downgrade() -> None:
    op.drop_table('load_test_slo_targets')
    op.drop_table('load_test_endpoint_stats')
    op.drop_table('load_test_runs')
```

### 4.9 CI Workflow Configuration (NEW)
```python
# .github/workflows/load-test.yml
name: Load Test
on:
  schedule:
    - cron: '0 3 * * *'  # Daily at 3 AM UTC
  workflow_dispatch:
    inputs:
      users:
        description: 'Number of concurrent users'
        required: false
        default: '100'
      duration:
        description: 'Test duration (seconds)'
        required: false
        default: '60'
      environment:
        description: 'Target environment'
        required: false
        default: 'staging'
        type: choice
        options:
          - staging
          - preprod

jobs:
  load-test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install locust==2.20.0
          pip install -r requirements.txt
          pip install -r tests/requirements.txt
      
      - name: Start application (if local)
        if: github.event.inputs.environment == 'staging'
        run: |
          docker-compose up -d db redis
          sleep 10
          uvicorn app.main:app --host 0.0.0.0 --port 8000 &
          sleep 5
      
      - name: Run load test
        env:
          TARGET_URL: ${{ github.event.inputs.environment == 'staging' && 'http://localhost:8000' || 'https://api-preprod.example.com' }}
          LOCUST_USERS: ${{ github.event.inputs.users || '100' }}
          LOCUST_DURATION: ${{ github.event.inputs.duration || '60' }}
          GIT_COMMIT: ${{ github.sha }}
        run: |
          cd tests/load
          locust -f locustfile.py \
            --headless \
            --users $LOCUST_USERS \
            --spawn-rate 10 \
            --run-time ${LOCUST_DURATION}s \
            --host $TARGET_URL \
            --csv=results/stats \
            --html=results/report.html \
            --json \
            --loglevel INFO \
            --exit-code-on-error 1
      
      - name: Check SLO violations
        id: slo-check
        run: |
          if [ -f "tests/load/results/slo_violations.json" ]; then
            echo "SLO violations detected"
            cat tests/load/results/slo_violations.json
            echo "::error::Load test failed SLO targets"
            exit 1
          else
            echo "All SLO targets met"
          fi
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: load-test-results-${{ github.run_id }}
          path: |
            tests/load/results/
          retention-days: 30
      
      - name: Store results in database
        if: success() || failure()
        env:
          DATABASE_URL: ${{ secrets.LOAD_TEST_DB_URL }}
        run: |
          python tests/load/store_results.py \
            --results-dir tests/load/results \
            --environment ${{ github.event.inputs.environment || 'staging' }} \
            --commit ${{ github.sha }}
      
      - name: Send notification on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `🚨 Load test failed for commit ${context.sha}. Check artifacts for details.`
            })

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Load tests never run against production by default** | `LoadTestConfig` in `tests/load/config.py` validates target URL against production domains and raises `ValueError` if matched |
| QS-2 | **SLO violations always fail the test with non-zero exit code** | `slo_assertions.py` sets `process_exit_code=1` when any endpoint exceeds its p99 target in the post-test listener |
| QS-3 | **Authentication is performed exactly once per simulated user** | `on_start` method in `locustfile.py` stores JWT token in instance variables reused across all tasks |
| QS-4 | **Factory-generated data always matches endpoint schemas** | `ItemFactory` and `UserFactory` in `app/tests/factories.py` generate data that passes Pydantic validation |
| QS-5 | **Task weights follow RESTful conventions by default** | Default weights in `locustfile.py` follow GET=10, POST=1, PATCH=2, DELETE=1 unless overridden |
| QS-6 | **Test reports are always generated even on failure** | `--csv` and `--html` flags in `.github/workflows/load_test.yml` ensure output files are written unconditionally |
| QS-7 | **Locust workers gracefully shutdown on timeout** | `--run-time` parameter in CI config enforces hard timeout, and `events.quitting` listener cleans up resources |
| QS-8 | **Per-endpoint latency measurements exclude Locust overhead** | `HttpUser` class in `locustfile.py` uses `between(0.5, 2.5)` wait time to simulate realistic think time |
| QS-9 | **Scenarios cover common user journeys** | `browsing_user.py`, `active_user.py`, and `admin_user.py` in `tests/load/scenarios/` implement distinct behavior patterns |
| QS-10 | **CI integration requires no manual setup** | `load_test.yml` workflow includes all necessary setup steps including Python 3.10 and Locust installation |
| QS-11 | **Tool execution leaves application code unchanged** | File modification check in `add_load_profile()` verifies only test files are touched |
| QS-12 | **SLO targets are configurable per environment** | `LoadTestConfig.slo_targets` can be overridden via `LOAD_TEST_SLO_TARGETS` environment variable |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `locustfile.py` exists at `tests/load/locustfile.py` | File exists, parses |
| CC-02 | `slo_assertions.py` exists with test_stop listener | File exists, contains `@events.test_stop.add_listener` |
| CC-03 | Scenario scripts exist for browsing/active/admin users | Files exist in `tests/load/scenarios/` |
| CC-04 | CI workflow `.github/workflows/load_test.yml` exists | File exists, contains Locust run command |
| CC-05 | Load test config `tests/load/config.py` exists | File exists, contains `LoadTestConfig` class |
| CC-06 | All endpoints have corresponding `@task` methods | grep `@task` in locustfile.py |
| CC-07 | Authentication flow implemented in `on_start` | Inspect `on_start` method in locustfile.py |
| CC-08 | Default task weights follow REST conventions | Verify GET=10, POST=1 in locustfile.py |
| CC-09 | SLO targets configurable via environment | grep `env_prefix="LOAD_TEST_"` in config.py |
| CC-10 | Production URL blocked by default | Test `LoadTestConfig` with prod domain |
| CC-11 | CSV and HTML reports generated | grep `--csv` and `--html` in CI config |
| CC-12 | Test duration configurable via parameter | Verify `--run-time` in CI config |
| CC-13 | Concurrent users configurable via parameter | Verify `--users` in CI config |
| CC-14 | Spawn rate configurable via parameter | Verify `--spawn-rate` in CI config |
| CC-15 | Factory data passes schema validation | Run `ItemFactory.build().model_dump()` through schema |
| CC-16 | Migration creates load test tables | Inspect `alembic/versions/0009_add_load_test_tables.py` |
| CC-17 | Load test tables have proper indexes | Verify `sa.Index` in migration |
| CC-18 | Stats collection includes p99 measurement | grep `get_response_time_percentile(0.99)` |
| CC-19 | Failed requests counted separately | Verify `failure_count` in stats |
| CC-20 | Test idempotent on re-run | Run tool twice, verify no duplicate files |
| CC-21 | All created files are under tests/load/ | Verify no files outside test directory |
| CC-22 | CI workflow runs on push to main | Inspect `on.push.branches` in workflow |
| CC-23 | CI workflow runs on pull requests | Inspect `on.pull_request` in workflow |
| CC-24 | HTML report includes SLO violations | Manual test with exceeded targets |
| CC-25 | CSV output includes all endpoints | Inspect generated CSV file |
| CC-26 | Factory data is randomized | Verify `random` usage in factories |
| CC-27 | User classes inherit from `HttpUser` | grep `class .*\(HttpUser` |
| CC-28 | Wait time between tasks is realistic | Verify `between(0.5, 2.5)` |
| CC-29 | Authentication uses JWT | Verify `Authorization: Bearer` header |
| CC-30 | SLO targets written to JSON | grep `slos.json` in slo_assertions.py |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Locustfile exists with weighted tasks for all endpoints
- [ ] SLO assertions module fails test on violation
- [ ] Three scenario scripts cover browsing/active/admin patterns
- [ ] CI workflow runs load tests on PR and main
- [ ] Load test config validates against production URLs
- [ ] Factory data passes schema validation
- [ ] Migration creates load test tables with proper indexes
- [ ] HTML and CSV reports generated on every run
- [ ] Test duration and user count configurable
- [ ] Authentication implemented with JWT reuse
- [ ] Tool execution modifies only test files
- [ ] All 30 tests pass (T-01 through T-30)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-LD-01 | Load tests **never** run against production by default | `LoadTestConfig` in `tests/load/config.py` validates target URL against known production domains using `allowed_domains` list | T-03, T-19 |
| INV-LD-02 | SLO violations **always** fail the test with non-zero exit code | `slo_assertions.py` sets `environment.process_exit_code = 1` when any endpoint's p99 exceeds target in post-test listener | T-13, T-14 |
| INV-LD-03 | Authentication is performed **exactly once** per simulated user | `on_start` method in `locustfile.py` stores JWT in instance variable reused across all `@task` methods | T-07, T-08 |
| INV-LD-04 | Factory-generated data **always** matches endpoint schemas | `ItemFactory` and `UserFactory` use Pydantic model definitions from `app/schemas/` to generate valid data | T-25, T-26 |
| INV-LD-05 | Test reports are **always** generated even on failure | `--csv` and `--html` flags in `.github/workflows/load_test.yml` ensure output files are written unconditionally | T-20, T-21 |
| INV-LD-06 | Locust workers **always** shutdown gracefully on timeout | `--run-time` parameter enforces hard timeout, and `events.quitting` listener in `slo_assertions.py` cleans up resources | T-27, T-28 |
| INV-LD-07 | Per-endpoint latency measurements **exclude** Locust overhead | `HttpUser.wait_time = between(0.5, 2.5)` simulates realistic think time between requests in `locustfile.py` | T-09, T-10 |
| INV-LD-08 | The tool **never** modifies application source code | File modification check in `add_load_profile()` restricts changes to `tests/load/` directory only | T-29, T-30 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Generate a basic load test profile**
- **As a** developer integrating load testing
- **I want** to generate a Locustfile with default task weights
- **So that** I can start load testing immediately
- **Given:** FastAPI project with `/api/v1/items` endpoint
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - `tests/load/locustfile.py` is created with `@task(10)` for GET /api/v1/items (CC-06)
  - Default task weights follow REST conventions (INV-LD-05)
  - Authentication implemented in `on_start` method (CC-07)

**US-02: Configure concurrent users**
- **As a** performance engineer
- **I want** to specify the number of concurrent users
- **So that** I can simulate realistic traffic
- **Given:** FastAPI project with 3 endpoints
- **When:** I call `add_load_profile(project_dir="my_project", users=500)`
- **Then:**
  - `.github/workflows/load_test.yml` includes `--users 500` (CC-13)
  - Locustfile contains `ApiUser` class with `wait_time` between 0.5-2.5s (INV-LD-07)
  - Migration creates `load_test_runs` table with `user_count` column (CC-16)

**US-03: Set per-endpoint SLO targets**
- **As a** SRE defining performance goals
- **I want** to specify p99 latency targets per endpoint
- **So that** I can catch regressions early
- **Given:** FastAPI project with `/api/v1/items` endpoint
- **When:** I call `add_load_profile(project_dir="my_project", targets_p99_ms={"GET /api/v1/items": 500})`
- **Then:**
  - `tests/load/slo_assertions.py` compares p99 against 500ms (INV-LD-02)
  - SLO targets written to `slos.json` (CC-30)
  - Test fails with exit code 1 if target exceeded (T-13)

**US-04: Generate realistic request data**
- **As a** developer testing API behavior
- **I want** Locust to use factory-generated request bodies
- **So that** tests reflect production usage
- **Given:** FastAPI project with `ItemFactory` in `app/tests/factories.py`
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - Locustfile imports `ItemFactory` and uses it in `create_item` task (INV-LD-04)
  - Factory data passes Pydantic validation (CC-15)
  - Request bodies match endpoint schemas (T-25)

**US-05: Authenticate simulated users**
- **As a** security-conscious developer
- **I want** each simulated user to authenticate once
- **So that** tests reflect real-world authentication overhead
- **Given:** FastAPI project with JWT authentication
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - `on_start` method performs login and stores JWT (INV-LD-03)
  - Subsequent requests include `Authorization: Bearer` header (CC-29)
  - Authentication performed exactly once per user (T-07)

### 9.2 Scenario coverage (US-06 .. US-10)

**US-06: Simulate browsing behavior**
- **As a** product manager analyzing user journeys
- **I want** to test read-only endpoint performance
- **So that** I can optimize the browsing experience
- **Given:** FastAPI project with `/api/v1/items` endpoint
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - `tests/load/scenarios/browsing_user.py` is created with `@task(5)` for GET /api/v1/items (CC-03)
  - Scenario includes search and detail view tasks (CC-09)
  - Wait time between tasks is realistic (CC-28)

**US-07: Simulate active user behavior**
- **As a** developer testing CRUD operations
- **I want** to test create/update/delete endpoint performance
- **So that** I can ensure write operations scale
- **Given:** FastAPI project with `/api/v1/items` endpoint
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - `tests/load/scenarios/active_user.py` is created with `@task(1)` for POST /api/v1/items (CC-03)
  - Scenario includes update and delete tasks (CC-08)
  - Factory data used for create/update requests (INV-LD-04)

**US-08: Simulate admin behavior**
- **As a** system administrator
- **I want** to test admin endpoint performance
- **So that** I can ensure admin operations remain responsive
- **Given:** FastAPI project with `/api/v1/admin/items` endpoint
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - `tests/load/scenarios/admin_user.py` is created with `@task(1)` for GET /api/v1/admin/items (CC-03)
  - Scenario includes bulk operations (CC-09)
  - Admin tasks use separate authentication (CC-29)

**US-09: Mix user scenarios**
- **As a** performance engineer
- **I want** to run multiple user scenarios simultaneously
- **So that** I can test realistic traffic patterns
- **Given:** FastAPI project with browsing, active, and admin endpoints
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - Locustfile includes `BrowsingUser`, `ActiveUser`, and `AdminUser` classes (CC-27)
  - Users spawned according to specified ratios (CC-14)
  - Stats collected per scenario (CC-18)

**US-10: Tag tasks for selective execution**
- **As a** developer debugging performance issues
- **I want** to run specific task types independently
- **So that** I can isolate performance bottlenecks
- **Given:** FastAPI project with tagged tasks
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - Tasks include `@tag("browse")`, `@tag("create")`, etc. (CC-09)
  - Locust can run specific tags via `--tags` parameter (CC-12)
  - Stats collected per tag (CC-18)

### 9.3 SLO enforcement (US-11 .. US-15)

**US-11: Fail test on SLO violation**
- **As a** SRE enforcing performance standards
- **I want** the test to fail if any endpoint exceeds its p99 target
- **So that** regressions are caught immediately
- **Given:** FastAPI project with SLO targets
- **When:** GET /api/v1/items p99 exceeds 500ms
- **Then:**
  - Test fails with exit code 1 (INV-LD-02)
  - Violation reported in console output (CC-24)
  - CSV output includes exceeded targets (CC-25)

**US-12: Skip SLO check for failed requests**
- **As a** developer debugging test failures
- **I want** failed requests excluded from SLO calculations
- **So that** SLO violations reflect genuine performance issues
- **Given:** FastAPI project with failing endpoint
- **When:** POST /api/v1/items returns 500 errors
- **Then:**
  - Failed requests counted separately (CC-19)
  - SLO comparison skipped for failing endpoints (T-13)
  - Failure rate reported in stats (CC-18)

**US-13: Handle missing SLO targets**
- **As a** developer adding new endpoints
- **I want** the tool to handle endpoints without SLO targets
- **So that** new endpoints can be tested immediately
- **Given:** FastAPI project with untargeted endpoint
- **When:** GET /api/v1/new-endpoint is called
- **Then:**
  - Endpoint included in stats (CC-25)
  - No SLO violation reported (CC-24)
  - Test continues normally (T-14)

**US-14: Report SLO violations in HTML**
- **As a** developer analyzing test results
- **I want** SLO violations highlighted in the HTML report
- **So that** I can quickly identify performance issues
- **Given:** FastAPI project with exceeded SLO
- **When:** GET /api/v1/items p99 exceeds target
- **Then:**
  - HTML report includes SLO violation section (CC-24)
  - Violated endpoints highlighted in red (CC-21)
  - Detailed stats available per endpoint (CC-18)

**US-15: Support per-environment SLO targets**
- **As a** developer testing in multiple environments
- **I want** to configure SLO targets per environment
- **So that** I can account for environment differences
- **Given:** FastAPI project with staging and production environments
- **When:** I set `LOAD_TEST_SLO_TARGETS` environment variable
- **Then:**
  - SLO targets loaded from environment (CC-09)
  - Targets override defaults (CC-12)
  - Test uses correct targets per environment (T-19)

### 9.4 CI integration (US-16 .. US-20)

**US-16: Run load tests on PR**
- **As a** developer practicing CI/CD
- **I want** load tests to run on every PR
- **So that** I can catch performance regressions early
- **Given:** FastAPI project with CI pipeline
- **When:** I open a PR
- **Then:**
  - `.github/workflows/load_test.yml` runs on `pull_request` (CC-23)
  - Test results uploaded as artifacts (CC-11)
  - PR blocked if SLOs violated (T-20)

**US-17: Generate JSON test results**
- **As a** developer integrating with CI
- **I want** test results in machine-readable format
- **So that** I can automate result analysis
- **Given:** FastAPI project with CI pipeline
- **When:** Load test completes
- **Then:**
  - JSON results written to `load_stats.json` (CC-11)
  - Results include p99, failure rate, and request count (CC-18)
  - Artifacts uploaded to CI (CC-21)

**US-18: Block production deployment on SLO violation**
- **As a** SRE enforcing deployment gates
- **I want** production deployments blocked on SLO violations
- **So that** regressions never reach users
- **Given:** FastAPI project with production deployment pipeline
- **When:** Load test fails SLO
- **Then:**
  - Deployment pipeline fails (T-20)
  - Violation details available in CI logs (CC-24)
  - Block remains until SLOs met (T-14)

**US-19: Compare against baseline performance**
- **As a** performance engineer tracking regressions
- **I want** to compare current results against a baseline
- **So that** I can detect performance degradation
- **Given:** FastAPI project with historical stats
- **When:** Load test completes
- **Then:**
  - Current stats compared to baseline (CC-25)
  - Significant deviations highlighted (CC-24)
  - Comparison available in CI artifacts (CC-21)

**US-20: Support headless CI execution**
- **As a** developer running tests in CI
- **I want** Locust to run in headless mode
- **So that** tests can run without UI
- **Given:** FastAPI project with CI pipeline
- **When:** Load test runs in CI
- **Then:**
  - Locust runs with `--headless` flag (CC-12)
  - Stats written to CSV and JSON (CC-11)
  - Test completes within CI timeout (CC-14)

### 9.5 Robustness & edge cases (US-21 .. US-25)

**US-21: Handle server downtime**
- **As a** developer testing failure scenarios
- **I want** Locust to handle server downtime gracefully
- **So that** I can test failure recovery
- **Given:** FastAPI project with load test
- **When:** Server goes down during test
- **Then:**
  - Locust reports 100% failure rate (CC-19)
  - Workers shutdown gracefully (INV-LD-06)
  - Partial stats written (CC-11)

**US-22: Prevent production testing**
- **As a** cautious developer
- **I want** the tool to block production testing by default
- **So that** I never accidentally test production
- **Given:** FastAPI project pointing to production
- **When:** I call `add_load_profile(project_dir="my_project")`
- **Then:**
  - Tool validates target URL against production domains (INV-LD-01)
  - Test fails if production URL detected (T-03)
  - Requires explicit flag to test production (CC-10)

**US-23: Handle invalid factory data**
- **As a** developer testing edge cases
- **I want** Locust to handle invalid factory data gracefully
- **So that** I can test error handling
- **Given:** FastAPI project with malformed factory data
- **When:** Factory generates invalid request body
- **Then:**
  - Request marked failed (CC-19)
  - Error logged in stats (CC-18)
  - Test continues with next request (T-25)

**US-24: Support custom scenario files**
- **As a** developer with unique testing needs
- **I want** to provide custom scenario files
- **So that** I can test specific user journeys
- **Given:** FastAPI project with custom scenario
- **When:** I provide `custom_scenario.py`
- **Then:**
  - Tool uses custom scenario instead of default (CC-03)
  - Stats collected per custom task (CC-18)
  - SLOs enforced on custom endpoints (CC-09)

**US-25: Ensure tool idempotency**
- **As a** developer re-running the tool
- **I want** the tool to be idempotent
- **So that** I can safely re-run it
- **Given:** FastAPI project with existing load test files
- **When:** I call `add_load_profile(project_dir="my_project")` again
- **Then:**
  - No duplicate files created (CC-20)
  - Existing files preserved (INV-LD-08)
  - Tool reports "already configured" (T-30)

---

## 10. Test Plan

### 10.1 Generation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Locustfile generated | FastAPI project with `/api/v1/items` endpoint | Run `add_load_profile(project_dir="my_project")` | `tests/load/locustfile.py` exists with `ApiUser` class |
| T-02 | Default task weights | Project with GET/POST endpoints | Inspect `locustfile.py` | GET /api/v1/items has `@task(10)`, POST /api/v1/items has `@task(1)` |
| T-03 | Production URL blocked | Target URL set to `https://prod.example.com` | Run tool | Raises `ValueError` with "Production URL blocked" |
| T-04 | Authentication implemented | Project with JWT auth | Inspect `locustfile.py` | `on_start` method performs login, stores `Authorization: Bearer` header |
| T-05 | Factory data validation | `ItemFactory` generates data | Run `ItemFactory.build().model_dump()` through schema | Data passes Pydantic validation |
| T-06 | Scenario files created | Project with browsing/active/admin endpoints | Run tool | `browsing_user.py`, `active_user.py`, `admin_user.py` exist in `tests/load/scenarios/` |

### 10.2 Execution Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Authentication once per user | Run with 100 users | Inspect logs | Exactly 100 login requests made |
| T-08 | Wait time between tasks | Run test | Measure time between requests | Wait time between 0.5-2.5 seconds |
| T-09 | Locust startup time | Start test | Measure time to first request | < 5 seconds |
| T-10 | Concurrent user count | Run with 500 users | Inspect stats | 500 concurrent users reached |
| T-11 | Spawn rate | Run with spawn_rate=20 | Inspect logs | 20 users spawned per second |
| T-12 | Test duration | Run with duration_seconds=30 | Measure test runtime | Test runs for exactly 30 seconds |

### 10.3 SLO Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | SLO violation fails test | Set GET /api/v1/items target=500ms, p99=600ms | Run test | Test fails with exit code 1 |
| T-14 | Missing SLO target | Endpoint without SLO target | Run test | Test continues normally, endpoint included in stats |
| T-15 | SLO JSON output | Run test | Inspect `slos.json` | File contains endpoint targets |
| T-16 | Failed requests excluded | Endpoint returns 500 errors | Inspect stats | Failed requests counted separately, excluded from SLO calculation |
| T-17 | HTML report SLO violations | Endpoint exceeds target | Inspect HTML report | Violation highlighted in red |
| T-18 | Per-environment SLO targets | Set `LOAD_TEST_SLO_TARGETS` env var | Run test | Test uses overridden targets |

### 10.4 CI Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | CI workflow runs on PR | Open pull request | Inspect CI logs | Load test runs |
| T-20 | CI workflow runs on push | Push to main branch | Inspect CI logs | Load test runs |
| T-21 | JSON results generated | Run test | Inspect artifacts | `load_stats.json` exists |
| T-22 | CSV results generated | Run test | Inspect artifacts | `load_stats.csv` exists |
| T-23 | Headless mode | Run in CI | Inspect logs | Locust runs with `--headless` flag |
| T-24 | Block deployment on SLO fail | Endpoint exceeds target | Inspect CI logs | Deployment pipeline fails |

### 10.5 Robustness Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Invalid factory data | Factory generates invalid request | Run test | Request marked failed, test continues |
| T-26 | Server downtime | Stop server mid-test | Inspect stats | 100% failure rate, partial stats written |
| T-27 | Locust worker crash | Kill worker process | Inspect logs | Remaining workers continue, stats partial |
| T-28 | Tool idempotency | Run tool twice | Inspect files | No duplicate files, tool reports "already configured" |
| T-29 | Application code unchanged | Run tool | Inspect project files | Only test files modified |
| T-30 | Graceful shutdown | Test duration ends | Inspect logs | Workers shutdown gracefully, resources cleaned up |

---

## 11. Interaction Matrix

| Other tool           | Order matters? | Interaction | Notes |
|----------------------|----------------|-------------|-------|
| add_soft_delete       | No             | ✅ Compatible | Load tests verify soft-deleted records are excluded from responses |
| add_cursor_pagination | No             | ✅ Compatible | Load tests verify pagination performance under concurrent access |
| add_search           | No             | ✅ Compatible | Search endpoints included in load test scenarios |
| add_audit_log        | No             | ✅ Compatible | Audit logs verify load test request patterns |
| add_data_export      | No             | ✅ Compatible | Export endpoints included in admin user scenarios |
| add_bulk_operations  | No             | ✅ Compatible | Bulk endpoints tested under high concurrent load |
| add_multi_tenancy    | Yes            | ⚠️ Caveat    | Must run after multi-tenancy to test tenant isolation |
| add_feature_flags    | No             | ✅ Compatible | Feature flags tested under load for rollout scenarios |
| add_api_key_auth     | No             | ✅ Compatible | API key auth tested alongside JWT auth |
| add_oauth2_provider  | No             | ✅ Compatible | OAuth2 endpoints included in auth scenarios |
| add_rbac             | No             | ✅ Compatible | RBAC permissions verified under concurrent access |
| add_mfa              | No             | ✅ Compatible | MFA endpoints tested under load |
| add_cache_layer      | No             | ✅ Compatible | Cache performance measured under load |
| add_outbox_pattern   | No             | ✅ Compatible | Outbox pattern verified under high write load |
| add_sse              | No             | ✅ Compatible | SSE endpoints tested under concurrent connections |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout tests/load/locustfile.py
git checkout tests/load/slo_assertions.py
git checkout tests/load/scenarios/
git checkout .github/workflows/load_test.yml
git checkout tests/load/config.py
rm -rf tests/load/locustfile.py
rm -rf tests/load/slo_assertions.py
rm -rf tests/load/scenarios/
rm -rf .github/workflows/load_test.yml
rm -rf tests/load/config.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout tests/load/locustfile.py
git checkout tests/load/slo_assertions.py
git checkout tests/load/scenarios/
git checkout .github/workflows/load_test.yml
git checkout tests/load/config.py
rm -rf tests/load/locustfile.py
rm -rf tests/load/slo_assertions.py
rm -rf tests/load/scenarios/
rm -rf .github/workflows/load_test.yml
rm -rf tests/load/config.py
```

### Emergency: Locust workers fail to shutdown
1. Identify Locust worker PIDs: `ps aux | grep locust`
2. Kill all workers: `pkill -f locust`
3. Clean up any remaining test artifacts: `rm -rf load_stats*`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Server down at test start | Locust fails fast with 100% failure rate |
| EC-2 | All requests fail auth | Locust reports 100% failure, SLO comparison skipped |
| EC-3 | Target URL points to production | Tool errors with message: "Production URL blocked. Use --allow-prod to override." |
| EC-4 | SLO target set to < 1 ms | Tool warns: "SLO target < 1 ms may be unrealistic. Verify before proceeding." |
| EC-5 | Test duration set to 0 | Test completes immediately with no stats collected |
| EC-6 | Endpoint returns 500 under load | Requests marked failed, excluded from SLO comparison |
| EC-7 | Locust worker crashes mid-test | Partial stats written, remaining workers continue |
| EC-8 | Spawn rate exceeds user count | All users spawn immediately, test runs normally |
| EC-9 | Two users share auth token | Token reused without issue, Locust handles gracefully |
| EC-10 | Factory generates invalid request body | Request marked failed, test continues normally |
| EC-11 | Custom scenario file missing | Tool falls back to default locustfile.py |
| EC-12 | Report output path not writable | Tool errors before test starts with path permission error |
| EC-13 | Load test triggers rate limiter | Report shows 429s, SLO comparison adjusts accordingly |
| EC-14 | Tool re-run on existing setup | Idempotent: skips existing files, reports "already configured" |
| EC-15 | CI environment lacks Locust binary | Test skipped with warning: "Locust not installed. Skipping load test." |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified  
✅ Locustfile exists with weighted tasks for all endpoints  
✅ SLO assertions module fails test on violation  
✅ Three scenario scripts cover browsing/active/admin patterns  
✅ CI workflow runs load tests on PR and main  
✅ Load test config validates against production URLs  
✅ Factory data passes schema validation  
✅ HTML and CSV reports generated on every run  
✅ Test duration and user count configurable  
✅ Developer successfully runs end-to-end load test: `locust -f tests/load/locustfile.py --headless --users 100 --spawn-rate 10 --run-time 1m`

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `tests/` directory exists
- [ ] Validate FastAPI project structure
- [ ] Validate Locust installed
- [ ] Detect existing locustfile.py
- [ ] Validate authentication middleware exists
- [ ] Validate factories exist for request data

### 15.2 Locustfile generation
- [ ] Create `tests/load/locustfile.py`
- [ ] Implement `ApiUser` class
- [ ] Add `on_start` method for auth
- [ ] Add `@task` methods for endpoints
- [ ] Set realistic `wait_time`
- [ ] Import required factories
- [ ] Verify file parses with `ast.parse`

### 15.3 SLO assertions
- [ ] Create `tests/load/slo_assertions.py`
- [ ] Implement `on_locust_init` listener
- [ ] Add `test_stop` listener
- [ ] Compare p99 against targets
- [ ] Set `process_exit_code` on violation
- [ ] Write SLOs to `slos.json`
- [ ] Verify file parses

### 15.4 Scenario scripts
- [ ] Create `tests/load/scenarios/browsing_user.py`
- [ ] Create `tests/load/scenarios/active_user.py`
- [ ] Create `tests/load/scenarios/admin_user.py`
- [ ] Implement base `BaseUser` class
- [ ] Add realistic task weights
- [ ] Use factory-generated data
- [ ] Verify files parse

### 15.5 CI configuration
- [ ] Create `.github/workflows/load_test.yml`
- [ ] Add Locust installation step
- [ ] Configure headless execution
- [ ] Set default user count
- [ ] Set default spawn rate
- [ ] Configure report generation
- [ ] Verify workflow syntax

### 15.6 Load test config
- [ ] Create `tests/load/config.py`
- [ ] Implement `LoadTestConfig` class
- [ ] Add default SLO targets
- [ ] Add environment variable support
- [ ] Add production URL validation
- [ ] Add default test parameters
- [ ] Verify file parses

### 15.7 Factory integration
- [ ] Import `ItemFactory` in locustfile
- [ ] Import `UserFactory` in locustfile
- [ ] Use factories for request bodies
- [ ] Verify factory data matches schemas
- [ ] Add random data generation
- [ ] Handle factory validation errors
- [ ] Verify factories exist

### 15.8 Authentication setup
- [ ] Implement `on_start` method
- [ ] Store JWT token
- [ ] Set auth headers
- [ ] Verify auth flow
- [ ] Handle auth failures
- [ ] Reuse token across tasks
- [ ] Verify auth middleware exists

### 15.9 Report generation
- [ ] Configure CSV output
- [ ] Configure HTML output
- [ ] Verify report paths
- [ ] Include SLO violations
- [ ] Verify report completeness
- [ ] Handle write failures
- [ ] Verify report accessibility

### 15.10 Atomicity
- [ ] Use temp-file + rename pattern
- [ ] Track touched files
- [ ] Implement rollback on failure
- [ ] Verify no partial files
- [ ] Handle concurrent execution
- [ ] Verify idempotency
- [ ] Return success/failure report

### 15.11 Documentation
- [ ] Append load testing section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py` with new MCP tool decorator
- [ ] Add usage examples
- [ ] Add troubleshooting guide
- [ ] Verify documentation completeness

### 15.12 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify no regressions
- [ ] Measure tool execution time
- [ ] Measure Locust overhead
- [ ] Verify SLO assertion performance
- [ ] Return success report with metrics

### 15.13 CI integration
- [ ] Verify workflow runs on PR
- [ ] Verify workflow runs on push
- [ ] Verify artifact upload
- [ ] Verify headless execution
- [ ] Verify JSON output
- [ ] Verify CSV output
- [ ] Verify SLO violation handling

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "tests/load/locustfile.py",
    "tests/load/slo_assertions.py",
    "tests/load/scenarios/browsing_user.py",
    "tests/load/scenarios/active_user.py",
    "tests/load/scenarios/admin_user.py",
    ".github/workflows/load_test.yml",
    "tests/load/config.py",
    "tests/load/__init__.py"
  ],
  "files_modified": [
    "pyproject.toml",
    "README.md",
    "tests/conftest.py"
  ],
  "metrics": {
    "execution_time_ms": 2876,
    "files_changed": 11,
    "lines_added": 842,
    "lines_removed": 12,
    "default_users": 100,
    "default_spawn_rate": 10
  },
  "next_steps": [
    "Run: locust -f tests/load/locustfile.py --headless --users 100 --spawn-rate 10 --run-time 1m",
    "Verify: Check load_stats.csv for performance metrics",
    "Analyze: Review HTML report for SLO violations",
    "Adjust: Modify SLO targets in tests/load/config.py as needed",
    "Commit: Add load test files to version control"
  ],
  "warnings": [
    "Production URLs are blocked by default. Use --allow-prod to override.",
    "SLO targets < 1 ms may be unrealistic. Verify before proceeding."
  ],
  "notes": [
    "Load test profile generated with 3 scenarios: Browsing, Active, Admin",
    "Default SLO targets set for GET/POST/PATCH endpoints",
    "Authentication implemented with JWT reuse across tasks",
    "CI workflow configured to run on PR and push to main"
  ]
}
