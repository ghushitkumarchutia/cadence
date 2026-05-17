import { FastifyPluginAsync } from "fastify";
import websocket from "@fastify/websocket";
import { redis, STREAMS } from "../lib/redis/client.js";

const DRIFT_POLL_MS = 2000;
const ALERT_POLL_MS = 2000;

const wsPlugin: FastifyPluginAsync = async (app) => {
  await app.register(websocket);

  app.get(
    "/ws/drift",
    { websocket: true },
    (connection) => {
      let lastId = "$";
      let active = true;

      const poll = async () => {
        while (active) {
          try {
            const results = await redis.xread(
              "COUNT",
              "10",
              "BLOCK",
              String(DRIFT_POLL_MS),
              "STREAMS",
              STREAMS.DRIFT_SCORES,
              lastId,
            );

            if (!results) continue;

            for (const streamData of results as [string, [string, string[]][]][]) {
              for (const msg of streamData[1]) {
                lastId = msg[0];
                const fields = msg[1];
                const event: Record<string, string> = {};
                for (let i = 0; i < fields.length; i += 2) {
                  const key = fields[i];
                  if (key !== undefined) event[key] = fields[i + 1] ?? "";
                }
                connection.socket.send(JSON.stringify({
                  type: "drift_score",
                  data: {
                    endpointId: event.endpoint_id,
                    driftScore: Number(event.drift_score || 0),
                    severity: event.severity,
                    alertType: event.alert_type,
                    confidence: event.confidence_state,
                    timestamp: event.timestamp,
                  },
                }));
              }
            }
          } catch {
            if (active) await new Promise((r) => setTimeout(r, 1000));
          }
        }
      };

      poll();

      connection.socket.on("close", () => {
        active = false;
      });
    },
  );

  app.get(
    "/ws/alerts",
    { websocket: true },
    (connection) => {
      let lastId = "$";
      let active = true;

      const poll = async () => {
        while (active) {
          try {
            const results = await redis.xread(
              "COUNT",
              "10",
              "BLOCK",
              String(ALERT_POLL_MS),
              "STREAMS",
              STREAMS.DRIFT_SCORES,
              lastId,
            );

            if (!results) continue;

            for (const streamData of results as [string, [string, string[]][]][]) {
              for (const msg of streamData[1]) {
                lastId = msg[0];
                const fields = msg[1];
                const event: Record<string, string> = {};
                for (let i = 0; i < fields.length; i += 2) {
                  const key = fields[i];
                  if (key !== undefined) event[key] = fields[i + 1] ?? "";
                }

                if (event.severity === "high" || event.severity === "critical") {
                  connection.socket.send(JSON.stringify({
                    type: "alert",
                    data: {
                      endpointId: event.endpoint_id,
                      driftScore: Number(event.drift_score || 0),
                      severity: event.severity,
                      alertType: event.alert_type,
                      summary: event.summary,
                      timestamp: event.timestamp,
                    },
                  }));
                }
              }
            }
          } catch {
            if (active) await new Promise((r) => setTimeout(r, 1000));
          }
        }
      };

      poll();

      connection.socket.on("close", () => {
        active = false;
      });
    },
  );
};

export default wsPlugin;
