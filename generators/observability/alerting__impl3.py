"""Internal implementation (part 3) for ``alerting`` — Prometheus alerts.

Split out of ``alerting.py`` to respect the 500-LOC cap.  Contains the five
multi-burn-rate alert definitions and the Prometheus rules assembler, building
on the constants and recording rules in ``alerting__impl1``.

Public symbols are re-exported from ``generators.observability.alerting`` —
import from there, not from this module.
"""

from __future__ import annotations

import textwrap

from generators.observability.alerting__impl1 import (
    BURN_RATE_FAST,
    BURN_RATE_MEDIUM,
    BURN_RATE_SLOW,
    ERROR_BUDGET_PAGE_THRESHOLD,
    LATENCY_FOR_MINUTES,
    _compute_burn_rate_thresholds,
    _recording_rules_block,
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
        _prometheus_rules_header(
            service_name, namespace, slo_availability, slo_latency_p99_ms, error_budget
        )
        + _recording_rules_block(service_name, error_budget)
        + "\n"
        + alerts_group
        + alerts_body
    )
