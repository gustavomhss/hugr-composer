"""Generic tool-contract mutation coverage for add_data_seeder.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_seeder.py in the mutation
runner: ``--tests test_add_data_seeder.py test_add_data_seeder_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_data_seeder import add_data_seeder

    for check in SCAFFOLDABLE_CHECKS:
        check(add_data_seeder, "add_data_seeder")
