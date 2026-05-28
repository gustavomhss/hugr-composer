"""Behavioural tests for state inspection.

Uses real on-disk staged primitives — the pool is the fixture. If the
pool changes, fixtures are regenerated deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.promotion.state import (
    SKILL_ROOT,
    _count_replace_me,
    _detect_concurrency,
    _detect_mutable_class_state,
    measure,
)


def test_count_replace_me_on_missing_dir(tmp_path: Path):
    assert _count_replace_me(tmp_path / "nope") == 0


def test_count_replace_me_on_empty_dir(tmp_path: Path):
    assert _count_replace_me(tmp_path) == 0


def test_count_replace_me_counts_across_subfiles(tmp_path: Path):
    (tmp_path / "a.py").write_text("# REPLACE_ME\nREPLACE_ME")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.json").write_text('"field": "REPLACE_ME"')
    assert _count_replace_me(tmp_path) == 3


def test_detect_concurrency_threading_import(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_text("import threading\nclass X: pass\n")
    assert _detect_concurrency(p) is True


def test_detect_concurrency_asyncio_from(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_text("from asyncio import Lock\nclass X: pass\n")
    assert _detect_concurrency(p) is True


def test_detect_concurrency_no_false_positive_on_name(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_text("threadings = 1\nclass X: pass\n")  # not an import
    assert _detect_concurrency(p) is False


def test_detect_mutable_class_state_true_on_self_assign(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_text("class X:\n    def __init__(self): self.a = 1\n    def set(self, v): self.a = v\n")
    assert _detect_mutable_class_state(p) is True


def test_detect_mutable_class_state_false_when_only_ctor_assigns(tmp_path: Path):
    p = tmp_path / "x.py"
    p.write_text("class X:\n    def __init__(self): self.a = 1\n    def get(self): return self.a\n")
    assert _detect_mutable_class_state(p) is False


@pytest.mark.skipif(
    not (SKILL_ROOT / "core" / "venous" / "_staging" / "api" / "DeprecationMiddleware").exists(),
    reason="DeprecationMiddleware staged primitive not present.",
)
def test_measure_real_primitive():
    """Smoke: measure a known staged primitive and assert plausible values."""
    p = SKILL_ROOT / "core" / "venous" / "_staging" / "api" / "DeprecationMiddleware"
    s = measure(p, "DeprecationMiddleware", "api", is_quarantined=False)
    assert s.name == "DeprecationMiddleware"
    assert s.test_file_present is True
    assert s.invariants_stubbed is True
    assert s.replace_me_count > 0
    assert s.loc > 0
