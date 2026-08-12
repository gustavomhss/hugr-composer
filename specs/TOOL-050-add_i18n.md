---
spec_id: "TOOL-050"
tool_name: "add_i18n"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-I18N-001"
  - "INV-I18N-002"
  - "INV-I18N-003"
  - "INV-I18N-004"
  - "INV-I18N-005"
  - "INV-I18N-006"
  - "INV-I18N-007"
  - "INV-I18N-008"
completeness_criteria:
  - "CC-001"
  - "CC-002"
  - "CC-003"
  - "CC-004"
  - "CC-005"
  - "CC-006"
  - "CC-007"
  - "CC-008"
  - "CC-009"
  - "CC-010"
  - "CC-011"
  - "CC-012"
  - "CC-013"
  - "CC-014"
  - "CC-015"
  - "CC-016"
  - "CC-017"
  - "CC-018"
  - "CC-019"
  - "CC-020"
  - "CC-021"
  - "CC-022"
  - "CC-023"
  - "CC-024"
  - "CC-025"
  - "CC-026"
  - "CC-027"
  - "CC-028"
  - "CC-029"
  - "CC-030"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "evolve"
---
# TOOL-050: fastapi_add_i18n

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_i18n` |
| Category | EVOLVE |
| Complexity | High |
| Dependencies | Existing FastAPI project, Babel ≥ 2.14, gettext (system), optional PyICU ≥ 2.11 for complex plural rules |
| Signature | `add_i18n(project_dir: str, default_locale: str = "en_US", supported_locales: list[str] \| None = None, translation_dir: str = "locales", fallback_chain: list[str] \| None = None, extract_from_source: bool = True) -> dict` |
| Parameters | `project_dir`: project root path<br>`default_locale`: BCP-47 canonical locale, source of truth for message IDs (default `en_US`)<br>`supported_locales`: list of BCP-47 locales to scaffold (e.g. `["en_US","pt_BR","es_MX","ar","fr_FR"]`); None = `[default_locale]`<br>`translation_dir`: directory holding per-locale `.po`/`.mo` catalogs (default `locales/`)<br>`fallback_chain`: per-locale fallback overrides as YAML-serialisable dict (e.g. `{"pt_PT":["pt_BR","en_US"]}`); None = auto-chain to default<br>`extract_from_source`: run `pybabel extract` during scaffolding and populate initial `.pot` (default `True`) |

---

## 2. Purpose

`fastapi_add_i18n` equips an existing FastAPI service with a full-stack internationalization and localization infrastructure without requiring any changes to existing business logic. The root problem it solves is that most FastAPI applications are born English-only: every user-facing string is a hardcoded English literal scattered across route handlers, service methods, exception factories, and Pydantic validation error messages. Retrofitting i18n after launch is painful because there is no systematic way to find all translatable strings, no runtime mechanism to select the right translation for an incoming request, and no workflow to hand off translation catalogs to human translators. This tool implements the full Babel+gettext workflow in a single invocation: it generates a `babel.cfg` extraction config that locates every `_()` call and Jinja2 `{{ _() }}` template expression, runs `pybabel extract` to produce a `.pot` master template, bootstraps per-locale `.po` files for every locale in `supported_locales`, and registers a `LocaleMiddleware` that resolves the active locale from four sources in priority order — (1) query parameter `?lang=`, (2) `X-Locale` request header, (3) user preference stored in session or DB, (4) `Accept-Language` negotiation against the supported list with BCP-47 quality-value scoring, falling back to `default_locale` if none match. The middleware stores the resolved locale in a `ContextVar` so that downstream `_()` calls automatically use the correct catalog without needing to pass a locale argument through every function signature.

The second pillar of this tool is production-grade correctness for the aspects of i18n that are most commonly wrong in first attempts. Pluralization is notoriously broken when developers use simple `if count == 1` guards in English: Russian has four plural forms, Arabic has six, Polish has three with irregular zero-form rules, and Icelandic is grammatically singular for 21, 31, 41, etc. This tool generates an ICU MessageFormat-compatible pluralization helper backed by Babel's CLDR plural rules database so that every language receives grammatically correct output without bespoke hand-coding per locale. Right-to-left (RTL) support for Arabic, Hebrew, Farsi, and Urdu is wired at the middleware layer: the resolved `LocaleMeta` dataclass carries a boolean `is_rtl` field, and the middleware injects a `X-Text-Direction: rtl` response header so that frontend consumers can apply `dir="rtl"` globally without per-component logic. Locale-aware number, date, and currency formatting delegates entirely to Babel's `format_number`, `format_date`, `format_datetime`, and `format_currency` functions, which are CLDR-backed and cover every regional variation automatically (e.g. `1.234,56 €` vs `$1,234.56`). The tool also generates a `missing_translation_audit` CLI command that scans all `.po` files, counts fuzzy and untranslated entries per locale, and exits with a non-zero code suitable for blocking CI pipelines. The catalog update workflow (`pybabel update → human edit → pybabel compile`) is encoded in a generated `Makefile` target so that developers can run a single `make i18n-compile` before every deploy without remembering the `pybabel` invocation details.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s for up to 10 locales and 1000 source strings | Developer waits in CLI during scaffolding |
| Files created | ≥ 11 (middleware, locale_context, babel_translator, icu_plurals, number_fmt, date_fmt, rtl_meta, audit CLI, tests, Makefile targets, babel.cfg, per-locale .po stubs) | Predictable scaffolding surface |
| Files modified | ≤ 4 (`main.py`, `core/config.py`, `pyproject.toml`, at minimum one route with user-facing strings) | Minimal blast radius on existing code |
| Locale resolution per request | < 1 ms | ContextVar lookup after Accept-Language parse; no DB hit unless user preference resolver enabled |
| Translation lookup (cached catalog) | < 10 µs | `gettext.GNUTranslations` catalog is loaded once at startup and held in a module-level dict keyed by locale |
| `pybabel extract` on 1000 strings | < 5s | File I/O bound; regex AST walk of Python source is O(n) |
| `pybabel compile` on 10 locales | < 2s | Binary `.mo` write is trivially fast; tested on 50k-entry catalogs |
| `pybabel update` (merge new strings) | < 3s | Preserves human edits via fuzzy matching; deterministic diff |
| Startup catalog preload (10 locales) | < 500 ms | All `.mo` files loaded at `@app.on_event("startup")`; error if any locale missing compiled catalog |
| Missing-translation audit (10 locales) | < 2s | CLI reads `.po` files, counts msgstr="" and fuzzy; prints table and exits 1 if threshold exceeded |
| Memory overhead per locale | < 512 KB | Typical `.mo` for 500 entries; 10 locales ≈ 5 MB total — negligible |
| Accept-Language parse throughput | > 50 000 requests/s | Regex parse + sort by q-value; benchmarked in CPython 3.11 |

---

## 4. Code Examples

### 4.1 LocaleMiddleware — full Accept-Language resolution chain

```python
# app/api/middleware/locale.py
"""
LocaleMiddleware: resolves locale for every incoming request.
Priority: ?lang query param → X-Locale header → user session pref → Accept-Language → default.
Stores resolved locale in ContextVar for downstream _() calls.
Injects X-Text-Direction: rtl response header for RTL locales.
"""
from __future__ import annotations

import re
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.locale_context import set_current_locale
from app.core.locale_meta import LOCALE_META, LocaleMeta
from app.core.config import settings

_ACCEPT_RE = re.compile(r"([a-zA-Z]{1,8}(?:-[a-zA-Z0-9]{1,8})*)\s*(?:;\s*q=([\d.]+))?")


def _parse_accept_language(header: str) -> list[str]:
    """Parse Accept-Language header into BCP-47 codes ordered by q-value."""
    candidates: list[tuple[float, str]] = []
    for m in _ACCEPT_RE.finditer(header):
        tag = m.group(1).replace("-", "_")
        q = float(m.group(2) or "1.0")
        candidates.append((q, tag))
    candidates.sort(key=lambda x: -x[0])
    return [tag for _, tag in candidates]


def _negotiate(preferred: list[str], supported: set[str], default: str) -> str:
    """BCP-47 negotiation: exact match → language-only match → default."""
    for tag in preferred:
        if tag in supported:
            return tag
        lang = tag.split("_")[0]
        for sup in supported:
            if sup.startswith(lang):
                return sup
    return default


class LocaleMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._supported: set[str] = set(settings.SUPPORTED_LOCALES)
        self._default: str = settings.DEFAULT_LOCALE

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        locale = self._resolve(request)
        set_current_locale(locale)
        response = await call_next(request)
        meta: LocaleMeta = LOCALE_META.get(locale, LOCALE_META[self._default])
        if meta.is_rtl:
            response.headers["X-Text-Direction"] = "rtl"
        response.headers["Content-Language"] = locale.replace("_", "-")
        return response

    def _resolve(self, request: Request) -> str:
        # 1. Query param ?lang=
        lang = request.query_params.get("lang")
        if lang and lang.replace("-", "_") in self._supported:
            return lang.replace("-", "_")
        # 2. X-Locale header
        header_locale = request.headers.get("X-Locale", "").replace("-", "_")
        if header_locale in self._supported:
            return header_locale
        # 3. Session user preference (set by /api/v1/me/locale endpoint)
        session_locale = (request.session.get("locale", "") if hasattr(request, "session") else "")
        if session_locale and session_locale.replace("-", "_") in self._supported:
            return session_locale.replace("-", "_")
        # 4. Accept-Language negotiation
        accept = request.headers.get("Accept-Language", "")
        if accept:
            preferred = _parse_accept_language(accept)
            return _negotiate(preferred, self._supported, self._default)
        return self._default
```

### 4.2 LocaleContext — ContextVar storage and `_()` helper

```python
# app/core/locale_context.py
"""
locale_context.py: stores the active locale in a per-request ContextVar
and exposes the _() translation helper that all service/route code should use.

Usage:
    from app.core.locale_context import _
    raise HTTPException(status_code=404, detail=_("Item not found"))
"""
from __future__ import annotations

import gettext
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.core.config import settings

_current_locale: ContextVar[str] = ContextVar("current_locale", default=settings.DEFAULT_LOCALE)

# Module-level catalog cache: avoids re-opening .mo files on every lookup.
# Populated at application startup via preload_catalogs().
_catalog_cache: dict[str, gettext.GNUTranslations] = {}
_fallback_registry: dict[str, list[str]] = {}


def set_current_locale(locale: str) -> None:
    _current_locale.set(locale)


def get_current_locale() -> str:
    return _current_locale.get()


def preload_catalogs(
    locales_dir: Path,
    supported_locales: list[str],
    fallback_chain: dict[str, list[str]] | None = None,
) -> None:
    """Load all .mo files at startup. Raises FileNotFoundError if any .mo is missing."""
    for locale in supported_locales:
        mo_path = locales_dir / locale / "LC_MESSAGES" / "messages.mo"
        if not mo_path.exists():
            raise FileNotFoundError(
                f"Missing compiled catalog for locale {locale}: {mo_path}. "
                "Run `make i18n-compile` before starting the server."
            )
        _catalog_cache[locale] = gettext.GNUTranslations(mo_path.open("rb"))
    if fallback_chain:
        _fallback_registry.update(fallback_chain)


def _get_translation(locale: str) -> gettext.GNUTranslations | None:
    """Walk fallback chain until a loaded catalog is found."""
    chain = _fallback_registry.get(locale, []) + [settings.DEFAULT_LOCALE]
    for candidate in [locale] + chain:
        if candidate in _catalog_cache:
            return _catalog_cache[candidate]
    return None


def _(msgid: str, **kwargs: Any) -> str:
    """
    Translate msgid to the current request locale.
    Falls back through the chain; returns msgid if nothing found.
    Supports simple keyword interpolation: _("Hello {name}", name="World").
    """
    locale = get_current_locale()
    translation = _get_translation(locale)
    if translation is None:
        result = msgid
    else:
        result = translation.gettext(msgid)
    if kwargs:
        result = result.format(**kwargs)
    return result
```

### 4.3 BabelTranslator — wrapper for lazy loading and ngettext

```python
# app/core/babel_translator.py
"""
BabelTranslator: extends the basic gettext helper with ngettext
(plural-aware translation) and lazy string support for module-level constants.
"""
from __future__ import annotations

import gettext
from typing import Callable

from app.core.locale_context import _, get_current_locale, _get_translation


class LazyString:
    """
    Defer translation until the string is actually rendered (e.g. in a response).
    Useful for module-level error message constants that must be defined before
    the request locale is known.
    """
    def __init__(self, msgid: str, **kwargs: str) -> None:
        self._msgid = msgid
        self._kwargs = kwargs

    def __str__(self) -> str:
        return _(self._msgid, **self._kwargs)

    def __repr__(self) -> str:
        return f"LazyString({self._msgid!r})"


