# Packaging — the hybrid: plugin + installable packages

> **Status: proposal scaffold.** The manifests exist to validate the shape;
> nothing is published to PyPI and the composer entrypoint below is not wired
> yet. This doc is the design, not a shipped feature.

The distribution splits along one real boundary the codebase already draws:
**agent-knowledge** vs **runtime-dependency**. Three artifacts, two channels.

```
                 ┌─────────────────────────── installs into the AGENT ──┐
   Claude Code   │   Plugin  hugr-fastapi-production                     │
   plugin        │   .claude-plugin/plugin.json                         │
   ecosystem     │     ├── SKILL.md          the *knowledge* (how to use)│
                 │     └── .mcp.json ────────► MCP server: the *tools*   │
                 └──────────────────────────────────────────┬───────────┘
                                                             │ pip/uvx
   PyPI          ┌──────────────────────────────────────────▼───────────┐
   (or brew      │   hugr-composer   the composer: generators + MCP      │
   wrapper)      │                   surface. Entrypoint: hugr-composer-mcp│
                 │                                                        │
                 │   hugr-fastapi    the primitives. RUNTIME dep of the   │
                 └───────────────────┤ generated app — `pip install` INTO┘
                                       the target project, not the agent.
```

## The three artifacts

| Artifact | What it is | Channel | Consumer |
|---|---|---|---|
| **Plugin** `hugr-fastapi-production` | thin manifest bundling `SKILL.md` + the MCP server | Claude Code plugin marketplace | the **agent** (learns + gets tools) |
| **`hugr-composer`** | generators + `mcp_tools/` MCP surface; exposes the `hugr-composer-mcp` stdio entrypoint | PyPI (`uvx`/`pip`) | the plugin invokes it |
| **`hugr-fastapi`** | framework-free primitives + protocols | PyPI (`pip`) | the **generated app** `import`s it |

The distinction that makes it clean: **the skill and protocols travel with the
plugin** (agent knowledge, versioned next to the tools they describe), but **the
primitives travel with the app** (runtime dependency of the emitted code). The
same `.protocol.py` appears on both sides — as the interface the agent composes,
and as the class the app imports.

## Why plugin *and* package (not one or the other)

A Claude Code plugin is a thin manifest — `mcpServers` points at a `command`.
The weight lives in the package the command runs. So the composer is a
**pip-installable package** (`hugr-composer`) exposing a console entrypoint, and
the plugin is the **thin registration** that calls it. "Too big for a plugin" is
a non-issue: the plugin is the casca, the package is the peso.

## Wiring (proposal)

**1. Composer entrypoint** — add to the root `pyproject.toml`:

```toml
[project.scripts]
hugr-composer-mcp = "mcp_server:main"   # needs a thin main() that calls mcp.run()
```

Then `uvx --from hugr-composer hugr-composer-mcp` boots the stdio server —
exactly what `.mcp.json` already calls.

**2. Local-dev alternative** — for hacking on the repo without publishing, point
the MCP server at the checkout instead of `uvx`:

```json
{ "mcpServers": { "hugr-composer": {
  "command": "${CLAUDE_PLUGIN_ROOT}/.venv/bin/fastmcp",
  "args": ["run", "${CLAUDE_PLUGIN_ROOT}/mcp_server.py:mcp"]
}}}
```

**3. Primitives package** — see `packaging/hugr-fastapi/pyproject.toml`. It
carries **zero required deps** by design (the impls are framework-free); provider
glue is opt-in via `hugr-fastapi[fastapi|redis|stripe]`.

## Known open question (not solved)

The primitives live as evidence bundles (`core/venous/<ns>/<Name>/<Name>.py` +
protocol + contract + spec + generated corpus, PascalCase dirs). That tree is not
import-clean as-is; publishing `hugr-fastapi` needs a build step that harvests the
`<Name>.py` impls into a flat `hugr_fastapi/<ns>/` layout. `engine/extraction/`
does the inverse today; the promotion pipeline is the natural home for the
forward flattening. Tracked here, deliberately not hand-waved.

## About brew

`brew` targets system CLIs/binaries; a Python library's idiomatic channel is
PyPI (`pip`/`uvx`/`pipx`). The *spirit* of `brew install` — installable,
versioned, discoverable — is right; the mechanism is PyPI. A brew formula could
later wrap the CLI for convenience, but it's a thin veneer over the PyPI package.
