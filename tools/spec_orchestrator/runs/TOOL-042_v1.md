<!--
{
  "tool_num": "042",
  "tool_name": "sla_reporter",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 1181.5970711510163,
  "prompt_tokens": 45972,
  "completion_tokens": 11246,
  "cost_usd": 0.045285870000000006,
  "calls": 6
}
-->

# TOOL-042: sla_reporter

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_sla_reporter` |
| Category | OPERATE > Monitoring |
| Complexity | High |
| Dependencies | FastAPI, Prometheus, optional Grafana |
| Signature | `sla_reporter(project_dir: str, sla_config_file: str = "sla.yaml", report_period: str = "month", p99_budget_ms: int = 500, availability_target_pct: float = 99.9, output_format: str = "pdf") -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/app/prod-api`)<br>`sla_config_file`: YAML path relative to project_dir defining per-endpoint SLOs (default: `config/sla.yaml`)<br>`report_period`: Reporting interval (`day`/`week`/`month`/`quarter`)<br>`p99_budget_ms`: Default latency threshold (500ms)<br>`availability_target_pct`: Default uptime target (99.9%)<br>`output_format`: Report format (`pdf`/`markdown`/`html`/`json`) |

## 2. Purpose

The `fastapi_sla_reporter` generates auditable Service Level Agreement (SLA) compliance reports from Prometheus metrics, calculating uptime percentages, latency distributions (p50/p95/p99), and error-budget consumption against per-endpoint targets defined in `sla.yaml`. Without this tool, teams manually query dashboards and spreadsheet calculations for contractual SLA verification, risking inconsistencies and audit failures. The tool integrates as a FastAPI middleware that periodically exports metrics to Prometheus, then generates branded PDF/Markdown reports with traffic-light status indicators per SLO. Key design decisions include Google SRE-style error budget calculations with 1h/6h/24h burn rate windows, deterministic report generation tied to git SHAs, and strict separation between observed metrics (Prometheus) and policy targets (YAML). Reports support multiple stakeholder needs: daily engineering reviews focus on burn rates, while quarterly executive summaries highlight trend analysis.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Report generation time | < 10s for 30 days of data | Must complete within CI pipeline timeout windows |
| Modified files | ≤ 2 (pyproject.toml + CI workflow) | Minimize project footprint |
| Created files | ≥ 8 (module, config, templates, tests) | Complete installation requires all assets |
| Prometheus query latency | < 2s per endpoint | Avoid report generation delays |
| PDF rendering time | < 5s for 50-page report | User experience requirement |
| Memory overhead | < 100MB during generation | Must run on CI worker nodes |
| Migration runtime | 0s — no DB changes | Pure reporting tool with no schema |
| Burn rate calculation | < 500ms per window | Complex math must remain performant |
| Incident linkage | < 1s per alert query | Fast correlation with Alertmanager/Sentry |

---

## 4. Code Examples (Before / After)

### 4.1 SLA Config Model: BEFORE
```python
# app/models/sla_config.py
from typing import Optional
from pydantic import BaseModel, Field


class SLATarget(BaseModel):
    path: str
    availability_pct: Optional[float] = None
    p99_ms: Optional[int] = None
    error_budget_window: Optional[str] = None
```

### 4.2 SLA Config Model: AFTER
```python
# app/models/sla_config.py
from typing import Optional
from pydantic import BaseModel, Field, validator


class SLATarget(BaseModel):
    path: str = Field(..., min_length=1, max_length=255)
    availability_pct: Optional[float] = Field(None, ge=90.0, le=100.0)
    p99_ms: Optional[int] = Field(None, gt=0)
    error_budget_window: Optional[str] = Field(None, regex="^\d+[hdwm]$")

    @validator("availability_pct")
    def validate_availability(cls, v):
        if v is not None and v < 90.0:
            raise ValueError("Availability must be >= 90%")
        return v

    @validator("p99_ms")
    def validate_p99(cls, v):
        if v is not None and v > 10000:
            raise ValueError("p99 latency must be <= 10s")
        return v
```

### 4.3 Prometheus Metrics Client (NEW)
```python
# app/core/prometheus_client.py
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from prometheus_api_client import PrometheusConnect
from fastapi import HTTPException


class PrometheusMetricsClient:
    def __init__(self, url: str, timeout: int = 10):
        self.client = PrometheusConnect(url=url, timeout=timeout)

    async def get_availability(self, path: str, start: datetime, end: datetime) -> float:
        query = f'sum(rate(http_requests_total{{path="{path}",status=~"5.."}}[1m])) / sum(rate(http_requests_total{{path="{path}"}}[1m]))'
        try:
            result = self.client.custom_query(query, start, end)
            return 1 - float(result[0]["value"][1])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Prometheus query failed: {str(e)}")

    async def get_latency_percentiles(self, path: str, start: datetime, end: datetime) -> Dict[str, float]:
        queries = {
            "p50": f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{path="{path}"}}[1m])) by (le))',
            "p95": f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{path="{path}"}}[1m])) by (le))',
            "p99": f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{path="{path}"}}[1m])) by (le))'
        }
        try:
            results = {}
            for percentile, query in queries.items():
                result = self.client.custom_query(query, start, end)
                results[percentile] = float(result[0]["value"][1])
            return results
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Prometheus query failed: {str(e)}")
```

### 4.4 SLA Report Service (NEW)
```python
# app/services/sla_report_service.py
from datetime import datetime, timedelta
from typing import Dict, List
from app.models.sla_config import SLATarget
from app.core.prometheus_client import PrometheusMetricsClient


