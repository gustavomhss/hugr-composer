"""Generic tool-contract mutation coverage for add_transactional_email.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_transactional_email.py in the mutation
runner: ``--tests test_add_transactional_email.py test_add_transactional_email_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_transactional_email import add_transactional_email

    for check in SCAFFOLDABLE_CHECKS:
        check(add_transactional_email, "add_transactional_email")
