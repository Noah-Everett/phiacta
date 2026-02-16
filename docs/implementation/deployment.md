# Phiacta Deployment Guide

*Covers local development, testing, production deployment, operations, and security. Read `architecture.md` first for project structure and dependency context.*

---

## 1. Development Environment Setup

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- An OpenAI API key (for embedding generation)
- Optionally: Python 3.12+ and `uv` for running outside containers

### docker-compose.yml

The Compose file defines three services: PostgreSQL with pgvector, the backend API, and an optional pgAdmin instance for database inspection during development.

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: phiacta
      POSTGRES_USER: newpub
      POSTGRES_PASSWORD: devpassword
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U newpub -d phiacta"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    environment:
      DATABASE_URL: "postgresql+asyncpg://newpub:devpassword@db:5432/phiacta"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      LOG_LEVEL: "debug"
      ENVIRONMENT: "development"
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src
      - ./extensions:/app/extensions
    depends_on:
      db:
        condition: service_healthy
    command: >
      uvicorn phiacta.main:app
      --host 0.0.0.0
      --port 8000
      --reload
      --reload-dir /app/src

  pgadmin:
    image: dpage/pgadmin4:latest
    profiles: ["debug"]
    environment:
      PGADMIN_DEFAULT_EMAIL: dev@phiacta.local
      PGADMIN_DEFAULT_PASSWORD: devpassword
    ports:
      - "5050:80"
    depends_on:
      - db

volumes:
  pgdata:
```

### Starting the Stack

```bash
# Start database and backend
docker compose up

# Start with pgAdmin for database inspection
docker compose --profile debug up

# Rebuild after dependency changes
docker compose build --no-cache backend && docker compose up
```

After startup, the API is available at `http://localhost:8000` and auto-generated docs at `http://localhost:8000/docs`. The startup sequence is: PostgreSQL passes its health check, then the backend boots, runs Alembic migrations via a lifespan hook, and binds to port 8000. This sequence is idempotent -- running against an existing database with data is safe.

### Running Outside Docker

For faster iteration, you can run the backend directly while using Docker only for PostgreSQL:

```bash
# Start only the database
docker compose up db

# Install the project in editable mode
uv pip install -e ".[dev]"

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://newpub:devpassword@localhost:5432/phiacta"
export OPENAI_API_KEY="sk-..."
export ENVIRONMENT="development"

# Run migrations
alembic upgrade head

# Start the dev server
uvicorn phiacta.main:app --reload --reload-dir src
```

---

## 2. Dockerfile (Multi-Stage)

The Dockerfile uses three stages: a base layer with dependencies, a development target with dev tooling and hot reload, a test target for CI, and a minimal production image.

```dockerfile
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
```

### Building Specific Stages

```bash
# Development image (used by docker-compose)
docker build --target development -t phiacta:dev .

# Run the CI test suite
docker build --target test -t phiacta:test .
docker run --rm phiacta:test

# Production image
docker build --target production -t phiacta:latest .
```

The production stage drops all dev dependencies, build tools, and the gcc compiler. It runs as a non-root user (`newpub`). The final image is ~250MB compared to ~800MB for the development stage.

---

## 3. Environment Variables and Configuration

All configuration is loaded from environment variables via `pydantic-settings`. No config files are baked into images, and no secrets are stored in source control.

### Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/phiacta` | Full async connection string |
| `OPENAI_API_KEY` | `sk-...` | Used by the embedding service and paper ingestion extension |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `production` | `development` enables debug logging, auto-reload, and relaxed CORS |
| `LOG_LEVEL` | `info` | One of `debug`, `info`, `warning`, `error` |
| `LOG_FORMAT` | `json` | `json` for production (structured), `console` for development (human-readable) |
| `CORS_ORIGINS` | `[]` | JSON array of allowed CORS origins, e.g. `["http://localhost:3000"]` |
| `API_KEY_SALT` | (auto-generated) | Salt used for hashing API keys; set explicitly in production for consistency across replicas |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI model name for embedding generation |
| `EMBEDDING_DIMENSIONS` | `1536` | Must match the vector column dimension in PostgreSQL |
| `DATABASE_POOL_SIZE` | `20` | Maximum concurrent connections in the SQLAlchemy pool |
| `DATABASE_MAX_OVERFLOW` | `10` | Burst connections allowed beyond the pool size |
| `DATABASE_POOL_TIMEOUT` | `30` | Seconds to wait for a connection from the pool |
| `MAX_BUNDLE_CLAIMS` | `500` | Maximum number of claims per bundle submission |
| `MAX_TRAVERSAL_DEPTH` | `10` | Maximum depth for graph traversal queries |

