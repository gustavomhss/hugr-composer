from __future__ import annotations
from pathlib import Path


def verify(lockfile: str, fail_on_critical: bool=False) -> dict:
    """Run full lockfile verification pipeline.

    Args:
        lockfile: Path to requirements.txt or lockfile.
        fail_on_critical: Exit non-zero if critical vulns found.

    Returns:
        Dict with hash, confusion_warnings, critical_findings, passed.
    """
    path = Path(lockfile)
    if not path.exists():
        return {'error': f'Lockfile not found: {lockfile}', 'passed': False}
    lockfile_hash = hash_lockfile(path)
    confusion_warnings = detect_confusion(path)
    packages = parse_requirements(path)
    osv_results = query_osv(packages)
    critical_findings = find_critical_vulns(osv_results, packages)
    for w in confusion_warnings:
        logger.warning(w)
    for f in critical_findings:
        logger.error(f)
    passed = not (fail_on_critical and critical_findings)
    return {'lockfile_hash': lockfile_hash, 'packages_checked': len(packages), 'confusion_warnings': confusion_warnings, 'critical_findings': critical_findings, 'passed': passed}
