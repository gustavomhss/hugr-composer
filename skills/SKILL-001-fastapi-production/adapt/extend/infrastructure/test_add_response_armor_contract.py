"""Generic tool-contract mutation coverage for add_response_armor.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_response_armor.py in the mutation
runner: ``--tests test_add_response_armor.py test_add_response_armor_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_response_armor import add_response_armor

    for check in SCAFFOLDABLE_CHECKS:
        check(add_response_armor, "add_response_armor")
