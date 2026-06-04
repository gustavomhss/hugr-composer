"""Generic tool-contract mutation coverage for add_arq_worker.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_arq_worker.py in the mutation
runner: ``--tests test_add_arq_worker.py test_add_arq_worker_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_arq_worker import add_arq_worker

    for check in SCAFFOLDABLE_CHECKS:
        check(add_arq_worker, "add_arq_worker")