def lazy_gettext(msgid: str, **kwargs: str) -> LazyString:
    """Create a lazy-evaluated translated string."""
    return LazyString(msgid, **kwargs)


def ngettext(singular: str, plural: str, n: int, **kwargs: str) -> str:
    """
    Plural-aware translation.
    Uses the .po ngettext catalog entry for the current locale.
    Falls back to English singular/plural if no catalog entry found.
    """
    locale = get_current_locale()
    translation = _get_translation(locale)
    if translation is None:
        result = singular if n == 1 else plural
    else:
        result = translation.ngettext(singular, plural, n)
    if kwargs:
        result = result.format(n=n, **kwargs)
    return result


# Module-level lazy message constants (safe to define at import time)
MSG_NOT_FOUND = lazy_gettext("Resource not found")
MSG_UNAUTHORIZED = lazy_gettext("Authentication required")
MSG_FORBIDDEN = lazy_gettext("Permission denied")
MSG_VALIDATION_FAILED = lazy_gettext("Request validation failed")
```

### 4.4 ICU MessageFormat pluralization for complex plural rules

```python
# app/core/icu_plurals.py
"""
ICU MessageFormat plural rules via PyICU (optional) or Babel CLDR fallback.
Handles Arabic (6 forms), Polish (3 irregular forms), Russian (4 forms), etc.
Falls back to Babel's plural rule engine when PyICU is not installed.

Install PyICU: pip install PyICU>=2.11  (requires libicu-dev on Linux)
"""
from __future__ import annotations

import babel.plural
from babel import Locale as BabelLocale
from app.core.locale_context import get_current_locale

try:
    import icu  # PyICU
    _ICU_AVAILABLE = True
except ImportError:
    _ICU_AVAILABLE = False


def get_plural_form(locale_code: str, n: int) -> str:
    """
    Return CLDR plural category for integer n in the given locale.
    Returns one of: 'zero', 'one', 'two', 'few', 'many', 'other'.
    """
    if _ICU_AVAILABLE:
        loc = icu.Locale(locale_code.replace("_", "-"))
        rules = icu.PluralRules.forLocale(loc)
        return rules.select(n)
    # Babel CLDR fallback
    babel_locale = BabelLocale.parse(locale_code)
    rule_func = babel.plural.to_python(
        babel_locale.plural_form  # type: ignore[attr-defined]
    ) if hasattr(babel_locale, "plural_form") else None
    if rule_func is not None:
        try:
            return rule_func(n)
        except Exception:
            pass
    # Last resort: English two-form rule
    return "one" if n == 1 else "other"


def format_plural(
    locale_code: str,
    n: int,
    forms: dict[str, str],
    default_form: str = "other",
) -> str:
    """
    Select the right plural form string for n in locale_code.

    Example:
        format_plural("ar", 3, {
            "zero": "لا عناصر", "one": "عنصر واحد", "two": "عنصران",
            "few": "{n} عناصر", "many": "{n} عنصرًا", "other": "{n} عنصر",
        }) → "3 عناصر"
    """
    category = get_plural_form(locale_code, n)
    template = forms.get(category, forms.get(default_form, str(n)))
    return template.format(n=n)


def pluralize(singular: str, plural: str, n: int) -> str:
    """Simple two-form helper using the current request locale."""
    locale = get_current_locale()
    category = get_plural_form(locale, n)
    return singular if category == "one" else plural
```

### 4.5 Fallback chain resolver with loop detection

```python
# app/core/fallback_chain.py
"""
FallbackChainResolver: loads per-locale fallback chains from YAML config,
validates for loops, and exposes a resolve() method used by locale_context.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import yaml


class FallbackLoopError(RuntimeError):
    """Raised when a fallback chain contains a cycle."""


class FallbackChainResolver:
    def __init__(self, chain_map: dict[str, list[str]], default_locale: str) -> None:
        self._chain: dict[str, list[str]] = {}
        self._default = default_locale
        for locale, fallbacks in chain_map.items():
            self._validate_no_loop(locale, fallbacks, chain_map)
            self._chain[locale] = fallbacks

    def _validate_no_loop(
        self,
        start: str,
        chain: list[str],
        all_chains: dict[str, list[str]],
    ) -> None:
        visited: set[str] = {start}
        queue = list(chain)
        while queue:
            node = queue.pop(0)
            if node in visited:
                raise FallbackLoopError(
                    f"Fallback loop detected: {start!r} eventually chains back to {node!r}. "
                    "Resolve by ensuring the chain terminates at the default locale."
                )
            visited.add(node)
            queue.extend(all_chains.get(node, []))

    def resolve(self, locale: str) -> Iterator[str]:
        """Yield locale candidates in priority order, ending with default."""
        yield locale
        for fallback in self._chain.get(locale, []):
            yield from self.resolve(fallback)
        if locale != self._default:
            yield self._default

    @classmethod
    def from_yaml(cls, path: Path, default_locale: str) -> "FallbackChainResolver":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(data.get("fallback_chains", {}), default_locale)
```

### 4.6 Number, currency, and date formatters

```python
# app/core/locale_formatters.py
"""
Locale-aware formatting for numbers, currencies, and dates.
Delegates entirely to Babel's CLDR-backed format_* functions.
All functions use the current request locale from ContextVar.

Usage:
    from app.core.locale_formatters import fmt_number, fmt_currency, fmt_date
    label = _("Balance: {amount}", amount=fmt_currency(1234.56, "USD"))
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from babel.dates import format_date, format_datetime
from babel.numbers import format_currency as babel_fmt_currency
from babel.numbers import format_decimal, format_number

from app.core.locale_context import get_current_locale


def fmt_number(value: float | Decimal, *, group_sep: bool = True) -> str:
    """Format a numeric value per the current locale's decimal/grouping rules."""
    locale = get_current_locale()
    return format_decimal(value, locale=locale)


def fmt_currency(value: float | Decimal, currency: str = "USD") -> str:
    """
    Format a monetary value with the correct symbol position and decimal mark.
    e.g. fmt_currency(1234.56, "EUR") → "$1,234.56" (en_US) or "1.234,56 €" (de_DE)
    """
    locale = get_current_locale()
    return babel_fmt_currency(value, currency=currency, locale=locale)


def fmt_date(value: date, fmt: str = "medium") -> str:
    """
    Format a date per the locale's regional convention.
    fmt: 'full' | 'long' | 'medium' | 'short'
    e.g. fmt_date(date(2026,4,12)) → "Apr 12, 2026" (en_US) or "12 avr. 2026" (fr_FR)
    """
    locale = get_current_locale()
    return format_date(value, format=fmt, locale=locale)


def fmt_datetime(value: datetime, fmt: str = "medium") -> str:
    """Format a datetime with timezone-aware display per current locale."""
    locale = get_current_locale()
    return format_datetime(value, format=fmt, locale=locale)
```

### 4.7 RTL locale metadata hook

```python
# app/core/locale_meta.py
"""
LocaleMeta: static metadata per supported locale.
is_rtl: True for ar, he, fa, ur (and variants).
Used by LocaleMiddleware to inject X-Text-Direction header.
Also used by template contexts to set HTML dir attribute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


_RTL_LANGUAGES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})


@dataclass(frozen=True)
class LocaleMeta:
    code: str          # BCP-47 code, e.g. "ar_SA"
    is_rtl: bool
    display_name: str  # English display name for UI dropdowns
    native_name: str   # Name in the locale's own script

    @classmethod
    def for_code(cls, code: str) -> "LocaleMeta":
        lang = code.split("_")[0].lower()
        is_rtl = lang in _RTL_LANGUAGES
        # display_name/native_name from LOCALE_REGISTRY or Babel as fallback
        from babel import Locale as BabelLocale
        babel_locale = BabelLocale.parse(code)
        return cls(
            code=code,
            is_rtl=is_rtl,
            display_name=babel_locale.get_display_name("en_US") or code,
            native_name=babel_locale.get_display_name(code) or code,
        )


def build_locale_registry(supported_locales: list[str]) -> dict[str, LocaleMeta]:
    return {loc: LocaleMeta.for_code(loc) for loc in supported_locales}


# Runtime registry — populated during app startup
LOCALE_META: dict[str, LocaleMeta] = {}
```

### 4.8 Missing-translation audit CLI

```python
# scripts/audit_translations.py
"""
CLI: scan all .po files and report untranslated / fuzzy strings per locale.
Exits with code 1 if any locale exceeds the configured threshold.
Run: python scripts/audit_translations.py --locales-dir locales --threshold 5
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import polib  # pip install polib


def audit_locale(po_path: Path) -> dict[str, int]:
    """Return counts of total, translated, fuzzy, untranslated entries."""
    po = polib.pofile(str(po_path))
    return {
        "total": len(po),
        "translated": len(po.translated_entries()),
        "fuzzy": len(po.fuzzy_entries()),
        "untranslated": len(po.untranslated_entries()),
        "percent": int(po.percent_translated()),
    }


@click.command()
@click.option("--locales-dir", default="locales", type=click.Path(exists=True))
@click.option("--threshold", default=0, help="Max allowed untranslated strings")
@click.option("--fail-on-fuzzy", is_flag=True, default=False)
def main(locales_dir: str, threshold: int, fail_on_fuzzy: bool) -> None:
    root = Path(locales_dir)
    failed = False
    print(f"{'Locale':<12} {'Total':>6} {'Translated':>12} {'Fuzzy':>8} {'Missing':>9} {'Pct':>6}")
    print("-" * 60)
    for po_path in sorted(root.glob("*/LC_MESSAGES/messages.po")):
        locale = po_path.parts[-3]
        stats = audit_locale(po_path)
        flag = ""
        if stats["untranslated"] > threshold:
            flag = " ← FAIL"
            failed = True
        if fail_on_fuzzy and stats["fuzzy"] > 0:
            flag = " ← FUZZY"
            failed = True
        print(
            f"{locale:<12} {stats['total']:>6} {stats['translated']:>12} "
            f"{stats['fuzzy']:>8} {stats['untranslated']:>9} {stats['percent']:>5}%{flag}"
        )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

### 4.9 Babel extraction config

```ini
# babel.cfg
[python: app/**.py]
encoding = utf-8
keywords = _ ngettext:1,2 lazy_gettext

[jinja2: app/templates/**.html]
encoding = utf-8
extensions = jinja2.ext.autoescape,jinja2.ext.with_
```

### 4.10 Pytest test suite for middleware and catalog

```python
# tests/i18n/test_locale_middleware.py
"""
Unit + integration tests for LocaleMiddleware, _() helper, ngettext, and formatters.
Uses pytest-anyio for async middleware dispatch tests.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.api.middleware.locale import LocaleMiddleware, _parse_accept_language, _negotiate
from app.core.locale_context import _, get_current_locale, preload_catalogs, set_current_locale
from app.core.icu_plurals import get_plural_form, format_plural
from app.core.locale_formatters import fmt_number, fmt_currency, fmt_date


# ── Accept-Language parser ──────────────────────────────────────────────────

def test_parse_accept_language_sorts_by_q():
    result = _parse_accept_language("fr;q=0.9,en_US;q=1.0,de;q=0.7")
    assert result[0] == "en_US"
    assert result[1] == "fr"
    assert result[2] == "de"


def test_negotiate_exact_match():
    assert _negotiate(["pt_BR"], {"pt_BR", "en_US"}, "en_US") == "pt_BR"


def test_negotiate_language_fallback():
    # pt_PT not supported but pt_BR is — language prefix match
    assert _negotiate(["pt_PT"], {"pt_BR", "en_US"}, "en_US") == "pt_BR"


def test_negotiate_returns_default_when_no_match():
    assert _negotiate(["ja_JP"], {"en_US", "pt_BR"}, "en_US") == "en_US"


# ── RTL header injection ────────────────────────────────────────────────────

def test_rtl_header_injected_for_arabic():
    app = FastAPI()
    app.add_middleware(LocaleMiddleware)

    @app.get("/test")
    async def endpoint():
        return {"locale": get_current_locale()}

    with patch("app.core.config.settings.SUPPORTED_LOCALES", ["ar", "en_US"]):
        with patch("app.core.config.settings.DEFAULT_LOCALE", "en_US"):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/test", headers={"X-Locale": "ar"})
            assert resp.headers.get("X-Text-Direction") == "rtl"


# ── Plural rules ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("locale,n,expected", [
    ("en_US", 1, "one"),
    ("en_US", 2, "other"),
    ("ar", 0, "zero"),
    ("ar", 1, "one"),
    ("ar", 2, "two"),
    ("ar", 3, "few"),
    ("ar", 11, "many"),
    ("ar", 100, "other"),
    ("pl", 1, "one"),
    ("pl", 2, "few"),
    ("pl", 5, "many"),
])
def test_plural_form(locale, n, expected):
    assert get_plural_form(locale, n) == expected


# ── Currency formatting ─────────────────────────────────────────────────────

def test_currency_formatting_us():
    set_current_locale("en_US")
    assert fmt_currency(1234.56, "USD") == "$1,234.56"


def test_currency_formatting_german():
    set_current_locale("de_DE")
    formatted = fmt_currency(1234.56, "EUR")
    assert "1.234,56" in formatted or "1234,56" in formatted
```

