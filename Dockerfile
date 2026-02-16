# ──────────────────────────────────────────
# Stage 1: Base -- shared dependency layer
# ──────────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev gcc \
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
# Source is mounted as a volume; command is set in docker-compose.yml


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
RUN uv pip install --system --no-cache -e .
COPY src/ src/
COPY extensions/ extensions/
COPY alembic.ini .

# Non-root user for production
RUN groupadd -r newpub && useradd -r -g newpub newpub
USER newpub

EXPOSE 8000
CMD ["uvicorn", "phiacta.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
