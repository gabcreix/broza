create schema if not exists config;

-- Registry mirror of the connectors registered in code (core/connectors). Can be
-- populated on startup by calling list_connector_descriptors() and upserting here.
create table config.connectors (
    type text primary key,
    display_name text not null,
    capabilities jsonb not null default '{}'::jsonb,
    acquisition jsonb not null default '[]'::jsonb,
    param_schema jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table config.source_instances (
    id uuid primary key default gen_random_uuid(),
    connector_type text not null references config.connectors (type),
    params jsonb not null default '{}'::jsonb,
    display_label text not null,
    created_at timestamptz not null default now()
);

create table config.queries (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    definition jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table config.feed_definitions (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    status text not null default 'draft',
    output jsonb not null default '{}'::jsonb,
    schedule jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- One row per source<->query pair bound to a feed.
create table config.feed_bindings (
    feed_id uuid not null references config.feed_definitions (id) on delete cascade,
    source_instance_id uuid not null references config.source_instances (id) on delete cascade,
    query_id uuid not null references config.queries (id) on delete cascade,
    primary key (feed_id, source_instance_id, query_id)
);

-- Queries applied across every source bound to the feed.
create table config.feed_global_queries (
    feed_id uuid not null references config.feed_definitions (id) on delete cascade,
    query_id uuid not null references config.queries (id) on delete cascade,
    primary key (feed_id, query_id)
);
