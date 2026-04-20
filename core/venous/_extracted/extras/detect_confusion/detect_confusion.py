from __future__ import annotations
from pathlib import Path
import re


def detect_confusion(lockfile_path: Path) -> list[str]:
    """Detect dependency confusion: internal packages potentially shadowed on PyPI.

    Args:
        lockfile_path: Path to requirements.txt.

    Returns:
        List of warning strings for suspicious packages.
    """
    warnings: list[str] = []
    content = lockfile_path.read_text()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name = re.split('[>=<!=;\\s]', line)[0].lower()
        if any((name.startswith(prefix.lower()) for prefix in _INTERNAL_PREFIXES)):
            warnings.append(f"CONFUSION-RISK: '{name}' matches internal prefix — verify it cannot be claimed on PyPI")
    return warnings
