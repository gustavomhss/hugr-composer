"""Generic tool-contract mutation coverage for add_database_migrations_ci.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_database_migrations_ci.py in the mutation
runner: ``--tests test_add_database_migrations_ci.py test_add_database_migrations_ci_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_database_migrations_ci import add_database_migrations_ci

    for check in SCAFFOLDABLE_CHECKS:
        check(add_database_migrations_ci, "add_database_migrations_ci")
