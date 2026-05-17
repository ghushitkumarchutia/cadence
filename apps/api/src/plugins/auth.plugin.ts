import fp from "fastify-plugin";
import fastifyJwt from "@fastify/jwt";
import { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { config } from "../lib/config.js";

declare module "@fastify/jwt" {
  interface FastifyJWT {
    payload: { userId: string; orgId: string; role: string };
    user: { userId: string; orgId: string; role: string };
  }
}

declare module "fastify" {
  interface FastifyInstance {
    authenticate: (request: FastifyRequest, reply: FastifyReply) => Promise<void>;
  }
}

export default fp(async (app: FastifyInstance) => {
  await app.register(fastifyJwt, {
    secret: config.auth.jwtSecret,
    sign: { expiresIn: "15m" },
  });

  app.decorate("authenticate", async (request: FastifyRequest, reply: FastifyReply) => {
    try {
      await request.jwtVerify();
    } catch {
      return reply.status(401).send({
        error: "Unauthorized",
        code: "UNAUTHORIZED",
        statusCode: 401,
      });
    }
  });
});
