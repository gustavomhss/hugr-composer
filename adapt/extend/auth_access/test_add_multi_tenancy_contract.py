"""Generic tool-contract mutation coverage for add_multi_tenancy.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_multi_tenancy.py in the mutation
runner: ``--tests test_add_multi_tenancy.py test_add_multi_tenancy_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy

    for check in UNIVERSAL_CHECKS:
        check(add_multi_tenancy, "add_multi_tenancy")
