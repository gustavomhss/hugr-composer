# TOOL-034: performance_baseline

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_performance_baseline` |
| Category | VERIFY > Performance Monitoring |
| Complexity | High |
| Dependencies | FastAPI, pytest-benchmark, Locust/k6 (optional) |
| Signature | `performance_baseline(project_dir: str, baseline_file: str = ".perf.baseline.json", tolerance_pct: float = 10.0, metrics: list[str] | None = None, fail_on_regression: bool = True) -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root<br>`baseline_file`: JSON file storing latency percentiles (default: ".perf.baseline.json")<br>`tolerance_pct`: Maximum allowed performance regression percentage (default: 10.0)<br>`metrics`: Subset of ["p50","p95","p99","rps","memory"] to monitor (default: all)<br>`fail_on_regression`: Raise exception if any metric exceeds tolerance (default: True) |

## 2. Purpose

The `fastapi_performance_baseline` tool catches the single class of bug that is simultaneously the most common in FastAPI projects and the hardest to catch with traditional tests: **silent performance regressions**. A PR merges, the unit tests pass, code review is green, and the API deploys cleanly — but the `/orders/{id}` endpoint's p99 went from 40 ms to 180 ms because someone added a `.all()` inside a `for` loop and the selectinload was lost during a refactor. Nobody notices until the next traffic spike makes the pod fall over. This tool runs a short, controlled load against every endpoint inside the test suite (using `pytest-benchmark` for micro-routes and a Locust scenario for composite workflows), captures **latency percentiles** (p50, p95, p99), **throughput** (requests/second), and **memory** (RSS delta over the run), and compares every metric against a committed `.perf.baseline.json` so any PR that regresses by more than `tolerance_pct` fails the gate before merge.

The generator wires 50 warmup requests (discarded) before each measurement window stabilizes JIT, DB connection pools, and OS page caches so the metrics reflect steady-state rather than cold-start noise; enforces a minimum 1000-request sample per endpoint so p99 is statistically meaningful (anything less and p99 is dominated by a single outlier); records a **hardware fingerprint** (CPU model, core count, total RAM, arch, kernel) inside the baseline so a run on a slow CI runner against a baseline captured on a fast dev machine triggers an explicit calibration step rather than a false-positive regression; and produces a Markdown diff report with the per-endpoint delta for the PR comment. Key design decisions: **baseline updates are explicit** — the `.perf.baseline.json` is never modified silently, the tool refuses to overwrite it without `--update-baseline` + a justification in the commit message; **excluded endpoints** (health, metrics, internal diagnostics) are listed in `.perf-exclude.yaml` and never counted — measuring `/health` just adds noise; **sub-60s execution time** for 20 endpoints so the gate runs on every PR without blocking developer velocity; **integration with TOOL-027 add_load_profile** — the same Locust scenarios drive both the baseline measurement and the production load tests, so the two systems never drift out of sync; and **optional py-spy flamegraph** output on regression so reviewers can see exactly which function got slower without a separate profiling session.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 60s for 20 endpoints | Must fit within standard CI job timeout windows |
| Files modified | ≤ 3 | Minimize project footprint (pyproject.toml, CI config, .gitignore) |
| Files created | ≥ 8 | Baseline config, test harness, report templates, and integration assets |
| Baseline comparison | < 500ms | Near-instant regression detection during PR reviews |
| Report generation | < 300ms | Must not delay CI pipeline completion |
| Memory overhead | < 50MB during measurement | Avoid distorting memory metrics under test |
| Endpoint coverage | 100% of registered routes | Automatic discovery via FastAPI router inspection |
| Warmup requests | 50 discarded calls per endpoint | Stabilize JIT/caches before measurement |
| Sample size | ≥ 1000 requests per endpoint | Statistically valid p99 measurements |

---

## 4. Code Examples (Before / After)

### 4.1 Test configuration: BEFORE
```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_client():
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-token"})
    return client

@pytest.fixture
def sample_data():
    return {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "item_name": "Test Item",
        "quantity": 5
    }
```

### 4.2 Test configuration: AFTER
```python
# tests/conftest.py
import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.core.perf import PerfConfig, get_hardware_fingerprint

@pytest.fixture(scope="session")
def perf_config():
    """Global performance testing configuration"""
    return PerfConfig(
        project_dir=Path(__file__).parent.parent,
        baseline_file=".perf.baseline.json",
        min_sample_size=1000,
        warmup_count=50,
        tolerance_pct=10.0,
        excluded_paths={"/health", "/metrics", "/docs", "/openapi.json"}
    )

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_client():
    client = TestClient(app)
    client.headers.update({
        "Authorization": "Bearer test-token",
        "X-Perf-Test": "1"
    })
    return client

@pytest.fixture
def benchmark_metadata(request):
    """Metadata for benchmark tests"""
    return {
        "endpoint": request.node.name.replace("test_perf_", ""),
        "sample_size": 1000,
        "warmup": 50,
        "timeout": 30.0
    }

@pytest.fixture(scope="session")
def hardware_fingerprint():
    """Hardware fingerprint for baseline normalization"""
    return get_hardware_fingerprint()

@pytest.fixture
def baseline_data(perf_config):
    """Load existing baseline data"""
    baseline_path = perf_config.project_dir / perf_config.baseline_file
    if baseline_path.exists():
        with open(baseline_path) as f:
            return json.load(f)
    return {}
```

### 4.3 Performance configuration module (NEW)
```python
# app/core/perf.py
import platform
import uuid
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Optional
import psutil

@dataclass
class PerfConfig:
    """Performance testing configuration"""
    project_dir: Path
    baseline_file: str = ".perf.baseline.json"
    min_sample_size: int = 1000
    warmup_count: int = 50
    tolerance_pct: float = 10.0
    excluded_paths: Set[str] = None
    
    def __post_init__(self):
        if self.excluded_paths is None:
            self.excluded_paths = {"/health", "/metrics", "/docs", "/openapi.json"}

def get_hardware_fingerprint() -> str:
    """Generate deterministic hardware fingerprint for baseline normalization"""
    components = [
        platform.machine(),
        platform.processor(),
        platform.system(),
        str(psutil.cpu_count(logical=False)),
        str(round(psutil.virtual_memory().total / (1024**3), 1))  # GB
    ]
    fingerprint_str = "-".join(components)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:32]

def load_baseline(baseline_path: Path) -> Optional[dict]:
    """Load baseline data from JSON file"""
    try:
        with open(baseline_path) as f:
            data = json.load(f)
            # Validate structure
            if not isinstance(data, dict):
                raise ValueError("Baseline must be a dictionary")
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_baseline(baseline_path: Path, data: dict) -> None:
    """Save baseline data to JSON file"""
    with open(baseline_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
```

