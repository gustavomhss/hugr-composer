"""Generator for SLO-driven Prometheus alerting rules and Grafana dashboard.

This module implements the **Google SRE Workbook Chapter 5 multi-window
multi-burn-rate** pattern for alert generation.  Instead of static thresholds
(e.g. "alert when error rate > 5%"), every alert threshold is derived
mathematically from the service's declared SLO targets:

    error_budget = 1 - slo_availability
    burn_rate    = current_error_ratio / error_budget

Why burn-rate alerts are superior to static thresholds
-------------------------------------------------------
* **False-positive immunity**: a 2% error rate on a 99.0% SLO (budget = 1%)
  is a 2x burn — worth a ticket, not a page.  The same rate on a 99.9% SLO
  (budget = 0.1%) is a 20x burn — page immediately.  Static thresholds cannot
  express this distinction.

* **Budget-exhaustion forecasting**: burn_rate 14.4 means the 30-day error
  budget will be exhausted in approximately 50 hours.  Burn_rate 6 means
  approximately 5 days.  Every alert annotation communicates *time to
  exhaustion*, not just "something is wrong".

* **Paired-window noise suppression**: each alert requires BOTH a long-window
  check (detects sustained burns) AND a short-window check where
  short = long / 12 (confirms the problem is still active, prevents stale
  alerts from resolved incidents).

Alert tiers generated
---------------------
=============  ===========  ==========  ========================================
Severity       Burn rate    For         Meaning
=============  ===========  ==========  ========================================
critical       14.4x        2 min       Budget exhausted in ~50 h -> page now
warning        6x           5 min       Budget exhausted in ~5 d -> page
info           1x           30 min      On track to exhaust budget -> ticket
warning        --           10 min      p99 latency exceeds SLO target
critical       --           5 min       Error budget remaining < 10%
=============  ===========  ==========  ========================================

Generated files (written to ``output_dir/alerts/``)
----------------------------------------------------
* ``prometheus-rules.yml``   -- PrometheusRule with recording rules + 5 alerts
* ``grafana-dashboard.json`` -- Importable Grafana dashboard (Four Golden
                                Signals + SLO error budget panels)

References
----------
Google SRE Workbook, Chapter 5 -- "Alerting on SLOs"
  https://sre.google/workbook/alerting-on-slos/
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_observability_generate_alerting',
    'description': 'Generate PrometheusRule alerts (5 rules) and Grafana dashboard (4 panels).',
    'tags': ['generator', 'observability'],
    'entry': 'generate_alerting',
}

import json
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Burn-rate constants (Google SRE Workbook Chapter 5)
# ---------------------------------------------------------------------------

# Fast burn: 14.4x means 2% of the 30-day error budget is consumed in 1 hour.
# At this rate the entire budget is exhausted in approximately 50 hours.  PAGE.
BURN_RATE_FAST: float = 14.4

# Medium burn: 6x means the budget is exhausted in approximately 5 days.  PAGE.
BURN_RATE_MEDIUM: float = 6.0

# Slow burn: 1x means the service is on track to exhaust the budget at exactly
# the end of the 30-day window.  Create a TICKET; no immediate page.
BURN_RATE_SLOW: float = 1.0

# Paired window durations -- long window detects sustained burn,
# short = long / 12 confirms the problem is still active.
FAST_WINDOW_LONG: str = "1h"
FAST_WINDOW_SHORT: str = "5m"     # 1h / 12 ~= 5m

MEDIUM_WINDOW_LONG: str = "6h"
MEDIUM_WINDOW_SHORT: str = "30m"  # 6h / 12 = 30m

SLOW_WINDOW_LONG: str = "6h"
SLOW_WINDOW_SHORT: str = "1h"

# Page when less than 10% of the 30-day error budget remains.
ERROR_BUDGET_PAGE_THRESHOLD: float = 0.1

# Number of minutes p99 must exceed SLO before the latency alert fires.
LATENCY_FOR_MINUTES: int = 10


# ---------------------------------------------------------------------------
# SLO config helpers
# ---------------------------------------------------------------------------


def _parse_slo_config(
    slo_config: dict | None,
    service_name: str,
    namespace: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
) -> tuple[str, str, float, int]:
    """Merge an optional ``slo_config`` dict with keyword-argument defaults.

    The ``slo_config`` dict (e.g. loaded from ``slo.yaml``) takes precedence
    over individual keyword arguments when both are provided.

    Args:
        slo_config: Optional dict with keys ``service_name``, ``namespace``,
            ``availability``, and/or ``latency_p99_ms``.
        service_name: Fallback service name if not in ``slo_config``.
        namespace: Fallback Kubernetes namespace if not in ``slo_config``.
        slo_availability: Fallback availability SLO (0 < v < 1).
        slo_latency_p99_ms: Fallback p99 latency target in milliseconds.

    Returns:
        Tuple ``(service_name, namespace, slo_availability, slo_latency_p99_ms)``
        after applying any ``slo_config`` overrides.
    """
    if slo_config:
        service_name = slo_config.get("service_name", service_name)
        namespace = slo_config.get("namespace", namespace)
        slo_availability = float(slo_config.get("availability", slo_availability))
        slo_latency_p99_ms = int(slo_config.get("latency_p99_ms", slo_latency_p99_ms))
    return service_name, namespace, slo_availability, slo_latency_p99_ms


def _validate_slo_params(slo_availability: float, slo_latency_p99_ms: int) -> None:
    """Raise ``ValueError`` for out-of-range SLO parameters.

    Args:
        slo_availability: Must be strictly between 0 and 1.
        slo_latency_p99_ms: Must be a positive integer.

    Raises:
        ValueError: If either parameter is out of the valid range.
    """
    if not 0 < slo_availability < 1:
        raise ValueError(
            f"slo_availability must be between 0 and 1 (exclusive), "
            f"got {slo_availability}"
        )
    if slo_latency_p99_ms <= 0:
        raise ValueError(
            f"slo_latency_p99_ms must be positive, got {slo_latency_p99_ms}"
        )


# ---------------------------------------------------------------------------
# Burn-rate math
# ---------------------------------------------------------------------------


def _compute_burn_rate_thresholds(
    slo_availability: float,
) -> tuple[float, float, float, float]:
    """Compute SLO-derived error-ratio thresholds for each burn-rate tier.

    The Prometheus alert expression compares ``error_ratio / error_budget``
    against the burn-rate constant.  This is equivalent to comparing the raw
    error ratio against ``burn_rate * error_budget``.

    Args:
        slo_availability: Availability SLO as a fraction (e.g. 0.999).

    Returns:
        Tuple ``(error_budget, fast_threshold, medium_threshold, slow_threshold)``
        where each threshold is the raw error-ratio value triggering the
        corresponding alert tier.
    """
    error_budget = round(1.0 - slo_availability, 6)
    fast_threshold = round(BURN_RATE_FAST * error_budget, 6)
    medium_threshold = round(BURN_RATE_MEDIUM * error_budget, 6)
    slow_threshold = round(BURN_RATE_SLOW * error_budget, 6)
    return error_budget, fast_threshold, medium_threshold, slow_threshold


# ---------------------------------------------------------------------------
# Prometheus recording rules
# ---------------------------------------------------------------------------


def _error_ratio_recording_rules(service_name: str, error_budget: float) -> str:
    """Return YAML recording rules for error ratios and burn rates.

    Covers 5m/30m/1h/6h error ratios and 1h/6h burn rates.

    Args:
        service_name: Metric name prefix and ``service`` label value.
        error_budget: Numeric error budget (= 1 - slo_availability).

    Returns:
        YAML string fragment with six ``record`` entries.
    """
    return textwrap.dedent(f"""\
              - record: {service_name}:error_ratio:5m
                expr: |
                  sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[5m]))
                  / sum(rate(http_requests_total{{service="{service_name}"}}[5m]))
              - record: {service_name}:error_ratio:30m
                expr: |
                  sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[30m]))
                  / sum(rate(http_requests_total{{service="{service_name}"}}[30m]))
              - record: {service_name}:error_ratio:1h
                expr: |
                  sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[1h]))
                  / sum(rate(http_requests_total{{service="{service_name}"}}[1h]))
              - record: {service_name}:error_ratio:6h
                expr: |
                  sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[6h]))
                  / sum(rate(http_requests_total{{service="{service_name}"}}[6h]))
              - record: {service_name}:burn_rate:1h
                expr: |
                  {service_name}:error_ratio:1h / {error_budget}
              - record: {service_name}:burn_rate:6h
                expr: |
                  {service_name}:error_ratio:6h / {error_budget}
    """)


def _derived_metric_recording_rules(service_name: str, error_budget: float) -> str:
    """Return YAML recording rules for derived metrics (latency, rate, budget).

    Covers p99 latency (5m), request rate (5m), and 30-day error budget
    remaining.

    Args:
        service_name: Metric name prefix and ``service`` label value.
        error_budget: Numeric error budget (= 1 - slo_availability).

    Returns:
        YAML string fragment with three ``record`` entries.
    """
    return textwrap.dedent(f"""\
              - record: {service_name}:latency_p99:5m
                expr: |
                  histogram_quantile(0.99,
                    sum(rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le)
                  )
              - record: {service_name}:request_rate:5m
                expr: |
                  sum(rate(http_requests_total{{service="{service_name}"}}[5m]))
              - record: {service_name}:error_budget_remaining:30d
                expr: |
                  1 - (
                    sum(increase(http_requests_total{{service="{service_name}", status=~"5.."}}[30d]))
                    / sum(increase(http_requests_total{{service="{service_name}"}}[30d]))
                  ) / {error_budget}
    """)


def _recording_rules_block(service_name: str, error_budget: float) -> str:
    """Return the full YAML recording-rules group for ``service_name``.

    Combines error-ratio/burn-rate rules and derived-metric rules into one
    group, evaluated every 30 s.

    Args:
        service_name: Metric name prefix and ``service`` label value.
        error_budget: Numeric error budget (= 1 - slo_availability).

    Returns:
        YAML string for the complete recording-rules group, ready to embed.
    """
    header = textwrap.dedent(f"""\
          - name: {service_name}_slo_recording
            interval: 30s
            rules:
    """)
    return (
        header
        + _error_ratio_recording_rules(service_name, error_budget)
        + _derived_metric_recording_rules(service_name, error_budget)
    )


# ---------------------------------------------------------------------------
# Individual Prometheus alert definitions
# ---------------------------------------------------------------------------


def _alert_fast_burn(service_name: str, error_budget: float, slo_availability: float) -> str:
    """Return YAML for the fast-burn PAGE alert (14.4x, critical, for 2m).

    Long window: 1h / Short window: 5m (= 1h / 12).
    Fires when budget will be exhausted in approximately 50 hours.

    Args:
        service_name: Alert name prefix and label value.
        error_budget: Numeric error budget fraction.
        slo_availability: SLO availability fraction (for annotation text).

    Returns:
        YAML string for one alert rule, ready to embed.
    """
    return textwrap.dedent(f"""\
              - alert: {service_name}_SLO_FastBurn
                expr: |
                  {service_name}:error_ratio:1h / {error_budget} > {BURN_RATE_FAST}
                  and
                  {service_name}:error_ratio:5m / {error_budget} > {BURN_RATE_FAST}
                for: 2m
                labels:
                  service: {service_name}
                  severity: critical
                  slo: availability
                  alert_type: page
                annotations:
                  summary: "CRITICAL: {{{{ $labels.service }}}} burning error budget at {BURN_RATE_FAST}x"
                  description: |
                    Error burn rate is {BURN_RATE_FAST}x the budget.
                    At this rate, the 30-day error budget will be exhausted in ~50 hours.
                    Current 1h error ratio: {{{{ $value | humanizePercentage }}}}
                    Error budget: {error_budget} ({slo_availability * 100:.1f}% SLO)
                  runbook: "https://wiki.example.com/runbooks/{service_name}/slo-fast-burn"
    """)


def _alert_medium_burn(service_name: str, error_budget: float) -> str:
    """Return YAML for the medium-burn PAGE alert (6x, warning, for 5m).

    Long window: 6h / Short window: 30m (= 6h / 12).
    Fires when budget will be exhausted in approximately 5 days.

    Args:
        service_name: Alert name prefix and label value.
        error_budget: Numeric error budget fraction.

    Returns:
        YAML string for one alert rule, ready to embed.
    """
    return textwrap.dedent(f"""\
              - alert: {service_name}_SLO_MediumBurn
                expr: |
                  {service_name}:error_ratio:6h / {error_budget} > {BURN_RATE_MEDIUM}
                  and
                  {service_name}:error_ratio:30m / {error_budget} > {BURN_RATE_MEDIUM}
                for: 5m
                labels:
                  service: {service_name}
                  severity: warning
                  slo: availability
                  alert_type: page
                annotations:
                  summary: "WARNING: {{{{ $labels.service }}}} elevated burn rate ({BURN_RATE_MEDIUM}x)"
                  description: |
                    Error burn rate is {BURN_RATE_MEDIUM}x the budget over 6 hours.
                    At this rate, the 30-day error budget will be exhausted in ~5 days.
                    Current 6h error ratio: {{{{ $value | humanizePercentage }}}}
                  runbook: "https://wiki.example.com/runbooks/{service_name}/slo-medium-burn"
    """)


def _alert_slow_burn(service_name: str, error_budget: float) -> str:
    """Return YAML for the slow-burn TICKET alert (1x, info, for 30m).

    Long window: 6h / Short window: 1h.
    Fires when the service is on track to exhaust the budget by window end.

    Args:
        service_name: Alert name prefix and label value.
        error_budget: Numeric error budget fraction.

    Returns:
        YAML string for one alert rule, ready to embed.
    """
    return textwrap.dedent(f"""\
              - alert: {service_name}_SLO_SlowBurn
                expr: |
                  {service_name}:error_ratio:6h / {error_budget} > {BURN_RATE_SLOW}
                  and
                  {service_name}:error_ratio:1h / {error_budget} > {BURN_RATE_SLOW}
                for: 30m
                labels:
                  service: {service_name}
                  severity: info
                  slo: availability
                  alert_type: ticket
                annotations:
                  summary: "INFO: {{{{ $labels.service }}}} error rate above SLO budget"
                  description: |
                    Sustained error rate above SLO budget.
                    If this continues, the 30-day error budget will be exhausted.
                    Current 6h error ratio: {{{{ $value | humanizePercentage }}}}
                  runbook: "https://wiki.example.com/runbooks/{service_name}/slo-slow-burn"
    """)


def _alert_latency_high(
    service_name: str,
    latency_threshold_s: float,
    slo_latency_p99_ms: int,
) -> str:
    """Return YAML for the p99 latency SLO alert (warning, ticket, for 10m).

    Fires when the p99 latency recording rule exceeds the SLO target for
    longer than ``LATENCY_FOR_MINUTES`` minutes.

    Args:
        service_name: Alert name prefix and label value.
        latency_threshold_s: p99 latency SLO in seconds (slo_latency_p99_ms / 1000).
        slo_latency_p99_ms: p99 latency SLO in milliseconds (for annotation text).

    Returns:
        YAML string for one alert rule, ready to embed.
    """
    return textwrap.dedent(f"""\
              - alert: {service_name}_SLO_LatencyHigh
                expr: |
                  {service_name}:latency_p99:5m > {latency_threshold_s}
                for: {LATENCY_FOR_MINUTES}m
                labels:
                  service: {service_name}
                  severity: warning
                  slo: latency
                  alert_type: ticket
                annotations:
                  summary: "WARNING: {{{{ $labels.service }}}} p99 latency exceeds {slo_latency_p99_ms}ms"
                  description: |
                    The p99 request latency has exceeded {slo_latency_p99_ms}ms for
                    more than {LATENCY_FOR_MINUTES} minutes.
                    Current p99: {{{{ $value | humanizeDuration }}}}
                  runbook: "https://wiki.example.com/runbooks/{service_name}/latency-high"
    """)


def _alert_error_budget_low(service_name: str) -> str:
    """Return YAML for the error-budget-exhausted PAGE alert (critical, for 5m).

    Fires when less than ``ERROR_BUDGET_PAGE_THRESHOLD`` (10%) of the 30-day
    error budget remains.

    Args:
        service_name: Alert name prefix and label value.

    Returns:
        YAML string for one alert rule, ready to embed.
    """
    pct = int(ERROR_BUDGET_PAGE_THRESHOLD * 100)
    return textwrap.dedent(f"""\
              - alert: {service_name}_ErrorBudgetLow
                expr: |
                  {service_name}:error_budget_remaining:30d < {ERROR_BUDGET_PAGE_THRESHOLD}
                for: 5m
                labels:
                  service: {service_name}
                  severity: critical
                  slo: availability
                  alert_type: page
                annotations:
                  summary: "CRITICAL: {{{{ $labels.service }}}} error budget nearly exhausted"
                  description: |
                    Less than {pct}% of the 30-day error budget remains.
                    Remaining: {{{{ $value | humanizePercentage }}}}
                    Stop feature work and focus on reliability.
                  runbook: "https://wiki.example.com/runbooks/{service_name}/error-budget-exhausted"
    """)


# ---------------------------------------------------------------------------
# Prometheus rules assembler
# ---------------------------------------------------------------------------


def _prometheus_rules_header(
    service_name: str,
    namespace: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
    error_budget: float,
) -> str:
    """Return the YAML document header for the PrometheusRule CRD.

    Includes inline comments summarising SLO targets and alert strategy.

    Args:
        service_name: Alert name prefix and CRD ``name`` field.
        namespace: Kubernetes namespace for the CRD.
        slo_availability: Availability SLO fraction (for comment text).
        slo_latency_p99_ms: p99 latency target (for comment text).
        error_budget: Computed error budget fraction (for comment text).

    Returns:
        YAML string from ``apiVersion`` through ``spec.groups:``.
    """
    return textwrap.dedent(f"""\
        # Prometheus Alerting Rules — {service_name}
        # Generated by SKILL-001 generators/observability/alerting.py
        # SLO: availability={slo_availability * 100:.2f}% (budget={error_budget}), p99<{slo_latency_p99_ms}ms
        # Strategy: multi-window multi-burn-rate (Google SRE Workbook Ch.5)
        #   Fast ({BURN_RATE_FAST}x): PAGE ~50 h | Medium ({BURN_RATE_MEDIUM}x): PAGE ~5 d | Slow ({BURN_RATE_SLOW}x): TICKET
        #   short_window = long_window / 12  (prevents stale alerts)
        apiVersion: monitoring.coreos.com/v1
        kind: PrometheusRule
        metadata:
          name: {service_name}-slo-rules
          namespace: {namespace}
          labels:
            app: {service_name}
            release: kube-prometheus-stack
        spec:
          groups:
    """)


def _build_prometheus_rules(
    service_name: str,
    namespace: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
) -> str:
    """Assemble the complete Prometheus rules YAML document.

    Combines the CRD header, recording-rules group, and five alert rules into
    one deployable YAML string compatible with the Prometheus Operator CRD and
    plain ``rule_files`` configuration.

    Args:
        service_name: Prometheus ``service`` label and alert name prefix.
        namespace: Kubernetes namespace for the PrometheusRule resource.
        slo_availability: Availability SLO as a fraction (e.g. 0.999).
        slo_latency_p99_ms: Maximum acceptable p99 latency in milliseconds.

    Returns:
        Complete YAML document as a string.
    """
    error_budget, _, _, _ = _compute_burn_rate_thresholds(slo_availability)
    latency_s = slo_latency_p99_ms / 1000.0
    alerts_group = textwrap.dedent(f"""\
          - name: {service_name}_slo_alerts
            rules:
    """)
    alerts_body = (
        _alert_fast_burn(service_name, error_budget, slo_availability)
        + _alert_medium_burn(service_name, error_budget)
        + _alert_slow_burn(service_name, error_budget)
        + _alert_latency_high(service_name, latency_s, slo_latency_p99_ms)
        + _alert_error_budget_low(service_name)
    )
    return (
        _prometheus_rules_header(service_name, namespace, slo_availability, slo_latency_p99_ms, error_budget)
        + _recording_rules_block(service_name, error_budget)
        + "\n"
        + alerts_group
        + alerts_body
    )


# ---------------------------------------------------------------------------
# Grafana panel builders (one function per panel)
# ---------------------------------------------------------------------------


def _panel_request_rate(service_name: str, panel_id: int, y_pos: int) -> dict:
    """Build the request-rate time-series panel (by endpoint).

    Args:
        service_name: Prometheus ``service`` label value.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisBorderShow": False,
                    "drawStyle": "line",
                    "fillOpacity": 10,
                    "lineWidth": 2,
                    "showPoints": "never",
                },
                "unit": "reqps",
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
        "id": panel_id,
        "options": {
            "legend": {"calcs": ["mean", "max"], "displayMode": "table", "placement": "bottom"},
        },
        "targets": [{
            "expr": f'sum(rate(http_requests_total{{service="{service_name}"}}[5m])) by (endpoint)',
            "legendFormat": "{{endpoint}}",
            "refId": "A",
        }],
        "title": "Request Rate (by endpoint)",
        "type": "timeseries",
    }


