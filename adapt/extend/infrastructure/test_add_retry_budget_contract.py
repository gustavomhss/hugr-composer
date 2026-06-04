"""Generic tool-contract mutation coverage for add_retry_budget.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_retry_budget.py in the mutation
runner: ``--tests test_add_retry_budget.py test_add_retry_budget_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_retry_budget import add_retry_budget

    for check in SCAFFOLDABLE_CHECKS:
        check(add_retry_budget, "add_retry_budget")