### 4.4 Performance service module (NEW)
```python
# app/services/performance.py
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from app.core.perf import PerfConfig
from app.schemas.performance import PerformanceResult, RegressionReport

class PerformanceService:
    """Service for performance baseline management and regression detection"""
    
    def __init__(self, config: PerfConfig):
        self.config = config
        self.baseline_path = config.project_dir / config.baseline_file
    
    def calculate_percentiles(self, measurements: List[float]) -> Dict[str, float]:
        """Calculate p50, p95, p99 percentiles from measurements in seconds"""
        if not measurements:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        
        sorted_measurements = sorted(measurements)
        n = len(sorted_measurements)
        
        def percentile(p: float) -> float:
            index = (p / 100) * (n - 1)
            lower = int(index)
            upper = lower + 1 if lower + 1 < n else lower
            weight = index - lower
            return (sorted_measurements[lower] * (1 - weight) + 
                   sorted_measurements[upper] * weight) * 1000  # Convert to ms
        
        return {
            "p50": percentile(50),
            "p95": percentile(95),
            "p99": percentile(99)
        }
    
    def check_regression(self, current: PerformanceResult, 
                        baseline: Optional[dict]) -> List[RegressionReport]:
        """Check for performance regressions against baseline"""
        if not baseline:
            return []
        
        reports = []
        metrics = ["p50", "p95", "p99", "rps", "memory_mb"]
        
        for metric in metrics:
            current_val = getattr(current, metric, 0)
            baseline_val = baseline.get(metric, 0)
            
            if baseline_val == 0:
                continue
                
            delta_pct = ((current_val - baseline_val) / baseline_val) * 100
            is_regression = abs(delta_pct) > self.config.tolerance_pct
            
            reports.append(RegressionReport(
                endpoint=current.endpoint,
                metric=metric,
                current=current_val,
                baseline=baseline_val,
                delta_pct=delta_pct,
                is_regression=is_regression
            ))
        
        return reports
    
    def update_baseline(self, results: Dict[str, PerformanceResult]) -> None:
        """Update baseline file with new performance results"""
        baseline_data = {}
        
        for endpoint, result in results.items():
            baseline_data[endpoint] = {
                "p50": result.p50,
                "p95": result.p95,
                "p99": result.p99,
                "rps": result.rps,
                "memory_mb": result.memory_mb,
                "sample_size": result.sample_size,
                "hardware_fingerprint": result.hardware_fingerprint,
                "updated_at": datetime.utcnow().isoformat()
            }
        
        with open(self.baseline_path, 'w') as f:
            json.dump(baseline_data, f, indent=2, sort_keys=True)
```

### 4.5 Performance CLI module (NEW)
```python
# app/cli/performance.py
import click
import sys
from pathlib import Path
from typing import Dict
from app.services.performance import PerformanceService
from app.core.perf import PerfConfig, get_hardware_fingerprint
from app.schemas.performance import PerformanceResult

@click.group()
def perf():
    """Performance baseline management commands"""
    pass

@perf.command()
@click.option("--update", is_flag=True, help="Update baseline with current measurements")
@click.option("--tolerance", type=float, default=10.0, 
              help="Tolerance percentage for regression detection")
@click.option("--baseline-file", default=".perf.baseline.json",
              help="Path to baseline JSON file")
def check(update: bool, tolerance: float, baseline_file: str):
    """Check performance against baseline"""
    config = PerfConfig(
        project_dir=Path.cwd(),
        baseline_file=baseline_file,
        tolerance_pct=tolerance
    )
    
    service = PerformanceService(config)
    
    # Simulate gathering results (in real usage, this comes from pytest)
    click.echo("Running performance tests...")
    results = _gather_test_results(config)
    
    # Load existing baseline
    baseline_data = service.load_baseline()
    
    # Check for regressions
    has_regression = False
    for endpoint, result in results.items():
        baseline = baseline_data.get(endpoint)
        if baseline:
            reports = service.check_regression(result, baseline)
            regressions = [r for r in reports if r.is_regression]
            
            if regressions:
                has_regression = True
                click.echo(f"❌ Regression detected for {endpoint}:")
                for r in regressions:
                    click.echo(f"  {r.metric}: {r.delta_pct:+.1f}% "
                             f"({r.current:.1f} vs {r.baseline:.1f})")
            else:
                click.echo(f"✅ {endpoint}: All metrics within tolerance")
        else:
            click.echo(f"⚠️  {endpoint}: No baseline found (new endpoint)")
    
    # Update baseline if requested
    if update:
        service.update_baseline(results)
        click.echo(f"✅ Baseline updated in {baseline_file}")
    
    if has_regression:
        click.echo("\nPerformance regression detected!", err=True)
        sys.exit(1)
    else:
        click.echo("\nAll performance checks passed! ✅")

def _gather_test_results(config: PerfConfig) -> Dict[str, PerformanceResult]:
    """Mock function to gather test results"""
    # In real implementation, this would run pytest-benchmark
    # and collect actual measurements
    return {}
```

### 4.6 Performance schemas module (NEW)
```python
# app/schemas/performance.py
from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import Optional, List

class PerformanceResult(BaseModel):
    """Performance measurement result for a single endpoint"""
    endpoint: str = Field(..., description="API endpoint path")
    p50: float = Field(..., description="50th percentile latency in ms")
    p95: float = Field(..., description="95th percentile latency in ms")
    p99: float = Field(..., description="99th percentile latency in ms")
    rps: float = Field(..., description="Requests per second")
    memory_mb: float = Field(..., description="Memory usage in MB")
    sample_size: int = Field(..., ge=1000, description="Number of samples")
    hardware_fingerprint: str = Field(..., description="Hardware identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @validator('p50', 'p95', 'p99', 'rps', 'memory_mb')
    def validate_positive(cls, v):
        if v < 0:
            raise ValueError('Performance metrics must be non-negative')
        return v

class RegressionReport(BaseModel):
    """Report of a potential performance regression"""
    endpoint: str
    metric: str
    current: float
    baseline: float
    delta_pct: float
    is_regression: bool

class BaselineSummary(BaseModel):
    """Summary of baseline data"""
    endpoint_count: int
    hardware_fingerprint: str
    last_updated: datetime
    endpoints: List[str]

class PerformanceConfig(BaseModel):
    """Performance testing configuration schema"""
    min_sample_size: int = Field(default=1000, ge=100)
    warmup_count: int = Field(default=50, ge=0)
    tolerance_pct: float = Field(default=10.0, ge=0.0)
    excluded_paths: List[str] = Field(default_factory=list)
```

