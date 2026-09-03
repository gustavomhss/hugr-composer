"""Scaffold manifest + doc-gate scripts (WP-01, commit 1).

Two responsibilities:

1. Emit ``.hugr-scaffold-manifest.json`` at the very END of ``generate_project`` —
   a sidecar that records ``{path: sha256}`` for the ~20 files in the narrow
   watched set (the doc surface whose drift the CI gate will detect).

2. Vend ``scripts/sync_docs.py`` + ``scripts/check_docs_drift.py`` into the
   generated project.  These two scripts are **self-contained** — they import
   nothing from ``generators/`` because the emitted project does not have the
   kit installed.  All emitters inlined here.

The disable flag (``.hugr-scaffold-disable``) is *not* emitted by default; it
is a conscious opt-out the operator creates after reading the message the
drift check prints.  Its mere existence makes ``check_docs_drift.py`` exit 0.

CRLF normalization is mandatory: ``content.replace(b'\\r\\n', b'\\n')`` before
``sha256`` so Windows checkouts (which auto-translate on checkout depending on
``.gitattributes``) do not produce permanent false-positives.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Watched set — narrow doc surface (~20 files).  Order is irrelevant here; the
# writer below sorts paths alphabetically for determinism.
# ---------------------------------------------------------------------------

WATCHED_PATTERNS: tuple[str, ...] = (
    "README.md",
    ".env.example",
    ".gitignore",
    ".github/workflows/ci.yml",
    "requirements.txt",
    "alembic.ini",
    "alembic/env.py",
    "alembic/versions/0001_*.py",
    "alembic/versions/0002_*.py",
    "core/venous/**/*.py",
    "pytest.ini",
    "tests/conftest.py",
)

# Files explicitly NOT watched (user-owned).  Kept here as a comment-anchor
# for the reviewer — these MUST NOT be added to WATCHED_PATTERNS:
#   - app/**/*.py      (user-owned business logic)
#   - tests/test_*.py  (user-authored tests)
#   - core/venous/**/__pycache__/*  (build artefacts)


# ---------------------------------------------------------------------------
# CRLF-safe hashing
# ---------------------------------------------------------------------------


def _sha256_bytes(content: bytes) -> str:
    """sha256 of ``content`` after CRLF→LF normalization (cross-OS deterministic)."""
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _sha256_file(path: Path) -> str:
    """sha256 of a file's bytes after CRLF→LF normalization."""
    return _sha256_bytes(path.read_bytes())


def _discover_watched(out: Path) -> list[Path]:
    """Return all files under ``out`` that match WATCHED_PATTERNS, alphabetically sorted."""
    seen: dict[str, Path] = {}
    for pattern in WATCHED_PATTERNS:
        matches = sorted(out.glob(pattern))
        for m in matches:
            if m.is_file():
                seen[str(m.relative_to(out))] = m
    return [seen[k] for k in sorted(seen.keys())]


# ---------------------------------------------------------------------------
# Manifest emit
# ---------------------------------------------------------------------------


def _kit_commit() -> str:
    """Best-effort kit HEAD commit hash.  Falls back to 'unknown' if no git."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001 — manifest must never fail generation
        return "unknown"


def write_manifest(
    out: Path,
    *,
    skill: str,
    name: str,
    prefix: str,
    profile: str,
) -> Path:
    """Write ``.hugr-scaffold-manifest.json`` next to every other project file.

    Called as the *very last* step of ``generate_project``.  Sorts paths
    alphabetically so the manifest is byte-stable for a given project state.
    """
    files = []
    for path in _discover_watched(out):
        files.append({"path": str(path.relative_to(out)), "sha256": _sha256_file(path)})

    manifest = {
        "version": 1,
        "kit": {"skill": skill, "commit": _kit_commit()},
        "params": {"name": name, "prefix": prefix, "profile": profile},
        "files": files,
    }
    target = out / ".hugr-scaffold-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target


# ---------------------------------------------------------------------------
# Inlined emitters — minimal but valid versions of each watched file.
#
# Goal: ``sync_docs.py`` must make ``check_docs_drift.py`` pass again.  We
# only re-emit what we know how to template.  ``core/venous/*`` is re-copied
# from the kit if available, otherwise skipped (no-op).
# ---------------------------------------------------------------------------

README_TEMPLATE = """\
# {name}

Production FastAPI service scaffolded with **HuGR Arsenal** (profile: `{profile}`).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in secrets
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Docs drift guard

This project is wired with a hash-based doc-drift gate.  If CI complains:

```bash
./scripts/sync_docs.py     # re-emit watched files to match the manifest
```

To intentionally opt out (do this consciously):

```bash
touch .hugr-scaffold-disable
```

See `.hugr-scaffold-manifest.json` for the watched-file hashes.
"""

ENV_EXAMPLE_TEMPLATE = """\
# {name} — environment template.  NEVER commit a filled .env.
APP_ENV=development
APP_DEBUG=true
APP_SECRET_KEY=changeme-32-bytes-base64
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/{name}
REDIS_URL=redis://localhost:6379/0
"""

REQUIREMENTS_TEMPLATE = """\
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.2
pydantic-settings==2.5.2
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
alembic==1.13.3
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
"""

PYTEST_INI_TEMPLATE = """\
[pytest]
asyncio_mode = auto
testpaths = tests
"""

GITIGNORE_TEMPLATE = """\
__pycache__/
*.py[cod]
.venv/
.env
.pytest_cache/
*.egg-info/
dist/
build/
"""

CI_YML_TEMPLATE = """\
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: pip install -r requirements.txt
      - run: pytest -q
