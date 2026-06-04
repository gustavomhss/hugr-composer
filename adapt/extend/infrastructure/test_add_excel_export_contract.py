"""Generic tool-contract mutation coverage for add_excel_export.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_excel_export.py in the mutation
runner: ``--tests test_add_excel_export.py test_add_excel_export_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_excel_export import add_excel_export

    for check in SCAFFOLDABLE_CHECKS:
        check(add_excel_export, "add_excel_export")
