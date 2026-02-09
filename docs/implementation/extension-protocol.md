# Extension Protocol Specification

*How to build, test, and distribute extensions for the NewPublishing knowledge backend.*

*Depends on: `docs/design/synthesis.md` (schema), `docs/implementation/architecture.md` (system architecture), `docs/design/extension-design.md` (API spec).*

---

## 1. Base Class Design

Extensions interact with the backend exclusively through HTTP and WebSocket. They never import backend internals. The `newpublishing-sdk` package provides two abstract base classes — `InputExtension` and `OutputExtension` — plus data classes for the objects they produce and consume.

### InputExtension

An input extension converts real-world artifacts (papers, audio recordings, photos, manual forms) into structured knowledge bundles. The only method you must implement is `ingest()`.

```python
from newpublishing.extensions.base import (
    InputExtension, Source, ExtractionResult,
    ExtractedClaim, ExtractedEdge, ExtractedArtifact,
)

class MyInputExtension(InputExtension):
    name = "my-input"
    version = "1.0.0"
    description = "Converts X into structured claims"

    async def ingest(self, source: Source) -> ExtractionResult:
        # Your domain logic here.
        # Parse the source, extract claims, build relationships.
        claims = [
            ExtractedClaim(
                temp_id="c1",
                content="The extracted assertion",
                claim_type="empirical",
                confidence=0.9,
                attrs={"sample_size": 100},
            )
        ]
        return ExtractionResult(claims=claims)
```

**Key contract:**

- `ingest()` receives a `Source` describing the real-world artifact (type, title, DOI/URL, content hash, and an `attrs` dict for arbitrary metadata).
- `ingest()` returns an `ExtractionResult` containing lists of `ExtractedClaim`, `ExtractedEdge`, and `ExtractedArtifact` objects.
- Claims within a single result reference each other by `temp_id` — short, extension-assigned identifiers that the backend maps to real UUIDs atomically during bundle commit.
- Edges can reference claims inside the bundle (via `source_temp_id` / `target_temp_id`), existing claims in the database (via `target_id`), or not-yet-ingested entities (via `target_external_ref`, which creates a pending reference resolved later).

**Optional override — `validate()`:**

```python
async def validate(self, result: ExtractionResult) -> list[str]:
    warnings = []
    for claim in result.claims:
        if not claim.content.strip():
            warnings.append(f"Claim {claim.temp_id} has empty content")
    return warnings
```

The SDK calls `validate()` before submission. Returning warnings does not block submission — it adds them to the bundle response. Override this to enforce domain-specific quality checks.

### OutputExtension

An output extension queries the knowledge graph and presents results. The only method you must implement is `query()`.

```python
from newpublishing.extensions.base import (
    OutputExtension, QueryRequest, QueryResponse,
)

class MyOutputExtension(OutputExtension):
    name = "my-output"
    version = "1.0.0"
    description = "Presents knowledge as X"

    async def query(self, request: QueryRequest) -> QueryResponse:
        # Use self.client to call backend search/traverse APIs.
        raw = await self.client.search(request.query, top_k=request.top_k)
        return QueryResponse(
            results=raw,
            total_matches=len(raw),
        )
```

**Key contract:**

- `query()` receives a `QueryRequest` with a natural language query string, `top_k`, filters, and an `include` list specifying which optional fields to return (provenance, evidence summaries, etc.).
- `query()` returns a `QueryResponse` with a list of result dicts, a total match count, and an arbitrary metadata dict.
- Output extensions use `self.client` (a `NewPublishingClient` instance, injected by the SDK runner) to call the backend's search, traverse, and view endpoints. They do not hit the database directly.

### Data Classes Reference

| Class | Purpose | Required fields |
|-------|---------|-----------------|
| `Source` | Real-world artifact being processed | `source_type` |
| `ExtractedClaim` | A claim ready for bundle submission | `temp_id`, `content`, `claim_type` |
| `ExtractedEdge` | A relationship between claims | `source_temp_id`, `edge_type` |
| `ExtractedArtifact` | A figure, table, photo, or dataset | `temp_id`, `artifact_type` |
| `ExtractionResult` | Output of `ingest()` | `claims` |
| `QueryRequest` | Input to `query()` | `query` |
| `QueryResponse` | Output of `query()` | `results`, `total_matches` |

