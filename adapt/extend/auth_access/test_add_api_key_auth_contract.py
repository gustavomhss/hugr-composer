"""Generic tool-contract mutation coverage for add_api_key_auth.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_key_auth.py in the mutation
runner: ``--tests test_add_api_key_auth.py test_add_api_key_auth_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_api_key_auth import add_api_key_auth

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_key_auth, "add_api_key_auth")
