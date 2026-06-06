"""LLM agent backend — input/output guardrails + per-tenant token budget."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field


INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all |the )?previous instructions", re.I),
    re.compile(r"disregard .* instructions", re.I),
    re.compile(r"you are now DAN", re.I),
)


SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
)


class PromptInjectionFilter:
    """Mirror of `PromptInjectionFilter` primitive."""

    def detects(self, prompt: str) -> str | None:
        for p in INJECTION_PATTERNS:
            if p.search(prompt):
                return p.pattern
        return None


class InputGuardrail:
    def __init__(self, detector: PromptInjectionFilter) -> None:
        self._detector = detector
        self.blocked_log: list[tuple[str, str]] = []

    def check(self, tenant: str, prompt: str) -> bool:
        match = self._detector.detects(prompt)
        if match is not None:
            self.blocked_log.append((tenant, match))
            return False
        return True


class OutputGuardrail:
    """Redacts secret-shaped substrings from streamed output."""

    REDACTION = "[REDACTED]"

    def redact(self, chunk: str) -> str:
        out = chunk
        for p in SECRET_PATTERNS:
            out = p.sub(self.REDACTION, out)
        return out


@dataclass
class Usage:
    tokens: int = 0


class CostTracker:
    """Per-tenant token accumulator with a daily cutoff at 1.10× budget."""

    def __init__(self, *, tokens_per_day: int, cutoff_ratio: float = 1.10) -> None:
        self.tokens_per_day = tokens_per_day
        self.cutoff_ratio = cutoff_ratio
        self._usage: dict[str, Usage] = {}
        self._lock = threading.Lock()

    def record(self, tenant: str, tokens: int) -> None:
        with self._lock:
            u = self._usage.setdefault(tenant, Usage())
            u.tokens += tokens

    def over_budget(self, tenant: str) -> bool:
        with self._lock:
            u = self._usage.get(tenant, Usage())
            return u.tokens > self.tokens_per_day * self.cutoff_ratio

    def total(self, tenant: str) -> int:
        with self._lock:
            return self._usage.get(tenant, Usage()).tokens


@dataclass
class InvocationMetric:
    ttft_s: float
    total_s: float
    input_tokens: int
    output_tokens: int
    model: str
    cost_estimate: float


class AgentService:
    def __init__(self, *, tokens_per_day: int = 1000) -> None:
        self._guard_in = InputGuardrail(PromptInjectionFilter())
        self._guard_out = OutputGuardrail()
        self._tracker = CostTracker(tokens_per_day=tokens_per_day)
        self.metrics: list[InvocationMetric] = []

    def invoke(
        self, *, tenant: str, agent: str, prompt: str,
        chunks: list[str], now_start: float, now_first_chunk: float,
        now_end: float, input_tokens: int, output_tokens: int,
        model: str = "gpt-dummy", cost_per_1k: float = 0.01,
    ) -> tuple[int, list[str]]:
        if self._tracker.over_budget(tenant):
            return 402, []
        if not self._guard_in.check(tenant, prompt):
            return 400, []
        redacted = [self._guard_out.redact(c) for c in chunks]
        self._tracker.record(tenant, input_tokens + output_tokens)
        self.metrics.append(InvocationMetric(
            ttft_s=now_first_chunk - now_start,
            total_s=now_end - now_start,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            cost_estimate=(input_tokens + output_tokens) / 1000 * cost_per_1k,
        ))
        return 200, redacted

    @property
    def blocked_log(self) -> list[tuple[str, str]]:
        return self._guard_in.blocked_log

    @property
    def tracker(self) -> CostTracker:
        return self._tracker
