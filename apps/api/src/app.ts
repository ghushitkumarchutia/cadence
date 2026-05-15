import Fastify from "fastify";
import cors from "@fastify/cors";
import { TypeBoxTypeProvider } from "@fastify/type-provider-typebox";
import { config } from "./lib/config.js";

export async function buildApp() {
  const app = Fastify({
    logger: {
      level: config.logLevel,
      transport:
        config.nodeEnv === "development"
          ? { target: "pino-pretty" }
          : undefined,
    },
  }).withTypeProvider<TypeBoxTypeProvider>();

  // ─── Plugins ──────────────────────────────────────────────────────────────
  await app.register(cors, {
    origin: true,
    credentials: true,
  });

  // ─── Routes ───────────────────────────────────────────────────────────────
  await app.register(import("./routes/health.js"));

  return app;
}
