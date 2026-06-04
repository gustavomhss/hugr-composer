"""Generic tool-contract mutation coverage for add_temporal_workflow.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_temporal_workflow.py in the mutation
runner: ``--tests test_add_temporal_workflow.py test_add_temporal_workflow_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_temporal_workflow import add_temporal_workflow

    for check in SCAFFOLDABLE_CHECKS:
        check(add_temporal_workflow, "add_temporal_workflow")
