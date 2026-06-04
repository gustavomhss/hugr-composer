"""Generic tool-contract mutation coverage for add_schema_enforcer.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_schema_enforcer.py in the mutation
runner: ``--tests test_add_schema_enforcer.py test_add_schema_enforcer_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer

    for check in SCAFFOLDABLE_CHECKS:
        check(add_schema_enforcer, "add_schema_enforcer")
