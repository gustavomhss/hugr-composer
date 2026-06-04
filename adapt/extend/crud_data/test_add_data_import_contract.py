"""Generic tool-contract mutation coverage for add_data_import.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_import.py in the mutation
runner: ``--tests test_add_data_import.py test_add_data_import_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_data_import import add_data_import

    for check in SCAFFOLDABLE_CHECKS:
        check(add_data_import, "add_data_import")