---

## 5. Quality Standards

| QS-N | Standard | Enforcement |
|------|----------|-------------|
| QS-1 | **BCP-47 locale codes everywhere** | Enforcement: `ruff` custom rule rejects underscore-less locale strings in middleware config |
| QS-2 | **Compiled `.mo` files required at startup** | Enforcement: `preload_catalogs()` raises `FileNotFoundError` if any `.mo` is absent |
| QS-3 | **`pybabel update` never overwrites human edits** | Enforcement: CI runs `pybabel update --no-fuzzy-matching=False`; diff gate fails if existing msgstr lines are deleted |
| QS-4 | **All user-facing strings wrapped with `_()`** | Enforcement: `ruff` plugin or grep pre-commit hook scans `raise HTTPException` and string literals not through `_()` |
| QS-5 | **Plural rules from CLDR, never hardcoded** | Enforcement: `grep -r "== 1 else"` pre-commit hook fails; `ngettext` and `pluralize()` are the only permitted plural paths |
| QS-6 | **RTL flag set for ar, he, fa, ur** | Enforcement: `test_rtl_metadata_all_locales` parameterized test validates `LocaleMeta.is_rtl` for every known RTL locale |
| QS-7 | **Missing-translation audit passes in CI** | Enforcement: `make i18n-audit` step in GitHub Actions workflow exits 1 on untranslated strings above threshold |
| QS-8 | **No locale resolution on every `_()` call** | Enforcement: code review; `_()` reads ContextVar (O(1)); catalog is pre-loaded dict; no file I/O at lookup time |
| QS-9 | **`.po` files version-controlled** | Enforcement: `.gitignore` must NOT exclude `locales/**/*.po`; only `*.mo` is excluded (binary) |
| QS-10 | **Fallback chain is loop-free** | Enforcement: `FallbackChainResolver.__init__` raises `FallbackLoopError` at startup if a cycle is detected |
| QS-11 | **Default locale always resolvable** | Enforcement: `preload_catalogs()` always loads default locale first; if it fails the server refuses to start |
| QS-12 | **Locale-aware date/number formatting uses Babel** | Enforcement: `ruff` custom rule warns on `str(datetime)` or `f"{number}"` in response-layer code (should use `fmt_*`) |

---

## 6. Completeness Criteria

| CC-N | Criterion | Verification |
|------|-----------|--------------|
| CC-001 | `LocaleMiddleware` registered in `main.py` before route-level middleware | `grep LocaleMiddleware app/main.py` returns exactly one match |
| CC-002 | `_()` helper importable from `app.core.locale_context` and used in ≥ 1 route | `grep -r "from app.core.locale_context import _" app/` has ≥ 1 hit |
| CC-003 | `ngettext()` importable from `app.core.babel_translator` and handles English plural | `pytest tests/i18n/test_gettext_helper.py::test_ngettext_english` passes |
| CC-004 | `LazyString` class supports `str()` coercion for module-level constants | `str(lazy_gettext("Hello"))` returns translated string without exception |
| CC-005 | `babel.cfg` at project root with `[python: app/**.py]` section | `grep "\[python" babel.cfg` returns match |
| CC-006 | `locales/` has per-locale subdirs `locales/{locale}/LC_MESSAGES/messages.po` | `find locales -name messages.po \| wc -l` equals `len(supported_locales)` |
| CC-007 | `locales/messages.pot` generated by `pybabel extract` when `extract_from_source=True` | File exists with ≥ 1 `msgid` entry |
| CC-008 | Each `.po` stub has `Content-Type: text/plain; charset=UTF-8` and CLDR `Plural-Forms` | `grep "Plural-Forms" locales/*/LC_MESSAGES/messages.po` has one match per locale |
| CC-009 | `pybabel compile` in `Makefile` compiles `.po → .mo` and exits non-zero on syntax errors | `make i18n-compile && ls locales/*/LC_MESSAGES/messages.mo` shows all `.mo` files |
| CC-010 | `pybabel update` merges new strings without discarding existing translations | Git diff after update shows no deleted `msgstr` lines |
| CC-011 | `preload_catalogs()` called at startup; loads all `.mo` into `_catalog_cache` | Startup log shows `Loaded {n} locale catalogs`; missing `.mo` raises `FileNotFoundError` |
| CC-012 | `FallbackChainResolver` instantiated from `fallback_chains.yaml` at startup | `_get_translation()` calls `resolver.resolve(locale)` on cache miss |
| CC-013 | `format_plural()` covers Arabic (6-form), Polish (3-form), Russian (4-form) | `pytest tests/i18n/test_plural_rules.py -k "arabic or polish or russian"` passes |
| CC-014 | `fmt_number()`, `fmt_currency()`, `fmt_date()` delegate to Babel CLDR | `pytest tests/i18n/test_formatters.py` passes; ≥ 1 route uses `fmt_currency` |
| CC-015 | `LocaleMeta.is_rtl` is `True` for `ar`, `ar_SA`, `ar_EG`, `he`, `fa`, `ur` variants | Parametrized test T-22 passes for all 9 RTL locale codes |
| CC-016 | `X-Text-Direction: rtl` injected by `LocaleMiddleware` for RTL locales only | Integration test T-22 asserts header presence/absence per locale |
| CC-017 | `Content-Language` response header set on every response with BCP-47 hyphenated code | Test T-23 asserts `Content-Language` present on all endpoints including error responses |
| CC-018 | `audit_translations.py` CLI accepts `--locales-dir`, `--threshold`, `--fail-on-fuzzy` | `python scripts/audit_translations.py --help` shows all three flags |
| CC-019 | GitHub Actions `i18n.yml` runs `extract + compile + audit` on every push to `main` | Workflow file exists; CI passes on clean repo |
| CC-020 | `tests/i18n/` has: `test_locale_middleware.py`, `test_gettext_helper.py`, `test_plural_rules.py`, `test_formatters.py`, `test_fallback_chain.py`, `test_audit_cli.py` | `ls tests/i18n/*.py \| wc -l` ≥ 6 |
| CC-021 | All test files have ≥ 3 assertions and cover at least one failure mode | `pytest tests/i18n/ -v` shows ≥ 30 passed |
| CC-022 | `pyproject.toml` has `babel`, `polib` in `[project.optional-dependencies.i18n]` | `grep -A5 '\[project.optional-dependencies\]' pyproject.toml` shows `babel` |
| CC-023 | `config.py` exposes `DEFAULT_LOCALE` and `SUPPORTED_LOCALES` from env vars | `I18N_DEFAULT_LOCALE=fr_FR pytest tests/i18n/test_config.py` shows `fr_FR` as default |
| CC-024 | `LOCALE_META` dict populated at startup; `GET /api/v1/locales` returns full list | Test T-24 validates response schema including `is_rtl` field |
| CC-025 | `configs/fallback_chains.yaml` has `pt_PT → pt_BR → en_US` and `es_419 → es_MX → en_US` | `cat configs/fallback_chains.yaml` shows both chains |
| CC-026 | `Makefile` has all 6 targets: `i18n-extract`, `i18n-update`, `i18n-compile`, `i18n-audit`, `i18n-clean`, `i18n-new-locale` | `grep "^i18n-" Makefile \| wc -l` ≥ 6 |
| CC-027 | `GET /api/v1/locales` returns `code`, `display_name`, `native_name`, `is_rtl` per locale | Test T-24 validates JSON schema against Pydantic model |
| CC-028 | `PUT /api/v1/me/locale` stores preference in session or `user_preferences.locale` | Integration test sets locale, subsequent request uses stored locale |
| CC-029 | `docs/i18n.md` documents extract → edit `.po` → compile → deploy workflow | File exists with ≥ 100 lines covering all workflow phases |
| CC-030 | Tool idempotent: second run preserves translations, no duplicate middleware, no reset | Test T-28 diffs file hashes before and after second `add_i18n()` invocation |

---

## 7. Definition of Done

- [ ] `LocaleMiddleware` registered in `main.py`, resolves locale from all 4 sources in correct priority order
- [ ] `_()` and `ngettext()` helpers importable from `app.core.locale_context` and `app.core.babel_translator`
- [ ] `babel.cfg` generated at project root with correct Python and optional Jinja2 sections
- [ ] Per-locale `.po` stubs generated for all `supported_locales` with correct CLDR `Plural-Forms` headers
- [ ] `preload_catalogs()` called at startup; server refuses to start if any locale's `.mo` is missing
- [ ] `FallbackChainResolver` instantiated; loop detection raises `FallbackLoopError` at startup, not at request time
- [ ] `format_plural()` covers Arabic 6-form, Polish 3-form, Russian 4-form using CLDR rules
- [ ] `LocaleMeta.is_rtl` correct for all RTL language codes; `X-Text-Direction` header injected automatically
- [ ] `fmt_number()`, `fmt_currency()`, `fmt_date()` use Babel CLDR; demonstrated in one route
- [ ] `audit_translations.py` CLI runs, prints per-locale table, exits 1 when threshold exceeded
- [ ] GitHub Actions `i18n.yml` workflow runs extract + compile + audit on every push
- [ ] `Makefile` includes all 6 `i18n-*` targets; `make i18n-compile` blocks deploy on `.po` syntax errors
- [ ] All 30 test cases in Test Plan pass with `pytest tests/i18n/ -v`
- [ ] `pyproject.toml` updated with `babel`, `polib`, optional `PyICU` under `[project.optional-dependencies.i18n]`
- [ ] Tool re-run is idempotent; existing `.po` translations are never overwritten

---

## 8. Invariants

| ID | Invariant | Enforcement | Test Ref |
|----|-----------|-------------|----------|
| INV-I18N-001 | Default locale ALWAYS resolvable — fallback chain always terminates at `DEFAULT_LOCALE` | `preload_catalogs()` loads default first; `FallbackChainResolver.resolve()` always yields default as final candidate; server refuses to start if default `.mo` is missing | T-06 |
| INV-I18N-002 | Missing translations NEVER raise — fall through entire chain, return raw msgid as absolute last resort | `_get_translation()` returns msgid string if all chain members miss; `_()` wraps in try/except; never raises `KeyError` or `MissingTranslationError` | T-25 |
| INV-I18N-003 | Catalogs ALWAYS compiled to `.mo` before server starts — no `.po`-only runtime | `preload_catalogs()` raises `FileNotFoundError` on missing `.mo`; CI blocks deploy via `make i18n-compile` non-zero exit; Makefile compile step is required, not optional | T-11 |
| INV-I18N-004 | Extraction ALWAYS idempotent — `pybabel update` merges new strings, never overwrites human-translated `msgstr` values | CI diff gate verifies no existing `msgstr` lines are deleted after `pybabel update`; `--no-fuzzy-matching=False` flag preserves fuzzy context entries | T-09 |
| INV-I18N-005 | Locale codes ALWAYS BCP-47 compliant — underscore separator, no ad-hoc lowercased codes | `LocaleMeta.for_code()` validates against Babel locale database; invalid codes raise `babel.core.UnknownLocaleError` at startup, not at request time | T-04 |
| INV-I18N-006 | RTL flag ALWAYS set for `ar`, `he`, `fa`, `ur` and ALL regional variants — never omitted | `_RTL_LANGUAGES` frozenset drives `LocaleMeta.is_rtl`; `X-Text-Direction: rtl` header injected by middleware on every response; parametrized test T-22 covers all 9 known RTL locale codes | T-22 |
| INV-I18N-007 | Plural rules ALWAYS from CLDR via Babel or PyICU — hardcoded `if n == 1` is FORBIDDEN | `get_plural_form()` is the single source of truth for all plural category selection; `ruff` pre-commit hook rejects `"== 1 else"` pattern in route and service layer code | T-13, T-15 |
| INV-I18N-008 | Fallback chain ALWAYS loop-free — cycle detected at startup, NEVER at request time | `FallbackChainResolver.__init__` performs full DFS traversal; raises `FallbackLoopError` before the first request is served; loop in YAML config prevents server startup | T-27 |

---

## 9. User Stories

