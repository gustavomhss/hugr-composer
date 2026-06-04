"""Generic tool-contract mutation coverage for add_circuit_breaker.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_circuit_breaker.py in the mutation
runner: ``--tests test_add_circuit_breaker.py test_add_circuit_breaker_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker

    for check in SCAFFOLDABLE_CHECKS:
        check(add_circuit_breaker, "add_circuit_breaker")
