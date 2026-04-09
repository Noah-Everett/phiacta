# ──────────────────────────────────────────
# Stage 1: Base -- shared dependency layer
# ──────────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev gcc curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache -e ".[all]"


# ──────────────────────────────────────────
# Stage 2: Development -- hot reload, dev deps
# ──────────────────────────────────────────
FROM base AS development
# Install tectonic for local dev (workers run in separate containers in prod)
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then TARCH="aarch64-unknown-linux-musl"; \
       else TARCH="x86_64-unknown-linux-gnu"; fi \
    && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-${TARCH}.tar.gz" \
       -o /tmp/tectonic.tar.gz \
    && tar xzf /tmp/tectonic.tar.gz -C /usr/local/bin/ tectonic \
    && rm /tmp/tectonic.tar.gz \
    && chmod +x /usr/local/bin/tectonic
COPY . .
RUN uv pip install --system --no-cache -e ".[dev]"
EXPOSE 8000
# Source is mounted as a volume; command is set in docker/docker-compose.yml


# ──────────────────────────────────────────
# Stage 3: Test -- run the full CI suite
# ──────────────────────────────────────────
FROM base AS test
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then TARCH="aarch64-unknown-linux-musl"; \
       else TARCH="x86_64-unknown-linux-gnu"; fi \
    && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-${TARCH}.tar.gz" \
       -o /tmp/tectonic.tar.gz \
    && tar xzf /tmp/tectonic.tar.gz -C /usr/local/bin/ tectonic \
    && rm /tmp/tectonic.tar.gz \
    && chmod +x /usr/local/bin/tectonic
COPY . .
RUN uv pip install --system --no-cache -e ".[dev]"
# Default entrypoint runs lint, typecheck, and tests
CMD ["bash", "-c", "ruff check . && ruff format --check . && mypy --strict src/ && pytest --tb=short -q"]


# ──────────────────────────────────────────
# Stage 4: Production -- minimal API runtime
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


# ──────────────────────────────────────────
# Stage 5: Worker base -- shared worker runtime
# ──────────────────────────────────────────
FROM python:3.12-slim AS worker-base
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache .

CMD ["python", "-m", "phiacta.jobs.run_worker"]


# ──────────────────────────────────────────
# Stage 6: Worker LaTeX -- Tectonic + pre-cached TeX packages
# ──────────────────────────────────────────
FROM worker-base AS worker-latex

# Install Tectonic
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then TARCH="aarch64-unknown-linux-musl"; \
       else TARCH="x86_64-unknown-linux-gnu"; fi \
    && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-${TARCH}.tar.gz" \
       -o /tmp/tectonic.tar.gz \
    && tar xzf /tmp/tectonic.tar.gz -C /usr/local/bin/ tectonic \
    && rm /tmp/tectonic.tar.gz \
    && chmod +x /usr/local/bin/tectonic

# Pre-cache common TeX packages by compiling a document that uses them.
# Tectonic downloads packages on first use; doing this at build time means
# workers start fast and don't need network access at runtime.
RUN mkdir -p /tmp/texcache && cd /tmp/texcache \
    && printf '%s\n' \
        '\documentclass{article}' \
        '\usepackage{amsmath,amssymb,amsthm}' \
        '\usepackage{mathtools}' \
        '\usepackage{hyperref}' \
        '\usepackage{graphicx}' \
        '\usepackage{xcolor}' \
        '\usepackage{geometry}' \
        '\usepackage{booktabs}' \
        '\usepackage{enumitem}' \
        '\usepackage{natbib}' \
        '\usepackage{tikz}' \
        '\usepackage{pgfplots}' \
        '\pgfplotsset{compat=1.18}' \
        '\usepackage{algorithm2e}' \
        '\usepackage{listings}' \
        '\usepackage{caption,subcaption}' \
        '\usepackage{microtype}' \
        '\usepackage{siunitx}' \
        '\usepackage{physics}' \
        '\begin{document}' \
        'Cache seed.' \
        '\end{document}' \
       > cache.tex \
    && tectonic -X compile cache.tex \
    && rm -rf /tmp/texcache

CMD ["python", "-m", "phiacta.jobs.run_worker"]
