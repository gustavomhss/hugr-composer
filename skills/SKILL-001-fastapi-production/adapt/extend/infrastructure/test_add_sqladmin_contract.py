"""Generic tool-contract mutation coverage for add_sqladmin.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sqladmin.py in the mutation
runner: ``--tests test_add_sqladmin.py test_add_sqladmin_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_sqladmin import add_sqladmin

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sqladmin, "add_sqladmin")
