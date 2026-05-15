import { relations } from "drizzle-orm";
import { organizations } from "./organizations.js";
import { users } from "./users.js";
import { projects } from "./projects.js";
import { endpoints } from "./endpoints.js";
import { apiKeys } from "./api-keys.js";
import { refreshTokens } from "./refresh-tokens.js";
import { deployments } from "./deployments.js";
import { alerts } from "./alerts.js";
import { alertEvidence } from "./alert-evidence.js";
import { suppressionWindows } from "./suppression-windows.js";
import { notificationChannels } from "./notification-channels.js";

export const organizationsRelations = relations(organizations, ({ many }) => ({
  users: many(users),
  projects: many(projects),
  apiKeys: many(apiKeys),
  notificationChannels: many(notificationChannels),
}));

export const usersRelations = relations(users, ({ one, many }) => ({
  organization: one(organizations, {
    fields: [users.orgId],
    references: [organizations.id],
  }),
  refreshTokens: many(refreshTokens),
}));

export const projectsRelations = relations(projects, ({ one, many }) => ({
  organization: one(organizations, {
    fields: [projects.orgId],
    references: [organizations.id],
  }),
  endpoints: many(endpoints),
  deployments: many(deployments),
}));

export const endpointsRelations = relations(endpoints, ({ one, many }) => ({
  project: one(projects, {
    fields: [endpoints.projectId],
    references: [projects.id],
  }),
  alerts: many(alerts),
  suppressionWindows: many(suppressionWindows),
}));

export const apiKeysRelations = relations(apiKeys, ({ one }) => ({
  organization: one(organizations, {
    fields: [apiKeys.orgId],
    references: [organizations.id],
  }),
  project: one(projects, {
    fields: [apiKeys.projectId],
    references: [projects.id],
  }),
}));

export const refreshTokensRelations = relations(refreshTokens, ({ one }) => ({
  user: one(users, {
    fields: [refreshTokens.userId],
    references: [users.id],
  }),
}));

export const deploymentsRelations = relations(deployments, ({ one, many }) => ({
  project: one(projects, {
    fields: [deployments.projectId],
    references: [projects.id],
  }),
  alerts: many(alerts),
}));

export const alertsRelations = relations(alerts, ({ one, many }) => ({
  endpoint: one(endpoints, {
    fields: [alerts.endpointId],
    references: [endpoints.id],
  }),
  deployment: one(deployments, {
    fields: [alerts.deploymentId],
    references: [deployments.id],
  }),
  acknowledger: one(users, {
    fields: [alerts.acknowledgedBy],
    references: [users.id],
  }),
  evidence: many(alertEvidence),
}));

export const alertEvidenceRelations = relations(alertEvidence, ({ one }) => ({
  alert: one(alerts, {
    fields: [alertEvidence.alertId],
    references: [alerts.id],
  }),
}));

export const suppressionWindowsRelations = relations(
  suppressionWindows,
  ({ one }) => ({
    endpoint: one(endpoints, {
      fields: [suppressionWindows.endpointId],
      references: [endpoints.id],
    }),
    creator: one(users, {
      fields: [suppressionWindows.createdBy],
      references: [users.id],
    }),
  }),
);

export const notificationChannelsRelations = relations(
  notificationChannels,
  ({ one }) => ({
    organization: one(organizations, {
      fields: [notificationChannels.orgId],
      references: [organizations.id],
    }),
  }),
);
