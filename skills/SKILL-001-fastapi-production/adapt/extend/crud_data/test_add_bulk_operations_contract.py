"""Generic tool-contract mutation coverage for add_bulk_operations.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_bulk_operations.py in the mutation
runner: ``--tests test_add_bulk_operations.py test_add_bulk_operations_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations

    for check in UNIVERSAL_CHECKS:
        check(add_bulk_operations, "add_bulk_operations")