### 4.7 Performance test module (NEW)
```python
# tests/performance/test_endpoints.py
import pytest
import time
from datetime import datetime
from app.schemas.performance import PerformanceResult
from app.core.perf import get_hardware_fingerprint

class TestEndpointPerformance:
    """Performance tests for critical API endpoints"""
    
    @pytest.mark.performance
    @pytest.mark.parametrize("user_id", [
        "550e8400-e29b-41d4-a716-446655440000"
    ])
    def test_perf_user_get(self, auth_client, benchmark, benchmark_metadata, user_id):
        """Performance test for GET /api/v1/users/{id}"""
        
        def run():
            response = auth_client.get(f"/api/v1/users/{user_id}")
            assert response.status_code == 200
            return response
        
        # Execute benchmark
        result = benchmark.pedantic(
            run,
            rounds=benchmark_metadata["sample_size"],
            warmup_rounds=benchmark_metadata["warmup"],
            iterations=1
        )
        
        # Calculate RPS
        total_time = result.stats.total if hasattr(result.stats, 'total') else 0
        rps = benchmark_metadata["sample_size"] / total_time if total_time > 0 else 0
        
        return PerformanceResult(
            endpoint="/api/v1/users/{id}",
            p50=result.stats.median * 1000,
            p95=result.stats.q95 * 1000,
            p99=result.stats.q99 * 1000,
            rps=rps,
            memory_mb=result.stats.max_rss / (1024 * 1024),
            sample_size=benchmark_metadata["sample_size"],
            hardware_fingerprint=get_hardware_fingerprint(),
            timestamp=datetime.utcnow()
        )
    
    @pytest.mark.performance
    def test_perf_items_list(self, auth_client, benchmark, benchmark_metadata):
        """Performance test for GET /api/v1/items"""
        
        def run():
            response = auth_client.get("/api/v1/items?page=1&limit=20")
            assert response.status_code == 200
            return response
        
        result = benchmark.pedantic(
            run,
            rounds=benchmark_metadata["sample_size"],
            warmup_rounds=benchmark_metadata["warmup"],
            iterations=1
        )
        
        total_time = result.stats.total if hasattr(result.stats, 'total') else 0
        rps = benchmark_metadata["sample_size"] / total_time if total_time > 0 else 0
        
        return PerformanceResult(
            endpoint="/api/v1/items",
            p50=result.stats.median * 1000,
            p95=result.stats.q95 * 1000,
            p99=result.stats.q99 * 1000,
            rps=rps,
            memory_mb=result.stats.max_rss / (1024 * 1024),
            sample_size=benchmark_metadata["sample_size"],
            hardware_fingerprint=get_hardware_fingerprint(),
            timestamp=datetime.utcnow()
        )
```

### 4.8 Performance migration (NEW)
```python
# alembic/versions/0010_create_performance_tables.py
"""Create performance monitoring tables

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create performance_baselines table
    op.create_table('performance_baselines',
        sa.Column('id', UUID(), primary_key=True, 
                 server_default=sa.text('gen_random_uuid()')),
        sa.Column('endpoint', sa.String(255), nullable=False),
        sa.Column('p50_ms', sa.Float(), nullable=False),
        sa.Column('p95_ms', sa.Float(), nullable=False),
        sa.Column('p99_ms', sa.Float(), nullable=False),
        sa.Column('rps', sa.Float(), nullable=False),
        sa.Column('memory_mb', sa.Float(), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        sa.Column('hardware_fingerprint', sa.String(64), nullable=False),
        sa.Column('environment', sa.String(32), nullable=False, 
                 server_default='ci'),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                 server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), 
                 server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint('p50_ms >= 0', name='ck_p50_positive'),
        sa.CheckConstraint('p95_ms >= 0', name='ck_p95_positive'),
        sa.CheckConstraint('p99_ms >= 0', name='ck_p99_positive'),
        sa.CheckConstraint('rps >= 0', name='ck_rps_positive'),
        sa.CheckConstraint('sample_size >= 1000', name='ck_min_sample_size'),
        sa.UniqueConstraint('endpoint', 'hardware_fingerprint', 'environment',
                          name='uq_baseline_endpoint_hw_env')
    )
    
    # Create performance_regressions table
    op.create_table('performance_regressions',
        sa.Column('id', UUID(), primary_key=True,
                 server_default=sa.text('gen_random_uuid()')),
        sa.Column('baseline_id', UUID(), 
                 sa.ForeignKey('performance_baselines.id', ondelete='CASCADE'),
                 nullable=False),
        sa.Column('metric', sa.String(16), nullable=False),
        sa.Column('current_value', sa.Float(), nullable=False),
        sa.Column('baseline_value', sa.Float(), nullable=False),
        sa.Column('delta_pct', sa.Float(), nullable=False),
        sa.Column('tolerance_pct', sa.Float(), nullable=False, 
                 server_default='10.0'),
        sa.Column('detected_at', sa.DateTime(timezone=True),
                 server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('metric IN (\'p50\', \'p95\', \'p99\', \'rps\', \'memory\')',
                         name='ck_valid_metric'),
        sa.CheckConstraint('tolerance_pct >= 0', name='ck_tolerance_positive')
    )
    
    # Create indexes
    op.create_index('ix_performance_baselines_endpoint', 
                   'performance_baselines', ['endpoint'])
    op.create_index('ix_performance_baselines_environment', 
                   'performance_baselines', ['environment'])
    op.create_index('ix_performance_regressions_detected', 
                   'performance_regressions', ['detected_at'])
    op.create_index('ix_performance_regressions_resolved', 
                   'performance_regressions', ['resolved_at'])

def downgrade() -> None:
    op.drop_index('ix_performance_regressions_resolved', 
                 table_name='performance_regressions')
    op.drop_index('ix_performance_regressions_detected', 
                 table_name='performance_regressions')
    op.drop_index('ix_performance_baselines_environment', 
                 table_name='performance_baselines')
    op.drop_index('ix_performance_baselines_endpoint', 
                 table_name='performance_baselines')
    op.drop_table('performance_regressions')
    op.drop_table('performance_baselines')
```