### 9.1 Basic Translation

**US-01: Developer wraps a hardcoded string with `_()`**
- **As a** backend developer who has an existing English string literal in a route handler
- **I want** to replace `"Item not found"` with `_("Item not found")` imported from `app.core.locale_context`
- **So that** the string is extracted by `pybabel extract` and served translated to non-English clients without altering the function signature
- **Given:** `locale_context.py` is generated and `_` is importable; `pt_BR` `.mo` catalog has `msgid "Item not found"` → `msgstr "Item não encontrado"`
- **When:** a request arrives with resolved locale `pt_BR` and the route calls `_("Item not found")`
- **Then:**
  - `_()` reads the active `ContextVar`, opens the `pt_BR` `GNUTranslations` catalog, and returns `"Item não encontrado"` — no locale arg passed explicitly
  - If `msgstr` is empty the function returns the English msgid, never an empty string (INV-I18N-002)
  - T-07 compiles a real test `.mo` and asserts exact string match

**US-02: Translator preserves existing work across `pybabel update`**
- **As a** human translator who has already translated 400 strings in `locales/pt_BR/LC_MESSAGES/messages.po`
- **I want** a developer's `make i18n-update` run (after new source strings were added) to merge only the new entries without touching my completed translations
- **So that** I never have to redo finished work because a developer ran an extraction cycle
- **Given:** the `.po` file contains 400 non-empty `msgstr` entries and the source gained 10 new `msgid` values
- **When:** `pybabel update -i messages.pot -d locales -l pt_BR` executes
- **Then:**
  - All 400 previously translated entries remain unchanged (INV-I18N-004)
  - 10 new entries appear with empty `msgstr` ready for translation
  - Entries where the English source changed slightly are marked `#, fuzzy` but not deleted (CC-009, CC-010)
  - T-09 diffs `.po` before and after and asserts only additive changes

**US-03: Broken `.po` kills the build, not production**
- **As a** DevOps engineer running a CI/CD pipeline
- **I want** `make i18n-compile` to exit with code 1 when any `.po` file contains mismatched Python format specifiers
- **So that** a corrupt catalog can never reach the production server where it would cause a runtime `KeyError` or `TypeError` on string interpolation
- **Given:** `locales/de_DE/LC_MESSAGES/messages.po` contains `msgid "Hello %s"` paired with `msgstr "Hallo"` (missing `%s`)
- **When:** `pybabel compile --statistics -d locales` runs as part of `make i18n-compile`
- **Then:**
  - `pybabel compile` exits with code 1 and prints the offending file path and line number
  - No `.mo` file is written for `de_DE`, blocking the deploy (INV-I18N-003)
  - `preload_catalogs()` at startup also fails with `FileNotFoundError` if someone bypasses the Makefile
  - T-10 asserts `.mo` presence for a valid `.po` and absence when the `.po` is malformed; T-29 checks compile exit code

**US-04: New locale scaffolded without overwriting existing work**
- **As a** developer tasked with adding Mexican Spanish support mid-project
- **I want** `make i18n-new-locale LOCALE=es_MX` to create `locales/es_MX/LC_MESSAGES/messages.po` pre-populated with all existing msgids and empty msgstr fields
- **So that** a translator can start immediately with a complete list of strings rather than having to discover them manually
- **Given:** `messages.pot` already contains 350 msgid entries extracted from the source; `locales/es_MX/` does not yet exist
- **When:** `pybabel init -i messages.pot -d locales -l es_MX` runs via the Makefile target
- **Then:**
  - `locales/es_MX/LC_MESSAGES/messages.po` is created with all 350 msgid entries and blank msgstr (CC-008, CC-026)
  - `python scripts/audit_translations.py --locale es_MX` reports 0% translated and exits 1 as expected
  - If `es_MX` already exists, the Makefile detects it and runs `pybabel update` instead, never destroying prior work (CC-030)
  - T-12 verifies new locale scaffold end-to-end via subprocess

**US-05: HTTP exception detail is translated end-to-end**
- **As a** French-speaking API consumer calling `GET /items/9999`
- **I want** the 404 error body to contain `{"detail": "Ressource introuvable"}` rather than the English original
- **So that** my client application can display the error directly without client-side translation logic
- **Given:** the route raises `HTTPException(status_code=404, detail=_("Resource not found"))`; `fr_FR.mo` has the French translation; request header is `Accept-Language: fr-FR,fr;q=0.9`
- **When:** `LocaleMiddleware` resolves `fr_FR`, sets the ContextVar, and the route handler runs
- **Then:**
  - `_("Resource not found")` returns `"Ressource introuvable"` because the ContextVar is set before the handler executes (INV-I18N-002, CC-002)
  - The JSON response body is `{"detail": "Ressource introuvable"}` with `Content-Language: fr-FR`
  - If the specific msgid is absent in `fr_FR.mo`, English fallback is returned seamlessly with no exception
  - T-08 integration test asserts the French string in the response body and the Content-Language header

### 9.2 Locale Detection

**US-06: Query parameter `?lang=` overrides every other signal**
- **As a** frontend developer debugging a locale-specific rendering issue in staging
- **I want** to append `?lang=de_DE` to any URL and have that locale used unconditionally, overriding my browser's `Accept-Language` and any stored session preference
- **So that** I can verify German translations without switching my OS language or clearing session state
- **Given:** the request has `Accept-Language: en_US` and a session cookie with `locale=ja_JP`; `?lang=de_DE` is in the query string; `de_DE` is in `SUPPORTED_LOCALES`
- **When:** `LocaleMiddleware.dispatch()` evaluates the four resolution sources in priority order
- **Then:**
  - `current_locale` ContextVar is set to `de_DE` — query param wins (CC-001, T-01)
  - If `?lang=xx_YY` is an unsupported locale the middleware silently skips it and tries the next source
  - The `Content-Language: de-DE` response header confirms the resolved locale to the caller
  - T-01 sends conflicting `?lang=` and `Accept-Language` values and asserts the ContextVar value

**US-07: Accept-Language BCP-47 quality-value negotiation**
- **As a** browser sending `Accept-Language: pt-PT,pt;q=0.9,en;q=0.8`
- **I want** the API to resolve to `pt_BR` when `pt_PT` is absent from the supported list, because Brazilian Portuguese is far closer to European Portuguese than English
- **So that** Portuguese speakers in Portugal receive translated content even if only `pt_BR` is deployed
- **Given:** `SUPPORTED_LOCALES = {"pt_BR", "en_US"}`; the Accept-Language header lists `pt-PT` first (q=1.0)
- **When:** `_parse_accept_language` parses the header and `_negotiate` compares against supported locales
- **Then:**
  - `pt_PT` misses exact match; language-prefix `pt` matches `pt_BR` (INV-I18N-001, CC-001)
  - `_negotiate(["pt_PT","pt","en"], {"pt_BR","en_US"}, "en_US")` returns `"pt_BR"`
  - A wildcard `Accept-Language: *` or a completely malformed header falls back to `DEFAULT_LOCALE` silently
  - T-04 covers 8 parameterized Accept-Language patterns including multi-tag with q-values, wildcard, and malformed input

**US-08: Authenticated user's saved locale preference beats Accept-Language**
- **As a** logged-in user who has set Japanese as my preferred language via `PUT /api/v1/me/locale`
- **I want** every subsequent API response to be in Japanese even if my work laptop sends `Accept-Language: en_US`
- **So that** I do not have to reconfigure my browser to use the app in my chosen language
- **Given:** session cookie carries `locale=ja_JP`; request header is `Accept-Language: en_US`; `ja_JP` is in `SUPPORTED_LOCALES`
- **When:** `LocaleMiddleware` evaluates source 3 (user preference from session)
- **Then:**
  - `ja_JP` from session is resolved before Accept-Language is evaluated (CC-001, CC-028)
  - If `ja_JP` is later removed from `SUPPORTED_LOCALES` by an admin, middleware falls through to Accept-Language rather than raising
  - `Content-Language: ja-JP` is set on the response
  - T-03 simulates session with a stored locale preference and asserts ContextVar and response header

**US-09: Fallback chain traverses configured intermediate locales**
- **As a** `pt_PT` speaker consuming an API that only deploys `pt_BR` and `en_US` catalogs
- **I want** `_("Submit")` to return the `pt_BR` translation rather than English
- **So that** I receive content in the closest available dialect, not a completely foreign language
- **Given:** `fallback_chain = {"pt_PT": ["pt_BR", "en_US"]}` in `configs/fallback_chains.yaml`; `pt_PT` is NOT in `SUPPORTED_LOCALES`
- **When:** `FallbackChainResolver.resolve("pt_PT")` is called inside `LocaleMiddleware`
- **Then:**
  - Chain traversal yields `pt_PT → pt_BR → en_US`; first hit with a compiled `.mo` wins (INV-I18N-001, INV-I18N-002, CC-025)
  - `get_current_locale()` inside the route handler returns `"pt_BR"`
  - If `fallback_chains.yaml` has no entry for a locale, the resolver auto-chains directly to `DEFAULT_LOCALE`
  - T-05 verifies the traversal and asserts the ContextVar is set to `pt_BR`, not `pt_PT`

**US-10: System returns a valid response even when every locale signal fails**
- **As a** system operator responsible for API SLA
- **I want** every request to receive a correctly structured response regardless of how malformed or unsupported the client's locale signals are
- **So that** a misconfigured client never triggers a 500 error caused by an unresolved locale
- **Given:** the request has no `?lang=`, no `X-Locale` header, no session, and `Accept-Language: xx-XX` (not in `SUPPORTED_LOCALES`)
- **When:** `LocaleMiddleware` exhausts all four resolution sources
- **Then:**
  - Locale resolves to `DEFAULT_LOCALE` (INV-I18N-001, T-06)
  - `Content-Language` header is set to the default locale's BCP-47 tag
  - If `DEFAULT_LOCALE` `.mo` is corrupt, `preload_catalogs()` fails at server startup — not at request time — so no request ever hits a broken catalog
  - T-06 sends all-unsupported locale signals and asserts the default locale in the ContextVar and response headers

### 9.3 Pluralization & ICU

**US-11: English two-form plural with explicit zero-state handling**
- **As a** developer rendering item counts in an English-language REST response
- **I want** `ngettext("item", "items", count)` to return "item" for count=1, "items" for all other counts, and to support an explicit "No items" zero-state without falling through to "0 items"
- **So that** English responses are grammatically correct for all count values without bespoke `if count == 1` guards scattered through route handlers
- **Given:** the `pt_BR` catalog has `ngettext` translated; `en_US` catalog follows standard two-form plural
- **When:** `ngettext("item", "items", n)` is called for n ∈ {0, 1, 2, 5, 11, 21}
- **Then:**
  - n=1 returns singular form; all others return plural (CC-013)
  - `format_plural("en_US", 0, {"zero":"No items","one":"1 item","other":"{n} items"})` returns `"No items"` — the explicit `zero` key is checked before CLDR category lookup
  - English CLDR has no built-in "zero" category, so the developer-supplied `zero` key is an intentional override
  - T-13 is parameterized over all six count values; T-17 specifically tests the `zero` key override

**US-12: Arabic six-form CLDR plural rules applied correctly**
- **As an** Arabic-speaking end user viewing item counts in an Arabic-localized response
- **I want** the count text to use all six CLDR plural forms (zero, one, two, few, many, other) rather than a binary singular/plural split
- **So that** the text reads as native Arabic and not as a mechanical calque of English grammar
- **Given:** the `ar` catalog has all six plural form translations; PyICU or Babel is available
- **When:** `get_plural_form("ar", n)` is called for n ∈ {0, 1, 2, 3, 11, 100}
- **Then:**
  - Returns `"zero"`, `"one"`, `"two"`, `"few"`, `"many"`, `"other"` respectively (INV-I18N-007, CC-013)
  - Arabic dialect codes `ar_SA` and `ar_EG` inherit rules from base `ar` locale via Babel's CLDR chain
  - If `ar_SA` is the resolved locale and no `ar_SA.mo` exists, the fallback chain reaches base `ar` before `en_US`
  - T-15 is parameterized over all six Arabic plural categories and asserts the returned category name

**US-13: Polish three-category irregular plural rules**
- **As a** Polish-speaking user viewing a file count in a Polish-localized UI
- **I want** "2 pliki" (few), "5 plików" (many), and "22 pliki" (few again, despite being >20) to be grammatically correct
- **So that** the application does not produce unnatural Polish like "5 plikis" due to incorrect English-style plural logic
- **Given:** the `pl` catalog has three plural form translations mapped to CLDR categories `one`, `few`, `many`
- **When:** `get_plural_form("pl", n)` is called for n ∈ {1, 2, 5, 11, 21, 22}
- **Then:**
  - n=1 → `"one"`, n=2 → `"few"`, n=5 → `"many"`, n=11 → `"many"`, n=21 → `"few"`, n=22 → `"few"` (INV-I18N-007, CC-013)
  - `pl_PL` locale code resolves to the same plural rules as base `pl` via Babel
  - T-14 covers all six Polish test values and asserts exact CLDR category names

