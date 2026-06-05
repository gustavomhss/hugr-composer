"""Generic tool-contract mutation coverage for add_structured_logging.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_structured_logging.py in the mutation
runner: ``--tests test_add_structured_logging.py test_add_structured_logging_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_structured_logging import add_structured_logging
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_structured_logging, "add_structured_logging")


# ---------------------------------------------------------------------------
# Tool-specific mutation coverage (kills survivors the generic preamble misses)
# ---------------------------------------------------------------------------


def test_config_fields_land_directly_after_redis_anchor():
    """L198 In->NotIn, L199 anchor insertion: with the REDIS_URL anchor present
    (the default fixture shape), the LOG_* block must be spliced *immediately*
    after that anchor line — not via any fallback branch. If `anchor in src`
    flips to NotIn, the tool skips the anchor branch and lands the fields
    elsewhere, breaking this adjacency assertion.
    """
    project = create_fixture_project(name="slog_anchor")
    add_structured_logging(ToolInput(project_dir=str(project)))
    config = (project / "app" / "core" / "config.py").read_text()

    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    assert anchor in config
    after_anchor = config.split(anchor, 1)[1]
    # The injected block (its comment header) must be the very next content
    # after the anchor — i.e. before any other Settings field reappears.
    log_pos = after_anchor.index("LOG_LEVEL")
    header_pos = after_anchor.index("Structured logging — added by add_structured_logging tool")
    # header precedes the field
    assert header_pos < log_pos
    # The injected block is spliced immediately after the anchor: the post-anchor
    # slice begins with the block's comment header, not with any other Settings
    # field. (Under In->NotIn the block lands elsewhere and SMTP_TLS shows first.)
    expected_prefix = "\n    # Structured logging — added by add_structured_logging tool"
    assert after_anchor.startswith(expected_prefix), (
        f"LOG_* block not spliced directly after anchor; got: {after_anchor[:80]!r}"
    )


def test_config_decorator_fallback_branch():
    """L202 In->NotIn + L204 Add->Sub: when there is NO REDIS_URL anchor but a
    `@computed_field`/`@model_validator`/`@property` decorator IS present, the
    LOG_* block must be inserted *before* that decorator. The string concat at
    L204 (`src[:pos] + new_fields + ...`) would raise TypeError under Add->Sub,
    and `decorator in src` flipping to NotIn skips this branch entirely.
    """
    project = create_fixture_project(name="slog_dec")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text(
        "class Settings:\n"
        '    APP: str = "x"\n'
        "\n"
        "    @computed_field\n"
        "    def foo(self):\n"
        "        return 1\n"
        "\n"
        "settings = Settings()\n"
    )
    result = add_structured_logging(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = config_file.read_text()
    assert "LOG_LEVEL" in out
    # Injected block must precede the decorator it was inserted before.
    assert out.index("LOG_LEVEL") < out.index("@computed_field")
    assert out.index("LOG_REDACTION_ENABLED") < out.index("@computed_field")


def test_config_marker_fallback_branch():
    """L208 In->NotIn + L209 Add->Sub: with NO anchor and NO decorator but the
    `settings = Settings()` marker present, the LOG_* block must be inserted
    *before* that marker. Add->Sub on the `new_fields + "\\n" + marker` concat
    raises TypeError; In->NotIn skips this branch.
    """
    project = create_fixture_project(name="slog_marker")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text('class Settings:\n    APP: str = "x"\n\nsettings = Settings()\n')
    result = add_structured_logging(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = config_file.read_text()
    assert "LOG_LEVEL" in out
    assert out.index("LOG_LEVEL") < out.index("settings = Settings()")
    assert out.index("LOG_REDACTION_ENABLED") < out.index("settings = Settings()")


def test_config_final_append_fallback_branch():
    """L211 Add->Sub: with NONE of the anchors/decorators/marker present, the
    LOG_* block is appended to the end of the file via
    `src.rstrip("\\n") + new_fields + "\\n"`. Add->Sub raises TypeError, so the
    success + appended-block assertion fails under the mutant.
    """
    project = create_fixture_project(name="slog_append")
    config_file = project / "app" / "core" / "config.py"
    config_file.write_text('class Settings:\n    APP: str = "x"\n')
    result = add_structured_logging(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = config_file.read_text()
    assert "LOG_LEVEL" in out
    # Original APP field stays first; injected block lands after it (appended).
    assert out.index("APP") < out.index("LOG_LEVEL")
    assert out.rstrip().endswith("LOG_REDACTION_ENABLED: bool = True")


def test_main_logging_import_lands_after_fastapi_import():
    """L253 In->NotIn: when `from fastapi import FastAPI` is present (default
    fixture), the logging import is spliced right after it (not prepended via
    the L259 else branch). In->NotIn would route to the prepend path, putting
    the logging import at the very top instead of after the FastAPI import.
    """
    project = create_fixture_project(name="slog_mainimp")
    add_structured_logging(ToolInput(project_dir=str(project)))
    main = (project / "app" / "main.py").read_text()
    fastapi_pos = main.index("from fastapi import FastAPI")
    logging_pos = main.index("from app.logging.setup import configure_structlog")
    assert logging_pos > fastapi_pos, "logging import must follow the FastAPI import"
    # And it must be the FastAPI import that comes first in the file (not the
    # prepended-at-top shape the else branch produces).
    assert not main.lstrip().startswith("from app.logging.setup")


def test_main_logging_import_prepended_when_no_fastapi_import():
    """L259 Add->Sub (`src = logging_import + src` else branch): for a main.py
    WITHOUT `from fastapi import FastAPI`, the logging import is prepended to
    the top of the file. Add->Sub raises TypeError on the str concat, so this
    branch's success + leading-import assertion fails under the mutant.
    """
    project = create_fixture_project(name="slog_noimp")
    main_file = project / "app" / "main.py"
    main_file.write_text("app = object()\n")
    result = add_structured_logging(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = main_file.read_text()
    assert out.lstrip().startswith("from app.logging.setup import configure_structlog")
    assert "app = object()" in out


def test_main_configure_call_spliced_directly_before_yield():
    """L269 Eq->NotEq + L271 NotEq->Eq: with `lifespan(...)` containing a
    `yield`, the `_configure_structlog(...)` startup block is inserted on the
    lines *immediately before* that yield.

    - L269 (`ln.strip() == "yield"`) flipping to NotEq makes the generator
      match the first non-yield line, splicing the block in the wrong place.
    - L271 (`yield_idx != -1`) flipping to Eq routes to the module-top
      fallback (adding the `pragma: B0.15` line) instead of the lifespan splice.
    """
    project = create_fixture_project(name="slog_lifespan")
    add_structured_logging(ToolInput(project_dir=str(project)))
    main = (project / "app" / "main.py").read_text()
    lines = main.splitlines()
    yield_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "yield")
    # The line right before `yield` must be the closing `)` of the spliced call,
    # and the configure call header must sit just above it.
    assert lines[yield_idx - 1].strip() == ")"
    window = "\n".join(lines[max(0, yield_idx - 7) : yield_idx])
    assert "_configure_structlog(" in window
    assert "add_structured_logging: configure structlog (B0.15)" in window
    # Lifespan path taken → NO module-top pragma fallback line emitted.
    assert "pragma: B0.15" not in main


def test_main_fallback_pragma_when_no_yield():
    """L271 NotEq->Eq + L307 Add->Sub: a main.py WITHOUT a `yield` (no standard
    lifespan) takes the fallback branch, which appends a module-top
    `_configure_structlog(...)` call carrying the `# pragma: B0.15` marker via
    `src.rstrip("\\n") + fallback`. Add->Sub raises TypeError on the concat;
    this asserts the pragma-bearing fallback line is present and parseable.
    """
    project = create_fixture_project(name="slog_noyield")
    main_file = project / "app" / "main.py"
    main_file.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    result = add_structured_logging(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = main_file.read_text()
    assert "pragma: B0.15" in out
    assert "_configure_structlog(" in out
    # The original content is preserved ahead of the appended fallback.
    assert out.index("app = FastAPI()") < out.index("_configure_structlog(")
