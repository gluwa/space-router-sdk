-- Supabase SQL schema for Space Router Coordination API
-- Run this in the Supabase SQL Editor to set up the database.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- API Keys table
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_key_hash ON api_keys (key_hash) WHERE is_active = TRUE;

-- Nodes table
CREATE TABLE nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    endpoint_url TEXT NOT NULL,
    public_ip TEXT,
    connectivity_type TEXT NOT NULL DEFAULT 'direct',
    node_type TEXT NOT NULL DEFAULT 'residential',
    status TEXT NOT NULL DEFAULT 'online',
    health_score FLOAT NOT NULL DEFAULT 1.0,
    region TEXT,
    label TEXT,
    ip_type TEXT,
    ip_region TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_nodes_status_health ON nodes (status, health_score DESC) WHERE status = 'online';

-- Route outcomes table (for health score calculation)
CREATE TABLE route_outcomes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    success BOOLEAN NOT NULL,
    latency_ms INTEGER NOT NULL,
    bytes_transferred INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_route_outcomes_node_id ON route_outcomes (node_id, created_at DESC);

-- Request logs table (written by proxy-gateway)
CREATE TABLE request_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id TEXT NOT NULL,
    api_key_id TEXT,
    node_id TEXT,
    method TEXT NOT NULL,
    target_host TEXT NOT NULL,
    status_code INTEGER,
    bytes_sent INTEGER NOT NULL DEFAULT 0,
    bytes_received INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_request_logs_api_key ON request_logs (api_key_id, created_at DESC);
CREATE INDEX idx_request_logs_created ON request_logs (created_at DESC);

-- Auto-update updated_at on nodes
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER nodes_updated_at
    BEFORE UPDATE ON nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Row Level Security (RLS) — service role bypasses RLS
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE route_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_logs ENABLE ROW LEVEL SECURITY;
