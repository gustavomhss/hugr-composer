"""Generic tool-contract mutation coverage for add_file_upload.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_file_upload.py in the mutation
runner: ``--tests test_add_file_upload.py test_add_file_upload_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_file_upload import add_file_upload

    for check in SCAFFOLDABLE_CHECKS:
        check(add_file_upload, "add_file_upload")
