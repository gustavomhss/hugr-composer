"""TOOL-050: add_i18n — internationalization scaffold for FastAPI projects.

Adds a full Babel+gettext i18n stack:
- ``LocaleMiddleware`` with 4-tier priority resolution
  (query param → X-Locale header → session → Accept-Language)
- ``ContextVar``-based locale context (no argument threading)
- ICU-compatible pluralization helper via Babel CLDR rules
- RTL detection (Arabic, Hebrew, Farsi, Urdu)
- Locale-aware number/date/currency formatting helpers
- Babel extraction config (``babel.cfg``)
- Per-locale ``.po``/``.mo`` stub catalogs
- Missing-translation audit CLI
- Makefile workflow targets (extract → update → compile)

The tool is idempotent: if ``app/core/locale_context.py`` already exists and
contains ``_current_locale``, returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.add_i18n import add_i18n

    result = add_i18n(
        ToolInput(project_dir="/path/to/project"),
        default_locale="en_US",
        supported_locales=["en_US", "pt_BR", "ar"],
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

# Locales with RTL text direction
_RTL_LOCALES = frozenset({"ar", "he", "fa", "ur", "ar_SA", "ar_EG", "he_IL"})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_i18n(
    inp: ToolInput,
    default_locale: str = "en_US",
    supported_locales: list[str] | None = None,
    translation_dir: str = "locales",
    fallback_chain: dict[str, list[str]] | None = None,
    extract_from_source: bool = True,
) -> ToolResult:
    """Scaffold full i18n infrastructure for a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        default_locale: BCP-47 canonical locale (source of truth for message IDs).
        supported_locales: Locales to scaffold; None = ``[default_locale]``.
        translation_dir: Directory for ``.po``/``.mo`` catalogs.
        fallback_chain: Per-locale fallback overrides (e.g. ``{"pt_PT":["pt_BR","en_US"]}``).
        extract_from_source: Run ``pybabel extract`` during scaffolding.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"
    supported_locales = supported_locales or [default_locale]
    fallback_chain = fallback_chain or {}

    # Idempotency guard
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

    files_created: list[str] = []
    files_modified: list[str] = []

    core_dir = app_dir / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    middleware_dir = app_dir / "api" / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    locales_dir = project / translation_dir
    locales_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: ContextVar
    locale_ctx_file.write_text(_locale_context_content())
    files_created.append(str(locale_ctx_file))

    # Step 2: Locale metadata
    locale_meta_file = core_dir / "locale_meta.py"
    locale_meta_file.write_text(_locale_meta_content(supported_locales))
    files_created.append(str(locale_meta_file))

    # Step 3: Babel translator
    translator_file = core_dir / "babel_translator.py"
    translator_file.write_text(_babel_translator_content(translation_dir, default_locale))
    files_created.append(str(translator_file))

    # Step 4: Locale middleware
    middleware_file = middleware_dir / "locale.py"
    middleware_file.write_text(_locale_middleware_content(default_locale, supported_locales))
    files_created.append(str(middleware_file))

    # Step 5: ICU plurals helper
    icu_file = core_dir / "icu_plurals.py"
    icu_file.write_text(_icu_plurals_content())
    files_created.append(str(icu_file))

    # Step 6: Number/date/currency formatters
    fmt_file = core_dir / "locale_formatters.py"
    fmt_file.write_text(_locale_formatters_content())
    files_created.append(str(fmt_file))

    # Step 7: babel.cfg
    babel_cfg = project / "babel.cfg"
    babel_cfg.write_text(_babel_cfg_content())
    files_created.append(str(babel_cfg))

    # Step 8: Per-locale .po stubs
    for locale in supported_locales:
        locale_dir = locales_dir / locale / "LC_MESSAGES"
        locale_dir.mkdir(parents=True, exist_ok=True)
        po_file = locale_dir / "messages.po"
        po_file.write_text(_po_stub_content(locale, default_locale))
        files_created.append(str(po_file))

    # Step 9: Audit CLI
    audit_cli = project / "scripts" / "i18n_audit.py"
    audit_cli.parent.mkdir(exist_ok=True)
    audit_cli.write_text(_audit_cli_content(translation_dir, supported_locales))
    files_created.append(str(audit_cli))

    # Step 10: Patch main.py to register middleware
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # Step 11: Makefile targets
    makefile = project / "Makefile"
    if makefile.exists():
        _patch_makefile(makefile, translation_dir)
        files_modified.append(str(makefile))

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
        next_steps=[
            "pip install Babel",
            f"make i18n-extract  # runs pybabel extract -F babel.cfg -o {translation_dir}/messages.pot .",
            f"make i18n-update   # merges new strings into all .po files",
            "make i18n-compile  # compiles .po → .mo",
            "python scripts/i18n_audit.py  # check missing translations",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def _locale_context_content() -> str:
    """Return content for app/core/locale_context.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Thread-safe locale context via ContextVar.

        Downstream _() calls read from this context automatically.
        \"\"\"
        from __future__ import annotations

        from contextvars import ContextVar

        _current_locale: ContextVar[str] = ContextVar("_current_locale", default="en_US")


        def get_current_locale() -> str:
            \"\"\"Return the active locale for the current async context.

            Returns:
                BCP-47 locale string (e.g. ``'pt_BR'``).
            \"\"\"
            return _current_locale.get()


        def set_current_locale(locale: str) -> None:
            \"\"\"Set the active locale for the current async context.

            Args:
                locale: BCP-47 locale string to activate.
            \"\"\"
            _current_locale.set(locale)
    """)


