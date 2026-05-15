import { pgTable, uuid, text, numeric, timestamp } from "drizzle-orm/pg-core";
import { endpoints } from "./endpoints.js";
import { deployments } from "./deployments.js";
import { users } from "./users.js";

export const alerts = pgTable("alerts", {
  id: uuid("id").primaryKey().defaultRandom(),
  endpointId: uuid("endpoint_id")
    .notNull()
    .references(() => endpoints.id, { onDelete: "cascade" }),
  alertType: text("alert_type").notNull(),
  severity: text("severity").notNull(),
  confidence: text("confidence").notNull(),
  confidenceScore: numeric("confidence_score", { precision: 5, scale: 4 }).notNull(),
  driftScore: numeric("drift_score", { precision: 8, scale: 4 }).notNull(),
  status: text("status").notNull().default("open"),
  segmentationKey: text("segmentation_key"),
  deploymentId: uuid("deployment_id").references(() => deployments.id),
  summary: text("summary").notNull(),
  resolvedAt: timestamp("resolved_at", { withTimezone: true }),
  acknowledgedBy: uuid("acknowledged_by").references(() => users.id),
  acknowledgedAt: timestamp("acknowledged_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type Alert = typeof alerts.$inferSelect;
export type NewAlert = typeof alerts.$inferInsert;
