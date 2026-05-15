import { pgTable, uuid, timestamp, integer, numeric } from "drizzle-orm/pg-core";

// Note: This must be converted to a hypertable via custom SQL migration:
// SELECT create_hypertable('ingestion_metrics', 'time', chunk_time_interval => INTERVAL '1 hour');
export const ingestionMetrics = pgTable("ingestion_metrics", {
  time: timestamp("time", { withTimezone: true }).notNull(),
  endpointId: uuid("endpoint_id").notNull(),
  observationsCount: integer("observations_count").notNull().default(0),
  errorsCount: integer("errors_count").notNull().default(0),
  avgLatencyMs: numeric("avg_latency_ms", { precision: 8, scale: 2 }),
  p95LatencyMs: numeric("p95_latency_ms", { precision: 8, scale: 2 }),
});

export type IngestionMetric = typeof ingestionMetrics.$inferSelect;
export type NewIngestionMetric = typeof ingestionMetrics.$inferInsert;
