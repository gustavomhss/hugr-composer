"""Generic tool-contract mutation coverage for add_chaos_testing.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_chaos_testing.py in the mutation
runner: ``--tests test_add_chaos_testing.py test_add_chaos_testing_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_chaos_testing import add_chaos_testing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_chaos_testing, "add_chaos_testing")
