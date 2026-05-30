"""Migration chain helper — used by all adapt tools that generate Alembic migrations.

Every adapt tool that creates a migration file must call ``find_migration_head()``
to discover the current HEAD revision rather than hard-coding a fallback or using
``None``.  Using ``None`` (root) or a hard-coded revision creates a multi-root fork
when several tools run in sequence, which breaks ``alembic upgrade head``.

Example::

    from adapt.contracts.migration_helper import find_migration_head

    down_rev = find_migration_head(versions_dir) or "0001_initial"
    # Then embed down_rev in the generated migration file.

R6-O4-A1 hardening
------------------
Historically this helper returned ``None`` when the versions directory was
empty or missing, and callers fell back to the string ``"0001_initial"`` —
which only worked if a migration with that revision actually existed on
disk.  The scaffold did not always emit one, so ``alembic upgrade head``
would fail with ``Can't locate revision identified by '0001_initial'``.

The helper now raises :class:`MigrationChainError` when the versions
directory is missing or contains no parseable revisions.  This forces the
scaffold guarantee (``alembic/versions/0001_initial.py`` is emitted by
``generators.database.alembic.generate_alembic``) to hold loudly instead
of silently producing a broken migration chain.
"""

from __future__ import annotations

import re
from pathlib import Path


class MigrationChainError(RuntimeError):
    """Raised when the Alembic chain root is missing or unparseable.

    Callers should treat this as a scaffold-integrity failure: the project
    was generated without the no-op ``0001_initial`` baseline that every
    extend tool implicitly relies on.  Re-run the scaffold (or recover the
    file) before retrying the extend tool.
    """


# Matches:  down_revision = "foo"  or  down_revision = None  (with optional
# type hint of any complexity — e.g. ``Union[str, None]`` or ``str | None``).
# ``[^=]+?`` (non-greedy) captures the annotation up to the assignment ``=``,
# so we tolerate spaces inside the annotation that ``\S+`` would have rejected.
_DOWN_REV_RE = re.compile(
    r'^down_revision\s*(?::\s*[^=]+?)?\s*=\s*(?:["\']([^"\']*)["\']|(None))',
    re.MULTILINE,
)
_REVISION_RE = re.compile(
    r'^revision\s*(?::\s*[^=]+?)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)


def find_migration_head(alembic_dir: Path) -> str | None:
    """Find the current HEAD revision in the Alembic migration chain.

    Parses every ``.py`` file in *alembic_dir*, builds a ``revision →
    down_revision`` map, and returns the revision that no other migration
    points to as its parent.  That is the current chain HEAD — the revision
    that a new migration should chain from.

    Args:
        alembic_dir: Path to the ``alembic/versions/`` directory.

    Returns:
        The HEAD revision string (e.g. ``"0014_add_audit_log"``).

    Raises:
        MigrationChainError: when *alembic_dir* does not exist, is not a
            directory, or contains no parseable migration files.  This is
            a scaffold-integrity failure (see module docstring) — the
            ``0001_initial`` chain root must always exist on disk.
    """
    if not alembic_dir.is_dir():
        raise MigrationChainError(
            f"Alembic versions directory not found: {alembic_dir}. "
            "The scaffold must emit alembic/versions/0001_initial.py — "
            "re-run generators.database.alembic.generate_alembic before "
            "applying extend tools."
        )

    # Parse every migration file
    revision_to_down: dict[str, str | None] = {}
    for path in sorted(alembic_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rev_m = _REVISION_RE.search(src)
        if not rev_m:
            continue
        revision = rev_m.group(1)

        down_m = _DOWN_REV_RE.search(src)
        if down_m:
            # group(1) = quoted string value, group(2) = literal None
            down_rev: str | None = down_m.group(1) if down_m.group(1) is not None else None
        else:
            down_rev = None

        revision_to_down[revision] = down_rev

    if not revision_to_down:
        raise MigrationChainError(
            f"No parseable migration files in {alembic_dir}. "
            "The scaffold must emit alembic/versions/0001_initial.py — "
            "re-run generators.database.alembic.generate_alembic before "
            "applying extend tools."
        )

    # Collect all revisions that ARE referenced as a down_revision
    referenced_as_parent: set[str] = set()
    for down in revision_to_down.values():
        if down is not None:
            referenced_as_parent.add(down)

    # HEAD = revision that is NOT someone else's down_revision
    heads = [rev for rev in revision_to_down if rev not in referenced_as_parent]

    if len(heads) == 1:
        return heads[0]

    if len(heads) > 1:
        # Fork already exists — return the lexicographically last one as a
        # best-effort heuristic so the new migration doesn't make it worse.
        return sorted(heads)[-1]

    # All revisions are referenced — circular chain?  Fall back to last file stem.
    last = sorted(alembic_dir.glob("*.py"))
    return last[-1].stem if last else None
