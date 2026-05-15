import "dotenv/config";

export const config = {
  port: parseInt(process.env.PORT || "3001", 10),
  host: "0.0.0.0",
  nodeEnv: process.env.NODE_ENV || "development",
  logLevel: process.env.LOG_LEVEL || "info",

  database: {
    url:
      process.env.DATABASE_URL ||
      "postgresql://cadence:devpassword@localhost:5432/cadence_dev",
  },

  redis: {
    url: process.env.REDIS_URL || "redis://localhost:6379",
  },

  auth: {
    jwtSecret: process.env.JWT_SECRET || "change-this-to-a-256-bit-random-secret-in-production",
    refreshTokenSecret:
      process.env.REFRESH_TOKEN_SECRET ||
      "change-this-to-a-different-256-bit-random-secret",
  },

  intelligence: {
    apiUrl: process.env.INTELLIGENCE_API_URL || "http://localhost:8000",
  },
} as const;
