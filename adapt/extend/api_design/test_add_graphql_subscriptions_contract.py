"""Generic tool-contract mutation coverage for add_graphql_subscriptions.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graphql_subscriptions.py in the mutation
runner: ``--tests test_add_graphql_subscriptions.py test_add_graphql_subscriptions_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_graphql_subscriptions import add_graphql_subscriptions

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graphql_subscriptions, "add_graphql_subscriptions")
