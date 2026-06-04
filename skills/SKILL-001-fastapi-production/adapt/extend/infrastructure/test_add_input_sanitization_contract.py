"""Generic tool-contract mutation coverage for add_input_sanitization.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_input_sanitization.py in the mutation
runner: ``--tests test_add_input_sanitization.py test_add_input_sanitization_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_input_sanitization import add_input_sanitization

    for check in SCAFFOLDABLE_CHECKS:
        check(add_input_sanitization, "add_input_sanitization")