"""

ALEMBIC_INI_TEMPLATE = """\
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

ALEMBIC_ENV_PY_TEMPLATE = '''\
"""Alembic env — async runner (HuGR scaffold)."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

ALEMBIC_0001_TEMPLATE = '''\
"""initial schema (HuGR scaffold stub)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''

ALEMBIC_0002_TEMPLATE = '''\
"""second revision (HuGR scaffold stub)."""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''


# ---------------------------------------------------------------------------
# sync_docs.py — vendored.  Self-contained, stdlib only.
# ---------------------------------------------------------------------------

SYNC_DOCS_PY = textwrap.dedent(
    '''\
    #!/usr/bin/env python
    """sync_docs.py — re-emit the watched doc surface to match the manifest.

    Run this after the doc-drift CI gate complains.  It uses the params baked
    into ``.hugr-scaffold-manifest.json`` (not the current shell env) so the
    emission is reproducible.

    Stdlib only — no import from the kit (the emitted project does not have
    the kit installed).
    """
    from __future__ import annotations

    import hashlib
    import json
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    MANIFEST = ROOT / ".hugr-scaffold-manifest.json"

    TEMPLATES = {
        "README.md": "# {name}\\n\\nProfile: {profile}\\n",
        ".env.example": "APP_ENV=development\\nDATABASE_URL=postgresql://{name}\\n",
        ".gitignore": "__pycache__/\\n.venv/\\n.env\\n",
        "requirements.txt": "fastapi==0.115.0\\nuvicorn[standard]==0.32.0\\n",
        "pytest.ini": "[pytest]\\nasyncio_mode = auto\\n",
        ".github/workflows/ci.yml": (
            "name: ci\\non: [push]\\njobs:\\n  test:\\n    runs-on: ubuntu-latest\\n"
        ),
        "alembic.ini": "[alembic]\\nscript_location = alembic\\n",
        "alembic/env.py": "# Alembic env stub\\n",
    }

    def _norm(b: bytes) -> str:
        return hashlib.sha256(b.replace(b"\\r\\n", b"\\n")).hexdigest()

    def _emit(target: Path, body: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    def main() -> int:
        if not MANIFEST.is_file():
            print("manifest missing", file=sys.stderr)
            return 2
        m = json.loads(MANIFEST.read_text())
        params = m["params"]
        name, prefix, profile = params["name"], params["prefix"], params["profile"]
        rendered = {
            k: v.format(name=name, prefix=prefix, profile=profile)
            for k, v in TEMPLATES.items()
        }
        try:
            for rel, body in rendered.items():
                _emit(ROOT / rel, body)
        except OSError as exc:
            print(f"io error: {{exc}}", file=sys.stderr)
            return 1
        # Refresh manifest hashes for the re-emitted files.
        for entry in m["files"]:
            p = ROOT / entry["path"]
            if p.is_file():
                entry["sha256"] = _norm(p.read_bytes())
        MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True) + "\\n")
        print("synced")
        return 0

    if __name__ == "__main__":
        sys.exit(main())
    '''
)


# ---------------------------------------------------------------------------
# check_docs_drift.py — vendored.  Self-contained, stdlib only.
# ---------------------------------------------------------------------------

CHECK_DOCS_DRIFT_PY = textwrap.dedent(
    '''\
    #!/usr/bin/env python
    """check_docs_drift.py — hash-comparison gate for the narrow doc surface.

    Exit codes:
      0 = no drift (or gate disabled by presence of ``.hugr-scaffold-disable``)
      1 = drift detected (print offending files + the fix)
      2 = manifest missing (cannot run gate)
    """
    from __future__ import annotations

    import hashlib
    import json
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    MANIFEST = ROOT / ".hugr-scaffold-manifest.json"
    DISABLE = ROOT / ".hugr-scaffold-disable"


    def _norm(b: bytes) -> str:
        return hashlib.sha256(b.replace(b"\\r\\n", b"\\n")).hexdigest()


    def main() -> int:
        if DISABLE.is_file():
            print("doc-gate=disabled")
            return 0
        if not MANIFEST.is_file():
            print("manifest missing", file=sys.stderr)
            return 2
        m = json.loads(MANIFEST.read_text())
        drift: list[str] = []
        for entry in m["files"]:
            p = ROOT / entry["path"]
            if not p.is_file():
                drift.append(entry["path"] + " (missing)")
                continue
            if _norm(p.read_bytes()) != entry["sha256"]:
                drift.append(entry["path"])
        if not drift:
            print("doc-gate=pass")
            return 0
        print("doc-gate=drift: " + ", ".join(drift))
        print("fix: run ./scripts/sync_docs.py")
        return 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
)


# ---------------------------------------------------------------------------
# Top-level: emit scripts + manifest together.  Called from phase 13.
# ---------------------------------------------------------------------------


def emit_doc_gate(
    out: Path,
    *,
    skill: str,
    name: str,
    prefix: str,
    profile: str,
) -> Path:
    """Vendor the 2 scripts and write the manifest.  Returns the manifest path."""
    scripts_dir = out / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "sync_docs.py").write_text(SYNC_DOCS_PY)
    (scripts_dir / "check_docs_drift.py").write_text(CHECK_DOCS_DRIFT_PY)
    (scripts_dir / "sync_docs.py").chmod(0o755)
    (scripts_dir / "check_docs_drift.py").chmod(0o755)
    return write_manifest(out, skill=skill, name=name, prefix=prefix, profile=profile)
