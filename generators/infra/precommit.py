"""Generator for .pre-commit-config.yaml."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_precommit',
    'description': 'Generate .pre-commit-config.yaml with Ruff linting/formatting and pre-commit hooks.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_precommit',
}

import textwrap
from pathlib import Path


def generate_precommit(
    output_dir: str,
    python_version: str = "3.12",
) -> dict:
    """Generate a .pre-commit-config.yaml with Ruff and standard hooks.

    Args:
        output_dir: Directory where .pre-commit-config.yaml will be written.
        python_version: Python version for language_version in hooks.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f"""\
        # See https://pre-commit.com for more information
        # Install: pip install pre-commit && pre-commit install
        # Run all: pre-commit run --all-files

        default_language_version:
          python: python{python_version}

        repos:
          # --------------------------------------------------------------------------
          # Ruff — fast Python linter + formatter (replaces flake8, isort, black)
          # --------------------------------------------------------------------------
          - repo: https://github.com/astral-sh/ruff-pre-commit
            rev: v0.8.6
            hooks:
              # Linting (runs before formatting so auto-fixes are formatted)
              - id: ruff
                args: [--fix, --exit-non-zero-on-fix]
              # Formatting (Black-compatible)
              - id: ruff-format

          # --------------------------------------------------------------------------
          # General file hygiene
          # --------------------------------------------------------------------------
          - repo: https://github.com/pre-commit/pre-commit-hooks
            rev: v5.0.0
            hooks:
              # Remove trailing whitespace from all files
              - id: trailing-whitespace
              # Ensure files end with a single newline
              - id: end-of-file-fixer
              # Validate YAML syntax
              - id: check-yaml
                args: [--allow-multiple-documents]
              # Prevent accidentally committing large files (>500 KB)
              - id: check-added-large-files
                args: [--maxkb=500]
              # Detect files that would conflict on case-insensitive filesystems
              - id: check-case-conflict
              # Ensure no merge conflict markers are left in files
              - id: check-merge-conflict
              # Validate JSON syntax
              - id: check-json
              # Validate TOML syntax
              - id: check-toml
              # Detect private keys
              - id: detect-private-key
    """)

    file_path = out / ".pre-commit-config.yaml"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated .pre-commit-config.yaml with Ruff (lint + format) and pre-commit-hooks.",
            f"Default Python version: {python_version}. Install with: pre-commit install.",
        ],
    }
