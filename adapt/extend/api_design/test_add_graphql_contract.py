"""Generic tool-contract mutation coverage for add_graphql.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graphql.py in the mutation
runner: ``--tests test_add_graphql.py test_add_graphql_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_graphql import add_graphql

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graphql, "add_graphql")
