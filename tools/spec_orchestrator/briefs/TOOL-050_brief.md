## Tool: `add_i18n`

### Overview parameters
- Tool name: `fastapi_add_i18n`
- Category: EVOLVE
- Complexity: High
- Dependencies: existing FastAPI project, Babel, gettext, optional ICU MessageFormat
- Signature: `add_i18n(project_dir: str, default_locale: str = "en_US", supported_locales: list[str] | None = None, translation_dir: str = "locales", fallback_chain: list[str] | None = None, extract_from_source: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `default_locale`: canonical locale (source of truth for message IDs)
  - `supported_locales`: list like `["en_US","pt_BR","es_MX","fr_FR"]`
  - `translation_dir`: directory holding `.po`/`.mo` files
  - `fallback_chain`: per-locale fallbacks (e.g., `pt_PT → pt_BR → en_US`)
  - `extract_from_source`: auto-extract translatable strings via Babel `pybabel extract`

### Purpose
Add internationalization (i18n) and localization (l10n) infrastructure to an existing FastAPI app. Generates: a locale detection middleware (reads `Accept-Language`, user preference, or URL segment), a `gettext`/`_()` integration for response messages and error strings, a translation catalog workflow (`pybabel extract` → `.po` → `.mo` → runtime lookup), ICU MessageFormat support for plurals/gender, right-to-left support for `ar`/`he`, and a CLI to audit missing translations. Critical for products going global without rewriting every response string. Handles locale-aware dates, numbers, and currency formatting via Babel.

### Performance SLOs
- Tool execution time < 4s (generation + extraction)
- Files modified ≤ 4 (main.py, config.py, pyproject.toml, routes with user-facing strings)
- Files created ≥ 11 (middleware, loader, extractor config, per-locale .po files, helpers, tests, CI workflow, docs, Makefile, CLI, fallback registry)
- Locale resolution < 1 ms per request
- Translation lookup < 10 µs (cached)
- Extraction of 1000 strings < 5s

### Key technical decisions
1. **Babel + gettext:** industry standard, well-supported, IDE tools exist
2. **Middleware:** resolves locale from (1) query param `?lang=`, (2) `Accept-Language`, (3) session, (4) default
3. **Pluralization:** ICU MessageFormat via `PyICU` (optional) for complex plural rules
4. **Extraction:** `pybabel extract -F babel.cfg` finds `_()` calls in code + `{{ _() }}` in templates
5. **Catalog update:** `pybabel update` merges new strings without losing existing translations
6. **Compile:** `pybabel compile` emits binary `.mo` files for runtime
7. **Fallback chain:** per-locale YAML config for dialect fallbacks
8. **Number/date formatting:** Babel's `format_number`, `format_date`, `format_currency`
9. **RTL support:** locale metadata flag, middleware adds `dir=rtl` to response headers
10. **Missing-translation audit:** CLI reports untranslated strings per locale

### Key invariants
1. Default locale is ALWAYS resolvable (never fails on fallback).
2. Missing translations ALWAYS fall back through the chain, never raise.
3. Catalogs are ALWAYS compiled to `.mo` before deploy.
4. Extraction is ALWAYS idempotent (merges, never overwrites human edits).
5. Locale codes ALWAYS conform to BCP-47 (e.g., `pt_BR`, not `pt-br`).
6. RTL flag is ALWAYS set for `ar`, `he`, `fa`, `ur`.
7. Plural rules ALWAYS come from CLDR via Babel (no hardcoded).

### User story themes
- 9.1 Basic translation (US-01..05): `_()` extracted, .po edited, .mo compiled, response localized
- 9.2 Locale detection (US-06..10): query param, header, user pref, fallback, default
- 9.3 Pluralization (US-11..15): 0/1/many, Polish edge, ICU, CLDR rules
- 9.4 Formatting (US-16..20): date, number, currency, RTL
- 9.5 Edge cases (US-21..25): missing translation, audit, tool idempotency

### Test plan categories
- 10.1 Middleware (T-01..06): query, header, pref, fallback, default, multi-source
- 10.2 Translation (T-07..12): extract, compile, lookup, cache, fallback
- 10.3 Pluralization (T-13..18): 0/1/many, ICU, Polish, CLDR
- 10.4 Formatting (T-19..24): date, number, currency, RTL
- 10.5 Edge cases (T-25..30): missing, audit, tool idempotency

### Edge cases (15)
1. `Accept-Language: es-MX,es;q=0.9` → matches es_MX via region
2. Locale unknown → falls back to default
3. Fallback chain loop → detected, broken with clear error
4. Translation missing → falls through chain, returns key as last resort
5. Plural rule for Arabic (6 forms) → handled via CLDR
6. RTL language (ar) → dir=rtl added to response
7. Number formatting locale-specific (1,000.00 vs 1.000,00) → correct
8. Date format (MM/DD vs DD/MM) → correct per locale
9. Missing translation audit finds gaps → report generated
10. `.po` file manually edited then re-extracted → merged, not overwritten
11. Tool re-run idempotent
12. Locale from URL path (`/en/products`) → honored
13. User preference saved in DB → takes precedence over header
14. Untranslated string logs warning (dev only) → helps catch gaps
15. Catalog compilation failure → deploy blocked

### Anti-patterns
- DO NOT hardcode plural rules (CLDR is the authority)
- DO NOT skip compilation (runtime lookup of .po is slow)
- DO NOT overwrite human-edited translations on re-extract
- DO NOT forget RTL (breaks layout for Arabic users)
- DO NOT resolve locale on every lookup (cache per request)
