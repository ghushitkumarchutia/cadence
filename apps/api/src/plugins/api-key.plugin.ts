import fp from "fastify-plugin";
import { createHash } from "node:crypto";
import { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { eq, and, isNull } from "drizzle-orm";
import { db } from "../lib/db/client.js";
import { apiKeys } from "../lib/db/schema/index.js";
import { redis, CACHE_KEYS, CACHE_TTL } from "../lib/redis/client.js";

export interface ApiKeyContext {
  orgId: string;
  projectId: string | null;
  apiKeyId: string;
}

declare module "fastify" {
  interface FastifyRequest {
    apiKeyContext: ApiKeyContext | null;
  }
  interface FastifyInstance {
    authenticateApiKey: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }
}

export default fp(async (app: FastifyInstance) => {
  app.decorateRequest("apiKeyContext", null);

  app.decorate("authenticateApiKey", async (request: FastifyRequest, reply: FastifyReply) => {
    const rawKey = request.headers["x-api-key"] as string | undefined;

    if (!rawKey || !rawKey.startsWith("cad_live_")) {
      return reply.status(401).send({
        error: "Valid API key required",
        code: "API_KEY_REQUIRED",
        statusCode: 401,
      });
    }

    const keyHash = createHash("sha256").update(rawKey).digest("hex");

    const cached = await redis.get(CACHE_KEYS.apiKey(keyHash));
    if (cached) {
      request.apiKeyContext = JSON.parse(cached) as ApiKeyContext;
      return;
    }

    const [record] = await db
      .select()
      .from(apiKeys)
      .where(and(eq(apiKeys.keyHash, keyHash), isNull(apiKeys.revokedAt)))
      .limit(1);

    if (!record) {
      return reply.status(401).send({
        error: "Invalid API key",
        code: "INVALID_API_KEY",
        statusCode: 401,
      });
    }

    if (record.expiresAt && record.expiresAt < new Date()) {
      return reply.status(401).send({
        error: "API key expired",
        code: "API_KEY_EXPIRED",
        statusCode: 401,
      });
    }

    const context: ApiKeyContext = {
      orgId: record.orgId,
      projectId: record.projectId,
      apiKeyId: record.id,
    };

    await redis.set(CACHE_KEYS.apiKey(keyHash), JSON.stringify(context), "EX", CACHE_TTL.API_KEY);

    db.update(apiKeys)
      .set({ lastUsedAt: new Date() })
      .where(eq(apiKeys.id, record.id))
      .execute()
      .catch(() => {});

    request.apiKeyContext = context;
  });
});
