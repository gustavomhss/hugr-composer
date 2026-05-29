"""Benchmark harness — CONTRACT §B3."""

from engine.bench.rubric import DimensionScore, SpecScore, score_spec
from engine.bench.runner import AgentAdapter, BenchmarkRunner, RunResult

__all__ = [
    "BenchmarkRunner",
    "DimensionScore",
    "AgentAdapter",
    "RunResult",
    "SpecScore",
    "score_spec",
]
