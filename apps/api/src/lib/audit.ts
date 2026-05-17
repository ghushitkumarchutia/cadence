import { db } from "./db/client.js";
import { auditLog } from "./db/schema/index.js";

export async function logAudit(params: {
  orgId: string;
  userId?: string;
  action: string;
  resourceId?: string;
  before?: unknown;
  after?: unknown;
  ipAddress?: string;
}): Promise<void> {
  db.insert(auditLog)
    .values({
      orgId: params.orgId,
      userId: params.userId ?? null,
      action: params.action,
      resourceId: params.resourceId ?? null,
      before: params.before ?? null,
      after: params.after ?? null,
      ipAddress: params.ipAddress ?? null,
    })
    .execute()
    .catch(() => {});
}
