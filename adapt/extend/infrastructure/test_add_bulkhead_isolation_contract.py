"""Generic tool-contract mutation coverage for add_bulkhead_isolation.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_bulkhead_isolation.py in the mutation
runner: ``--tests test_add_bulkhead_isolation.py test_add_bulkhead_isolation_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_bulkhead_isolation import add_bulkhead_isolation

    for check in SCAFFOLDABLE_CHECKS:
        check(add_bulkhead_isolation, "add_bulkhead_isolation")
