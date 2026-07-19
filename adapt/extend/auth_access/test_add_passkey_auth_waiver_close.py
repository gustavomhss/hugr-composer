"""Regression tests for the Wave-2 waiver closures on TOOL-075 add_passkey_auth.

Covers:

* **B0.14 / R6-O3-P2** — every WRITE schema in ``app/schemas/passkey.py``
  declares ``model_config = ConfigDict(extra="forbid")`` and the rendered
  Pydantic models reject extra keys at parse time.
* **B0.12 / R5-O4-H4** — the rendered ``app/api/routes/passkeys.py``
  template no longer declares a module-level mutable ``_CHALLENGE_STORE``
  dict; storage is encapsulated in a ``_ChallengeStore`` class instance
  whose fallback dict is per-instance state and whose primary backend is
  Redis (``webauthn:challenge:{session_id}`` SETEX). The store/pop round
  trip works with no Redis (dict fallback) and honours the configured
  ``WEBAUTHN_CHALLENGE_TTL_SECONDS`` expiry.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_passkey_auth_waiver_close.py -v
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import sys
import time
import types
from pathlib import Path

import pytest

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-for-passkey-auth-ok!")
os.environ.setdefault("WEBAUTHN_RP_ID", "localhost")
os.environ.setdefault("WEBAUTHN_RP_NAME", "Test App")
os.environ.setdefault("WEBAUTHN_ORIGIN", "http://localhost:8000")

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Project build (module-scoped so tests are fast)
# ---------------------------------------------------------------------------


_PROJECT_DIR: Path | None = None


def _build_project() -> Path:
    """Generate the fixture project + apply the tool once for all tests."""
    global _PROJECT_DIR
    if _PROJECT_DIR is not None:
        return _PROJECT_DIR
    project_dir = create_fixture_project(name="passkey_waiver_close")
    result = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"tool failed: {result.error}"
    _PROJECT_DIR = project_dir
    return project_dir


# ---------------------------------------------------------------------------
# B0.14 — schemas
# ---------------------------------------------------------------------------


def _load_passkey_schemas(project_dir: Path) -> types.ModuleType:
    """Import the rendered ``app.schemas.passkey`` module from the project."""
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    return importlib.import_module("app.schemas.passkey")


def test_schema_extra_forbid_rejects_unknown_keys() -> None:
    """B0.14 — every WRITE schema rejects an extra key with a ValidationError.

    Cites R6-O3-P2: the pre-fix RegistrationBeginRequest /
    RegistrationCompleteRequest / AuthenticationCompleteRequest all
    accepted arbitrary keys via the default Pydantic ``extra="ignore"``,
    enabling key smuggling / mass-assignment.
    """
    from pydantic import ValidationError

    project_dir = _build_project()
    passkey_schemas = _load_passkey_schemas(project_dir)

    cases = [
        (
            passkey_schemas.RegistrationBeginRequest,
            {"username": "alice", "is_admin": True},
        ),
        (
            passkey_schemas.RegistrationCompleteRequest,
            {
                "session_id": "abc",
                "credential": {"id": "x", "type": "public-key"},
                "user_id": "victim-uuid",
            },
        ),
        (
            passkey_schemas.AuthenticationCompleteRequest,
            {
                "session_id": "abc",
                "credential": {"id": "x", "type": "public-key"},
                "elevated_role": "owner",
            },
        ),
    ]
    for cls, payload in cases:
        with pytest.raises(ValidationError):
            cls(**payload)


def test_schema_extra_forbid_accepts_only_declared_keys() -> None:
    """Sanity — happy path still parses with only the declared fields."""
    project_dir = _build_project()
    passkey_schemas = _load_passkey_schemas(project_dir)

    passkey_schemas.RegistrationBeginRequest(username="alice")
    passkey_schemas.RegistrationCompleteRequest(
        session_id="sess",
        credential={"id": "x", "type": "public-key"},
    )
    passkey_schemas.AuthenticationCompleteRequest(
        session_id="sess",
        credential={"id": "x", "type": "public-key"},
    )


def test_schema_template_declares_config_dict_extra_forbid() -> None:
    """Static check on the template AST — every Request class carries
    ``model_config = ConfigDict(extra="forbid")`` so the contract rule
    (B0.14) passes whether or not Pydantic itself is importable."""
    tmpl = (
        Path(__file__).parent
        / "add_passkey_auth"
        / "templates"
        / "schemas.py.tmpl"
    )
    tree = ast.parse(tmpl.read_text(encoding="utf-8"))
    write_classes = {
        "RegistrationBeginRequest",
        "RegistrationCompleteRequest",
        "AuthenticationCompleteRequest",
    }
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in write_classes:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for tgt in stmt.targets:
                if not (isinstance(tgt, ast.Name) and tgt.id == "model_config"):
                    continue
                if not isinstance(stmt.value, ast.Call):
                    continue
                for kw in stmt.value.keywords:
                    if (
                        kw.arg == "extra"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "forbid"
                    ):
                        seen.add(node.name)
    assert seen == write_classes, (
        f"missing extra=forbid on: {write_classes - seen}"
    )


# ---------------------------------------------------------------------------
# B0.12 — challenge store
# ---------------------------------------------------------------------------


def test_routes_template_has_no_module_level_challenge_dict() -> None:
    """B0.12 — the routes template no longer declares a module-level
    ``_CHALLENGE_STORE`` mutable dict; the new shape is a
    ``_ChallengeStore`` instance whose mutable state lives inside the
    class (allow-listed by the contract rule)."""
    tmpl = (
        Path(__file__).parent
        / "add_passkey_auth"
        / "templates"
        / "routes.py.tmpl"
    )
    src = tmpl.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for stmt in tree.body:
        # Reject any top-level `_CHALLENGE_STORE = {...}` literal assignment.
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_CHALLENGE_STORE":
                    assert not isinstance(stmt.value, ast.Dict), (
                        "_CHALLENGE_STORE must not be a module-level dict literal"
                    )
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == "_CHALLENGE_STORE" and stmt.value is not None:
                assert not isinstance(stmt.value, ast.Dict), (
                    "_CHALLENGE_STORE must not be a module-level dict literal"
                )
    # Positive: the encapsulating class is present.
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "_ChallengeStore" in class_names, (
        "_ChallengeStore encapsulation class missing from routes template"
    )


def test_challenge_store_roundtrip_with_no_redis() -> None:
    """Behavior — without Redis, _ChallengeStore stores + pops a challenge
    via the per-worker dict fallback (so single-instance deployments and
    local dev still work)."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    # Force "no Redis" by ensuring app.core.redis is absent — the import
    # inside _redis_or_none will raise ModuleNotFoundError and the helper
    # will return None (exercising the pragma-disclosed broad-catch).
    routes_mod = importlib.import_module("app.api.routes.passkeys")
    store = routes_mod._ChallengeStore()

    async def _exercise() -> None:
        await store.store("sess-1", b"chal-bytes")
        got = await store.pop("sess-1")
        assert got == b"chal-bytes"
        # One-shot semantics: a second pop returns None.
        gone = await store.pop("sess-1")
        assert gone is None

    asyncio.run(_exercise())