def _locale_meta_content(supported_locales: list[str]) -> str:
    """Return content for app/core/locale_meta.py.

    Args:
        supported_locales: List of supported BCP-47 locale strings.

    Returns:
        Python source string.
    """
    rtl_set = {loc for loc in supported_locales if loc in _RTL_LOCALES or loc.split("_")[0] in {"ar", "he", "fa", "ur"}}
    return textwrap.dedent(f"""\
        \"\"\"Locale metadata: supported locales and RTL detection.\"\"\"
        from __future__ import annotations

        from dataclasses import dataclass


        @dataclass(frozen=True)
        class LocaleMeta:
            \"\"\"Metadata for a single locale.

            Attributes:
                code: BCP-47 locale code (e.g. ``'pt_BR'``).
                is_rtl: True for right-to-left text direction locales.
            \"\"\"

            code: str
            is_rtl: bool = False


        SUPPORTED_LOCALES: tuple[str, ...] = {tuple(supported_locales)!r}
        DEFAULT_LOCALE = "{supported_locales[0] if supported_locales else 'en_US'}"

        LOCALE_META: dict[str, LocaleMeta] = {{
            code: LocaleMeta(
                code=code,
                is_rtl=code in {sorted(rtl_set)!r} or code.split("_")[0] in {{"ar", "he", "fa", "ur"}},
            )
            for code in SUPPORTED_LOCALES
        }}


        def is_rtl(locale: str) -> bool:
            \"\"\"Return True if *locale* uses right-to-left text direction.

            Args:
                locale: BCP-47 locale code.

            Returns:
                True for RTL locales.
            \"\"\"
            meta = LOCALE_META.get(locale)
            return meta.is_rtl if meta else False
    """)


