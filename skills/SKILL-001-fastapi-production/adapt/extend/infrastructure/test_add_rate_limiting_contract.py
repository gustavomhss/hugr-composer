"""Generic tool-contract mutation coverage for add_rate_limiting.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_rate_limiting.py in the mutation
runner: ``--tests test_add_rate_limiting.py test_add_rate_limiting_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_rate_limiting import add_rate_limiting

    for check in SCAFFOLDABLE_CHECKS:
        check(add_rate_limiting, "add_rate_limiting")