**US-14: ICU MessageFormat gender-sensitive strings in French**
- **As a** developer localizing a French notification that reads "Elle a envoyé un fichier" vs "Il a envoyé un fichier" depending on sender gender
- **I want** to use a single ICU MessageFormat msgid with a `{gender, select, female{...} male{...} other{...}}` pattern rather than two separate msgids
- **So that** translators manage one entry per sentence rather than combinatorially exploding the catalog with every gender/plural combination
- **Given:** PyICU ≥ 2.11 is optionally installed; `babel_translator.py` detects its presence and routes ICU patterns through `icu.MessageFormat`
- **When:** `format_plural("fr_FR", 1, {"one":"...", "other":"..."})` is called with an ICU-pattern msgid
- **Then:**
  - When PyICU is installed, `icu.MessageFormat` handles the pattern (CC-013, INV-I18N-007)
  - When PyICU is absent, Babel's CLDR plural rules provide correct output for >95% of cases without ICU
  - T-16 runs conditionally via `pytest.importorskip("icu")` and asserts identical output from both paths for the same locale/n pairs

**US-15: Russian four-form plural via CLDR**
- **As a** Russian-speaking user viewing a file count in a Russian interface
- **I want** "21 файл" (one form, not "21 файлы"), "2 файла" (few), and "5 файлов" (many) because Russian plurals follow a modular remainder rule that has no analogue in English
- **So that** the UI does not sound illiterate to native Russian speakers
- **Given:** the `ru` catalog has four plural form translations for CLDR categories `one`, `few`, `many`, `other`
- **When:** `get_plural_form("ru", n)` is called for n ∈ {1, 2, 5, 11, 21}
- **Then:**
  - n=1 → `"one"`, n=2 → `"few"`, n=5 → `"many"`, n=11 → `"many"`, n=21 → `"one"` (T-18, CC-013)
  - Babel's CLDR database drives the rule; no hand-coded `if/elif` chains exist in the generated helper
  - T-18 is parameterized over the five values and asserts category names match CLDR `ru` plural rules exactly

### 9.4 Formatting

**US-16: Dates rendered in locale-appropriate medium format**
- **As a** Japanese-speaking API consumer receiving a `created_at` field in a REST response
- **I want** dates to be formatted as "2026年4月12日" rather than "Apr 12, 2026" so that I can display them directly without client-side reformatting
- **Given:** `fmt_date(date(2026, 4, 12))` is called inside the response serializer; resolved locale is `ja_JP`
- **When:** the serializer calls `format_date(value, format="medium", locale=get_current_locale())`
- **Then:**
  - `ja_JP` → `"2026年4月12日"`, `en_US` → `"Apr 12, 2026"`, `fr_FR` → `"12 avr. 2026"`, `de_DE` → `"12.04.2026"` (CC-014)
  - UTC datetimes with timezone info are formatted in the timezone supplied or the default; no implicit timezone conversion is performed
  - T-19 is parameterized over all four locales and asserts exact Babel `format_date` output against a fixed reference date

**US-17: Number grouping separators match locale convention**
- **As a** German user reading a dashboard that shows total event count as `1.234.567`
- **I want** the thousands separator to be a period and the decimal mark to be a comma, matching German typographic convention
- **So that** I do not have to mentally parse an anglophone number format mid-sentence
- **Given:** `fmt_number(1234567.89)` is called; resolved locale is `de_DE`
- **When:** `format_decimal(value, locale="de_DE")` executes inside `fmt_number`
- **Then:**
  - Output is `"1.234.567,89"` with period grouping and comma decimal (CC-014, T-20)
  - `en_US` produces `"1,234,567.89"`; `fr_FR` produces `"1\u202f234\u202f567,89"` (narrow no-break space grouping)
  - Integer values produce no decimal separator; Babel handles this without extra guards
  - T-20 covers `en_US`, `de_DE`, `fr_FR`, `pt_BR` and asserts each exact formatted string

**US-18: Currency symbol position and decimal format follow CLDR**
- **As a** Brazilian user viewing a product price
- **I want** prices displayed as "R$\u00a01.234,56" — the Brazilian Real symbol before the amount, using comma decimal and period thousands — not the international "$1,234.56" format
- **So that** the price looks like a price in my locale, not a converted foreign-currency amount
- **Given:** `fmt_currency(1234.56, "BRL")` is called; resolved locale is `pt_BR`
- **When:** `format_currency(value, currency, locale=get_current_locale())` runs
- **Then:**
  - `pt_BR / BRL` → `"R$\u00a01.234,56"`; `de_DE / EUR` → `"1.234,56\u00a0€"`; `en_US / USD` → `"$1,234.56"` (CC-014, T-21)
  - Saudi Riyal `SAR / ar_SA` uses Arabic locale formatting including Arabic-Indic digit preference if configured
  - Unrecognised currency codes (e.g. `BTC`) are not in CLDR; Babel falls back to the ISO code as symbol with no crash
  - T-21 asserts symbol position, decimal/group separators, and non-breaking space for all four currency/locale pairs

**US-19: RTL direction header injected automatically for Arabic, Hebrew, Farsi, Urdu**
- **As a** frontend developer building a Svelte SPA that consumes the API
- **I want** a `X-Text-Direction: rtl` header in every response when the resolved locale is Arabic, Hebrew, Farsi, or Urdu
- **So that** I can apply `document.documentElement.dir = response.headers.get("X-Text-Direction") ?? "ltr"` globally without per-route logic
- **Given:** `LocaleMeta` dataclass carries an `is_rtl: bool` field; RTL languages are `ar`, `ar_SA`, `ar_EG`, `he`, `he_IL`, `fa`, `fa_IR`, `ur`, `ur_PK`
- **When:** `LocaleMiddleware` calls `send()` on the response
- **Then:**
  - RTL locales receive `X-Text-Direction: rtl` in the response headers (INV-I18N-006, CC-016)
  - `Content-Language: ar-SA` (hyphenated BCP-47) is always co-sent alongside for browser-level direction hints
  - LTR locales `en_US`, `pt_BR`, `fr_FR` receive no `X-Text-Direction` header
  - T-22 is parameterized over all 9 RTL locale codes and 3 LTR codes; asserts header presence or absence for each

**US-20: `/api/v1/locales` serves a machine-readable locale menu**
- **As a** frontend developer building a language-switcher dropdown
- **I want** `GET /api/v1/locales` to return a JSON array with `code`, `display_name` (English), `native_name`, and `is_rtl` for every supported locale
- **So that** the dropdown can be built dynamically from the API response without hardcoding locale metadata in the frontend bundle
- **Given:** the server is configured with `supported_locales = ["en_US", "pt_BR", "ar", "ja_JP", "de_DE"]`
- **When:** `GET /api/v1/locales` is called with no authentication
- **Then:**
  - Response is a JSON array; Arabic entry is `{"code":"ar","display_name":"Arabic","native_name":"العربية","is_rtl":true}` (CC-024, CC-027)
  - `display_name` and `native_name` are sourced from Babel at startup and do not change at runtime
  - Pydantic model validates every entry in the array; no locale entry has `null` display_name
  - T-24 hits the endpoint and validates schema against all five configured locales; checks `ar.is_rtl == True`

### 9.5 Catalog Workflow & Edge Cases

**US-21: Missing translation returns msgid silently, never a 500**
- **As a** DevOps engineer deploying a hotfix that adds a new user-facing string before the translator has touched the `.po` file
- **I want** the missing translation to return the English msgid transparently rather than raising an exception
- **So that** a translation gap is a cosmetic gap in localization coverage, not a production outage
- **Given:** `locales/de_DE/LC_MESSAGES/messages.po` has no entry for `msgid "Account suspended"`; `de_DE.mo` is compiled but lacks that key
- **When:** a request with `Accept-Language: de` calls `_("Account suspended")`
- **Then:**
  - `GNUTranslations.gettext()` returns the msgid `"Account suspended"` — no exception, no empty string (INV-I18N-002, CC-030)
  - In `DEBUG=True` mode a `WARNING`-level log entry is emitted with the missing msgid and locale, enabling developers to catch gaps locally without production noise
  - T-25 verifies the silent fallback for both a completely absent msgid and a present msgid with empty `msgstr`

**US-22: Audit CLI produces a per-locale coverage table and gates CI**
- **As a** project lead enforcing translation completeness before a public release
- **I want** `python scripts/audit_translations.py --threshold 0` to print a table showing untranslated and fuzzy counts per locale, and to exit with code 1 if any locale exceeds the threshold
- **So that** the CI pipeline blocks the release pipeline when translations are incomplete
- **Given:** `locales/de_DE/LC_MESSAGES/messages.po` has 5 empty `msgstr` entries out of 200 total; threshold is 0
- **When:** the audit script reads all `.po` files under `locales/` using `polib`
- **Then:**
  - A table is printed with columns `locale`, `total`, `translated`, `fuzzy`, `untranslated`, `%` (CC-018, CC-019)
  - Script exits with code 1; `subprocess.run(...).returncode == 1` in T-26
  - `--fail-on-fuzzy` flag additionally fails on any `#, fuzzy` entries — useful for release branches requiring 100% clean catalogs
  - T-26 seeds a `.po` with one empty `msgstr` and one fuzzy entry and validates both exit-code paths

**US-23: Tool re-run is idempotent and preserves manual edits**
- **As a** developer who added three new supported locales after the initial `add_i18n()` scaffolding
- **I want** to run `add_i18n(project_dir=".", supported_locales=["en_US","pt_BR","es_MX"])` again without losing any existing translated strings, creating duplicate middleware registrations, or overwriting my manually edited `babel.cfg`
- **So that** I can safely evolve the locale configuration as the product grows without a destructive re-scaffold
- **Given:** `LocaleMiddleware` is already registered in `main.py`; `locales/pt_BR/` has 300 translated entries; `babel.cfg` has been manually extended with a custom Jinja2 path
- **When:** `add_i18n()` is called a second time
- **Then:**
  - Existing `LocaleMiddleware` registration in `main.py` is detected and skipped — no duplicate (INV-I18N-004, CC-030, T-28)
  - `pybabel update` runs instead of `pybabel init` for `pt_BR`; all 300 translated msgstr values are preserved
  - `babel.cfg` is backed up to `babel.cfg.bak` before regeneration if it differs from the generated template
  - T-28 runs the tool twice on a test project fixture, diffs all output files, and asserts file hashes are identical on the second run

**US-24: Circular fallback chain is rejected at startup, not at request time**
- **As a** developer who accidentally wrote `fallback_chain = {"a": ["b"], "b": ["a"]}` in `configs/fallback_chains.yaml`
- **I want** `FallbackChainResolver` to raise `FallbackLoopError` during the `@app.on_event("startup")` hook
- **So that** the server refuses to start with a circular fallback configuration rather than hanging on the first request that triggers the loop
- **Given:** `fallback_chain` contains a cycle; the resolver is constructed inside `preload_catalogs()` called at startup
- **When:** `FallbackChainResolver(fallback_chain)` is instantiated
- **Then:**
  - A topological sort of the fallback graph detects the cycle and raises `FallbackLoopError` with the cycle path in the message (INV-I18N-001, CC-025)
  - The server process exits non-zero immediately; no request ever reaches a route handler
  - T-27 constructs a resolver with a two-node cycle and asserts `FallbackLoopError` is raised before any `.resolve()` call

**US-25: URL path-prefix resolution enables SEO-friendly locale URLs**
- **As an** SEO engineer who wants `/es/products` and `/en/products` to be indexable as distinct language variants by search engines
- **I want** the first URL path segment to be consumed as a locale alias, mapping `"es"` → `"es_MX"` via a configured alias map, before any other locale source is evaluated
- **So that** users can share locale-specific URLs and search engines can crawl them as discrete pages with `hreflang` annotations
- **Given:** `PATH_LOCALE_PREFIX=true` in config; `locale_path_aliases = {"en":"en_US","es":"es_MX","pt":"pt_BR"}`; a `PathLocaleMiddleware` is injected before `LocaleMiddleware`
- **When:** `GET /es/products` is received
- **Then:**
  - `PathLocaleMiddleware` extracts `"es"`, resolves it to `"es_MX"` via the alias map, strips the prefix from the path before routing, and sets the locale ContextVar (CC-001, INV-I18N-001)
  - `Content-Language: es-MX` is returned; response body is in Spanish
  - The feature is gated on `PATH_LOCALE_PREFIX=true`; when false, the middleware is not registered and existing URL structures are unchanged
  - T-30 sends `GET /es/products` with `PATH_LOCALE_PREFIX=true` and asserts `Content-Language: es-MX` and Spanish translation in the body
