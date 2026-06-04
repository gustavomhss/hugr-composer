"""Generic tool-contract mutation coverage for add_push_notifications_native.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_push_notifications_native.py in the mutation
runner: ``--tests test_add_push_notifications_native.py test_add_push_notifications_native_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_push_notifications_native import (
        add_push_notifications_native,
    )

    for check in SCAFFOLDABLE_CHECKS:
        check(add_push_notifications_native, "add_push_notifications_native")
