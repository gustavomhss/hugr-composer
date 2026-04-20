from __future__ import annotations


def find_critical_vulns(osv_results: list[dict], packages: list[dict]) -> list[str]:
    """Return list of CRITICAL/HIGH severity vulnerability descriptions.

    Args:
        osv_results: Results from query_osv().
        packages: Original package list (parallel to osv_results).

    Returns:
        List of human-readable critical finding strings.
    """
    findings: list[str] = []
    for pkg, result in zip(packages, osv_results):
        for vuln in result.get('vulns', []):
            severity = vuln.get('database_specific', {}).get('severity', '')
            if severity.upper() in ('CRITICAL', 'HIGH'):
                findings.append(f"VULN {severity}: {pkg['name']}=={pkg['version']} — {vuln.get('id', 'unknown')} {vuln.get('summary', '')[:80]}")
    return findings
