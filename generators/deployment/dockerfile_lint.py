"""Generator: Dockerfile static analyzer and hadolint config.

Analyzes an existing Dockerfile for production anti-patterns and generates a
``.hadolint.yaml`` configuration file for CI integration.

Lint rules implemented
----------------------
DOCKER-01  Missing USER directive — container runs as root (UID 0).
DOCKER-02  Missing HEALTHCHECK instruction — Docker cannot assess container health.
DOCKER-03  RUN with sudo — indicates root assumption; breaks non-root containers.
DOCKER-04  ``latest`` tag on base image — non-deterministic, supply-chain risk.
DOCKER-05  Secrets in ARG (KEY, TOKEN, SECRET, PASSWORD) — exposed in image history.
DOCKER-06  Missing .dockerignore — build context bloat, risk of leaking .env files.
DOCKER-07  COPY . before COPY requirements — invalidates pip layer cache on every
           source-code change.

Usage::

    from generators.deployment.dockerfile_lint import (
        analyze_dockerfile,
        generate_dockerfile_lint_config,
    )

    result = analyze_dockerfile("/path/to/project")
    for f in result["findings"]:
        print(f"[{f.severity.value.upper()}] {f.rule_id}: {f.title}")

    config_result = generate_dockerfile_lint_config("/path/to/project")
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from sys import path as _sys_path

# ---------------------------------------------------------------------------
# Bootstrap import path so core.models resolves from any cwd
# ---------------------------------------------------------------------------
_SKILL_ROOT = Path(__file__).parent.parent.parent
if str(_SKILL_ROOT) not in _sys_path:
    _sys_path.insert(0, str(_SKILL_ROOT))

from core.models import Finding, Severity  # noqa: E402


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

_Lines = list[str]


# ---------------------------------------------------------------------------
# Individual rule checks  (one function per rule — hyper-modular)
# ---------------------------------------------------------------------------


def _check_docker_01(lines: _Lines) -> Finding | None:
    """DOCKER-01: Detect missing USER directive (runs as root).

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if no USER directive is present, else None.
    """
    has_user = any(
        line.strip().upper().startswith("USER ")
        for line in lines
        if not line.strip().startswith("#")
    )
    if has_user:
        return None
    return Finding(
        rule_id="DOCKER-01",
        severity=Severity.HIGH,
        title="Container runs as root — no USER directive",
        description=(
            "No USER instruction found. Container processes run as root (UID 0). "
            "If the application is compromised, the attacker has full system access. "
            "Many Kubernetes clusters block root containers via PodSecurityStandards."
        ),
        fix_suggestion=(
            "Add a non-root user before CMD:\n"
            "  RUN groupadd -r app && useradd -r -g app -u 10001 app\n"
            "  USER app"
        ),
    )


def _check_docker_02(lines: _Lines) -> Finding | None:
    """DOCKER-02: Detect missing HEALTHCHECK instruction.

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if no HEALTHCHECK is present, else None.
    """
    has_healthcheck = any(
        line.strip().upper().startswith("HEALTHCHECK")
        for line in lines
        if not line.strip().startswith("#")
    )
    if has_healthcheck:
        return None
    return Finding(
        rule_id="DOCKER-02",
        severity=Severity.MEDIUM,
        title="Missing HEALTHCHECK instruction",
        description=(
            "Docker cannot determine whether the containerized application is healthy. "
            "docker-compose, ECS, and Swarm rely on HEALTHCHECK for restart decisions."
        ),
        fix_suggestion=(
            "Add a health check before CMD:\n"
            "  HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\\n"
            '    CMD python -c "import urllib.request; '
            "urllib.request.urlopen('http://localhost:8000/healthz')\""
        ),
    )


def _check_docker_03(lines: _Lines) -> Finding | None:
    """DOCKER-03: Detect RUN with sudo (implies root assumption).

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if a RUN sudo command is found, else None.
    """
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.upper().startswith("RUN ") and re.search(r"\bsudo\b", stripped):
            return Finding(
                rule_id="DOCKER-03",
                severity=Severity.HIGH,
                title="RUN with sudo detected",
                description=(
                    f"Line {i}: '{stripped[:80]}' uses sudo inside a RUN instruction. "
                    "This assumes root is available and fails in non-root builds. "
                    "Install system packages in a dedicated RUN layer as root, then "
                    "switch to a non-root user before CMD."
                ),
                line_number=i,
                fix_suggestion=(
                    "Remove sudo. Arrange your Dockerfile so privileged RUN commands "
                    "execute before the USER switch."
                ),
            )
    return None


def _check_docker_04(lines: _Lines) -> Finding | None:
    """DOCKER-04: Detect 'latest' tag on base image (non-deterministic builds).

    Only checks the first FROM line (the base image).

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if the first FROM uses :latest, else None.
    """
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.upper().startswith("FROM "):
            parts = stripped.split()
            image_ref = parts[1] if len(parts) > 1 else ""
            if image_ref.endswith(":latest"):
                return Finding(
                    rule_id="DOCKER-04",
                    severity=Severity.MEDIUM,
                    title=f"Unpinned 'latest' tag on base image: {image_ref}",
                    description=(
                        f"Line {i}: base image '{image_ref}' uses the ':latest' tag. "
                        "The tag is mutable — upstream changes silently alter your build, "
                        "potentially introducing vulnerabilities or breaking changes."
                    ),
                    line_number=i,
                    fix_suggestion=(
                        "Pin to a specific version tag (python:3.12-slim) or an immutable "
                        "SHA256 digest (python:3.12-slim@sha256:abc123...)."
                    ),
                )
            return None  # Only inspect the first FROM line
    return None


def _check_docker_05(lines: _Lines) -> Finding | None:
    """DOCKER-05: Detect secrets in ARG names (exposed in image history).

    Matches ARG names containing KEY, TOKEN, SECRET, or PASSWORD (case-insensitive).

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if any secret-like ARG is found, else None.
    """
    _SECRET_PATTERN = re.compile(
        r"^\s*ARG\s+(\w*(?:SECRET|PASSWORD|KEY|TOKEN)\w*)",
        re.IGNORECASE,
    )
    secret_args: list[str] = []
    for line in lines:
        match = _SECRET_PATTERN.match(line)
        if match:
            secret_args.append(match.group(1))

    if not secret_args:
        return None

    names = ", ".join(secret_args)
    return Finding(
        rule_id="DOCKER-05",
        severity=Severity.CRITICAL,
        title=f"Potential secrets in ARG: {names}",
        description=(
            f"ARG values ({names}) are baked into image layer history and are "
            "visible via 'docker history --no-trunc'. Anyone with pull access to "
            "the image can extract these values."
        ),
        fix_suggestion=(
            "Use --mount=type=secret for build-time secrets:\n"
            "  RUN --mount=type=secret,id=my_token,env=MY_TOKEN pip install ...\n"
            "Or pass secrets at runtime via environment variables / K8s Secrets."
        ),
    )


def _check_docker_06(project_dir: Path) -> Finding | None:
    """DOCKER-06: Detect missing .dockerignore file.

    Args:
        project_dir: Path to the project root (directory containing Dockerfile).

    Returns:
        Finding if .dockerignore is absent, else None.
    """
    if (project_dir / ".dockerignore").exists():
        return None
    return Finding(
        rule_id="DOCKER-06",
        severity=Severity.MEDIUM,
        title="Missing .dockerignore file",
        description=(
            "No .dockerignore found in the project root. Docker will send the entire "
            "directory as build context, which may include .env files (credentials), "
            ".git history, virtual environments, and test artifacts. This bloats the "
            "build context and risks leaking secrets into the image layer."
        ),
        fix_suggestion=(
            "Create .dockerignore in the project root with at minimum:\n"
            "  .env\n  .env.*\n  .git\n  .venv\n  __pycache__\n  *.pyc"
        ),
    )


def _check_docker_07(lines: _Lines) -> Finding | None:
    """DOCKER-07: Detect COPY . before COPY requirements (breaks layer cache).

    When ``COPY . .`` appears before ``COPY requirements.txt``, every source-code
    change invalidates the pip install layer, causing full reinstalls on every build.

    Args:
        lines: Dockerfile lines (raw, including comments).

    Returns:
        Finding if COPY . precedes COPY requirements, else None.
    """
    copy_dot_line: int | None = None
    copy_req_line: int | None = None

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if (stripped.startswith("COPY . ") or stripped == "COPY . .") and copy_dot_line is None:
            copy_dot_line = i
        if "requirements" in stripped.lower() and stripped.startswith("COPY") and copy_req_line is None:
            copy_req_line = i

    if copy_dot_line is None or copy_req_line is None:
        return None
    if copy_dot_line >= copy_req_line:
        return None

    return Finding(
        rule_id="DOCKER-07",
        severity=Severity.MEDIUM,
        title="COPY . before COPY requirements — layer cache invalidated on every commit",
        description=(
            f"COPY . at line {copy_dot_line} appears before COPY requirements at "
            f"line {copy_req_line}. Every source-code change invalidates the pip "
            "install layer, forcing a full dependency reinstall on every build "
            "(typically 30–120 extra seconds)."
        ),
        line_number=copy_dot_line,
        fix_suggestion=(
            "Move COPY requirements.txt and RUN pip install BEFORE COPY . .:\n"
            "  COPY requirements.txt .\n"
            "  RUN pip install --no-cache-dir -r requirements.txt\n"
            "  COPY . ."
        ),
    )


# ---------------------------------------------------------------------------
# Severity sort key
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    """Return findings sorted by severity (CRITICAL first).

    Args:
        findings: Unsorted list of Finding objects.

    Returns:
        New list sorted by severity descending.
    """
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))


# ---------------------------------------------------------------------------
# Public API: analyze_dockerfile
# ---------------------------------------------------------------------------


def analyze_dockerfile(project_dir: str) -> dict:
    """Perform static analysis on an existing Dockerfile.

    Runs all 7 DOCKER-01..07 lint rules against the ``Dockerfile`` found in
    *project_dir* and returns a structured result dict.

    Args:
        project_dir: Absolute or relative path to the directory containing
            the Dockerfile to analyze.

    Returns:
        Dict with keys:

        * ``findings`` — list of :class:`~core.models.Finding` objects sorted
          by severity (CRITICAL first).
        * ``files_created`` — always ``[]`` (analysis only, no files written).
        * ``notes`` — human-readable summary strings.

    Example::

        result = analyze_dockerfile("/my/project")
        for f in result["findings"]:
            print(f"[{f.severity.value.upper()}] {f.rule_id}: {f.title}")
    """
    root = Path(project_dir)
    dockerfile_path = root / "Dockerfile"

    if not dockerfile_path.exists():
        return {
            "findings": [],
            "files_created": [],
            "notes": [f"No Dockerfile found at {dockerfile_path}. Nothing to analyze."],
        }

    content = dockerfile_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Run all 7 rules — collect non-None results
    raw: list[Finding | None] = [
        _check_docker_01(lines),
        _check_docker_02(lines),
        _check_docker_03(lines),
        _check_docker_04(lines),
        _check_docker_05(lines),
        _check_docker_06(root),
        _check_docker_07(lines),
    ]
    findings = _sorted_findings([f for f in raw if f is not None])

    critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in findings if f.severity == Severity.MEDIUM)
    low = sum(1 for f in findings if f.severity == Severity.LOW)

    summary = (
        f"Dockerfile analysis complete: {len(findings)} finding(s) — "
        f"CRITICAL={critical}, HIGH={high}, MEDIUM={medium}, LOW={low}."
    )

    return {
        "findings": findings,
        "files_created": [],
        "notes": [summary],
    }


# ---------------------------------------------------------------------------
# Public API: generate_dockerfile_lint_config
# ---------------------------------------------------------------------------

_HADOLINT_YAML = textwrap.dedent("""\
    # .hadolint.yaml — Dockerfile linter configuration
    # Generated by SKILL-001 generators/deployment/dockerfile_lint.py
    # Reference: https://github.com/hadolint/hadolint

    # Treat these rule violations as errors (fail CI):
    failure-threshold: warning

    # Globally ignored rules (adjust as needed):
    # DL3008: apt-get without pinned versions — acceptable in development images
    ignore:
      - DL3008

    # Trusted base image registries (docker.io allowed by default):
    trustedRegistries:
      - docker.io
      - ghcr.io
      - public.ecr.aws

    # Rules that map to our custom DOCKER-* checks (for reference):
    #   DOCKER-01 (no USER)          → DL3002
    #   DOCKER-02 (no HEALTHCHECK)   → DL3027 / manual
    #   DOCKER-03 (sudo in RUN)      → DL3004
    #   DOCKER-04 (latest tag)       → DL3007
    #   DOCKER-05 (secrets in ARG)   → SC2154 / manual
    #   DOCKER-06 (.dockerignore)    → manual
    #   DOCKER-07 (COPY ordering)    → manual
""")


def generate_dockerfile_lint_config(output_dir: str) -> dict:
    """Generate a ``.hadolint.yaml`` configuration file for Dockerfile linting.

    Writes a ready-to-use hadolint configuration that enforces SOTA Dockerfile
    best practices in CI.  The comments in the file cross-reference each
    hadolint rule to the corresponding DOCKER-01..07 custom check.

    Args:
        output_dir: Directory where ``.hadolint.yaml`` will be written.

    Returns:
        Dict with keys:

        * ``findings`` — always ``[]`` (config generation, no analysis).
        * ``files_created`` — list with the path of the created file.
        * ``notes`` — human-readable summary strings.

    Example::

        result = generate_dockerfile_lint_config("/my/project")
        print(result["files_created"])   # ["/my/project/.hadolint.yaml"]
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    config_path = out / ".hadolint.yaml"
    config_path.write_text(_HADOLINT_YAML, encoding="utf-8")

    return {
        "findings": [],
        "files_created": [str(config_path)],
        "notes": [
            ".hadolint.yaml written — run 'hadolint Dockerfile' to lint locally.",
            "Add 'hadolint/hadolint-action@v3' to your GitHub Actions workflow for CI.",
        ],
    }
