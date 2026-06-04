"""Generic tool-contract mutation coverage for add_request_fingerprint.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_request_fingerprint.py in the mutation
runner: ``--tests test_add_request_fingerprint.py test_add_request_fingerprint_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint

    for check in SCAFFOLDABLE_CHECKS:
        check(add_request_fingerprint, "add_request_fingerprint")
