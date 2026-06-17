-- High-water mark per source so re-running ingestion never re-lands already-fetched content.
create table bronze.source_watermarks (
    source_instance_id uuid primary key references config.source_instances (id) on delete cascade,
    watermark timestamptz not null,
    updated_at timestamptz not null default now()
);