def _error_rate_field_config(budget_pct: float) -> dict:
    """Build the fieldConfig for the error-rate panel.

    Yellow threshold at 50% of budget, red at 100%.  Y-axis max is 10x budget
    so small exceedances are visible without the axis exploding.

    Args:
        budget_pct: Error budget expressed as a percentage (e.g. 0.1 for 0.1%).

    Returns:
        Grafana ``fieldConfig`` dict.
    """
    return {
        "defaults": {
            "color": {"fixedColor": "red", "mode": "fixed"},
            "custom": {
                "drawStyle": "line",
                "fillOpacity": 20,
                "lineWidth": 2,
                "showPoints": "never",
                "thresholdsStyle": {"mode": "line"},
            },
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": round(budget_pct * 0.5, 4)},
                    {"color": "red", "value": budget_pct},
                ],
            },
            "unit": "percent",
            "max": max(round(budget_pct * 10, 4), 1.0),
        },
        "overrides": [],
    }


def _panel_error_rate(service_name: str, error_budget: float, panel_id: int, y_pos: int) -> dict:
    """Build the SLO-thresholded error-rate percentage time-series panel.

    Args:
        service_name: Prometheus ``service`` label value.
        error_budget: Numeric error budget fraction (= 1 - slo_availability).
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    budget_pct = round(error_budget * 100, 4)
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": _error_rate_field_config(budget_pct),
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
        "id": panel_id,
        "targets": [{
            "expr": (
                f'sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[5m]))'
                f' / sum(rate(http_requests_total{{service="{service_name}"}}[5m])) * 100'
            ),
            "legendFormat": "Error Rate %",
            "refId": "A",
        }],
        "title": f"Error Rate % (SLO budget: <{budget_pct}%)",
        "type": "timeseries",
    }


def _latency_percentile_targets(service_name: str) -> list[dict]:
    """Build Prometheus targets for p50, p95, and p99 latency percentiles.

    Args:
        service_name: Prometheus ``service`` label value.

    Returns:
        List of three Grafana target dicts (refId A/B/C).
    """
    metric = f'http_request_duration_seconds_bucket{{service="{service_name}"}}'
    return [
        {
            "expr": f"histogram_quantile(0.50, sum(rate({metric}[5m])) by (le))",
            "legendFormat": "p50",
            "refId": "A",
        },
        {
            "expr": f"histogram_quantile(0.95, sum(rate({metric}[5m])) by (le))",
            "legendFormat": "p95",
            "refId": "B",
        },
        {
            "expr": f"histogram_quantile(0.99, sum(rate({metric}[5m])) by (le))",
            "legendFormat": "p99",
            "refId": "C",
        },
    ]


def _panel_latency_percentiles(
    service_name: str,
    slo_latency_p99_ms: int,
    panel_id: int,
    y_pos: int,
) -> dict:
    """Build the latency percentile time-series panel (p50, p95, p99).

    A red threshold line at the SLO p99 target makes breaches immediately visible.

    Args:
        service_name: Prometheus ``service`` label value.
        slo_latency_p99_ms: p99 latency SLO in milliseconds (threshold line).
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    latency_s = slo_latency_p99_ms / 1000.0
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line",
                    "fillOpacity": 0,
                    "lineWidth": 2,
                    "showPoints": "never",
                    "thresholdsStyle": {"mode": "line"},
                },
                "thresholds": {
                    "mode": "absolute",
                    "steps": [{"color": "green", "value": None}, {"color": "red", "value": latency_s}],
                },
                "unit": "s",
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
        "id": panel_id,
        "targets": _latency_percentile_targets(service_name),
        "title": f"Latency Percentiles (SLO: p99 < {slo_latency_p99_ms}ms)",
        "type": "timeseries",
    }