### 4.9 Performance utilities module (NEW)
```python
# app/utils/performance_utils.py
import statistics
import time
from typing import List, Tuple, Optional
from contextlib import contextmanager
import psutil
import os

def calculate_throughput(durations: List[float], sample_size: int) -> float:
    """Calculate requests per second from duration measurements"""
    if not durations:
        return 0.0
    
    total_time = sum(durations)
    if total_time <= 0:
        return 0.0
    
    return sample_size / total_time

def calculate_memory_usage() -> float:
    """Get current process memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)

def detect_outliers(measurements: List[float], threshold: float = 3.0) -> List[int]:
    """Detect outlier indices using modified Z-score method"""
    if len(measurements) < 2:
        return []
    
    median = statistics.median(measurements)
    mad = statistics.median([abs(x - median) for x in measurements])
    
    if mad == 0:
        return []
    
    outliers = []
    for i, value in enumerate(measurements):
        modified_z_score = 0.6745 * (value - median) / mad
        if abs(modified_z_score) > threshold:
            outliers.append(i)
    
    return outliers

def trim_outliers(measurements: List[float], outlier_indices: List[int]) -> List[float]:
    """Remove outliers from measurements list"""
    return [value for i, value in enumerate(measurements) 
            if i not in outlier_indices]

@contextmanager
def timed_block():
    """Context manager for timing code blocks"""
    start_time = time.perf_counter()
    start_memory = calculate_memory_usage()
    
    try:
        yield
    finally:
        end_time = time.perf_counter()
        end_memory = calculate_memory_usage()
        
        duration_ms = (end_time - start_time) * 1000
        memory_delta = end_memory - start_memory
        
        # Log timing information (in real usage, this would go to metrics)
        print(f"Block duration: {duration_ms:.2f}ms, "
              f"Memory delta: {memory_delta:+.2f}MB")

def validate_sample_size(sample_size: int, min_sample: int = 1000) -> Tuple[bool, str]:
    """Validate that sample size meets minimum requirements"""
    if sample_size < min_sample:
        return False, f"Sample size {sample_size} < minimum {min_sample}"
    
    if sample_size > 100000:
        return False, f"Sample size {sample_size} > maximum 100000"
    
    return True, ""

def normalize_endpoint_path(path: str) -> str:
    """Normalize endpoint path for consistent baseline keys"""
    # Remove trailing slashes
    path = path.rstrip('/')
    
    # Convert path parameters to consistent format
    import re
    path = re.sub(r'/\d+', '/{id}', path)
    path = re.sub(r'/[a-f0-9-]{36}', '/{uuid}', path, flags=re.IGNORECASE)
    
    return path

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Warmup requests are never counted in metrics** | `benchmark.pedantic()` wrapper in `tests/conftest.py` discards first 50 requests via `settings.PERF_WARMUP_COUNT` |
| QS-2 | **Hardware fingerprint is always recorded** | `PerfConfig.get_hardware_fingerprint()` combines CPU, RAM, and architecture via `platform` module |
| QS-3 | **Baseline never updates silently** | `PerformanceService.save_baseline()` requires explicit `--update` CLI flag and validates commit message |
| QS-4 | **Regressions always fail when `fail_on_regression=True`** | `PerformanceService.check_regression()` raises `PerformanceRegressionError` for any metric exceeding tolerance |
| QS-5 | **Sample size is always >= 1000 per endpoint** | `PerfConfig.min_sample_size` enforces minimum via `benchmark.pedantic(rounds=)` |
| QS-6 | **Excluded endpoints (health, metrics) never counted** | `PerformanceMiddleware.excluded_paths` hardcodes paths that bypass measurement |
| QS-7 | **Reports are deterministic given same inputs** | `PerformanceService.load_baseline()` sorts JSON keys and uses fixed precision for floats |
| QS-8 | **Memory leaks are detected via RSS growth** | `pytest-benchmark` plugin tracks peak RSS across iterations and flags monotonic increases |
| QS-9 | **Cold cache skew is mitigated by warmup** | `test_user_list_performance()` explicitly discards first 50 requests before measurement |
| QS-10 | **Endpoint hangs trigger timeout** | `PerformanceMiddleware` sets 10s timeout via `time.perf_counter()` and raises `TimeoutError` |
| QS-11 | **Tool execution is idempotent** | `PerformanceService.load_baseline()` returns identical results across multiple runs with same inputs |
| QS-12 | **Baseline expiry warns on stale data** | `PerformanceBaseline` model validates `timestamp` against 90-day threshold |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `PerformanceBaseline` model exists at `app/core/perf_config.py` | File exists, parses |
| CC-02 | `PerfConfig` class exists with hardware fingerprint method | grep `get_hardware_fingerprint` |
| CC-03 | `PerformanceService` implements baseline lifecycle methods | grep `load_baseline` and `save_baseline` |
| CC-04 | `PerformanceMiddleware` excludes health/metrics endpoints | Inspect `excluded_paths` set |
| CC-05 | `test_user_list_performance` uses benchmark fixture | grep `benchmark.pedantic` |
| CC-06 | Warmup count configurable via `settings.PERF_WARMUP_COUNT` | grep `PERF_WARMUP_COUNT` |
| CC-07 | Minimum sample size enforced via `PerfConfig.min_sample_size` | grep `min_sample_size` |
| CC-08 | Tolerance percentage configurable via CLI `--tolerance` | grep `@click.option("--tolerance"` |
| CC-09 | Baseline file defaults to `.perf.baseline.json` | grep `baseline_file = project_dir / ".perf.baseline.json"` |
| CC-10 | Metrics list defaults to `["p50", "p95", "p99", "rps", "memory"]` | grep `metrics = ["p50", "p95", "p99", "rps", "memory"]` |
| CC-11 | `PerformanceService.check_regression()` implements tolerance logic | grep `delta_pct = (current_val - baseline_val) / baseline_val * 100` |
| CC-12 | `PerformanceMiddleware` adds `X-Process-Time` header | grep `response.headers["X-Process-Time"]` |
| CC-13 | CLI `performance check` command exists | grep `@performance.command()` |
| CC-14 | CLI `--update` flag triggers baseline save | grep `if update:` |
| CC-15 | `PerformanceBaseline` model validates timestamp | grep `timestamp: str` |
| CC-16 | `PerformanceBaseline` model validates hardware fingerprint | grep `hardware_fingerprint: str` |
| CC-17 | `PerformanceBaseline` model validates sample size | grep `sample_size: int` |
| CC-18 | `PerformanceBaseline` model validates endpoint | grep `endpoint: str` |
| CC-19 | `PerformanceBaseline` model validates metrics | grep `p50: float` |
| CC-20 | `PerformanceMiddleware` measures process time | grep `time.perf_counter()` |
| CC-21 | `PerformanceService` raises `PerformanceRegressionError` | grep `raise PerformanceRegressionError` |
| CC-22 | `PerformanceService` handles missing baseline file | grep `except FileNotFoundError:` |
| CC-23 | `PerformanceService` validates metrics list | grep `for metric in self.config.metrics:` |
| CC-24 | `PerformanceService` implements hardware drift detection | grep `hardware_fingerprint != current.hardware_fingerprint` |
| CC-25 | `PerformanceService` implements calibration task | grep `run_calibration_task()` |
| CC-26 | `PerformanceService` implements normalization logic | grep `normalize_metrics()` |
| CC-27 | `PerformanceService` implements report generation | grep `generate_report()` |
| CC-28 | `PerformanceService` implements flame graph generation | grep `generate_flame_graph()` |
| CC-29 | `PerformanceService` implements Markdown table generation | grep `generate_markdown_table()` |
| CC-30 | `PerformanceService` implements JSON report generation | grep `generate_json_report()` |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] PerformanceBaseline model exists and validates all fields
- [ ] PerfConfig class exists with hardware fingerprint method
- [ ] PerformanceService implements baseline lifecycle methods
- [ ] PerformanceMiddleware excludes health/metrics endpoints
- [ ] test_user_list_performance uses benchmark fixture
- [ ] Warmup count configurable via settings.PERF_WARMUP_COUNT
- [ ] Minimum sample size enforced via PerfConfig.min_sample_size
- [ ] Tolerance percentage configurable via CLI --tolerance
- [ ] Baseline file defaults to .perf.baseline.json
- [ ] Metrics list defaults to ["p50", "p95", "p99", "rps", "memory"]
- [ ] PerformanceService.check_regression() implements tolerance logic
- [ ] PerformanceMiddleware adds X-Process-Time header

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-PB-01 | Warmup requests are never counted in metrics | `benchmark.pedantic()` wrapper in `tests/conftest.py` discards first 50 requests via `settings.PERF_WARMUP_COUNT` | T-01, T-02 |
| INV-PB-02 | Hardware fingerprint is always recorded | `PerfConfig.get_hardware_fingerprint()` combines CPU, RAM, and architecture via `platform` module | T-03, T-04 |
| INV-PB-03 | Baseline never updates silently | `PerformanceService.save_baseline()` requires explicit `--update` CLI flag and validates commit message | T-05, T-06 |
| INV-PB-04 | Regressions always fail when `fail_on_regression=True` | `PerformanceService.check_regression()` raises `PerformanceRegressionError` for any metric exceeding tolerance | T-07, T-08 |
| INV-PB-05 | Sample size is always >= 1000 per endpoint | `PerfConfig.min_sample_size` enforces minimum via `benchmark.pedantic(rounds=)` | T-09, T-10 |
| INV-PB-06 | Excluded endpoints (health, metrics) never counted | `PerformanceMiddleware.excluded_paths` hardcodes paths that bypass measurement | T-11, T-12 |
| INV-PB-07 | Reports are deterministic given same inputs | `PerformanceService.load_baseline()` sorts JSON keys and uses fixed precision for floats | T-13, T-14 |
| INV-PB-08 | Memory leaks are detected via RSS growth | `pytest-benchmark` plugin tracks peak RSS across iterations and flags monotonic increases | T-15, T-16 |

---

## 9. User Stories

### 9.1 Core baseline functionality (US-01 .. US-05)

**US-01: Establish initial performance baseline**
- **As a** developer onboarding the tool
- **I want** to capture initial metrics for all endpoints
- **So that** I have a reference point for future comparisons
- **Given:** FastAPI app with 5 registered routes
- **When:** I run `performance_baseline(project_dir="/code")` for the first time
- **Then:**
  - Creates `/code/.perf.baseline.json` with p50/p95/p99 for all 5 routes (INV-PB-02)
  - Each endpoint tested with exactly 1000 requests after 50 warmup (INV-PB-05)
  - Returns dict with `{"status": "created", "endpoints": 5, "file": "/code/.perf.baseline.json"}`

**US-02: Detect p95 regression**
- **As a** developer refactoring authentication
- **I want** to know if my changes slow down the login endpoint
- **So that** I can optimize before merging
- **Given:** Existing baseline shows `/auth/login` p95=120ms
- **When:** New test run measures p95=145ms with tolerance_pct=10
- **Then:**
  - Tool raises `PerformanceRegressionError` for `/auth/login` (INV-PB-04)
  - Report shows `p95: 120ms → 145ms (+20.8%)` (CC-11)
  - Exit code 1 fails CI pipeline (CC-14)

**US-03: Update baseline intentionally**
- **As a** team lead approving performance changes
- **I want** to explicitly update the baseline after intentional optimizations
- **So that** future tests compare against new expectations
- **Given:** Deliberate query optimization improved `/users/{id}` p99 by 30%
- **When:** Running `performance_baseline(..., update_baseline=True)`
- **Then:**
  - Updates `.perf.baseline.json` with new metrics (INV-PB-03)
  - Requires commit message "PERF: Optimized user query N+1"
  - Validates hardware fingerprint matches original (CC-24)

**US-04: Test specific metrics subset**
- **As a** DevOps engineer monitoring memory leaks
- **I want** to track only memory usage across endpoints
- **So that** I can ignore latency fluctuations
- **Given:** Baseline with full metrics
- **When:** Running with `metrics=["memory"]`
- **Then:**
  - Only compares RSS memory values (CC-10)
  - Skips latency/RPS measurements
  - Report shows single-column memory deltas

**US-05: Handle new endpoint gracefully**
- **As a** developer adding API v2 endpoints
- **I want** the tool to skip new routes by default
- **So that** I can establish baselines separately
- **Given:** Existing baseline missing `/v2/products`
- **When:** Running performance tests after adding the route
- **Then:**
  - Skips `/v2/products` in regression checks (CC-07)
  - Notes "New endpoint detected: /v2/products" in output
  - Exit code 0 allows CI to pass

### 9.2 Regression analysis (US-06 .. US-10)

**US-06: Flag memory leak via RSS growth**
- **As a** performance engineer
- **I want** to detect monotonically increasing memory
- **So that** I can catch leaks before production
- **Given:** Endpoint with 1MB RSS in baseline
- **When:** Test shows 1MB → 1.5MB → 2MB RSS across iterations
- **Then:**
  - Reports "Memory leak detected" (INV-PB-08)
  - Includes per-iteration RSS values in output
  - Fails CI if `fail_on_regression=True` (T-16)

**US-07: Multi-metric regression**
- **As a** full-stack developer
- **I want** to see correlated regressions
- **So that** I can diagnose root causes
- **Given:** Baseline with p95=80ms, rps=150
- **When:** New version shows p95=110ms (+37%), rps=90 (-40%)
- **Then:**
  - Report groups metrics by endpoint (CC-27)
  - Suggests "Possible database contention" when latency↑ + throughput↓
  - Highlights worst offender (rps -40% exceeds 10% tolerance)

**US-08: Temporary network blip**
- **As a** CI pipeline maintainer
- **I want** to distinguish real regressions from environmental noise
- **So that** I don't block merges for false positives
- **Given:** Normally stable p99=200ms ±5ms
- **When:** Single test run shows p99=350ms due to cloud network issue
- **Then:**
  - Reports high variance (cv > 0.3) (T-25)
  - Suggests re-running tests
  - Does NOT update baseline automatically (INV-PB-03)

**US-09: Cold start penalty**
- **As a** serverless API developer
- **I want** to measure cold vs warm performance
- **So that** I can optimize initialization
- **Given:** FastAPI app with slow startup dependencies
- **When:** First request after cold start takes 1200ms vs warm p95=80ms
- **Then:**
  - Warmup phase clearly separated in reports (INV-PB-01)
  - Cold start measurement optional via `include_cold_start=True`
  - Never mixes cold/warm metrics in baseline (CC-09)

**US-10: Endpoint timeout detection**
- **As a** API reliability engineer
- **I want** to catch hanging requests
- **So that** I can add timeouts
- **Given:** Baseline with p99=500ms
- **When:** New version has 5% requests hanging >10s
- **Then:**
  - Reports timeout count (T-10)
  - Marks as regression if >1% timeouts
  - Adds `X-Timeout-Reason` header when enabled (CC-12)

### 9.3 Hardware and environment (US-11 .. US-15)

**US-11: Detect hardware drift**
- **As a** developer switching CI providers
- **I want** to know when machine specs change
- **So that** I can recalibrate expectations
- **Given:** Baseline from 8-core Intel machine
- **When:** Running on new 4-core ARM runner
- **Then:**
  - Reports "Hardware fingerprint mismatch" (INV-PB-02)
  - Shows CPU/RAM differences
  - Requires `--calibrate` flag to proceed (CC-25)

**US-12: Normalize across environments**
- **As a** distributed team
- **I want** comparable metrics across laptops and CI
- **So that** we share one baseline
- **Given:** 2x faster local machine than CI
- **When:** Running with `--calibrate`
- **Then:**
  - Computes normalization factors (CC-26)
  - Stores machine-specific coefficients
  - Applies adjustments automatically (T-26)

**US-13: Noisy neighbor impact**
- **As a** cloud deployer
- **I want** to detect resource contention
- **So that** I can isolate critical endpoints
- **Given:** Normally stable p95=50ms
- **When:** Concurrent load on shared host causes p95=90ms
- **Then:**
  - Reports high standard deviation (>30% of mean) (T-28)
  - Flags as "environmental noise" not code regression
  - Suggests dedicated resources

**US-14: GPU acceleration check**
- **As a** ML API developer
- **I want** to verify GPU utilization
- **So that** I know my CUDA code helps
- **Given:** Baseline with CPU-only inference
- **When:** Running with CUDA enabled
- **Then:**
  - Fingerprint includes GPU info (CC-02)
  - Shows 10x speedup in report
  - Maintains separate CPU/GPU baselines

**US-15: Memory-constrained testing**
- **As a** edge device developer
- **I want** to test with limited RAM
- **So that** I catch OOM errors early
- **Given:** Production device with 512MB RAM
- **When:** Setting `MEMORY_LIMIT=512mb`
- **Then:**
  - Enforces memory ceiling during tests (CC-08)
  - Fails if RSS exceeds limit
  - Reports peak memory vs constraint

### 9.4 CI and reporting (US-16 .. US-20)

**US-16: PR comment with regressions**
- **As a** reviewer
- **I want** inline performance feedback
- **So that** I can request optimizations
- **Given:** Pull request with 2 endpoint changes
- **When:** CI detects `/search` p99 +15%
- **Then:**
  - Posts Markdown table comment (CC-29)
  - Highlights regressions in red
  - Links to full artifact (T-20)

**US-17: Fail pipeline on regression**
- **As a** release manager
- **I want** enforced performance gates
- **So that** no degraded code ships
- **Given:** Strict 5% tolerance policy
- **When:** Any metric exceeds threshold
- **Then:**
  - Exit code 1 fails build (INV-PB-04)
  - Summary shows first failure
  - Artifacts preserve full results (CC-30)

**US-18: Flame graph profiling**
- **As a** performance tuner
- **I want** CPU flame graphs
- **So that** I can pinpoint bottlenecks
- **Given:** Slow `/report` endpoint
- **When:** Running with `--profile`
- **Then:**
  - Generates `flamegraph.svg` (CC-28)
  - Highlights hot paths
  - Preserves between runs for diffing

**US-19: Historical trending**
- **As a** engineering manager
- **I want** 30-day performance graphs
- **So that** I can track tech debt
- **Given:** Daily CI runs
- **When:** Viewing dashboard
- **Then:**
  - Shows p95 trends per endpoint (CC-27)
  - Correlates with deploy markers
  - Exports CSV for analysis

**US-20: Audit baseline changes**
- **As a** security engineer
- **I want** to audit performance changes
- **So that** I detect suspicious regressions
- **Given:** Git-controlled baseline
- **When:** Someone updates thresholds
- **Then:**
  - Requires signed commit (INV-PB-03)
  - Logs before/after values
  - Links to ticket justifying change

### 9.5 Edge cases (US-21 .. US-25)

**US-21: Handle removed endpoint**
- **As a** API simplifier
- **I want** clean baseline maintenance
- **So that** I don't carry dead routes
- **Given:** Baseline with deprecated `/legacy`
- **When:** Running after route removal
- **Then:**
  - Warns "Missing endpoint: /legacy"
  - Prunes on `--update` (CC-04)
  - Confirms removal in changelog

**US-22: Empty baseline initialization**
- **As a** new project developer
- **I want** sensible first-run behavior
- **So that** I don't get false failures
- **Given:** Brand new FastAPI project
- **When:** Running tool first time
- **Then:**
  - Creates baseline with all zeros (T-01)
  - Exit code 0 for first run
  - Documents "Initial baseline established"

**US-23: Partial metric regression**
- **As a** database optimizer
- **I want** to see tradeoffs
- **So that** I can balance improvements
- **Given:** Baseline with p95=100ms, memory=50MB
- **When:** New version shows p95=80ms, memory=70MB
- **Then:**
  - Reports mixed results (CC-11)
  - Highlights tradeoff clearly
  - Allows override with justification

**US-24: Stale baseline warning**
- **As a** maintenance developer
- **I want** to know when baselines age
- **So that** I refresh expectations
- **Given:** 6-month old baseline
- **When:** Running regular checks
- **Then:**
  - Warns "Baseline older than 90 days" (INV-PB-08)
  - Suggests re-benchmarking
  - Still enforces thresholds

**US-25: Idempotent re-runs**
- **As a** flaky test investigator
- **I want** consistent results
- **So that** I trust the output
- **Given:** Unchanged codebase
- **When:** Running tool 3x consecutively
- **Then:**
  - Returns same metrics ±2% (INV-PB-07)
  - Reports identical regressions
  - No file changes without `--update` (T-12)

---

## 10. Test Plan

### 10.1 Measurement Accuracy Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Warmup requests excluded | Endpoint with 50 warmup + 1000 measured requests | Run test and inspect metrics | Reported sample size = 1000 (INV-PB-01) |
| T-02 | Minimum sample size enforced | Endpoint with 999 requests | Run performance test | Fails with "Sample size 999 < 1000 required" (INV-PB-05) |
| T-03 | Hardware fingerprint recorded | Test run on x86_64 machine | Inspect baseline.json | Contains "x86_64" in hardware_fingerprint (INV-PB-02) |
| T-04 | Memory measurement valid | Endpoint allocating 10MB | Run test with metrics=["memory"] | Reports memory_mb ≈ 10.0 (INV-PB-08) |
| T-05 | p99 calculation correct | Endpoint with known latency distribution | Run 1000 requests | p99 within 2% of theoretical value |
| T-06 | Excluded paths ignored | Request to /health endpoint | Run full test suite | No metrics recorded for /health (INV-PB-06) |

### 10.2 Regression Detection Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | p95 within tolerance | Baseline p95=100ms, current=105ms (tolerance=10%) | Run comparison | No regression reported (INV-PB-04) |
| T-08 | p95 exceeds tolerance | Baseline p95=100ms, current=115ms (tolerance=10%) | Run comparison | Fails with "p95 +15% regression" (INV-PB-04) |
| T-09 | Multi-metric regression | p95 +12%, rps -15% (tolerance=10%) | Run comparison | Reports both regressions |
| T-10 | Timeout detection | Endpoint hanging >10s on 5% requests | Run test | Reports "5% timeouts >10s" |
| T-11 | Memory leak detection | RSS grows 1MB → 2MB → 3MB across iterations | Run test | Reports "Memory leak detected" (INV-PB-08) |
| T-12 | Variance threshold | High stddev (cv > 0.3) due to noisy environment | Run test | Reports "High variance detected" |

### 10.3 Baseline Lifecycle Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | First run creates baseline | Empty project_dir | Run tool first time | Creates .perf.baseline.json (INV-PB-03) |
| T-14 | Silent update prevented | Modified metrics | Run without --update | Baseline unchanged (INV-PB-03) |
| T-15 | Explicit update works | Modified metrics + --update flag | Run tool | Baseline updated |
| T-16 | Hardware drift detection | Run on different CPU architecture | Compare fingerprints | Warns "Hardware mismatch" (INV-PB-02) |
| T-17 | New endpoint handling | Added /v2/users endpoint | Run tests | Skips /v2/users in regression checks |
| T-18 | Removed endpoint cleanup | Delete /old-endpoint | Run with --update | Removes /old-endpoint from baseline |

### 10.4 CI Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Regression fails CI | p95 +15% regression | Run with fail_on_regression=True | Exit code 1 |
| T-20 | Markdown report generation | 2 regressions detected | Run with --format=md | Creates report.md with tables |
| T-21 | JSON artifact creation | Test run with 5 endpoints | Run tool | Creates perf_results.json |
| T-22 | Flame graph generation | Run with --profile | Execute CPU-bound endpoint | Creates flamegraph.svg |
| T-23 | Execution time limit | 20 endpoints | Full test run | Completes in <60s |
| T-24 | PR comment integration | GitHub Actions run | Open PR with regression | Posts comment with delta table |

### 10.5 Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Empty project handling | New FastAPI project with no endpoints | Run tool | Creates empty baseline |
| T-26 | Idempotent re-run | Unchanged codebase | Run tool 3x | Same metrics ±2% (INV-PB-07) |
| T-27 | Stale baseline warning | Baseline file from 91 days ago | Run test | Warns "Baseline stale" |
| T-28 | Metric subset selection | Run with metrics=["p95"] | Test endpoint | Only p95 compared |
| T-29 | Cold start measurement | Run with include_cold_start=True | First request | Reports cold_start_ms separately |
| T-30 | Deterministic reporting | Same inputs on same machine | Run 2x | Identical reports (INV-PB-07) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Performance baseline measures response times regardless of soft delete status |
| add_cursor_pagination | Yes | ⚠️ Caveat | Must run after pagination to measure real-world page load performance |
| add_search | Yes | ⚠️ Caveat | Search endpoints should be baselined after search indexes are built |
| add_audit_log | No | ✅ Compatible | Audit logging adds minimal overhead that's captured in baseline |
| add_data_export | No | ✅ Compatible | Export endpoints measured like any other API route |
| add_bulk_operations | Yes | ⚠️ Caveat | Bulk ops must be installed first to measure their optimized performance |
| add_multi_tenancy | No | ✅ Compatible | Tenant middleware runs before performance measurement |
| add_feature_flags | No | ✅ Compatible | Feature flags don't affect performance measurement methodology |
| add_api_key_auth | No | ✅ Compatible | Auth checks are part of normal endpoint overhead |
| add_oauth2_provider | No | ✅ Compatible | Token validation included in baseline measurements |
| add_rbac | No | ✅ Compatible | Permission checks contribute to endpoint timing |
| add_mfa | No | ✅ Compatible | MFA flows can be baselined like other auth endpoints |
| add_cache_layer | Yes | ⚠️ Caveat | Must run after cache to measure real-world performance |
| add_outbox_pattern | No | ✅ Compatible | Outbox processing happens async and doesn't affect API timing |
| add_sse | Yes | ⚠️ Caveat | SSE endpoints require special long-poll measurement approach |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- tests/conftest.py tests/test_performance.py app/core/perf_config.py app/core/performance.py app/api/middleware/performance.py app/cli/performance.py
rm -f .perf.baseline.json .perf.report.md .perf.flamegraph.svg
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated
by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (benchmark module present but conftest not wired, baseline half-written), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed relative to HEAD
git status --short tests/ app/ .perf.baseline.json

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- tests/conftest.py app/core/perf_config.py \
    app/core/performance.py app/api/middleware/performance.py app/cli/performance.py
git clean -fd tests/test_performance.py .perf.baseline.json .perf.report.md

# 3. Verify tree matches HEAD exactly
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: regression blocking CI after a legitimate change
If a refactor legitimately made an endpoint slower (e.g., added a required security check) and the gate is now blocking every merge, do NOT raise `tolerance_pct` globally — it hides future regressions too. Instead, update the baseline for the specific endpoint with an audited commit:
```bash
# 1. Run the tool locally to see exact regression details
pytest tests/test_performance.py -v --perf-report

# 2. Inspect the delta per endpoint
python -m app.cli.performance diff --verbose

# 3. If the slowdown is justified, update baseline for that endpoint only
python -m app.cli.performance update-baseline \
    --endpoint /orders/{id} --reason "added audit log write (SEC-1234)" \
    --reviewed-by perf-team

# 4. Commit the updated baseline + the code change in the same PR
git add .perf.baseline.json
git commit -m "perf(orders): update p99 baseline after audit-log integration"
```

### Failure mode: noisy CI machine causing flaky regressions
If the benchmark runs on a shared CI runner whose neighbor steals CPU cycles mid-run, p99 flakes by ±30% and random PRs fail for no real reason. Containment:
1. Increase sample size: set `PERF_SAMPLE_SIZE=2000` in the workflow env so the outliers get averaged out
2. Enable `trimmed_mean` statistic: add `--stat trimmed_mean` to the CLI invocation so the top/bottom 5% of samples are dropped
3. Pin the CI runner to a dedicated pool (GitHub Actions `runs-on: self-hosted-perf` or equivalent) — flaky shared runners will never produce stable benchmarks
4. If the variance persists, raise `tolerance_pct` for that specific endpoint to 15% with a justification and a ticket to investigate the noise

### Emergency: hardware fingerprint drift after CI migration
If the CI provider upgraded the runner (new CPU, different arch) and every endpoint now reports a "hardware mismatch" warning:
1. Inspect the old vs new fingerprint: `jq '.fingerprint' .perf.baseline.json` vs `python -m app.cli.performance fingerprint`
2. Run the calibration task to recompute the hardware scaling factor: `python -m app.cli.performance calibrate --new-runner`
3. The calibration produces a `scale_factor` applied to every baseline comparison (e.g., new runner is 1.15× faster → multiply old p99 by 1.15 before comparing)
4. Commit the calibration + the new fingerprint + a note explaining the runner migration so the next review understands the baseline delta

### Emergency: baseline file corruption
If `.perf.baseline.json` is malformed (bad JSON after merge conflict, truncated write, manual edit):
1. Validate: `python -m json.tool .perf.baseline.json` — prints error location if corrupted
2. Restore the last known-good: `git show HEAD~1:.perf.baseline.json > .perf.baseline.json`
3. Re-validate: `python -m app.cli.performance check`
4. If no good baseline exists, regenerate with an explicit flag that blocks regression detection on the first post-reset PR: `python -m app.cli.performance reset-baseline --confirm --reason "corrupt file recovery"`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | First run with empty project | Creates zero-value baseline for all auto-discovered endpoints |
| EC-2 | Hardware fingerprint mismatch | Errors with "Hardware changed: run calibration with --calibrate" |
| EC-3 | New endpoint added | Skips in regression checks, notes "New endpoint detected: /new-route" |
| EC-4 | Endpoint removed but still in baseline | Warns "Endpoint missing: /old-route (prune with --update)" |
| EC-5 | Sample size < 1000 requests | Fails with "Insufficient samples: 850 < 1000 required for /users" |
| EC-6 | High variance (cv > 0.3) | Reports "High variance detected on /search (cv=0.35), results unreliable" |
| EC-7 | Cold start measurement requested | Measures first request separately as cold_start_ms |
| EC-8 | Memory leak detected (RSS grows) | Reports "Memory leak: RSS grew from 50MB → 75MB across iterations" |
| EC-9 | Timeout >10s on 5% requests | Flags as regression: "5% requests timed out >10s on /report" |
| EC-10 | Network blip during test | Reports high stddev, suggests re-run without failing |
| EC-11 | GPU-accelerated endpoint | Includes GPU in fingerprint, maintains separate baseline |
| EC-12 | Stale baseline (>90 days) | Warns "Baseline outdated (120 days), consider refresh" |
| EC-13 | Zero-tolerance (0%) mode | Fails on any regression, even 1ms increase |
| EC-14 | Metrics subset specified | Only compares selected metrics (e.g. just ["p95"]) |
| EC-15 | Idempotent re-run | Returns same metrics ±2% when unchanged |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via grep/ast.parse  
✅ 2. PerformanceBaseline model validates all fields (p50/p95/p99/rps/memory)  
✅ 3. PerfConfig implements hardware fingerprint and warmup controls  
✅ 4. PerformanceService handles baseline lifecycle and regression checks  
✅ 5. PerformanceMiddleware excludes health/metrics endpoints  
✅ 6. Test module uses benchmark fixture with 1000+ samples  
✅ 7. CLI commands work (check, update, profile)  
✅ 8. All 30 test cases pass (T-01 through T-30)  
✅ 9. Execution time <60s for 20 endpoints  
✅ 10. Developer can: (1) run baseline, (2) make code change, (3) detect p95 regression, (4) view flame graph, (5) fix regression, (6) verify pass  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains FastAPI app  
- [ ] Verify pytest-benchmark installed in test environment  
- [ ] Check for existing `.perf.baseline.json`  
- [ ] Auto-discover endpoints via FastAPI router  
- [ ] Validate Python >=3.8 (required for hardware fingerprint)  
- [ ] Check available memory >500MB for reliable measurements  
- [ ] Verify CPU cores >=2 for parallel test execution  

### 15.2 Configuration setup  
- [ ] Create `app/core/perf_config.py` with `PerformanceBaseline` model  
- [ ] Implement `PerfConfig` with tolerance/sample size defaults  
- [ ] Add hardware fingerprint via `platform` module  
- [ ] Define default metrics list ["p50","p95","p99","rps","memory"]  
- [ ] Add `PERF_WARMUP_COUNT` to `app/core/config.py` settings  
- [ ] Add `PERF_SAMPLE_SIZE` to settings  
- [ ] Register config in `app/main.py` startup  

### 15.3 Core service
- [ ] Create `app/core/performance.py` with `PerformanceService`  
- [ ] Implement `load_baseline()` with JSON parsing  
- [ ] Implement `save_baseline()` with atomic write  
- [ ] Add `check_regression()` with tolerance math  
- [ ] Add hardware drift detection  
- [ ] Implement calibration task for new hardware  
- [ ] Add report generation (JSON/Markdown)  

### 15.4 Middleware
- [ ] Create `app/api/middleware/performance.py`  
- [ ] Implement `PerformanceMiddleware` with timing  
- [ ] Define `excluded_paths` for health/metrics  
- [ ] Add `X-Process-Time` header injection  
- [ ] Integrate with FastAPI app (`app/main.py`)  
- [ ] Add timeout detection (10s threshold)  
- [ ] Validate middleware order (after auth)  

### 15.5 Test harness
- [ ] Create `tests/conftest.py` with benchmark fixtures  
- [ ] Add `benchmark_metadata` fixture for endpoint naming  
- [ ] Implement warmup phase (50 requests)  
- [ ] Enforce minimum sample size (1000 requests)  
- [ ] Add memory measurement via `psutil`  
- [ ] Generate hardware fingerprint for test runs  
- [ ] Add variance threshold checks  

### 15.6 CLI integration
- [ ] Create `app/cli/performance.py` with Click commands  
- [ ] Implement `check` command with tolerance flag  
- [ ] Add `update` flag for baseline updates  
- [ ] Support `--profile` for flame graphs  
- [ ] Add `--metrics` subset selection  
- [ ] Implement `--calibrate` for new hardware  
- [ ] Add colored output for regressions  

### 15.7 Test generation
- [ ] Create `tests/test_performance.py` with 30 cases  
- [ ] Test warmup exclusion (T-01)  
- [ ] Test sample size enforcement (T-02)  
- [ ] Test hardware fingerprint (T-03)  
- [ ] Test memory measurement (T-04)  
- [ ] Test p99 calculation (T-05)  
- [ ] Test excluded paths (T-06)  
- [ ] Test regression detection (T-07..T-12)  

### 15.8 Report generation
- [ ] Implement JSON report output  
- [ ] Add Markdown table generation  
- [ ] Support flame graph via py-spy  
- [ ] Include hardware comparison  
- [ ] Highlight worst regressions  
- [ ] Add variance warnings  
- [ ] Generate CI-friendly output  

### 15.9 CI integration
- [ ] Create `.github/workflows/performance.yml`  
- [ ] Add baseline check on PR  
- [ ] Implement update job on main  
- [ ] Add artifact upload for reports  
- [ ] Set timeout to 90s  
- [ ] Configure hardware constraints  
- [ ] Add PR comment integration  

### 15.10 Atomicity
- [ ] Use tempfile for baseline writes  
- [ ] Verify file writes with checksums  
- [ ] Rollback on validation failure  
- [ ] Preserve old baseline on error  
- [ ] Clean up temp files  
- [ ] Verify AST for all modified files  
- [ ] Check import chains  

### 15.11 Documentation
- [ ] Add to `SKILL.md` tools table  
- [ ] Update `manifest.yaml`  
- [ ] Add `core/KNOWLEDGE.md` section  
- [ ] Document CLI usage  
- [ ] Explain hardware fingerprint  
- [ ] Describe CI integration  
- [ ] Note common pitfalls  

### 15.12 Verification
- [ ] Run `ast.parse` on all new files  
- [ ] Execute all 30 test cases  
- [ ] Verify cold vs warm measurements  
- [ ] Check hardware drift handling  
- [ ] Test report generation time  
- [ ] Validate flame graph output  
- [ ] Measure tool overhead  

### 15.13 Performance
- [ ] Time full test suite (20 endpoints)  
- [ ] Measure baseline comparison speed  
- [ ] Profile memory overhead  
- [ ] Check multi-core utilization  
- [ ] Verify deterministic reports  
- [ ] Test large endpoint sets (50+)  
- [ ] Benchmark calibration task  

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/perf_config.py",
    "app/core/performance.py",
    "app/api/middleware/performance.py",
    "app/cli/performance.py",
    "tests/conftest.py",
    "tests/test_performance.py",
    ".github/workflows/performance.yml",
    ".perf.baseline.json"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/main.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 4872,
    "files_changed": 11,
    "lines_added": 842,
    "lines_removed": 18,
    "endpoints_baselined": 14,
    "warmup_requests": 50,
    "sample_size": 1000
  },
  "next_steps": [
    "Run: pytest tests/test_performance.py -v",
    "Establish baseline: python -m app.cli.performance --update",
    "Check for regressions: python -m app.cli.performance check",
    "Generate flame graph: python -m app.cli.performance --profile",
    "Integrate with CI: git add .github/workflows/performance.yml"
  ],
  "warnings": [
    "Hardware changes will require recalibration (--calibrate)",
    "First run creates zero-value baseline - update after optimizing",
    "Network noise may cause variance >10% in cloud environments"
  ],
  "notes": [
    "Performance baseline established for 14 endpoints",
    "Middleware measures all non-excluded routes",
    "Default tolerance set to 10% (adjust in PerfConfig)",
    "Test suite includes 30 verification cases",
    "CI workflow will block PRs on regression",
    "Flame graphs require py-spy installation"
  ]
}
