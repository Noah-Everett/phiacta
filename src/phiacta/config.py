# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from functools import lru_cache

from pydantic import model_validator
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
    access_token_expire_minutes: int = 1440

    # Forgejo (git backend)
    forgejo_url: str = "http://forgejo:3000"
    forgejo_admin_user: str = "phiacta-admin"
    forgejo_admin_password: str = ""
    forgejo_org: str = "phiacta"
    forgejo_webhook_secret: str = ""

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
