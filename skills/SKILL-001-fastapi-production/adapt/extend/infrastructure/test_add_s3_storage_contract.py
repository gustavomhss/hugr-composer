"""Generic tool-contract mutation coverage for add_s3_storage.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_s3_storage.py in the mutation
runner: ``--tests test_add_s3_storage.py test_add_s3_storage_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_s3_storage import add_s3_storage

    for check in SCAFFOLDABLE_CHECKS:
        check(add_s3_storage, "add_s3_storage")
