from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from core.connectors.base import Connector, get_connector_class
from core.models.config import SourceInstance
from core.models.raw import BronzeRawItem
from core.storage.base import BronzeStore


@dataclass
class IngestionRunResult:
    run_id: UUID
    source_instance_id: UUID
    connector_type: str
    fetched_count: int
    watermark: datetime


async def run_ingestion(connector: Connector, store: BronzeStore) -> IngestionRunResult:
    """Land everything the connector currently exposes since the last watermark into Bronze.

    No query is pushed down here: Bronze ingestion is source-driven, not feed-driven, so the
    same source is fetched once regardless of how many feeds/queries are bound to it. Query
    pushdown is the future query engine's concern, for a targeted on-demand fetch.

    The watermark advances to the run's start time (not to the max item timestamp seen) so
    nothing the connector hasn't looked at yet is silently skipped on the next run.
    """

    run_id = uuid4()
    run_started_at = datetime.now(timezone.utc)
    source = connector.source

    since = await store.get_watermark(source.id)

    rows = [
        BronzeRawItem(
            connector_type=connector.type,
            source_instance_id=source.id,
            fetch_run_id=run_id,
            external_id=raw.external_id,
            fetched_at=raw.fetched_at,
            connector_version=raw.connector_version,
            payload=raw.payload,
        )
        async for raw in connector.fetch(query=None, since=since)
    ]

    await store.insert_raw_items(rows)
    await store.set_watermark(source.id, run_started_at)

    return IngestionRunResult(
        run_id=run_id,
        source_instance_id=source.id,
        connector_type=connector.type,
        fetched_count=len(rows),
        watermark=run_started_at,
    )


async def run_ingestion_for_sources(
    sources: list[SourceInstance], store: BronzeStore
) -> list[IngestionRunResult]:
    results = []
    for source in sources:
        connector_cls = get_connector_class(source.connector_type)
        results.append(await run_ingestion(connector_cls(source), store))
    return results