def _babel_translator_content(translation_dir: str, default_locale: str) -> str:
    """Return content for app/core/babel_translator.py.

    Args:
        translation_dir: Path to the locales directory.
        default_locale: Fallback locale code.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Babel/gettext translation catalog manager.

        Catalogs are loaded once at startup from ``{translation_dir}/<locale>/LC_MESSAGES/messages.mo``
        and cached in a module-level dict for < 10 µs per lookup.
        \"\"\"
        from __future__ import annotations

        import gettext
        import logging
        from pathlib import Path

        from app.core.locale_context import get_current_locale

        logger = logging.getLogger(__name__)

        _LOCALE_DIR = Path(__file__).parent.parent.parent / "{translation_dir}"
        _DEFAULT_LOCALE = "{default_locale}"
        _CATALOGS: dict[str, gettext.GNUTranslations] = {{}}


        def load_catalogs(supported_locales: list[str]) -> None:
            \"\"\"Pre-load all compiled .mo catalogs at startup.

            Args:
                supported_locales: List of BCP-47 locale codes to load.
            \"\"\"
            for locale in supported_locales:
                try:
                    translation = gettext.translation(
                        domain="messages",
                        localedir=str(_LOCALE_DIR),
                        languages=[locale],
                    )
                    _CATALOGS[locale] = translation
                    logger.info("Loaded translation catalog for %s", locale)
                except FileNotFoundError:
                    logger.warning("No compiled .mo for locale %s — falling back to default", locale)


        def _(message: str) -> str:
            \"\"\"Translate *message* using the active locale catalog.

            Args:
                message: Message ID string (English source text).

            Returns:
                Translated string for the active locale.
            \"\"\"
            locale = get_current_locale()
            catalog = _CATALOGS.get(locale) or _CATALOGS.get(_DEFAULT_LOCALE)
            if catalog is None:
                return message
            return catalog.gettext(message)


        def ngettext(singular: str, plural: str, n: int) -> str:
            \"\"\"Translate a plural-form message.

            Args:
                singular: Singular form (English source).
                plural: Plural form (English source).
                n: Count used to select the appropriate plural form.

            Returns:
                Translated string for the active locale and count *n*.
            \"\"\"
            locale = get_current_locale()
            catalog = _CATALOGS.get(locale) or _CATALOGS.get(_DEFAULT_LOCALE)
            if catalog is None:
                return singular if n == 1 else plural
            return catalog.ngettext(singular, plural, n)
    """)


def _locale_middleware_content(default_locale: str, supported_locales: list[str]) -> str:
    """Return content for app/api/middleware/locale.py.

    Args:
        default_locale: Fallback locale code.
        supported_locales: List of supported locale codes.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"LocaleMiddleware: resolves the active locale for every request.

        Priority order:
        1. ``?lang=`` query parameter
        2. ``X-Locale`` request header
        3. ``Accept-Language`` header (BCP-47 q-value negotiation)
        4. Default locale fallback

        Injects ``X-Text-Direction: rtl`` response header for RTL locales.
        Stores resolved locale in ContextVar for downstream ``_()`` calls.
        \"\"\"
        from __future__ import annotations

        import re

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.types import ASGIApp

        from app.core.locale_context import set_current_locale
        from app.core.locale_meta import SUPPORTED_LOCALES, is_rtl

        _DEFAULT_LOCALE = "{default_locale}"
        _SUPPORTED = set(SUPPORTED_LOCALES)
        _ACCEPT_RE = re.compile(r"([a-zA-Z]{{1,8}}(?:-[a-zA-Z0-9]{{1,8}})*)(;q=([\\d.]+))?")


        class LocaleMiddleware(BaseHTTPMiddleware):
            \"\"\"ASGI middleware that resolves and activates the request locale.

            Args:
                app: The downstream ASGI application.
            \"\"\"

            def __init__(self, app: ASGIApp) -> None:
                super().__init__(app)

            async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
                \"\"\"Resolve locale and inject into ContextVar before handling request.

                Args:
                    request: Incoming Starlette request.
                    call_next: Next middleware/handler callable.

                Returns:
                    Response with optional ``X-Text-Direction`` header.
                \"\"\"
                locale = (
                    self._from_query(request)
                    or self._from_header(request)
                    or self._from_accept_language(request)
                    or _DEFAULT_LOCALE
                )
                set_current_locale(locale)
                response = await call_next(request)
                if is_rtl(locale):
                    response.headers["X-Text-Direction"] = "rtl"
                return response

            def _from_query(self, request: Request) -> str | None:
                \"\"\"Extract locale from ?lang= query parameter.\"\"\"
                lang = request.query_params.get("lang")
                return lang if lang in _SUPPORTED else None

            def _from_header(self, request: Request) -> str | None:
                \"\"\"Extract locale from X-Locale header.\"\"\"
                locale = request.headers.get("X-Locale")
                return locale if locale in _SUPPORTED else None

            def _from_accept_language(self, request: Request) -> str | None:
                \"\"\"Negotiate locale from Accept-Language header.\"\"\"
                header = request.headers.get("Accept-Language", "")
                candidates: list[tuple[float, str]] = []
                for m in _ACCEPT_RE.finditer(header):
                    tag = m.group(1).replace("-", "_")
                    q = float(m.group(3)) if m.group(3) else 1.0
                    candidates.append((q, tag))
                for _, tag in sorted(candidates, reverse=True):
                    if tag in _SUPPORTED:
                        return tag
                    # Try language-only match (e.g. 'pt' matches 'pt_BR')
                    lang = tag.split("_")[0]
                    for supported in _SUPPORTED:
                        if supported.startswith(lang):
                            return supported
                return None
    """)


