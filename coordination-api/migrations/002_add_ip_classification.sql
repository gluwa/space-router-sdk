-- Migration: Add IP classification fields to nodes table
-- These are populated automatically at registration via ipinfo.io.

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS ip_type TEXT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS ip_region TEXT;
