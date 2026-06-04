"""Generic tool-contract mutation coverage for add_dlp_shield.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dlp_shield.py in the mutation
runner: ``--tests test_add_dlp_shield.py test_add_dlp_shield_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_dlp_shield import add_dlp_shield

    for check in SCAFFOLDABLE_CHECKS:
        check(add_dlp_shield, "add_dlp_shield")
