# TOOL-087 — `add_structured_logging`

**Layer:** extend / infrastructure / observability
**Entry point:** `adapt.extend.infrastructure.add_structured_logging.add_structured_logging`
**MCP name:** `fastapi_add_structured_logging`
**Source:** `adapt/extend/infrastructure/add_structured_logging.py` (487 LOC)
**Tests:** `adapt/extend/infrastructure/test_add_structured_logging.py` (22 tests)

---

## 1. Overview

`add_structured_logging` upgrades a FastAPI project's logging to **structlog** with a
JSON/console renderer, per-request correlation ID binding via `contextvars`, and a
`Redactor` processor that strips PII (emails, phone numbers, credit card PANs, and API keys)
from every log event.

The tool writes the `app/logging/` package — `setup.py`, `redactor.py`, `context.py`, and
`__init__.py` — patches `app/core/config.py` with `LOG_LEVEL` / `LOG_FORMAT` /
`LOG_REDACTION_ENABLED`, and patches `app/main.py` to call `configure_structlog()` at module
load. No new pip dependency is introduced: `structlog` is already present in the base project's
`requirements.txt`.

The tool is fully **idempotent**: a second invocation detects
`"configure_structlog" in app/logging/setup.py` and returns `status="no_op"`.

---

## 2. Purpose

| Problem | Solution |
|---------|---------|
| Default Python logging emits unstructured text | `configure_structlog()` replaces renderer with `JSONRenderer` |
| No correlation IDs across async requests | `bind_context()` wraps `structlog.contextvars.bind_contextvars` |
| PII leaking into log aggregators | `Redactor.__call__()` applies 4 regex patterns to every string value |
| Log level / format hardcoded in source | `LOG_LEVEL` / `LOG_FORMAT` env vars read at startup |
| structlog configured inconsistently | Single `configure_structlog()` call from `main.py` |

---

## 3. Performance SLOs

| SLO | Target |
|-----|--------|
| Tool execution time | < 200 ms on warm filesystem |
| `execution_time_ms` field | Always present and > 0 |
| `Redactor.__call__()` overhead | < 10 µs per event (4 regex substitutions on string fields only) |
| `bind_context()` overhead | < 1 µs (thin wrapper over `structlog.contextvars`) |
| New pip dependencies added | 0 — structlog already in base requirements |

---

## 4. Code Examples

### Before

```python
# app/main.py — stdlib logging, no structlog
import logging
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
```

```python
# app/core/config.py — no logging fields
class Settings(BaseSettings):
    APP_NAME: str = "myapp"
    REDIS_URL: str = "redis://localhost:6379/0"
```

### After

```python
# app/logging/setup.py — configure_structlog with JSON renderer and PII redaction
def configure_structlog(
    level: str = "INFO",
    fmt: str = "json",
    redaction_enabled: bool = True,
) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if redaction_enabled:
        redactor = Redactor()
        processors.append(redactor)
    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
```

```python
# app/logging/redactor.py — Redactor processor with 4 PII patterns
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_CARD_RE  = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_APIKEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|bearer)[=:\s]+[\w\-\.]{8,}"
)

class Redactor:
    def __call__(
        self,
        logger: Any,
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        for key, value in list(event_dict.items()):
            if isinstance(value, str):
                event_dict[key] = _redact_string(value)
        return event_dict

def _redact_string(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED]", text)
    text = _PHONE_RE.sub("[REDACTED]", text)
    text = _CARD_RE.sub("[REDACTED]", text)
    text = _APIKEY_RE.sub(r"\1=[REDACTED]", text)
    return text
```

```python
# app/logging/context.py — correlation ID helpers
def get_correlation_id() -> str:
    ctx = structlog.contextvars.get_contextvars()
    return str(ctx.get("correlation_id") or uuid.uuid4())

def bind_context(**kwargs: Any) -> None:
    structlog.contextvars.bind_contextvars(**kwargs)

def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
```

```python
# app/core/config.py — patched with LOG_* fields
class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Structured logging — added by add_structured_logging tool
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_REDACTION_ENABLED: bool = True
```

