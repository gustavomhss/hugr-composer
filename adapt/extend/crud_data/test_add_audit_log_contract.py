"""Generic tool-contract mutation coverage for add_audit_log.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_audit_log.py in the mutation
runner: ``--tests test_add_audit_log.py test_add_audit_log_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_audit_log import add_audit_log

    for check in SCAFFOLDABLE_CHECKS:
        check(add_audit_log, "add_audit_log")
