"""Generic tool-contract mutation coverage for add_api_versioning.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_versioning.py in the mutation
runner: ``--tests test_add_api_versioning.py test_add_api_versioning_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_api_versioning import add_api_versioning

    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_versioning, "add_api_versioning")
