"""Generic tool-contract mutation coverage for add_adaptive_timeouts.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_adaptive_timeouts.py in the mutation
runner: ``--tests test_add_adaptive_timeouts.py test_add_adaptive_timeouts_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_adaptive_timeouts import add_adaptive_timeouts

    for check in SCAFFOLDABLE_CHECKS:
        check(add_adaptive_timeouts, "add_adaptive_timeouts")
