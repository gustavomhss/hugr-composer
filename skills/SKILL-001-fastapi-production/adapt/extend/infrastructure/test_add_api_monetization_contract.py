"""Generic + tool-specific mutation coverage for add_api_monetization.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The tool-specific block below targets the
surviving operators unique to this tool: the config anchor/else insertion
branches, the alembic down-revision wiring, the requirements dedup branches,
the models-init import dedup BoolOp, and the billing-package __init__ guard.

Run alongside test_add_api_monetization.py in the mutation runner:
``--tests test_add_api_monetization.py test_add_api_monetization_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_api_monetization import (
    _patch_config,
    _patch_models_init,
    _patch_requirements,
    add_api_monetization,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_monetization, "add_api_monetization")


def _resolved_set(paths: list[str]) -> set[str]:
    return {str(Path(p).resolve()) for p in paths}


# ---------------------------------------------------------------------------
# L133: `if not billing_init.exists():` — the billing package __init__ guard.
# Flip drops the file entirely. Assert it is created and exists.
# ---------------------------------------------------------------------------


def test_billing_package_init_created() -> None:
    project_dir = create_fixture_project(name="mon_c_pkginit")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    billing_init = project_dir / "app" / "billing" / "__init__.py"
    assert str(billing_init.resolve()) in _resolved_set(result.files_created), (
        "app/billing/__init__.py must be reported in files_created"
    )
    assert billing_init.exists(), "app/billing/__init__.py must be written"
    assert "Billing and metering package" in billing_init.read_text()


# ---------------------------------------------------------------------------
# L272: `if anchor in content:` — config patch anchor branch. The fixture
# config HAS the ACCESS_TOKEN_EXPIRE_MINUTES anchor, so the METERING block
# must be inserted IMMEDIATELY after that anchor line (inside the class body).
# Flipping `in`->`not in` would route to the else branch and the block would
# not land right after the anchor.
# ---------------------------------------------------------------------------


def test_config_block_inserted_after_anchor() -> None:
    project_dir = create_fixture_project(name="mon_c_anchor")
    add_api_monetization(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    assert anchor in content
    after = content.split(anchor, 1)[1]
    # The very next config field after the anchor must be METERING_ENABLED,
    # and it must precede the rest of the file's content.
    assert "METERING_ENABLED" in after
    idx_metering = after.index("METERING_ENABLED")
    # Nothing but whitespace/comment lines between anchor and the injected
    # block — assert the block is within the first ~200 chars after anchor.
    assert idx_metering < 200, (
        f"METERING block not inserted right after anchor (offset={idx_metering})"
    )


# ---------------------------------------------------------------------------
# L276 + L279: config else-branch (no anchor present). Drive _patch_config
# directly on a Settings file that lacks the anchor but defines
# `settings = Settings()`. L276 `if settings_line in content` controls whether
# the block is written at all; L279 BinOp `block + "\n\n" + settings_line`
# controls the ORDER — the block must appear BEFORE `settings = Settings()`.
# ---------------------------------------------------------------------------


def test_config_else_branch_inserts_before_settings_instance(tmp_path) -> None:
    cfg = tmp_path / "config.py"
    cfg.write_text(
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        "    APP_NAME: str = 'x'\n\n\n"
        "settings = Settings()\n"
    )
    _patch_config(cfg)
    out = cfg.read_text()
    # L276: the block must be written (kills `not in` flip which would no-op).
    assert "METERING_ENABLED" in out, "config else-branch did not inject the block"
    # L279: block must precede the settings instantiation (Settings must be
    # fully declared before it is instantiated, else NameError on the fields).
    assert out.index("METERING_ENABLED") < out.index("settings = Settings()"), (
        "METERING block must be inserted BEFORE `settings = Settings()`"
    )


def test_config_else_branch_skips_when_no_settings_instance(tmp_path) -> None:
    # L276 false-branch: no `settings = Settings()` anchor and no
    # ACCESS_TOKEN anchor -> nothing is written (block stays absent).
    cfg = tmp_path / "config.py"
    cfg.write_text("# empty config, no Settings instance\nFOO = 1\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "METERING_ENABLED" not in out, "block must NOT be written when neither anchor is present"


# ---------------------------------------------------------------------------
# L171 (`find_migration_head(...) or None`) and L181 (`down_rev or ""`):
# the alembic migration must wire its down_revision/Revises to the REAL
# migration head from the fixture. The fixture head is `0002_baseline_schema`.
# Mutating the `or` BoolOps would null out down_rev and break this wiring.
# ---------------------------------------------------------------------------


def test_migration_wires_down_revision_to_head() -> None:
    from adapt.contracts.migration_helper import find_migration_head

    project_dir = create_fixture_project(name="mon_c_migr")
    versions = project_dir / "alembic" / "versions"
    # Capture the head BEFORE the tool runs — afterwards find_migration_head
    # would return the freshly-emitted 0_add_usage_records migration instead.
    head = find_migration_head(versions)
    assert head, "fixture should have a migration head"
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    migration = versions / "0_add_usage_records.py"
    assert migration.exists(), "alembic migration not emitted"
    text = migration.read_text()
    # L171: down_revision must be the head string, not None.
    assert f'down_revision: str | None = "{head}"' in text, (
        f"migration down_revision must reference head {head!r}; got:\n{text}"
    )
    # L181: the Revises docstring substitution must carry the head, not "".
    assert f"Revises: {head}" in text, f"migration docstring must reference head {head!r}"


# ---------------------------------------------------------------------------
# L298: `if "stripe>=" not in content:` — requirements add path. The fixture
# requirements lacks `stripe>=`, so stripe must be appended. Flip -> stripe
# would NOT be added.
# ---------------------------------------------------------------------------


def test_requirements_stripe_added_when_absent() -> None:
    project_dir = create_fixture_project(name="mon_c_req")
    result = add_api_monetization(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    req = (project_dir / "requirements.txt").read_text()
    assert "stripe>=" in req, "stripe dependency must be appended to requirements.txt"


def test_requirements_stripe_not_duplicated_when_present(tmp_path) -> None:
    # L298 dedup direction: when stripe is already present it must NOT be
    # appended again. Drive the helper directly for a deterministic file.
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110\nstripe>=7.0.0\n")
    _patch_requirements(req)
    out = req.read_text()
    assert out.count("stripe>=") == 1, "stripe must not be duplicated"


# ---------------------------------------------------------------------------
# L300: `if "httpx>=" not in content:` — httpx add path. Drive the helper on a
# requirements file WITHOUT httpx so the add branch runs (the fixture already
# ships httpx). Also assert dedup when present.
# ---------------------------------------------------------------------------


def test_requirements_httpx_added_when_absent(tmp_path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110\n")
    _patch_requirements(req)
    out = req.read_text()
    assert "httpx>=" in out, "httpx must be appended when absent"


def test_requirements_httpx_not_duplicated_when_present(tmp_path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.110\nhttpx>=0.28.0\nstripe>=7.0.0\n")
    _patch_requirements(req)
    out = req.read_text()
    assert out.count("httpx>=") == 1, "httpx must not be duplicated"


# ---------------------------------------------------------------------------
# L252: `if import_line not in content and <bare> not in content:` — the
# models-init import dedup BoolOp (And->Or survivor). When the bare import is
# already present (with a different trailing comment), the And-form must still
# treat it as present and NOT re-add it; the Or-form would re-add a duplicate.
# Drive the helper directly with a pre-existing bare import line.
# ---------------------------------------------------------------------------


def test_models_init_dedup_respects_bare_existing_import(tmp_path) -> None:
    models_init = tmp_path / "__init__.py"
    # Bare import already present WITHOUT the noqa-F401 suffix that the
    # helper would add. The first clause (`import_line not in content`) is True
    # (the suffixed form is absent) but the second clause (bare form not in
    # content) is False -> And -> skip. Or-flip would re-add the import.
    models_init.write_text(
        '"""models package"""\nfrom app.models.usage_record import UsageRecord\n'
    )
    _patch_models_init(models_init, [("usage_record", "UsageRecord")])
    out = models_init.read_text()
    assert out.count("from app.models.usage_record import UsageRecord") == 1, (
        "import must not be duplicated when a bare form already exists"
    )


def test_models_init_adds_import_when_absent(tmp_path) -> None:
    models_init = tmp_path / "__init__.py"
    models_init.write_text('"""models package"""\n')
    _patch_models_init(models_init, [("usage_record", "UsageRecord")])
    out = models_init.read_text()
    assert "from app.models.usage_record import UsageRecord" in out, (
        "import must be added when absent"
    )
