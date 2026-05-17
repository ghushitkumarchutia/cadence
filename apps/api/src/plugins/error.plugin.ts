import fp from "fastify-plugin";
import { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { AppError } from "../lib/errors.js";

export default fp(async (app: FastifyInstance) => {
  app.setErrorHandler(
    (error: Error & { statusCode?: number; validation?: unknown[] }, request: FastifyRequest, reply: FastifyReply) => {
      if (error instanceof AppError) {
        return reply.status(error.statusCode).send({
          error: error.message,
          code: error.code,
          statusCode: error.statusCode,
        });
      }

      if (error.validation) {
        return reply.status(400).send({
          error: "Validation Error",
          code: "VALIDATION_ERROR",
          statusCode: 400,
          details: error.validation,
        });
      }

      const statusCode = error.statusCode ?? 500;

      if (statusCode >= 500) {
        request.log.error({ err: error, reqId: request.id }, error.message);
      }

      return reply.status(statusCode).send({
        error: statusCode >= 500 ? "Internal Server Error" : error.message,
        code: statusCode >= 500 ? "INTERNAL_ERROR" : "REQUEST_ERROR",
        statusCode,
      });
    },
  );
});
