"""Generic tool-contract mutation coverage for add_request_signing.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_request_signing.py in the mutation
runner: ``--tests test_add_request_signing.py test_add_request_signing_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_request_signing import add_request_signing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_request_signing, "add_request_signing")