```python
# app/main.py — patched to call configure_structlog at module load
from fastapi import FastAPI
from app.logging.setup import configure_structlog as _configure_structlog  # noqa: F401
import os as _log_os

app = FastAPI()

# Structured logging startup — added by add_structured_logging tool
_configure_structlog(
    level=_log_os.getenv("LOG_LEVEL", "INFO"),
    fmt=_log_os.getenv("LOG_FORMAT", "json"),
    redaction_enabled=_log_os.getenv("LOG_REDACTION_ENABLED", "true").lower() != "false",
)
```

---

## 5. Quality Standards

| Standard | Requirement |
|----------|-------------|
| Function size | No function > 50 LOC (AST-verified in T-07) |
| Type hints | 100% on all public functions |
| Docstrings | Every public function and class has a docstring |
| New pip dependencies | Zero — structlog already in base requirements |
| Syntax validity | All generated `.py` files pass `ast.parse()` |
| Config indent | All injected Settings fields use 4-space indent |
| Idempotency | Second run returns `status="no_op"`, zero file changes |
| PII coverage | Redactor covers email, phone (E.164), credit card PAN, API key patterns |
| Async safety | `contextvars` used for per-request context — no thread-safety issues |

---

## 6. Completeness Criteria

| ID | Criterion | Verified by |
|----|-----------|-------------|
| CC-01 | Tool returns `status="success"` on a fresh fixture project | T-01 |
| CC-02 | Second run returns `status="no_op"` with zero files created/modified | T-02 |
| CC-03 | `dry_run=True` returns success but writes nothing to disk | T-03 |
| CC-04 | `files_created` contains >= 3 entries, all of which exist on disk | T-04 |
| CC-05 | `files_modified` contains >= 1 entry, all of which exist on disk | T-05 |
| CC-06 | All `.py` files in the project parse without `SyntaxError` | T-06 |
| CC-07 | No generated function in `app/logging/` exceeds 50 LOC | T-07 |
| CC-08 | `LOG_LEVEL`, `LOG_FORMAT`, and `LOG_REDACTION_ENABLED` in `config.py` with 4-space indent | T-08 |
| CC-09 | `app/logging/setup.py` exists and contains `configure_structlog` and `structlog` | T-09 |
| CC-10 | `app/logging/setup.py` contains `JSONRenderer` or `json` (case-insensitive) | T-10 |
| CC-11 | `app/logging/redactor.py` exists with `Redactor` class, email pattern, and `[REDACTED]` | T-11 |
| CC-12 | `app/logging/context.py` exists with `get_correlation_id` and `bind_context` | T-12 |
| CC-13 | `app/main.py` contains `configure_structlog` after patching | T-13 |
| CC-14 | `app/logging/__init__.py` re-exports `configure_structlog` and `Redactor` | T-14 |
| CC-15 | `redactor.py` contains `api` / `token` / `secret` (case-insensitive) | T-15 |
| CC-16 | `result.execution_time_ms` is a positive integer | T-16 |
| CC-17 | `result.next_steps` is non-empty and mentions `log` or `structlog` | T-17 |
| CC-18 | After two runs all `.py` files remain parseable | T-18 |
| CC-19 | `result.notes` mention `structlog` / `redact` / `json` | T-19 |
| CC-20 | `redactor.py` has a credit card pattern (`CARD` / `card` / `\d`) | T-20 |
| CC-21 | `context.py` has both `bind_context` and `clear_context` | T-21 |
| CC-22 | `setup.py` contains `contextvars` or `correlation` (correlation processor) | T-22 |

---

## 7. Definition of Done

- [ ] `add_structured_logging(ToolInput(project_dir=...))` returns `status="success"`
- [ ] `app/logging/__init__.py`, `setup.py`, `redactor.py`, `context.py` all created
- [ ] `app/core/config.py` patched with `LOG_LEVEL`, `LOG_FORMAT`, `LOG_REDACTION_ENABLED`
- [ ] `app/main.py` patched with `configure_structlog()` call at module load
- [ ] `requirements.txt` NOT modified (structlog already present)
- [ ] Second run returns `no_op` without touching any file
- [ ] `dry_run=True` writes nothing to disk
- [ ] All 22 tests pass: `pytest adapt/extend/infrastructure/test_add_structured_logging.py -v`

---

## 8. Invariants