class SLAReportService:
    def __init__(self, prometheus_url: str):
        self.client = PrometheusMetricsClient(prometheus_url)

    async def generate_report(self, targets: List[SLATarget], start: datetime, end: datetime) -> Dict:
        report = {}
        for target in targets:
            availability = await self.client.get_availability(target.path, start, end)
            latency = await self.client.get_latency_percentiles(target.path, start, end)
            report[target.path] = {
                "availability": availability,
                "latency": latency,
                "status": self._calculate_status(target, availability, latency["p99"]),
                "error_budget": self._calculate_error_budget(target, availability, start, end),
            }
        return report

    def _calculate_status(self, target: SLATarget, availability: float, p99: float) -> str:
        if availability < target.availability_pct or p99 > target.p99_ms:
            return "red"
        return "green"

    def _calculate_error_budget(self, target: SLATarget, availability: float, start: datetime, end: datetime) -> float:
        total_seconds = (end - start).total_seconds()
        error_budget = (1 - target.availability_pct) * total_seconds
        return error_budget
```

### 4.5 SLA Report Route (NEW)
```python
# app/api/endpoints/sla_report.py
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from app.services.sla_report_service import SLAReportService
from app.models.sla_config import SLATarget
from app.core.config import settings
from typing import List


router = APIRouter(prefix="/sla-reports", tags=["sla-reports"])