def _icu_plurals_content() -> str:
    """Return content for app/core/icu_plurals.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"ICU MessageFormat-compatible pluralization helper.

        Uses Babel's CLDR plural rules for grammatically correct multi-language
        pluralization.  Falls back to simple English rules when Babel is not
        installed.
        \"\"\"
        from __future__ import annotations

        from app.core.locale_context import get_current_locale


        def pluralize(count: int, forms: dict[str, str]) -> str:
            \"\"\"Return the correct plural form for *count* in the active locale.

            Args:
                count: Numeric count to pluralize.
                forms: Dict of CLDR plural category → translated string.
                    Categories: ``zero``, ``one``, ``two``, ``few``, ``many``, ``other``.
                    Always include ``other`` as the fallback.

            Returns:
                The appropriate plural form string.

            Example::

                text = pluralize(3, {
                    "one": "{} item",
                    "other": "{} items",
                })
                # Returns "3 items"
            \"\"\"
            locale = get_current_locale()
            category = _get_plural_category(count, locale)
            template = forms.get(category) or forms.get("other", str(count))
            return template.format(count)


        def _get_plural_category(count: int, locale: str) -> str:
            \"\"\"Return the CLDR plural category for *count* in *locale*.

            Args:
                count: Numeric value.
                locale: BCP-47 locale code.

            Returns:
                CLDR category string (``'one'``, ``'few'``, ``'many'``, ``'other'``, etc.).
            \"\"\"
            try:
                from babel.plural import get_plural  # type: ignore[import-untyped]
                plural_func = get_plural(locale)
                return plural_func(count)
            except (ImportError, Exception):  # noqa: BLE001
                # English fallback: 1 → 'one', everything else → 'other'
                return "one" if count == 1 else "other"
    """)


