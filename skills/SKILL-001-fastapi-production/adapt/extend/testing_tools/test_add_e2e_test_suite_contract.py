"""Generic tool-contract mutation coverage for add_e2e_test_suite.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_e2e_test_suite.py in the mutation
runner: ``--tests test_add_e2e_test_suite.py test_add_e2e_test_suite_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_e2e_test_suite import add_e2e_test_suite

    for check in SCAFFOLDABLE_CHECKS:
        check(add_e2e_test_suite, "add_e2e_test_suite")
