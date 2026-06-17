from __future__ import annotations

from datetime import datetime
from types import TracebackType
from uuid import UUID

import psycopg
from psycopg.types.json import Json

from core.models.raw import BronzeRawItem
from core.storage.base import BronzeStore


class SupabaseBronzeStore(BronzeStore):
    """Direct Postgres access (psycopg, async) against the Supabase-hosted bronze/config
    schemas. Holds one connection open for the lifetime of the `async with` block, since a
    store is normally scoped to a single ingestion run."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: psycopg.AsyncConnection | None = None

    async def __aenter__(self) -> SupabaseBronzeStore:
        self._conn = await psycopg.AsyncConnection.connect(self._dsn)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            await self._conn.close()

    @property
    def _connection(self) -> psycopg.AsyncConnection:
        if self._conn is None:
            raise RuntimeError("SupabaseBronzeStore must be used as an 'async with' context manager")
        return self._conn

    async def get_watermark(self, source_instance_id: UUID) -> datetime | None:
        async with self._connection.cursor() as cur:
            await cur.execute(
                "select watermark from bronze.source_watermarks where source_instance_id = %s",
                (source_instance_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_watermark(self, source_instance_id: UUID, value: datetime) -> None:
        async with self._connection.cursor() as cur:
            await cur.execute(
                """
                insert into bronze.source_watermarks (source_instance_id, watermark)
                values (%s, %s)
                on conflict (source_instance_id)
                do update set watermark = excluded.watermark, updated_at = now()
                """,
                (source_instance_id, value),
            )
        await self._connection.commit()

    async def insert_raw_items(self, rows: list[BronzeRawItem]) -> None:
        if not rows:
            return
        async with self._connection.cursor() as cur:
            await cur.executemany(
                """
                insert into bronze.raw_items
                    (connector_type, source_instance_id, external_id, fetched_at,
                     connector_version, fetch_run_id, payload)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        r.connector_type,
                        r.source_instance_id,
                        r.external_id,
                        r.fetched_at,
                        r.connector_version,
                        r.fetch_run_id,
                        Json(r.payload),
                    )
                    for r in rows
                ],
            )
        await self._connection.commit()
