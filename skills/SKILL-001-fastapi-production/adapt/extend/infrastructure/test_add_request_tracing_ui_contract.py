"""Generic tool-contract mutation coverage for add_request_tracing_ui.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_request_tracing_ui.py in the mutation
runner: ``--tests test_add_request_tracing_ui.py test_add_request_tracing_ui_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_request_tracing_ui import add_request_tracing_ui

    for check in SCAFFOLDABLE_CHECKS:
        check(add_request_tracing_ui, "add_request_tracing_ui")
