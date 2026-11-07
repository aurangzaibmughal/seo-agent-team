-- ==============================================================================
-- Schema for SEO Agent Team (M1 + M2 + M3)
-- Compatible with Supabase Postgres + Row Level Security (RLS)
-- ==============================================================================

create extension if not exists "uuid-ossp";

-- 1. PROJECTS
create table if not exists public.projects (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid references auth.users(id) on delete cascade default auth.uid(),
    url text not null,
    domain text not null,
    platform text default 'unknown',
    agency_name text,
    agency_logo_url text,
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 2. JOBS
create table if not exists public.jobs (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references public.projects(id) on delete cascade,
    user_id uuid references auth.users(id) on delete cascade default auth.uid(),
    target_url text not null,
    status text not null default 'pending',
    current_step text not null default 'init',
    max_pages integer not null default 200,
    pages_crawled integer not null default 0,
    in_sitemap_not_crawled integer default 0,
    crawled_not_in_sitemap integer default 0,
    sitemap_found boolean default false,
    error text,
    cost_usd numeric(10, 4) default 0.0000,
    created_at timestamptz default timezone('utc'::text, now()) not null,
    updated_at timestamptz default timezone('utc'::text, now()) not null
);

-- 3. CRAWL PAGES
create table if not exists public.crawl_pages (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    url text not null,
    status_code integer not null,
    title text,
    meta_desc text,
    h1 text,
    canonical text,
    word_count integer default 0,
    links_out integer default 0,
    inlinks_count integer default 0,
    indexable boolean default true,
    indexability_status text default 'indexable',
    redirect_url text,
    content_type text default 'text/html',
    response_time_ms integer default 0,
    outlinks_list jsonb default '[]'::jsonb,
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 4. CRAWL LINKS
create table if not exists public.crawl_links (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    source_url text not null,
    target_url text not null,
    anchor_text text default '',
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 5. PSI RESULTS
create table if not exists public.psi_results (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    url text not null,
    strategy text not null,
    performance_score integer,
    lcp_ms numeric(10, 2),
    cls numeric(10, 4),
    inp_or_tbt_ms numeric(10, 2),
    fcp_ms numeric(10, 2),
    ttfb_ms numeric(10, 2),
    raw_json jsonb,
    error text,
    fetched_at timestamptz default timezone('utc'::text, now()) not null
);

-- 6. AGENT RUNS (with mode column)
create table if not exists public.agent_runs (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    agent text not null,
    status text not null default 'pending',
    mode text default 'fallback', -- 'llm' or 'fallback'
    input_ref text[],
    output_json jsonb,
    confidence numeric(3, 2) default 1.0,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 7. GOOGLE CONNECTIONS (Encrypted OAuth Tokens)
create table if not exists public.google_connections (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid references auth.users(id) on delete cascade default auth.uid(),
    google_email text not null,
    encrypted_refresh_token text not null,
    scopes text[] not null,
    created_at timestamptz default timezone('utc'::text, now()) not null,
    revoked_at timestamptz
);

-- 8. PROJECT GOOGLE LINKS
create table if not exists public.project_google_links (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references public.projects(id) on delete cascade not null,
    gsc_site_url text,
    ga4_property_id text,
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 9. PERFORMANCE SNAPSHOTS (GSC & GA4 Metrics)
create table if not exists public.performance_snapshots (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    snapshot_json jsonb not null,
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- 10. REPORTS
create table if not exists public.reports (
    id uuid primary key default uuid_generate_v4(),
    job_id uuid references public.jobs(id) on delete cascade not null,
    file_url text not null,
    format text not null default 'pdf',
    created_at timestamptz default timezone('utc'::text, now()) not null
);

-- Row Level Security
alter table public.projects enable row level security;
alter table public.jobs enable row level security;
alter table public.crawl_pages enable row level security;
alter table public.crawl_links enable row level security;
alter table public.psi_results enable row level security;
alter table public.agent_runs enable row level security;
alter table public.google_connections enable row level security;
alter table public.project_google_links enable row level security;
alter table public.performance_snapshots enable row level security;
alter table public.reports enable row level security;

create policy "Users can view own google_connections" on public.google_connections for select using (auth.uid() is null or auth.uid() = user_id);
create policy "Users can modify own google_connections" on public.google_connections for all using (auth.uid() is null or auth.uid() = user_id);
