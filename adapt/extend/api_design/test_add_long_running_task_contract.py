"""Generic tool-contract mutation coverage for add_long_running_task.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_long_running_task.py in the mutation
runner: ``--tests test_add_long_running_task.py test_add_long_running_task_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_long_running_task import add_long_running_task

    for check in SCAFFOLDABLE_CHECKS:
        check(add_long_running_task, "add_long_running_task")
