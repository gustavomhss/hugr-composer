"""Generic tool-contract mutation coverage for add_notifications.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_notifications.py in the mutation
runner: ``--tests test_add_notifications.py test_add_notifications_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_notifications import add_notifications

    for check in SCAFFOLDABLE_CHECKS:
        check(add_notifications, "add_notifications")
