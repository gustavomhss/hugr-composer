"""Generic tool-contract mutation coverage for add_mfa.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_mfa.py in the mutation
runner: ``--tests test_add_mfa.py test_add_mfa_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_mfa import add_mfa

    for check in SCAFFOLDABLE_CHECKS:
        check(add_mfa, "add_mfa")
