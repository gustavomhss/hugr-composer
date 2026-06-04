"""Generic tool-contract mutation coverage for add_api_fuzzer.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_fuzzer.py in the mutation
runner: ``--tests test_add_api_fuzzer.py test_add_api_fuzzer_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_api_fuzzer import add_api_fuzzer

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_fuzzer, "add_api_fuzzer")
