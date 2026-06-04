"""Generic tool-contract mutation coverage for add_search.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_search.py in the mutation
runner: ``--tests test_add_search.py test_add_search_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_search import add_search

    for check in UNIVERSAL_CHECKS:
        check(add_search, "add_search")
