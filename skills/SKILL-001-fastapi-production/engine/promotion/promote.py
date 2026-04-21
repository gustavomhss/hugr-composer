"""Execute an approved promotion verdict — atomic, rollback on failure.

Usage:
    python -m engine.promotion.promote --from-ledger NAME [--dry-run]
    python -m engine.promotion.promote --delete NAME [--dry-run]

Invariants:
    - Refuses to promote unless the ledger entry says PROMOTE_FULL /
      PROMOTE_LITE AND has zero blockers.
    - PROMOTE_LITE requires the ratification line "§B1.7 ratified"
      in CONTRACT.md §E. Without it, the executor refuses (§A12 intact).
    - Every action is fully reversible: a pre-flight copy of the
      affected trees is written to a temp dir; on any failure, the
      original state is restored.
    - Contract must stay 33/33 green. A post-flight contract_check
      failure triggers automatic rollback.
    - Every promotion is one atomic commit — never batched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.promotion.schemas import Ledger, LedgerEntry, Verdict
from engine.promotion.state import SKILL_ROOT

_LEDGER_PATH = SKILL_ROOT / "engine" / "promotion" / "ledger.json"
_REGISTRY_PATH = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
_CONTRACT_PATH = SKILL_ROOT.parent.parent / "CONTRACT.md"


@dataclass
class PromotionPlan:
    """Pre-computed plan for one promotion — printed before any write."""

    entry: LedgerEntry
    source_dir: Path
    target_dir: Path
    registry_entry: dict
    is_lite: bool

    def describe(self) -> str:
        bits = [
            f"Primitive: {self.entry.primitive}",
            f"Namespace: {self.entry.namespace}",
            f"Tier: {'lite' if self.is_lite else 'full'}",
            f"Source:  {self.source_dir.relative_to(SKILL_ROOT)}",
            f"Target:  {self.target_dir.relative_to(SKILL_ROOT)}",
            f"Signals: {len(self.entry.signals)}",
            "Rationale: " + self.entry.rationale,
        ]
        return "\n  ".join(bits)


def _load_ledger() -> Ledger:
    if not _LEDGER_PATH.exists():
        raise SystemExit(
            "ledger.json not found — run `python -m engine.promotion.classify` first."
        )
    return Ledger.model_validate(json.loads(_LEDGER_PATH.read_text(encoding="utf-8")))


def _lite_ratified() -> bool:
    """True iff CONTRACT.md §E carries a ratification of §B1.7 / §A12 amendment."""
    if not _CONTRACT_PATH.exists():
        return False
    text = _CONTRACT_PATH.read_text(encoding="utf-8")
    return "§B1.7 ratified" in text or "tier-lite ratified" in text


def _find_source(entry: LedgerEntry) -> Path:
    base = SKILL_ROOT / "core" / "venous" / "_extracted"
    if entry.state.is_quarantined:
        return base / "_quarantine" / entry.primitive
    return base / entry.namespace / entry.primitive


def _build_registry_entry(entry: LedgerEntry, is_lite: bool) -> dict:
    """Derive the YAML entry from the primitive's .md and contract.json.

    Deterministic — no invention. The `purpose` field uses the first line
    of the primitive's .md (or the docstring). compose_with is seeded
    with [] to be filled when the primitive enters real recipes.
    """
    source = _find_source(entry)
    md = source / f"{entry.primitive}.md"
    first_para = ""
    if md.exists():
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
            # First non-heading, non-empty line.
            for ln in lines:
                ln_s = ln.strip()
                if ln_s and not ln_s.startswith("#"):
                    first_para = ln_s[:120]
                    break
        except OSError:
            pass
    return {
        "name": entry.primitive,
        "namespace": entry.namespace,
        "concern": entry.namespace,
        "purpose": first_para or f"{entry.primitive} (purpose TBD).",
        "compose_with": [],
        "tier": "lite" if is_lite else "full",
    }


def plan(name: str) -> PromotionPlan:
    """Load ledger, validate, and return a concrete promotion plan."""
    ledger = _load_ledger()
    matches = [e for e in ledger.entries if e.primitive == name]
    if not matches:
        raise SystemExit(f"No ledger entry for primitive `{name}`.")
    entry = matches[0]

    if entry.verdict not in (
        Verdict.PROMOTE_AS_ADAPTER,
        Verdict.PROMOTE_AS_PRIMITIVE,
    ):
        raise SystemExit(
            f"Ledger verdict for `{name}` is {entry.verdict.value}, not a "
            "promotion. Executor refuses (§A12 discipline)."
        )

    if entry.blockers:
        joined = "\n    - ".join(entry.blockers)
        raise SystemExit(
            f"Ledger entry for `{name}` has blockers:\n    - {joined}\n"
            "Resolve blockers and re-run the classifier before promoting."
        )

    is_adapter = entry.verdict == Verdict.PROMOTE_AS_ADAPTER
    is_lite = entry.verdict == Verdict.PROMOTE_AS_PRIMITIVE and entry.tier == "lite"

    if is_lite and not _lite_ratified():
        raise SystemExit(
            f"Refusing to promote `{name}` at lite tier: §B1.7 not ratified "
            "in CONTRACT.md §E. Add a ratification block first."
        )

    source = _find_source(entry)
    if not source.exists():
        raise SystemExit(f"Source tree missing: {source}")

    if is_adapter:
        if not entry.promotion_target:
            raise SystemExit(
                f"PROMOTE_AS_ADAPTER entry for `{name}` is missing "
                "promotion_target. Re-run classifier."
            )
        target = SKILL_ROOT / entry.promotion_target
    else:
        target = SKILL_ROOT / "core" / "venous" / entry.namespace / entry.primitive

    if target.exists():
        raise SystemExit(
            f"Target already exists: {target.relative_to(SKILL_ROOT)}. "
            "Refusing to overwrite — resolve manually."
        )

    reg_entry = (
        {} if is_adapter else _build_registry_entry(entry, is_lite)
    )
    return PromotionPlan(
        entry=entry,
        source_dir=source,
        target_dir=target,
        registry_entry=reg_entry,
        is_lite=is_lite,
    )


def _backup(path: Path, backup_root: Path) -> Path | None:
    """Copy `path` under `backup_root`, preserving relative layout."""
    if not path.exists():
        return None
    rel = path.relative_to(SKILL_ROOT) if path.is_relative_to(SKILL_ROOT) else Path(path.name)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    return dest


def _restore(path: Path, backup_root: Path) -> None:
    """Inverse of _backup — restore original state from backup dir."""
    rel = path.relative_to(SKILL_ROOT) if path.is_relative_to(SKILL_ROOT) else Path(path.name)
    src = backup_root / rel
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    if src.exists():
        if src.is_dir():
            shutil.copytree(src, path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, path)


def _rebuild_catalog_and_audit() -> tuple[bool, str]:
    """Rebuild catalog + run contract_check. Returns (ok, message)."""
    import subprocess

    # Rebuild catalog.
    r1 = subprocess.run(
        [sys.executable, "-m", "engine.index.manifest", "build"],
        cwd=str(SKILL_ROOT),
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SKILL_ROOT), **_env()},
    )
    if r1.returncode != 0:
        return False, f"manifest build failed:\n{r1.stderr}"

    r2 = subprocess.run(
        [sys.executable, "-m", "engine.audit.contract_check"],
        cwd=str(SKILL_ROOT),
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SKILL_ROOT), **_env()},
    )
    if "ALL GREEN" not in r2.stdout:
        return False, f"contract_check failed:\n{r2.stdout}\n{r2.stderr}"
    return True, "catalog rebuilt; contract 33/33 green."


def _env() -> dict:
    import os

    return {k: v for k, v in os.environ.items()}


def _execute_adapter(p: PromotionPlan, backup_root: Path) -> str:
    """Copy `<Name>.py` → `<Motor>Adapter.py`. Non-destructive to staged tree."""
    source_py = p.source_dir / f"{p.entry.primitive}.py"
    if not source_py.exists():
        raise RuntimeError(f"Adapter source missing: {source_py}")
    p.target_dir.parent.mkdir(parents=True, exist_ok=True)
    # Backup target parent (not source — adapter promotion is non-destructive).
    _backup(p.target_dir.parent, backup_root)
    shutil.copy2(source_py, p.target_dir)
    return (
        f"Adapter promoted: {source_py.relative_to(SKILL_ROOT)} → "
        f"{p.target_dir.relative_to(SKILL_ROOT)}"
    )


def _execute_primitive(p: PromotionPlan, backup_root: Path) -> str:
    """Move staged tree into registered, update registry YAML."""
    _backup(p.source_dir, backup_root)
    _backup(p.target_dir.parent, backup_root)
    _backup(_REGISTRY_PATH, backup_root)

    p.target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(p.source_dir, p.target_dir)
    for meta in ("_origin.json", "_provenance.json", "_quarantined.json"):
        m = p.target_dir / meta
        if m.exists():
            m.unlink()

    reg_data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    existing_names = {entry["name"] for entry in reg_data["primitives"]}
    if p.entry.primitive in existing_names:
        raise RuntimeError(
            f"Registry already contains `{p.entry.primitive}` — abort."
        )
    reg_data["primitives"].append(p.registry_entry)
    reg_data["primitives"].sort(key=lambda e: (e.get("namespace", ""), e["name"]))
    _REGISTRY_PATH.write_text(
        yaml.dump(reg_data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    shutil.rmtree(p.source_dir)
    return f"Primitive promoted: {p.entry.primitive} → {p.target_dir.relative_to(SKILL_ROOT)}"


def execute(name: str, *, dry_run: bool = False) -> int:
    """Execute the promotion — with automatic rollback on any failure."""
    p = plan(name)
    print("Promotion plan:")
    print("  " + p.describe())
    if dry_run:
        print("\n[dry-run] no files written.")
        return 0

    backup_root = Path(tempfile.mkdtemp(prefix="promotion_backup_"))
    print(f"\nBackup root: {backup_root}")
    is_adapter = p.entry.verdict == Verdict.PROMOTE_AS_ADAPTER
    try:
        if is_adapter:
            msg = _execute_adapter(p, backup_root)
        else:
            msg = _execute_primitive(p, backup_root)

        ok, audit_msg = _rebuild_catalog_and_audit()
        if not ok:
            raise RuntimeError(audit_msg)

        print("\n" + audit_msg)
        print(msg)
        shutil.rmtree(backup_root, ignore_errors=True)
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"\n[ROLLBACK] {exc}", file=sys.stderr)
        _restore(p.source_dir, backup_root)
        _restore(p.target_dir, backup_root)
        _restore(p.target_dir.parent, backup_root)
        _restore(_REGISTRY_PATH, backup_root)
        print(f"[ROLLBACK] state restored from {backup_root}", file=sys.stderr)
        return 1


def execute_delete(name: str, *, dry_run: bool = False) -> int:
    """Remove a staged primitive marked REDUNDANT in the ledger.

    REDUNDANT deletion is explicit opt-in — default stance is leave in place.
    """
    ledger = _load_ledger()
    matches = [e for e in ledger.entries if e.primitive == name]
    if not matches:
        raise SystemExit(f"No ledger entry for primitive `{name}`.")
    entry = matches[0]
    if entry.verdict != Verdict.REDUNDANT:
        raise SystemExit(
            f"Ledger verdict for `{name}` is {entry.verdict.value}, not redundant. "
            "Delete is only offered for REDUNDANT entries."
        )
    source = _find_source(entry)
    if not source.exists():
        raise SystemExit(f"Source tree missing: {source}")

    print(f"Delete plan: {source.relative_to(SKILL_ROOT)}")
    print(f"  reason: {entry.delete_reason}")
    if dry_run:
        print("[dry-run] no files removed.")
        return 0

    backup_root = Path(tempfile.mkdtemp(prefix="promotion_delete_backup_"))
    _backup(source, backup_root)
    try:
        shutil.rmtree(source)
        ok, msg = _rebuild_catalog_and_audit()
        if not ok:
            raise RuntimeError(msg)
        print(msg)
        print(f"Deleted: {source.relative_to(SKILL_ROOT)}")
        shutil.rmtree(backup_root, ignore_errors=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ROLLBACK] {exc}", file=sys.stderr)
        _restore(source, backup_root)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Execute an approved ledger entry (promote or delete)."
    )
    ap.add_argument("--from-ledger", metavar="NAME", help="Promote primitive NAME.")
    ap.add_argument("--delete", metavar="NAME", help="Delete staged primitive NAME.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.from_ledger and args.delete:
        ap.error("Specify either --from-ledger or --delete, not both.")
    if not args.from_ledger and not args.delete:
        ap.error("Specify one of --from-ledger or --delete.")

    if args.from_ledger:
        return execute(args.from_ledger, dry_run=args.dry_run)
    return execute_delete(args.delete, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