All data classes use `@dataclass` with optional fields defaulting to `None`, empty lists, or empty dicts. Every entity supports an `attrs: dict[str, Any]` field for extension-specific metadata that does not belong in the core schema.

---

## 2. Extension Lifecycle

### 2.1 Discovery

The backend maintains a registry of all extensions. Extensions are discoverable via:

```
GET /v1/extensions?type=input&status=active
```

This returns a list of registered extensions with their capabilities, version, and health status. Client applications use this endpoint to offer users a menu of available input/output methods. The registry also powers the admin dashboard (planned for v2) and enables extensions to discover each other for composition.

Discovery is passive — extensions do not announce themselves. The backend pulls health status periodically.

### 2.2 Registration

Before an extension can submit bundles or serve queries, it must register with the backend. Registration is a one-time operation performed by the extension developer (or automated by a deploy script).

**Step 1: Submit the extension manifest** (see Section 4 for format) to the registration endpoint:

```
POST /v1/extensions/register
Authorization: Bearer <admin_api_key>
```

**Step 2: Receive credentials.** The backend validates the manifest, provisions an API key scoped to the declared capabilities, and returns:

```json
{
  "extension_id": "ext-my-input-v1",
  "api_key": "ext_key_live_abc123def456",
  "status": "active",
  "registered_at": "2026-02-08T10:00:00Z"
}
```

The raw API key is shown exactly once. Store it in your extension's environment variables (never in source code).

**Step 3: The extension is now active.** It can make API calls using its key. The backend starts pinging the health check URL if one was provided.

### 2.3 Loading and Initialization

The SDK provides a runner that handles the extension startup sequence:

```python
from newpublishing.extensions.runner import run_extension

from my_extension import MyInputExtension

if __name__ == "__main__":
    run_extension(MyInputExtension())
```

`run_extension()` performs:

1. **Configuration loading.** Reads `NEWPUB_BACKEND_URL` and `NEWPUB_API_KEY` from environment variables (or from a `.env` file).
2. **Client initialization.** Creates a `NewPublishingClient` instance and attaches it to the extension as `self.client`.
3. **Health check registration.** If the extension declares a `health_check_url`, the runner starts a lightweight HTTP server responding to `GET /health`.
4. **Event loop startup.** For event-driven extensions, the runner opens a WebSocket connection to `/v1/subscribe` and routes events to the extension's handler methods.
5. **Ready signal.** Logs "Extension {name} v{version} ready" and begins accepting work.

For input extensions, the runner exposes a local HTTP endpoint (default `:9000/ingest`) that accepts `Source` payloads and delegates to `ingest()`. This is how an orchestrator or CLI tool triggers ingestion.

For output extensions, the runner exposes `:9000/query` and delegates to `query()`.

### 2.4 Health Checks

The backend pings each extension's `health_check_url` every 60 seconds. Expected response:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600
}
```

Extensions that fail health checks for 5 consecutive minutes are marked `degraded`. After 24 hours of continuous failure, they are marked `inactive` and excluded from the discovery endpoint. They are not deleted — re-deploying the extension and passing a health check restores `active` status automatically.

### 2.5 Shutdown

Extensions can be deregistered via:

```
DELETE /v1/extensions/{extension_id}
Authorization: Bearer <admin_api_key>
```

This revokes the API key immediately. In-flight requests from the extension will fail with `401 UNAUTHORIZED`. Bundles already committed are not affected — provenance records are immutable.

---

## 3. SDK / Client Interface

The `newpublishing-sdk` package (installable via `pip install newpublishing-sdk`) provides everything an extension developer needs. It is intentionally thin — it handles auth, HTTP, and serialization so you focus on domain logic.

### NewPublishingClient

The client wraps all backend API calls:

```python
from newpublishing.extensions.client import NewPublishingClient