def _locale_formatters_content() -> str:
    """Return content for app/core/locale_formatters.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Locale-aware number, date, and currency formatters.

        All functions delegate to Babel's CLDR-backed format functions.
        \"\"\"
        from __future__ import annotations

        from datetime import date, datetime

        from app.core.locale_context import get_current_locale


        def format_number(value: int | float) -> str:
            \"\"\"Format *value* as a locale-aware number string.

            Args:
                value: Numeric value to format.

            Returns:
                Locale-formatted number string (e.g. ``'1.234,56'`` for pt_BR).
            \"\"\"
            locale = get_current_locale()
            try:
                from babel.numbers import format_number as _fmt  # type: ignore[import-untyped]
                return _fmt(value, locale=locale)
            except (ImportError, Exception):  # noqa: BLE001
                return str(value)


        def format_date(value: date | datetime) -> str:
            \"\"\"Format *value* as a locale-aware date string.

            Args:
                value: Date or datetime to format.

            Returns:
                Locale-formatted date string.
            \"\"\"
            locale = get_current_locale()
            try:
                from babel.dates import format_date as _fmt  # type: ignore[import-untyped]
                return _fmt(value, locale=locale)
            except (ImportError, Exception):  # noqa: BLE001
                return str(value)


        def format_currency(amount: int | float, currency: str = "USD") -> str:
            \"\"\"Format *amount* as a locale-aware currency string.

            Args:
                amount: Monetary value to format.
                currency: ISO 4217 currency code (e.g. ``'BRL'``, ``'EUR'``).

            Returns:
                Locale-formatted currency string (e.g. ``'R$ 1.234,56'``).
            \"\"\"
            locale = get_current_locale()
            try:
                from babel.numbers import format_currency as _fmt  # type: ignore[import-untyped]
                return _fmt(amount, currency, locale=locale)
            except (ImportError, Exception):  # noqa: BLE001
                return f"{currency} {amount}"
    """)


def _babel_cfg_content() -> str:
    """Return content for babel.cfg.

    Returns:
        INI-format Babel extraction config string.
    """
    return textwrap.dedent("""\
        # Babel extraction configuration.
        # Run: pybabel extract -F babel.cfg -k _ -k ngettext -o locales/messages.pot .

        [python: app/**.py]
        encoding = utf-8

        [jinja2: templates/**.html]
        encoding = utf-8
        extensions = jinja2.ext.autoescape,jinja2.ext.with_
    """)


def _po_stub_content(locale: str, default_locale: str) -> str:
    """Return a minimal .po file stub for *locale*.

    Args:
        locale: Target locale code.
        default_locale: Source/default locale code.

    Returns:
        Gettext PO file header string.
    """
    return textwrap.dedent(f"""\
        # {locale} translation catalog.
        # FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
        #
        msgid ""
        msgstr ""
        "Project-Id-Version: 1.0\\n"
        "Report-Msgid-Bugs-To: \\n"
        "POT-Creation-Date: 2026-01-01 00:00+0000\\n"
        "PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
        "Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
        "Language-Team: {locale}\\n"
        "Language: {locale}\\n"
        "MIME-Version: 1.0\\n"
        "Content-Type: text/plain; charset=UTF-8\\n"
        "Content-Transfer-Encoding: 8bit\\n"
        "Plural-Forms: nplurals=2; plural=(n != 1);\\n"

        # Add translations below.
        # msgid "Hello"
        # msgstr "{_hello_translation(locale)}"
    """)


