# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from functools import lru_cache

from pydantic import model_validator
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
    auto_install_layers: bool = True

    # Auth
    jwt_secret_key: str
    access_token_expire_minutes: int = 1440

    model_config = {"env_file": ".env"}

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        if len(self.jwt_secret_key) < 32:
            raise ValueError("jwt_secret_key must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance. Lazy-loaded to avoid import-time failures."""
    return Settings()
