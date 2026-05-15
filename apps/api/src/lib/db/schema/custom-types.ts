import { customType } from "drizzle-orm/pg-core";

export const tstzrange = customType<{ data: string; driverData: string }>({
  dataType() {
    return "tstzrange";
  },
});

export const inet = customType<{ data: string; driverData: string }>({
  dataType() {
    return "inet";
  },
});