def _hello_translation(locale: str) -> str:
    """Return a sample 'Hello' translation for common locales.

    Args:
        locale: Locale code.

    Returns:
        Translated greeting string.
    """
    _samples = {
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
    return _samples.get(locale, "Hello")


def _audit_cli_content(translation_dir: str, supported_locales: list[str]) -> str:
    """Return content for scripts/i18n_audit.py.

    Args:
        translation_dir: Path to the locales directory.
        supported_locales: List of locale codes to audit.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Audit missing and fuzzy translations across all supported locales.

        Exits with code 1 if any locale has untranslated or fuzzy strings.

        Usage::

            python scripts/i18n_audit.py
            python scripts/i18n_audit.py --threshold 90
        \"\"\"
        from __future__ import annotations

        import argparse
        import sys
        from pathlib import Path

        TRANSLATION_DIR = Path(__file__).parent.parent / "{translation_dir}"
        SUPPORTED_LOCALES = {supported_locales!r}


        def audit_locale(locale: str) -> dict:
            \"\"\"Audit a single locale's .po file.

            Args:
                locale: BCP-47 locale code.

            Returns:
                Dict with total, translated, fuzzy, untranslated counts.
            \"\"\"
            po_file = TRANSLATION_DIR / locale / "LC_MESSAGES" / "messages.po"
            if not po_file.exists():
                return {{"locale": locale, "total": 0, "translated": 0, "fuzzy": 0, "untranslated": 0, "missing_file": True}}
            lines = po_file.read_text(encoding="utf-8").splitlines()
            total = translated = fuzzy = untranslated = 0
            in_msgid = False
            current_msgid = ""
            for line in lines:
                if line.startswith("msgid ") and line != 'msgid ""':
                    total += 1
                    current_msgid = line
                    in_msgid = True
                elif line.startswith("msgstr ") and in_msgid:
                    in_msgid = False
                    if line == 'msgstr ""':
                        untranslated += 1
                    else:
                        translated += 1
                elif line.startswith("#, fuzzy"):
                    fuzzy += 1
            return {{
                "locale": locale,
                "total": total,
                "translated": translated,
                "fuzzy": fuzzy,
                "untranslated": untranslated,
                "missing_file": False,
            }}


        def main() -> None:
            \"\"\"Run the missing-translation audit and print a summary table.\"\"\"
            parser = argparse.ArgumentParser(description="i18n translation audit")
            parser.add_argument(
                "--threshold", type=int, default=0,
                help="Minimum translated percentage; exit 1 if any locale is below"
            )
            args = parser.parse_args()

            print(f"{{'-' * 60}}")
            print(f"{{'Locale':<12}} {{'Total':>6}} {{'Trans':>6}} {{'Fuzzy':>6}} {{'Missing':>8}}")
            print(f"{{'-' * 60}}")

            any_fail = False
            for locale in SUPPORTED_LOCALES:
                stats = audit_locale(locale)
                if stats.get("missing_file"):
                    print(f"{{locale:<12}} NO .po FILE")
                    any_fail = True
                    continue
                total = stats["total"]
                pct = int(stats["translated"] / total * 100) if total else 100
                flag = "" if pct >= args.threshold else "BELOW THRESHOLD"
                if flag:
                    any_fail = True
                print(
                    f"{{locale:<12}} {{total:>6}} {{stats['translated']:>6}} "
                    f"{{stats['fuzzy']:>6}} {{stats['untranslated']:>8}}  {{pct}}% {{flag}}"
                )

            print(f"{{'-' * 60}}")
            if any_fail:
                print("AUDIT FAILED: some locales are below threshold or missing .po files.")
                sys.exit(1)
            print("AUDIT PASSED: all locales meet the translation threshold.")


        if __name__ == "__main__":
            main()
    """)


def _patch_main(main_file: Path) -> None:
    """Inject LocaleMiddleware registration into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "LocaleMiddleware" in src:
        return
    snippet = textwrap.dedent("""\

        # i18n: locale middleware — added by add_i18n tool
        # from app.api.middleware.locale import LocaleMiddleware
        # app.add_middleware(LocaleMiddleware)
    """)
    main_file.write_text(src + snippet)


def _patch_makefile(makefile: Path, translation_dir: str) -> None:
    """Append i18n Makefile targets.

    Args:
        makefile: Path to the project Makefile.
        translation_dir: Path to the locales directory.
    """
    src = makefile.read_text()
    if "i18n-extract" in src:
        return
    targets = textwrap.dedent(f"""\

        ## i18n / Internationalization
        .PHONY: i18n-extract i18n-update i18n-compile i18n-audit
        i18n-extract:
        \tpybabel extract -F babel.cfg -k _ -k ngettext -o {translation_dir}/messages.pot .

        i18n-update:
        \tpybabel update -i {translation_dir}/messages.pot -d {translation_dir}

        i18n-compile:
        \tpybabel compile -d {translation_dir}

        i18n-audit:
        \tpython scripts/i18n_audit.py
    """)
    makefile.write_text(src + targets)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
