"""Generic tool-contract mutation coverage for add_prometheus_metrics.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_prometheus_metrics.py in the mutation
runner: ``--tests test_add_prometheus_metrics.py test_add_prometheus_metrics_contract.py``.

The ``test_logic_*`` functions below target this tool's BESPOKE logic
(config/main patchers, requirements dedup) — the survivors the generic
preamble checks cannot reach.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_prometheus_metrics import add_prometheus_metrics
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_prometheus_metrics import add_prometheus_metrics

    for check in SCAFFOLDABLE_CHECKS:
        check(add_prometheus_metrics, "add_prometheus_metrics")


# ---------------------------------------------------------------------------
# Bare-project builder — gives precise control over config.py / main.py shape
# so each anchor branch can be driven deterministically.
# ---------------------------------------------------------------------------


def _bare_project(config_src: str, main_src: str, req_src: str = "fastapi\n") -> Path:
    """Build a minimal project tree with caller-supplied config/main content."""
    d = Path(tempfile.mkdtemp())
    (d / "app" / "core").mkdir(parents=True)
    (d / "app" / "__init__.py").write_text("")
    (d / "app" / "core" / "__init__.py").write_text("")
    (d / "app" / "core" / "config.py").write_text(config_src)
    (d / "app" / "main.py").write_text(main_src)
    (d / "requirements.txt").write_text(req_src)
    return d


_REDIS_CONFIG = (
    'class Settings:\n    REDIS_URL: str = "redis://localhost:6379/0"\n\nsettings = Settings()\n'
)
_DECORATOR_CONFIG = (
    "class Settings:\n"
    '    APP_NAME: str = "x"\n'
    "\n"
    "    @property\n"
    "    def foo(self):\n"
    "        return 1\n"
    "\n"
    "settings = Settings()\n"
)
_MARKER_CONFIG = 'class Settings:\n    APP_NAME: str = "x"\n\nsettings = Settings()\n'

_FASTAPI_IMPORT_MAIN = "from fastapi import FastAPI\napp = FastAPI()\n"
_LIFESPAN_MAIN = (
    "from fastapi import FastAPI\n"
    "\n"
    "async def lifespan(app):\n"
    '    print("start")\n'
    "    yield\n"
    '    print("stop")\n'
    "\n"
    "app = FastAPI(lifespan=lifespan)\n"
)
_NO_IMPORT_MAIN = (
    "import fastapi\n"
    "\n"
    "async def lifespan(app):\n"
    '    print("start")\n'
    "    yield\n"
    '    print("stop")\n'
    "\n"
    "app = fastapi.FastAPI(lifespan=lifespan)\n"
)
_NO_LIFESPAN_MAIN = "import fastapi\napp = fastapi.FastAPI()\n"


# ---------------------------------------------------------------------------
# L194  Compare In->NotIn — REDIS_URL anchor placement in config.py
# ---------------------------------------------------------------------------


def test_logic_config_fields_land_right_after_redis_anchor():
    d = _bare_project(_REDIS_CONFIG, _FASTAPI_IMPORT_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    cfg = (d / "app" / "core" / "config.py").read_text()
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    # The new fields must be spliced IMMEDIATELY after the REDIS_URL line.
    # If In->NotIn flips, the anchor replace is skipped and the fields land
    # elsewhere (decorator/marker fallback), so the substring below breaks.
    assert anchor + "\n    # Prometheus metrics" in cfg
    assert "PROMETHEUS_ENABLED: bool = True" in cfg


# ---------------------------------------------------------------------------
# L197/L198  Compare In->NotIn — decorator fallback when no REDIS anchor
# ---------------------------------------------------------------------------


def test_logic_config_fields_precede_decorator_fallback():
    d = _bare_project(_DECORATOR_CONFIG, _FASTAPI_IMPORT_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    cfg = (d / "app" / "core" / "config.py").read_text()
    assert "PROMETHEUS_ENABLED: bool = True" in cfg
    # No REDIS anchor present → fields must be inserted BEFORE the @property
    # decorator. If In->NotIn flips on the decorator probe, the fields fall
    # through to the marker/EOF path and land after @property instead.
    assert cfg.index("PROMETHEUS_ENABLED") < cfg.index("@property")


# ---------------------------------------------------------------------------
# L203/L204  Compare In->NotIn — marker fallback when no REDIS & no decorator
# ---------------------------------------------------------------------------


def test_logic_config_fields_precede_settings_marker_fallback():
    d = _bare_project(_MARKER_CONFIG, _FASTAPI_IMPORT_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    cfg = (d / "app" / "core" / "config.py").read_text()
    assert "PROMETHEUS_ENABLED: bool = True" in cfg
    # No anchor, no decorator → fields inserted BEFORE `settings = Settings()`.
    assert cfg.index("PROMETHEUS_ENABLED") < cfg.index("settings = Settings()")


# ---------------------------------------------------------------------------
# L136  Compare NotIn->In — requirements.txt dedup of prometheus-client
# ---------------------------------------------------------------------------


def test_logic_requirements_gets_prometheus_client_added():
    d = _bare_project(_MARKER_CONFIG, _FASTAPI_IMPORT_MAIN, req_src="fastapi\n")
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    req = (d / "requirements.txt").read_text()
    # NotIn guard: prometheus-client is absent → must be appended exactly once.
    assert req.count("prometheus-client") == 1
    assert "prometheus-client>=0.20.0" in req


def test_logic_requirements_not_duplicated_when_already_present():
    # prometheus-client already pinned → dedup guard must NOT re-append.
    # If NotIn->In flips, the tool would only write when ALREADY present,
    # producing a second line.
    d = _bare_project(
        _MARKER_CONFIG,
        _FASTAPI_IMPORT_MAIN,
        req_src="fastapi\nprometheus-client>=0.20.0\n",
    )
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    req = (d / "requirements.txt").read_text()
    assert req.count("prometheus-client") == 1
    # requirements.txt must NOT be reported as modified — nothing changed.
    assert not any(p.endswith("requirements.txt") for p in r.files_modified)


# ---------------------------------------------------------------------------
# L241  Compare In->NotIn — metrics import spliced after `from fastapi import FastAPI`
# ---------------------------------------------------------------------------


def test_logic_metrics_import_follows_fastapi_import():
    d = _bare_project(_MARKER_CONFIG, _FASTAPI_IMPORT_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    # Import present → metrics import block spliced DIRECTLY after the
    # `from fastapi import FastAPI` line (not prepended at module top).
    assert (
        "from fastapi import FastAPI\nfrom app.metrics.middleware import PrometheusMiddleware"
    ) in main


# ---------------------------------------------------------------------------
# L247  BinOp Add->Sub — fallback prepend when no FastAPI import line
# ---------------------------------------------------------------------------


def test_logic_metrics_import_prepended_when_no_fastapi_import():
    d = _bare_project(_MARKER_CONFIG, _NO_IMPORT_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    # `from fastapi import FastAPI` absent → fallback does `metrics_import + src`.
    # Add->Sub would raise TypeError (str - str) → tool would error/crash.
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    # Metrics import block must be prepended at the very top, ahead of the
    # original `import fastapi`.
    assert main.index("from app.metrics.middleware import PrometheusMiddleware") < main.index(
        "import fastapi"
    )


# ---------------------------------------------------------------------------
# L257  Compare Eq->NotEq — locate the `yield` line inside lifespan
# L259  Compare NotEq->Eq — splice path taken when yield found
# L261  BinOp Sub->Add — indentation of spliced startup lines
# L268  BinOp Add->Sub — ordering of the three startup lines
# ---------------------------------------------------------------------------


def test_logic_init_metrics_spliced_inside_lifespan_before_yield():
    d = _bare_project(_MARKER_CONFIG, _LIFESPAN_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    lines = main.splitlines()
    yield_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "yield")
    init_idx = next(i for i, ln in enumerate(lines) if "_init_metrics(prefix=" in ln)
    # L257/L259: init must be spliced BEFORE the yield (inside the lifespan
    # body), not after / at module top.
    assert init_idx < yield_idx
    # L261: spliced lines carry the SAME 4-space indentation as the yield
    # (inside the async-def body). Sub->Add corrupts the indent slice.
    init_line = lines[init_idx]
    assert init_line.startswith("    _init_metrics(prefix=_prom_prefix)")
    assert not init_line.startswith("     ")  # exactly 4 spaces, not more


def test_logic_startup_lines_inserted_in_order():
    d = _bare_project(_MARKER_CONFIG, _LIFESPAN_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    comment_pos = main.index("# --- add_prometheus_metrics: registry startup")
    prefix_pos = main.index('_prom_prefix = _prom_os.getenv("PROMETHEUS_PREFIX"')
    init_pos = main.index("_init_metrics(prefix=_prom_prefix)")
    # L268 Add->Sub reverses the insertion offsets → the three lines would
    # appear in reverse. Assert strict comment < prefix < init ordering.
    assert comment_pos < prefix_pos < init_pos


def test_logic_lifespan_path_emits_no_module_top_fallback():
    d = _bare_project(_MARKER_CONFIG, _LIFESPAN_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    # L259 NotEq->Eq: when a yield IS found, the lifespan-splice path is
    # taken and the pragma-tagged module-top fallback MUST NOT be emitted.
    assert "pragma: B0.15" not in main


# ---------------------------------------------------------------------------
# L283  BinOp Add->Sub — module-top fallback when no lifespan/yield present
# ---------------------------------------------------------------------------


def test_logic_module_top_fallback_when_no_lifespan():
    d = _bare_project(_MARKER_CONFIG, _NO_LIFESPAN_MAIN)
    r = add_prometheus_metrics(ToolInput(project_dir=str(d)))
    # No `yield` line → fallback does `src.rstrip() + fallback`.
    # Add->Sub raises TypeError (str - str) → tool would error.
    assert r.status == "success"
    main = (d / "app" / "main.py").read_text()
    # Pragma-tagged module-top init must be present in the fallback path.
    assert "pragma: B0.15" in main
    assert "_init_metrics(prefix=_prom_prefix)" in main