## 10. Test Plan

### 10.1 Middleware Tests (T-01..T-05)

**T-01 — Query parameter overrides Accept-Language**
Type: Unit. Input: `GET /items?lang=de_DE` with header `Accept-Language: en_US`. Expected: `get_current_locale()` returns `de_DE` inside the route handler. Assertion: ContextVar set to `de_DE`; response `Content-Language: de-DE`.

**T-02 — X-Locale header overrides Accept-Language**
Type: Unit. Input: request with `X-Locale: fr_FR` header and `Accept-Language: en_US`. Expected: resolved locale is `fr_FR`. Assertion: middleware sets ContextVar before calling `call_next`.

**T-03 — Session locale preference overrides Accept-Language**
Type: Unit/Integration. Input: session cookie with `locale=ja_JP`; `Accept-Language: en_US`. Expected: locale resolved to `ja_JP`. Assertion: `request.session["locale"]` is read in priority step 3.

**T-04 — Accept-Language quality-value negotiation**
Type: Unit. Parametrized inputs: 8 different `Accept-Language` values including multi-locale with q-values, wildcard `*`, malformed headers, and `es-MX,es;q=0.9`. Expected: correct BCP-47 locale returned for each. Assertion: `_parse_accept_language` and `_negotiate` behave per RFC 5646.

**T-05 — Fallback chain traversal**
Type: Unit. Setup: `fallback_chain = {"pt_PT": ["pt_BR", "en_US"]}`. Input: request with `X-Locale: pt_PT`; `pt_PT` not in `SUPPORTED_LOCALES`. Expected: middleware resolves `pt_BR` via fallback. Assertion: `get_current_locale()` == `pt_BR`.

### 10.2 Catalog and Translation Tests (T-06..T-12)

**T-06 — Default locale fallback when all signals fail**
Type: Integration. Input: no `?lang=`, no `X-Locale`, no session, `Accept-Language: xx-XX` (unsupported). Expected: locale resolves to `DEFAULT_LOCALE`. Assertion: `Content-Language` header matches `DEFAULT_LOCALE`.

**T-07 — gettext lookup from compiled `.mo`**
Type: Unit. Setup: compile a real test `.mo` with `msgid "Hello"` / `msgstr "Olá"` for `pt_BR`. Input: set `current_locale = "pt_BR"`; call `_("Hello")`. Expected: returns `"Olá"`. Assertion: exact string match, no exception.

**T-08 — Full-stack localized error response**
Type: Integration. Setup: route raises `HTTPException(detail=_("Resource not found"))`. Input: `GET /items/9999` with `Accept-Language: fr-FR`. Expected: JSON `{"detail": "Ressource introuvable"}`. Assertion: response body and `Content-Language` header.

**T-09 — `pybabel update` idempotency**
Type: Integration/CLI. Setup: existing `.po` with translated entries; add a new string to source. Run `pybabel update`. Expected: new string appears as untranslated; existing translations unchanged. Assertion: diff shows only additive changes.

**T-10 — `pybabel compile` generates `.mo`**
Type: CLI. Setup: valid `.po` file. Run `make i18n-compile`. Expected: `.mo` file created; `pybabel compile` exits 0. Assertion: `Path("locales/pt_BR/LC_MESSAGES/messages.mo").exists()`.

**T-11 — Catalog preload at startup fails on missing `.mo`**
Type: Unit. Setup: `supported_locales = ["pt_BR"]`; no `.mo` file present. Expected: `preload_catalogs()` raises `FileNotFoundError`. Assertion: exception message contains locale code and path.

**T-12 — New locale scaffold via `make i18n-new-locale`**
Type: CLI. Input: `make i18n-new-locale LOCALE=es_MX`. Expected: `locales/es_MX/LC_MESSAGES/messages.po` created with all msgids and empty msgstr. Assertion: file exists; `polib` audit shows 0% translated.

### 10.3 Pluralization Tests (T-13..T-18)

**T-13 — English two-form plural with zero handling**
Type: Unit. Inputs: n=0,1,2,5,11,21. Expected: `ngettext("item","items",1)` → "item"; all others → "items". Assertion: parametrized over 6 values.

**T-14 — Polish irregular plural rules**
Type: Unit. Inputs: n=1,2,5,11,21,22 with locale `pl`. Expected CLDR categories: one, few, many, many, few, few. Assertion: `get_plural_form("pl", n)` matches expected category for each n.

**T-15 — Arabic 6-form plural coverage**
Type: Unit. Inputs: n=0,1,2,3,11,100 with locale `ar`. Expected CLDR categories: zero, one, two, few, many, other. Assertion: all 6 categories validated in a single parametrized test.

**T-16 — PyICU vs Babel fallback consistency**
Type: Unit. Conditional on PyICU availability (`pytest.importorskip("icu")`). Input: same locale/n pairs run through both PyICU path and Babel path. Expected: identical CLDR category for all tested languages. Assertion: `get_plural_form` agrees across both implementations.

**T-17 — `format_plural` with explicit zero key**
Type: Unit. Input: `format_plural("en_US", 0, {"zero":"No items","one":"1 item","other":"{n} items"})`. Expected: "No items". Assertion: "zero" key is used before CLDR category lookup.

**T-18 — Russian 4-form plural**
Type: Unit. Inputs: n=1,2,5,11,21 with locale `ru`. Expected: one, few, many, many, one. Assertion: matches CLDR ru plural rules exactly.

### 10.4 Formatting Tests (T-19..T-24)

**T-19 — Date formatting per locale**
Type: Unit. Parametrized: `(date(2026,4,12), "en_US", "medium") → "Apr 12, 2026"`, `(same, "fr_FR", "medium") → "12 avr. 2026"`, `(same, "de_DE", "medium") → "12.04.2026"`. Assertion: Babel `format_date` output matches expected string.

**T-20 — Number grouping separators**
Type: Unit. Inputs: `1234567.89` with locales `en_US`, `de_DE`, `fr_FR`, `pt_BR`. Expected: `en_US` → `1,234,567.89`; `de_DE` → `1.234.567,89`. Assertion: `fmt_number()` delegates to Babel correctly.

**T-21 — Currency symbol position and formatting**
Type: Unit. Inputs: `(1234.56, "USD", "en_US")`, `(1234.56, "EUR", "de_DE")`, `(1234.56, "BRL", "pt_BR")`. Assertion: correct symbol position and decimal/group separators per Babel CLDR data.

**T-22 — RTL header for all RTL locales**
Type: Unit/Integration. Parametrized locales: `ar`, `ar_SA`, `ar_EG`, `he`, `he_IL`, `fa`, `fa_IR`, `ur`, `ur_PK`. Expected: `X-Text-Direction: rtl` in response headers. LTR locales `en_US`, `pt_BR`, `fr_FR` expected: no such header. Assertion: 17 parametrized cases pass.

**T-23 — `Content-Language` header always set**
Type: Integration. Every response (regardless of locale resolution path) must contain `Content-Language` header with hyphenated BCP-47 code. Assertion: `response.headers["Content-Language"]` matches `resolved_locale.replace("_","-")`.

**T-24 — `/api/v1/locales` endpoint schema**
Type: Integration. Expected: response is a JSON array where each element has keys `code` (string), `display_name` (string), `native_name` (string), `is_rtl` (bool). Assertion: Pydantic model validates all entries; Arabic entry has `is_rtl=true`.

### 10.5 Edge Case Tests (T-25..T-27)

**T-25 — Missing translation returns msgid, no exception**
Type: Unit. Setup: catalog for `de_DE` does NOT contain `msgid "Newly added string"`. Expected: `_("Newly added string")` returns `"Newly added string"` without raising. Assertion: no exception; return value == input msgid.

**T-26 — Audit CLI exits 1 on untranslated strings**
Type: CLI. Setup: seed `locales/de_DE/LC_MESSAGES/messages.po` with one empty `msgstr`. Run `python scripts/audit_translations.py --threshold 0`. Expected: exit code 1; per-locale table shows `de_DE` with 1 untranslated. Assertion: `subprocess.run(...).returncode == 1`.

**T-27 — Fallback loop detection raises at startup**
Type: Unit. Setup: `fallback_chain = {"a": ["b"], "b": ["a"]}`. Expected: `FallbackChainResolver(...)` raises `FallbackLoopError`. Assertion: exception raised before any `.resolve()` call.

### 10.6 Idempotency and Integration Tests (T-28..T-30)

**T-28 — Tool re-run idempotency**
Type: Integration. Run `add_i18n()` twice on a test project with pre-translated `.po` files. Expected: `diff` of output shows no changes; translated `msgstr` values are preserved; `LocaleMiddleware` appears exactly once in `main.py`. Assertion: file hash of `.po` files identical before and after second run.

**T-29 — Malformed `.po` fails compile**
Type: CLI. Setup: `.po` file with `msgid "Hello %s"` and `msgstr "Hallo"` (missing `%s`). Run `pybabel compile`. Expected: exits with code 1 and error message referencing the offending file. Assertion: `.mo` file is NOT created; `make i18n-compile` propagates the non-zero exit.

**T-30 — URL path-prefix locale resolution**
Type: Integration. Setup: `PATH_LOCALE_PREFIX=true`; alias `{"en":"en_US","es":"es_MX"}`. Input: `GET /es/products`. Expected: locale resolved to `es_MX`. Assertion: `Content-Language: es-MX`; body translated to Spanish.

---

## 11. Interaction Matrix

| This Tool | Interacts With | Nature | Details |
|-----------|---------------|--------|---------|
| `add_i18n` | **TOOL-005** `audit_log` | Uses | Locale resolution events (locale detected, fallback triggered) are audit-logged with `action="locale_resolved"`, `actor=request_ip` for compliance traceability |
| `add_i18n` | **TOOL-008** `add_multi_tenancy` | Coordinates | Per-tenant locale preference: if multi-tenancy is active, the tenant's default locale overrides the system default; `TenantMiddleware` runs before `LocaleMiddleware` to set `current_tenant_id` first |
| `add_i18n` | **TOOL-033** `api_spec_compliance` | Validates | OpenAPI spec must document `Content-Language` response header and `?lang` query parameter; TOOL-033 adds these to the spec schema and validates them in contract tests |
| `add_i18n` | **TOOL-049** `generate_docs` | Generates | Translation workflow guide (`docs/i18n.md`) is generated by TOOL-049 using the locale manifest produced by `add_i18n`; locale table and workflow diagram are auto-generated |
| `add_i18n` | **TOOL-001** `scaffold_project` | Depends on | Requires an existing FastAPI project created by TOOL-001; `main.py` and `core/config.py` must exist before `add_i18n` modifies them |
| `add_i18n` | **TOOL-003** `add_auth` | Coordinates | User locale preference storage: if auth is present, `PUT /api/v1/me/locale` stores preference in the User model or `user_preferences` table created by TOOL-003 |
| `add_i18n` | **TOOL-010** `add_caching` | Compatible | Translation catalogs are loaded at startup (in-memory); no conflict with Redis caching layer. Per-request locale resolution is ContextVar-based, not cache-dependent |
| `add_i18n` | **TOOL-015** `add_monitoring` | Integrates | Missing-translation WARNING logs feed Grafana/Prometheus via `i18n_missing_translation_total{locale,msgid}` counter; locale distribution metric `i18n_request_locale_total{locale}` is emitted by middleware |
| `add_i18n` | **TOOL-020** `add_testing` | Extends | `tests/i18n/` directory created by this tool follows the test layout conventions from TOOL-020; pytest fixtures `set_locale` and `with_locale` are registered in `conftest.py` |
| `add_i18n` | **TOOL-025** `add_rate_limiting` | Compatible | Locale resolution happens before rate limiting middleware; no conflict. Rate limit headers (`X-RateLimit-*`) are returned alongside `Content-Language` without interference |
| `add_i18n` | **TOOL-030** `add_feature_flags` | Coordinates | New locale rollout can be gated behind a feature flag: `if feature_enabled("locale_es_MX", user_id): supported_locales.append("es_MX")` pattern is documented in generated code |
| `add_i18n` | **TOOL-040** `add_background_tasks` | Coordinates | Background workers lack a request context; `set_current_locale(default_locale)` must be called explicitly at worker startup to ensure `_()` calls in task bodies resolve correctly |
| `add_i18n` | **TOOL-046** `add_event_driven` | Coordinates | Events containing user-facing strings must use the recipient's locale, not the producer's; event schema should include an optional `recipient_locale` field for async notification payloads |
| `add_i18n` | **CI/CD pipeline** | Integrates | GitHub Actions `i18n.yml` workflow integrates with existing `ci.yml`; runs extract/compile/audit as a required check before merge |
| `add_i18n` | **Poedit / Weblate** | Supports | Generated `.po` file structure is fully compatible with Poedit (desktop) and Weblate (web-based) translation management platforms |

