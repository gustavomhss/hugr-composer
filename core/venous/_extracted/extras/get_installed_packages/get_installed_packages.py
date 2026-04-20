from __future__ import annotations
import json
import sys


def get_installed_packages() -> list[dict]:
    """Return list of installed packages via pip inspect.

    Returns:
        List of dicts with name, version, metadata fields.
    """
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', 'inspect', '--format=json'], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return data.get('installed', [])
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.warning('pip inspect failed: %s', exc)
        return []