### Environment-Specific Configuration

In development mode (`ENVIRONMENT=development`):
- CORS allows all origins
- SQL queries are logged at DEBUG level
- Auto-migration runs on startup via the FastAPI lifespan hook
- Detailed error responses include stack traces

In production mode (`ENVIRONMENT=production`):
- CORS is restricted to `CORS_ORIGINS`
- SQL logging is off
- Auto-migration is disabled (migrations run as a separate step)
- Error responses return structured codes without internal details

### .env File for Local Development

For convenience, create a `.env` file in the project root (git-ignored):

```bash
DATABASE_URL=postgresql+asyncpg://newpub:devpassword@localhost:5432/phiacta
OPENAI_API_KEY=sk-your-key-here
ENVIRONMENT=development
LOG_LEVEL=debug
LOG_FORMAT=console
```

Docker Compose reads `.env` automatically. For running outside Docker, use `export $(cat .env | xargs)` or a tool like `direnv`.

---

## 4. Database Initialization and Migrations

### Alembic Setup

Alembic manages all schema changes. The migration environment is configured in `alembic.ini` and `src/phiacta/db/migrations/env.py`. The connection string is read from the `DATABASE_URL` environment variable -- never hardcoded.

### Initial Migration

The first Alembic migration creates the complete schema:

1. Enables the `uuid-ossp` and `vector` PostgreSQL extensions.
2. Creates the 11 tables: `agents`, `namespaces`, `sources`, `claims`, `edge_types`, `edges`, `provenance`, `reviews`, `bundles`, `artifacts`, `artifact_claims`, `pending_references`.
3. Creates all indexes: B-tree on foreign keys and lookups, IVFFlat on `claims.embedding`, GIN on `claims.search_tsv` and `claims.attrs`, partial indexes on `pending_references` and `claims_latest`.
4. Seeds the 15 initial edge types (`supports`, `contradicts`, `depends_on`, etc.) with their formal properties (`transitive`, `symmetric`, `anti_reflexive`).
5. Creates the two materialized views: `claims_latest` (current version of each claim lineage) and `claims_with_confidence` (aggregated reviewer confidence).

### Running Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "add_field_to_claims"

# Downgrade one step
alembic downgrade -1

# Show current migration state
alembic current

# Show migration history
alembic history --verbose
```

### Migration Discipline

- Every schema change goes through Alembic. No manual DDL in production.
- Autogenerated migrations are always reviewed before committing. Alembic's autogenerate detects most changes but can miss column type modifications, index changes, and constraint renames.
- Destructive migrations (dropping columns, changing types) must include explicit `op.execute()` statements for data migration and should be split into two deployments: first deploy code that handles both old and new schemas, then deploy the destructive migration.
- Migrations run in a transaction by default. If a migration fails halfway, PostgreSQL rolls it back cleanly.

### Development vs. Production Migration Strategy

- **Development:** Auto-migration on startup via the FastAPI lifespan hook. The app calls `alembic upgrade head` before accepting requests. This is enabled when `ENVIRONMENT=development`.
- **Production:** Migrations run as a separate step before the application starts. In Kubernetes, this means a Job or init container. The application itself never runs migrations in production to avoid race conditions when multiple replicas start simultaneously.

```bash
# Production migration command (run once, before deploying new app version)
docker run --rm \
  -e DATABASE_URL="$PROD_DATABASE_URL" \
  phiacta:latest \
  alembic upgrade head
