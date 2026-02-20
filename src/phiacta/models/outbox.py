# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class OutboxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OutboxOperation(str, enum.Enum):
    CREATE_REPO = "create_repo"
    COMMIT_FILES = "commit_files"
    CREATE_BRANCH = "create_branch"
    RENAME_BRANCH = "rename_branch"
    SETUP_BRANCH_PROTECTION = "setup_branch_protection"
    SETUP_WEBHOOK = "setup_webhook"


class Outbox(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outbox"

    operation: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_outbox_status",
        ),
        Index(
            "idx_outbox_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
