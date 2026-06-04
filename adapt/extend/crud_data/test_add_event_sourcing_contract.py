"""Generic tool-contract mutation coverage for add_event_sourcing.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_event_sourcing.py in the mutation
runner: ``--tests test_add_event_sourcing.py test_add_event_sourcing_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_event_sourcing, "add_event_sourcing")
