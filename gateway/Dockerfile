# claude-gateway — Multi-provider LLM Gateway for HuGR Arsenal
# Build: docker build -t humangr-labs/claude-gateway:latest .
# Run: docker run -p 8080:8080 -e OPENAI_API_KEY=... -e ANTHROPIC_API_KEY=... humangr-labs/claude-gateway:latest

FROM python:3.12-slim AS builder

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# No uv.lock in the repo — resolve deps at build time (deterministic enough
# for a service image; a lockfile can be added later for hermetic rebuilds).
COPY pyproject.toml ./

# Install dependencies
RUN uv sync --no-dev

# ---- Runtime Stage ----
FROM python:3.12-slim AS runtime

# Create non-root user
RUN groupadd -r gateway && useradd -r -g gateway gateway

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder --chown=gateway:gateway /app/.venv .venv

# Copy application code
COPY --chown=gateway:gateway gateway/ ./gateway/
COPY --chown=gateway:gateway gateway_config.yaml ./

# Switch to non-root user
USER gateway

# Environment
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Run the gateway
ENTRYPOINT [".venv/bin/python", "-m", "gateway.main"]