```

---

## 5. Production Deployment

### Architecture Overview

A production deployment consists of:

- **PostgreSQL 16 + pgvector**: Managed database service (AWS RDS, GCP Cloud SQL, or self-hosted). Do NOT run PostgreSQL as a container in production unless you have a strong operational story for backups, failover, and monitoring.
- **Backend API**: Multiple replicas of the production Docker image behind a load balancer. Stateless -- any replica can handle any request.
- **Reverse proxy / load balancer**: TLS termination, request routing, rate limiting. Nginx, Caddy, or a cloud load balancer (ALB, Cloud Load Balancing).

### Kubernetes Deployment (Basic)

For teams running Kubernetes, the deployment requires three manifests: a Deployment, a Service, and a migration Job.

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: phiacta-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: phiacta-api
  template:
    metadata:
      labels:
        app: phiacta-api
    spec:
      containers:
        - name: api
          image: phiacta:latest
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: phiacta-secrets
            - configMapRef:
                name: phiacta-config
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
---
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: phiacta-api
spec:
  selector:
    app: phiacta-api
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
---
# migration-job.yaml (run before each deployment)
apiVersion: batch/v1
kind: Job
metadata:
  name: phiacta-migrate
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: phiacta:latest
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef:
                name: phiacta-secrets
      restartPolicy: Never
  backoffLimit: 3
```

### Kubernetes Secrets and ConfigMaps

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: phiacta-config
data:
  ENVIRONMENT: "production"
  LOG_LEVEL: "info"
  LOG_FORMAT: "json"
  EMBEDDING_MODEL: "text-embedding-3-small"
  EMBEDDING_DIMENSIONS: "1536"
  DATABASE_POOL_SIZE: "20"
  MAX_BUNDLE_CLAIMS: "500"
---
# secret.yaml (use sealed-secrets or external-secrets in practice)
apiVersion: v1
kind: Secret
metadata:
  name: phiacta-secrets
type: Opaque
stringData:
  DATABASE_URL: "postgresql+asyncpg://newpub:PRODPASSWORD@db-host:5432/phiacta"
  OPENAI_API_KEY: "sk-..."
  API_KEY_SALT: "random-64-char-string"
