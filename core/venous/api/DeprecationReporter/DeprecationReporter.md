# DeprecationReporter

`DeprecationReporter` is the observability half of the deprecation toolkit: a
`defaultdict(int)` keyed by `'METHOD path'` with four verbs — `record`,
`get_count`, `usage_report`, and `reset`. Request middleware calls `record()`
once per hit on a deprecated endpoint (`DEPRECATION_REPORTER_INV_01`), and the
report endpoint dumps `usage_report()` which is sorted by call_count
descending so the hottest deprecated endpoint is always at the top
(`DEPRECATION_REPORTER_INV_03`) — that is the signal for "this endpoint must
not be retired on schedule, a consumer is still live."

Method casing is normalized on both write and read paths so `get` and `GET`
never fork the counter (`DEPRECATION_REPORTER_INV_01`), and `get_count()`
returns 0 for unknown keys rather than raising
(`DEPRECATION_REPORTER_INV_02`), making the reporter safe to call
optimistically from middleware without feature-flag guards. `reset()` is
provided primarily for tests and for operators who want a clean window after a
rollout (`DEPRECATION_REPORTER_INV_04`). Extracted from
`adapt/extend/api_design/add_api_deprecation.py` (lines 517–568).

## Compose with:

- **Sunset-date triage** → `DeprecationRegistry` + `DeprecationEntry`
  Reporter's usage_report joins with the registry's entries; the 'hottest deprecated endpoint' is obvious, and the scheduled Sunset date is one column away.

- **Metric-fed alerting** → `MetricMeter` + `HealthProbe`
  Counter values feed dashboards; high usage past a threshold flips a readiness-style warning for API product owners.

- **Audit trail of retirement** → `AuditEvent` + `StructuredLogger`
  Resets and Sunset enforcements are audited — there is no 'silent retirement' that support can't reconstruct.
