"""Generic tool-contract mutation coverage for add_rbac.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_rbac.py in the mutation
runner: ``--tests test_add_rbac.py test_add_rbac_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_rbac import add_rbac

    for check in SCAFFOLDABLE_CHECKS:
        check(add_rbac, "add_rbac")
