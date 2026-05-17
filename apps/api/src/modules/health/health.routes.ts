import { FastifyPluginAsync } from "fastify";
import { Type } from "@sinclair/typebox";

const healthRoute: FastifyPluginAsync = async (app) => {
  app.get(
    "/health",
    {
      schema: {
        response: {
          200: Type.Object({
            status: Type.String(),
            timestamp: Type.String(),
            version: Type.String(),
            uptime: Type.Number(),
          }),
        },
      },
    },
    async (_request, _reply) => {
      return {
        status: "ok",
        timestamp: new Date().toISOString(),
        version: "0.0.0",
        uptime: process.uptime(),
      };
    },
  );
};

export default healthRoute;
