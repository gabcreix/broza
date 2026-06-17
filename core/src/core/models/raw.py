from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RawPayload(BaseModel):
    """What a connector yields. The ingestion layer stamps run-level fields
    (id, source_instance_id, fetch_run_id) before landing it in bronze.raw_items."""

    external_id: str
    fetched_at: datetime
    connector_version: str
    payload: dict[str, Any]


class BronzeRawItem(BaseModel):
    """A RawPayload stamped with run-level fields — one row of bronze.raw_items."""

    connector_type: str
    source_instance_id: UUID
    fetch_run_id: UUID
    external_id: str
    fetched_at: datetime
    connector_version: str
    payload: dict[str, Any]
