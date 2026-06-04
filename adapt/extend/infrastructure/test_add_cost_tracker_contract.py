"""Generic tool-contract mutation coverage for add_cost_tracker.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cost_tracker.py in the mutation
runner: ``--tests test_add_cost_tracker.py test_add_cost_tracker_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cost_tracker, "add_cost_tracker")
