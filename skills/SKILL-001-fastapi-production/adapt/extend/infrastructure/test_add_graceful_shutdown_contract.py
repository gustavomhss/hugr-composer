"""Generic tool-contract mutation coverage for add_graceful_shutdown.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graceful_shutdown.py in the mutation
runner: ``--tests test_add_graceful_shutdown.py test_add_graceful_shutdown_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_graceful_shutdown import add_graceful_shutdown

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graceful_shutdown, "add_graceful_shutdown")
