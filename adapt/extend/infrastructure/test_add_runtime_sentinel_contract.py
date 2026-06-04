"""Generic tool-contract mutation coverage for add_runtime_sentinel.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_runtime_sentinel.py in the mutation
runner: ``--tests test_add_runtime_sentinel.py test_add_runtime_sentinel_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_runtime_sentinel import add_runtime_sentinel

    for check in SCAFFOLDABLE_CHECKS:
        check(add_runtime_sentinel, "add_runtime_sentinel")
