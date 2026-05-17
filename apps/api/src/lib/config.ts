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
    jwtSecret:
      process.env.JWT_SECRET ||
      "263f9cdf204809fdcd881fcc3048f48c082ff68e221b1d9cf5243d440979e4e58ecd25ada7a030419a5ea8ffb2b85e1a7d743d8c8eb173497fd2a926b406aef2",
    refreshTokenSecret:
      process.env.REFRESH_TOKEN_SECRET ||
      "8788c960422c59039dbc6c2f74ad1bcdcb5fba069523518b650971ea58426b8a4405faece6dcd7c00f043401cc6d2f3610477fe00020035addf8d62fd3161a0a",
  },

  intelligence: {
    apiUrl: process.env.INTELLIGENCE_API_URL || "http://localhost:8000",
  },
} as const;
