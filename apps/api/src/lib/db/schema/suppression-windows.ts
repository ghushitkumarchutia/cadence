import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";
import { endpoints } from "./endpoints.js";
import { users } from "./users.js";

export const suppressionWindows = pgTable("suppression_windows", {
  id: uuid("id").primaryKey().defaultRandom(),
  endpointId: uuid("endpoint_id")
    .notNull()
    .references(() => endpoints.id, { onDelete: "cascade" }),
  reason: text("reason").notNull(),
  startsAt: timestamp("starts_at", { withTimezone: true }).notNull(),
  endsAt: timestamp("ends_at", { withTimezone: true }).notNull(),
  createdBy: uuid("created_by").references(() => users.id),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type SuppressionWindow = typeof suppressionWindows.$inferSelect;
export type NewSuppressionWindow = typeof suppressionWindows.$inferInsert;
