"""Owner-bearing model discovery + per-model BOLA test rendering for add_bola_guard."""

from __future__ import annotations

import ast
from pathlib import Path

from adapt._base import load_template, render

OWNER_FIELD_CANDIDATES: tuple[str, ...] = ("user_id", "owner_id", "created_by_id")


def discover_owner_bearing_models(project: Path) -> list[dict]:
    """Find every ``app/models/*.py`` class that declares an owner FK column.

    Owner detection: the class body contains an annotated/assigned attribute
    whose name is one of ``user_id`` / ``owner_id`` / ``created_by_id``.
    """
    models_dir = project / "app" / "models"
    routes_dir = project / "app" / "api" / "routes"
    if not models_dir.is_dir():
        return []

    available_routes: set[str] = set()
    if routes_dir.is_dir():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)

    skip = {"base", "user", "mixins", "__init__", "tenant"}
    discovered: list[dict] = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name.lower() != stem:
                continue
            owner_field = _owner_field_for_class(node)
            if owner_field is None:
                continue
            discovered.append(
                {
                    "class_name": node.name,
                    "stem": stem,
                    "owner_field": owner_field,
                    "route_prefix": (
                        f"/api/v1/{stem}s" if stem in available_routes else f"/api/v1/{stem}s"
                    ),
                }
            )
    discovered.sort(key=lambda d: d["class_name"])
    return discovered


def _owner_field_for_class(cls: ast.ClassDef) -> str | None:
    for body_node in cls.body:
        target_name: str | None = None
        if isinstance(body_node, ast.AnnAssign) and isinstance(body_node.target, ast.Name):
            target_name = body_node.target.id
        elif isinstance(body_node, ast.Assign):
            for target in body_node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    break
        if target_name in OWNER_FIELD_CANDIDATES:
            return target_name
    return None


def render_generated_bola_tests(here: Path, owner_models: list[dict]) -> str:
    """Produce the full content for ``tests/test_bola_generated.py``."""
    header = load_template(here, "tests_header.py.tmpl").template
    if not owner_models:
        body = load_template(here, "tests_empty_body.py.tmpl").template
        return header + body
    blocks: list[str] = []
    for m in owner_models:
        blocks.append(
            render(
                here,
                "bola_block_per_model.py.tmpl",
                {
                    "cls": m["class_name"],
                    "stem": m["stem"],
                    "route": m["route_prefix"],
                    "owner_field": m["owner_field"],
                },
            )
        )
    return header + "\n".join(blocks)


def patch_config(config_file: Path):
    """Inject BOLA guard settings into ``app/core/config.py`` Settings class."""
    from adapt.contracts.config_patcher import patch_settings_fields

    # R5-O1-F1 (juror a96f3835e9f3a913e): BOLA_GUARD_STRICT_MODE used to
    # gate fail-closed-on-missing-resource-id behaviour and defaulted to
    # False (fail-OPEN).  The guard is now always fail-CLOSED on that
    # branch, so the field is no longer emitted.  BOLA_GUARD_ENABLED is
    # kept as the single kill-switch.
    return patch_settings_fields(
        config_file,
        fields=[
            ("BOLA_GUARD_ENABLED", "BOLA_GUARD_ENABLED: bool = True"),
        ],
    )
