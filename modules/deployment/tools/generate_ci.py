"""
SKILL-001 Deployment Tool: Generate GitHub Actions CI/CD workflows.

Creates production-grade GitHub Actions workflows for FastAPI applications with:
  - Test job: pytest with coverage reporting
  - Lint job: ruff for fast Python linting
  - Build job: Docker multi-stage build with layer caching
  - Scan job: Trivy container vulnerability scanning (fail on CRITICAL/HIGH)
  - Push job: Push to GitHub Container Registry (ghcr.io)
  - Deploy job: Optional Kubernetes deployment via kubectl set image

The workflow enforces the quality gate chain: tests -> lint -> build -> scan -> push -> deploy.
Each stage gates the next — a failure at any point blocks deployment.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_ci_pipeline',
    'description': 'Generate GitHub Actions CI/CD workflow for FastAPI: test, lint, Docker build with caching, Trivy scan, push, deploy.',
    'tags': ['deployment', 'generator'],
    'entry': 'generate_github_actions',
    'annotations': {'readOnlyHint': False, 'destructiveHint': False},
}

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# GitHub Actions workflow generator
# ---------------------------------------------------------------------------


def generate_github_actions(
    project_name: str,
    python_version: str = "3.12",
    with_docker: bool = True,
    with_k8s: bool = False,
    *,
    registry: str = "ghcr.io",
    k8s_deployment_name: str | None = None,
    k8s_namespace: str = "default",
    test_command: str = "pytest --cov --tb=short -q",
    lint_enabled: bool = True,
    trivy_severity: str = "CRITICAL,HIGH",
    trivy_exit_code: int = 1,
    branches: list[str] | None = None,
) -> str:
    """
    Generate a GitHub Actions CI/CD workflow for a FastAPI project.

    Creates a multi-job workflow that enforces quality gates in sequence:
    test -> lint -> build Docker image -> scan with Trivy -> push to registry
    -> optional K8s deploy. Each job depends on the previous, ensuring
    broken code never reaches production.

    Args:
        project_name: Used in image names and workflow title.
        python_version: Python version for test/lint jobs (default: "3.12").
        with_docker: Include Docker build, scan, and push jobs (default: True).
        with_k8s: Include Kubernetes deploy job (default: False).
        registry: Container registry prefix (default: "ghcr.io").
        k8s_deployment_name: K8s Deployment name for rollout. Defaults to project_name.
        k8s_namespace: K8s namespace for deployment (default: "default").
        test_command: Command to run tests (default: "pytest --cov --tb=short -q").
        lint_enabled: Include ruff lint job (default: True).
        trivy_severity: Trivy severity filter (default: "CRITICAL,HIGH").
        trivy_exit_code: Trivy exit code on findings — 1 fails the build,
            0 reports only (default: 1).
        branches: Trigger branches (default: ["main"]).

    Returns:
        String containing the complete GitHub Actions workflow YAML.

    Example::

        workflow = generate_github_actions(
            project_name="billing-api",
            python_version="3.12",
            with_docker=True,
            with_k8s=True,
        )
        Path(".github/workflows/ci.yml").write_text(workflow)

        # Docker-only (no K8s deploy):
        workflow = generate_github_actions("billing-api")

        # Tests-only (no Docker):
        workflow = generate_github_actions("billing-api", with_docker=False)
    """
    if branches is None:
        branches = ["main"]
    if k8s_deployment_name is None:
        k8s_deployment_name = project_name

    branch_list = ", ".join(branches)
    image_name = f"{registry}/${{{{ github.repository_owner }}}}/{project_name}"

    # --- Test job (always present) ---
    test_job = textwrap.dedent(f"""\
      test:
        name: Test
        runs-on: ubuntu-latest
        steps:
        - uses: actions/checkout@v4

        - uses: actions/setup-python@v5
          with:
            python-version: "{python_version}"
            cache: pip

        - name: Install dependencies
          run: |
            python -m pip install --upgrade pip
            pip install -r requirements.txt
            pip install -r requirements-dev.txt || true

        - name: Run tests
          run: {test_command}

        - name: Upload coverage
          uses: actions/upload-artifact@v4
          if: always()
          with:
            name: coverage-report
            path: |
              .coverage
              htmlcov/
            retention-days: 7
    """)

    # --- Lint job (optional) ---
    lint_job = ""
    lint_needs = ""
    if lint_enabled:
        lint_needs = ", lint"
        lint_job = textwrap.dedent(f"""\

      lint:
        name: Lint
        runs-on: ubuntu-latest
        steps:
        - uses: actions/checkout@v4

        - uses: actions/setup-python@v5
          with:
            python-version: "{python_version}"
            cache: pip

        - name: Install ruff
          run: pip install ruff

        - name: Ruff check
          run: ruff check . --output-format=github

        - name: Ruff format check
          run: ruff format --check .
    """)

    # --- Docker build + scan + push jobs ---
    docker_jobs = ""
    if with_docker:
        docker_needs = f"[test{lint_needs}]"
        docker_jobs = textwrap.dedent(f"""\

      build-and-scan:
        name: Build & Scan
        needs: {docker_needs}
        runs-on: ubuntu-latest
        permissions:
          contents: read
          packages: write
          security-events: write    # Required for SARIF upload
        outputs:
          image-tag: ${{{{ steps.meta.outputs.tags }}}}
        steps:
        - uses: actions/checkout@v4

        - name: Set up Docker Buildx
          uses: docker/setup-buildx-action@v3

        - name: Docker metadata
          id: meta
          uses: docker/metadata-action@v5
          with:
            images: {image_name}
            tags: |
              type=sha,prefix=
              type=ref,event=branch
              type=semver,pattern={{{{version}}}}

        - name: Build image (no push yet)
          uses: docker/build-push-action@v6
          with:
            context: .
            push: false
            load: true
            tags: ${{{{ steps.meta.outputs.tags }}}}
            labels: ${{{{ steps.meta.outputs.labels }}}}
            cache-from: type=gha
            cache-to: type=gha,mode=max

        - name: Trivy vulnerability scan
          uses: aquasecurity/trivy-action@0.28.0
          with:
            image-ref: {image_name}:${{{{ github.sha }}}}
            format: sarif
            output: trivy-results.sarif
            severity: "{trivy_severity}"
            exit-code: "{trivy_exit_code}"

        - name: Upload Trivy SARIF to GitHub Security
          uses: github/codeql-action/upload-sarif@v3
          if: always()
          with:
            sarif_file: trivy-results.sarif

        - name: Login to registry
          uses: docker/login-action@v3
          with:
            registry: {registry}
            username: ${{{{ github.actor }}}}
            password: ${{{{ secrets.GITHUB_TOKEN }}}}

        - name: Push image
          uses: docker/build-push-action@v6
          with:
            context: .
            push: true
            tags: ${{{{ steps.meta.outputs.tags }}}}
            labels: ${{{{ steps.meta.outputs.labels }}}}
            cache-from: type=gha
            cache-to: type=gha,mode=max
    """)

    # --- K8s deploy job ---
    k8s_job = ""
    if with_k8s and with_docker:
        k8s_job = textwrap.dedent(f"""\

      deploy:
        name: Deploy to Kubernetes
        needs: [build-and-scan]
        runs-on: ubuntu-latest
        if: github.ref == 'refs/heads/main'
        environment: production
        steps:
        - uses: actions/checkout@v4

        - name: Configure kubectl
          uses: azure/setup-kubectl@v4

        - name: Set kubeconfig
          run: |
            mkdir -p $HOME/.kube
            echo "${{{{ secrets.KUBECONFIG }}}}" | base64 -d > $HOME/.kube/config

        - name: Deploy
          run: |
            kubectl set image deployment/{k8s_deployment_name} \\
              {k8s_deployment_name}={image_name}:${{{{ github.sha }}}} \\
              -n {k8s_namespace}

        - name: Wait for rollout
          run: |
            kubectl rollout status deployment/{k8s_deployment_name} \\
              -n {k8s_namespace} --timeout=300s

        - name: Verify deployment
          run: |
            kubectl get pods -l app={k8s_deployment_name} -n {k8s_namespace}
            echo "---"
            kubectl get deployment/{k8s_deployment_name} -n {k8s_namespace} -o wide
    """)

    # --- Compose the full workflow ---
    return textwrap.dedent(f"""\
        # =============================================================================
        # {project_name} — CI/CD Pipeline
        # Generated by SKILL-001 Deployment Module
        # =============================================================================
        #
        # Quality gate chain: test -> lint -> build -> scan (Trivy) -> push -> deploy
        # Each job gates the next. A failure at any point blocks deployment.
        #
        # Required secrets:
        #   GITHUB_TOKEN    — Auto-provided, used for ghcr.io push
        {"#   KUBECONFIG      — Base64-encoded kubeconfig for K8s deploy" if with_k8s else "#"}
        # =============================================================================

        name: CI/CD

        on:
          push:
            branches: [{branch_list}]
          pull_request:
            branches: [{branch_list}]

        concurrency:
          group: ${{{{ github.workflow }}}}-${{{{ github.ref }}}}
          cancel-in-progress: true

        jobs:
        {test_job}{lint_job}{docker_jobs}{k8s_job}""")


# ---------------------------------------------------------------------------
# Workflow analysis
# ---------------------------------------------------------------------------


def analyze_github_workflow(workflow_content: str) -> list[Finding]:
    """
    Analyze an existing GitHub Actions workflow for CI/CD anti-patterns.

    Checks for 6 common issues: missing Trivy/security scan, unpinned
    action versions, missing concurrency control, no test step, Docker
    push without scan gate, and missing cache configuration.

    Args:
        workflow_content: The raw YAML content of a GitHub Actions workflow.

    Returns:
        List of Finding objects for detected anti-patterns.

    Example::

        content = Path(".github/workflows/ci.yml").read_text()
        findings = analyze_github_workflow(content)
        for f in findings:
            print(f"[{f.severity.value}] {f.rule_id}: {f.title}")
    """
    findings: list[Finding] = []
    lower_content = workflow_content.lower()

    # CI-01: No security scanning
    has_trivy = "trivy" in lower_content
    has_snyk = "snyk" in lower_content
    has_grype = "grype" in lower_content
    has_scan = has_trivy or has_snyk or has_grype
    if not has_scan:
        findings.append(Finding(
            rule_id="CI-01",
            severity=Severity.HIGH,
            title="No container security scanning in pipeline",
            description=(
                "No Trivy, Snyk, or Grype scan step found. Container images "
                "may ship with known CVEs in system libraries. Automated scanning "
                "reduces vulnerability exposure by up to 87%."
            ),
            fix_suggestion=(
                "Add aquasecurity/trivy-action@0.28.0 after docker build, "
                "with exit-code: 1 to fail on CRITICAL/HIGH vulnerabilities."
            ),
        ))

    # CI-02: Unpinned action versions (@master, @main, @latest)
    import re
    unpinned_actions = re.findall(
        r"uses:\s*(\S+@(?:master|main|latest))",
        workflow_content,
    )
    if unpinned_actions:
        findings.append(Finding(
            rule_id="CI-02",
            severity=Severity.HIGH,
            title=f"Unpinned action versions: {', '.join(unpinned_actions[:3])}",
            description=(
                "Actions using @master/@main/@latest are vulnerable to supply chain "
                "attacks. A compromised action version runs with your repo's secrets."
            ),
            fix_suggestion=(
                "Pin actions to specific versions or SHA: "
                "uses: actions/checkout@v4 or uses: actions/checkout@abc123..."
            ),
        ))

    # CI-03: No concurrency control
    has_concurrency = "concurrency:" in lower_content
    if not has_concurrency:
        findings.append(Finding(
            rule_id="CI-03",
            severity=Severity.LOW,
            title="No concurrency control",
            description=(
                "Without concurrency groups, pushing 3 commits in quick succession "
                "runs 3 full pipelines simultaneously, wasting CI minutes and "
                "potentially causing race conditions in deployment."
            ),
            fix_suggestion=(
                "Add concurrency group: "
                "concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, "
                "cancel-in-progress: true }"
            ),
        ))

    # CI-04: No test step
    has_pytest = "pytest" in lower_content
    has_test = "test" in lower_content and ("run:" in lower_content or "run :" in lower_content)
    if not has_pytest and not has_test:
        findings.append(Finding(
            rule_id="CI-04",
            severity=Severity.CRITICAL,
            title="No test step in CI pipeline",
            description=(
                "No pytest or test command found. Without tests in CI, broken "
                "code reaches production unchecked."
            ),
            fix_suggestion="Add a test job: run: pytest --cov --tb=short",
        ))

    # CI-05: Docker push without scan gate
    has_push = "push: true" in lower_content or "docker push" in lower_content
    if has_push and not has_scan:
        findings.append(Finding(
            rule_id="CI-05",
            severity=Severity.HIGH,
            title="Docker push without vulnerability scan gate",
            description=(
                "Docker image is pushed to registry without a security scan step. "
                "Vulnerable images enter the registry and may be auto-deployed "
                "before anyone notices."
            ),
            fix_suggestion=(
                "Add Trivy scan BETWEEN build and push, with exit-code: 1 "
                "to block push on critical/high CVEs."
            ),
        ))

    # CI-06: No build cache
    has_cache = "cache" in lower_content
    if not has_cache:
        findings.append(Finding(
            rule_id="CI-06",
            severity=Severity.LOW,
            title="No build caching configured",
            description=(
                "No pip cache or Docker layer cache found. Every CI run "
                "reinstalls all dependencies from scratch, adding 2-5 minutes "
                "per run and increasing costs."
            ),
            fix_suggestion=(
                "Add cache to setup-python (cache: pip) and docker/build-push-action "
                "(cache-from: type=gha, cache-to: type=gha,mode=max)."
            ),
        ))

    # Sort by severity
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return findings
