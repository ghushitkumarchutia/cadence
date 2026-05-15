import { pgTable, uuid, text, jsonb, timestamp, integer, numeric, boolean } from "drizzle-orm/pg-core";

// Note: This must be converted to a hypertable via custom SQL migration:
// SELECT create_hypertable('baseline_snapshots', 'time', chunk_time_interval => INTERVAL '7 days');
export const baselineSnapshots = pgTable("baseline_snapshots", {
  time: timestamp("time", { withTimezone: true }).notNull(),
  endpointId: uuid("endpoint_id").notNull(),
  segmentationKey: text("segmentation_key").notNull().default("default"),
  windowDays: integer("window_days").notNull().default(7),
  sampleCount: integer("sample_count").notNull(),
  baseline: jsonb("baseline").notNull(),
  confidenceScore: numeric("confidence_score", { precision: 5, scale: 4 }).notNull(),
  maturityState: text("maturity_state").notNull(),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export type BaselineSnapshot = typeof baselineSnapshots.$inferSelect;
export type NewBaselineSnapshot = typeof baselineSnapshots.$inferInsert;
