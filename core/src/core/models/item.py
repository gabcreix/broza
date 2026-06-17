from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentKind(str, Enum):
    ARTICLE = "article"
    FORUM_POST = "forum_post"
    COMMENT = "comment"
    SOCIAL_POST = "social_post"


class Item(BaseModel):
    """The canonical contract: every connector's output is mapped to this model, and nothing
    downstream (enrichment, query engine, gold, newsletter) knows the concrete source."""

    id: UUID
    raw_item_id: UUID
    source_instance_id: UUID
    source_type: str
    content_kind: ContentKind
    canonical_url: str | None = None
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    lang: str | None = None
    full_text: str | None = None
    summary: str | None = None
    parent_id: UUID | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    dedup_cluster_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
