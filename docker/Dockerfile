# ──────────────────────────────────────────
# Stage 1: Base -- shared dependency layer
# ──────────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev gcc curl ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then TARCH="aarch64-unknown-linux-musl"; \
       else TARCH="x86_64-unknown-linux-gnu"; fi \
    && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-${TARCH}.tar.gz" \
       -o /tmp/tectonic.tar.gz \
    && tar xzf /tmp/tectonic.tar.gz -C /usr/local/bin/ tectonic \
    && rm /tmp/tectonic.tar.gz \
    && chmod +x /usr/local/bin/tectonic \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache -e ".[all]"


# ──────────────────────────────────────────
# Stage 2: Development -- hot reload, dev deps
# ──────────────────────────────────────────
FROM base AS development
COPY . .
RUN uv pip install --system --no-cache -e ".[dev]"
EXPOSE 8000
# Source is mounted as a volume; command is set in docker/docker-compose.yml


# ──────────────────────────────────────────
# Stage 3: Test -- run the full CI suite
# ──────────────────────────────────────────
FROM base AS test
COPY . .
RUN uv pip install --system --no-cache -e ".[dev]"
# Default entrypoint runs lint, typecheck, and tests
CMD ["bash", "-c", "ruff check . && ruff format --check . && mypy --strict src/ && pytest --tb=short -q"]


# ──────────────────────────────────────────
# Stage 4: Production -- minimal runtime image
# ──────────────────────────────────────────
FROM python:3.12-slim AS production
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache .
COPY alembic.ini .
COPY scripts/entrypoint.prod.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Non-root user for production
RUN groupadd -r phiacta && useradd -r -g phiacta phiacta
USER phiacta

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
