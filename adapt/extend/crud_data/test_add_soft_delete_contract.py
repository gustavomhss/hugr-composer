"""Generic tool-contract mutation coverage for add_soft_delete.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_soft_delete.py in the mutation
runner: ``--tests test_add_soft_delete.py test_add_soft_delete_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    for check in SCAFFOLDABLE_CHECKS:
        check(add_soft_delete, "add_soft_delete")
