"""Generic tool-contract mutation coverage for add_scheduled_tasks.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_scheduled_tasks.py in the mutation
runner: ``--tests test_add_scheduled_tasks.py test_add_scheduled_tasks_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_scheduled_tasks import add_scheduled_tasks

    for check in SCAFFOLDABLE_CHECKS:
        check(add_scheduled_tasks, "add_scheduled_tasks")
