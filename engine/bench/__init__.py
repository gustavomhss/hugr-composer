"""Benchmark harness — CONTRACT §B3."""

from engine.bench.rubric import DimensionScore, SpecScore, score_spec
from engine.bench.runner import BenchmarkRunner, MaestroAdapter, RunResult

__all__ = [
    "BenchmarkRunner",
    "DimensionScore",
    "MaestroAdapter",
    "RunResult",
    "SpecScore",
    "score_spec",
]
