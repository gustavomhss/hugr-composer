"""Generic tool-contract mutation coverage for add_celery_beat.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_celery_beat.py in the mutation
runner: ``--tests test_add_celery_beat.py test_add_celery_beat_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_celery_beat import add_celery_beat

    for check in SCAFFOLDABLE_CHECKS:
        check(add_celery_beat, "add_celery_beat")
