"""Runtime framework-free probe — import every primitive with web frameworks BLOCKED.

Codex v7 + Opus HIGH-M2: the static `framework_free_probe.py` only catches
DIRECT imports. A primitive that imports `pydantic` which transitively
loads `starlette` would slip through. This probe is the runtime
counterpart: install a meta_path finder that REJECTS any attempt to
import a web framework at runtime, then import each of 124 primitives
and report which (if any) trigger the rejection.

This is the strong form of PRODUCT §A2 / §6.2 "primitives are
framework-free motors" — not just "they don't import fastapi at the
top of their file" but "they boot to a usable state without fastapi
being importable."

Frameworks blocked at import:
    fastapi, starlette, uvicorn, flask, django, tornado, sanic,
    bottle, aiohttp, quart, falcon, hypercorn

Output JSON:
    evidence/deterministic/framework_free_runtime.json
    {
      "_meta": {...},
      "primitives_scanned": 124,
      "frameworks_blocked": [...12...],
      "per_primitive": [{ns, name, import_ok, blocked_framework, error}],
      "summary": {imported_clean, blocked, errored, passed}
    }

Exit 0 iff every primitive imports cleanly under the framework block.

Note: a primitive that fails import for OTHER reasons (e.g., missing
optional deps like httpx) is reported under `errored`, not `blocked`.
The "passed" criterion is `blocked == 0`; non-framework errors are
informative but tolerated (the primitive may simply require an
optional dep at runtime; that's not a framework-free violation).
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "SKILL-001-fastapi-production"

FRAMEWORKS = (
    "fastapi", "starlette", "uvicorn", "flask", "django", "tornado",
    "sanic", "bottle", "aiohttp", "quart", "falcon", "hypercorn",
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _build_runner_script() -> str:
    """Return a Python script that blocks frameworks then probes every primitive."""
    # Using single-quoted regular string + concat to avoid quoting hell.
    return (
        "import sys, importlib, json, pathlib\n"
        f"FRAMEWORKS = {FRAMEWORKS!r}\n"
        # The runner script is dropped at SKILL_DIR/_framework_free_runner_tmp.py
        # so __file__ resolves to inside the skill dir. parents[0] = skill dir.
        "SKILL = pathlib.Path(__file__).resolve().parents[0]\n"
        "sys.path.insert(0, str(SKILL))\n"
        "\n"
        "class FrameworkBlocker:\n"
        "    def find_spec(self, fullname, path, target=None):\n"
        "        root = fullname.split('.')[0].lower()\n"
        "        if root in FRAMEWORKS:\n"
        "            raise ImportError(f'BLOCKED_FRAMEWORK:{root}')\n"
        "        return None\n"
        "\n"
        "sys.meta_path.insert(0, FrameworkBlocker())\n"
        "for mod in list(sys.modules):\n"
        "    root = mod.split('.')[0].lower()\n"
        "    if root in FRAMEWORKS:\n"
        "        del sys.modules[mod]\n"
        "\n"
        "VENOUS = SKILL / 'core' / 'venous'\n"
        "results = []\n"
        "for ns_dir in sorted(p for p in VENOUS.iterdir() if p.is_dir() and not p.name.startswith('_')):\n"
        "    for prim_dir in sorted(p for p in ns_dir.iterdir() if p.is_dir() and not p.name.startswith('_')):\n"
        "        motor = prim_dir / f'{prim_dir.name}.py'\n"
        "        if not motor.exists():\n"
        "            continue\n"
        "        ns = ns_dir.name\n"
        "        name = prim_dir.name\n"
        "        modpath = f'core.venous.{ns}.{name}.{name}'\n"
        "        record = {'ns': ns, 'name': name, 'import_ok': False, 'blocked_framework': None, 'error': None}\n"
        "        try:\n"
        "            importlib.import_module(modpath)\n"
        "            record['import_ok'] = True\n"
        "        except ImportError as e:\n"
        "            msg = str(e)\n"
        "            if msg.startswith('BLOCKED_FRAMEWORK:'):\n"
        "                record['blocked_framework'] = msg.split(':', 1)[1]\n"
        "            else:\n"
        "                record['error'] = f'ImportError: {msg[:200]}'\n"
        "        except Exception as e:\n"
        "            record['error'] = f'{type(e).__name__}: {str(e)[:200]}'\n"
        "        results.append(record)\n"
        "\n"
        "print(json.dumps(results))\n"
    )


def main() -> int:
    runner_script = _build_runner_script()
    runner_path = SKILL_DIR / "_framework_free_runner_tmp.py"
    runner_path.write_text(runner_script)
    try:
        r = subprocess.run(
            [str(SKILL_DIR / ".venv" / "bin" / "python"), str(runner_path)],
            capture_output=True, text=True, timeout=180,
        )
    finally:
        runner_path.unlink(missing_ok=True)

    if r.returncode != 0:
        print(json.dumps({"_error": "runner failed", "stderr": r.stderr[:1000]}, indent=2), file=sys.stderr)
        return 2

    per_primitive = json.loads(r.stdout)
    total = len(per_primitive)
    imported_clean = sum(1 for x in per_primitive if x["import_ok"])
    blocked = sum(1 for x in per_primitive if x["blocked_framework"])
    errored = sum(1 for x in per_primitive if x["error"])
    passed = (blocked == 0) and (total == 124)

    out = {
        "_meta": {
            "command": ".venv/bin/python evidence/_harness/framework_free_runtime.py",
            "cwd": "repo root",
            "commit": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "grading": "exit 0 iff zero primitives trigger a blocked-framework import",
            "frameworks_blocked": list(FRAMEWORKS),
        },
        "primitives_scanned": total,
        "summary": {
            "imported_clean": imported_clean,
            "blocked_framework_imports": blocked,
            "non_framework_errors": errored,
            "passed": passed,
        },
        "per_primitive": per_primitive,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