@router.post("/generate")
async def generate_report(
    targets: List[SLATarget],
    period: str = "month",
    report_service: SLAReportService = Depends(lambda: SLAReportService(settings.PROMETHEUS_URL))
):
    if period not in ["day", "week", "month", "quarter"]:
        raise HTTPException(status_code=400, detail="Invalid period. Must be day, week, month, or quarter")
    
    end = datetime.utcnow()
    if period == "day":
        start = end - timedelta(days=1)
    elif period == "week":
        start = end - timedelta(weeks=1)
    elif period == "month":
        start = end - timedelta(days=30)
    else:
        start = end - timedelta(days=90)
    
    try:
        report = await report_service.generate_report(targets, start, end)
        return {
            "report": report,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 4.6 SLA Report Migration (NEW)
```python
# alembic/versions/0001_add_sla_report_tables.py
"""add sla report tables

Revision ID: 0001
Revises: 
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "sla_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("report_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_sla_reports_period", "sla_reports", ["period_start", "period_end"])
    op.create_index("ix_sla_reports_created", "sla_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sla_reports_created", table_name="sla_reports")
    op.drop_index("ix_sla_reports_period", table_name="sla_reports")
    op.drop_table("sla_reports")
```

### 4.7 Report Rendering Service (NEW)
```python
# app/services/report_renderer.py
from typing import Dict
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML


class ReportRenderer:
    def __init__(self, template_dir: str = "templates"):
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def render_pdf(self, report_data: Dict, template_name: str = "report.html") -> bytes:
        template = self.env.get_template(template_name)
        html = template.render(report=report_data)
        pdf = HTML(string=html).write_pdf()
        return pdf

    def render_html(self, report_data: Dict, template_name: str = "report.html") -> str:
        template = self.env.get_template(template_name)
        return template.render(report=report_data)

    def render_markdown(self, report_data: Dict) -> str:
        markdown = f"# SLA Report\n\n"
        for path, metrics in report_data.items():
            markdown += f"## {path}\n"
            markdown += f"- Availability: {metrics['availability']:.2f}%\n"
            markdown += f"- p99 Latency: {metrics['latency']['p99']:.2f}ms\n"
            markdown += f"- Status: {metrics['status']}\n\n"
        return markdown
```

### 4.8 Report Configuration (NEW)
```python
# app/core/config.py
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    PROMETHEUS_URL: str = Field("http://localhost:9090", env="PROMETHEUS_URL")
    REPORT_TEMPLATE_DIR: str = Field("templates", env="REPORT_TEMPLATE_DIR")
    REPORT_OUTPUT_DIR: str = Field("/var/www/reports", env="REPORT_OUTPUT_DIR")
    DEFAULT_REPORT_PERIOD: str = Field("month", env="DEFAULT_REPORT_PERIOD")
    TIMEZONE: str = Field("UTC", env="TIMEZONE")

    class Config:
        env_file = ".env"


settings = Settings()
```

### 4.9 Report CLI (NEW)
```python
# app/cli/report.py
import click
from datetime import datetime, timedelta
from app.services.sla_report_service import SLAReportService
from app.services.report_renderer import ReportRenderer
from app.core.config import settings
from typing import List


@click.command()
@click.option("--period", default="month", help="Report period (day, week, month, quarter)")
@click.option("--output", default="pdf", help="Output format (pdf, html, markdown)")
def generate_report(period: str, output: str):
    """Generate SLA report for specified period"""
    report_service = SLAReportService(settings.PROMETHEUS_URL)
    renderer = ReportRenderer(settings.REPORT_TEMPLATE_DIR)
    
    end = datetime.utcnow()
    if period == "day":
        start = end - timedelta(days=1)
    elif period == "week":
        start = end - timedelta(weeks=1)
    elif period == "month":
        start = end - timedelta(days=30)
    else:
        start = end - timedelta(days=90)
    
    # TODO: Load targets from config
    targets = [
        {"path": "/api/orders", "availability_pct": 99.95, "p99_ms": 300},
        {"path": "/api/products", "availability_pct": 99.9, "p99_ms": 500},
    ]
    
    report = report_service.generate_report(targets, start, end)
    
    if output == "pdf":
        pdf = renderer.render_pdf(report)
        with open(f"{settings.REPORT_OUTPUT_DIR}/report.pdf", "wb") as f:
            f.write(pdf)
    elif output == "html":
        html = renderer.render_html(report)
        with open(f"{settings.REPORT_OUTPUT_DIR}/report.html", "w") as f:
            f.write(html)
    else:
        markdown = renderer.render_markdown(report)
        with open(f"{settings.REPORT_OUTPUT_DIR}/report.md", "w") as f:
            f.write(markdown)
    
    click.echo(f"Report generated successfully: {settings.REPORT_OUTPUT_DIR}/report.{output}")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Report generation is deterministic** | `ReportGenerator` class in `app/core/generator.py` hashes input metrics + config to produce identical output for same inputs |
| QS-2 | **All calculations use bounded time windows** | `PrometheusClient` in `app/core/prometheus.py` enforces max 30d range with `end_time - start_time <= timedelta(days=30)` validation |
| QS-3 | **Error budget calculations follow Google SRE methodology** | `ErrorBudgetCalculator` in `app/core/calculator.py` implements multi-window burn rates (1h/6h/24h) with 95% confidence intervals |
| QS-4 | **PDF reports include cryptographic signatures** | `PDFSigner` in `app/core/signing.py` embeds SHA-256 hash of source data + generation timestamp |
| QS-5 | **YAML config validation rejects invalid targets** | `SLATarget` model in `app/models/sla.py` validates `availability_pct >= 90.0` and `p99_ms > 0` via Pydantic validators |
| QS-6 | **Prometheus queries are always rate-limited** | `PrometheusClient.execute_query()` in `app/core/prometheus.py` uses token bucket rate limiter (10 req/sec) |
| QS-7 | **HTML reports are XSS-safe by design** | `HTMLRenderer` in `app/core/renderers.py` escapes all dynamic content via Jinja2 autoescape |
| QS-8 | **All numerical calculations use decimal precision** | `Decimal` type used throughout `app/core/calculator.py` with context precision set to 6 decimal places |
| QS-9 | **Report generation is idempotent** | `ReportService.generate()` in `app/services/report.py` checks for existing report hash before regeneration |
| QS-10 | **Time zones are explicitly UTC unless configured** | `DateTimeHelper` in `app/core/datetime.py` converts all timestamps to UTC before processing |
| QS-11 | **Configuration overrides are strictly typed** | `ConfigLoader` in `app/core/config.py` uses Pydantic BaseSettings with env var prefixes |
| QS-12 | **All external dependencies are pinned** | `pyproject.toml` specifies exact versions with poetry lockfile verification in CI |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `SLATarget` model exists at `app/models/sla.py` | File exists, parses |
| CC-02 | `PrometheusClient` exists at `app/core/prometheus.py` | File exists, contains rate limiting |
| CC-03 | `ErrorBudgetCalculator` exists at `app/core/calculator.py` | File exists, implements multi-window burn |
| CC-04 | Report templates exist in `app/templates/reports/` | Directory contains PDF/HTML/Markdown templates |
| CC-05 | `ReportGenerator` class exists at `app/core/generator.py` | File exists, contains hash generation |
| CC-06 | CLI entrypoint exists at `app/cli.py` | File exists, handles argument parsing |
| CC-07 | PDF signing implemented in `app/core/signing.py` | File exists, generates SHA-256 hashes |
| CC-08 | Configuration loader supports env vars in `app/core/config.py` | File exists, uses Pydantic BaseSettings |
| CC-09 | Example `sla.yaml` exists in project root | File exists, contains valid example config |
| CC-10 | CI workflow exists at `.github/workflows/sla-reports.yml` | File exists, schedules monthly runs |
| CC-11 | PDF renderer uses WeasyPrint or ReportLab | Inspect `app/core/renderers.py` |
| CC-12 | HTML templates use Jinja2 with autoescape | Inspect `app/templates/reports/html/` |
| CC-13 | Markdown output follows CommonMark spec | Inspect `app/core/renderers.py` |
| CC-14 | JSON output follows JSON Schema spec | Inspect `app/schemas/report.json` |
| CC-15 | All calculations use Decimal precision | grep `Decimal` in `app/core/calculator.py` |
| CC-16 | Timezone handling defaults to UTC | Inspect `app/core/datetime.py` |
| CC-17 | Prometheus queries are rate-limited | grep `TokenBucket` in `app/core/prometheus.py` |
| CC-18 | Report generation is deterministic | Test identical inputs produce identical outputs (T-01) |
| CC-19 | Error budget calculations match SRE book | Compare `app/core/calculator.py` to Google SRE workbook (T-07) |
| CC-20 | Configuration validation rejects invalid values | Test invalid `sla.yaml` raises ValidationError (T-13) |
| CC-21 | PDF reports include cryptographic signatures | Inspect output PDF metadata (T-19) |
| CC-22 | HTML output is XSS-safe | Test script injection attempts (T-25) |
| CC-23 | CLI supports all output formats | Test `--output-format` with all options (T-02) |
| CC-24 | CI workflow uploads to S3 | Inspect `.github/workflows/sla-reports.yml` |
| CC-25 | Report service checks for existing hashes | grep `report_exists` in `app/services/report.py` |
| CC-26 | Dependencies are strictly pinned | Inspect `pyproject.toml` and `poetry.lock` |
| CC-27 | Multi-window burn rates implemented | Inspect `app/core/calculator.py` for 1h/6h/24h windows |
| CC-28 | Incident linking queries Alertmanager/Sentry | grep `query_incidents` in `app/core/prometheus.py` |
| CC-29 | Maintenance windows excluded from calculations | Inspect `app/core/datetime.py` for exclusion logic |
| CC-30 | Test coverage ≥ 90% for new code | pytest --cov report |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] PDF/HTML/Markdown/JSON output formats implemented
- [ ] Example `sla.yaml` included in project root
- [ ] CLI supports all required arguments
- [ ] CI workflow scheduled and tested
- [ ] Cryptographic signing implemented for PDFs
- [ ] Multi-window burn rate calculations match SRE spec
- [ ] XSS protection verified for HTML output
- [ ] Timezone handling defaults to UTC
- [ ] Prometheus query rate limiting implemented
- [ ] Configuration validation rejects invalid values
- [ ] Deterministic report generation verified
- [ ] Test coverage ≥ 90% for new code

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SL-01 | Report generation is ALWAYS deterministic | `ReportGenerator` in `app/core/generator.py` hashes all inputs before processing | T-01 |
| INV-SL-02 | Error budgets are NEVER calculated cumulatively | `ErrorBudgetCalculator` in `app/core/calculator.py` uses strict time-windowed calculations | T-07 |
| INV-SL-03 | Prometheus queries are ALWAYS rate-limited | `TokenBucket` rate limiter in `app/core/prometheus.py` enforces 10 req/sec | T-13 |
| INV-SL-04 | PDF reports ALWAYS include cryptographic signatures | `PDFSigner` in `app/core/signing.py` embeds SHA-256 hash in metadata | T-19 |
| INV-SL-05 | Configuration ALWAYS validated before use | `ConfigLoader` in `app/core/config.py` uses Pydantic validation | T-25 |
| INV-SL-06 | HTML output is ALWAYS XSS-safe | Jinja2 autoescape enabled in `app/core/renderers.py` with no unsafe exceptions | T-02 |
| INV-SL-07 | Time zones are ALWAYS UTC unless explicitly configured | `DateTimeHelper` in `app/core/datetime.py` converts all timestamps to UTC | T-08 |
| INV-SL-08 | Incident linking NEVER invents fictional events | `IncidentLinker` in `app/core/incidents.py` only includes alerts from Alertmanager/Sentry | T-14 |

---

## 9. User Stories

### 9.1 Core report generation (US-01 .. US-05)

**US-01: Generate monthly PDF report**
- **As a** engineering manager
- **I want** a monthly SLA compliance report in PDF format
- **So that** I can share it with executive stakeholders
- **Given:** Prometheus metrics for `/api/orders` endpoint with 99.2% availability
- **When:** I call `sla_reporter("/app/prod-api", report_period="month", output_format="pdf")`
- **Then:**
  - Report shows red status for `/api/orders` (INV-SL-01)
  - PDF includes cryptographic signature in metadata (CC-07)
  - File saved to `/app/prod-api/reports/sla-2026-04.pdf`

**US-02: Weekly markdown report for engineering**
- **As a** site reliability engineer
- **I want** a weekly markdown report with burn rates
- **So that** I can review error budget consumption
- **Given:** 6h burn rate of 3.2 for `/api/users`
- **When:** Tool runs with `report_period="week"` and `output_format="markdown"`
- **Then:**
  - Report shows "Critical" status for 6h window (INV-SL-02)
  - Markdown file follows CommonMark spec (CC-13)
  - File saved to `/app/prod-api/reports/sla-weekly-2026w15.md`

**US-03: Daily HTML report with charts**
- **As a** frontend engineer
- **I want** an interactive HTML report with latency charts
- **So that** I can visualize performance trends
- **Given:** Prometheus metrics with p99 spikes at 08:00 UTC
- **When:** Generating report with `output_format="html"`
- **Then:**
  - HTML contains Plotly SVG charts of latency (CC-12)
  - All dynamic content is XSS-safe (INV-SL-06)
  - File saved to `/app/prod-api/reports/daily-2026-04-08.html`

**US-04: Quarterly executive summary**
- **As a** CTO
- **I want** a high-level quarterly summary
- **So that** I can review annual SLO trends
- **Given:** 3 months of historical reports
- **When:** Running with `report_period="quarter"`
- **Then:**
  - Report shows quarterly availability trend chart (T-19)
  - Includes narrative summary of major incidents (CC-28)
  - PDF generated in < 5s (CC-11)

**US-05: Empty period handling**
- **As a** developer testing new endpoint
- **I want** clear reporting for endpoints with no traffic
- **So that** I can distinguish between downtime and new deployments
- **Given:** `/api/new` endpoint with zero requests
- **When:** Generating report with default targets
- **Then:**
  - Report shows "No traffic" status for `/api/new` (T-25)
  - Availability calculated as 100% (INV-SL-02)
  - No Prometheus queries executed for empty endpoints (INV-SL-03)

### 9.2 SLA configuration (US-06 .. US-10)

**US-06: Custom per-endpoint SLOs**
- **As a** API product owner
- **I want** to set stricter SLOs for checkout endpoints
- **So that** critical paths have higher reliability
- **Given:** `sla.yaml` with `/api/checkout` target of 99.99%
- **When:** Report includes checkout endpoint metrics
- **Then:**
  - Custom target overrides default 99.9% (CC-01)
  - Validation ensures 99.99% ≥ 90% minimum (INV-SL-05)
  - Report highlights checkout as "Key Endpoint"

**US-07: Default targets for new endpoints**
- **As a** platform engineer
- **I want** new endpoints to inherit default SLOs
- **So that** I don't need to update YAML for every deployment
- **Given:** New `/api/search` endpoint with no SLA config
- **When:** Generating report with `p99_budget_ms=300`
- **Then:**
  - Report uses 300ms p99 target for `/api/search` (CC-09)
  - Availability defaults to 99.9% (INV-SL-05)
  - YAML remains clean without boilerplate

**US-08: Reject invalid window format**
- **As a** DevOps engineer
- **I want** config validation to catch typos
- **So that** error budgets calculate correctly
- **Given:** `error_budget_window: "30days"` (invalid)
- **When:** Loading `sla.yaml` config
- **Then:**
  - Pydantic raises ValidationError (CC-20)
  - Error specifies valid formats ("30d", "1w", etc) (INV-SL-05)
  - Report generation aborts before queries

**US-09: Maintenance window exclusion**
- **As a** release manager
- **I want** planned downtime excluded from SLA calcs
- **So that** maintenance doesn't consume error budget
- **Given:** 2h maintenance window in `sla.yaml`
- **When:** Report period includes maintenance
- **Then:**
  - Metrics from maintenance window excluded (CC-29)
  - Report footnotes the exclusion (T-07)
  - Availability calculated only on active hours

**US-10: Environment-specific overrides**
- **As a** QA engineer
- **I want** lower SLOs in staging
- **So that** I can test failure scenarios
- **Given:`STAGING_MODE=true` env var
- **When:** Loading SLA config
- **Then:**
  - Targets automatically relaxed to 95% availability (CC-08)
  - Report watermarked "STAGING" (CC-11)
  - Production SLOs remain unchanged (INV-SL-04)

### 9.3 Error budget calculations (US-11 .. US-15)

**US-11: Calculate multi-window burn rates**
- **As a** SRE on call
- **I want** to see 1h/6h/24h burn rates
- **So that** I can assess incident severity
- **Given:** API outage from 09:00-09:45 UTC
- **When:** Generating report at 10:00 UTC
- **Then:**
  - 1h window shows "Critical" (burn rate > 1) (INV-SL-02)
  - 24h window shows "Healthy" (CC-27)
  - Report highlights conflicting windows (T-07)

**US-12: Budget exhaustion detection**
- **As a** incident commander
- **I want** clear visual indication of exhausted budget
- **So that** I can escalate appropriately
- **Given:`/api/payments` with 0% remaining budget
- **When:** Reviewing PDF report
- **Then:**
  - Endpoint marked with red "EXHAUSTED" banner (CC-05)
  - Narrative suggests freeze on deployments (CC-28)
  - Historical burn rate chart included (INV-SL-01)

**US-13: Near-miss detection**
- **As a** engineering lead
- **I want** warnings when approaching budget limits
- **So that** we can proactively improve reliability
- **Given:`/api/inventory` with 15% budget remaining
- **When:** Generating weekly report
- **Then:**
  - Endpoint marked yellow "AT RISK" (CC-03)
  - Report suggests mitigation strategies (CC-28)
  - Burn rate trend arrows show acceleration (T-19)

**US-14: Partial period calculation**
- **As a** developer rolling out new features
- **I want** accurate SLOs for endpoints added mid-period
- **So that** new functionality gets fair assessment
- **Given:`/api/reviews` deployed on April 15
- **When:** Generating monthly report
- **Then:**
  - Availability calculated only from April 15-30 (INV-SL-02)
  - Report footnotes "Partial month" (CC-05)
  - Targets not prorated (full-month expectations)

**US-15: Holiday traffic exclusion**
- **As a** retail platform owner
- **I want** Black Friday excluded from normal SLOs
- **So that** seasonal spikes don't distort metrics
- **Given:`holidays: ["2026-11-27"]` in sla.yaml
- **When:** Generating November report
- **Then:**
  - Black Friday metrics excluded (CC-29)
  - Separate holiday report generated (CC-24)
  - Main report indicates exclusion (INV-SL-07)

### 9.4 Incident integration (US-16 .. US-20)

**US-16: Link Prometheus alerts**
- **As a** incident responder
- **I want** to see which alerts fired during outages
- **So that** I can correlate with error budget
- **Given:`HighErrorRate` alert fired at 2026-04-01T14:22Z
- **When:** Reviewing April report
- **Then:**
  - Alert appears in incident timeline (CC-28)
  - Burn rate spike aligns with alert time (INV-SL-08)
  - Alertmanager query takes <1s (CC-17)

**US-17: Sentry exception linkage**
- **As a** backend developer
- **I want** to see exception spikes in SLA context
- **So that** I can prioritize fixes
- **Given:`PaymentGatewayTimeout` exceptions on April 5
- **When:** Generating weekly report
- **Then:**
  - Sentry events appear in narrative section (CC-28)
  - Error rate correlates with exception count (INV-SL-08)
  - Report links to Sentry issue (CC-05)

**US-18: Maintenance incident exclusion**
- **As a** infrastructure engineer
- **I want** planned database maintenance excluded
- **So that** we don't get false SLO violations
- **Given:`DB_MAINTENANCE=2026-04-10T01:00,2026-04-10T03:00`
- **When:** Generating report
- **Then:**
  - 2h window excluded from availability (CC-29)
  - Report shows maintenance as gray bar (T-19)
  - Raw metrics still available in JSON export (CC-14)

**US-19: Annotate incidents with RCA**
- **As a** postmortem author
- **I want** to attach root cause analysis
- **So that** reports show improvement actions
- **Given:`sla.yaml` with `rca: "Load balancer config error"`
- **When:** Viewing incident in HTML report
- **Then:**
  - RCA appears in timeline (CC-28)
  - PDF includes "Lessons Learned" section (CC-05)
  - JSON export contains raw RCA text (CC-14)

**US-20: Multi-team incident attribution**
- **As a** engineering director
- **I want** to split error budget impact by team
- **So that** accountability is clear
- **Given:`teams: [frontend, backend]` in incident config
- **When:** Reviewing quarterly report
- **Then:**
  - Budget consumption split 60/40 in pie chart (CC-03)
  - Each team's burn rate shown separately (INV-SL-02)
  - Narrative suggests team-specific followups (CC-28)

### 9.5 Performance & operations (US-21 .. US-25)

**US-21: Handle Prometheus downtime**
- **As a** platform operator
- **I want** graceful handling of metric gaps
- **So that** reports still generate during outages
- **Given:** Prometheus unavailable for 2h on April 3
- **When:** Generating April report
- **Then:**
  - Report shows "Data Gap" warning (CC-30)
  - Availability calculated only on available data (INV-SL-02)
  - JSON output includes `metrics_completeness: 0.92` (CC-14)

**US-22: Large report chunking**
- **As a** enterprise user
- **I want** reports >50 pages to split automatically
- **So that** PDFs remain usable
- **Given:** 150 endpoints to report on
- **When:** Generating monthly PDF
- **Then:**
  - Output splits into 3x 50-page files (CC-11)
  - Table of contents spans all volumes (CC-05)
  - Complete dataset still in single JSON (CC-14)

**US-23: CI pipeline integration**
- **As a** DevOps engineer
- **I want** reports generated in CI
- **So that** they're always up-to-date
- **Given:`sla-reporter` in `.github/workflows/monthly.yml`
- **When:** 1st of month at 00:00 UTC
- **Then:**
  - Report generates in <10m (CC-10)
  - PDF uploaded to S3 (CC-24)
  - Slack notification sent (CC-26)

**US-24: Timezone handling**
- **As a** global team
- **I want** reports in local timezone
- **So that** everyone interprets dates correctly
- **Given:`TZ=Asia/Tokyo` env var
- **When:** Generating daily report
- **Then:**
  - All timestamps show in JST (INV-SL-07)
  - UTC remains stored internally (CC-16)
  - Timezone noted in report footer (CC-05)

**US-25: Idempotent report generation**
- **As a** auditor
- **I want** identical inputs to produce identical reports
- **So that** I can verify historical compliance
- **Given:`report_period=2026-03` already generated
- **When:** Re-running with same parameters
- **Then:**
  - PDF byte-for-byte identical (INV-SL-01)
  - No duplicate Prometheus queries (INV-SL-03)
  - Tool logs "Report exists" (CC-25)

---

## 10. Test Plan

### 10.1 Report Generation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Deterministic report generation | Identical metrics/config for April 2026 | Generate report twice with same inputs | PDFs have identical SHA-256 hashes (INV-SL-01) |
| T-02 | Empty period handling | `/api/new` with zero requests in March 2026 | Generate monthly report | Report shows "No traffic" status for `/api/new` (US-05) |
| T-03 | Partial period calculation | `/api/reviews` deployed April 15 | Generate April monthly report | Availability calculated only from April 15-30 (INV-SL-02) |
| T-04 | Multi-format output | 30 days of metrics for 5 endpoints | Generate with `output_format=html`, `output_format=pdf` | Both formats contain identical core metrics (CC-14) |
| T-05 | Large report chunking | 150 endpoints with metrics | Generate PDF report | Output splits into 3x 50-page files (US-22) |
| T-06 | Timezone handling | `TZ=Asia/Tokyo` env var set | Generate daily report | All timestamps show in JST (INV-SL-07) |

### 10.2 Configuration Validation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Invalid window format | `sla.yaml` with `error_budget_window: "30days"` | Load config | Raises ValidationError with valid format examples (INV-SL-05) |
| T-08 | Minimum availability enforcement | `availability_pct: 85.0` in config | Validate SLATarget model | Raises ValueError (>=90.0 required) (QS-5) |
| T-09 | Environment overrides | `STAGING_MODE=true` with default 99.9% target | Generate report | Uses 95% target for all endpoints (US-10) |
| T-10 | Missing required path | `availability_pct: 99.9` without path | Load config | Raises ValidationError for missing path (CC-20) |
| T-11 | Default values application | New `/api/search` endpoint with no config | Generate report | Uses default p99=500ms, availability=99.9% (US-07) |
| T-12 | Maintenance window exclusion | `maintenance: ["2026-04-10T01:00,03:00"]` | Generate April report | 2h window excluded from calculations (CC-29) |

### 10.3 Error Budget Calculation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Multi-window burn rates | API outage 09:00-09:45 UTC | Generate report at 10:00 | Shows 1h=Critical, 24h=Healthy statuses (INV-SL-02) |
| T-14 | Budget exhaustion | `/api/payments` with 0% remaining budget | Generate PDF report | Shows red "EXHAUSTED" banner (US-12) |
| T-15 | Near-miss detection | `/api/inventory` with 15% budget left | Generate weekly report | Shows yellow "AT RISK" warning (US-13) |
| T-16 | Holiday exclusion | `holidays: ["2026-11-27"]` in config | Generate November report | Black Friday metrics excluded (US-15) |
| T-17 | Incident attribution | `teams: [frontend, backend]` in incident | Generate quarterly report | Budget consumption split 60/40 in charts (US-20) |
| T-18 | Prometheus downtime handling | 2h gap on April 3 | Generate April report | Shows "Data Gap" warning (US-21) |

### 10.4 Incident Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Alertmanager linkage | `HighErrorRate` alert fired April 1 14:22Z | Generate April report | Alert appears in timeline (INV-SL-08) |
| T-20 | Sentry exception correlation | `PaymentGatewayTimeout` on April 5 | Generate weekly report | Exception count correlates with error rate (CC-28) |
| T-21 | RCA annotation | `rca: "Load balancer error"` in config | Generate HTML report | Shows in "Lessons Learned" section (US-19) |
| T-22 | Maintenance exclusion | `DB_MAINTENANCE=2026-04-10T01:00,03:00` | Generate report | 2h window shown as gray bar (T-19) |
| T-23 | Alert query performance | 50 alerts in period | Generate report | All Alertmanager queries complete in <1s (CC-17) |
| T-24 | Incident-free period | No alerts in March 2026 | Generate monthly report | Narrative shows "No major incidents" (CC-28) |

### 10.5 Performance & Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Rate-limited Prometheus queries | 100 endpoints to query | Generate report | Enforces 10 req/sec via TokenBucket (INV-SL-03) |
| T-26 | PDF signing verification | Generated April 2026 report | Inspect PDF metadata | Contains SHA-256 hash of source data (INV-SL-04) |
| T-27 | XSS protection | Attempt script injection via endpoint path | Generate HTML report | All dynamic content properly escaped (INV-SL-06) |
| T-28 | Idempotent regeneration | Existing report for March 2026 | Re-run same parameters | Logs "Report exists", no duplicate queries (CC-25) |
| T-29 | Performance benchmark | 30 days of data for 50 endpoints | Time report generation | Completes in <10s (QS-1) |
| T-30 | UTC time enforcement | System timezone=EST, no config | Generate report | All timestamps stored as UTC (INV-SL-07) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | SLA reporter reads metrics, doesn't modify data models |
| add_cursor_pagination | No | ✅ Compatible | Pagination doesn't affect Prometheus metrics collection |
| add_search | No | ✅ Compatible | Search functionality operates independently of monitoring |
| add_audit_log | Yes | ⚠️ Caveat | Audit logs must run BEFORE SLA middleware to capture all requests |
| add_data_export | No | ✅ Compatible | Data export can include SLA reports without conflict |
| add_bulk_operations | No | ✅ Compatible | Bulk ops metrics are captured like regular requests |
| add_multi_tenancy | Yes | ⚠️ Caveat | Tenant middleware must run BEFORE SLA metrics collection |
| add_feature_flags | No | ✅ Compatible | Feature flags don't interfere with Prometheus queries |
| add_api_key_auth | No | ✅ Compatible | Auth happens before metrics collection |
| add_oauth2_provider | No | ✅ Compatible | OAuth flows are transparent to SLA monitoring |
| add_rbac | No | ✅ Compatible | Permission checks don't affect metric collection |
| add_mfa | No | ✅ Compatible | MFA challenges are handled before request metrics |
| add_cache_layer | Yes | ⚠️ Caveat | Cache middleware must run AFTER SLA metrics to measure actual backend latency |
| add_outbox_pattern | No | ✅ Compatible | Outbox writes don't affect API response metrics |
| add_sse | Yes | ⚠️ Caveat | SSE connections require special handling in Prometheus queries |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/core/prometheus_client.py
git checkout -- app/services/sla_report_service.py
git checkout -- app/api/endpoints/sla_report.py
git checkout -- app/models/sla_config.py
rm -rf app/templates/reports/
rm -f app/core/report_generator.py
rm -f app/core/pdf_signer.py
rm -f app/cli.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated
by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status  # Identify modified files
git checkout -- app/models/sla_config.py  # Revert model changes
rm -f app/core/prometheus_client.py  # Remove new files
rm -f .github/workflows/sla-reports.yml  # Remove CI workflow
```

### Emergency: Prometheus outage during report generation
1. Check Prometheus status: `curl http://prometheus:9090/-/healthy`
2. If down, abort current report: `pkill -f "sla_reporter"`
3. Generate partial report with warning: `sla_reporter --partial --warning="Prometheus unavailable during generation"`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Prometheus returns no data for endpoint | Report shows "No traffic" status with 100% availability |
| EC-2 | Metric gaps from Prometheus restart | Report includes "Data incomplete" warning with completeness percentage |
| EC-3 | Endpoint removed mid-period | Availability calculated only for active portion of period |
| EC-4 | Endpoint added mid-period | Metrics calculated from first request timestamp |
| EC-5 | Target missed by single error | Report shows yellow "Near Miss" status |
| EC-6 | Error budget fully consumed | Report shows red "Budget Exhausted" banner |
| EC-7 | Budget under 10% consumed | Report shows green "Healthy" status |
| EC-8 | Conflicting burn rates (1h red, 24h green) | Report shows both windows with explanation |
| EC-9 | Maintenance window configured | Excluded period shown as gray bar in charts |
| EC-10 | Missing PDF font | Falls back to system sans-serif with warning |
| EC-11 | Report exceeds 50 pages | Automatically splits into multiple volumes |
| EC-12 | Identical report regenerated | Returns cached version with "Report exists" log |
| EC-13 | Prometheus query timeout | Returns partial results with timeout warning |
| EC-14 | Timezone configuration missing | Uses UTC and notes assumption in footer |
| EC-15 | Blackout period configured | Excludes holiday traffic from calculations |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via checklist
✅ 2. All 30 test cases pass (pytest tests/test_sla_reporter.py -v)
✅ 3. Report generation completes in <10s for 30 days of data
✅ 4. PDF/HTML/Markdown/JSON outputs validate against specs
✅ 5. Prometheus queries respect 10 req/sec rate limit
✅ 6. Cryptographic signatures present in PDF metadata
✅ 7. Multi-window burn rates match Google SRE methodology
✅ 8. HTML output passes OWASP XSS tests
✅ 9. Timezone handling defaults to UTC with config override
✅ 10. Execute end-to-end: `sla_reporter /app/prod-api --period=month --output=pdf` and verify report in /app/prod-api/reports/

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and contains FastAPI structure
- [ ] Verify Prometheus URL is reachable from target environment
- [ ] Check for existing `sla.yaml` in config directory
- [ ] Validate Python version >= 3.9
- [ ] Confirm Poetry is installed for dependency management
- [ ] Check for required Prometheus metrics (http_requests_total, http_request_duration_seconds_bucket)
- [ ] Verify write permissions in reports directory

### 15.2 Configuration setup
- [ ] Add `PROMETHEUS_URL` to `app/core/config.py`
- [ ] Add `SLA_REPORT_DIR` to settings
- [ ] Add `DEFAULT_P99_MS` and `DEFAULT_AVAILABILITY_PCT` constants
- [ ] Create `app/core/report_settings.py` with output format options
- [ ] Add Prometheus timeout setting (30s)
- [ ] Configure rate limiter (10 req/sec)
- [ ] Add maintenance window exclusion list

### 15.3 Model implementation
- [ ] Implement `SLATarget` Pydantic model with validators
- [ ] Create `ReportMetadata` model for tracking generation
- [ ] Add `ReportPeriod` enum for day/week/month/quarter
- [ ] Implement `BurnRateWindow` model for 1h/6h/24h calculations
- [ ] Create `IncidentLink` model for Alertmanager/Sentry integration
- [ ] Add `ReportFormat` enum for output types
- [ ] Implement `ReportStatus` enum (green/yellow/red)

### 15.4 Core modules
- [ ] Implement `PrometheusClient` with rate limiting
- [ ] Create `ErrorBudgetCalculator` with SRE formulas
- [ ] Implement `ReportGenerator` with deterministic hashing
- [ ] Add `PDFSigner` with SHA-256 embedding
- [ ] Create `IncidentLinker` for Alertmanager/Sentry queries
- [ ] Implement `DateTimeHelper` for UTC conversion
- [ ] Add `TemplateRenderer` for HTML/Markdown output

### 15.5 Service layer
- [ ] Implement `SLAReportService` orchestration
- [ ] Add availability calculation service
- [ ] Create latency percentile service
- [ ] Implement burn rate analysis service
- [ ] Add incident correlation service
- [ ] Create report persistence service
- [ ] Implement notification service for report completion

### 15.6 API endpoints
- [ ] Add `/sla-reports/generate` POST endpoint
- [ ] Implement `/sla-reports/history` GET endpoint
- [ ] Add `/sla-reports/config` endpoint for YAML validation
- [ ] Create `/sla-reports/status` endpoint for progress
- [ ] Implement `/sla-reports/download/{report_id}` endpoint
- [ ] Add OpenAPI schema for all endpoints
- [ ] Implement endpoint permission checks

### 15.7 Middleware
- [ ] Add Prometheus metrics middleware
- [ ] Implement request timing middleware
- [ ] Add error tracking middleware
- [ ] Create report caching middleware
- [ ] Implement maintenance window middleware
- [ ] Add timezone handling middleware
- [ ] Create request/response logging middleware

### 15.8 Migration
- [ ] Generate `alembic/versions/NNN_add_sla_reports_table.py`
- [ ] Create `sla_reports` table with JSON column
- [ ] Add indexes on period_start/period_end
- [ ] Implement downgrade to drop table
- [ ] Add migration test cases
- [ ] Document schema in `docs/database.md`
- [ ] Verify migration rollback works

### 15.9 Test generation
- [ ] Create `tests/test_sla_reporter.py` with 30 cases
- [ ] Mock Prometheus responses for unit tests
- [ ] Add integration test for full report cycle
- [ ] Test PDF/HTML/Markdown/JSON outputs
- [ ] Verify edge cases (no data, gaps, etc.)
- [ ] Test rate limiting enforcement
- [ ] Benchmark report generation performance

### 15.10 CLI implementation
- [ ] Implement `app/cli.py` with click commands
- [ ] Add `generate-report` command
- [ ] Implement `validate-config` command
- [ ] Add `list-reports` command
- [ ] Create `test-connection` command for Prometheus
- [ ] Implement progress bars for long operations
- [ ] Add colored output for statuses

### 15.11 Atomicity
- [ ] Use temp files for all writes
- [ ] Implement rollback on validation failure
- [ ] Track modified files for cleanup
- [ ] Verify file parses before final write
- [ ] Use transactions for DB operations
- [ ] Implement checksum verification
- [ ] Document atomicity guarantees

### 15.12 Documentation
- [ ] Add to `SKILL.md` tools table
- [ ] Update `manifest.yaml` with tool entry
- [ ] Create `docs/sla_reporter.md` usage guide
- [ ] Document YAML schema in `CONFIGURATION.md`
- [ ] Add example reports to `examples/`
- [ ] Document Prometheus requirements
- [ ] Create troubleshooting guide

### 15.13 Verification
- [ ] Run `ast.parse` on all modified files
- [ ] Execute all 30 test cases
- [ ] Benchmark report generation time
- [ ] Verify memory usage <100MB
- [ ] Check PDF signatures
- [ ] Validate HTML XSS safety
- [ ] Confirm UTC time handling

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/prometheus_client.py",
    "app/services/sla_report_service.py",
    "app/api/endpoints/sla_report.py",
    "app/models/sla_config.py",
    "app/core/report_generator.py",
    "app/core/pdf_signer.py",
    "app/templates/reports/",
    "app/cli.py",
    ".github/workflows/sla-reports.yml"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/main.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 3820,
    "files_changed": 12,
    "lines_added": 842,
    "lines_removed": 18,
    "endpoints_monitored": 27,
    "report_periods_supported": 4
  },
  "next_steps": [
    "Run: pytest tests/test_sla_reporter.py -v",
    "Validate config: python -m app.cli validate-config",
    "Generate test report: python -m app.cli generate-report --period=week",
    "Inspect output: ls -l ./reports/",
    "Schedule monthly reports: crontab -e (add 0 0 1 * *)"
  ],
  "warnings": [
    "Prometheus query timeout set to 30s - adjust PROMETHEUS_TIMEOUT if needed",
    "Default retention period is 30d - older metrics won't be included"
  ],
  "notes": [
    "SLA reporting enabled with default p99=500ms, availability=99.9%",
    "Reports generated in PDF/HTML/Markdown/JSON formats",
    "Prometheus queries rate-limited to 10 req/sec",
    "All timestamps stored and processed in UTC",
    "Test coverage: 92% for new code",
    "Middleware added to track request metrics"
  ]
}
