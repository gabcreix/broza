from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SourceInstance(BaseModel):
    """A source is a connector instance: a type plus its parameters (e.g. reddit + subreddit)."""

    id: UUID
    connector_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    display_label: str
    created_at: datetime


class QueryDefinitionBody(BaseModel):
    """Queries are the unified topic mechanism: natural language and/or structured filters,
    used identically whether bound to one source or applied globally across a feed."""

    natural_language: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class QueryDefinition(BaseModel):
    id: UUID
    name: str
    definition: QueryDefinitionBody
    created_at: datetime


class FeedOutput(BaseModel):
    format: str
    channel: str
    template: str | None = None


class FeedSchedule(BaseModel):
    mode: Literal["on_demand", "scheduled"]
    frequency: str | None = None
    window: str | None = None


class FeedDefinition(BaseModel):
    """Ties everything together: bindings, global queries and output/schedule. Doubles as a
    saved search, a newsletter spec and an API input."""

    id: UUID
    name: str
    status: str
    output: FeedOutput
    schedule: FeedSchedule
    created_at: datetime
    updated_at: datetime


class FeedBinding(BaseModel):
    """One row per source<->query pair attached to a feed."""

    feed_id: UUID
    source_instance_id: UUID
    query_id: UUID


class FeedGlobalQuery(BaseModel):
    """A query applied across every source bound to the feed."""

    feed_id: UUID
    query_id: UUID
