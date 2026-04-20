from __future__ import annotations
from pathlib import Path
import re


def parse_requirements(lockfile_path: Path) -> list[dict]:
    """Parse requirements.txt into list of name/version dicts.

    Args:
        lockfile_path: Path to requirements.txt.

    Returns:
        List of dicts with 'name' and 'version' keys.
    """
    packages = []
    for line in lockfile_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('-'):
            continue
        match = re.match('^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)', line)
        if match:
            packages.append({'name': match.group(1), 'version': match.group(2)})
    return packages
