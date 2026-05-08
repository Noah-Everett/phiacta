# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    environment: str = "production"
    log_level: str = "info"
    log_format: str = "json"
    cors_origins: list[str] = []
    database_pool_size: int = 20

    # Auth
    jwt_secret_key: str
    access_token_expire_minutes: int = 43200  # 30 days

    # Forgejo (git backend)
    forgejo_url: str = "http://forgejo:3000"
    forgejo_admin_user: str = "phiacta-admin"
    forgejo_admin_password: str = ""
    forgejo_org: str = "phiacta"
    forgejo_webhook_secret: str = ""
    webhook_callback_url: str = "http://backend:8000/webhooks/forgejo"

    # Rate limiting
    rate_limit_enabled: bool = True
    max_json_body_bytes: int = 1 * 1024 * 1024  # 1 MB for JSON bodies

    # File upload limits
    max_file_size_bytes: int = 25 * 1024 * 1024  # 25 MB per file
    max_upload_files: int = 10_000  # max files per upload request
    max_upload_size_bytes: int = 500 * 1024 * 1024  # 500 MB total per request
    max_repo_size_bytes: int = 1024 * 1024 * 1024  # 1 GB per repo

    # Jobs
    max_active_jobs_per_user: int = 10
    # Grace period before a 'running' job is considered crashed and reset.
    # Must comfortably exceed the longest job timeout_seconds so that
    # rolling-restart of the worker does not cancel jobs that are still
    # legitimately running. Default 600s = 10 minutes (current longest
    # handler timeout is 480s).
    job_recovery_grace_seconds: int = 600

    # Plugins
    enabled_plugins: list[str] = Field(default_factory=list)

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        if len(self.jwt_secret_key) < 32:
            raise ValueError("jwt_secret_key must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Lazy-loaded to avoid import-time failures."""
    return Settings()
