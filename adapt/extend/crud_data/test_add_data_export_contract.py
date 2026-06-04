"""Generic tool-contract mutation coverage for add_data_export.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_export.py in the mutation
runner: ``--tests test_add_data_export.py test_add_data_export_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_data_export import add_data_export

    for check in UNIVERSAL_CHECKS:
        check(add_data_export, "add_data_export")
