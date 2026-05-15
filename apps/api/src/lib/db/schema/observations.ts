import { pgTable, uuid, text, jsonb, timestamp, smallint, integer } from "drizzle-orm/pg-core";

// Note: This must be converted to a hypertable via custom SQL migration:
// SELECT create_hypertable('observations', 'time', chunk_time_interval => INTERVAL '1 day');
// SELECT add_retention_policy('observations', INTERVAL '90 days');
// SELECT add_compression_policy('observations', COMPRESS_AFTER => INTERVAL '7 days');
export const observations = pgTable("observations", {
  time: timestamp("time", { withTimezone: true }).notNull(),
  endpointId: uuid("endpoint_id").notNull(),
  requestId: text("request_id"),
  statusCode: smallint("status_code").notNull(),
  latencyMs: integer("latency_ms").notNull(),
  requestSizeBytes: integer("request_size_bytes"),
  responseSizeBytes: integer("response_size_bytes"),
  segmentationKey: text("segmentation_key").notNull().default("default"),
  payloadHash: text("payload_hash"),
  payloadSample: jsonb("payload_sample"),
  region: text("region"),
  deploymentId: uuid("deployment_id"),
  metadata: jsonb("metadata").notNull().default({}),
});

export type Observation = typeof observations.$inferSelect;
export type NewObservation = typeof observations.$inferInsert;
