from __future__ import annotations
from datetime import datetime
from datetime import timezone
from pathlib import Path
import json


def generate_sbom(output_path: str, sign: bool=False) -> dict:
    """Generate CycloneDX 1.4 JSON SBOM and write to output_path.

    Args:
        output_path: File path to write the SBOM JSON.
        sign: When True, embed SHA-256 integrity hash in metadata.

    Returns:
        Dict with component_count and output_path.
    """
    packages = get_installed_packages()
    components = [build_component(p) for p in packages]
    sbom: dict = {'bomFormat': 'CycloneDX', 'specVersion': '1.4', 'version': 1, 'metadata': {'timestamp': datetime.now(timezone.utc).isoformat(), 'tools': [{'name': 'sbom_guardian', 'version': '1.0.0'}]}, 'components': components}
    sbom_json = json.dumps(sbom, indent=2)
    if sign:
        sbom['metadata']['integrity'] = compute_sbom_hash(sbom_json)
        sbom_json = json.dumps(sbom, indent=2)
    Path(output_path).write_text(sbom_json)
    logger.info('SBOM written to %s (%d components)', output_path, len(components))
    return {'component_count': len(components), 'output_path': output_path}
