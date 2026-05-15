-- ═══════════════════════════════════════════════════════════════════════════════
-- Cadence — TimescaleDB Hypertable Conversion, Indexes, Retention & Compression
-- Run this AFTER the base Drizzle migration has created all tables.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ─── Hypertable Conversions ──────────────────────────────────────────────────

-- observations: primary time-series table, highest write volume
SELECT create_hypertable('observations', 'time',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

-- feature_vectors: computed aggregates per window
SELECT create_hypertable('feature_vectors', 'time',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

-- baseline_snapshots: rolling baseline state
SELECT create_hypertable('baseline_snapshots', 'time',
  chunk_time_interval => INTERVAL '7 days',
  if_not_exists => TRUE
);

-- drift_scores: per-window scoring results
SELECT create_hypertable('drift_scores', 'time',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

-- ingestion_metrics: per-endpoint throughput counters
SELECT create_hypertable('ingestion_metrics', 'time',
  chunk_time_interval => INTERVAL '1 hour',
  if_not_exists => TRUE
);

-- ─── Indexes ─────────────────────────────────────────────────────────────────

-- observations: query by endpoint + time range (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_observations_endpoint_time
  ON observations (endpoint_id, time DESC);

-- observations: query by endpoint + segment + time (segmented analysis)
CREATE INDEX IF NOT EXISTS idx_observations_segment
  ON observations (endpoint_id, segmentation_key, time DESC);

-- feature_vectors: lookup by endpoint + time
CREATE INDEX IF NOT EXISTS idx_fv_endpoint_time
  ON feature_vectors (endpoint_id, time DESC);

-- feature_vectors: segmented feature vector queries
CREATE INDEX IF NOT EXISTS idx_fv_segment
  ON feature_vectors (endpoint_id, segmentation_key, time DESC);

-- baseline_snapshots: find active baseline for endpoint + segment
CREATE INDEX IF NOT EXISTS idx_bs_endpoint_active
  ON baseline_snapshots (endpoint_id, segmentation_key, is_active, time DESC);

-- drift_scores: timeline queries for endpoint drift history
CREATE INDEX IF NOT EXISTS idx_ds_endpoint_time
  ON drift_scores (endpoint_id, time DESC);

-- ─── Retention Policies ──────────────────────────────────────────────────────

-- observations: 90 days retention (raw payloads are expensive to store)
SELECT add_retention_policy('observations',
  drop_after => INTERVAL '90 days',
  if_not_exists => TRUE
);

-- feature_vectors: 180 days retention (compressed aggregates, cheaper)
SELECT add_retention_policy('feature_vectors',
  drop_after => INTERVAL '180 days',
  if_not_exists => TRUE
);

-- drift_scores: 365 days retention (lightweight, keep for trend analysis)
SELECT add_retention_policy('drift_scores',
  drop_after => INTERVAL '365 days',
  if_not_exists => TRUE
);

-- ─── Compression Policies ────────────────────────────────────────────────────

-- observations: compress chunks older than 7 days (~90% storage reduction)
ALTER TABLE observations SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'endpoint_id, segmentation_key',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('observations',
  compress_after => INTERVAL '7 days',
  if_not_exists => TRUE
);

-- feature_vectors: compress chunks older than 14 days
ALTER TABLE feature_vectors SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'endpoint_id, segmentation_key',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('feature_vectors',
  compress_after => INTERVAL '14 days',
  if_not_exists => TRUE
);
