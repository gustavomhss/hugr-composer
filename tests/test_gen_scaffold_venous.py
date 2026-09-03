"""Tests for generator: scaffold_venous."""

import pytest
import tempfile
import shutil
import ast
from pathlib import Path


PRIMITIVE_NAME = "core.venous.resiliency.GracefulShutdown"


def test_generator_scaffold_venous_creates_files():
    """Generator must run successfully and write files for a valid primitive."""
    from generators.scaffold_venous import copy_primitive, CopyResult

    output_dir = tempfile.mkdtemp()
    try:
        result = copy_primitive(output_dir, PRIMITIVE_NAME)
        assert isinstance(result, CopyResult)
        assert result.already_present is False
        assert isinstance(result.files_written, list)
        assert len(result.files_written) > 0, "Generator created no files"
    finally:
        shutil.rmtree(output_dir)


def test_generator_scaffold_venous_idempotent():
    """Running twice must be safe — second run is no-op (already_present)."""
    from generators.scaffold_venous import copy_primitive, CopyResult

    output_dir = tempfile.mkdtemp()
    try:
        result1 = copy_primitive(output_dir, PRIMITIVE_NAME)
        result2 = copy_primitive(output_dir, PRIMITIVE_NAME)
        assert isinstance(result2, CopyResult)
        assert result2.already_present is True
        assert result2.files_written == []
    finally:
        shutil.rmtree(output_dir)


def test_generator_scaffold_venous_valid_python():
    """Generated .py files must pass ast.parse."""
    from generators.scaffold_venous import copy_primitive

    output_dir = tempfile.mkdtemp()
    try:
        result = copy_primitive(output_dir, PRIMITIVE_NAME)
        for fpath in result.files_written:
            if fpath.endswith(".py"):
                source = Path(fpath).read_text()
                ast.parse(source)
    finally:
        shutil.rmtree(output_dir)


def test_generator_scaffold_venous_files_exist():
    """All files_written must exist on disk after generation."""
    from generators.scaffold_venous import copy_primitive

    output_dir = tempfile.mkdtemp()
    try:
        result = copy_primitive(output_dir, PRIMITIVE_NAME)
        entry = Path(result.destination) / "GracefulShutdown.py"
        assert entry.exists(), f"Entry-point file missing: {entry}"
        for fpath in result.files_written:
            assert Path(fpath).exists(), f"File not found: {fpath}"
    finally:
        shutil.rmtree(output_dir)