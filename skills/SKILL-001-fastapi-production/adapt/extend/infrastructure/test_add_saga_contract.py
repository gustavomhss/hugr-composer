"""Generic tool-contract mutation coverage for add_saga.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_saga.py in the mutation
runner: ``--tests test_add_saga.py test_add_saga_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_saga import add_saga

    for check in SCAFFOLDABLE_CHECKS:
        check(add_saga, "add_saga")
