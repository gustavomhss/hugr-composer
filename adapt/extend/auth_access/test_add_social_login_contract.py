"""Generic tool-contract mutation coverage for add_social_login.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_social_login.py in the mutation
runner: ``--tests test_add_social_login.py test_add_social_login_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_social_login import add_social_login

    for check in SCAFFOLDABLE_CHECKS:
        check(add_social_login, "add_social_login")
