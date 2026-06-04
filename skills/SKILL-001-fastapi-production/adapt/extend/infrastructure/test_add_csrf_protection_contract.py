"""Generic tool-contract mutation coverage for add_csrf_protection.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_csrf_protection.py in the mutation
runner: ``--tests test_add_csrf_protection.py test_add_csrf_protection_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_csrf_protection import add_csrf_protection

    for check in SCAFFOLDABLE_CHECKS:
        check(add_csrf_protection, "add_csrf_protection")