def _panel_latency_heatmap(service_name: str, panel_id: int, y_pos: int) -> dict:
    """Build the latency distribution heatmap panel.

    Args:
        service_name: Prometheus ``service`` label value.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "scheme", "schemeVersion": 1},
                "custom": {"hideFrom": {"legend": False, "tooltip": False, "viz": False}},
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
        "id": panel_id,
        "options": {
            "calculate": False,
            "cellGap": 1,
            "color": {"mode": "scheme", "scheme": "Oranges", "steps": 64},
            "yAxis": {"unit": "s"},
        },
        "targets": [{
            "expr": (
                f'sum(increase(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le)'
            ),
            "format": "heatmap",
            "legendFormat": "{{le}}",
            "refId": "A",
        }],
        "title": "Latency Distribution (Heatmap)",
        "type": "heatmap",
    }


def _panel_active_requests(service_name: str, panel_id: int, y_pos: int) -> dict:
    """Build the active-requests saturation time-series panel.

    Args:
        service_name: Prometheus ``service`` label value.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "color": {"fixedColor": "blue", "mode": "fixed"},
                "custom": {
                    "drawStyle": "line",
                    "fillOpacity": 30,
                    "lineWidth": 2,
                    "showPoints": "never",
                },
                "unit": "short",
            },
            "overrides": [],
        },
        "gridPos": {"h": 8, "w": 8, "x": 0, "y": y_pos},
        "id": panel_id,
        "targets": [{
            "expr": f'sum(http_requests_in_progress{{service="{service_name}"}})',
            "legendFormat": "Active Requests",
            "refId": "A",
        }],
        "title": "Active Requests (Saturation)",
        "type": "timeseries",
    }


