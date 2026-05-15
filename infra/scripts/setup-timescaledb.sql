-- Cadence — TimescaleDB Initialization Script
-- This script runs automatically on first container startup
-- via the /docker-entrypoint-initdb.d/ mount.

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Verify extension is active
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    RAISE NOTICE 'TimescaleDB extension enabled successfully';
  ELSE
    RAISE EXCEPTION 'TimescaleDB extension failed to initialize';
  END IF;
END
$$;
