import { drizzle } from "drizzle-orm/node-postgres";
import pkg from "pg";
const { Pool } = pkg;
import "dotenv/config";
import * as schema from "./schema/index.js";

const pool = new Pool({
  connectionString:
    process.env.DATABASE_URL ||
    "postgresql://cadence:devpassword@localhost:5432/cadence_dev",
});

export const db = drizzle(pool, { schema });
