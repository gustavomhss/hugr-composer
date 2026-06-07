"""Internal implementation (part 1) for ``alerting`` — SLO + recording rules.

Split out of ``alerting.py`` to respect the 500-LOC cap.  Contains the
burn-rate constants, SLO-config helpers, burn-rate math, and the Prometheus
recording rules.  Alert definitions and the Prometheus rules assembler live in
``alerting__impl3``.

Public symbols are re-exported from ``generators.observability.alerting`` —
import from there, not from this module.
"""

from __future__ import annotations

import textwrap

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
FAST_WINDOW_SHORT: str = "5m"  # 1h / 12 ~= 5m

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
            f"slo_availability must be between 0 and 1 (exclusive), got {slo_availability}"
        )
    if slo_latency_p99_ms <= 0:
        raise ValueError(f"slo_latency_p99_ms must be positive, got {slo_latency_p99_ms}")


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
