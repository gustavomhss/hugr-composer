"""Generic tool-contract mutation coverage for add_stripe_refund_flow.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_stripe_refund_flow.py in the mutation
runner: ``--tests test_add_stripe_refund_flow.py test_add_stripe_refund_flow_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_stripe_refund_flow import add_stripe_refund_flow

    for check in SCAFFOLDABLE_CHECKS:
        check(add_stripe_refund_flow, "add_stripe_refund_flow")