---

## 12. Rollback Procedure

### 12.1 Pre-Rollback Checklist

Before rolling back, confirm:
- [ ] The issue is definitively caused by the i18n layer (not auth, routing, or database)
- [ ] `make i18n-compile` was run before the last deploy (missing `.mo` is a common false positive)
- [ ] The fallback chain is not the cause (test with `?lang=en_US` explicitly)
- [ ] Rollback target version is identified (git SHA or image tag)
- [ ] On-call translator has been notified that locale files may revert

### 12.2 Code Rollback

```bash
# Step 1: Identify the commit that introduced add_i18n
git log --oneline --all | grep -i "i18n\|locale\|translation" | head -10

# Step 2: Revert main.py middleware registration (safe single-file revert)
git checkout <PRE_I18N_SHA> -- app/main.py
git checkout <PRE_I18N_SHA> -- app/core/config.py

# Step 3: Verify middleware is no longer registered
grep "LocaleMiddleware" app/main.py  # should return empty

# Step 4: Restart the service (locale resolution gone; all strings serve default language)
systemctl restart api  # or docker-compose restart api

# Step 5: Verify 200 responses with no Content-Language header
curl -I https://api.example.com/health | grep -i "content-language"
# Expected: no Content-Language header in response
```

### 12.3 Database Rollback

> **N/A — Code-only tool (no schema migration required by default)**
>
> `fastapi_add_i18n` does not create or modify any database tables by default.
> All locale infrastructure is code-only: ContextVars, `.mo` files, and middleware.
>
> **Exception**: If `PUT /api/v1/me/locale` was implemented and stores locale in a
> `user_preferences.locale` column (via TOOL-003 integration), roll back as follows:
>
> ```bash
> # Only execute if user_preferences.locale column was added
> alembic downgrade <PRE_I18N_MIGRATION_ID>
> # Verify column is gone
> psql $DATABASE_URL -c "\d user_preferences"
> ```

### 12.4 Failure Mode: Missing Translation in Production

**Symptom**: All responses return English regardless of `Accept-Language` header.
**Root cause**: `.mo` files were not compiled before deploy; OR `SUPPORTED_LOCALES` env var was not updated.
**Immediate fix**:
```bash
# On the running container/server:
make i18n-compile
systemctl restart api
# Verify:
curl -H "Accept-Language: pt-BR" https://api.example.com/items/1
# Response should now include Content-Language: pt-BR
```
**Prevention**: Block deploys when `make i18n-compile` exits non-zero (CI gate).

### 12.5 Failure Mode: `.mo` Compile Step Fails

**Symptom**: `pybabel compile` exits non-zero; server refuses to start.
**Root cause**: A `.po` file has mismatched format specifiers (e.g. `%s` in msgid but not msgstr).
**Immediate fix**:
```bash
# Identify the offending file
pybabel compile --statistics --directory locales 2>&1 | grep "error"
# Example output: locales/de_DE/LC_MESSAGES/messages.po:142: error: msgstr is not a valid ...

# Option A: fix the msgstr in the .po file
poedit locales/de_DE/LC_MESSAGES/messages.po

# Option B: emergency — mark the entry as untranslated (remove msgstr)
# The fallback chain will serve English until the translator fixes it
sed -i '/^msgid "Problem string"/,/^$/s/^msgstr ".*"/msgstr ""/' \
    locales/de_DE/LC_MESSAGES/messages.po
make i18n-compile
systemctl restart api
```

### 12.6 Failure Mode: Locale Middleware Breaking Auth Flow

**Symptom**: `/api/v1/auth/login` returns 500 or 400 after i18n deployment; error is `MissingTranslationCatalog` or ContextVar-related.
**Root cause**: `LocaleMiddleware` runs before auth middleware and either raises on catalog load or inadvertently modifies request state expected by auth.
**Immediate fix**:
```bash
# Emergency: disable LocaleMiddleware via env var (requires code guard)
# In app/main.py, wrap middleware registration:
#   if not os.getenv("I18N_DISABLED"):
#       app.add_middleware(LocaleMiddleware)

I18N_DISABLED=true systemctl restart api
# Verify auth endpoint works:
curl -X POST https://api.example.com/api/v1/auth/login -d '{"email":"...","password":"..."}'
```
**Fix root cause**: Ensure `LocaleMiddleware.dispatch()` never raises; wrap `call_next` in try/except; ensure auth paths are not blocked by locale resolution.

### 12.7 Failure Mode: RTL Layout Broken After Locale Switch

**Symptom**: Arabic UI renders with left-to-right layout; `X-Text-Direction` header missing.
**Root cause**: `LOCALE_META` dict not populated at startup (e.g. `build_locale_registry` not called); OR frontend consuming the header incorrectly.
**Immediate fix**:
```bash
# Verify header is set by the API:
curl -I -H "X-Locale: ar" https://api.example.com/items | grep -i "x-text-direction"
# Expected: X-Text-Direction: rtl

# If header IS present but UI is still LTR, the issue is frontend-side.
# Check that the React/Vue app reads X-Text-Direction and sets document.dir = "rtl"

# If header is MISSING, restart with debug to see LOCALE_META population:
LOG_LEVEL=DEBUG systemctl restart api
# Check startup logs for "LOCALE_META populated with N locales"
```

### 12.8 Emergency Procedures

```bash
# OPTION 1: Disable i18n entirely via environment variable
I18N_DISABLED=true systemctl restart api
# Effect: LocaleMiddleware skips all logic; all responses in DEFAULT_LOCALE

# OPTION 2: Revert locale middleware only (preserves other i18n code)
git checkout <BEFORE_SHA> -- app/api/middleware/locale.py
# Rebuild and deploy

# OPTION 3: Force single locale (disable multilingual, serve one language)
I18N_SUPPORTED_LOCALES=en_US systemctl restart api
# Effect: every request resolves to en_US regardless of headers/session

# OPTION 4: Full i18n rollback — revert all generated files
git revert <I18N_COMMIT_SHA> --no-commit
git commit -m "revert: remove i18n infrastructure [emergency rollback]"
```

---

## 13. Edge Cases

| # | Edge Case | Expected Behavior |
|---|-----------|-------------------|
| EC-01 | `Accept-Language: es-MX,es;q=0.9,en;q=0.8` header received | Matches `es_MX` exactly via region variant; no fallback chain traversal needed; q-value parsing returns correct ordered list |
| EC-02 | Locale code `xx_YY` not in `SUPPORTED_LOCALES` passed via `?lang=xx_YY` | Silently ignored; next resolution source tried in priority order; `DEFAULT_LOCALE` returned if all sources fail without raising |
| EC-03 | Fallback chain loop `a → b → a` configured in `fallback_chains.yaml` | `FallbackLoopError` raised during `FallbackChainResolver.__init__` at server startup; server refuses to serve any requests |
| EC-04 | `msgid "New string"` missing from ALL fallback chain `.mo` files | `_()` returns raw msgid string `"New string"`; `WARNING` log emitted in `DEBUG=true` mode; absolutely no exception raised |
| EC-05 | Arabic plural form for count=11 which is form "many" not "few" | `get_plural_form("ar", 11)` → `"many"` per CLDR; `format_plural` selects the `"many"` template key from the forms dict |
| EC-06 | RTL locale `ar_DZ` (Algerian Arabic variant) | `LocaleMeta.is_rtl=True` because `"ar_DZ".split("_")[0] == "ar"` is in `_RTL_LANGUAGES` frozenset |
| EC-07 | Number `1000.0` formatted with `fr_FR` locale | `fmt_number(1000.0)` → `"1\u202f000"` using narrow no-break space as French thousands separator per CLDR standard |
| EC-08 | Date `date(2026, 4, 12)` formatted with `ja_JP` locale | `fmt_date` returns `"2026/04/12"` using YYYY/MM/DD format per Japanese locale convention in Babel CLDR |
| EC-09 | `.po` file manually edited, then `pybabel extract` + `pybabel update` run again | Existing translated `msgstr` values preserved; new msgids added as empty strings; strings with minor source changes flagged `#, fuzzy` but NOT deleted |
| EC-10 | `add_i18n()` called twice on same project with existing translations | Second run detects `LocaleMiddleware` already in `main.py` and skips; runs `pybabel update` (not `pybabel init`) for each existing locale; file hash of `.po` unchanged |
| EC-11 | Locale from URL path prefix `/fr/products` with `PATH_LOCALE_PREFIX=true` | Path-prefix resolver extracts `fr`, maps to `fr_FR` via alias dict; Starlette route receives `/products` without the locale segment |
| EC-12 | Session contains `ja_JP` but `ja_JP` was removed from `SUPPORTED_LOCALES` config | Middleware skips session locale because it is absent from `_supported` set; falls through to Accept-Language negotiation without error |
| EC-13 | `I18N_SUPPORTED_LOCALES` env var set to empty string at startup | `preload_catalogs()` loads only `DEFAULT_LOCALE` catalog; all requests resolve to default locale; no crash or empty-list iteration error |
| EC-14 | `.po` file has `msgstr "Hallo"` for `msgid "Hello %s"` — format specifier mismatch | `pybabel compile` detects Python-format mismatch and exits non-zero; `.mo` not written; `preload_catalogs()` raises `FileNotFoundError` blocking startup |
| EC-15 | Background ARQ worker calls `_("Processing complete")` without any request context | `get_current_locale()` returns `DEFAULT_LOCALE` (ContextVar default value); worker MUST call `set_current_locale(user_locale)` explicitly for per-user async notifications |

---

## 14. Acceptance Criteria

✅ **AC-01** — `LocaleMiddleware` is registered in `main.py` and resolves locale from all 4 sources (query param → header → session → Accept-Language) in documented priority order.

✅ **AC-02** — `_("msgid")` returns the translated string for the current request locale and silently falls back to msgid when translation is missing, never raising an exception.

✅ **AC-03** — `ngettext("singular","plural",n)` and `format_plural(locale, n, forms)` return grammatically correct plurals for English (2-form), Polish (3-form), Russian (4-form), and Arabic (6-form).

✅ **AC-04** — `X-Text-Direction: rtl` response header is injected for all Arabic, Hebrew, Farsi, and Urdu locale requests; no header for LTR locales.

✅ **AC-05** — `fmt_number()`, `fmt_currency()`, and `fmt_date()` delegate to Babel CLDR and return locale-correct formatting for all tested locales including `de_DE`, `fr_FR`, `pt_BR`, `ar_SA`, `ja_JP`.

✅ **AC-06** — `FallbackChainResolver` raises `FallbackLoopError` at startup for cyclic chains; valid chains resolve correctly with `resolve()` yielding candidates in priority order.

✅ **AC-07** — `pybabel update` is idempotent: existing translated `msgstr` values survive re-extraction; new strings are added as untranslated; fuzzy entries are flagged.

✅ **AC-08** — `python scripts/audit_translations.py --threshold 0` exits with code 1 when any locale has untranslated strings and code 0 when all locales are fully translated.

✅ **AC-09** — GitHub Actions `i18n.yml` workflow runs and passes `make i18n-extract && make i18n-compile && make i18n-audit` on every push; deploy is blocked if compile or audit exits non-zero.

✅ **AC-10** — Tool is idempotent: running `add_i18n()` twice on the same project produces no changes to translated `.po` files, no duplicate middleware in `main.py`, and no reset of `babel.cfg`.

---

## 15. Implementation Checklist

### 15.1 Project Analysis

- [ ] Scan `app/` for existing user-facing string literals using regex `r'"[A-Z][^"]{4,}"'`
- [ ] Identify all `raise HTTPException` callsites that contain hardcoded strings
- [ ] Check if `main.py` already has any middleware with locale-handling logic to avoid duplication
- [ ] Confirm `pyproject.toml` does not already declare `babel` as a dependency
- [ ] Detect existing `babel.cfg` at project root; if found, back up before regenerating
- [ ] Detect if Jinja2 templates exist in `app/templates/`; if yes, add Jinja2 section to `babel.cfg`
- [ ] Check for existing `locales/` directory; if found, run `pybabel update` not `pybabel init`

### 15.2 Dependency Installation

