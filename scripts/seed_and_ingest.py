"""Local validation harness for Bronze ingestion against a real Supabase Postgres.

Seeds config.connectors from the code registry, ensures a source_instance exists, runs one
ingestion pass and reports what landed in bronze.raw_items. Idempotent: re-running reuses the
same source_instance (looked up by connector_type + display_label) so the watermark persists
and the second run should land 0 new rows.

Usage (needs DATABASE_URL in the environment, e.g. via `uv run --env-file .env`):

    uv run --env-file .env python scripts/seed_and_ingest.py reddit python
    uv run --env-file .env python scripts/seed_and_ingest.py rss https://feeds.bbci.co.uk/news/rss.xml
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from psycopg.types.json import Json

import core.connectors.reddit  # noqa: F401  (import to self-register)
import core.connectors.rss  # noqa: F401  (import to self-register)
from core.connectors.base import get_connector_class, list_connector_descriptors
from core.ingestion.bronze import run_ingestion
from core.models.config import SourceInstance
from core.storage.supabase import SupabaseBronzeStore

PRESETS = {
    "reddit": lambda v: ("reddit", {"subreddit": v, "listing": "new", "limit": 25}, f"r/{v}"),
    "rss": lambda v: ("press_rss", {"feed_url": v}, v),
}


def seed_connectors(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for d in list_connector_descriptors():
            cur.execute(
                """
                insert into config.connectors
                    (type, display_name, capabilities, acquisition, param_schema)
                values (%s, %s, %s, %s, %s)
                on conflict (type) do update set
                    display_name = excluded.display_name,
                    capabilities = excluded.capabilities,
                    acquisition = excluded.acquisition,
                    param_schema = excluded.param_schema,
                    updated_at = now()
                """,
                (
                    d.type,
                    d.display_name,
                    Json(d.capabilities.model_dump()),
                    Json([a.value for a in d.acquisition]),
                    Json(d.param_schema),
                ),
            )
    conn.commit()


def ensure_source_instance(
    conn: psycopg.Connection, connector_type: str, params: dict, display_label: str
) -> SourceInstance:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, created_at from config.source_instances
            where connector_type = %s and display_label = %s
            """,
            (connector_type, display_label),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                insert into config.source_instances (connector_type, params, display_label)
                values (%s, %s, %s)
                returning id, created_at
                """,
                (connector_type, Json(params), display_label),
            )
            row = cur.fetchone()
    conn.commit()
    return SourceInstance(
        id=row[0],
        connector_type=connector_type,
        params=params,
        display_label=display_label,
        created_at=row[1],
    )


def report(conn: psycopg.Connection, source_id: UUID, run_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from bronze.raw_items where source_instance_id = %s", (source_id,)
        )
        total = cur.fetchone()[0]
        cur.execute(
            "select count(*) from bronze.raw_items where fetch_run_id = %s", (run_id,)
        )
        this_run = cur.fetchone()[0]
        cur.execute(
            """
            select connector_type, external_id, left(payload::text, 80)
            from bronze.raw_items where fetch_run_id = %s order by id limit 5
            """,
            (run_id,),
        )
        sample = cur.fetchall()
    print(f"  bronze.raw_items for this source (all runs): {total}")
    print(f"  landed in this run ({run_id}): {this_run}")
    for ct, ext, snippet in sample:
        print(f"    - [{ct}] {ext}  {snippet}...")


async def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in PRESETS:
        print(__doc__)
        sys.exit(2)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set (put it in .env and use `uv run --env-file .env`).")
        sys.exit(2)

    connector_type, params, display_label = PRESETS[sys.argv[1]](sys.argv[2])

    with psycopg.connect(dsn) as conn:
        seed_connectors(conn)
        source = ensure_source_instance(conn, connector_type, params, display_label)
        print(f"source_instance: {source.display_label} ({source.id})")

        connector = get_connector_class(source.connector_type)(source)
        async with SupabaseBronzeStore(dsn) as store:
            started = datetime.now(timezone.utc)
            result = await run_ingestion(connector, store)
        print(f"run {result.run_id}: fetched {result.fetched_count} item(s) in "
              f"{(datetime.now(timezone.utc) - started).total_seconds():.1f}s")
        report(conn, source.id, result.run_id)


if __name__ == "__main__":
    # psycopg's async mode needs the selector loop; Windows defaults to the proactor loop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
