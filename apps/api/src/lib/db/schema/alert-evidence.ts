import { pgTable, uuid, text, numeric, timestamp } from "drizzle-orm/pg-core";
import { alerts } from "./alerts.js";
import { tstzrange } from "./custom-types.js";

export const alertEvidence = pgTable("alert_evidence", {
  id: uuid("id").primaryKey().defaultRandom(),
  alertId: uuid("alert_id")
    .notNull()
    .references(() => alerts.id, { onDelete: "cascade" }),
  featureName: text("feature_name").notNull(),
  baselineValue: numeric("baseline_value"),
  observedValue: numeric("observed_value"),
  deviationZ: numeric("deviation_z"),
  deviationPct: numeric("deviation_pct"),
  timeWindow: tstzrange("time_window"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type AlertEvidence = typeof alertEvidence.$inferSelect;
export type NewAlertEvidence = typeof alertEvidence.$inferInsert;
