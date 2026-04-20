from __future__ import annotations
import json


def query_osv(packages: list[dict]) -> list[dict]:
    """Query OSV API for known vulnerabilities.

    Args:
        packages: List of dicts with 'name' and 'version'.

    Returns:
        List of vulnerability result dicts.
    """
    if not packages:
        return []
    queries = [{'version': p['version'], 'package': {'name': p['name'], 'ecosystem': 'PyPI'}} for p in packages]
    payload = json.dumps({'queries': queries}).encode()
    req = urllib.request.Request(_OSV_BATCH_URL, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get('results', [])
    except Exception as exc:
        logger.warning('OSV query failed (offline?): %s', exc)
        return []
