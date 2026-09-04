"""Generator for SemVer versioning, CHANGELOG.md, and VERSION file."""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

MCP_TOOL = {
    "name": "fastapi_semver_generate",
    "description": "Generate VERSION, CHANGELOG.md, and semver tooling (bump, validate).",
    "tags": ["generator", "semver", "changelog"],
    "entry": "generate_semver",
}


def generate_semver(
    output_dir: str,
    project_name: str = "app",
    initial_version: str = "0.1.0",
) -> dict:
    """Generate VERSION file, CHANGELOG.md template, and version bump script.

    Args:
        output_dir: Directory where VERSION, CHANGELOG.md, and bump_version.py will be written.
        project_name: Name of the project.
        initial_version: Initial version string (SemVer).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    files_created = []
    notes = []

    # 1. VERSION file
    version_path = Path(output_dir) / "VERSION"
    version_path.write_text(f"{initial_version}\n")
    files_created = ["VERSION"]
    notes.append(f"VERSION file created with initial version {initial_version}")

    # 2. CHANGELOG.md template
    changelog_path = Path(output_dir) / "CHANGELOG.md"
    changelog_content = textwrap.dedent(f"""\
        # Changelog

        All notable changes to `{project_name}` will be documented in this file.

        The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
        and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

        ## [Unreleased]
        ### Added
        -
        ### Changed
        -
        ### Deprecated
        -
        ### Removed
        -
        ### Fixed
        -
        ### Security
        -

        ## [{initial_version}] - {{date}}
        ### Added
        - Initial release of {project_name}
    """)
    changelog_path.write_text(changelog_content.format(date="YYYY-MM-DD"))
    files_created = ["VERSION", "CHANGELOG.md"]
    notes.append("CHANGELOG.md template created (Keep a Changelog format)")

# 3. Version bump script
    bump_script_path = Path(output_dir) / "scripts" / "bump_version.py"
    Path(output_dir, "scripts").mkdir(parents=True, exist_ok=True)
    bump_script = '''#!/usr/bin/env python
"""Bump version in VERSION, CHANGELOG.md, and pyproject.toml (if exists).

Usage:
    python scripts/bump_version.py major|minor|patch
    python scripts/bump_version.py 1.2.3  # explicit version
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
PYPROJECT_FILE = ROOT / "pyproject.toml"

SEMVER_REGEX = re.compile(r"^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-((?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\\+([0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*))?$")

def read_version() -> str:
    return VERSION_FILE.read_text().strip()

def write_version(version: str) -> None:
    VERSION_FILE.write_text(version + "\\n")

def update_changelog(version: str) -> None:
    import datetime
    today = __import__("datetime").date.today().isoformat()
    content = CHANGELOG_FILE.read_text()
    # Replace [Unreleased] with version + date, keep Unreleased section
    content = content.replace(
        "## [Unreleased]",
        f"## [Unreleased]\\n\\n## [{version}] - {__import__('datetime').date.today().isoformat()}"
    )
    CHANGELOG_FILE.write_text(content)

def update_pyproject(version: str) -> bool:
    if not PYPROJECT_FILE.exists():
        return False
    content = PYPROJECT_FILE.read_text()
    # Update version in [project] section
    new_content = re.sub(
        r'^version\\s*=\\s*["\\\'].*["\\\']',
        f'version = "{version}"',
        content,
        flags=re.MULTILINE,
    )
    if content != new_content:
        Path(PYPROJECT_FILE).write_text(new_content)
        return True
    return False

def bump_version(current: str, bump: str) -> str:
    match = SEMVER_REGEX.match(current)
    if not match:
        raise ValueError(f"Invalid current version: {current}")
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        # explicit version
        if SEMVER_REGEX.match(bump):
            return bump
        raise ValueError(f"Invalid bump: {bump}")

def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)

    if len(sys.argv) < 2:
        logging.info("Usage: python bump_version.py major|minor|patch|X.Y.Z")
        sys.exit(1)

    bump = sys.argv[1]
    current = read_version()
    try:
        new_version = bump_version(sys.argv[1], current)
    except ValueError as e:
        logging.error(f"Error: {e}")
        sys.exit(1)

    logging.info(f"Bumping {current} -> {new_version}")
    write_version(new_version)
    update_changelog(new_version)
    if (Path(__file__).parent.parent / "pyproject.toml").exists():
        update_pyproject(new_version)
    logging.info(f"Version bumped to {new_version}")
    logging.info("Remember to update CHANGELOG.md with actual changes!")

if __name__ == "__main__":
    main()
'''
    bump_path = Path(output_dir) / "scripts" / "bump_version.py"
    Path(output_dir, "scripts").mkdir(parents=True, exist_ok=True)
    Path(output_dir, "scripts", "bump_version.py").write_text(bump_script)
    files_created = ["VERSION", "CHANGELOG.md", "scripts/bump_version.py"]
    notes = [
        f"VERSION created with {initial_version}",
        "CHANGELOG.md created (Keep a Changelog format)",
        "scripts/bump_version.py created (usage: python scripts/bump_version.py major|minor|patch)",
    ]
    return {"files_created": files_created, "notes": notes}


MCP_TOOL = {
    "name": "fastapi_semver_generate",
    "description": "Generate VERSION, CHANGELOG.md, and semver tooling (bump, validate).",
    "tags": ["generator", "semver", "changelog"],
    "entry": "generate_semver",
}