def _budget_gauge_field_config() -> dict:
    """Build the fieldConfig for the error-budget-remaining gauge panel.

    Red below 20% remaining (critical), yellow below 50% (warning),
    green at or above 50% (healthy).

    Returns:
        Grafana ``fieldConfig`` dict with percentunit and threshold steps.
    """
    return {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "red", "value": None},
                    {"color": "yellow", "value": 0.2},
                    {"color": "green", "value": 0.5},
                ],
            },
            "unit": "percentunit",
            "min": 0,
            "max": 1,
        },
        "overrides": [],
    }


def _panel_error_budget_gauge(
    service_name: str,
    slo_availability: float,
    error_budget: float,
    panel_id: int,
    y_pos: int,
) -> dict:
    """Build the error-budget-remaining gauge panel (30-day window).

    Args:
        service_name: Prometheus ``service`` label value.
        slo_availability: SLO availability fraction (for the panel title).
        error_budget: Numeric error budget fraction.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": _budget_gauge_field_config(),
        "gridPos": {"h": 8, "w": 8, "x": 8, "y": y_pos},
        "id": panel_id,
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
        "targets": [{
            "expr": (
                f"1 - ("
                f'sum(increase(http_requests_total{{service="{service_name}", status=~"5.."}}[30d]))'
                f' / sum(increase(http_requests_total{{service="{service_name}"}}[30d]))'
                f") / {error_budget}"
            ),
            "legendFormat": "Budget Remaining",
            "refId": "A",
        }],
        "title": f"Error Budget Remaining ({slo_availability * 100:.1f}% SLO)",
        "type": "gauge",
    }


def _burn_rate_field_config() -> dict:
    """Build the fieldConfig for the burn-rate panel.

    A red line+area above BURN_RATE_FAST (14.4x) shows at a glance
    whether a critical burn is in progress.

    Returns:
        Grafana ``fieldConfig`` dict.
    """
    return {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {
                "drawStyle": "line",
                "fillOpacity": 0,
                "lineWidth": 2,
                "showPoints": "never",
                "thresholdsStyle": {"mode": "line+area"},
            },
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "transparent", "value": None},
                    {"color": "red", "value": BURN_RATE_FAST},
                ],
            },
            "unit": "short",
        },
        "overrides": [],
    }


def _panel_burn_rate(service_name: str, panel_id: int, y_pos: int) -> dict:
    """Build the burn-rate time-series panel (1h and 6h windows).

    Args:
        service_name: Prometheus ``service`` label value.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana panel dict.
    """
    return {
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": _burn_rate_field_config(),
        "gridPos": {"h": 8, "w": 8, "x": 16, "y": y_pos},
        "id": panel_id,
        "targets": [
            {"expr": f"{service_name}:burn_rate:1h", "legendFormat": "Burn Rate (1h)", "refId": "A"},
            {"expr": f"{service_name}:burn_rate:6h", "legendFormat": "Burn Rate (6h)", "refId": "B"},
        ],
        "title": f"Error Budget Burn Rate (page threshold: {BURN_RATE_FAST}x)",
        "type": "timeseries",
    }


def _row_panel(title: str, panel_id: int, y_pos: int) -> dict:
    """Build a Grafana row panel (section divider).

    Args:
        title: Display title for the row.
        panel_id: Grafana panel ID.
        y_pos: Vertical grid position.

    Returns:
        Grafana row panel dict.
    """
    return {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y_pos},
        "id": panel_id,
        "title": title,
        "type": "row",
    }


# ---------------------------------------------------------------------------
# Grafana dashboard assembler
# ---------------------------------------------------------------------------


def _dashboard_metadata(service_name: str) -> dict:
    """Build the Grafana dashboard skeleton (metadata, templating, time range).

    The ``panels`` key is set to an empty list; callers must populate it.

    Args:
        service_name: Used in the dashboard title, UID, tags, and description.

    Returns:
        Grafana dashboard dict with an empty ``panels`` list.
    """
    return {
        "annotations": {"list": []},
        "description": (
            f"Production monitoring for {service_name} — "
            "Four Golden Signals + SLO error budget"
        ),
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": [],
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["api", "slo", "red", service_name],
        "templating": {
            "list": [{
                "current": {"selected": False, "text": "default", "value": "default"},
                "hide": 0,
                "includeAll": False,
                "multi": False,
                "name": "datasource",
                "options": [],
                "query": "prometheus",
                "refresh": 1,
                "type": "datasource",
            }],
        },
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "utc",
        "title": f"{service_name} — API Observability",
        "uid": f"{service_name.replace('-', '_')}_api_obs",
        "version": 1,
    }


def _assemble_dashboard_panels(
    service_name: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
    error_budget: float,
) -> list[dict]:
    """Build the ordered list of all dashboard panels across three rows.

    Args:
        service_name: Prometheus ``service`` label value.
        slo_availability: Availability SLO fraction (for gauge title).
        slo_latency_p99_ms: p99 latency SLO in milliseconds.
        error_budget: Numeric error budget fraction.

    Returns:
        Ordered list of Grafana panel dicts (rows + data panels).
    """
    pid = 1
    y = 0
    panels: list[dict] = [_row_panel("Traffic & Errors", pid, y)]
    pid += 1; y += 1  # noqa: E702
    panels += [_panel_request_rate(service_name, pid, y),
               _panel_error_rate(service_name, error_budget, pid + 1, y)]
    pid += 2; y += 8  # noqa: E702
    panels += [_row_panel("Latency", pid, y)]
    pid += 1; y += 1  # noqa: E702
    panels += [_panel_latency_percentiles(service_name, slo_latency_p99_ms, pid, y),
               _panel_latency_heatmap(service_name, pid + 1, y)]
    pid += 2; y += 8  # noqa: E702
    panels += [_row_panel("Saturation & SLO", pid, y)]
    pid += 1; y += 1  # noqa: E702
    panels += [
        _panel_active_requests(service_name, pid, y),
        _panel_error_budget_gauge(service_name, slo_availability, error_budget, pid + 1, y),
        _panel_burn_rate(service_name, pid + 2, y),
    ]
    return panels


def _build_grafana_dashboard(
    service_name: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
) -> dict:
    """Assemble the complete Grafana dashboard JSON model.

    Args:
        service_name: Prometheus ``service`` label value and dashboard title.
        slo_availability: Availability SLO fraction for threshold computation.
        slo_latency_p99_ms: p99 latency SLO in milliseconds for threshold lines.

    Returns:
        Grafana dashboard dict ready for JSON serialisation and import.
    """
    error_budget, _, _, _ = _compute_burn_rate_thresholds(slo_availability)
    dashboard = _dashboard_metadata(service_name)
    dashboard["panels"] = _assemble_dashboard_panels(
        service_name, slo_availability, slo_latency_p99_ms, error_budget
    )
    return dashboard


# ---------------------------------------------------------------------------
# Top-level generator (v3 contract)
# ---------------------------------------------------------------------------


def _write_alerting_files(
    out: "Path",
    service_name: str,
    namespace: str,
    slo_availability: float,
    slo_latency_p99_ms: int,
) -> list[str]:
    """Write prometheus-rules.yml and grafana-dashboard.json to ``out/``.

    Args:
        out: Target directory (already created by caller).
        service_name: Prometheus ``service`` label and alert name prefix.
        namespace: Kubernetes namespace for the PrometheusRule CRD.
        slo_availability: Availability SLO as a fraction.
        slo_latency_p99_ms: Maximum acceptable p99 latency in milliseconds.

    Returns:
        List of absolute file paths written.
    """
    prom_path = out / "prometheus-rules.yml"
    prom_path.write_text(
        _build_prometheus_rules(service_name, namespace, slo_availability, slo_latency_p99_ms),
        encoding="utf-8",
    )
    grafana_path = out / "grafana-dashboard.json"
    grafana_path.write_text(
        json.dumps(
            _build_grafana_dashboard(service_name, slo_availability, slo_latency_p99_ms),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return [str(prom_path), str(grafana_path)]


def _build_notes(
    slo_availability: float,
    slo_latency_p99_ms: int,
    error_budget: float,
    fast_t: float,
    medium_t: float,
    slow_t: float,
) -> list[str]:
    """Build the human-readable notes list for the generator result dict.

    Args:
        slo_availability: Availability SLO fraction.
        slo_latency_p99_ms: p99 latency target in milliseconds.
        error_budget: Computed error budget fraction.
        fast_t: Fast-burn error ratio threshold.
        medium_t: Medium-burn error ratio threshold.
        slow_t: Slow-burn error ratio threshold.

    Returns:
        List of note strings summarising what was generated.
    """
    return [
        f"SLO: availability={slo_availability * 100:.2f}% "
        f"(error budget={error_budget}), latency p99<{slo_latency_p99_ms}ms.",
        f"Fast burn ({BURN_RATE_FAST}x): threshold={fast_t} — pages in <50 h.",
        f"Medium burn ({BURN_RATE_MEDIUM}x): threshold={medium_t} — pages in <5 days.",
        f"Slow burn ({BURN_RATE_SLOW}x): threshold={slow_t} — ticket if sustained.",
        f"Paired windows: fast={FAST_WINDOW_LONG}/{FAST_WINDOW_SHORT}, "
        f"medium={MEDIUM_WINDOW_LONG}/{MEDIUM_WINDOW_SHORT}, "
        f"slow={SLOW_WINDOW_LONG}/{SLOW_WINDOW_SHORT} (short=long/12).",
        "Grafana: 3 rows, 9 panels — error budget gauge + burn rate chart.",
    ]


def generate_alerting(
    output_dir: str,
    slo_config: dict | None = None,
    service_name: str = "fastapi-app",
    namespace: str = "default",
    slo_availability: float = 0.999,
    slo_latency_p99_ms: int = 500,
) -> dict:
    """Generate SLO-driven Prometheus alerting rules and a Grafana dashboard.

    All thresholds derive from the declared SLO (Google SRE Workbook Ch.5).
    ``slo_config`` dict overrides keyword args (keys: ``service_name``,
    ``namespace``, ``availability``, ``latency_p99_ms``).

    Creates ``output_dir/alerts/prometheus-rules.yml`` (recording rules +
    5 multi-burn-rate alerts) and ``output_dir/alerts/grafana-dashboard.json``
    (Four Golden Signals + SLO error budget panels).

    Args:
        output_dir: Root directory where ``alerts/`` will be created.
        slo_config: Optional dict from a ``slo.yaml`` file.
        service_name: Prometheus ``service`` label and alert name prefix.
        namespace: Kubernetes namespace for the PrometheusRule CRD.
        slo_availability: Availability SLO fraction (e.g. ``0.999`` = 99.9%).
        slo_latency_p99_ms: Maximum acceptable p99 latency in milliseconds.

    Returns:
        Dict with ``files_created`` (paths) and ``notes`` (summary strings).

    Raises:
        ValueError: If ``slo_availability`` not in (0, 1) or
            ``slo_latency_p99_ms`` not positive.
    """
    service_name, namespace, slo_availability, slo_latency_p99_ms = _parse_slo_config(
        slo_config, service_name, namespace, slo_availability, slo_latency_p99_ms
    )
    _validate_slo_params(slo_availability, slo_latency_p99_ms)
    error_budget, fast_t, medium_t, slow_t = _compute_burn_rate_thresholds(slo_availability)
    out = Path(output_dir) / "alerts"
    out.mkdir(parents=True, exist_ok=True)
    return {
        "files_created": _write_alerting_files(
            out, service_name, namespace, slo_availability, slo_latency_p99_ms
        ),
        "notes": _build_notes(
            slo_availability, slo_latency_p99_ms, error_budget, fast_t, medium_t, slow_t
        ),
    }
