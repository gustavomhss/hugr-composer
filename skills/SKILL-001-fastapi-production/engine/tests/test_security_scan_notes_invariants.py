"""B0.13 honesty test for ``verify/security_scan``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "SARIF 2.1.0 output — uploads to GitHub Security tab automatically."

The matched B0.13 claim token is ``"automatically"``. The honest
reading: the emitted GitHub Actions workflow MUST include a
``github/codeql-action/upload-sarif`` step that runs on every CI
invocation (``if: always()`` so it fires even when the scan exits
non-zero) AND the orchestrator MUST actually produce a SARIF 2.1.0
artefact for that step to upload.

Without the upload step, the SARIF artefact lives only inside the
runner and never reaches the GitHub Security tab — the "uploads
automatically" half of the claim is structurally false. Without the
``if: always()`` guard, a failing scan would skip the upload and
operators would never see the findings.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py``
(``tool_leaf`` is ``security_scan``).

What we actually assert
=======================

1. ``test_security_scan_workflow_automatically_uploads_sarif`` —
   the emitted CI workflow MUST declare a step using
   ``github/codeql-action/upload-sarif@v<N>`` AND that step's
   ``with.sarif_file`` MUST name a path the orchestrator writes.

2. ``test_security_scan_workflow_upload_step_runs_automatically_on_failure``
   — the upload step MUST have ``if: always()`` so the SARIF lands
   in the Security tab even when the scan exits non-zero (operators
   only learn about findings if the upload is reached). Without
   ``always()`` the claim collapses to "uploads on green CI" — far
   weaker than the notes line implies.

3. ``test_security_scan_workflow_grants_security_events_write`` —
   uploading SARIF requires ``security-events: write`` permission
   on the job. Without it the GitHub action fails at the upload
   step with HTTP 403 and the "automatically" claim is false even
   when every other piece is wired correctly.

4. ``test_security_scan_orchestrator_emits_sarif_filename`` — the
   orchestrator MUST write the SARIF file at the path the workflow
   references. A mismatch ("results.sarif" vs "security-results.
   sarif") would silently upload nothing and the claim would be
   trivially "uploaded an empty file".

5. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* The CI workflow is a YAML template; we parse it with ``yaml.safe_
  load`` after stripping the leading comment header — no execution.
* The orchestrator is read as text (its primary role is invoking
  external scanners); we string-search for the SARIF filename
  literal rather than fully parsing the bandit/semgrep argument
  flow.
* "Automatically" is asserted via the workflow steps (the
  observable mechanism). Whether the underlying SARIF is *valid*
  schema-wise is the orchestrator's responsibility; this test only
  asserts the upload-pipeline shape.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "verify" / "security_scan"
WORKFLOW_TMPL = TOOL_DIR / "templates" / "ci_workflow.yml.tmpl"
ORCHESTRATOR_TMPL = TOOL_DIR / "templates" / "orchestrator.py.tmpl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_HEADER_RE = re.compile(r"^#[^\n]*\n", re.MULTILINE)


def _load_workflow(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    return yaml.safe_load(src)


def _all_steps(wf: dict) -> list[dict]:
    """Flatten every step across every job."""
    out: list[dict] = []
    for job in (wf.get("jobs") or {}).values():
        for step in job.get("steps", []) or []:
            if isinstance(step, dict):
                out.append(step)
    return out


def _upload_sarif_step(wf: dict) -> dict | None:
    for step in _all_steps(wf):
        uses = step.get("uses", "")
        if isinstance(uses, str) and "upload-sarif" in uses:
            return step
    return None


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for ``automatically``.
# ---------------------------------------------------------------------------


def test_security_scan_workflow_automatically_uploads_sarif() -> None:
    """The CI workflow MUST declare a ``github/codeql-action/upload-sarif``
    step AND that step's ``with.sarif_file`` MUST point at the
    artefact the orchestrator produces. Without the step the SARIF
    artefact never leaves the runner.
    """
    wf = _load_workflow(WORKFLOW_TMPL)
    step = _upload_sarif_step(wf)
    assert step is not None, (
        "ci_workflow.yml.tmpl MUST include a step using "
        "`github/codeql-action/upload-sarif@v<N>`. Without it the "
        "SARIF artefact never reaches the GitHub Security tab and "
        "the `automatically` claim is structurally false."
    )

    with_section = step.get("with", {})
    sarif_file = with_section.get("sarif_file")
    assert isinstance(sarif_file, str) and sarif_file.endswith(".sarif"), (
        f"upload-sarif step MUST set `with.sarif_file: <path>.sarif`; "
        f"found {sarif_file!r}."
    )


def test_security_scan_workflow_upload_step_runs_automatically_on_failure() -> None:
    """The upload step MUST carry ``if: always()`` so the SARIF lands
    even when the scan exits non-zero. Without it, failing scans
    silently skip the upload and operators never see the findings —
    the `automatically` claim would mean "uploads on green CI"
    which is the opposite of what reviewers expect from a security
    pipeline.
    """
    wf = _load_workflow(WORKFLOW_TMPL)
    step = _upload_sarif_step(wf)
    assert step is not None, "upload-sarif step missing (see previous test)"

    cond = step.get("if")
    # YAML may parse `always()` as a string literal `always()`.
    assert isinstance(cond, str) and "always()" in cond, (
        f"upload-sarif step MUST set `if: always()` (got {cond!r}); "
        f"without it the upload skips on non-zero scan exit and the "
        f"`automatically` claim collapses to `uploads only on green`."
    )


def test_security_scan_workflow_grants_security_events_write() -> None:
    """Uploading SARIF requires the ``security-events: write``
    permission on the job; without it the GitHub action fails with
    HTTP 403 at the upload step and the SARIF never lands in the
    Security tab.
    """
    wf = _load_workflow(WORKFLOW_TMPL)
    jobs = wf.get("jobs") or {}
    found = False
    for job in jobs.values():
        perms = job.get("permissions") or {}
        if not isinstance(perms, dict):
            continue
        if perms.get("security-events") == "write":
            found = True
    assert found, (
        "ci_workflow.yml.tmpl MUST grant `permissions: {security-"
        "events: write}` on the job that runs upload-sarif. Without "
        "it the upload step fails with 403 and the `automatically` "
        "claim is false even when every other piece is wired."
    )


def test_security_scan_orchestrator_emits_sarif_filename() -> None:
    """The orchestrator MUST write the SARIF file at the same path
    the workflow's ``with.sarif_file`` references. A mismatch
    silently uploads nothing.
    """
    wf = _load_workflow(WORKFLOW_TMPL)
    step = _upload_sarif_step(wf)
    assert step is not None, "upload-sarif step missing (see earlier test)"
    sarif_path = step.get("with", {}).get("sarif_file")
    assert isinstance(sarif_path, str), "sarif_file not a string"
    sarif_basename = sarif_path.rsplit("/", 1)[-1]

    orch_src = ORCHESTRATOR_TMPL.read_text(encoding="utf-8")
    assert sarif_basename in orch_src, (
        f"orchestrator.py.tmpl MUST reference the SARIF filename "
        f"{sarif_basename!r} that the workflow uploads. A mismatch "
        f"means the upload step has nothing to upload and the "
        f"`automatically` claim is hollow."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``verify/security_scan`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "verify/security_scan" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for verify/security_scan was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
