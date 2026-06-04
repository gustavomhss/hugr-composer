"""Generic tool-contract mutation coverage for add_opentelemetry.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_opentelemetry.py in the mutation
runner: ``--tests test_add_opentelemetry.py test_add_opentelemetry_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_opentelemetry import add_opentelemetry

    for check in SCAFFOLDABLE_CHECKS:
        check(add_opentelemetry, "add_opentelemetry")
