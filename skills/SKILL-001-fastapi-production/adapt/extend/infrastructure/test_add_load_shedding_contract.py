"""Generic tool-contract mutation coverage for add_load_shedding.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_load_shedding.py in the mutation
runner: ``--tests test_add_load_shedding.py test_add_load_shedding_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_load_shedding import add_load_shedding

    for check in SCAFFOLDABLE_CHECKS:
        check(add_load_shedding, "add_load_shedding")
