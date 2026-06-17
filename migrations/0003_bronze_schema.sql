create schema if not exists bronze;

-- Append-only, immutable landing zone: raw as the connector delivered it. Exists so
-- reprocessing never requires re-scraping. No unique constraint on the natural key
-- (connector_type, external_id) since the same item may be re-fetched across runs.
create table bronze.raw_items (
    id uuid primary key default gen_random_uuid(),
    connector_type text not null references config.connectors (type),
    source_instance_id uuid not null references config.source_instances (id),
    external_id text not null,
    fetched_at timestamptz not null default now(),
    connector_version text not null,
    fetch_run_id uuid not null,
    payload jsonb,
    payload_uri text,
    created_at timestamptz not null default now()
);

create index raw_items_source_fetched_idx on bronze.raw_items (source_instance_id, fetched_at);
create index raw_items_natural_key_idx on bronze.raw_items (connector_type, external_id);
