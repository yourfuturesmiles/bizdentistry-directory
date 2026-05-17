-- BizDentistry Directory — Supabase Schema
-- Run this in the Supabase SQL Editor in order.
-- After running, immediately test RLS (see comments at bottom).

-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE agents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    slug                TEXT UNIQUE NOT NULL,
    website             TEXT,
    listings_url        TEXT,
    logo_url            TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT false,
    scrape_enabled      BOOLEAN NOT NULL DEFAULT true,
    priority_rank       INTEGER NOT NULL DEFAULT 99,
    subscription_tier   TEXT,
    max_listings        INTEGER NOT NULL DEFAULT 10,
    featured_enabled    BOOLEAN NOT NULL DEFAULT false,
    monthly_budget      NUMERIC,
    budget_notes        TEXT,
    last_scraped_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE listings (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id                UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    external_id             TEXT NOT NULL,
    title                   TEXT,
    location                TEXT,
    postcode_area           TEXT,
    region_normalised       TEXT,
    latitude                NUMERIC,
    longitude               NUMERIC,
    region                  TEXT,
    practice_type           TEXT,
    tenure                  TEXT,
    num_surgeries           INTEGER,
    asking_price            TEXT,
    asking_price_pence      BIGINT,
    asking_price_history    JSONB NOT NULL DEFAULT '[]',
    turnover                TEXT,
    ebitda_associate_led    TEXT,
    ebitda_owner_operated   TEXT,
    uda_value               TEXT,
    highlights              TEXT[],
    listing_url             TEXT,
    image_url               TEXT,
    is_featured             BOOLEAN NOT NULL DEFAULT false,
    is_active               BOOLEAN NOT NULL DEFAULT true,
    delisted_at             TIMESTAMPTZ,
    delisted_reason         TEXT,
    scrape_hash             TEXT,
    scraped_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scraper_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID REFERENCES agents(id) ON DELETE SET NULL,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    listings_found      INTEGER,
    listings_new        INTEGER,
    listings_updated    INTEGER,
    listings_delisted   INTEGER,
    error_message       TEXT,
    duration_ms         INTEGER
);

-- Schema-ready for v2; not used in v1 application code
CREATE TABLE enquiries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id  UUID REFERENCES listings(id) ON DELETE SET NULL,
    agent_id    UUID REFERENCES agents(id) ON DELETE SET NULL,
    buyer_email TEXT,
    buyer_name  TEXT,
    message     TEXT,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Deduplication key for scraper upserts
CREATE UNIQUE INDEX listings_agent_external_id ON listings(agent_id, external_id);

-- Public listing query performance
CREATE INDEX listings_active_agent ON listings(agent_id, is_active, is_featured, scraped_at DESC);
CREATE INDEX listings_region ON listings(region_normalised, practice_type);

-- Scraper run history lookups
CREATE INDEX scraper_runs_agent_time ON scraper_runs(agent_id, run_at DESC);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE agents    ENABLE ROW LEVEL SECURITY;
ALTER TABLE listings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraper_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE enquiries ENABLE ROW LEVEL SECURITY;

-- Public: read active agents only
CREATE POLICY "public_read_agents" ON agents
    FOR SELECT
    USING (is_active = true);

-- Public: read active listings from active agents only
CREATE POLICY "public_read_listings" ON listings
    FOR SELECT
    USING (
        is_active = true
        AND EXISTS (
            SELECT 1 FROM agents
            WHERE agents.id = listings.agent_id
            AND agents.is_active = true
        )
    );

-- Public: no read on scraper_runs or enquiries
-- (service role key bypasses RLS — scrapers and admin use service role)

-- ============================================================
-- SEED DATA (development only — delete before production)
-- ============================================================

-- Uncomment to insert test agents for RLS verification:
--
-- INSERT INTO agents (name, slug, website, listings_url, logo_url, is_active, priority_rank, max_listings)
-- VALUES
--   ('Christie & Co', 'christie', 'https://www.christie.com', 'https://www.christie.com/dental-practices-for-sale/', '', true, 1, 20),
--   ('Dental Elite', 'dental-elite', 'https://dentalelite.co.uk', 'https://dentalelite.co.uk/practices/', '', true, 2, 15),
--   ('Lily Head', 'lily-head', 'https://dentalpracticesales.co.uk', 'https://dentalpracticesales.co.uk/dental-practices/', '', true, 3, 10);

-- ============================================================
-- RLS VERIFICATION TEST (run after inserting seed data)
-- ============================================================
-- 1. In Supabase SQL editor, run:
--      SELECT * FROM listings;
--    This uses the service role — should return all rows.
--
-- 2. In your Python backend, connect with SUPABASE_ANON_KEY and run:
--      client.table("listings").select("*").execute()
--    Should return only rows where is_active=true AND agent is_active=true.
--    If it returns EMPTY with no error when rows exist → RLS policy missing or wrong.
--    Fix before writing any scraper or frontend code.
--
-- 3. Confirm SUPABASE_SERVICE_KEY bypasses RLS (returns all rows including inactive).
