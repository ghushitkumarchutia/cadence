import {
  pgTable,
  uuid,
  text,
  jsonb,
  timestamp,
  bigint,
  unique,
} from "drizzle-orm/pg-core";
import { projects } from "./projects.js";

export const endpoints = pgTable(
  "endpoints",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    projectId: uuid("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    routeTemplate: text("route_template").notNull(),
    method: text("method").notNull(),
    displayName: text("display_name"),
    config: jsonb("config").notNull().default({}),
    maturityState: text("maturity_state").notNull().default("initializing"),
    observationCount: bigint("observation_count", { mode: "number" })
      .notNull()
      .default(0),
    lastObservedAt: timestamp("last_observed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (table) => [
    unique("uq_endpoints_project_route_method").on(
      table.projectId,
      table.routeTemplate,
      table.method,
    ),
  ],
);

export type Endpoint = typeof endpoints.$inferSelect;
export type NewEndpoint = typeof endpoints.$inferInsert;
