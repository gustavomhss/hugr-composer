"""Workdir snapshots — tar.zst of the emitted directory at a given moment.

The full per-turn snapshot scheme promised in PROTOCOL §5 requires a live
hook from the agent into the harness (so we can snapshot AFTER each
tool-use turn that writes to disk). That hook is not yet wired for the
Claude CLI adapter (the CLI returns on completion, not mid-run). For v1
we emit ONE final snapshot per attempt: `file_snapshots/final.tar.zst`.

The module is structured so per-turn snapshots can be enabled by feeding
a `turn_index` into `snapshot_workdir()` once the live hook lands.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

try:
    import zstandard as zstd  # noqa: F401
    _HAS_ZSTD = True
except ImportError:
    _HAS_ZSTD = False


def snapshot_workdir(workdir: Path, out_dir: Path, label: str = "final") -> Path:
    """Compress `workdir` into `out_dir/<label>.tar.zst` (or .tar.gz fallback).

    Returns the path to the archive. The archive preserves the workdir
    layout so the emitted code can be inspected directly via `tar`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if _HAS_ZSTD:
        import zstandard
        archive = out_dir / f"{label}.tar.zst"
        cctx = zstandard.ZstdCompressor(level=9)
        with archive.open("wb") as fh, cctx.stream_writer(fh) as compressor:
            with tarfile.open(mode="w|", fileobj=compressor) as tar:
                if workdir.exists():
                    tar.add(str(workdir), arcname=workdir.name,
                            filter=_reject_cache)
    else:
        archive = out_dir / f"{label}.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
            if workdir.exists():
                tar.add(str(workdir), arcname=workdir.name, filter=_reject_cache)
    return archive


def _reject_cache(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Skip __pycache__ / .pytest_cache / .venv — non-artefactual."""
    skip = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
            ".venv", "node_modules", ".DS_Store")
    if any(s in tarinfo.name.split("/") for s in skip):
        return None
    return tarinfo
