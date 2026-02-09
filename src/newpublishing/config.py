# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    openai_api_key: str = ""
    environment: str = "production"
    log_level: str = "info"
    log_format: str = "json"
    cors_origins: list[str] = []
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    database_pool_size: int = 20
    max_bundle_claims: int = 500
    max_traversal_depth: int = 10

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Lazy-loaded to avoid import-time failures."""
    return Settings()