client = NewPublishingClient(
    base_url="https://api.knowledge-backend.example.com",
    api_key="ext_key_live_abc123def456",
)

# Submit a bundle (used internally by the runner after ingest())
response = await client.submit_bundle(
    result=extraction_result,
    source=source,
    idempotency_key="paper-doi-10.1234/abc",
    contributor_id="user-jane-doe",
)

# Search claims
results = await client.search("effect of X on Y", top_k=20)

# Get a specific claim
claim = await client.get_claim(uuid)

# Traverse the graph
graph = await client.traverse(start=uuid, depth=3, edge_types=["supports", "contradicts"])

# Subscribe to events (async iterator)
async for event in client.subscribe(event_types=["claim_created"]):
    print(event)
```

**Error handling.** The client raises typed exceptions:

| Exception | HTTP Status | When |
|-----------|-------------|------|
| `AuthenticationError` | 401 | Invalid or expired API key |
| `PermissionError` | 403 | Key lacks required scope |
| `NotFoundError` | 404 | Requested entity does not exist |
| `ValidationError` | 422 | Bundle or request failed validation |
| `RateLimitError` | 429 | Too many requests; includes `retry_after` seconds |
| `BackendError` | 500 | Server-side failure |

All exceptions include `request_id` for debugging.

**Retry behavior.** The client automatically retries on `429` and `5xx` errors using exponential backoff (via `tenacity`). Default: 3 retries, 1s/2s/4s delays. Configurable via `NewPublishingClient(max_retries=5, base_delay=0.5)`.

### Extension Runner

The runner is the entry point for deployed extensions. It wraps your extension class with HTTP serving and lifecycle management:

```python
from newpublishing.extensions.runner import run_extension, RunnerConfig

config = RunnerConfig(
    host="0.0.0.0",
    port=9000,
    log_level="info",
)

