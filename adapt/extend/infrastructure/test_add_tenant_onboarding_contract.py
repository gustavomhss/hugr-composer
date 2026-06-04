"""Generic tool-contract mutation coverage for add_tenant_onboarding.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_tenant_onboarding.py in the mutation
runner: ``--tests test_add_tenant_onboarding.py test_add_tenant_onboarding_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding

    for check in SCAFFOLDABLE_CHECKS:
        check(add_tenant_onboarding, "add_tenant_onboarding")
