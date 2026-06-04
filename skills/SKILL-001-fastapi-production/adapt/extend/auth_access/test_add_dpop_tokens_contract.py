"""Generic tool-contract mutation coverage for add_dpop_tokens.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dpop_tokens.py in the mutation
runner: ``--tests test_add_dpop_tokens.py test_add_dpop_tokens_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_dpop_tokens import add_dpop_tokens

    for check in SCAFFOLDABLE_CHECKS:
        check(add_dpop_tokens, "add_dpop_tokens")
