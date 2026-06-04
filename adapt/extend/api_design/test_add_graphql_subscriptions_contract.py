"""Generic tool-contract mutation coverage for add_graphql_subscriptions.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graphql_subscriptions.py in the mutation
runner: ``--tests test_add_graphql_subscriptions.py test_add_graphql_subscriptions_contract.py``.

The ``test_mut_*`` functions below target this tool's bespoke logic
(schema/main/requirements patch helpers + idempotency guards) so the
tool-specific survivors are killed too.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_graphql_subscriptions import add_graphql_subscriptions
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_graphql_subscriptions import add_graphql_subscriptions

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graphql_subscriptions, "add_graphql_subscriptions")


def _run(name: str) -> object:
    project_dir = create_fixture_project(name=name)
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"{result.status}: {result.error}"
    return project_dir


# ---------------------------------------------------------------------------
# Schema patching — _patch_or_create_schema (L232-261)
# ---------------------------------------------------------------------------


def test_mut_schema_created_when_absent_returns_created():
    """L234 (return True): a fresh project has no schema.py, so the tool must
    CREATE it (counts as files_created, not files_modified)."""
    project_dir = create_fixture_project(name="gws_mut_schema_create")
    schema_file = project_dir / "app" / "graphql" / "schema.py"
    if schema_file.exists():
        schema_file.unlink()
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert schema_file.exists()
    assert str(Path(schema_file).resolve()) in {
        str(Path(p).resolve()) for p in result.files_created
    }, "newly-created schema.py must be reported as created"
    assert str(schema_file) not in result.files_modified
    # Minimal schema wires the subscription in.
    src = schema_file.read_text()
    assert "subscription=_GQLSubscription" in src


def test_mut_existing_schema_is_modified_not_created():
    """L261 (return False): an existing schema.py is MODIFIED in place, so it
    appears in files_modified, never files_created."""
    project_dir = create_fixture_project(name="gws_mut_schema_modify")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    schema_file.write_text(
        "import strawberry\n\n"
        "from app.graphql.queries import Query\n\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert str(schema_file) in result.files_modified
    assert str(schema_file) not in result.files_created


def test_mut_schema_with_subscription_is_left_untouched():
    """L237 (if "Subscription" in src: return False): a schema that already
    mentions Subscription must NOT be re-patched (no duplicate import)."""
    project_dir = create_fixture_project(name="gws_mut_schema_idem")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    original = (
        "import strawberry\n\n"
        "from app.graphql.subscriptions import Subscription\n\n"
        "schema = strawberry.Schema(query=None, subscription=Subscription)\n"
    )
    schema_file.write_text(original)
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert schema_file.read_text() == original, (
        "schema already containing Subscription must be left byte-for-byte unchanged"
    )


def test_mut_schema_import_inserted_after_query_import():
    """L241 + L244 (Query-import branch, ``Query\\n`` + sub_import): when the
    schema imports Query, the subscription import is inserted DIRECTLY AFTER the
    Query import (not before / not at top)."""
    project_dir = create_fixture_project(name="gws_mut_schema_query")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    schema_file.write_text(
        "import strawberry\n\n"
        "from app.graphql.queries import Query\n\n"
        "schema = strawberry.Schema(query=Query)\n"
    )
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = schema_file.read_text()
    query_idx = src.index("from app.graphql.queries import Query")
    sub_idx = src.index("from app.graphql.subscriptions import Subscription as _GQLSubscription")
    assert sub_idx > query_idx, "subscription import must come after the Query import"
    # L244: the two imports must be adjacent (Query line immediately followed by sub import).
    after_query = src[query_idx:]
    first_nl = after_query.index("\n")
    assert after_query[first_nl + 1 :].startswith(
        "from app.graphql.subscriptions import Subscription as _GQLSubscription"
    ), "subscription import must sit on the line immediately after the Query import"


def test_mut_schema_import_inserted_after_strawberry_when_no_query():
    """L246 + L252 (elif ``import strawberry`` branch): with no Query import the
    subscription import is inserted after ``import strawberry`` — NOT prepended
    to the very top of the file (which is the no-anchor fallback)."""
    project_dir = create_fixture_project(name="gws_mut_schema_straw")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    schema_file.write_text(
        '"""Schema."""\n\nimport strawberry\n\nschema = strawberry.Schema(query=None)\n'
    )
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = schema_file.read_text()
    straw_idx = src.index("import strawberry")
    sub_idx = src.index("from app.graphql.subscriptions import Subscription as _GQLSubscription")
    assert sub_idx > straw_idx, "subscription import must follow ``import strawberry``"
    # Not prepended to the top: the docstring still leads the file.
    assert src.lstrip().startswith('"""Schema."""'), (
        "subscription import must NOT be prepended above the module docstring"
    )


def test_mut_schema_import_prepended_when_no_anchor():
    """L252 fallback (``src = sub_import + src``): a schema with neither a Query
    import nor ``import strawberry`` gets the subscription import PREPENDED."""
    project_dir = create_fixture_project(name="gws_mut_schema_noanchor")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    schema_file.write_text("schema = make_schema()\n")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = schema_file.read_text()
    assert src.startswith(
        "from app.graphql.subscriptions import Subscription as _GQLSubscription"
    ), "with no anchor the subscription import must be prepended to the top"


def test_mut_schema_subscription_kwarg_injected_into_schema_call():
    """L254 (And) + the kwarg replace: when ``strawberry.Schema(`` is present and
    has no ``subscription=`` yet, the kwarg is injected into the constructor."""
    project_dir = create_fixture_project(name="gws_mut_schema_kwarg")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    schema_file = gql / "schema.py"
    schema_file.write_text("import strawberry\n\nschema = strawberry.Schema(query=None)\n")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = schema_file.read_text()
    assert "subscription=_GQLSubscription" in src, (
        "subscription kwarg must be injected into strawberry.Schema(...)"
    )


# ---------------------------------------------------------------------------
# main.py patching — _patch_main (L264-282)
# ---------------------------------------------------------------------------


def test_mut_main_ws_import_inserted_after_fastapi_import():
    """L272 (if ``from fastapi import FastAPI`` in src) + L278 ordering: the
    ws_handler import lands DIRECTLY AFTER the FastAPI import, and the mount
    call comes after the import."""
    project_dir = _run("gws_mut_main_order")
    src = (project_dir / "app" / "main.py").read_text()
    fastapi_idx = src.index("from fastapi import FastAPI")
    import_idx = src.index(
        "from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler"
    )
    mount_idx = src.index('add_api_websocket_route("/graphql/ws"')
    assert fastapi_idx < import_idx < mount_idx, (
        "ws import must sit after FastAPI import and before the mount call"
    )
    after_fastapi = src[fastapi_idx:]
    first_nl = after_fastapi.index("\n")
    assert after_fastapi[first_nl + 1 :].startswith(
        "from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler"
    ), "ws import must sit on the line right after the FastAPI import"


def test_mut_main_ws_import_prepended_when_no_fastapi_import():
    """L278 fallback (``src = ws_import + src``): a main.py without
    ``from fastapi import FastAPI`` gets the ws import PREPENDED to the top."""
    project_dir = create_fixture_project(name="gws_mut_main_noanchor")
    main_file = project_dir / "app" / "main.py"
    main_file.write_text("import fastapi\n\napp = fastapi.FastAPI()\n")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = main_file.read_text()
    assert src.startswith(
        "from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler"
    ), "without a FastAPI import anchor the ws import must be prepended"
    assert 'add_api_websocket_route("/graphql/ws"' in src


def test_mut_main_already_mounted_is_left_untouched():
    """L267 (if "/graphql/ws" in src or "graphql_ws_handler" in src): a main.py
    that already mounts the route must NOT be patched again."""
    project_dir = create_fixture_project(name="gws_mut_main_idem")
    main_file = project_dir / "app" / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n"
        'app.add_api_websocket_route("/graphql/ws", handler)\n'
    )
    original = main_file.read_text()
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert main_file.read_text() == original, (
        "main.py already mounting /graphql/ws must be left byte-for-byte unchanged"
    )


def test_mut_main_only_handler_token_present_is_left_untouched():
    """L267 (Or, second arm ``graphql_ws_handler``): a main.py mentioning the
    handler name (but not the route path) must also be treated as already wired."""
    project_dir = create_fixture_project(name="gws_mut_main_handler_token")
    main_file = project_dir / "app" / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\n\n"
        "# graphql_ws_handler already wired elsewhere\n"
        "app = FastAPI()\n"
    )
    original = main_file.read_text()
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert main_file.read_text() == original, (
        "main.py mentioning graphql_ws_handler must be left unchanged"
    )


# ---------------------------------------------------------------------------
# requirements.txt patching — _patch_requirements (L285-294)
# ---------------------------------------------------------------------------


def test_mut_requirements_adds_both_when_absent():
    """L289 (if "strawberry-graphql" not in src) + graphql-ws guard: both deps
    are appended exactly once to a requirements file lacking them."""
    project_dir = _run("gws_mut_req_add")
    src = (project_dir / "requirements.txt").read_text()
    assert "strawberry-graphql" in src
    assert "graphql-ws" in src
    assert src.count("strawberry-graphql[fastapi]>=0.220.0") == 1
    assert src.count("graphql-ws>=0.5.0") == 1


def test_mut_requirements_does_not_duplicate_existing_dep():
    """L289 (NotIn guard): if strawberry-graphql is already pinned, the tool must
    NOT append a second strawberry-graphql line."""
    project_dir = create_fixture_project(name="gws_mut_req_dedup")
    req = project_dir / "requirements.txt"
    req.write_text(req.read_text().rstrip("\n") + "\nstrawberry-graphql==0.1.0\n")
    add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    src = req.read_text()
    assert src.count("strawberry-graphql") == 1, (
        "existing strawberry-graphql pin must not be duplicated"
    )
    # graphql-ws was absent, so it should still get appended.
    assert "graphql-ws>=0.5.0" in src


# ---------------------------------------------------------------------------
# Idempotency content guard — main() (L120-122)
# ---------------------------------------------------------------------------


def test_mut_no_op_only_when_pubsub_marker_present():
    """L122 (if "get_pubsub" in body or "PubSubManager" in body): a pre-existing
    pubsub.py WITHOUT either marker must NOT short-circuit to no_op — the tool
    proceeds and writes its files."""
    project_dir = create_fixture_project(name="gws_mut_guard_nomarker")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    pubsub_file = gql / "pubsub.py"
    pubsub_file.write_text("# placeholder, no real pubsub yet\n")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        "pubsub.py without get_pubsub/PubSubManager must not trigger no_op"
    )
    assert "get_pubsub" in pubsub_file.read_text()


def test_mut_no_op_when_legacy_pubsubmanager_marker_present():
    """L122 (Or, second arm ``PubSubManager``): a pubsub.py containing the legacy
    PubSubManager marker must short-circuit to no_op."""
    project_dir = create_fixture_project(name="gws_mut_guard_legacy")
    gql = project_dir / "app" / "graphql"
    gql.mkdir(parents=True, exist_ok=True)
    pubsub_file = gql / "pubsub.py"
    pubsub_file.write_text("class PubSubManager:\n    pass\n")
    result = add_graphql_subscriptions(ToolInput(project_dir=str(project_dir)))
    assert result.status == "no_op", "legacy PubSubManager marker must trigger no_op"
