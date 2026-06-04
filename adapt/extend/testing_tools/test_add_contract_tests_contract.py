"""Generic tool-contract mutation coverage for add_contract_tests.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_contract_tests.py in the mutation
runner: ``--tests test_add_contract_tests.py test_add_contract_tests_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_contract_tests import add_contract_tests

    for check in SCAFFOLDABLE_CHECKS:
        check(add_contract_tests, "add_contract_tests")