run_extension(MyInputExtension(), config=config)
```

The runner provides:

- **HTTP server** with `/ingest` (input) or `/query` (output) endpoints.
- **`/health` endpoint** for backend health checks.
- **Structured logging** via `structlog` — JSON output in production, human-readable in development.
- **Graceful shutdown** on SIGTERM/SIGINT.
- **Metrics endpoint** at `/metrics` (Prometheus format, opt-in via `config.enable_metrics=True`).

---

## 4. Plugin Manifest Format

Every extension declares its identity and capabilities in a manifest. The manifest is submitted during registration and can be updated via `PATCH /v1/extensions/{extension_id}`.

```json
{
  "extension_id": "ext-paper-ingest-v2",
  "name": "Paper Ingestion",
  "version": "2.0.0",
  "type": "input",
  "description": "Extracts claims, evidence, and relationships from academic papers (PDF)",
  "author": "NewPublishing Core Team",
  "license": "GPL-3.0",
  "repository": "https://github.com/newpublishing/ext-paper-ingestion",

  "capabilities": {
    "can_write": true,
    "can_read": true,
    "claim_types": ["empirical", "mechanistic", "interpretive", "hypothesis"],
    "edge_types": ["supports", "contradicts", "cites", "explains"],
    "creates_artifacts": true,
    "requires_user_auth": true
  },

  "api_version_required": "v1",
  "sdk_version_required": ">=0.3.0",

  "health_check_url": "https://paper-ext.example.com/health",
  "webhook_url": "https://paper-ext.example.com/webhook",

  "config_schema": {
    "type": "object",
    "properties": {
      "llm_model": {
        "type": "string",
        "default": "gpt-4o",
        "description": "LLM used for claim extraction"
      },
      "max_claims_per_paper": {
        "type": "integer",
        "default": 100,
        "description": "Maximum claims to extract per paper"
      }
    }
  },

  "event_subscriptions": [
    "claim_created",
    "bundle_accepted"
  ]
}
```

### Manifest Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `extension_id` | Yes | Globally unique identifier. Convention: `ext-{name}-v{major}`. |
| `name` | Yes | Human-readable display name. |
| `version` | Yes | Semver string. |
| `type` | Yes | `"input"` or `"output"`. |
| `description` | Yes | One-sentence description shown in the registry. |
| `author` | No | Individual or organization name. |
| `license` | No | SPDX identifier. Extensions that modify backend code must be GPL-3.0 (copyleft). Standalone extensions can use any license. |
| `repository` | No | Source code URL. |
| `capabilities` | Yes | Declares what the extension can do — used for API key scoping. |
| `capabilities.can_write` | Yes | Whether the extension submits bundles. |
| `capabilities.can_read` | Yes | Whether the extension queries claims. |
| `capabilities.claim_types` | No | Which claim types this extension creates. Backend enforces this — submitting an undeclared type returns `403`. |
| `capabilities.edge_types` | No | Which edge types this extension creates. |
| `capabilities.creates_artifacts` | No | Whether the extension attaches artifacts to bundles. |
| `capabilities.requires_user_auth` | No | Whether the extension passes user identity tokens. |
| `api_version_required` | Yes | Backend API version the extension targets. |
| `sdk_version_required` | No | Minimum SDK version required. |
| `health_check_url` | No | URL the backend pings for liveness. Omit for extensions that run on-demand (CLI tools, scripts). |
| `webhook_url` | No | URL for backend-initiated callbacks (e.g., pending reference resolution notifications). |
| `config_schema` | No | JSON Schema describing the extension's runtime configuration. Displayed in the admin interface (v2). |
| `event_subscriptions` | No | Event types the extension subscribes to. Used by the backend to optimize event routing. |

### Validation

The backend validates the manifest at registration time:

- `extension_id` must be unique across all registered extensions.
- `api_version_required` must match a supported API version.
- `capabilities` must be internally consistent (`can_write: false` with non-empty `claim_types` is rejected).
- `health_check_url` and `webhook_url`, if provided, must be reachable (the backend makes a single probe request).

---

## 5. Example Extension Walkthrough

This walkthrough builds a complete input extension that ingests Markdown notes into structured claims. It covers project setup, implementation, local testing, and submission.

### 5.1 Project Setup

```bash
mkdir ext-markdown-notes && cd ext-markdown-notes
python -m venv .venv && source .venv/bin/activate
pip install newpublishing-sdk
```

Create the project structure:

```
ext-markdown-notes/
├── pyproject.toml
├── manifest.json
├── src/
│   └── markdown_notes/
│       ├── __init__.py
│       └── extension.py
└── tests/
    └── test_extension.py
```

`pyproject.toml`:

```toml
[project]
name = "ext-markdown-notes"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "newpublishing-sdk>=0.3.0",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio"]
```

### 5.2 The Manifest

`manifest.json`:

```json
{
  "extension_id": "ext-markdown-notes-v1",
  "name": "Markdown Notes Input",
  "version": "1.0.0",
  "type": "input",
  "description": "Extracts claims from structured Markdown notes",
  "author": "Your Name",
  "capabilities": {
    "can_write": true,
    "can_read": false,
    "claim_types": ["assertion", "observation", "hypothesis"],
    "creates_artifacts": false,
    "requires_user_auth": true
  },
  "api_version_required": "v1"
}
```

### 5.3 The Extension

`src/markdown_notes/extension.py`:

```python
import re
from newpublishing.extensions.base import (
    InputExtension,
    Source,
    ExtractionResult,
    ExtractedClaim,
    ExtractedEdge,
)


