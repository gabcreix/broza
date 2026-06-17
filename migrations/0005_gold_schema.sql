create schema if not exists gold;

-- Recomputed per execution (run_id) so re-running never duplicates a feed's output.
create table gold.feed_runs (
    id uuid primary key default gen_random_uuid(),
    feed_id uuid not null references config.feed_definitions (id),
    run_at timestamptz not null default now(),
    window_start timestamptz not null,
    window_end timestamptz not null,
    status text not null default 'pending',
    item_count integer not null default 0
);

create table gold.feed_items (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references gold.feed_runs (id) on delete cascade,
    item_id uuid not null references silver.items (id),
    relevance_score double precision not null,
    rank integer not null,
    matched_queries text[] not null default '{}',
    reason text
);

create index feed_items_run_rank_idx on gold.feed_items (run_id, rank);

create table gold.topic_trends (
    topic text not null,
    period date not null,
    source_type text not null,
    volume integer not null default 0,
    primary key (topic, period, source_type)
);
