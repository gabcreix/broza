from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RawPayload(BaseModel):
    """What a connector yields. The ingestion layer stamps run-level fields
    (id, source_instance_id, fetch_run_id) before landing it in bronze.raw_items."""

    external_id: str
    fetched_at: datetime
    connector_version: str
    payload: dict[str, Any]
