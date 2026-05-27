# HuGR Auth API — production image (license issuance + introspection).
#
# This is the authority that gates the hosted MCP server: it holds the signing
# secret and answers /introspect. It is a SEPARATE service/image from the gated
# MCP server (deploy/mcp builds from skills/.../infra/docker/Dockerfile).
#
# Build context = REPO ROOT (so we can COPY the hugr_auth/ package):
#   docker build -f deploy/auth.Dockerfile -t hugr-auth:latest .
#
# Run (prod expects a real signing secret, admin token, and a Postgres DSN):
#   docker run --rm -p 8079:8079 \
#     -e HUGR_LICENSE_SIGNING_SECRET=<hex64> \
#     -e HUGR_ADMIN_TOKEN=<>=16-char-token> \
#     -e HUGR_STORE_DSN=postgresql+psycopg2://hugr:pw@db:5432/hugr \
#     hugr-auth:latest

# ── Stage 1: build deps into a venv ─────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Self-contained venv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements first to maximise layer-cache hits.
COPY deploy/requirements-auth.txt ./requirements-auth.txt
RUN pip install --upgrade pip \
    && pip install -r requirements-auth.txt

# ── Stage 2: slim runtime ───────────────────────────────────────────────────
FROM python:3.12-slim AS final

# Least privilege: dedicated non-root user, no shell login needed.
RUN groupadd --gid 1001 hugr \
    && useradd --uid 1001 --gid hugr --no-create-home --shell /usr/sbin/nologin hugr

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HUGR_MCP_PORT=8079

WORKDIR /app

# Pre-built venv from the builder stage (no build toolchain in the final image).
COPY --from=builder /opt/venv /opt/venv

# Only the auth package — NOT skills/, NOT tests are needed at runtime, but the
# package's test_*.py are tiny and harmless; we copy just the package dir.
COPY --chown=hugr:hugr hugr_auth/ /app/hugr_auth/

USER hugr

EXPOSE 8079

# Container-level liveness. /healthz is unauthenticated and always 200 when up.
# Uses the stdlib (urllib) so no extra dep is needed for the probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8079/healthz', timeout=4).status==200 else sys.exit(1)"]

# Single worker is fine: the revocation authority lives in Postgres (shared),
# so horizontal scale = more replicas, not more workers. Scale via compose.
CMD ["uvicorn", "hugr_auth.app:app", "--host", "0.0.0.0", "--port", "8079"]
