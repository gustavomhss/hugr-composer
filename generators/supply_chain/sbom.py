"""Generator for SBOM (Software Bill of Materials) and lockfile reproducibility."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MCP_TOOL = {
    "name": "fastapi_supply_chain_generate_sbom",
    "description": "Generate SBOM (CycloneDX), lockfile (pip compile), and verify reproducible install.",
    "tags": ["generator", "supply_chain"],
    "entry": "generate_sbom",
}


def generate_sbom(
    output_dir: str,
    project_name: str = "app",
    generate_lockfile: bool = True,
    verify_reproducible: bool = True,
) -> dict:
    """Generate SBOM (CycloneDX), lockfile, and verify reproducible install.

    Args:
        output_dir: Root directory of the generated project.
        project_name: Name of the project for SBOM metadata.
        generate_lockfile: Whether to generate pip-compile lockfile.
        verify_reproducible: Whether to verify reproducible install in container.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    files_created = []
    notes = []

    # 1. Generate CycloneDX SBOM using cyclonedx-bom
    sbom_path = out / "sbom.cdx.json"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cyclonedx_bom",
                "--format",
                "json",
                "--output",
                str(sbom_path),
                out.as_posix(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            files_created.append(str(sbom_path))
            notes.append("SBOM generated (CycloneDX JSON) at sbom.cdx.json")
        else:
            notes.append(f"SBOM generation failed: {result.stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        notes.append(f"SBOM generation skipped: {exc}")

    # 2. Generate lockfile using pip-compile (if requirements.txt or pyproject.toml exists)
    lockfile_path = out / "requirements.lock"
    requirements_path = out / "requirements.txt"
    pyproject_path = out / "pyproject.toml"

    if generate_lockfile and (requirements_path.exists() or pyproject_path.exists()):
        try:
            source = requirements_path if requirements_path.exists() else pyproject_path
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "compile",
                    "--output-file",
                    str(lockfile_path),
                    str(source),
                    "--generate-hashes",
                    "--allow-unsafe",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0:
                files_created.append(str(lockfile_path))
                notes.append("Lockfile generated at requirements.lock with hashes")
            else:
                notes.append(f"Lockfile generation failed: {result.stderr}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            notes.append(f"Lockfile generation skipped: {exc}")

    # 3. Verify reproducible install in clean container (optional, heavy)
    if verify_reproducible:
        try:
            # Check if we have Docker and a lockfile
            if lockfile_path.exists():
                dockerfile_content = textwrap.dedent(f"""\
                    FROM python:3.12-slim AS builder
                    WORKDIR /build
                    COPY requirements.lock .
                    RUN pip install --no-cache-dir -r requirements.lock

                    FROM python:3.12-slim AS verifier
                    WORKDIR /verify
                    COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
                    RUN python -c "import sys; import pkg_resources; dists = [d for d in pkg_resources.working_set]; print('OK', len(dists), 'distributions')"
                """)
                dockerfile_path = out / "Dockerfile.verify"
                files_created.append(str(dockerfile_path))
                Path(output_dir).joinpath("Dockerfile.verify").write_text(
                    textwrap.dedent(f"""\
                        # Reproducible install verification Dockerfile
                        # Build: docker build -f Dockerfile.verify -t {{project_name}}-verify .
                        # Run: docker run --rm {{project_name}}-verify
                        FROM python:3.12-slim AS builder
                        WORKDIR /build
                        COPY requirements.lock .
                        RUN pip install --no-cache-dir -r requirements.lock

                        FROM python:3.12-slim AS verifier
                        WORKDIR /verify
                        COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
                        RUN python -c "import sys; import pkg_resources; dists = [d for d in pkg_resources.working_set]; print('OK', len(dists), 'distributions')"
                    """))
                files_created.append("Dockerfile.verify")
                notes.append("Dockerfile.verify added for reproducible install verification")
        except Exception as exc:
            notes.append(f"Reproducible install verification skipped: {exc}")

    # 4. Generate reproducibility manifest
    repro_manifest = {
        "project": project_name,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "pip_version": subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "generated_files": files_created,
    }
    repro_path = out / "reproducibility.json"
    Path(output_dir).joinpath("reproducibility.json").write_text(
        json.dumps(repro_manifest, indent=2, sort_keys=True) + "\n"
    )
    files_created.append("reproducibility.json")
    notes.append("Reproducibility manifest generated at reproducibility.json")

    return {"files_created": files_created, "notes": notes}


import textwrap
from pathlib import Path
import subprocess
import sys
import json
import textwrap