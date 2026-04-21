"""MaestroAdapter Protocol + concrete adapters (naked + kit + stub).

Each adapter consumes a Spec + workdir and emits files into the workdir
while recording a full trajectory (see PROTOCOL.md §5). The harness does
NOT judge the emitted code; that's the judge module's job.

Two real adapters:
  - NakedAdapter  — Claude CLI subagent, no MCP config, brief.md only
  - KitAdapter    — Claude CLI subagent + SKILL-001 MCP config

One stub:
  - StubAdapter   — used in unit tests to validate harness plumbing.
                    Emits a pre-baked project + synthetic trajectory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass
class EmissionResult:
    """What an adapter produced for one (spec, workdir) pair."""
    emit_status: str                       # "success" | "timeout" | "error"
    error: str = ""
    trajectory_path: Path | None = None    # jsonl with full transcript
    tool_calls_path: Path | None = None    # jsonl, flat
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    wall_clock_s: float = 0.0
    model: str = ""
    temperature: float = 0.0
    seed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class MaestroAdapter(Protocol):
    name: str

    def emit(self, spec, workdir: Path, *, seed: int) -> EmissionResult:  # noqa: ANN001
        """Run the agent against the spec; produce emitted code in workdir."""


# ---------------------------------------------------------------------------
# Stub adapter — validates harness plumbing end-to-end without an LLM call.
# ---------------------------------------------------------------------------

class StubAdapter:
    """Replays a pre-baked emission from a fixture directory.

    Used by unit tests + the `--stub` mode of the runner. Does NOT touch the
    network or run an LLM — copies files deterministically and emits a
    synthetic trajectory.
    """

    def __init__(self, fixture_root: Path, *, name: str = "stub") -> None:
        self._fixture_root = fixture_root
        self.name = name

    def emit(self, spec, workdir: Path, *, seed: int) -> EmissionResult:  # noqa: ANN001
        t0 = time.perf_counter()
        # Fixture layout: <fixture_root>/<spec_id-slug>/<name>/emitted/
        slug = spec.spec_id.replace("/", "__")
        src = self._fixture_root / slug / self.name / "emitted"
        if not src.exists():
            return EmissionResult(
                emit_status="error",
                error=f"stub fixture missing: {src}",
                wall_clock_s=time.perf_counter() - t0,
                model="stub", seed=seed,
            )
        # Copy fixture → workdir
        if workdir.exists():
            shutil.rmtree(workdir)
        shutil.copytree(src, workdir)

        # Emit a synthetic trajectory
        traj_path = workdir.parent / "trajectory.jsonl"
        tool_path = workdir.parent / "tool_calls.jsonl"
        now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        trajectory_lines = [
            {"turn": 0, "timestamp": now, "role": "system",
             "content": [{"type": "text", "text": "stub adapter"}],
             "model": "stub", "usage": {}, "latency_ms": 0},
            {"turn": 1, "timestamp": now, "role": "user",
             "content": [{"type": "text", "text": spec.brief[:200]}],
             "model": "stub", "usage": {}, "latency_ms": 0},
            {"turn": 2, "timestamp": now, "role": "assistant",
             "content": [{"type": "text", "text": f"[stub:{self.name}] emitted fixture"}],
             "model": "stub",
             "usage": {"input_tokens": 100, "output_tokens": 50},
             "latency_ms": 1,
             "workdir_snapshot_after": "final"},
        ]
        traj_path.write_text("\n".join(json.dumps(l) for l in trajectory_lines) + "\n")
        tool_path.write_text("")  # stub has no tool calls

        return EmissionResult(
            emit_status="success",
            trajectory_path=traj_path,
            tool_calls_path=tool_path,
            input_tokens=100, output_tokens=50,
            wall_clock_s=time.perf_counter() - t0,
            model="stub", seed=seed,
            extra={"adapter": "stub", "fixture_slug": slug},
        )


# ---------------------------------------------------------------------------
# Claude CLI subagent adapter (live).
# ---------------------------------------------------------------------------

@dataclass
class ClaudeCliConfig:
    """Config for invoking a Claude CLI subagent."""
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.7
    max_turns: int = 40
    mcp_config_path: Path | None = None     # None → naked
    dangerously_skip_permissions: bool = True
    timeout_s: int = 900


class AdapterConfigError(RuntimeError):
    """Raised on adapter init when config is inconsistent.

    Example: KitAdapter is asked to run but its mcp_config_path does not
    exist — we refuse to silently run as naked (that would corrupt the
    benchmark's two-arm design).
    """


class ClaudeCliAdapter:
    """Drives `claude -p` (print mode) with optional MCP config.

    This is the real adapter used for naked vs kit runs. It shells out to
    the locally-authenticated Claude CLI — no API key handling needed in
    the harness. Emits the full jsonl transcript from claude's --output-format=stream-json.
    """

    def __init__(self, config: ClaudeCliConfig, *, name: str) -> None:
        self.config = config
        self.name = name
        # Fail-fast validation — a KitAdapter that silently runs with no
        # MCP config corrupts the benchmark. The only legitimate way to
        # run without MCP is naked (mcp_config_path is None by design).
        if self.name == "kit" and self.config.mcp_config_path is None:
            raise AdapterConfigError(
                "KitAdapter constructed with mcp_config_path=None — refuse to "
                "silently degrade to naked. Pass the path to the kit's "
                "claude_code.mcp.json (examples/claude_code.mcp.json) or rename "
                "this adapter to 'naked'."
            )
        if self.config.mcp_config_path is not None:
            p = Path(self.config.mcp_config_path)
            if not p.is_file():
                raise AdapterConfigError(
                    f"mcp_config_path does not exist: {p}. Refuse to start — "
                    f"a run with a missing MCP config would be naked-in-disguise."
                )
            # Validate JSON parseability + presence of at least one server.
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise AdapterConfigError(f"mcp_config_path not valid JSON: {p} ({exc})") from exc
            if not cfg.get("mcpServers"):
                raise AdapterConfigError(
                    f"mcp_config_path at {p} has no mcpServers entries — "
                    f"running as kit would be indistinguishable from naked."
                )

    def emit(self, spec, workdir: Path, *, seed: int) -> EmissionResult:  # noqa: ANN001
        """Stream Claude CLI stdout line-by-line and snapshot per tool-use turn.

        Unlike a buffered `subprocess.run()` read, this method:
          - Opens the CLI via `Popen` and reads stdout one line at a time,
            so per-turn latency is measured accurately AS events arrive.
          - After each assistant turn whose content contains `tool_use`
            blocks that modify the filesystem, snapshots the workdir
            via `snapshots.snapshot_workdir` — giving step-level deltas
            for process-reward-model training (PROTOCOL §7c).
          - Enforces `timeout_s` on the cumulative wall clock (kills the
            subprocess group on breach).
        """
        from engine.bench.blind.snapshots import snapshot_workdir  # local import to avoid cycles

        t0 = time.perf_counter()
        workdir.mkdir(parents=True, exist_ok=True)

        traj_path = workdir.parent / "trajectory.jsonl"
        tool_path = workdir.parent / "tool_calls.jsonl"
        snapshots_dir = workdir.parent / "file_snapshots"

        has_kit = self.config.mcp_config_path is not None
        prompt = _build_prompt(spec, workdir, has_kit_mcp=has_kit)

        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.config.model,
            "--max-turns", str(self.config.max_turns),
        ]
        if self.config.mcp_config_path is not None:
            cmd += ["--mcp-config", str(self.config.mcp_config_path)]
        if self.config.dangerously_skip_permissions:
            cmd += ["--dangerously-skip-permissions"]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=workdir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                env={**os.environ, "CLAUDE_CODE_DISABLE_TELEMETRY": "1"},
            )
        except FileNotFoundError:
            return EmissionResult(
                emit_status="error",
                error="claude CLI not found on PATH",
                wall_clock_s=time.perf_counter() - t0,
                model=self.config.model, seed=seed,
            )

        input_tokens = output_tokens = cache_read = cache_creation = 0
        traj_lines: list[dict] = []
        tool_call_lines: list[dict] = []
        turn = 0
        last_turn_t = t0
        timed_out = False

        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                # Check wall-clock deadline
                if time.perf_counter() - t0 > self.config.timeout_s:
                    timed_out = True
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = ev.get("type", "")
                if msg_type not in ("assistant", "user"):
                    # system / result events — record minimal trace for auditability
                    if msg_type in ("system", "result"):
                        traj_lines.append({
                            "turn": None,
                            "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
                            "role": msg_type,
                            "content": ev,
                            "model": self.config.model,
                            "usage": {},
                            "latency_ms": 0,
                        })
                    continue
                turn += 1
                now = time.perf_counter()
                latency_ms = int((now - last_turn_t) * 1000)
                last_turn_t = now
                content = ev.get("message", {}).get("content", [])
                usage = ev.get("message", {}).get("usage", {}) or {}
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
                cache_read += int(usage.get("cache_read_input_tokens", 0) or 0)
                cache_creation += int(usage.get("cache_creation_input_tokens", 0) or 0)

                # Extract tool_use / tool_result blocks
                writes_fs = False
                for blk in content if isinstance(content, list) else []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_use":
                        tool_call_lines.append({
                            "turn": turn, "tool_use_id": blk.get("id"),
                            "name": blk.get("name"), "input": blk.get("input"),
                            "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
                        })
                        if blk.get("name") in {"Write", "Edit", "str_replace_based_edit_tool", "create_file"}:
                            writes_fs = True
                    elif blk.get("type") == "tool_result":
                        tool_call_lines.append({
                            "turn": turn, "tool_use_id": blk.get("tool_use_id"),
                            "name": "<tool_result>",
                            "result": _compact_result(blk.get("content")),
                            "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
                        })

                snapshot_ref = None
                if writes_fs:
                    try:
                        snap = snapshot_workdir(
                            workdir, snapshots_dir, label=f"turn_{turn:03d}",
                        )
                        snapshot_ref = snap.name
                    except Exception:  # noqa: BLE001
                        pass

                traj_lines.append({
                    "turn": turn,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
                    "role": ev.get("message", {}).get("role", msg_type),
                    "content": content,
                    "model": self.config.model,
                    "usage": usage,
                    "latency_ms": latency_ms,
                    "workdir_snapshot_after": snapshot_ref,
                })
        finally:
            if timed_out:
                _kill_process_group(proc)
            # Drain remaining output
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass

        stderr_tail = (proc.stderr.read() if proc.stderr else "")[-500:]
        returncode = proc.returncode if proc.returncode is not None else -1

        traj_path.write_text(
            "\n".join(json.dumps(l) for l in traj_lines) + ("\n" if traj_lines else "")
        )
        tool_path.write_text(
            "\n".join(json.dumps(l) for l in tool_call_lines) + ("\n" if tool_call_lines else "")
        )

        if timed_out:
            status = "timeout"
            error = f"wall-clock deadline {self.config.timeout_s}s exceeded"
        else:
            status = "success" if returncode == 0 else "error"
            error = "" if status == "success" else stderr_tail

        return EmissionResult(
            emit_status=status,
            error=error,
            trajectory_path=traj_path,
            tool_calls_path=tool_path,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read, cache_creation_tokens=cache_creation,
            wall_clock_s=time.perf_counter() - t0,
            model=self.config.model, temperature=self.config.temperature,
            seed=seed,
            extra={
                "adapter": self.name, "returncode": returncode,
                "turns": turn,
                "tool_call_count": len(tool_call_lines),
                "snapshots_taken": len(list(snapshots_dir.glob("turn_*.tar.*")))
                    if snapshots_dir.exists() else 0,
            },
        )


def _compact_result(content) -> str:  # noqa: ANN001
    """Compact a tool_result content block into a single string for the log."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:2000]
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    parts.append(_compact_result(b.get("content")))
        return "\n".join(parts)[:2000]
    try:
        return json.dumps(content)[:2000]
    except (TypeError, ValueError):
        return str(content)[:2000]


def _kill_process_group(proc: subprocess.Popen) -> None:
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM
            time.sleep(0.3)
            os.killpg(os.getpgid(proc.pid), 9)   # SIGKILL
        except (ProcessLookupError, PermissionError):
            pass
    else:
        try:
            proc.terminate()
            proc.kill()
        except OSError:
            pass


def _build_prompt(spec, workdir: Path, *, has_kit_mcp: bool) -> str:  # noqa: ANN001
    """Canonical prompt — same TASK both arms, kit arm additionally announces
    available MCP tools so the agent can discover them.

    Two-arm prompt discipline (PROTOCOL §2): the BRIEF text is byte-identical
    across conditions (identical `brief_sha256`). The only prompt difference
    is a kit-only paragraph telling the agent which MCP tools are available.
    Without this paragraph, empirically the kit agent ignores the MCP
    surface entirely (first live run on hard/01 showed 0 kit tool calls).

    Changing the prompt structure bumps PROTOCOL.md version — past runs
    are preserved verbatim and never re-scored under new wording.
    """
    kit_block = ""
    if has_kit_mcp:
        kit_block = """
---

YOU HAVE A SKILL. SKILL-001 (HuGR) is the LLM-equivalent of `rails new`
for FastAPI production backends. Six tier-1 "meta" tools are your
entry surface; the remaining 180 tools live in a catalog the meta
tools navigate for you. You are NOT expected to read a library guide —
you are an LLM and the skill speaks your language.

CANONICAL WORKFLOW (follow the breadcrumbs in every return's next_steps):

  TURN 1 — Orient. Your FIRST call is:

      mcp__fastapi-production__fastapi_meta_home()

    Returns the 10-domain landscape in ~1200 tokens. See the shape of
    the skill before scanning 180 tool descriptions.

  TURN 2 — Scaffold. Call:

      mcp__fastapi-production__fastapi_meta_scaffold(
          output_dir="<this cwd>",
          name="<slug>",
          models={"<Entity>": {"field": "type", ...}, ...},
          owner_models={"<Entity>": "user"},
          profile="full",
      )

    One call → ~40-60 files: FastAPI app, DB, alembic, auth, middleware,
    CRUD, observability, Docker, tests. The return's next_steps name
    the exact slice tools to call next given the brief.

  TURN 3+ — Capability slices. For each brief requirement not covered
    by default, follow the returned next_steps OR query the catalog:

      mcp__fastapi-production__fastapi_meta_search(
          query="exactly-once webhook",
          domain="realtime",
          k=5,
      )

    Returns top matching tool + synopsis + next_steps pointing at the
    exact invocation.

  TREE DISPATCHERS (preferred for domain work when one exists). If the
    brief mentions auth/identity, prefer the domain-level dispatcher
    over hunting for individual slices:

      mcp__fastapi-production__fastapi_auth(action="list")
        → returns the full auth tree (1 bundle + 15 slices + 8 primitives)
      mcp__fastapi-production__fastapi_auth(
          action="bundle", params={"output_dir": "<cwd>"}
      )
        → installs curated production auth stack in ONE call
      mcp__fastapi-production__fastapi_auth(
          action="primitive",
          params={"name": "SessionStore", "output_dir": "<cwd>"}
      )
        → copy ONE Lego block surgically into core/venous/auth/<Name>/

    The auth dispatcher indirects to 15 legacy auth slices under the
    hood — you do NOT need to call fastapi_add_oauth2 directly.
    Additional per-domain dispatchers ship incrementally; always check
    fastapi_meta_home() for which are live before hunting for
    individual add_* tools in a domain.

  TURN N — Verify. Before finishing, call:

      mcp__fastapi-production__fastapi_meta_audit()

    Runs the structural contract. Per-rule failures + fix breadcrumbs.
    Loop until green.

  DEEP DIVE (any turn). For a specific tool/primitive/recipe name:

      mcp__fastapi-production__fastapi_meta_describe(name="...")

    Returns the full schema, when-to-call, primitives composed.

EVERY tier-1 return carries a next_steps list — FOLLOW IT. That is the
skill talking back: it watched what you just did and names the tool to
call next. Don't call `Write` for files the scaffold should write;
don't grep when fastapi_meta_search returns the answer.

SPEC → PRIMITIVE QUICK-MAP (query the search tool for the full set):
  - Exactly-once / idempotency     → IdempotentConsumer + IdempotencyStore
  - Tamper-evident audit           → TamperEvidentAuditLog + AuditEvent
  - Transactional outbox           → TransactionalOutbox + UnitOfWork
  - Optimistic concurrency         → OptimisticConcurrency
  - Rate limit + priority shed     → RateLimiter + Bulkhead + LoadShedder
  - Session cache with TTL         → SessionCache
  - Sharded hot-key counter        → ShardedCounter
  - Causal reorder under partition → CausalReorderBuffer
  - Heterogeneous worker pool      → HeterogeneousWorkerPool

All primitives above are 10-tier gated upstream (compile / types /
concurrency / chaos / observability). Hand-rolling means the judge
catches edge cases we've already closed.

TLDR: Call `fastapi_meta_home()` FIRST. Let the skill drive.
"""
    return f"""You are a senior backend engineer. Produce a working FastAPI project that implements the requirements in the brief below. Write all files to the current working directory ({workdir}). The evaluator will boot your project with the boot command declared in the brief's metadata and run a sealed test suite you will NOT see.

Emit:
  - A pyproject.toml or requirements.txt declaring dependencies.
  - All Python source files under your chosen package layout.
  - Any SQL / alembic migration needed to bring the DB to a runnable state.
  - An executable entry point such that `{spec.boot_command}` starts a server listening on PORT that responds to GET {spec.health_probe} with 200.

Do not write tests — the evaluator has its own sealed test suite. Focus on production-grade code that meets every acceptance-criterion bullet.
{kit_block}
---

BRIEF (brief_sha256={spec.brief_sha256}):

{spec.brief}
"""
