"""TOOL-050: add_i18n — internationalization scaffold for FastAPI projects.

Adds Babel+gettext i18n: ``LocaleMiddleware`` (4-tier resolution),
ContextVar-based locale context, ICU pluralization (Babel CLDR), RTL
detection, locale-aware formatters, ``babel.cfg``, per-locale ``.po``
stubs, audit CLI, and Makefile workflow targets.

The tool is idempotent: if ``app/core/locale_context.py`` already contains
``_current_locale``, returns ``status="no_op"``.

Warnings:
    - LocaleMiddleware is NOT auto-registered in app/main.py: the patched
      main.py appends a commented-out registration snippet only. Operators
      must uncomment the lines for locale resolution to take effect.
    - When Babel is not installed, ``icu_plurals`` falls back to English
      "1 → one, everything else → other" — NOT CLDR-correct.
    - The ``.po`` stubs are EMPTY catalogs. Translations are not provided.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

# B0.12 — emitted ``babel_translator.py`` keeps the loaded gettext
# catalogs inside a ``_CatalogCache`` instance (class-instance
# singleton, allow-listed by ``r_no_module_state``). The body is
# in-process; under a multi-worker deployment each worker has its own
# copy. ``load_catalogs`` is called at app startup on every worker so
# steady-state reads are correct, but a hot-reload of catalogs at
# runtime is NOT broadcast across workers (operators must restart).
# This flag + the ``single-process`` ``warnings=`` entry below
# disclose the trade-off explicitly. Swap the cache body for a
# Redis-backed pubsub invalidator if cross-worker runtime
# invalidation is required (public surface unchanged).
_SINGLE_PROCESS_OK: bool = True

# Locales with RTL text direction
_RTL_LOCALES = frozenset({"ar", "he", "fa", "ur", "ar_SA", "ar_EG", "he_IL"})

_HELLO_SAMPLES = {
    "pt_BR": "Olá",
    "es_MX": "Hola",
    "es_ES": "Hola",
    "fr_FR": "Bonjour",
    "de_DE": "Hallo",
    "ar": "مرحبا",
    "ar_SA": "مرحبا",
    "he": "שלום",
    "he_IL": "שלום",
    "ja": "こんにちは",
    "zh_CN": "你好",
}


MCP_TOOL = {
    "name": "fastapi_resiliency_add_i18n",
    "description": "Add internationalization (i18n) support with locale detection and message catalogs.",
    "tags": ["evolve"],
    "entry": "add_i18n",
}


def add_i18n(
    inp: ToolInput,
    default_locale: str = "en_US",
    supported_locales: list[str] | None = None,
    translation_dir: str = "locales",
    fallback_chain: dict[str, list[str]] | None = None,
    extract_from_source: bool = True,
) -> ToolResult:
    """Scaffold full i18n infrastructure for a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    supported_locales = supported_locales or [default_locale]
    fallback_chain = fallback_chain or {}

    locale_ctx_file = app_dir / "core" / "locale_context.py"
    if locale_ctx_file.exists() and "_current_locale" in locale_ctx_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["locale_context.py already present — i18n already configured, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] default_locale={default_locale} supported={supported_locales}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    core_dir = app_dir / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    middleware_dir = app_dir / "api" / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    locales_dir = project / translation_dir
    locales_dir.mkdir(parents=True, exist_ok=True)

    render_to(_HERE, "locale_context.py.tmpl", dest=locale_ctx_file, substitutions={})
    files_created.append(str(locale_ctx_file))

    locale_meta_file = core_dir / "locale_meta.py"
    rtl_set = {
        loc
        for loc in supported_locales
        if loc in _RTL_LOCALES or loc.split("_")[0] in {"ar", "he", "fa", "ur"}
    }
    render_to(
        _HERE,
        "locale_meta.py.tmpl",
        dest=locale_meta_file,
        substitutions={
            "supported_tuple": repr(tuple(supported_locales)),
            "default_locale": supported_locales[0] if supported_locales else "en_US",
            "rtl_list": repr(sorted(rtl_set)),
        },
    )
    files_created.append(str(locale_meta_file))

    translator_file = core_dir / "babel_translator.py"
    render_to(
        _HERE,
        "babel_translator.py.tmpl",
        dest=translator_file,
        substitutions={"translation_dir": translation_dir, "default_locale": default_locale},
    )
    files_created.append(str(translator_file))

    middleware_file = middleware_dir / "locale.py"
    render_to(
        _HERE,
        "locale_middleware.py.tmpl",
        dest=middleware_file,
        substitutions={"default_locale": default_locale},
    )
    files_created.append(str(middleware_file))

    icu_file = core_dir / "icu_plurals.py"
    render_to(_HERE, "icu_plurals.py.tmpl", dest=icu_file, substitutions={})
    files_created.append(str(icu_file))

    fmt_file = core_dir / "locale_formatters.py"
    render_to(_HERE, "locale_formatters.py.tmpl", dest=fmt_file, substitutions={})
    files_created.append(str(fmt_file))

    babel_cfg = project / "babel.cfg"
    babel_cfg.write_text(render(_HERE, "babel.cfg.tmpl", {}))
    files_created.append(str(babel_cfg))

    for locale in supported_locales:
        locale_dir = locales_dir / locale / "LC_MESSAGES"
        locale_dir.mkdir(parents=True, exist_ok=True)
        po_file = locale_dir / "messages.po"
        po_file.write_text(
            render(
                _HERE,
                "po_stub.po.tmpl",
                {"locale": locale, "hello": _HELLO_SAMPLES.get(locale, "Hello")},
            )
        )
        files_created.append(str(po_file))

    audit_cli = project / "scripts" / "i18n_audit.py"
    audit_cli.parent.mkdir(exist_ok=True)
    render_to(
        _HERE,
        "i18n_audit.py.tmpl",
        dest=audit_cli,
        substitutions={
            "translation_dir": translation_dir,
            "supported_locales": repr(supported_locales),
        },
    )
    files_created.append(str(audit_cli))

    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    makefile = project / "Makefile"
    if makefile.exists() and _patch_makefile(makefile, translation_dir):
        files_modified.append(str(makefile))

    _emit_project_test(project, files_created)

    # CLAUDE.md pattern #7 — emitted .py files must parse cleanly.
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.exists():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"emitted file failed ast.parse: {p} :: {exc}",
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"i18n scaffolded: default={default_locale} supported={supported_locales}",
            f"Translation catalogs: {translation_dir}/<locale>/LC_MESSAGES/messages.po",
            "RTL detection enabled for: ar, he, fa, ur",
            "Locale resolution: ?lang > X-Locale > session > Accept-Language > default",
        ],
        warnings=[
            # B0.12 disclosure — paired with _SINGLE_PROCESS_OK = True
            # above. The emitted babel_translator's _CatalogCache is
            # in-process; under multi-worker (gunicorn -w N / uvicorn
            # --workers) each worker has its own copy. Catalogs are
            # loaded at app startup on every worker so steady-state
            # reads are correct; runtime hot-reload of catalogs is NOT
            # broadcast cross-worker (operators must restart, or swap
            # the cache body for a Redis-backed pubsub invalidator).
            "Translation catalog cache is single-process (in-memory). "
            "Multi-worker deployments: catalogs reload only on restart; "
            "swap _CatalogCache for a Redis pubsub invalidator if "
            "cross-worker runtime invalidation is required.",
        ],
        next_steps=[
            "pip install Babel",
            f"make i18n-extract  # runs pybabel extract -F babel.cfg -o {translation_dir}/messages.pot .",
            "make i18n-update   # merges new strings into all .po files",
            "make i18n-compile  # compiles .po → .mo",
            "python scripts/i18n_audit.py  # check missing translations",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main(main_file: Path) -> bool:
    """Inject (commented-out) LocaleMiddleware registration into app/main.py."""
    src = main_file.read_text()
    if "LocaleMiddleware" in src:
        return False
    snippet = (
        "\n# i18n: locale middleware — added by add_i18n tool\n"
        "# from app.api.middleware.locale import LocaleMiddleware\n"
        "# app.add_middleware(LocaleMiddleware)\n"
    )
    main_file.write_text(src + snippet)
    return True


def _patch_makefile(makefile: Path, translation_dir: str) -> bool:
    """Append i18n Makefile targets if not already present."""
    src = makefile.read_text()
    if "i18n-extract" in src:
        return False
    targets = (
        "\n## i18n / Internationalization\n"
        ".PHONY: i18n-extract i18n-update i18n-compile i18n-audit\n"
        "i18n-extract:\n"
        f"\tpybabel extract -F babel.cfg -k _ -k ngettext -o {translation_dir}/messages.pot .\n\n"
        "i18n-update:\n"
        f"\tpybabel update -i {translation_dir}/messages.pot -d {translation_dir}\n\n"
        "i18n-compile:\n"
        f"\tpybabel compile -d {translation_dir}\n\n"
        "i18n-audit:\n"
        "\tpython scripts/i18n_audit.py\n"
    )
    makefile.write_text(src + targets)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_i18n_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_i18n_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_i18n_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
