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

Implementation note
-------------------
The implementation is split across four internal modules to keep each file
under the 500-LOC cap: ``alerting__impl1`` (constants, SLO config, burn-rate
math, recording rules), ``alerting__impl2`` (Grafana panel builders),
``alerting__impl3`` (Prometheus alerts + rules assembler), and
``alerting__impl4`` (dashboard assembler, file writers, ``generate_alerting``
entry point).  This module re-exports the public API so
``from generators.observability.alerting import X`` is unchanged.
"""

from __future__ import annotations

import json  # noqa: F401  (re-exported: part of historical module surface)
import textwrap  # noqa: F401  (re-exported: part of historical module surface)
from pathlib import Path  # noqa: F401  (re-exported: part of historical module surface)

from generators.observability.alerting__impl1 import (
    BURN_RATE_FAST,
    BURN_RATE_MEDIUM,
    BURN_RATE_SLOW,
    ERROR_BUDGET_PAGE_THRESHOLD,
    FAST_WINDOW_LONG,
    FAST_WINDOW_SHORT,
    LATENCY_FOR_MINUTES,
    MEDIUM_WINDOW_LONG,
    MEDIUM_WINDOW_SHORT,
    SLOW_WINDOW_LONG,
    SLOW_WINDOW_SHORT,
)
from generators.observability.alerting__impl4 import generate_alerting

MCP_TOOL = {
    'name': 'fastapi_observability_generate_alerting',
    'description': 'Generate PrometheusRule alerts (5 rules) and Grafana dashboard (4 panels).',
    'tags': ['generator', 'observability'],
    'entry': 'generate_alerting',
}

__all__ = [
    "MCP_TOOL",
    "generate_alerting",
    "BURN_RATE_FAST",
    "BURN_RATE_MEDIUM",
    "BURN_RATE_SLOW",
    "ERROR_BUDGET_PAGE_THRESHOLD",
    "FAST_WINDOW_LONG",
    "FAST_WINDOW_SHORT",
    "LATENCY_FOR_MINUTES",
    "MEDIUM_WINDOW_LONG",
    "MEDIUM_WINDOW_SHORT",
    "SLOW_WINDOW_LONG",
    "SLOW_WINDOW_SHORT",
]
