"""Generic tool-contract mutation coverage for add_pdf_reports.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_pdf_reports.py in the mutation
runner: ``--tests test_add_pdf_reports.py test_add_pdf_reports_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_pdf_reports import add_pdf_reports

    for check in SCAFFOLDABLE_CHECKS:
        check(add_pdf_reports, "add_pdf_reports")
