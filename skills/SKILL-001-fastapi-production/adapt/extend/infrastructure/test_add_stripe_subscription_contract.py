"""Generic tool-contract mutation coverage for add_stripe_subscription.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_stripe_subscription.py in the mutation
runner: ``--tests test_add_stripe_subscription.py test_add_stripe_subscription_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_stripe_subscription import add_stripe_subscription

    for check in SCAFFOLDABLE_CHECKS:
        check(add_stripe_subscription, "add_stripe_subscription")
