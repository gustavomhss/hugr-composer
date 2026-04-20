from __future__ import annotations
from pathlib import Path
import json


def register_slo_handlers() -> None:
    """Register SLO assertion event handlers with Locust.

    Call once at module import time in the locustfile so handlers are
    active for every test run.
    """

    @events.quitting.add_listener
    def _assert_slos(environment, **_kwargs: object) -> None:
        """Fail the run if any p99 latency target is violated.

        Args:
            environment: Locust ``Environment`` instance.
        """
        if isinstance(environment.runner, WorkerRunner):
            return
        slos = _load_slos()
        if not slos:
            logger.info('No SLO targets configured — skipping SLO assertions.')
            return
        violations: dict[str, dict] = {}
        for name, entry in environment.runner.stats.entries.items():
            label = f'{name[1]} {name[0]}'
            target = slos.get(label)
            if target is None:
                continue
            p99 = entry.get_response_time_percentile(0.99)
            if p99 and p99 > target:
                violations[label] = {'p99_actual_ms': round(p99, 1), 'p99_target_ms': target, 'delta_ms': round(p99 - target, 1)}
        if violations:
            logger.error('SLO violations detected:')
            for label, v in violations.items():
                logger.error('  %s  p99=%sms  target=%sms  delta=+%sms', label, v['p99_actual_ms'], v['p99_target_ms'], v['delta_ms'])
            out = Path('load_slo_violations.json')
            out.write_text(json.dumps(violations, indent=2))
            environment.process_exit_code = 1
        else:
            logger.info('All SLO targets met.')
