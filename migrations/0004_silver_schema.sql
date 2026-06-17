create schema if not exists silver;

-- The canonical Item, conformed/deduplicated/enriched. This is the reuse boundary: the
-- core produces up to here, each app builds its own Gold on top.
create table silver.items (
    id uuid primary key default gen_random_uuid(),
    raw_item_id uuid not null references bronze.raw_items (id),
    source_instance_id uuid not null references config.source_instances (id),
    source_type text not null,
    content_kind text not null check (content_kind in ('article', 'forum_post', 'comment', 'social_post')),
    canonical_url text,
    title text,
    author text,
    published_at timestamptz,
    fetched_at timestamptz not null,
    lang text,
    full_text text,
    summary text,
    parent_id uuid references silver.items (id),
    metrics jsonb not null default '{}'::jsonb,
    entities jsonb not null default '[]'::jsonb,
    topics text[] not null default '{}',
    dedup_cluster_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Upsert/merge key: canonical_url when present, otherwise (source_instance_id, raw natural key).
create unique index items_source_canonical_url_idx on silver.items (source_instance_id, canonical_url)
    where canonical_url is not null;
create index items_dedup_cluster_idx on silver.items (dedup_cluster_id);
create index items_topics_idx on silver.items using gin (topics);
create index items_parent_idx on silver.items (parent_id);

-- text-embedding-3-small -> 1536 dims. Swap dimension/index if the embeddings provider changes.
create table silver.item_embeddings (
    item_id uuid not null references silver.items (id) on delete cascade,
    model text not null,
    embedding vector(1536) not null,
    created_at timestamptz not null default now(),
    primary key (item_id, model)
);

create index item_embeddings_hnsw_idx on silver.item_embeddings using hnsw (embedding vector_cosine_ops);

-- On-demand translation cache; the original is always kept on silver.items.
create table silver.translations (
    item_id uuid not null references silver.items (id) on delete cascade,
    lang text not null,
    title text,
    text text,
    created_at timestamptz not null default now(),
    primary key (item_id, lang)
);
