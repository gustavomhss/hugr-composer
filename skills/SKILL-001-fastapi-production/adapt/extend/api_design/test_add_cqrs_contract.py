"""Generic tool-contract mutation coverage for add_cqrs.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cqrs.py in the mutation
runner: ``--tests test_add_cqrs.py test_add_cqrs_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_cqrs import add_cqrs

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cqrs, "add_cqrs")
