"""Generic tool-contract mutation coverage for add_email_templates.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_email_templates.py in the mutation
runner: ``--tests test_add_email_templates.py test_add_email_templates_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_email_templates import add_email_templates

    for check in SCAFFOLDABLE_CHECKS:
        check(add_email_templates, "add_email_templates")