- [ ] Add `babel>=2.14` to `pyproject.toml` `[project.dependencies]`
- [ ] Add `polib>=1.2` to `pyproject.toml` `[project.optional-dependencies.i18n]`
- [ ] Add `PyICU>=2.11` to `pyproject.toml` `[project.optional-dependencies.i18n-icu]` (optional)
- [ ] Add `click>=8.1` to `pyproject.toml` (for audit CLI, if not already present)
- [ ] Run `uv pip install babel polib` to verify installation
- [ ] Verify `gettext` system binary available: `which msgfmt && which msginit`
- [ ] Add `babel.cfg` to `.gitignore` exceptions (must be tracked, not ignored)

### 15.3 Core Locale Infrastructure

- [ ] Create `app/core/locale_context.py` with `ContextVar`, `set_current_locale`, `get_current_locale`, `_()`, `preload_catalogs`, `_get_translation`, `_catalog_cache`, `_fallback_registry`
- [ ] Create `app/core/babel_translator.py` with `LazyString`, `lazy_gettext`, `ngettext`, module-level lazy constants
- [ ] Create `app/core/locale_meta.py` with `LocaleMeta` dataclass, `_RTL_LANGUAGES` frozenset, `build_locale_registry`, `LOCALE_META` dict
- [ ] Create `app/core/locale_formatters.py` with `fmt_number`, `fmt_currency`, `fmt_date`, `fmt_datetime`
- [ ] Create `app/core/icu_plurals.py` with `get_plural_form`, `format_plural`, `pluralize`; PyICU optional import with Babel fallback
- [ ] Create `app/core/fallback_chain.py` with `FallbackChainResolver`, `FallbackLoopError`, `from_yaml` classmethod
- [ ] Add `DEFAULT_LOCALE: str` and `SUPPORTED_LOCALES: list[str]` to `app/core/config.py` with env var bindings

### 15.4 Middleware

- [ ] Create `app/api/middleware/locale.py` with `LocaleMiddleware`, `_parse_accept_language`, `_negotiate`
- [ ] Register `LocaleMiddleware` in `main.py` with correct ordering (after CORS, before auth)
- [ ] Verify `LocaleMiddleware` is registered exactly once (idempotency check on re-run)
- [ ] Add `TENANT_FREE_PATHS` equivalent: `LOCALE_FREE_PATHS` set for health check, metrics endpoints
- [ ] Wire `LOCALE_META` population to `@app.on_event("startup")` handler in `main.py`
- [ ] Wire `preload_catalogs()` call to startup handler with correct `locales_dir` and `supported_locales`
- [ ] Wire `FallbackChainResolver.from_yaml()` to startup handler using `configs/fallback_chains.yaml`

### 15.5 Babel Catalog Workflow

- [ ] Generate `babel.cfg` at project root with `[python: app/**.py]` section
- [ ] Add `[jinja2: app/templates/**.html]` section if Jinja2 templates detected
- [ ] Run `pybabel extract -F babel.cfg -o locales/messages.pot app/` when `extract_from_source=True`
- [ ] For each locale in `supported_locales`: run `pybabel init -i locales/messages.pot -d locales -l {locale}` if not exists, else `pybabel update`
- [ ] Verify each `.po` file has correct `Plural-Forms` header from CLDR via Babel
- [ ] Verify `Content-Type: text/plain; charset=UTF-8` header in each `.po`
- [ ] Compile all `.po` to `.mo`: `pybabel compile -d locales --statistics`

### 15.6 Makefile Targets

- [ ] Add `i18n-extract` target: `pybabel extract -F babel.cfg -o locales/messages.pot app/`
- [ ] Add `i18n-update` target: iterate all supported locales and run `pybabel update`
- [ ] Add `i18n-compile` target: `pybabel compile -d locales --statistics` with exit-code propagation
- [ ] Add `i18n-audit` target: `python scripts/audit_translations.py --threshold 0`
- [ ] Add `i18n-clean` target: `find locales -name "*.mo" -delete`
- [ ] Add `i18n-new-locale` target: `pybabel init -i locales/messages.pot -d locales -l $(LOCALE)`
- [ ] Document all targets in Makefile comments with usage examples

### 15.7 CLI Tools

- [ ] Create `scripts/audit_translations.py` with `click` CLI, `--locales-dir`, `--threshold`, `--fail-on-fuzzy`
- [ ] Implement `audit_locale()` using `polib` to count translated/fuzzy/untranslated entries
- [ ] Print formatted table with per-locale statistics and `← FAIL` markers
- [ ] Exit 0 when all locales pass; exit 1 when any locale exceeds threshold
- [ ] Add `--output=json` flag for machine-readable output (CI integration)
- [ ] Add `--locale` flag to audit a single locale for fast developer feedback
- [ ] Test CLI with both passing and failing scenarios

### 15.8 API Endpoints

- [ ] Create `GET /api/v1/locales` endpoint returning all `LocaleMeta` objects as JSON array
- [ ] Create `PUT /api/v1/me/locale` endpoint requiring authentication and storing locale in session
- [ ] Validate locale against `SUPPORTED_LOCALES` in the `PUT` handler; return 422 for unknown locales
- [ ] Add `X-Locale` header to OpenAPI schema (parameter documentation)
- [ ] Add `Content-Language` response header to OpenAPI schema (response documentation)
- [ ] Add `lang` query parameter to OpenAPI schema for affected endpoints

### 15.9 Configuration Files

- [ ] Create `configs/fallback_chains.yaml` with `pt_PT → pt_BR → en_US` and `es_419 → es_MX → en_US` examples
- [ ] Create `locales/` directory structure for all `supported_locales`
- [ ] Add `*.mo` to `.gitignore` (binary files should not be tracked)
- [ ] Ensure `*.po` files are NOT in `.gitignore` (must be tracked for translators)
- [ ] Add `I18N_DEFAULT_LOCALE` and `I18N_SUPPORTED_LOCALES` to `.env.example`
- [ ] Add `I18N_DISABLED` emergency flag to `.env.example` with documentation
- [ ] Update `README.md` with link to `docs/i18n.md` translation workflow guide

### 15.10 GitHub Actions CI

- [ ] Create `.github/workflows/i18n.yml` triggered on push to `main` and all PRs
- [ ] Add step: `make i18n-extract` (ensure `.pot` is up to date)
- [ ] Add step: `make i18n-compile` (compile `.po` → `.mo`; fail on error)
- [ ] Add step: `make i18n-audit` (verify completeness; fail on untranslated strings)
- [ ] Add step: verify `git diff --name-only locales/` is empty (no uncommitted catalog changes)
- [ ] Cache `locales/` directory in CI to avoid recompiling unchanged catalogs
- [ ] Notify Slack/webhook when a locale falls below 80% translated

### 15.11 Test Infrastructure

- [ ] Create `tests/i18n/` directory
- [ ] Create `tests/i18n/conftest.py` with `set_locale`, `with_locale`, `temp_catalog` fixtures
- [ ] Create `tests/i18n/test_locale_middleware.py` covering T-01 through T-06
- [ ] Create `tests/i18n/test_gettext_helper.py` covering T-07, T-08, T-11
- [ ] Create `tests/i18n/test_plural_rules.py` covering T-13 through T-18
- [ ] Create `tests/i18n/test_formatters.py` covering T-19 through T-24
- [ ] Create `tests/i18n/test_fallback_chain.py` covering T-05, T-09, T-27
- [ ] Create `tests/i18n/test_audit_cli.py` covering T-26 with `subprocess` invocations

### 15.12 Documentation

- [ ] Create `docs/i18n.md` with full translation workflow: extract → edit `.po` → compile → deploy
- [ ] Document `_()` and `ngettext()` usage with 3 code examples
- [ ] Document `fmt_number`, `fmt_currency`, `fmt_date` with locale-specific output examples
- [ ] Document RTL support and how frontend should consume `X-Text-Direction` header
- [ ] Document fallback chain YAML format with all valid configuration patterns
- [ ] Document audit CLI usage and how to integrate with Poedit/Weblate
- [ ] Add architecture diagram: request → LocaleMiddleware → ContextVar → `_()` → `.mo` → response

### 15.13 Idempotency and Safety Guards

- [ ] Before writing `main.py`, check if `LocaleMiddleware` import already present; skip if yes
- [ ] Before running `pybabel init`, check if `.po` file exists; use `pybabel update` if yes
- [ ] Before writing `babel.cfg`, compare with existing; back up if different before overwriting
- [ ] Before writing `configs/fallback_chains.yaml`, check if file exists; merge, do not overwrite
- [ ] Verify tool output: assert that translated `msgstr` in pre-existing `.po` files are unchanged
- [ ] Run `pytest tests/i18n/ -v` as final step of tool execution; report failures to caller
- [ ] Return dict with `{"status": "success"|"partial"|"failed", "files_created": [...], "warnings": [...]}` from `add_i18n()`

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/api/middleware/locale.py",
    "app/core/locale_context.py",
    "app/core/babel_translator.py",
    "app/core/locale_meta.py",
    "app/core/locale_formatters.py",
    "app/core/icu_plurals.py",
    "app/core/fallback_chain.py",
    "babel.cfg",
    "locales/messages.pot",
    "locales/en_US/LC_MESSAGES/messages.po",
    "locales/pt_BR/LC_MESSAGES/messages.po",
    "locales/es_MX/LC_MESSAGES/messages.po",
    "locales/ar/LC_MESSAGES/messages.po",
    "locales/fr_FR/LC_MESSAGES/messages.po",
    "configs/fallback_chains.yaml",
    "scripts/audit_translations.py",
    "tests/i18n/conftest.py",
    "tests/i18n/test_locale_middleware.py",
    "tests/i18n/test_gettext_helper.py",
    "tests/i18n/test_plural_rules.py",
    "tests/i18n/test_formatters.py",
    "tests/i18n/test_fallback_chain.py",
    "tests/i18n/test_audit_cli.py",
    ".github/workflows/i18n.yml",
    "docs/i18n.md"
  ],
  "files_modified": [
    "app/main.py",
    "app/core/config.py",
    "pyproject.toml",
    "Makefile"
  ],
  "next_steps": [
    "Run `make i18n-extract` to populate locales/messages.pot from source strings",
    "Run `make i18n-compile` to compile .po → .mo before starting the server",
    "Open locales/{locale}/LC_MESSAGES/messages.po in Poedit and fill in msgstr values",
    "Run `make i18n-audit` to check translation completeness before release",
    "Set I18N_SUPPORTED_LOCALES env var to the comma-separated list of active locales",
    "Connect PUT /api/v1/me/locale to user preferences if auth (TOOL-003) is active",
    "Configure Weblate or Crowdin to sync with the locales/ directory for team translation workflows"
  ],
  "warnings": [
    "Arabic plural rules require 6 distinct msgstr forms; ensure translators use Poedit 3.x which supports CLDR plural rules natively",
    "PyICU (libicu-dev) must be installed separately on Linux CI runners; Babel fallback is used automatically if PyICU is absent — verify plural accuracy for Arabic before production",
    "Compiled .mo files are NOT tracked in git; CI must run `make i18n-compile` on every deploy or .mo files must be committed explicitly for containerized deployments",
    "Changing DEFAULT_LOCALE after initial deployment may break fallback chains that were configured relative to the original default"
  ],
  "notes": [
    "Tool is fully idempotent: re-running on a project with existing .po files will run pybabel update (not init) and will not overwrite any translated msgstr values",
    "RTL support (X-Text-Direction header) covers ar, he, fa, ur and all regional variants automatically via _RTL_LANGUAGES frozenset",
    "The fallback chain loop detector runs at server startup via FallbackChainResolver.__init__; a misconfigured loop will prevent the server from starting and will surface in logs immediately",
    "fmt_currency delegates entirely to Babel CLDR; cryptocurrency codes (BTC, ETH) that are not in CLDR will display the ISO code as the symbol instead of a regional symbol",
    "The audit CLI exit code 1 is designed for CI integration; the --threshold flag allows gradual adoption (e.g. --threshold 10 during initial rollout, then --threshold 0 for release branches)",
    "LocaleMiddleware injects Content-Language on EVERY response including error responses, ensuring clients can always determine which language the error message is in"
  ],
  "metrics": {
    "locale_resolution_p99_ms": 1,
    "translation_lookup_cached_us": 10,
    "pybabel_extract_1000_strings_s": 5,
    "pybabel_compile_10_locales_s": 2,
    "catalog_preload_10_locales_ms": 500,
    "accept_language_parse_throughput_rps": 50000,
    "audit_cli_10_locales_s": 2,
    "tool_execution_time_s": 4,
    "memory_per_locale_kb": 512,
    "files_created_min": 11,
    "files_modified_max": 4
  }
}
```
