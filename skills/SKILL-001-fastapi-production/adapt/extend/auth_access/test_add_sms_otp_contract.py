"""Generic tool-contract mutation coverage for add_sms_otp.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sms_otp.py in the mutation
runner: ``--tests test_add_sms_otp.py test_add_sms_otp_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_sms_otp import add_sms_otp

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sms_otp, "add_sms_otp")