```

Never store secrets in plain YAML committed to source control. Use Sealed Secrets, External Secrets Operator, or your cloud provider's secret manager (AWS Secrets Manager, GCP Secret Manager) to inject secrets at runtime.

### Scaling Considerations

- **Backend replicas**: The API is stateless. Scale horizontally by increasing the Deployment replica count. Each replica runs 4 uvicorn workers (configurable via the Dockerfile CMD).
- **Database connections**: With 3 replicas x 4 workers x pool_size 20, the database needs to handle ~240 connections. Managed PostgreSQL services typically support 500-1000 connections. If you need more, add PgBouncer as a connection pooler.
- **WebSocket subscriptions**: In-process pubsub means subscriptions are local to each replica. At multi-replica scale, add Redis Pub/Sub as a broadcast channel so events reach all subscribers regardless of which replica they're connected to. This is a v2 concern.
- **Embedding generation**: The OpenAI API is the bottleneck for ingestion. Rate limits apply. For bulk ingestion, implement client-side batching and respect the `Retry-After` header.

### Helm Chart (Planned)

A Helm chart is planned for v1.0 but is not part of the initial release. The Kubernetes manifests above are sufficient for early production deployments. The Helm chart will parameterize replica count, resource limits, database connection settings, and ingress configuration.

---

## 6. Monitoring and Logging

### Structured Logging

The backend uses `structlog` configured to output JSON in production and human-readable console format in development. Every log line includes:

- `timestamp` (ISO 8601)
- `level` (info, warning, error)
- `event` (what happened)
- `request_id` (UUID, set by middleware on each request)
- `duration_ms` (for request logs)

```json
{
  "timestamp": "2026-02-08T14:30:00Z",
  "level": "info",
  "event": "bundle_submitted",
  "request_id": "a1b2c3d4-...",
  "extension_id": "paper-ingestion",
  "claim_count": 42,
  "duration_ms": 1230
}
```

Structured logs are designed to be ingested by any log aggregation system: ELK stack (Elasticsearch, Logstash, Kibana), Grafana Loki, Datadog, or cloud-native solutions (CloudWatch, Cloud Logging).

### Health Endpoints

Two health endpoints are exposed for orchestrator probes:

- **`GET /health`** -- Liveness probe. Returns 200 if the process is running. Does not check dependencies. Used by Kubernetes to decide whether to restart the container.
- **`GET /ready`** -- Readiness probe. Returns 200 only if the database is reachable and migrations are current. Used by Kubernetes to decide whether to route traffic to this replica. Returns 503 with details if any dependency is unhealthy.

### Metrics (Recommended Setup)

Expose Prometheus-compatible metrics via `prometheus-fastapi-instrumentator` or a similar library:

- **Request metrics**: request count, latency histogram, error rate, grouped by endpoint and status code.
- **Database metrics**: connection pool utilization, query duration, slow query count.
- **Business metrics**: bundles submitted per hour, claims ingested per day, search queries per hour, active extensions.
- **System metrics**: CPU, memory, and disk usage via node-exporter or cAdvisor.

A basic Grafana dashboard should track: request rate, p50/p95/p99 latency, error rate, database connection pool usage, and bundle submission rate. Alert on: error rate > 5%, p99 latency > 5s, database connection pool saturation > 80%, and health check failures.

---

## 7. Backup and Recovery

### Database Backups

PostgreSQL is the single source of truth. Protect it accordingly.

**Managed databases (recommended):** AWS RDS, GCP Cloud SQL, and similar services provide automated daily backups, point-in-time recovery (PITR) within a retention window (typically 7-35 days), and automated failover. Use these features. They are the primary reason to use a managed database in production.

**Self-hosted PostgreSQL:**

```bash
# Full logical backup (portable, slower)
pg_dump -Fc -U newpub -d phiacta > backup_$(date +%Y%m%d_%H%M%S).dump

# Restore from logical backup
pg_restore -U newpub -d phiacta --clean --if-exists backup_20260208_143000.dump

