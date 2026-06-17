from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from core.models.raw import BronzeRawItem


class BronzeStore(ABC):
    """What the ingestion layer needs from storage to land raw payloads and track
    per-source watermarks. Swappable independently of the connectors that produce rows."""

    @abstractmethod
    async def get_watermark(self, source_instance_id: UUID) -> datetime | None: ...

    @abstractmethod
    async def set_watermark(self, source_instance_id: UUID, value: datetime) -> None: ...

    @abstractmethod
    async def insert_raw_items(self, rows: list[BronzeRawItem]) -> None: ...
