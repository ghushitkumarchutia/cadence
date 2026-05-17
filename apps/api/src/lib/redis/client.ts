import { Redis } from "ioredis";
import { config } from "../config.js";

export const redis = new Redis(config.redis.url, {
  maxRetriesPerRequest: null,
  retryStrategy(times: number) {
    const delay = Math.min(times * 50, 2000);
    return delay;
  },
});

export const STREAMS = {
  OBSERVATIONS: "cadence:observations",
  DRIFT_SCORES: "cadence:drift-scores",
  BASELINE_REQUESTS: "cadence:baseline-requests",
  ALERTS: "cadence:alerts",
} as const;

export const CACHE_KEYS = {
  endpoint: (id: string) => `endpoint:${id}`,
  apiKey: (hash: string) => `apikey:${hash}`,
  hotBaseline: (endpointId: string, segKey: string) =>
    `baseline:hot:${endpointId}:${segKey}`,
  suppression: (endpointId: string) => `suppression:${endpointId}`,
  alertDedup: (endpointId: string, alertType: string) =>
    `alert:dedup:${endpointId}:${alertType}`,
  sessionProjects: (userId: string) => `session:${userId}:projects`,
  timeline: (endpointId: string, resolution: string) =>
    `agg:timeline:${endpointId}:${resolution}`,
  maturity: (endpointId: string) => `maturity:${endpointId}`,
} as const;

export const CACHE_TTL = {
  ENDPOINT: 300,
  API_KEY: 3600,
  HOT_BASELINE: 1800,
  SUPPRESSION: 60,
  ALERT_DEDUP: 3600,
  SESSION_PROJECTS: 300,
  TIMELINE: 60,
  MATURITY: 600,
} as const;

export const STREAM_MAX_LEN = 100000;

export async function closeRedis(): Promise<void> {
  await redis.quit();
}
