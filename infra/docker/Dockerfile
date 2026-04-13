# SKILL-001 MCP Server — Production Dockerfile
#
# Packages the FastAPI Production skill as a self-contained MCP server.
# The server exposes all 30 generators + 51 adapt tools over the MCP protocol.
#
# Build:
#   docker build -t hugr-skill-fastapi:latest -f infra/docker/Dockerfile .
#
# Run (stdio transport — for Claude Desktop / local agents):
#   docker run --rm -i hugr-skill-fastapi:latest
#
# Run (HTTP transport — for remote / production use):
#   docker run --rm -p 8000:8000 hugr-skill-fastapi:latest \
#       fastmcp run mcp_server.py:mcp --transport streamable-http \
#       --host 0.0.0.0 --port 8000

# ── Stage 1: dependency resolver ──────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /skill

# Install build tools needed by some transitive deps (e.g. cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to maximise layer-cache hits.
# requirements.txt is the minimal set needed to run the MCP server itself;
# the generated projects bring their own requirements at generation time.
COPY requirements-mcp.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-mcp.txt

# ── Stage 2: final image ───────────────────────────────────────────────────
FROM python:3.12-slim AS final

# Security: run as non-root
RUN groupadd --gid 1001 skill \
    && useradd --uid 1001 --gid skill --shell /bin/bash --create-home skill

WORKDIR /skill

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy skill source
COPY --chown=skill:skill . .

# Ensure the skill root is on the Python path so that
# `from generators.orchestrator import generate_project` works.
ENV PYTHONPATH=/skill
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER skill

EXPOSE 8000

# Default: stdio transport (compatible with Claude Desktop + all MCP clients).
# Override CMD for HTTP transport in docker-compose or k8s deployments.
CMD ["fastmcp", "run", "mcp_server.py:mcp"]