class MarkdownNotesExtension(InputExtension):
    name = "markdown-notes"
    version = "1.0.0"
    description = "Extracts claims from structured Markdown notes"

    async def ingest(self, source: Source) -> ExtractionResult:
        """Parse Markdown content and extract claims.

        Expected source.attrs:
            content (str): The raw Markdown text.
            default_claim_type (str): Fallback claim type. Defaults to "assertion".
        """
        markdown = source.attrs.get("content", "")
        default_type = source.attrs.get("default_claim_type", "assertion")

        claims: list[ExtractedClaim] = []
        edges: list[ExtractedEdge] = []

        # Extract bullet points as claims.
        # Lines starting with "- CLAIM:" are treated as explicit claims.
        # Lines starting with "- " are treated as implicit claims.
        lines = markdown.strip().splitlines()
        for i, line in enumerate(lines):
            line = line.strip()

            explicit = re.match(r"^-\s+CLAIM(?:\[(\w+)\])?:\s+(.+)$", line)
            implicit = re.match(r"^-\s+(.+)$", line)

            if explicit:
                claim_type = explicit.group(1) or default_type
                content = explicit.group(2).strip()
            elif implicit:
                claim_type = default_type
                content = implicit.group(1).strip()
            else:
                continue

            claims.append(
                ExtractedClaim(
                    temp_id=f"c{i}",
                    content=content,
                    claim_type=claim_type,
                    confidence=1.0,  # Human-authored = full extraction confidence
                )
            )

        # Link sequential claims: each claim "related_to" the previous one
        # within the same note (lightweight structural relationship).
        for j in range(1, len(claims)):
            edges.append(
                ExtractedEdge(
                    source_temp_id=claims[j].temp_id,
                    target_temp_id=claims[j - 1].temp_id,
                    edge_type="related_to",
                )
            )

        return ExtractionResult(claims=claims, edges=edges)

    async def validate(self, result: ExtractionResult) -> list[str]:
        warnings = []
        if not result.claims:
            warnings.append("No claims extracted from the Markdown source")
        for claim in result.claims:
            if len(claim.content) < 10:
                warnings.append(
                    f"Claim {claim.temp_id} is very short ({len(claim.content)} chars) "
                    "— consider expanding"
                )
        return warnings
```

### 5.4 Running It

`src/markdown_notes/__main__.py`:

```python
from newpublishing.extensions.runner import run_extension
from markdown_notes.extension import MarkdownNotesExtension

run_extension(MarkdownNotesExtension())
```

```bash
export NEWPUB_BACKEND_URL="http://localhost:8000"
export NEWPUB_API_KEY="ext_key_live_..."
python -m markdown_notes
```

The runner starts on `:9000`. Trigger ingestion:

```bash
curl -X POST http://localhost:9000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "markdown_note",
    "title": "Lab Notes 2026-02-08",
    "attrs": {
      "content": "- CLAIM[empirical]: Compound X reduces inflammation by 40%\n- The effect is dose-dependent\n- CLAIM[hypothesis]: NF-kB pathway inhibition is the mechanism"
    }
  }'
```

The runner calls `ingest()`, then `validate()`, then `client.submit_bundle()`. The response includes the created claim IDs and any warnings.

---

## 6. Testing Extensions

The SDK provides test utilities that let you test extensions without a running backend.

### 6.1 Unit Testing `ingest()` and `query()`

Test the core logic in isolation — no HTTP, no backend:

```python
import pytest
from markdown_notes.extension import MarkdownNotesExtension
from newpublishing.extensions.base import Source


@pytest.fixture
def ext():
    return MarkdownNotesExtension()


@pytest.mark.asyncio
async def test_extracts_explicit_claims(ext):
    source = Source(
        source_type="markdown_note",
        attrs={"content": "- CLAIM[empirical]: X reduces Y by 40%"},
    )
    result = await ext.ingest(source)
    assert len(result.claims) == 1
    assert result.claims[0].claim_type == "empirical"
    assert "X reduces Y" in result.claims[0].content


@pytest.mark.asyncio
async def test_extracts_implicit_claims(ext):
    source = Source(
        source_type="markdown_note",
        attrs={"content": "- The effect is dose-dependent"},
    )
    result = await ext.ingest(source)
    assert len(result.claims) == 1
    assert result.claims[0].claim_type == "assertion"


@pytest.mark.asyncio
async def test_creates_edges_between_sequential_claims(ext):
    source = Source(
        source_type="markdown_note",
        attrs={"content": "- Claim one\n- Claim two\n- Claim three"},
    )
    result = await ext.ingest(source)
    assert len(result.claims) == 3
    assert len(result.edges) == 2
    assert result.edges[0].edge_type == "related_to"


@pytest.mark.asyncio
async def test_empty_input_produces_warning(ext):
    source = Source(source_type="markdown_note", attrs={"content": ""})
    result = await ext.ingest(source)
    warnings = await ext.validate(result)
    assert any("No claims extracted" in w for w in warnings)


