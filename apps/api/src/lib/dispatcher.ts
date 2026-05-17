import { createHmac } from "node:crypto";
import { getActiveChannels } from "../modules/notifications/notification.service.js";

interface AlertPayload {
  alertId: string;
  endpointId: string;
  alertType: string;
  severity: string;
  driftScore: number;
  confidence: string;
  summary: string;
  timestamp: string;
}

export async function dispatchAlertNotifications(
  orgId: string,
  payload: AlertPayload,
): Promise<void> {
  const channels = await getActiveChannels(orgId);
  if (channels.length === 0) return;

  const promises = channels.map((channel) => {
    const config = channel.config as Record<string, unknown>;
    switch (channel.type) {
      case "webhook":
        return deliverWebhook(
          config.url as string,
          config.secret as string | undefined,
          payload,
        );
      case "slack":
        return deliverSlack(config.url as string, payload);
      case "email":
        return Promise.resolve();
      case "pagerduty":
        return deliverPagerDuty(
          config.routingKey as string,
          payload,
        );
      default:
        return Promise.resolve();
    }
  });

  await Promise.allSettled(promises);
}

async function deliverWebhook(
  url: string,
  secret: string | undefined,
  payload: AlertPayload,
): Promise<void> {
  const body = JSON.stringify({
    event: "cadence.alert.created",
    data: payload,
    timestamp: new Date().toISOString(),
  });

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "User-Agent": "Cadence/1.0",
  };

  if (secret) {
    const signature = createHmac("sha256", secret)
      .update(body)
      .digest("hex");
    headers["X-Cadence-Signature"] = `sha256=${signature}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    await fetch(url, {
      method: "POST",
      headers,
      body,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

async function deliverSlack(
  webhookUrl: string,
  payload: AlertPayload,
): Promise<void> {
  const severityEmoji: Record<string, string> = {
    low: "🟡",
    medium: "🟠",
    high: "🔴",
    critical: "🚨",
  };

  const emoji = severityEmoji[payload.severity] ?? "⚠️";
  const body = JSON.stringify({
    blocks: [
      {
        type: "header",
        text: {
          type: "plain_text",
          text: `${emoji} Cadence Alert: ${payload.severity.toUpperCase()}`,
        },
      },
      {
        type: "section",
        fields: [
          { type: "mrkdwn", text: `*Type:*\n${payload.alertType}` },
          { type: "mrkdwn", text: `*Drift Score:*\n${payload.driftScore}` },
          { type: "mrkdwn", text: `*Confidence:*\n${payload.confidence}` },
          { type: "mrkdwn", text: `*Endpoint:*\n${payload.endpointId}` },
        ],
      },
      {
        type: "section",
        text: { type: "mrkdwn", text: `*Summary:*\n${payload.summary}` },
      },
    ],
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

async function deliverPagerDuty(
  routingKey: string,
  payload: AlertPayload,
): Promise<void> {
  const severityMap: Record<string, string> = {
    low: "info",
    medium: "warning",
    high: "error",
    critical: "critical",
  };

  const body = JSON.stringify({
    routing_key: routingKey,
    event_action: "trigger",
    payload: {
      summary: payload.summary,
      severity: severityMap[payload.severity] ?? "warning",
      source: "cadence",
      component: payload.endpointId,
      custom_details: {
        alert_id: payload.alertId,
        drift_score: payload.driftScore,
        alert_type: payload.alertType,
        confidence: payload.confidence,
      },
    },
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    await fetch("https://events.pagerduty.com/v2/enqueue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}
