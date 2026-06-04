"""Generic tool-contract mutation coverage for add_opa_integration.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_opa_integration.py in the mutation
runner: ``--tests test_add_opa_integration.py test_add_opa_integration_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_opa_integration import add_opa_integration

    for check in SCAFFOLDABLE_CHECKS:
        check(add_opa_integration, "add_opa_integration")