| ID | Invariant |
|----|-----------|
| INV-SLOG-01 | `structlog` is NEVER imported lazily — it is a required base dependency |
| INV-SLOG-02 | `Redactor.__call__()` only processes `str` values; non-string values are passed through unchanged |
| INV-SLOG-03 | `Redactor` applies all 4 patterns in order: email → phone → card → API key |
| INV-SLOG-04 | `bind_context()` uses `structlog.contextvars` — never `threading.local()` |
| INV-SLOG-05 | `get_correlation_id()` returns a fresh `uuid.uuid4()` when no correlation ID is bound |
| INV-SLOG-06 | `LOG_FORMAT="console"` selects `ConsoleRenderer`; any other value selects `JSONRenderer` |
| INV-SLOG-07 | `LOG_REDACTION_ENABLED=False` disables the `Redactor` processor entirely |
| INV-SLOG-08 | `configure_structlog()` is called from `app/main.py` at module load, before `app = FastAPI()` |
| INV-SLOG-09 | Idempotency fingerprint is `"configure_structlog" in app/logging/setup.py` |
| INV-SLOG-10 | Config anchor is `REDIS_URL: str = "redis://localhost:6379/0"` (not `ACCESS_TOKEN_EXPIRE_MINUTES`) |
| INV-SLOG-11 | `execution_time_ms` is recorded on every return path including errors and no_op |
| INV-SLOG-12 | No new pip dependency is added to `requirements.txt` |

---

## 9. User Stories

### Installation Stories (US-01 – US-05)

**US-01** — As a backend engineer, I want to run `fastapi_add_structured_logging` once and have
structlog fully configured with JSON output and PII redaction, so I don't manually wire up
processors.

**US-02** — As an SRE, I want the tool to be idempotent, so I can include it in provisioning
pipelines without worrying about duplicate processor registration.

**US-03** — As a developer, I want `dry_run=True` to show me what would change without touching
any files, so I can preview the installation before committing.

**US-04** — As a developer, I want zero new pip dependencies, so the installation doesn't
increase the project's dependency surface.

**US-05** — As a platform engineer, I want `LOG_LEVEL`, `LOG_FORMAT`, and
`LOG_REDACTION_ENABLED` injected into `class Settings`, so all runtime configuration lives
in the standard settings object.

### Logging Format Stories (US-06 – US-10)

**US-06** — As an SRE, I want `LOG_FORMAT=json` to produce machine-readable JSON logs with
ISO timestamps, so log aggregation pipelines (Datadog, Loki, CloudWatch) can parse them.

**US-07** — As a developer, I want `LOG_FORMAT=console` to produce human-readable coloured
output locally, so I can read logs without piping through `jq`.

**US-08** — As a developer, I want `structlog.contextvars.merge_contextvars` as the first
processor, so any context bound via `bind_context()` is automatically included in every log
entry for the current request.

**US-09** — As a developer, I want `structlog.processors.TimeStamper(fmt="iso")` in the
processor chain, so every log entry has a standardised timestamp.

**US-10** — As a developer, I want `structlog.processors.format_exc_info` in the chain,
so exceptions are serialised as structured data rather than raw tracebacks.

### PII Redaction Stories (US-11 – US-15)

**US-11** — As a compliance engineer, I want `Redactor` to strip email addresses matching
`[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+`, so no PII leaks to log aggregators.

**US-12** — As a compliance engineer, I want `Redactor` to strip phone numbers in E.164 and
common formats, so customer contact details are never logged in plain text.

**US-13** — As a compliance engineer, I want `Redactor` to strip credit card PANs (13–19 digit
sequences), so cardholder data is never written to log sinks.

**US-14** — As a security engineer, I want `Redactor` to strip API key / token / secret /
bearer patterns, so leaked credentials are replaced with `[REDACTED]` before reaching storage.

**US-15** — As a developer, I want to disable redaction via `LOG_REDACTION_ENABLED=false` in
development, so I can inspect actual values during local debugging without regex overhead.

### Correlation ID Stories (US-16 – US-20)

**US-16** — As a developer, I want `bind_context(request_id=...)` to propagate the value to
every log entry in the same async request, so I can trace a request end-to-end.