# Continuous archiving for point-in-time recovery
# Configure in postgresql.conf:
#   archive_mode = on
#   archive_command = 'cp %p /backups/wal/%f'
#   wal_level = replica
```

### Backup Strategy

| Layer | Method | Frequency | Retention |
|-------|--------|-----------|-----------|
| Full database | `pg_dump` or managed snapshot | Daily | 30 days |
| WAL archiving | Continuous (for PITR) | Continuous | 7 days |
| Alembic migration state | Committed to git | Every change | Forever |
| Application config | Environment variables in secret manager | Every change | Versioned |

### Recovery Procedures

**Scenario: Data corruption or accidental deletion.**
1. Identify the point in time before the corruption (from logs or user report).
2. Restore to a new database from the most recent backup before that time.
3. If using WAL archiving, replay WAL up to the target time for PITR.
4. Verify data integrity by running the health check endpoint against the restored database.
5. Swap the application's `DATABASE_URL` to the restored database.
6. Investigate root cause before resuming writes.

**Scenario: Complete database loss.**
1. Provision a new PostgreSQL instance with pgvector.
2. Run `alembic upgrade head` to create the schema.
3. Restore the most recent `pg_dump` backup.
4. Verify migration state: `alembic current` should show the latest revision.
5. Resume service.

### Backup Testing

Backups that are never tested are not backups. Schedule a monthly restore test:

1. Restore the latest backup to a staging database.
2. Run the full integration test suite against it.
3. Verify claim counts and spot-check recent data.
4. Document the restore time and any issues encountered.

---

## 8. Security Considerations

### Network Security

- **TLS everywhere.** All external traffic terminates TLS at the reverse proxy or load balancer. Internal traffic between the backend and database should also use TLS (configure `sslmode=require` in the database connection string for production).
- **Minimal port exposure.** Only port 443 (HTTPS) is exposed publicly. The database port (5432) is never exposed to the internet. Use VPC peering, private subnets, or firewall rules to restrict database access to the backend service only.
- **CORS.** Configured via `CORS_ORIGINS`. In production, restrict to the specific frontend domains that need access. Never use `*` in production.

### Authentication and Secrets

- **API keys are hashed.** Keys are hashed with bcrypt before storage. The raw key is displayed once at creation and never stored or logged.
- **Secrets in environment variables.** Database credentials, API keys, and salts are injected via environment variables or a secret manager. Never in Docker images, config files, or source control.
- **Key rotation.** Extensions can generate new API keys without downtime. Old keys are revoked immediately. The `API_KEY_SALT` can be rotated, but this invalidates all existing keys -- coordinate with extension operators.

### Input Validation

- **Pydantic validates all API input.** Request bodies, query parameters, and path parameters are validated by Pydantic schemas before reaching service code. Invalid input returns 422 with specific field-level errors.
- **Bundle size limits.** `MAX_BUNDLE_CLAIMS` prevents memory exhaustion from oversized submissions. The default is 500 claims per bundle.
- **Content sanitization.** Claim content is stored as-is (no HTML rendering in the backend), but output extensions that render HTML must sanitize to prevent XSS. The backend API returns JSON only.
- **SQL injection.** SQLAlchemy parameterizes all queries. No raw SQL strings with user input are ever constructed. The `attrs` JSONB field is queried via SQLAlchemy's JSONB operators, not string interpolation.

### Container Security

- **Non-root user.** The production image runs as user `newpub`, not root. This limits the blast radius of container escape vulnerabilities.
- **Minimal base image.** The production stage uses `python:3.12-slim` and installs only runtime dependencies (`libpq5`). No compiler, no build tools, no dev packages.
- **No secrets in images.** The Docker image contains no credentials. All secrets are injected at runtime via environment variables.
- **Image scanning.** Run `trivy image phiacta:latest` or equivalent in CI to catch known vulnerabilities in base images and dependencies. Rebuild images when upstream security patches are released.

### Rate Limiting

- Per-API-key rate limiting is enforced in middleware. Default limits (configurable per key scope):
  - `bundles:write` -- 60 requests/minute (ingestion is expensive)
  - `claims:read` -- 300 requests/minute
  - `query/*` -- 120 requests/minute
- Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are included in every response.
- For v1, rate limiting is in-process (per-replica). At multi-replica scale, use Redis-backed rate limiting for global enforcement.

### Dependency Security

- **Dependabot or Renovate** for automated dependency update PRs.
- **`pip-audit`** in CI to check for known vulnerabilities in Python packages.
- **Lock file.** `uv.lock` or `requirements.txt` pinned to exact versions for reproducible builds. `pyproject.toml` specifies minimum versions; the lock file pins exact versions.

### Audit Logging

Every write operation (bundle submission, claim update, review creation) is logged with the acting agent's ID, timestamp, and request ID. These logs are the audit trail for provenance disputes. In production, ship these logs to a tamper-evident store (append-only S3 bucket, immutable log stream) separate from application logs.

---

## Quick Reference: Common Operations

| Task | Command |
|------|---------|
| Start local dev stack | `docker compose up` |
| Start with pgAdmin | `docker compose --profile debug up` |
| Rebuild after dependency changes | `docker compose build backend` |
| Run migrations (local) | `alembic upgrade head` |
| Run migrations (production) | `docker run --rm -e DATABASE_URL=... phiacta:latest alembic upgrade head` |
| Run tests in Docker | `docker build --target test -t test . && docker run --rm test` |
| Run tests locally | `pytest` |
| Check types | `mypy --strict src/` |
| Lint and format | `ruff check . && ruff format --check .` |
| Create database backup | `pg_dump -Fc -U newpub -d phiacta > backup.dump` |
| Restore database backup | `pg_restore -U newpub -d phiacta --clean --if-exists backup.dump` |
| Build production image | `docker build --target production -t phiacta:latest .` |
| Scan image for vulnerabilities | `trivy image phiacta:latest` |
