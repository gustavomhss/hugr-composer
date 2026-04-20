"""
LLM transport via the local `claude` CLI.

Zero API-key management: reuses the logged-in CLI auth. Async subprocess
invocation with bounded concurrency and a typed response envelope.

Environment requirements:
- `claude` CLI installed, authenticated (`claude /login`).
- Python 3.12+.

Contract (every caller MUST obey):
- Every `llm_call` returns a typed `LLMResponse` or raises `LLMCallFailed`.
- `LLMCallFailed` carries the full stderr, exit code, and invoked argv.
- Concurrency ceiling is enforced by `TransportPool`, never by the caller.
- Prompts MUST NOT embed credentials or API keys — hard rejection.

Usage:
    pool = TransportPool(max_concurrent=8)
    res = await pool.call(prompt, model="claude-sonnet-4-6", system="...")
    res.text             # str
    res.raw              # dict from claude --output-format json
    res.duration_ms
    res.cost_estimate_usd
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any

_CREDENTIAL_SIGNATURES = (
    r"sk-ant-[A-Za-z0-9_-]{20,}",       # Anthropic
    r"sk-[A-Za-z0-9_-]{20,}",           # OpenAI legacy / generic
    r"AKIA[0-9A-Z]{16}",                # AWS access key
    r"AIza[0-9A-Za-z_-]{35}",           # Google API
    r"ghp_[A-Za-z0-9]{36}",             # GitHub personal token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack
)
_CREDENTIAL_RE = re.compile("|".join(_CREDENTIAL_SIGNATURES))


class LLMCallFailed(RuntimeError):
    """Raised when the CLI subprocess exits non-zero or the response is malformed."""

    def __init__(self, message: str, *, argv: list[str], exit_code: int, stderr: str) -> None:
        super().__init__(message)
        self.argv = argv
        self.exit_code = exit_code
        self.stderr = stderr

    def __repr__(self) -> str:
        return (
            f"LLMCallFailed(exit_code={self.exit_code}, argv={self.argv!r}, "
            f"stderr={self.stderr[:300]!r})"
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: dict[str, Any]
    model: str
    duration_ms: int
    cost_estimate_usd: float

    def as_json(self) -> Any:
        """Parse `.text` as JSON. Raises `json.JSONDecodeError` if not valid JSON."""
        return json.loads(self.text)


class TransportPool:
    """Bounded concurrency wrapper for `claude` subprocess invocations."""

    # Rough cost anchors per 1K output tokens (assume ≤ 2K output per call).
    # These are over-estimates — the real per-call cost is reported by the
    # CLI when available, otherwise we fall back to this heuristic so the
    # delivery contract's cost cap still biases toward cheap models.
    _COST_HINT_PER_CALL: dict[str, float] = {
        "claude-opus-4-7": 0.30,
        "claude-sonnet-4-6": 0.05,
        "claude-haiku-4-5": 0.01,
    }

    def __init__(self, *, max_concurrent: int = 8, cli: str = "claude") -> None:
        if max_concurrent < 1 or max_concurrent > 32:
            raise ValueError(f"max_concurrent must be 1..32, got {max_concurrent}")
        self._sem = asyncio.Semaphore(max_concurrent)
        self._cli = cli
        if shutil.which(cli) is None:
            raise RuntimeError(
                f"`{cli}` CLI not found on PATH. Install Claude Code and `{cli} /login` first."
            )

    async def call(
        self,
        prompt: str,
        *,
        model: str = "claude-sonnet-4-6",
        system: str | None = None,
        max_turns: int = 1,
        timeout_s: float = 180.0,
    ) -> LLMResponse:
        self._reject_credentials(prompt)
        if system is not None:
            self._reject_credentials(system)

        argv: list[str] = [
            self._cli,
            "-p", prompt,
            "--output-format", "json",
            "--model", model,
            "--max-turns", str(max_turns),
            "--permission-mode", "plan",  # read-only; builder does not let the judge model mutate files
        ]
        if system is not None:
            argv.extend(["--append-system-prompt", system])

        async with self._sem:
            started = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise LLMCallFailed(
                    f"CLI call timed out after {timeout_s}s.",
                    argv=argv, exit_code=-1, stderr=f"timeout={timeout_s}s",
                )

            duration_ms = int((time.monotonic() - started) * 1000)
            if proc.returncode != 0:
                raise LLMCallFailed(
                    f"CLI exited with code {proc.returncode}.",
                    argv=argv, exit_code=proc.returncode or -1,
                    stderr=stderr.decode(errors="replace"),
                )

            try:
                raw = json.loads(stdout.decode())
            except json.JSONDecodeError as e:
                raise LLMCallFailed(
                    f"CLI stdout was not JSON: {e}",
                    argv=argv, exit_code=0, stderr=stdout.decode()[:2000],
                )

        text = raw.get("result", "")
        if not isinstance(text, str):
            raise LLMCallFailed(
                "CLI JSON missing str `result` field.",
                argv=argv, exit_code=0, stderr=str(raw)[:2000],
            )

        cost = self._extract_cost(raw, model)
        return LLMResponse(
            text=text,
            raw=raw,
            model=model,
            duration_ms=duration_ms,
            cost_estimate_usd=cost,
        )

    @staticmethod
    def _reject_credentials(blob: str) -> None:
        m = _CREDENTIAL_RE.search(blob)
        if m:
            # Redact before raising so the logs don't echo the secret.
            preview = blob[: m.start()][-40:] + "<REDACTED>" + blob[m.end():][:40]
            raise ValueError(
                f"Prompt looks like it contains a credential. Refusing. Preview: {preview!r}"
            )

    @classmethod
    def _extract_cost(cls, raw: dict[str, Any], model: str) -> float:
        # The Claude CLI may or may not include `total_cost_usd` depending on version.
        reported = raw.get("total_cost_usd") or raw.get("cost_usd")
        if isinstance(reported, (int, float)):
            return float(reported)
        return cls._COST_HINT_PER_CALL.get(model, 0.05)


# ---------------------------------------------------------------------------
# Convenience: fan-out across models (used by T6 ensemble)
# ---------------------------------------------------------------------------
async def fan_out(
    pool: TransportPool,
    prompt: str,
    models: list[str],
    *,
    system: str | None = None,
    timeout_s: float = 180.0,
) -> list[tuple[str, LLMResponse | LLMCallFailed]]:
    """Run the same prompt against multiple models concurrently.

    Returns a list of `(model, response_or_failure)` tuples — failures do NOT
    propagate; the caller decides whether a partial ensemble is acceptable.
    """
    async def one(m: str) -> tuple[str, LLMResponse | LLMCallFailed]:
        try:
            res = await pool.call(prompt, model=m, system=system, max_turns=5, timeout_s=timeout_s)
            return (m, res)
        except LLMCallFailed as e:
            return (m, e)

    return await asyncio.gather(*(one(m) for m in models))