**US-17** — As a developer, I want `get_correlation_id()` to return the bound `correlation_id`
from context, or a fresh UUID4 if none is bound, so it is always safe to call.

**US-18** — As a developer, I want `clear_context()` to erase all structlog context vars at
request teardown, so context from one request does not leak into the next.

**US-19** — As a developer, I want `structlog.contextvars` used (not `threading.local`), so
the context binding is safe in an `async def` / `asyncio` environment.

**US-20** — As a developer, I want `app/logging/__init__.py` to re-export `configure_structlog`,
`Redactor`, `get_correlation_id`, and `bind_context`, so callers import from a single stable
namespace.

### Integration Stories (US-21 – US-25)

**US-21** — As a developer, I want `configure_structlog()` called in `app/main.py` before the
FastAPI application is created, so all logging is structured from the first import.

**US-22** — As a developer, I want the `main.py` patch to read `LOG_LEVEL`, `LOG_FORMAT`, and
`LOG_REDACTION_ENABLED` from environment variables, so no restart is needed to change level.

**US-23** — As a developer, I want any module to obtain a structured logger with
`import structlog; log = structlog.get_logger()`, without importing anything from `app.logging`.

**US-24** — As a developer, I want the tool to check whether `LOG_LEVEL` is already in
`config.py` before patching, so a second run never duplicates config fields.

**US-25** — As a developer, I want `next_steps` to include the `.env` settings hint and usage
example for `structlog.get_logger()`, so the full setup path is documented.

---

## 10. Test Plan