@pytest.mark.asyncio
async def test_short_claim_warning(ext):
    source = Source(
        source_type="markdown_note",
        attrs={"content": "- Short"},
    )
    result = await ext.ingest(source)
    warnings = await ext.validate(result)
    assert any("very short" in w for w in warnings)
```

Run with: `pytest tests/ -v`

### 6.2 Integration Testing with a Mock Backend

The SDK provides `MockNewPublishingClient` for testing the full submission flow without a real backend:

```python
from newpublishing.extensions.testing import MockNewPublishingClient

@pytest.mark.asyncio
async def test_bundle_submission(ext):
    mock_client = MockNewPublishingClient()
    ext.client = mock_client

    source = Source(
        source_type="markdown_note",
        attrs={"content": "- CLAIM[empirical]: X reduces Y by 40%"},
    )
    result = await ext.ingest(source)
    response = await mock_client.submit_bundle(
        result=result,
        source=source,
        idempotency_key="test-key-1",
        contributor_id="test-user",
    )
    assert response.status == "accepted"
    assert len(response.created_claims) == 1
    assert mock_client.submitted_bundles == 1
```

`MockNewPublishingClient` records all calls so you can assert on what was submitted without network I/O.

### 6.3 End-to-End Testing Against a Live Backend

For full integration tests, spin up the backend with Docker and test against it:

```bash
docker compose up -d
export NEWPUB_BACKEND_URL="http://localhost:8000"
export NEWPUB_API_KEY="ext_key_live_test_..."
pytest tests/e2e/ -v
```

End-to-end tests submit real bundles and verify claims appear in the database via the search API. Use a dedicated test namespace to isolate test data from real data.

### 6.4 CI Pipeline for Extensions

Recommended CI for extension repos:

```yaml
# .github/workflows/ci.yml
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  - run: pip install -e ".[dev]"
  - run: ruff check .
  - run: mypy --strict src/
  - run: pytest tests/ -v --cov=src/ --cov-report=term-missing
```

Type checking with `mypy --strict` is strongly recommended. The SDK's base classes and data classes are fully typed, so your extension inherits type safety automatically.

---

## 7. Publishing and Distributing Extensions

### 7.1 Packaging

Extensions are standard Python packages. Use `pyproject.toml` with a build backend (e.g., `hatchling`, `setuptools`):

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "newpub-ext-markdown-notes"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = ["newpublishing-sdk>=0.3.0"]
description = "Markdown notes input extension for NewPublishing"
license = "MIT"
```

Convention for package naming: `newpub-ext-{name}`. This makes extensions discoverable on PyPI.

### 7.2 Distribution Channels

**PyPI (recommended for most extensions):**

```bash
pip install build twine
python -m build
twine upload dist/*
```

Users install with: `pip install newpub-ext-markdown-notes`

