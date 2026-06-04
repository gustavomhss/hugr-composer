"""Generic tool-contract mutation coverage for add_sbom_guardian.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sbom_guardian.py in the mutation
runner: ``--tests test_add_sbom_guardian.py test_add_sbom_guardian_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_sbom_guardian import add_sbom_guardian

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sbom_guardian, "add_sbom_guardian")