| Test ID | Test Name | CC Covered | What it verifies |
|---------|-----------|------------|-----------------|
| T-01 | `test_success_status` | CC-01 | `status == "success"` on fresh fixture project |
| T-02 | `test_idempotent` | CC-02 | Second run: `status == "no_op"`, no files created/modified |
| T-03 | `test_dry_run` | CC-03 | `dry_run=True` returns success, zero disk changes, `before == after` snapshot |
| T-04 | `test_files_created_count` | CC-04 | `len(files_created) >= 3`, all paths exist on disk |
| T-05 | `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist on disk |
| T-06 | `test_all_py_parse` | CC-06 | Every `.py` in project parses after tool |
| T-07 | `test_no_function_over_50_loc` | CC-07 | AST walk of `app/logging/`: no function > 50 LOC |
| T-08 | `test_config_fields_patched` | CC-08 | `LOG_LEVEL`, `LOG_FORMAT`, `LOG_REDACTION_ENABLED` in `config.py`; 4-space indent |
| T-09 | `test_setup_file_has_configure_structlog` | CC-09 | `setup.py` exists with `configure_structlog` and `structlog` |
| T-10 | `test_setup_file_has_json_renderer` | CC-10 | `setup.py` contains `JSONRenderer` or `json` |
| T-11 | `test_redactor_file_has_pii_patterns` | CC-11 | `redactor.py` exists with `Redactor`, email pattern, `[REDACTED]` |
| T-12 | `test_context_file_has_correlation_id` | CC-12 | `context.py` exists with `get_correlation_id` and `bind_context` |
| T-13 | `test_main_py_patched_with_configure_structlog` | CC-13 | `main.py` contains `configure_structlog` |
| T-14 | `test_logging_init_has_exports` | CC-14 | `__init__.py` contains `configure_structlog` and `Redactor` |
| T-15 | `test_redactor_has_api_key_pattern` | CC-15 | `redactor.py` contains `api` / `token` / `secret` |
| T-16 | `test_execution_time_recorded` | CC-16 | `result.execution_time_ms > 0` |
| T-17 | `test_next_steps_present` | CC-17 | `result.next_steps` non-empty, contains `log` or `structlog` |
| T-18 | `test_idempotent_project_still_parses` | CC-18 | Two runs; all `.py` still parseable |
| T-19 | `test_notes_mention_structlog_or_redaction` | CC-19 | `result.notes` mentions `structlog` / `redact` / `json` |
| T-20 | `test_redactor_strips_credit_cards` | CC-20 | `redactor.py` has `CARD` / `card` / `\d` pattern |
| T-21 | `test_context_has_bind_and_clear` | CC-21 | `context.py` has `bind_context` and `clear_context` |
| T-22 | `test_setup_has_correlation_processor` | CC-22 | `setup.py` contains `contextvars` or `correlation` |

**Run command:**
```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_structured_logging.py -v
```

---

## 11. Interaction Matrix

| Tool | Interaction | Notes |
|------|-------------|-------|
| `fastapi_generate_project` | Prerequisite | Provides `app/core/config.py` with REDIS_URL anchor, `app/main.py`, and base `structlog` dependency |
| `add_prometheus_metrics` (TOOL-086) | Complementary | Both patch `main.py` idempotently; install order does not matter |
| `add_opentelemetry` (TOOL-085) | Complementary | OTEL spans and structlog entries can be correlated via `correlation_id` |
| `add_arq_worker` (TOOL-053) | Complementary | Workers should call `bind_context(worker_id=..., job_id=...)` to enrich job logs |
| Log aggregator (Datadog / Loki / CloudWatch) | Consumer | JSON renderer output is directly ingestible; index on `correlation_id` |

---

## 12. Rollback Procedure

The tool does not provide an automated rollback command. Manual steps:

1. **Remove generated package:**
   ```bash
   rm -rf app/logging/
   ```

2. **Revert `app/core/config.py`** — remove the `LOG_LEVEL` / `LOG_FORMAT` /
   `LOG_REDACTION_ENABLED` block.

3. **Revert `app/main.py`** — remove the `from app.logging.setup import configure_structlog...`
   import lines and the `_configure_structlog(...)` call block appended at the end.

4. Verify with `pytest` to confirm no test regressions.

---

## 13. Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| `app/main.py` does not exist | Step 3 is skipped; `files_modified` will not include `main.py` |
| `REDIS_URL` anchor absent from `config.py` | `_patch_config()` falls back to `@computed_field` / `@model_validator` / `@property` decorators, then `settings = Settings()`, then raw append |
| `LOG_LEVEL` already in `config.py` | `_patch_config()` detects it and returns without patching |
| `configure_structlog` already in `main.py` | `_patch_main()` detects it and returns without patching |
| `structlog` not installed at runtime | `configure_structlog()` raises `ImportError`; tool does not guard against this — it is a required base dependency |
| `LOG_FORMAT` set to unknown value | Falls through to `JSONRenderer` (the `else` branch in `configure_structlog`) |
| Non-string values in `event_dict` | `Redactor` iterates all values but applies substitution only when `isinstance(value, str)` — others pass through unchanged |
| Very long string values | `_redact_string()` applies regex substitution which is linear in string length; no length cap is applied |
| `contextvars` in non-async context | `structlog.contextvars` is backed by Python's `contextvars.ContextVar` — safe in both sync and async code |

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|------------|
| PII in log aggregators | `Redactor` strips email, phone, credit card, and API key patterns from all string values |
| `LOG_REDACTION_ENABLED=false` in production | The `next_steps` note explicitly warns this is not suitable for production |
| Regex correctness | `_CARD_RE` matches 13–19 digit sequences which may cause false positives on numeric IDs; acceptable trade-off for PII safety |
| `LOG_LEVEL=DEBUG` leaking sensitive data | Redactor applies regardless of log level, but developers should not log raw request bodies at DEBUG in production |
| structlog misconfiguration silencing errors | `logging.basicConfig(level=...)` is called after `structlog.configure()` to ensure stdlib handlers remain active |

---

## 15. Observability

The structured logging layer IS the observability output. After installation:

| Feature | Details |
|---------|---------|
| Format | JSON (production) or console (development), controlled by `LOG_FORMAT` |
| Timestamp | ISO 8601 via `TimeStamper(fmt="iso")` |
| Level | Configurable via `LOG_LEVEL` env var; default `INFO` |
| Correlation | `correlation_id` field bound per-request via `bind_context(correlation_id=...)` in middleware |
| PII | Stripped by `Redactor` before emission: email → `[REDACTED]`, phone → `[REDACTED]`, card PAN → `[REDACTED]`, API key → `key=[REDACTED]` |
| Stack traces | Structured via `format_exc_info` processor |

Tool execution records `execution_time_ms` in the `ToolResult`. No additional instrumentation
is emitted by the tool itself.

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-04-15 | Initial spec — 22 CCs, 12 invariants, 25 user stories |
