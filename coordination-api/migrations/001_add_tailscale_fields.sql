-- Migration: Add connectivity fields to nodes table
-- Run this against an existing database to add support for UPnP/direct networking modes.

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS public_ip TEXT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS connectivity_type TEXT NOT NULL DEFAULT 'direct';
