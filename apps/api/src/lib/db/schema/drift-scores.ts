import { pgTable, uuid, text, jsonb, timestamp, numeric, boolean } from "drizzle-orm/pg-core";

// Note: This must be converted to a hypertable via custom SQL migration:
// SELECT create_hypertable('drift_scores', 'time', chunk_time_interval => INTERVAL '1 day');
// SELECT add_retention_policy('drift_scores', INTERVAL '365 days');
export const driftScores = pgTable("drift_scores", {
  time: timestamp("time", { withTimezone: true }).notNull(),
  endpointId: uuid("endpoint_id").notNull(),
  segmentationKey: text("segmentation_key").notNull().default("default"),
  score: numeric("score", { precision: 8, scale: 4 }).notNull(),
  components: jsonb("components").notNull(),
  alertTriggered: boolean("alert_triggered").notNull().default(false),
  alertId: uuid("alert_id"),
  modelVersion: text("model_version").notNull(),
  baselineSnapshotTime: timestamp("baseline_snapshot_time", { withTimezone: true }),
});

export type DriftScore = typeof driftScores.$inferSelect;
export type NewDriftScore = typeof driftScores.$inferInsert;
