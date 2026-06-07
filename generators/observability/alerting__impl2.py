"""Internal implementation (part 2) for ``alerting`` — Grafana panels.

Split out of ``alerting.py`` to respect the 500-LOC cap.  Contains the
individual Grafana panel builders (one function per panel) plus the row
divider.  The dashboard assembler, file writers, and the public
``generate_alerting`` entry point live in ``alerting__impl4``.

Public symbols are re-exported from ``generators.observability.alerting`` —
import from there, not from this module.
"""

from __future__ import annotations

from generators.observability.alerting__impl1 import BURN_RATE_FAST

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
        "targets": [
            {
                "expr": f'sum(rate(http_requests_total{{service="{service_name}"}}[5m])) by (endpoint)',
                "legendFormat": "{{endpoint}}",
                "refId": "A",
            }
        ],
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
        "targets": [
            {
                "expr": (
                    f'sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[5m]))'
                    f' / sum(rate(http_requests_total{{service="{service_name}"}}[5m])) * 100'
                ),
                "legendFormat": "Error Rate %",
                "refId": "A",
            }
        ],
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
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "red", "value": latency_s},
                    ],
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
        "targets": [
            {
                "expr": (
                    f'sum(increase(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le)'
                ),
                "format": "heatmap",
                "legendFormat": "{{le}}",
                "refId": "A",
            }
        ],
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
        "targets": [
            {
                "expr": f'sum(http_requests_in_progress{{service="{service_name}"}})',
                "legendFormat": "Active Requests",
                "refId": "A",
            }
        ],
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
        "targets": [
            {
                "expr": (
                    f"1 - ("
                    f'sum(increase(http_requests_total{{service="{service_name}", status=~"5.."}}[30d]))'
                    f' / sum(increase(http_requests_total{{service="{service_name}"}}[30d]))'
                    f") / {error_budget}"
                ),
                "legendFormat": "Budget Remaining",
                "refId": "A",
            }
        ],
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
            {
                "expr": f"{service_name}:burn_rate:1h",
                "legendFormat": "Burn Rate (1h)",
                "refId": "A",
            },
            {
                "expr": f"{service_name}:burn_rate:6h",
                "legendFormat": "Burn Rate (6h)",
                "refId": "B",
            },
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