**Docker image (recommended for extensions with heavy dependencies):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
EXPOSE 9000
CMD ["python", "-m", "markdown_notes"]
```

Extensions with system-level dependencies (e.g., the paper ingestion extension depends on `pymupdf` which links C libraries) should ship as Docker images to avoid installation friction.

**Git repository (for development/experimental extensions):**

```bash
pip install git+https://github.com/yourname/ext-markdown-notes.git
```

### 7.3 The Extension Registry

The NewPublishing project maintains a curated extension registry at `github.com/newpublishing/extension-registry` (planned). The registry is a JSON file listing vetted extensions with metadata:

```json
{
  "extensions": [
    {
      "extension_id": "ext-paper-ingest-v2",
      "name": "Paper Ingestion",
      "pypi_package": "newpub-ext-paper-ingestion",
      "docker_image": "ghcr.io/newpublishing/ext-paper-ingestion:2.0.0",
      "verified": true,
      "category": "input",
      "tags": ["papers", "pdf", "ai-extraction"]
    }
  ]
}
```

Extensions in the registry are:

- **Verified:** The maintainers have reviewed the code for quality, security, and adherence to the extension protocol.
- **Tested:** They pass the SDK's conformance test suite (see below).
- **Listed:** They appear in the `GET /v1/extensions` discovery endpoint with a `verified: true` badge.

Unverified extensions can still register with any backend instance — the registry is opt-in curation, not a gatekeeper.

### 7.4 Conformance Test Suite

The SDK ships a conformance test runner that validates any extension against the protocol:

```bash
newpub-test-conformance ./manifest.json
```

The conformance suite checks:

1. **Manifest validity.** All required fields present, types correct, no unknown fields.
2. **Base class compliance.** The extension class extends `InputExtension` or `OutputExtension` and implements all required methods.
3. **Return type correctness.** `ingest()` returns `ExtractionResult`, `query()` returns `QueryResponse`.
4. **Temp ID consistency.** All `temp_id` references in edges resolve to claims or artifacts in the same result.
5. **Idempotency.** Calling `ingest()` twice with the same source produces equivalent results.
6. **Error handling.** The extension does not crash on empty input, malformed sources, or missing `attrs` keys.
7. **Health check endpoint.** If declared, `/health` responds with 200 and the expected JSON shape.

Passing the conformance suite is required for inclusion in the curated registry.

### 7.5 Versioning and Compatibility

Extensions follow semver independently of the backend:

- **Patch (1.0.x):** Bug fixes. No change to extraction behavior.
- **Minor (1.x.0):** New features (e.g., extracting a new claim type). Backwards compatible.
- **Major (x.0.0):** Breaking changes to extraction behavior, manifest format, or required attrs.

When the backend releases a new API version (`/v2/`), extensions continue working on `/v1/` until they choose to migrate. The backend serves both versions simultaneously for at least 6 months. The SDK documents migration guides for each API version bump.

Extensions should pin their `newpublishing-sdk` dependency to a compatible range (e.g., `>=0.3.0,<1.0.0`) to avoid breaking on SDK major version changes.

### 7.6 Security Considerations

- **API keys are secrets.** Never commit them to source code. Use environment variables or a secrets manager. The SDK reads from `NEWPUB_API_KEY` by default.
- **Extensions run as separate processes.** They cannot access the backend database, filesystem, or memory. The HTTP API is the only interface.
- **Capability enforcement.** The backend enforces the capabilities declared in the manifest. An extension that declares `claim_types: ["empirical"]` cannot submit `"theorem"` claims — the backend returns `403 FORBIDDEN`.
- **Rate limiting.** Each API key has per-minute read and write rate limits set during registration. The SDK's client handles `429` responses with automatic backoff.
- **Bundle size limits.** The backend enforces `MAX_BUNDLE_CLAIMS` (default 500). Extensions processing large sources should split into multiple bundles with cross-references.
- **Input sanitization.** The backend validates all bundle content. Extensions do not need to sanitize for SQL injection or similar attacks — the API layer handles this. However, extensions should validate their own inputs (e.g., checking that a PDF file is actually a PDF before parsing it).

---

## Appendix: Quick Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEWPUB_BACKEND_URL` | Yes | — | Base URL of the backend API |
| `NEWPUB_API_KEY` | Yes | — | Extension API key |
| `NEWPUB_LOG_LEVEL` | No | `info` | Logging level |
| `NEWPUB_RUNNER_HOST` | No | `0.0.0.0` | Host for the extension's HTTP server |
| `NEWPUB_RUNNER_PORT` | No | `9000` | Port for the extension's HTTP server |

### Extension Checklist

Before publishing your extension:

- [ ] `ingest()` or `query()` implemented and tested
- [ ] `validate()` overridden with domain-specific checks (if applicable)
- [ ] `manifest.json` complete with accurate capabilities
- [ ] Unit tests cover happy path, edge cases, and empty input
- [ ] `mypy --strict` passes
- [ ] `ruff check` passes
- [ ] Conformance test suite passes (`newpub-test-conformance`)
- [ ] API key stored in environment variable, not in code
- [ ] README documents required `attrs` keys and expected source format
- [ ] `pyproject.toml` declares `newpublishing-sdk` dependency with version range
