"""Generic tool-contract mutation coverage for add_api_monetization.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_monetization.py in the mutation
runner: ``--tests test_add_api_monetization.py test_add_api_monetization_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_api_monetization import add_api_monetization

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_monetization, "add_api_monetization")
