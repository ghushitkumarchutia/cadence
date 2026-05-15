import { pgTable, uuid, text, jsonb, timestamp, integer } from "drizzle-orm/pg-core";

// Note: This must be converted to a hypertable via custom SQL migration:
// SELECT create_hypertable('feature_vectors', 'time', chunk_time_interval => INTERVAL '1 day');
// SELECT add_retention_policy('feature_vectors', INTERVAL '180 days');
// SELECT add_compression_policy('feature_vectors', COMPRESS_AFTER => INTERVAL '14 days');
export const featureVectors = pgTable("feature_vectors", {
  time: timestamp("time", { withTimezone: true }).notNull(),
  endpointId: uuid("endpoint_id").notNull(),
  segmentationKey: text("segmentation_key").notNull().default("default"),
  windowStart: timestamp("window_start", { withTimezone: true }).notNull(),
  windowEnd: timestamp("window_end", { withTimezone: true }).notNull(),
  sampleCount: integer("sample_count").notNull(),
  features: jsonb("features").notNull(),
  modelVersion: text("model_version").notNull().default("1.0.0"),
  computedAt: timestamp("computed_at", { withTimezone: true }).notNull().defaultNow(),
});

export type FeatureVector = typeof featureVectors.$inferSelect;
export type NewFeatureVector = typeof featureVectors.$inferInsert;
