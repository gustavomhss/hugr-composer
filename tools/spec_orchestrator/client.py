"""OpenRouter client wrapper. Reads OPENROUTER_API_KEY from .env."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_REFERER = "https://github.com/humangr-labs/brains"
DEFAULT_TITLE = "HuGR SKILL-001 spec orchestrator"


@dataclass
class CompletionResult:
    content: str
    reasoning: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float
    elapsed_seconds: float
    raw: dict


def load_env_key() -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENROUTER_API_KEY missing from .env")


def call_deepseek(
    prompt: str,
    *,
    model: str = "deepseek/deepseek-r1",
    max_tokens: int = 32_000,
    temperature: float = 0.2,
    timeout: int = 600,
    system_prompt: str | None = None,
) -> CompletionResult:
    """
    Call OpenRouter chat completions endpoint.

    Returns CompletionResult with content, reasoning trace, token counts, and cost.
    Raises on HTTP errors with the response body included.
    """
    key = os.environ.get("OPENROUTER_API_KEY") or load_env_key()

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": DEFAULT_REFERER,
            "X-Title": DEFAULT_TITLE,
        },
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
    elapsed = time.monotonic() - t0

    msg = data["choices"][0]["message"]
    usage = data.get("usage", {}) or {}
    completion_details = usage.get("completion_tokens_details", {}) or {}

    return CompletionResult(
        content=msg.get("content", "") or "",
        reasoning=msg.get("reasoning"),
        model=data.get("model", model),
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        reasoning_tokens=int(completion_details.get("reasoning_tokens", 0) or 0),
        cost_usd=float(usage.get("cost", 0.0) or 0.0),
        elapsed_seconds=elapsed,
        raw=data,
    )
