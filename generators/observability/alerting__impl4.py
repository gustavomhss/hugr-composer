"""Internal implementation (part 4) for ``alerting`` — dashboard + entry point.

Split out of ``alerting.py`` to respect the 500-LOC cap.  Contains the Grafana
dashboard assembler, the file writers, the notes builder, and the public
``generate_alerting`` entry point.  Builds on the panel builders in
``alerting__impl2``, the alert assembler in ``alerting__impl3``, and the SLO
helpers in ``alerting__impl1``.

Public symbols are re-exported from ``generators.observability.alerting`` —
import from there, not from this module.
"""

from __future__ import annotations

import json
from pathlib import Path

from generators.observability.alerting__impl1 import (
    BURN_RATE_FAST,
    BURN_RATE_MEDIUM,
    BURN_RATE_SLOW,
    FAST_WINDOW_LONG,
    FAST_WINDOW_SHORT,
    MEDIUM_WINDOW_LONG,
    MEDIUM_WINDOW_SHORT,
    SLOW_WINDOW_LONG,
    SLOW_WINDOW_SHORT,
    _compute_burn_rate_thresholds,
    _parse_slo_config,
    _validate_slo_params,
)
from generators.observability.alerting__impl2 import (
    _panel_active_requests,
    _panel_burn_rate,
    _panel_error_budget_gauge,
    _panel_error_rate,
    _panel_latency_heatmap,
    _panel_latency_percentiles,
    _panel_request_rate,
    _row_panel,
)
from generators.observability.alerting__impl3 import _build_prometheus_rules


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
