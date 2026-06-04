"""Generic tool-contract mutation coverage for add_cursor_pagination.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cursor_pagination.py in the mutation
runner: ``--tests test_add_cursor_pagination.py test_add_cursor_pagination_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_cursor_pagination import add_cursor_pagination

    for check in UNIVERSAL_CHECKS:
        check(add_cursor_pagination, "add_cursor_pagination")
