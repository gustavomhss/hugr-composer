"""Generic tool-contract mutation coverage for add_outbox_pattern.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_outbox_pattern.py in the mutation
runner: ``--tests test_add_outbox_pattern.py test_add_outbox_pattern_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern

    for check in SCAFFOLDABLE_CHECKS:
        check(add_outbox_pattern, "add_outbox_pattern")
