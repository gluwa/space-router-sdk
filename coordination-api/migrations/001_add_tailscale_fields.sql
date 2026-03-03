-- Migration: Add Tailscale connectivity fields to nodes table
-- Run this against an existing database to add support for Tailscale networking.

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS public_ip TEXT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS connectivity_type TEXT NOT NULL DEFAULT 'direct';