def test_challenge_store_fallback_honours_ttl() -> None:
    """Behavior — the per-worker fallback dict expires entries past TTL."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    routes_mod = importlib.import_module("app.api.routes.passkeys")

    store = routes_mod._ChallengeStore()
    store._ttl = 0  # forces immediate expiry on the fallback path

    async def _exercise() -> None:
        await store.store("sess-ttl", b"chal-bytes")
        # Ensure the monotonic clock advances strictly past the expiry.
        time.sleep(0.01)
        got = await store.pop("sess-ttl")
        assert got is None, "Expired fallback entry must not be returned"

    asyncio.run(_exercise())


def test_challenge_store_uses_redis_when_available() -> None:
    """Behavior — when ``app.core.redis.get_redis_or_none()`` returns a
    fake client, _ChallengeStore writes via SETEX and reads via GET
    (Redis path is exercised), then DELETEs on pop."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    routes_mod = importlib.import_module("app.api.routes.passkeys")

    # Inject a fake ``app.core.redis`` module BEFORE the routes module
    # tries the lazy import inside _redis_or_none.
    fake_state: dict[str, bytes] = {}
    calls: dict[str, int] = {"setex": 0, "get": 0, "delete": 0}

    class _FakeRedis:
        async def setex(self, k: str, ttl: int, v: bytes) -> None:
            calls["setex"] += 1
            fake_state[k] = v

        async def get(self, k: str) -> bytes | None:
            calls["get"] += 1
            return fake_state.get(k)

        async def delete(self, k: str) -> None:
            calls["delete"] += 1
            fake_state.pop(k, None)

    fake_module = types.ModuleType("app.core.redis")

    async def _get_redis_or_none() -> _FakeRedis:
        return _FakeRedis()

    fake_module.get_redis_or_none = _get_redis_or_none  # type: ignore[attr-defined]
    sys.modules["app.core.redis"] = fake_module

    try:
        store = routes_mod._ChallengeStore()

        async def _exercise() -> None:
            await store.store("sess-redis", b"chal-redis-bytes")
            got = await store.pop("sess-redis")
            assert got == b"chal-redis-bytes"

        asyncio.run(_exercise())
        assert calls["setex"] >= 1, "Redis SETEX must be exercised"
        assert calls["get"] >= 1, "Redis GET must be exercised"
        assert calls["delete"] >= 1, "Redis DELETE must be exercised"
        # Verify the fallback dict is NOT populated when Redis succeeds.
        assert store._fallback == {}, (
            "Fallback dict must stay empty when Redis is the source of truth"
        )
    finally:
        sys.modules.pop("app.core.redis", None)


# ---------------------------------------------------------------------------
# Cross-check — waivers really were removed from both rule files.
# ---------------------------------------------------------------------------


def test_waivers_removed_from_rule_files() -> None:
    """Meta — both rule files no longer carry ``add_passkey_auth`` in
    their ``_WAIVED_TOOLS`` set. This prevents the next regression from
    re-introducing the defects under the safety of a stale waiver."""
    from engine.audit.contract_rules import (  # type: ignore[import]
        r_no_module_state,
        r_write_schemas_strict,
    )

    assert (
        "extend/auth_access/add_passkey_auth"
        not in r_no_module_state._WAIVED_TOOLS
    ), "B0.12 waiver for add_passkey_auth must be removed"
    assert (
        "add_passkey_auth" not in r_write_schemas_strict._WAIVED_TOOLS
    ), "B0.14 waiver for add_passkey_auth must be removed"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [
        test_schema_extra_forbid_rejects_unknown_keys,
        test_schema_extra_forbid_accepts_only_declared_keys,
        test_schema_template_declares_config_dict_extra_forbid,
        test_routes_template_has_no_module_level_challenge_dict,
        test_challenge_store_roundtrip_with_no_redis,
        test_challenge_store_fallback_honours_ttl,
        test_challenge_store_uses_redis_when_available,
        test_waivers_removed_from_rule_files,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
