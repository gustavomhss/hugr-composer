"""Generic tool-contract mutation coverage for add_cedar_policies.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cedar_policies.py in the mutation
runner: ``--tests test_add_cedar_policies.py test_add_cedar_policies_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_cedar_policies import add_cedar_policies

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cedar_policies, "add_cedar_policies")
